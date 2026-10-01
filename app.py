from flask import Flask, jsonify, render_template_string
from datetime import datetime, timezone
from urllib.parse import quote, urljoin
from bs4 import BeautifulSoup
from email.utils import parsedate_to_datetime
from difflib import SequenceMatcher
import requests
import time
import re
import xml.etree.ElementTree as ET
import threading
import os
import json
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
}

CACHE = {"time": 0, "data": None}
CACHE_SECONDS = 25
XAU_CACHE = {"time": 0, "data": None}
XAU_CACHE_SECONDS = 60
TREASURY_CACHE = {"time": 0, "data": None}
TREASURY_CACHE_SECONDS = 900
FED_CACHE = {"time": 0, "result": None}
FED_CACHE_SECONDS = 300
FED_AI_CACHE = {"fingerprint": None, "result": None, "time": 0}
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
FED_MAX_DOCUMENTS = 18
FED_DOC_CHAR_LIMIT = 950
FED_MAX_DOCS_PER_SPEAKER = 2

GEO_CACHE = {"time": 0, "result": None}
GEO_CACHE_SECONDS = 300
GEO_AI_CACHE = {"fingerprint": None, "result": None, "time": 0}
GEO_MAX_CANDIDATES = 20
GEO_MAX_EVENTS = 8
TRUMP_TRUTH_ACCOUNT_ID = "107780257626128497"
GEO_GROQ_MODEL = os.environ.get("GEO_GROQ_MODEL", "openai/gpt-oss-20b")

# Hybrid Fed stance sources: official Federal Reserve System sites are primary;
# UtoTimes/UtoFX are secondary for timely same-day quotes/Q&A when official text
# is not yet published. Official sources win on overlapping episodes.
OFFICIAL_REGIONAL_FED_SOURCES = {
    # Current 2026 voting Reserve Bank presidents. Board members are collected
    # directly from federalreserve.gov below.
    "John Williams": {"source": "New York Fed", "archive": "https://www.newyorkfed.org/newsevents/speeches/index", "domain": "newyorkfed.org"},
    "Beth Hammack": {"source": "Cleveland Fed", "archive": "https://www.clevelandfed.org/collections/speeches", "domain": "clevelandfed.org"},
    "Neel Kashkari": {"source": "Minneapolis Fed", "archive": "https://www.minneapolisfed.org/topic/monetary-policy", "domain": "minneapolisfed.org"},
    "Lorie Logan": {"source": "Dallas Fed", "archive": "https://www.dallasfed.org/news/speeches/logan", "domain": "dallasfed.org"},
    "Anna Paulson": {"source": "Philadelphia Fed", "archive": "https://www.philadelphiafed.org/the-economy/speeches-anna-paulson", "domain": "philadelphiafed.org"},
}

ECON_CACHE = {"time": 0, "result": None, "last_2y": None}
ECON_CACHE_SECONDS = 300

# Non-blocking dashboard refresh state. The HTML page should never wait for
# slow external data providers on a cold Render start.
REFRESH_LOCK = threading.Lock()
REFRESH_STATE = {"running": False, "last_error": None, "started": 0}

FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
UTOTIMES_FEEDS = [
    "https://utotimes.com/category/news/eco-dada/feed/",
    "https://utotimes.com/feed/",
]

# Dedicated Fed/central-bank discovery. The general UtoTimes feed can move a Fed
# story out of the newest items quickly, so the Fed engine also watches the
# central-banks category directly.
UTOTIMES_FED_FEEDS = [
    "https://utotimes.com/category/news/centralbanks/feed/",
    "https://utotimes.com/feed/",
]

# =========================================================
# FED CONFIG
# =========================================================

FOMC_VOTERS_2026 = {
    "Kevin Warsh", "John Williams", "Michael Barr", "Michelle Bowman",
    "Lisa Cook", "Beth Hammack", "Philip Jefferson", "Neel Kashkari",
    "Lorie Logan", "Anna Paulson", "Jerome Powell", "Christopher Waller",
}

FED_SPEAKERS = {
    "Kevin Warsh": {"full": ["kevin warsh", "کوین وارش"], "short": ["warsh", "وارش"], "weight": 1.50},
    "John Williams": {"full": ["john williams", "john c. williams", "جان ویلیامز"], "short": ["williams", "ویلیامز"], "weight": 1.35},
    "Philip Jefferson": {"full": ["philip jefferson", "philip n. jefferson", "فیلیپ جفرسون"], "short": ["jefferson", "جفرسون"], "weight": 1.25},
    "Jerome Powell": {"full": ["jerome powell", "jerome h. powell", "جروم پاول"], "short": ["powell", "پاول"], "weight": 1.15},
    "Christopher Waller": {"full": ["christopher waller", "christopher j. waller", "کریستوفر والر"], "short": ["waller", "والر"], "weight": 1.10},
    "Michelle Bowman": {"full": ["michelle bowman", "michelle w. bowman", "میشل بومن"], "short": ["bowman", "بومن"], "weight": 1.10},
    "Lisa Cook": {"full": ["lisa cook", "lisa d. cook", "لیزا کوک"], "short": ["cook", "کوک"], "weight": 1.10},
    "Michael Barr": {"full": ["michael barr", "michael s. barr", "مایکل بار"], "short": ["barr", "بار"], "weight": 1.10},
    "Beth Hammack": {"full": ["beth hammack", "beth m. hammack", "بث همک"], "short": ["hammack", "همک"], "weight": 1.00},
    "Neel Kashkari": {"full": ["neel kashkari", "نیل کشکاری"], "short": ["kashkari", "کشکاری"], "weight": 1.00},
    "Lorie Logan": {"full": ["lorie logan", "لوری لوگان"], "short": ["logan", "لوگان"], "weight": 1.00},
    "Anna Paulson": {"full": ["anna paulson", "آنا پالسون"], "short": ["paulson", "پالسون"], "weight": 1.00},
    "Mary Daly": {"full": ["mary daly", "مری دالی"], "short": ["daly", "دالی"], "weight": 0.75},
    "Austan Goolsbee": {"full": ["austan goolsbee", "آستن گولزبی"], "short": ["goolsbee", "گولزبی"], "weight": 0.75},
    "Thomas Barkin": {"full": ["thomas barkin", "توماس بارکین"], "short": ["barkin", "بارکین"], "weight": 0.75},
    "Susan Collins": {"full": ["susan collins", "سوزان کالینز"], "short": ["collins", "کالینز"], "weight": 0.75},
    "Alberto Musalem": {"full": ["alberto musalem", "آلبرتو موسالم"], "short": ["musalem", "موسالم"], "weight": 0.75},
    "Jeffrey Schmid": {"full": ["jeffrey schmid", "جفری اشمید"], "short": ["schmid", "اشمید"], "weight": 0.75},
}

STRICT_FED_CONTEXT = [
    "federal reserve", "fomc", "fed governor", "fed chair", "fed vice chair",
    "federal reserve bank", "the fed", "u.s. central bank", "us central bank",
    "فدرال رزرو", "عضو فد", "عضو فدرال رزرو", "رئیس فد", "رئیس فدرال رزرو",
    "بانک فدرال رزرو", "کمیته بازار آزاد",
]

HAWKISH_PHRASES = {
    "further tightening": 3.0, "additional tightening": 3.0,
    "further rate increase": 3.0, "additional rate increase": 3.0,
    "need to raise rates": 3.0, "rates may need to rise": 3.0,
    "inflation remains too high": 2.5, "inflation is too high": 2.5,
    "inflation has been too high": 2.5, "upside risks to inflation": 2.0,
    "higher for longer": 2.0, "more restrictive": 2.0,
    "not ready to cut": 2.0, "premature to cut": 2.0,
    "persistent inflation": 1.5, "price pressures remain": 1.5,
    "more work to do": 1.5,
    "تورم همچنان بالاست": 2.5, "تورم هنوز بالاست": 2.5,
    "تورم بیش از حد بالاست": 2.5, "نیاز به افزایش نرخ": 3.0,
    "افزایش بیشتر نرخ": 3.0, "افزایش نرخ بهره": 1.5,
    "نرخ بهره بالاتر": 2.0, "فشار تورمی": 1.5,
    "سیاست انقباضی‌تر": 2.0, "کاهش نرخ زود است": 2.0,
    "برای کاهش نرخ زود است": 2.0,
}

DOVISH_PHRASES = {
    "no urgency": 3.0, "no rush": 3.0, "can be patient": 2.5,
    "policy can be patient": 2.5, "wait and see": 2.0,
    "hold rates": 2.0, "keep rates unchanged": 2.0, "pause rate": 2.0,
    "no need to raise": 3.0, "do not need to raise": 3.0,
    "rate cuts": 2.0, "lower rates": 2.0, "less restrictive": 2.0,
    "labor market cooling": 2.0, "labour market cooling": 2.0,
    "downside risks to employment": 2.0, "inflation has eased": 1.5,
    "disinflation": 1.5,
    "نیازی به عجله": 3.0, "عجله‌ای برای افزایش": 3.0,
    "نیازی به افزایش سریع": 3.0, "نیازی به افزایش": 2.5,
    "صبر کنیم": 2.0, "می‌توانیم صبر کنیم": 2.5,
    "ثابت نگه داشتن نرخ": 2.0, "توقف افزایش نرخ": 2.5,
    "کاهش نرخ بهره": 2.0, "بازار کار ضعیف": 2.0,
    "بازار کار سرد": 2.0, "کاهش تورم": 1.5,
    "تورم کاهش یافته": 1.5, "ریسک اشتغال": 1.5,
}

# =========================================================
# ECONOMIC CONFIG
# direction: +1 means a higher-than-expected actual tends to help gold.
# direction: -1 means a higher-than-expected actual tends to hurt gold.
# =========================================================

EVENT_PROFILES = [
    {"name": "Core PCE", "aliases": ["core pce price index", "شاخص هزینه های مصرف شخصی هسته", "شاخص هزینه‌های مصرف شخصی هسته"], "category": "Inflation", "direction": -1, "scale": 0.10, "immediate_weight": 3.5, "policy_weight": 5.0, "persistence_hours": 336},
    {"name": "Core CPI", "aliases": ["core cpi", "شاخص قیمت مصرف کننده هسته", "شاخص قیمت مصرف‌کننده هسته"], "category": "Inflation", "direction": -1, "scale": 0.10, "immediate_weight": 3.8, "policy_weight": 4.8, "persistence_hours": 336},
    {"name": "Headline CPI", "aliases": ["cpi m/m", "consumer price index", "شاخص قیمت مصرف کننده ایالات متحده", "شاخص قیمت مصرف‌کننده ایالات متحده"], "category": "Inflation", "direction": -1, "scale": 0.10, "immediate_weight": 3.4, "policy_weight": 4.0, "persistence_hours": 240},
    {"name": "Core PPI", "aliases": ["core ppi", "core producer price index", "شاخص قیمت تولیدکننده هسته", "شاخص قیمت تولید کننده هسته"], "category": "Inflation", "direction": -1, "scale": 0.15, "immediate_weight": 2.0, "policy_weight": 2.0, "persistence_hours": 120},
    {"name": "PPI", "aliases": ["producer price index", "ppi m/m", "شاخص قیمت تولیدکننده ایالات متحده", "شاخص قیمت تولید کننده ایالات متحده"], "category": "Inflation", "direction": -1, "scale": 0.15, "immediate_weight": 1.7, "policy_weight": 1.6, "persistence_hours": 96},
    {"name": "ISM Prices Paid", "aliases": ["ism manufacturing prices", "ism prices paid", "مولفه قیمت", "مولفه قیمت ها", "مولفه قیمت‌ها"], "category": "Inflation", "direction": -1, "scale": 2.0, "immediate_weight": 2.5, "policy_weight": 3.0, "persistence_hours": 168},
    {"name": "Nonfarm Payrolls", "aliases": ["non-farm employment change", "nonfarm payrolls", "non-farm payrolls", "تغییرات اشتغال بخش غیرکشاورزی", "اشتغال بخش غیرکشاورزی"], "category": "Labor", "direction": -1, "scale": 50.0, "immediate_weight": 4.0, "policy_weight": 4.5, "persistence_hours": 336},
    {"name": "Unemployment Rate", "aliases": ["unemployment rate", "نرخ بیکاری ایالات متحده", "نرخ بیکاری آمریکا"], "category": "Labor", "direction": +1, "scale": 0.10, "immediate_weight": 3.5, "policy_weight": 4.2, "persistence_hours": 336},
    {"name": "Average Hourly Earnings", "aliases": ["average hourly earnings", "متوسط درآمد ساعتی", "میانگین درآمد ساعتی"], "category": "Labor", "direction": -1, "scale": 0.10, "immediate_weight": 3.0, "policy_weight": 3.8, "persistence_hours": 240},
    {"name": "Initial Jobless Claims", "aliases": ["unemployment claims", "initial jobless claims", "مدعیان بیکاری", "آمار مدعیان بیکاری"], "category": "Labor", "direction": +1, "scale": 10.0, "immediate_weight": 2.3, "policy_weight": 1.2, "persistence_hours": 72},
    {"name": "Continuing Claims", "aliases": ["continuing jobless claims", "continuing claims", "ادامه دار مدعیان بیکاری", "ادامه‌دار مدعیان بیکاری"], "category": "Labor", "direction": +1, "scale": 25.0, "immediate_weight": 1.5, "policy_weight": 1.4, "persistence_hours": 96},
    {"name": "ADP Employment", "aliases": ["adp non-farm employment change", "adp employment", "adp"], "category": "Labor", "direction": -1, "scale": 40.0, "immediate_weight": 1.6, "policy_weight": 1.1, "persistence_hours": 72},
    {"name": "JOLTS", "aliases": ["jolts job openings", "فرصت های شغلی jolts", "فرصت‌های شغلی jolts"], "category": "Labor", "direction": -1, "scale": 250.0, "immediate_weight": 1.8, "policy_weight": 1.8, "persistence_hours": 120},
    {"name": "ISM Manufacturing", "aliases": ["ism manufacturing pmi", "شاخص مدیران خرید بخش تولید ism", "شاخص مدیران خرید تولیدی ism"], "category": "Growth", "direction": -1, "scale": 1.0, "immediate_weight": 2.2, "policy_weight": 1.8, "persistence_hours": 120},
    {"name": "ISM Services", "aliases": ["ism services pmi", "ism non-manufacturing", "شاخص مدیران خرید بخش خدمات ism"], "category": "Growth", "direction": -1, "scale": 1.0, "immediate_weight": 2.5, "policy_weight": 2.2, "persistence_hours": 144},
    {"name": "GDP", "aliases": ["advance gdp", "prelim gdp", "final gdp", "gdp q/q", "تولید ناخالص داخلی ایالات متحده", "تولید ناخالص داخلی آمریکا"], "category": "Growth", "direction": -1, "scale": 0.50, "immediate_weight": 2.0, "policy_weight": 2.0, "persistence_hours": 168},
    {"name": "Core Retail Sales", "aliases": ["core retail sales", "خرده فروشی هسته", "خرده‌فروشی هسته"], "category": "Consumption", "direction": -1, "scale": 0.30, "immediate_weight": 2.2, "policy_weight": 1.8, "persistence_hours": 120},
    {"name": "Retail Sales", "aliases": ["retail sales m/m", "retail sales", "خرده فروشی ایالات متحده", "خرده‌فروشی ایالات متحده"], "category": "Consumption", "direction": -1, "scale": 0.30, "immediate_weight": 2.0, "policy_weight": 1.6, "persistence_hours": 96},
    {"name": "Consumer Confidence", "aliases": ["cb consumer confidence", "consumer confidence", "اعتماد مصرف کننده", "اعتماد مصرف‌کننده"], "category": "Consumption", "direction": -1, "scale": 3.0, "immediate_weight": 1.1, "policy_weight": 0.8, "persistence_hours": 72},
    {"name": "Consumer Sentiment", "aliases": ["consumer sentiment", "احساسات مصرف کننده", "تمایلات مصرف کننده"], "category": "Consumption", "direction": -1, "scale": 2.0, "immediate_weight": 1.1, "policy_weight": 0.8, "persistence_hours": 72},
]

# =========================================================
# GENERIC HELPERS
# =========================================================

PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def clamp(value, minimum=0, maximum=100):
    return max(minimum, min(maximum, value))


def safe_round(value, digits=2):
    try:
        if value is None:
            return None
        return round(float(value), digits)
    except Exception:
        return None


def normalize_digits(text):
    return str(text or "").translate(PERSIAN_DIGITS)


def normalize_text(text):
    text = normalize_digits(text).lower()
    text = text.replace("ي", "ی").replace("ك", "ک")
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[\u200c\u200f\u202a-\u202e]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def token_pattern(alias):
    return r"(?<![\w\u0600-\u06FF])" + re.escape(alias.lower()) + r"(?![\w\u0600-\u06FF])"


def parse_date(value):
    if not value:
        return None
    value = str(value).strip()
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def hours_since(value):
    dt = parse_date(value)
    if not dt:
        return None
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0)


def parse_number(value):
    if value is None:
        return None
    text = normalize_digits(value).strip().replace(",", "").replace("%", "").replace("$", "")
    if not text:
        return None
    trailing_minus = text.endswith("-")
    if trailing_minus:
        text = text[:-1].strip()
    mult = 1.0
    upper = text.upper()
    if upper.endswith("K"):
        text = text[:-1]
    elif upper.endswith("M"):
        mult = 1000.0
        text = text[:-1]
    elif upper.endswith("B"):
        mult = 1000000.0
        text = text[:-1]
    try:
        val = float(text) * mult
        return -val if trailing_minus else val
    except Exception:
        return None

# =========================================================
# MARKET DATA
# =========================================================


def yahoo_market(symbol):
    try:
        encoded = quote(symbol, safe="")
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?interval=5m&range=1d"
        r = requests.get(url, headers=HEADERS, timeout=8)
        r.raise_for_status()
        result = r.json()["chart"]["result"][0]
        meta = result["meta"]
        price = meta.get("regularMarketPrice")
        previous = meta.get("chartPreviousClose") or meta.get("previousClose")
        change = None
        change_pct = None
        if price is not None and previous:
            change = price - previous
            change_pct = (change / previous) * 100
        return {
            "price": safe_round(price, 3),
            "previous": safe_round(previous, 3),
            "change": safe_round(change, 3),
            "change_pct": safe_round(change_pct, 2),
            "ok": True,
        }
    except Exception:
        return {"price": None, "previous": None, "change": None, "change_pct": None, "ok": False}




def _extract_marketwatch_yield(html):
    """Best-effort parser for MarketWatch Treasury pages.

    Returns (current_yield, previous_close). Both are percentage-point values,
    e.g. 4.78 means 4.78%.
    """
    soup = BeautifulSoup(html, "html.parser")

    current = None
    previous = None

    # Current quote: MarketWatch commonly exposes the live number in bg-quote.
    selectors = [
        "bg-quote.value",
        ".intraday__price bg-quote",
        ".intraday__data bg-quote",
        "bg-quote",
    ]
    for selector in selectors:
        node = soup.select_one(selector)
        if not node:
            continue
        text = node.get_text(" ", strip=True)
        m = re.search(r"([0-9]+(?:\.[0-9]+)?)", text)
        if m:
            try:
                value = float(m.group(1))
                if 0 < value < 20:
                    current = value
                    break
            except Exception:
                pass

    # Previous close from labelled key/value rows.
    for label_node in soup.find_all(string=re.compile(r"Previous\s+Close", re.I)):
        parent = label_node.parent
        if parent:
            container = parent.parent if parent.parent else parent
            text = container.get_text(" ", strip=True)
            m = re.search(r"Previous\s+Close\s*([0-9]+(?:\.[0-9]+)?)", text, re.I)
            if m:
                try:
                    value = float(m.group(1))
                    if 0 < value < 20:
                        previous = value
                        break
                except Exception:
                    pass

    # Regex fallbacks against full page text / HTML.
    page_text = soup.get_text(" ", strip=True)

    if current is None:
        patterns = [
            r"Yield\s*(?:\|\s*)?(?:As of|At close|Market Open)?[^0-9]{0,80}([0-9]+\.[0-9]+)\s*%",
            r'"price"\s*:\s*"?(?:\$)?([0-9]+\.[0-9]+)',
            r'"value"\s*:\s*"([0-9]+\.[0-9]+)"',
        ]
        for pattern in patterns:
            m = re.search(pattern, html, re.I | re.S) or re.search(pattern, page_text, re.I | re.S)
            if m:
                try:
                    value = float(m.group(1))
                    if 0 < value < 20:
                        current = value
                        break
                except Exception:
                    pass

    if previous is None:
        patterns = [
            r"Previous\s+Close[^0-9]{0,40}([0-9]+\.[0-9]+)",
            r"Prev(?:ious)?\s+Close[^0-9]{0,40}([0-9]+\.[0-9]+)",
        ]
        for pattern in patterns:
            m = re.search(pattern, page_text, re.I | re.S) or re.search(pattern, html, re.I | re.S)
            if m:
                try:
                    value = float(m.group(1))
                    if 0 < value < 20:
                        previous = value
                        break
                except Exception:
                    pass

    return current, previous


def _marketwatch_treasury_quote(tenor):
    """Live Treasury yield + previous close from MarketWatch, no API key."""
    slug_map = {
        "2Y": "tmubmusd02y",
        "10Y": "tmubmusd10y",
        "30Y": "tmubmusd30y",
    }
    slug = slug_map[tenor]
    url = f"https://www.marketwatch.com/investing/bond/{slug}?countrycode=bx"

    headers = dict(HEADERS)
    headers.update({
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.marketwatch.com/",
    })

    r = requests.get(url, headers=headers, timeout=(3.0, 5.0))
    r.raise_for_status()

    current, previous = _extract_marketwatch_yield(r.text)
    if current is None or previous is None:
        raise ValueError(f"Could not parse MarketWatch {tenor} yield")

    change_bps = (current - previous) * 100.0

    return {
        "price": safe_round(current, 3),
        "previous": safe_round(previous, 3),
        "change": safe_round(current - previous, 3),
        "change_pct": safe_round(((current - previous) / previous) * 100, 2) if previous else None,
        "change_bps": safe_round(change_bps, 1),
        "ok": True,
        "source": "MarketWatch",
        "tenor": tenor,
    }


def _fred_series_latest(series_id):
    """Daily constant-maturity Treasury yield from FRED; no API key required."""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    r = requests.get(url, headers=HEADERS, timeout=(3.0, 6.0))
    r.raise_for_status()

    rows = []
    for raw in r.text.splitlines()[1:]:
        parts = raw.strip().split(",")
        if len(parts) < 2:
            continue
        date_str, value_str = parts[0].strip(), parts[1].strip()
        if value_str in ("", "."):
            continue
        try:
            rows.append((date_str, float(value_str)))
        except Exception:
            continue

    if len(rows) < 2:
        raise ValueError(f"Not enough FRED data for {series_id}")

    current_date, current = rows[-1]
    previous_date, previous = rows[-2]
    return current, previous, current_date, previous_date


def _fred_treasury_curve():
    series_map = {
        "2Y": "DGS2",
        "10Y": "DGS10",
        "30Y": "DGS30",
    }
    curve = {}

    for tenor, series_id in series_map.items():
        current, previous, current_date, previous_date = _fred_series_latest(series_id)
        curve[tenor] = {
            "price": safe_round(current, 3),
            "previous": safe_round(previous, 3),
            "change": safe_round(current - previous, 3),
            "change_pct": safe_round(((current - previous) / previous) * 100, 2) if previous else None,
            "change_bps": safe_round((current - previous) * 100.0, 1),
            "ok": True,
            "source": "FRED Daily",
            "tenor": tenor,
            "as_of": current_date,
            "previous_as_of": previous_date,
        }

    return curve


def _treasury_official_curve():
    """Latest official U.S. Treasury nominal CMT curve from Treasury.gov.

    This source is free, requires no API key, and provides 2Y/10Y/30Y from
    one internally consistent curve. Values are daily official closes, not
    intraday quotes.
    """
    year = datetime.now(timezone.utc).year
    url = (
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
        f"TextView?type=daily_treasury_yield_curve&field_tdr_date_value={year}"
    )
    headers = dict(HEADERS)
    headers.update({
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    r = requests.get(url, headers=headers, timeout=(3.0, 8.0))
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    rows = []
    for table in soup.find_all("table"):
        header_cells = table.find_all("th")
        headers_text = [re.sub(r"\\s+", " ", h.get_text(" ", strip=True)).strip() for h in header_cells]
        normalized = [h.lower().replace("yr", "yr").strip() for h in headers_text]

        def find_col(candidates):
            for i, h in enumerate(normalized):
                compact = re.sub(r"\\s+", " ", h)
                if compact in candidates:
                    return i
            return None

        date_i = find_col({"date"})
        y2_i = find_col({"2 yr", "2 year", "2-year"})
        y10_i = find_col({"10 yr", "10 year", "10-year"})
        y30_i = find_col({"30 yr", "30 year", "30-year"})
        if None in (date_i, y2_i, y10_i, y30_i):
            continue

        for tr in table.find_all("tr"):
            cells = tr.find_all("td")
            if not cells:
                continue
            values = [re.sub(r"\\s+", " ", c.get_text(" ", strip=True)).strip() for c in cells]
            if max(date_i, y2_i, y10_i, y30_i) >= len(values):
                continue
            try:
                dt = datetime.strptime(values[date_i], "%m/%d/%Y").replace(tzinfo=timezone.utc)
                y2 = float(values[y2_i])
                y10 = float(values[y10_i])
                y30 = float(values[y30_i])
            except Exception:
                continue
            rows.append((dt, y2, y10, y30))

    # Some Treasury page variants expose a duplicated/complex header. Fallback:
    # identify rows by date and use the standard nominal CMT column ordering.
    if len(rows) < 2:
        for tr in soup.find_all("tr"):
            cells = [re.sub(r"\\s+", " ", c.get_text(" ", strip=True)).strip() for c in tr.find_all("td")]
            if len(cells) < 14:
                continue
            try:
                dt = datetime.strptime(cells[0], "%m/%d/%Y").replace(tzinfo=timezone.utc)
            except Exception:
                continue
            # Treasury nominal table commonly ends with: 1Y, 2Y, 3Y, 5Y, 7Y, 10Y, 20Y, 30Y.
            numeric = []
            for value in cells[1:]:
                try:
                    numeric.append(float(value))
                except Exception:
                    numeric.append(None)
            valid_tail = [v for v in numeric if v is not None]
            if len(valid_tail) >= 8:
                try:
                    y2, y10, y30 = valid_tail[-7], valid_tail[-3], valid_tail[-1]
                    rows.append((dt, y2, y10, y30))
                except Exception:
                    pass

    if len(rows) < 2:
        raise ValueError("Could not parse official Treasury yield curve")

    # Remove duplicate dates and sort chronologically.
    by_date = {}
    for row in rows:
        by_date[row[0].date().isoformat()] = row
    ordered = sorted(by_date.values(), key=lambda x: x[0])
    current = ordered[-1]
    previous = ordered[-2]

    labels = {"2Y": 1, "10Y": 2, "30Y": 3}
    curve = {}
    for tenor, idx in labels.items():
        cur = float(current[idx])
        prev = float(previous[idx])
        curve[tenor] = {
            "price": safe_round(cur, 3),
            "previous": safe_round(prev, 3),
            "change": safe_round(cur - prev, 3),
            "change_pct": safe_round(((cur - prev) / prev) * 100, 2) if prev else None,
            "change_bps": safe_round((cur - prev) * 100.0, 1),
            "ok": True,
            "source": "U.S. Treasury Daily CMT",
            "tenor": tenor,
            "as_of": current[0].date().isoformat(),
            "previous_as_of": previous[0].date().isoformat(),
            "intraday": False,
        }
    return curve


def treasury_spot_curve():
    """Return 2Y/10Y/30Y Treasury yields from one consistent source.

    Primary: official U.S. Treasury Daily CMT curve.
    Fallback: FRED Daily. Both are daily closes and therefore are not used as
    an intraday 2Y confirmation signal for a just-released economic report.
    """
    now = time.time()
    if (
        TREASURY_CACHE["data"] is not None
        and now - TREASURY_CACHE["time"] < TREASURY_CACHE_SECONDS
    ):
        return TREASURY_CACHE["data"]

    try:
        curve = _treasury_official_curve()
    except Exception:
        try:
            curve = _fred_treasury_curve()
            for item in curve.values():
                item["intraday"] = False
        except Exception:
            curve = {
                tenor: {
                    "price": None, "previous": None, "change": None,
                    "change_pct": None, "change_bps": None, "ok": False,
                    "source": "Unavailable", "tenor": tenor,
                    "as_of": None, "previous_as_of": None, "intraday": False,
                }
                for tenor in ("2Y", "10Y", "30Y")
            }

    TREASURY_CACHE["time"] = now
    TREASURY_CACHE["data"] = curve
    return curve

def xau_spot_market():

    """Fetch live XAU/USD spot from XAUS.com (free, no API key).

    The live spot price comes from /api/v1/spot. Daily change is calculated
    against the most recent completed daily close from /api/v1/history.
    """
    now = time.time()
    if XAU_CACHE["data"] is not None and now - XAU_CACHE["time"] < XAU_CACHE_SECONDS:
        return XAU_CACHE["data"]

    try:
        fresh = int(now // 60)
        spot_url = f"https://xaus.com/api/v1/spot?compact=1&fresh={fresh}"
        r = requests.get(spot_url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        spot = r.json()

        price = spot.get("spot_usd_oz")
        if price is None:
            price = (spot.get("xau") or {}).get("price")

        previous = None
        try:
            hr = requests.get("https://xaus.com/api/v1/history", headers=HEADERS, timeout=10)
            hr.raise_for_status()
            history = hr.json()
            points = history.get("points") or []
            valid = []
            for point in points:
                d = point.get("d")
                c = point.get("c")
                if d and c is not None:
                    try:
                        valid.append((str(d), float(c)))
                    except Exception:
                        pass
            if valid:
                valid.sort(key=lambda x: x[0])
                today = datetime.now(timezone.utc).date().isoformat()
                completed = [row for row in valid if row[0] < today]
                if completed:
                    previous = completed[-1][1]
                elif len(valid) >= 2:
                    previous = valid[-2][1]
                else:
                    previous = valid[-1][1]
        except Exception:
            previous = None

        change = None
        change_pct = None
        if price is not None and previous:
            change = float(price) - float(previous)
            change_pct = (change / float(previous)) * 100

        state = spot.get("data_state") or {}
        result = {
            "price": safe_round(price, 2),
            "previous": safe_round(previous, 2),
            "change": safe_round(change, 2),
            "change_pct": safe_round(change_pct, 2),
            "ok": price is not None,
            "source": "XAUS.com",
            "data_state": state.get("status", "unknown"),
            "as_of": state.get("as_of") or spot.get("price_as_of") or spot.get("updated_at"),
        }
        XAU_CACHE["time"] = now
        XAU_CACHE["data"] = result
        return result
    except Exception:
        result = {
            "price": None,
            "previous": None,
            "change": None,
            "change_pct": None,
            "ok": False,
            "source": "XAUS.com",
            "data_state": "unavailable",
            "as_of": None,
        }
        XAU_CACHE["time"] = now
        XAU_CACHE["data"] = result
        return result

# =========================================================
# NEWS SOURCES
# =========================================================


def get_utofx_news(limit=12):
    try:
        r = requests.get("https://t.me/s/UtoFx", headers=HEADERS, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        messages = []
        for message in soup.select(".tgme_widget_message"):
            text_box = message.select_one(".tgme_widget_message_text")
            if not text_box:
                continue
            text = " ".join(text_box.stripped_strings)
            if not text:
                continue
            date_tag = message.select_one("time")
            link_tag = message.select_one(".tgme_widget_message_date")
            messages.append({
                "source": "UtoFX Telegram",
                "text": text[:1600],
                "date": date_tag.get("datetime") if date_tag else None,
                "link": link_tag.get("href") if link_tag else None,
            })
        return messages[-limit:][::-1]
    except Exception:
        return []


def parse_rss_items(url, limit=20):
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        items = []
        for item in root.findall(".//item")[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            date = (item.findtext("pubDate") or "").strip()
            description = (item.findtext("description") or "").strip()
            encoded = ""
            for child in list(item):
                if child.tag.endswith("encoded") and child.text:
                    encoded = child.text
                    break
            items.append({"source": "UtoTimes", "title": title, "text": title, "date": date, "link": link or None, "content": encoded or description})
        return items
    except Exception:
        return []


def get_utotimes_news(limit=8):
    items = parse_rss_items("https://utotimes.com/feed/", limit=max(limit, 12))
    return items[:limit]


def get_utotimes_fed_news(limit=24):
    """Collect recent Fed-speaker items from UtoTimes, independent of Live News.

    The normal homepage RSS can be crowded by non-Fed headlines within minutes.
    For the Fed engine we therefore read the UtoTimes central-banks category feed
    plus the general feed, then keep only items that identify one of our Fed
    speakers in a strict Federal Reserve context.
    """
    items = []
    seen = set()
    for feed_url in UTOTIMES_FED_FEEDS:
        for item in parse_rss_items(feed_url, limit=max(limit, 36)):
            link = item.get("link")
            if link and link in seen:
                continue

            body = BeautifulSoup(item.get("content") or "", "html.parser").get_text(" ", strip=True)
            combined = f"{item.get('title','')} {body}".strip()
            speaker = detect_speaker(combined, official_source=False)
            if not speaker or not has_strict_fed_context(combined):
                continue

            # If RSS only carries a teaser, fetch the article so the semantic
            # model sees the actual quote/context rather than just a headline.
            page_date = None
            if len(body) < 450 and link:
                page_text, page_date = fetch_page(link)
                if page_text:
                    body = page_text
                    combined = f"{item.get('title','')} {body}".strip()

            if link:
                seen.add(link)
            items.append({
                "source": "UtoTimes",
                "title": item.get("title", ""),
                "text": combined,
                "date": item.get("date") or page_date,
                "link": link,
            })
            if len(items) >= limit:
                return items
    return items


def fetch_page(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        page_date = None
        time_tag = soup.find("time", attrs={"datetime": True})
        if time_tag:
            page_date = time_tag.get("datetime")
        if not page_date:
            meta = soup.find("meta", attrs={"property": "article:published_time"})
            if meta:
                page_date = meta.get("content")
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        main = soup.find("main") or soup.find(id="content") or soup
        text = " ".join(main.stripped_strings)
        return text[:40000], page_date
    except Exception:
        return "", None

# =========================================================
# FED ENGINE — SEMANTIC / WHOLE-MESSAGE ANALYSIS
# =========================================================


def has_strict_fed_context(text):
    lower = normalize_text(text)
    return any(term in lower for term in STRICT_FED_CONTEXT)


def detect_speaker(text, official_source=False):
    """Entity detection only. Keywords are NOT used to score policy stance."""
    lower = normalize_text(text)
    for speaker, info in FED_SPEAKERS.items():
        for alias in info["full"]:
            if re.search(token_pattern(normalize_text(alias)), lower, flags=re.IGNORECASE):
                return speaker
    if official_source or has_strict_fed_context(lower):
        for speaker, info in FED_SPEAKERS.items():
            for alias in info["short"]:
                if re.search(token_pattern(normalize_text(alias)), lower, flags=re.IGNORECASE):
                    return speaker
    return None


def fed_recency_weight(date_value):
    hours = hours_since(date_value)
    if hours is None or hours > 168:
        return 0.0
    if hours <= 24:
        return 1.00
    if hours <= 72:
        return 0.82
    return 0.60


def extract_nyfed_date(url):
    if not url:
        return None
    m = re.search(r"(?:wil|williams)(\d{6})", url.lower())
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1), "%y%m%d").replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        return None


def _fed_raw_document(text, source, date=None, title=None, link=None, official_source=False):
    """Create a raw Fed document. No hawkish/dovish scoring happens here."""
    if not text:
        return None
    if not official_source and not has_strict_fed_context(text):
        return None
    speaker = detect_speaker(text, official_source=official_source)
    if not speaker:
        return None
    if fed_recency_weight(date) <= 0:
        return None
    clean_text = re.sub(r"\s+", " ", str(text)).strip()
    return {
        "speaker": speaker,
        "source": source,
        "date": date,
        "title": (title or clean_text[:180]).strip(),
        "link": link,
        "text": clean_text,
        "voter": speaker in FOMC_VOTERS_2026,
        "official_source": bool(official_source),
    }


def get_board_speech_documents(limit=30):
    items = []
    try:
        r = requests.get("https://www.federalreserve.gov/feeds/speeches.xml", headers=HEADERS, timeout=(3, 8))
        r.raise_for_status()
        root = ET.fromstring(r.content)
        for item in root.findall(".//item")[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            date = (item.findtext("pubDate") or "").strip()
            description = (item.findtext("description") or "").strip()
            if fed_recency_weight(date) <= 0:
                continue
            body, page_date = fetch_page(link) if link else ("", None)
            date = date or page_date
            doc = _fed_raw_document(
                f"{title} {description} {body}",
                source="Federal Reserve", date=date, title=title,
                link=link or None, official_source=True,
            )
            if doc:
                items.append(doc)
    except Exception:
        pass
    return items


def get_williams_speech_documents(limit=12):
    items = []
    try:
        index_url = "https://www.newyorkfed.org/newsevents/speeches/index"
        r = requests.get(index_url, headers=HEADERS, timeout=(3, 8))
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        seen = set()
        for a in soup.find_all("a", href=True):
            label = " ".join(a.stripped_strings)
            href = a.get("href", "")
            if "williams" not in label.lower() or "/newsevents/speeches/2026/" not in href:
                continue
            link = urljoin(index_url, href)
            if link in seen:
                continue
            seen.add(link)
            body, page_date = fetch_page(link)
            date = page_date or extract_nyfed_date(link)
            doc = _fed_raw_document(
                f"{label} {body}", source="New York Fed", date=date,
                title=label, link=link, official_source=True,
            )
            if doc:
                items.append(doc)
            if len(items) >= limit:
                break
    except Exception:
        pass
    return items



MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _visible_date(text):
    """Best-effort parser for dates printed on official Fed archive/detail pages."""
    if not text:
        return None
    t = normalize_digits(str(text))
    # ISO / numeric date first.
    for pat in [r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b"]:
        m = re.search(pat, t)
        if m:
            try:
                if pat.startswith(r"\b(20"):
                    y, mo, d = map(int, m.groups())
                else:
                    mo, d, y = map(int, m.groups())
                return datetime(y, mo, d, 12, 0, tzinfo=timezone.utc).isoformat()
            except Exception:
                pass
    # Month-name dates: September 30, 2026 / Sept. 30, 2026
    m = re.search(r"\b(January|February|March|April|May|June|July|August|September|Sept\.?|October|November|December|Jan\.?|Feb\.?|Mar\.?|Apr\.?|Jun\.?|Jul\.?|Aug\.?|Sep\.?|Oct\.?|Nov\.?|Dec\.?)\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(20\d{2})\b", t, re.I)
    if m:
        key = m.group(1).lower().replace('.', '')
        try:
            return datetime(int(m.group(3)), MONTHS[key], int(m.group(2)), 12, 0, tzinfo=timezone.utc).isoformat()
        except Exception:
            pass
    # Federal Reserve archive style: 10/1/2026 is already handled above.
    return None


def _official_doc_for_speaker(speaker, text, source, date=None, title=None, link=None):
    """Create a document from a speaker-specific official Federal Reserve page."""
    if not text or not speaker:
        return None
    date = date or _visible_date(text)
    if fed_recency_weight(date) <= 0:
        return None
    clean_text = re.sub(r"\s+", " ", str(text)).strip()
    return {
        "speaker": speaker,
        "source": source,
        "date": date,
        "title": (title or clean_text[:180]).strip(),
        "link": link,
        "text": clean_text,
        "voter": speaker in FOMC_VOTERS_2026,
        "official_source": True,
    }


def _is_same_official_domain(url, domain):
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
        return host == domain or host.endswith("." + domain)
    except Exception:
        return False


def _archive_recent_links(speaker, config, limit=8):
    """Discover recent detail links from a speaker-specific official Fed archive page."""
    try:
        r = requests.get(config["archive"], headers=HEADERS, timeout=(3, 8))
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception:
        return []

    found = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(config["archive"], a.get("href", ""))
        if not href or href in seen or not _is_same_official_domain(href, config["domain"]):
            continue
        if href.lower().endswith((".pdf", ".jpg", ".jpeg", ".png", ".zip")):
            continue
        label = " ".join(a.stripped_strings).strip()
        if not label:
            continue

        # Pull a little surrounding text because most official archive pages print
        # the publication date beside the link rather than inside the anchor.
        context = label
        node = a
        for _ in range(3):
            node = getattr(node, "parent", None)
            if not node:
                break
            txt = " ".join(node.stripped_strings)
            if txt:
                context = txt[:1200]
            if _visible_date(context):
                break

        date_hint = _visible_date(context)
        path = href.lower()
        combined = normalize_text(label + " " + context)
        last = speaker.split()[-1].lower()
        pathish = any(k in path for k in ("speech", "speeches", "remarks", "president", "/2026/", "policy"))
        named = last in combined or normalize_text(speaker) in combined
        recent = fed_recency_weight(date_hint) > 0 if date_hint else False

        # Speaker-specific archive pages allow path-based discovery even when the
        # speaker's name is omitted from a compact card. Unknown-date links are
        # kept sparingly and verified on the detail page later.
        if not pathish:
            continue
        if date_hint and not recent:
            continue
        if not named and "2026" not in path and not recent:
            continue

        seen.add(href)
        found.append({"link": href, "title": label[:260], "date_hint": date_hint})

    found.sort(key=lambda x: parse_date(x.get("date_hint")) or datetime(2000,1,1,tzinfo=timezone.utc), reverse=True)
    # Keep recent dated links plus only a few unknown-date links for verification.
    dated = [x for x in found if x.get("date_hint")]
    unknown = [x for x in found if not x.get("date_hint")][:3]
    return (dated + unknown)[:limit]


def _fetch_official_regional_source(speaker, config):
    docs = []
    candidates = _archive_recent_links(speaker, config, limit=5)
    if not candidates:
        return docs

    def load(candidate):
        body, page_date = fetch_page(candidate["link"])
        if not body:
            return None
        date = page_date or candidate.get("date_hint") or _visible_date(body[:3000])
        return _official_doc_for_speaker(
            speaker, body, config["source"], date=date,
            title=candidate.get("title"), link=candidate.get("link"),
        )

    with ThreadPoolExecutor(max_workers=min(4, len(candidates))) as pool:
        futures = [pool.submit(load, c) for c in candidates]
        for f in as_completed(futures):
            try:
                doc = f.result()
                if doc:
                    docs.append(doc)
            except Exception:
                pass
    return docs


def get_official_regional_fed_documents():
    """Collect recent remarks from official Reserve Bank websites only."""
    docs = []
    # Williams is already covered by the New York Fed-specific parser below, which
    # is more reliable than the generic archive crawler.
    items = [(sp, cfg) for sp, cfg in OFFICIAL_REGIONAL_FED_SOURCES.items() if sp != "John Williams"]
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_fetch_official_regional_source, sp, cfg): sp for sp, cfg in items}
        for f in as_completed(futures):
            try:
                docs.extend(f.result() or [])
            except Exception:
                pass
    return docs


def get_board_yearpage_documents(limit=30):
    """Second official Board source to reduce RSS lag for same-day speeches."""
    url = "https://www.federalreserve.gov/newsevents/2026-speeches.htm"
    try:
        r = requests.get(url, headers=HEADERS, timeout=(3, 8))
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception:
        return []

    candidates = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a.get("href", ""))
        if "/newsevents/speech/" not in href or href in seen:
            continue
        seen.add(href)
        label = " ".join(a.stripped_strings).strip()
        context = " ".join((a.parent.parent if a.parent and a.parent.parent else a).stripped_strings)[:1600]
        date_hint = _visible_date(context)
        if date_hint and fed_recency_weight(date_hint) <= 0:
            continue
        candidates.append({"link": href, "title": label, "date_hint": date_hint})
        if len(candidates) >= limit:
            break

    docs = []
    def load(c):
        body, page_date = fetch_page(c["link"])
        date = page_date or c.get("date_hint") or _visible_date(body[:3000])
        # Board pages carry the speaker name in the body, so entity detection is safe.
        return _fed_raw_document(body, source="Federal Reserve", date=date,
                                 title=c.get("title"), link=c.get("link"), official_source=True)
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(load, c) for c in candidates]
        for f in as_completed(futures):
            try:
                d = f.result()
                if d:
                    docs.append(d)
            except Exception:
                pass
    return docs


def _fed_document_similarity(a, b):
    if a.get("speaker") != b.get("speaker"):
        return 0.0
    ta = normalize_text(a.get("title", ""))[:500]
    tb = normalize_text(b.get("title", ""))[:500]
    if not ta or not tb:
        return 0.0
    return SequenceMatcher(None, ta, tb).ratio()


def dedupe_fed_documents(documents):
    priority = {"Federal Reserve": 4, "New York Fed": 4, "UtoFX Telegram": 2, "UtoTimes": 1}
    ordered = sorted(documents, key=lambda e: priority.get(e.get("source"), 0), reverse=True)
    unique = []
    for doc in ordered:
        duplicate = False
        for existing in unique:
            same_link = doc.get("link") and existing.get("link") and doc["link"] == existing["link"]
            if same_link or _fed_document_similarity(doc, existing) >= 0.80:
                duplicate = True
                break
        if not duplicate:
            unique.append(doc)
    unique.sort(key=lambda x: parse_date(x.get("date")) or datetime(2000, 1, 1, tzinfo=timezone.utc), reverse=True)
    return unique


def balanced_fed_candidates(documents, max_per_speaker=FED_MAX_DOCS_PER_SPEAKER, total_limit=FED_MAX_DOCUMENTS):
    """Keep several recent documents per speaker instead of only the newest global items.

    This lets semantic analysis reject a non-policy speech and still inspect an
    earlier policy-relevant statement from the same speaker within the recency window.
    """
    counts = {}
    result = []
    ordered = sorted(
        documents,
        key=lambda x: parse_date(x.get("date")) or datetime(2000, 1, 1, tzinfo=timezone.utc),
        reverse=True,
    )
    for doc in ordered:
        speaker = doc.get("speaker")
        if not speaker:
            continue
        if counts.get(speaker, 0) >= max_per_speaker:
            continue
        result.append(doc)
        counts[speaker] = counts.get(speaker, 0) + 1
        if len(result) >= total_limit:
            break
    return result


def latest_fed_document_per_speaker(documents):
    latest = {}
    for doc in documents:
        speaker = doc.get("speaker")
        dt = parse_date(doc.get("date"))
        if not speaker or not dt:
            continue
        if speaker not in latest or dt > parse_date(latest[speaker].get("date")):
            latest[speaker] = doc
    result = list(latest.values())
    result.sort(key=lambda x: parse_date(x.get("date")) or datetime(2000, 1, 1, tzinfo=timezone.utc), reverse=True)
    return result


def _tone_from_stance(stance):
    """stance: -2 strongly dovish ... 0 neutral ... +2 strongly hawkish."""
    if stance >= 1.35:
        return "HAWKISH"
    if stance >= 0.40:
        return "SLIGHTLY HAWKISH"
    if stance <= -1.35:
        return "DOVISH"
    if stance <= -0.40:
        return "SLIGHTLY DOVISH"
    return "NEUTRAL"


def _safe_view(value):
    allowed = {
        "STRONGLY HAWKISH", "HAWKISH", "SLIGHTLY HAWKISH", "NEUTRAL",
        "SLIGHTLY DOVISH", "DOVISH", "STRONGLY DOVISH", "MIXED", "NOT DISCUSSED"
    }
    text = str(value or "NEUTRAL").strip().upper()
    return text if text in allowed else "NEUTRAL"


def _parse_json_object(text):
    if not text:
        raise ValueError("Empty AI response")
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError("No JSON object in AI response")


def _fed_documents_fingerprint(documents):
    payload = []
    for d in documents:
        payload.append({
            "speaker": d.get("speaker"), "date": d.get("date"),
            "source": d.get("source"), "title": d.get("title"),
            "text": (d.get("text") or "")[:FED_DOC_CHAR_LIMIT],
        })
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


POLICY_RELEVANCE_TERMS = [
    "monetary policy", "policy rate", "federal funds", "fed funds", "interest rate",
    "rate hike", "rate increase", "rate cut", "rate reduction", "hold rates",
    "inflation", "price stability", "labor market", "labour market", "employment",
    "unemployment", "dual mandate", "fomc", "economic outlook", "policy outlook",
    "restrictive", "neutral rate", "incoming data", "more data", "wait", "patience",
]

# These terms are used ONLY to establish that an official speech is plainly about
# monetary policy. They never determine hawkish/dovish direction or the score.
# This prevents a semantic model from accidentally rejecting an obviously policy-
# focused official speech such as "Economic Conditions and Monetary Policy".
FORCE_POLICY_TITLE_TERMS = [
    "monetary policy", "economic outlook", "u.s. economy", "us economy",
    "dual mandate", "policy communication", "policy risks",
    "outlook for the economy", "economic conditions", "policy framework",
    "federal funds", "interest rates", "rate policy",
]

def _title_policy_relevance_hint(title):
    t = normalize_text(title or "")
    return any(term in t for term in FORCE_POLICY_TITLE_TERMS)


def _policy_excerpt(text, title="", max_chars=FED_DOC_CHAR_LIMIT):
    """Build a compact but policy-complete excerpt for semantic analysis.

    This function does NOT score words. It only makes sure the LLM sees the
    forward-guidance/conclusion passages that are often near the end of a long
    official speech, instead of sending only the opening section.
    """
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        return ""

    lower = clean.lower()
    # Forward-looking policy language gets searched first because it is the most
    # informative part of a Fed speech for the CURRENT stance.
    priority_terms = [
        "further policy adjustments", "current views on monetary policy",
        "next policy move", "next rate", "policy rate", "federal funds",
        "rate increase", "rate hike", "rate cut", "interest rates",
        "monetary policy", "dual mandate", "inflation", "labor market",
        "labour market", "economic outlook", "incoming data", "more data",
    ]

    windows = []
    for term in priority_terms:
        pos = 0
        hits_for_term = 0
        while True:
            hit = lower.find(term, pos)
            if hit < 0:
                break
            windows.append((max(0, hit - 300), min(len(clean), hit + len(term) + 520)))
            pos = hit + len(term)
            hits_for_term += 1
            if hits_for_term >= 3 or len(windows) >= 16:
                break
        if len(windows) >= 16:
            break

    windows.sort()
    merged = []
    for a, b in windows:
        if merged and a <= merged[-1][1] + 100:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))

    policy_chunks = []
    for a, b in merged:
        chunk = clean[a:b].strip()
        if chunk and chunk not in policy_chunks:
            policy_chunks.append(chunk)

    title_part = str(title or "").strip()
    lead = clean[:300].strip()
    # Fed speakers very often state the actual policy conclusion near the end.
    tail = clean[-650:].strip() if len(clean) > 650 else clean

    core_parts = [x for x in [title_part, lead] + policy_chunks if x]
    core = " | ".join(core_parts)
    separator = " ... [CONCLUSION/TAIL] ... "

    # Reserve room for the conclusion so it can never be truncated away.
    tail_budget = min(650, max(300, max_chars // 3))
    tail = tail[-tail_budget:]
    core_budget = max(0, max_chars - len(separator) - len(tail))
    core = core[:core_budget]
    excerpt = (core + separator + tail).strip()
    return excerpt[:max_chars]

def _fed_speaker_bundles(documents):
    """Group recent candidate documents by speaker before asking the LLM.

    The model should make ONE stance decision per speaker after comparing the
    speaker's latest official Fed material with any timely Uto quote/Q&A. This is
    both more accurate and much smaller than asking for one output per document.
    """
    grouped = {}
    for doc in documents[:FED_MAX_DOCUMENTS]:
        speaker = doc.get("speaker")
        if not speaker:
            continue
        grouped.setdefault(speaker, []).append(doc)

    bundles = []
    for speaker, docs in grouped.items():
        docs = sorted(
            docs,
            key=lambda x: parse_date(x.get("date")) or datetime(2000, 1, 1, tzinfo=timezone.utc),
            reverse=True,
        )[:FED_MAX_DOCS_PER_SPEAKER]
        bundles.append({"speaker": speaker, "documents": docs})

    bundles.sort(
        key=lambda b: parse_date(b["documents"][0].get("date")) if b.get("documents") else datetime(2000, 1, 1, tzinfo=timezone.utc),
        reverse=True,
    )
    return bundles


def _groq_semantic_fed_analysis(documents):
    """Analyze one compact bundle per speaker in a single Groq request.

    v9 sent 12 document-level items and the model sometimes returned only a few
    analyses. v10 asks for exactly one result per SPEAKER bundle and validates
    that every bundle came back before a score is accepted.
    """
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not configured")

    bundles = _fed_speaker_bundles(documents)
    if not bundles:
        return [], []

    system_prompt = """You are a Federal Reserve monetary-policy analyst. Read meaning, not keyword counts.

Each item is ONE Fed speaker and may contain up to two recent source documents: official Federal Reserve System material and/or UtoFX/UtoTimes reporting. Decide the speaker's latest CURRENT monetary-policy stance after considering all supplied documents together.

Rules:
1. Forward guidance about the NEXT rate move has the highest weight.
2. A prior hike/cut/vote is historical context unless the speaker links it to the next move.
3. Inflation concern alone does not make the overall stance hawkish.
4. "More time", "wait for data", "no urgency", or similar patience language normally means neutral/slightly dovish unless another near-term hike is clearly advocated.
5. If an official source and Uto describe the SAME episode and conflict, prefer the official source. But an unrelated official speech must NOT suppress a newer policy-relevant Uto quote/Q&A.
6. If none of the supplied documents gives meaningful current policy guidance, set policy_relevant=false.
7. Never increase hawkish/dovish strength because a phrase is repeated.

stance_score: -2 strongly dovish, -1 dovish, -0.5 slightly dovish, 0 neutral, +0.5 slightly hawkish, +1 hawkish, +2 strongly hawkish.

You MUST return exactly ONE analysis object for EVERY supplied item id. Never omit an id, even when policy_relevant=false. Keep summary to max 24 words.

Return ONLY valid JSON:
{"analyses":[{"id":1,"speaker":"Name","policy_relevant":true,"selected_doc_id":1,"summary":"short factual summary","inflation_view":"NEUTRAL","labor_view":"NEUTRAL","rate_path_view":"NEUTRAL","stance_score":0.0,"confidence":85}]}

selected_doc_id is the document inside that speaker bundle that best supports the current stance, or null if policy_relevant=false.
Views: STRONGLY HAWKISH, HAWKISH, SLIGHTLY HAWKISH, NEUTRAL, SLIGHTLY DOVISH, DOVISH, STRONGLY DOVISH, MIXED, NOT DISCUSSED."""

    items = []
    for bundle_id, bundle in enumerate(bundles, 1):
        doc_items = []
        for doc_id, doc in enumerate(bundle["documents"], 1):
            doc_items.append({
                "doc_id": doc_id,
                "date": doc.get("date"),
                "source": doc.get("source"),
                "official_source": bool(doc.get("official_source")),
                "title": doc.get("title"),
                "policy_relevant_title_hint": _title_policy_relevance_hint(doc.get("title") or ""),
                "text": _policy_excerpt(doc.get("text") or "", doc.get("title") or "", max_chars=FED_DOC_CHAR_LIMIT),
            })
        items.append({
            "id": bundle_id,
            "speaker": bundle["speaker"],
            "documents": doc_items,
        })

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps({"speaker_bundles": items}, ensure_ascii=False)},
        ],
        "temperature": 0.05,
        "max_tokens": 2200,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    r = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=(5, 25))
    if r.status_code == 429:
        retry_after = r.headers.get("retry-after", "unknown")
        raise RuntimeError(f"GROQ RATE LIMIT (retry-after {retry_after}s)")
    r.raise_for_status()
    data = r.json()
    content = data["choices"][0]["message"]["content"]
    parsed = _parse_json_object(content)
    analyses = parsed.get("analyses")
    if not isinstance(analyses, list):
        raise ValueError("AI response missing analyses array")

    expected_ids = set(range(1, len(bundles) + 1))
    returned_ids = set()
    cleaned = []
    for a in analyses:
        try:
            aid = int(a.get("id"))
        except Exception:
            continue
        if aid in expected_ids and aid not in returned_ids:
            returned_ids.add(aid)
            cleaned.append(a)

    missing = sorted(expected_ids - returned_ids)
    if missing:
        raise RuntimeError(f"INCOMPLETE AI RESPONSE missing bundle ids {missing}")

    return bundles, cleaned


def _build_semantic_fed_result(bundles, analyses, candidate_count):
    by_id = {}
    for a in analyses:
        try:
            by_id[int(a.get("id"))] = a
        except Exception:
            continue

    events = []
    weighted_sum = 0.0
    weight_sum = 0.0
    relevant_count = 0

    for bundle_id, bundle in enumerate(bundles, 1):
        a = by_id.get(bundle_id)
        if not a:
            continue

        policy_relevant = a.get("policy_relevant", False)
        if isinstance(policy_relevant, str):
            policy_relevant = policy_relevant.strip().lower() in ("true", "1", "yes")

        docs = bundle.get("documents") or []
        # A clearly policy-focused official title is a relevance safety net only;
        # it never determines hawkish/dovish direction.
        forced_docs = [d for d in docs if d.get("official_source") and _title_policy_relevance_hint(d.get("title") or "")]
        if not policy_relevant and not forced_docs:
            continue

        try:
            selected_doc_id = int(a.get("selected_doc_id"))
        except Exception:
            selected_doc_id = None

        selected_doc = None
        if selected_doc_id and 1 <= selected_doc_id <= len(docs):
            selected_doc = docs[selected_doc_id - 1]
        elif forced_docs:
            selected_doc = forced_docs[0]
        elif docs:
            selected_doc = docs[0]
        if not selected_doc:
            continue

        try:
            stance = max(-2.0, min(2.0, float(a.get("stance_score", 0.0))))
        except Exception:
            stance = 0.0
        try:
            confidence = max(0.0, min(100.0, float(a.get("confidence", 50))))
        except Exception:
            confidence = 50.0

        relevant_count += 1
        confidence_weight = 0.45 + 0.55 * (confidence / 100.0)
        recency = fed_recency_weight(selected_doc.get("date"))
        speaker = bundle.get("speaker")
        speaker_weight = FED_SPEAKERS.get(speaker, {}).get("weight", 0.75)
        voter_weight = 1.08 if selected_doc.get("voter") else 0.92
        source_weight = 1.00 if selected_doc.get("official_source") else 0.82
        weight = speaker_weight * voter_weight * source_weight * recency * confidence_weight

        weighted_sum += stance * weight
        weight_sum += weight
        gold_impact = -stance * weight

        events.append({
            "speaker": speaker,
            "tone": _tone_from_stance(stance),
            "stance_score": round(stance, 2),
            "summary": str(a.get("summary") or "").strip()[:520],
            "inflation_view": _safe_view(a.get("inflation_view")),
            "labor_view": _safe_view(a.get("labor_view")),
            "rate_path_view": _safe_view(a.get("rate_path_view")),
            "confidence": round(confidence, 0),
            "gold_impact": round(gold_impact, 2),
            "source": selected_doc.get("source"),
            "source_type": "OFFICIAL FED" if selected_doc.get("official_source") else "UTO SECONDARY",
            "date": selected_doc.get("date"),
            "title": selected_doc.get("title"),
            "link": selected_doc.get("link"),
            "voter": selected_doc.get("voter"),
        })

    if weight_sum <= 0:
        score = 50.0
        avg_stance = 0.0
    else:
        avg_stance = weighted_sum / weight_sum
        score = clamp(50.0 - avg_stance * 15.0, 20.0, 80.0)

    events.sort(key=lambda x: parse_date(x.get("date")) or datetime(2000, 1, 1, tzinfo=timezone.utc), reverse=True)
    return {
        "score": round(score, 1),
        "events": events,
        "event_count": len(events),
        "candidate_count": candidate_count,
        "speaker_bundle_count": len(bundles),
        "analyzed_count": len(analyses),
        "relevant_count": relevant_count,
        "rejected_count": max(0, len(bundles) - relevant_count),
        "average_stance": round(avg_stance, 2),
        "mode": "AI SEMANTIC • FED + UTO",
        "model": GROQ_MODEL,
        "source_scope": "Official Federal Reserve System sources + UtoFX/UtoTimes secondary reporting",
        "status": "OK",
    }

def get_fed_monitor(telegram_news, utotimes_news):
    now = time.time()
    if FED_CACHE["result"] is not None and now - FED_CACHE["time"] < FED_CACHE_SECONDS:
        return FED_CACHE["result"]

    documents = []
    # Primary sources: official Federal Reserve System websites.
    documents.extend(get_board_speech_documents(30))
    documents.extend(get_board_yearpage_documents(30))
    documents.extend(get_williams_speech_documents(12))
    documents.extend(get_official_regional_fed_documents())

    # Secondary/timely sources: UtoFX and UtoTimes. These are useful for same-day
    # Q&A/quotes before an official transcript appears, but receive lower weight
    # and lose to an official source when the two are effectively contemporaneous.
    for item in telegram_news:
        doc = _fed_raw_document(
            item.get("text", ""), source=item.get("source", "UtoFX Telegram"),
            date=item.get("date"), title=item.get("text", "")[:240],
            link=item.get("link"), official_source=False,
        )
        if doc:
            documents.append(doc)

    # Dedicated UtoTimes Fed discovery. This is intentionally separate from the
    # 5-item Live News panel, so a Kashkari/Jefferson/etc. story is not lost just
    # because several unrelated headlines were published afterward.
    fed_uto_items = get_utotimes_fed_news(24)

    # Also keep the already-fetched general UtoTimes items as a fallback, then
    # de-duplicate by link before turning them into Fed documents.
    combined_uto = []
    uto_seen = set()
    for item in fed_uto_items + list(utotimes_news or []):
        link = item.get("link")
        key = link or (item.get("title"), item.get("date"))
        if key in uto_seen:
            continue
        uto_seen.add(key)
        combined_uto.append(item)

    for item in combined_uto:
        if item.get("text") and item.get("source") == "UtoTimes":
            text = item.get("text", "")
        else:
            body = BeautifulSoup(item.get("content") or "", "html.parser").get_text(" ", strip=True)
            text = f"{item.get('title','')} {body}"
        doc = _fed_raw_document(
            text, source="UtoTimes", date=item.get("date"),
            title=item.get("title", ""), link=item.get("link"),
            official_source=False,
        )
        if doc:
            documents.append(doc)

    documents = dedupe_fed_documents(documents)
    # Diagnostics before the final candidate cap. These counts make it obvious
    # whether a missing speaker failed at source collection or at semantic filtering.
    discovered_official_count = sum(1 for d in documents if d.get("official_source"))
    discovered_uto_count = sum(1 for d in documents if not d.get("official_source"))
    # Keep up to several recent documents PER SPEAKER. This prevents a cluster of
    # non-policy speeches from crowding out an older, still-recent policy statement.
    # The AI then rejects irrelevant documents and the latest relevant one per
    # speaker is selected after semantic analysis.
    documents = balanced_fed_candidates(documents)

    if not documents:
        result = {
            "score": 50.0, "events": [], "event_count": 0,
            "average_stance": 0.0, "mode": "AI SEMANTIC • FED + UTO",
            "model": GROQ_MODEL, "source_scope": "Official Federal Reserve System sources + UtoFX/UtoTimes secondary reporting", "status": "NO RECENT DOCUMENTS",
        }
        FED_CACHE["time"] = now
        FED_CACHE["result"] = result
        return result

    fingerprint = _fed_documents_fingerprint(documents)
    if FED_AI_CACHE.get("fingerprint") == fingerprint and FED_AI_CACHE.get("result"):
        result = dict(FED_AI_CACHE["result"])
        result["official_discovered"] = discovered_official_count
        result["uto_discovered"] = discovered_uto_count
        result["uto_fed_items"] = len(fed_uto_items)
        FED_CACHE["time"] = now
        FED_CACHE["result"] = result
        return result

    try:
        bundles, analyses = _groq_semantic_fed_analysis(documents)
        result = _build_semantic_fed_result(bundles, analyses, len(documents))
        result["official_discovered"] = discovered_official_count
        result["uto_discovered"] = discovered_uto_count
        result["uto_fed_items"] = len(fed_uto_items)
        FED_AI_CACHE["fingerprint"] = fingerprint
        FED_AI_CACHE["result"] = result
        FED_AI_CACHE["time"] = now
    except Exception as exc:
        # Never fall back to keyword scoring. If AI is unavailable, neutralize this
        # component instead of presenting a misleading hawkish/dovish number.
        previous = FED_AI_CACHE.get("result")
        if previous:
            result = dict(previous)
            result["status"] = "USING LAST AI RESULT"
        else:
            result = {
                "score": 50.0,
                "events": [],
                "event_count": 0,
                "average_stance": 0.0,
                "mode": "AI SEMANTIC • FED + UTO",
                "model": GROQ_MODEL, "source_scope": "Official Federal Reserve System sources + UtoFX/UtoTimes secondary reporting",
                "status": ("API KEY MISSING" if "GROQ_API_KEY" in str(exc) else ("AI RATE LIMIT" if "RATE LIMIT" in str(exc) else ("AI INCOMPLETE RESPONSE" if "INCOMPLETE AI RESPONSE" in str(exc) else "AI TEMPORARILY UNAVAILABLE"))),
                "error": str(exc)[:220],
            }

    FED_CACHE["time"] = now
    FED_CACHE["result"] = result
    return result

# =========================================================
# ECONOMIC ENGINE
# =========================================================


def find_profile(text):
    lower = normalize_text(text)
    for profile in EVENT_PROFILES:
        for alias in profile["aliases"]:
            if normalize_text(alias) in lower:
                return profile
    return None


def find_all_profiles(text):
    lower = normalize_text(text)
    found = []
    for profile in EVENT_PROFILES:
        if any(normalize_text(alias) in lower for alias in profile["aliases"]):
            found.append(profile)
    return found


def extract_labeled_number(text, labels):
    clean = normalize_digits(text).replace("٫", ".").replace("٬", ",")
    label_re = "|".join(re.escape(x) for x in labels)
    pattern = rf"(?:{label_re})\s*[:：]?\s*[\.…·_\-–—\s]*([+-]?\d+(?:\.\d+)?)(\-)?\s*(%|درصد|هزار|میلیون|میلیارد|K|M|B)?"
    m = re.search(pattern, clean, flags=re.IGNORECASE)
    if not m:
        return None
    value = float(m.group(1))
    if m.group(2) == "-":
        value = -value
    unit = (m.group(3) or "").lower()
    if unit in ("میلیون", "m"):
        value *= 1000.0
    elif unit in ("میلیارد", "b"):
        value *= 1000000.0
    return value


def value_display(value, original_unit=""):
    if value is None:
        return "-"
    if abs(value) >= 1000000:
        return f"{value/1000000:.2f}B"
    if abs(value) >= 1000:
        return f"{value:.0f}K"
    if float(value).is_integer():
        return str(int(value))
    return str(round(value, 3))


def extract_profile_block(text, profile, window=1200):
    lower = normalize_text(text)
    positions = []
    for alias in profile["aliases"]:
        pos = lower.find(normalize_text(alias))
        if pos >= 0:
            positions.append(pos)
    if not positions:
        return None
    pos = min(positions)
    start = max(0, pos - 100)
    return lower[start:pos + window]


def economic_article_candidate(title, content=""):
    combined = f"{title} {BeautifulSoup(content or '', 'html.parser').get_text(' ', strip=True)}"
    return bool(find_all_profiles(combined))


def get_economic_articles(limit=24):
    items = []
    seen = set()
    for feed_url in UTOTIMES_FEEDS:
        feed_items = parse_rss_items(feed_url, limit=limit)
        for item in feed_items:
            link = item.get("link")
            if not link or link in seen:
                continue
            combined = f"{item.get('title','')} {BeautifulSoup(item.get('content') or '', 'html.parser').get_text(' ', strip=True)}"
            if not economic_article_candidate(item.get("title", ""), item.get("content", "")):
                continue
            seen.add(link)
            text = BeautifulSoup(item.get("content") or "", "html.parser").get_text(" ", strip=True)
            page_date = None
            if "واقعی" not in text and "actual" not in normalize_text(text):
                page_text, page_date = fetch_page(link)
                text = page_text
            items.append({"title": item.get("title", ""), "link": link, "date": item.get("date") or page_date, "text": text})
            if len(items) >= limit:
                return items
        if items:
            break
    return items


def fetch_ff_calendar():
    try:
        r = requests.get(FF_URL, headers=HEADERS, timeout=12)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception:
        return []


def ff_impact_for_profile(profile, event_date, ff_events):
    target_dt = parse_date(event_date)
    best = None
    best_hours = 9999
    for event in ff_events:
        if str(event.get("country", "")).upper() != "USD":
            continue
        title = event.get("title", "")
        if not any(normalize_text(alias) in normalize_text(title) for alias in profile["aliases"]):
            continue
        dt = parse_date(event.get("date"))
        if target_dt and dt:
            diff = abs((dt - target_dt).total_seconds()) / 3600.0
        else:
            diff = 24
        if diff < best_hours:
            best = event
            best_hours = diff
    return best


def immediate_decay(date_value):
    hours = hours_since(date_value)
    if hours is None:
        return 0.0
    if hours <= 1:
        return 1.00
    if hours <= 3:
        return 0.85
    if hours <= 6:
        return 0.60
    if hours <= 12:
        return 0.35
    if hours <= 24:
        return 0.15
    return 0.0


def policy_decay(date_value, persistence_hours):
    hours = hours_since(date_value)
    if hours is None or hours > persistence_hours:
        return 0.0
    return max(0.15, 1.0 - hours / persistence_hours)


def impact_weight(value):
    text = normalize_text(value)
    if "high" in text:
        return 1.00
    if "medium" in text:
        return 0.65
    if "low" in text:
        return 0.30
    return 0.65


def session_yield_confirmation(policy_signal, two_year_change_bps, event_date):
    """Use the 2Y session move as confirmation, measured in basis points.

    The economic release creates the signal. The 2Y move only confirms or
    weakens it. We apply this only to releases from the last six hours.
    """
    hours = hours_since(event_date)

    if (
        hours is None
        or hours > 6
        or two_year_change_bps is None
        or abs(policy_signal) < 0.10
    ):
        return {"status": "NOT APPLIED", "multiplier": 1.00}

    try:
        bps = float(two_year_change_bps)
    except Exception:
        return {"status": "NOT APPLIED", "multiplier": 1.00}

    # Dovish / gold-positive data should generally pull the 2Y yield lower.
    if policy_signal > 0:
        if bps <= -2.0:
            return {"status": "CONFIRMED", "multiplier": 1.15}
        if bps >= 2.0:
            return {"status": "REJECTED BY 2Y", "multiplier": 0.70}

    # Hawkish / gold-negative data should generally push the 2Y yield higher.
    else:
        if bps >= 2.0:
            return {"status": "CONFIRMED", "multiplier": 1.15}
        if bps <= -2.0:
            return {"status": "REJECTED BY 2Y", "multiplier": 0.70}

    return {"status": "NOT CONFIRMED", "multiplier": 0.90}


def score_release(profile, actual, forecast, previous, date, impact, source, link, two_year_change_bps):
    if actual is None:
        return None
    basis = None
    confidence = 1.0
    comparison = None
    if forecast is not None:
        comparison = actual - forecast
        basis = "forecast"
    elif previous is not None:
        comparison = actual - previous
        basis = "previous"
        confidence = 0.45
    else:
        return None
    normalized_surprise = max(-3.0, min(3.0, comparison / profile["scale"]))
    gold_direction_signal = normalized_surprise * profile["direction"]
    imp = impact_weight(impact)
    immediate = gold_direction_signal * profile["immediate_weight"] * imp * confidence * immediate_decay(date)
    immediate = max(-10, min(10, immediate))
    raw_policy = gold_direction_signal * profile["policy_weight"] * imp * confidence * policy_decay(date, profile["persistence_hours"])
    confirmation = session_yield_confirmation(raw_policy, two_year_change_bps, date)
    policy = max(-10, min(10, raw_policy * confirmation["multiplier"]))
    return {
        "name": profile["name"], "category": profile["category"],
        "actual": value_display(actual), "forecast": value_display(forecast), "previous": value_display(previous),
        "actual_num": actual, "forecast_num": forecast, "previous_num": previous,
        "impact": impact or "Unknown", "date": date, "basis": basis,
        "surprise": round(normalized_surprise, 2),
        "immediate_impact": round(immediate, 2), "policy_impact": round(policy, 2),
        "confirmation": confirmation["status"], "source": source, "link": link,
        "persistence_hours": profile["persistence_hours"],
    }


def extract_releases_from_article(article, ff_events, two_year_change_bps):
    text = article.get("text", "")
    date = article.get("date")
    results = []
    for profile in find_all_profiles(f"{article.get('title','')} {text}"):
        block = extract_profile_block(text, profile)
        if not block:
            continue
        actual = extract_labeled_number(block, ["واقعی", "actual"])
        forecast = extract_labeled_number(block, ["پیش‌بینی", "پیش بینی", "forecast"])
        previous = extract_labeled_number(block, ["قبلی", "previous"])
        if actual is None:
            continue
        ff_match = ff_impact_for_profile(profile, date, ff_events)
        if ff_match:
            if forecast is None:
                forecast = parse_number(ff_match.get("forecast"))
            if previous is None:
                previous = parse_number(ff_match.get("previous"))
            impact = ff_match.get("impact")
        else:
            impact = "Medium"
        scored = score_release(profile, actual, forecast, previous, date, impact, "UtoTimes", article.get("link"), two_year_change_bps)
        if scored:
            results.append(scored)
    return results


def dedupe_releases(events):
    unique = {}
    for event in events:
        dt = parse_date(event.get("date"))
        day = dt.strftime("%Y-%m-%d") if dt else "unknown"
        key = (event.get("name"), day)
        if key not in unique:
            unique[key] = event
    result = list(unique.values())
    result.sort(key=lambda x: parse_date(x.get("date")) or datetime(2000, 1, 1, tzinfo=timezone.utc), reverse=True)
    return result


def build_category_scores(events):
    categories = {"Inflation": 50.0, "Labor": 50.0, "Growth": 50.0, "Consumption": 50.0}
    for category in categories:
        impact = sum(e["policy_impact"] for e in events if e["category"] == category)
        categories[category] = round(clamp(50 + impact), 1)
    return categories


def get_economic_monitor(two_year_change_bps=None):
    now = time.time()
    if ECON_CACHE["result"] is not None and now - ECON_CACHE["time"] < ECON_CACHE_SECONDS and ECON_CACHE["last_2y"] == two_year_change_bps:
        return ECON_CACHE["result"]
    ff_events = fetch_ff_calendar()
    articles = get_economic_articles(24)
    scored = []
    for article in articles:
        scored.extend(extract_releases_from_article(article, ff_events, two_year_change_bps))
    scored = dedupe_releases(scored)
    active_policy = [e for e in scored if abs(e["policy_impact"]) > 0.01]
    active_immediate = [e for e in scored if abs(e["immediate_impact"]) > 0.01]
    market_shock = round(clamp(50 + sum(e["immediate_impact"] for e in active_immediate[:12])), 1)
    fed_policy = round(clamp(50 + sum(e["policy_impact"] for e in active_policy[:20])), 1)
    categories = build_category_scores(active_policy)
    underlying = round(categories["Labor"] * 0.40 + categories["Growth"] * 0.35 + categories["Consumption"] * 0.25, 1)
    economic_score = round(market_shock * 0.25 + fed_policy * 0.50 + underlying * 0.25, 1)
    result = {
        "score": economic_score, "market_shock_score": market_shock,
        "fed_policy_score": fed_policy, "underlying_score": underlying,
        "categories": categories, "events": scored[:15], "event_count": len(scored),
        "source": "UtoTimes + Forex Factory schedule", "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
    ECON_CACHE["time"] = now
    ECON_CACHE["result"] = result
    ECON_CACHE["last_2y"] = two_year_change_bps
    return result

# =========================================================
# ECONOMIC ENGINE V2 — EXACT SECTION MATCHING + REVISIONS
# =========================================================

# Add two useful profiles that were not in the first version.
if not any(p["name"] == "Headline PCE" for p in EVENT_PROFILES):
    EVENT_PROFILES.insert(1, {
        "name": "Headline PCE",
        "aliases": ["pce price index", "شاخص هزینه های مصرف شخصی", "شاخص هزینه‌های مصرف شخصی"],
        "category": "Inflation", "direction": -1, "scale": 0.10,
        "immediate_weight": 3.0, "policy_weight": 4.3, "persistence_hours": 336,
    })

if not any(p["name"] == "ISM Services Prices" for p in EVENT_PROFILES):
    EVENT_PROFILES.append({
        "name": "ISM Services Prices",
        "aliases": ["ism services prices", "ism services prices paid", "مولفه قیمت های خدمات ism", "مولفه قیمت‌های خدمات ism"],
        "category": "Inflation", "direction": -1, "scale": 2.0,
        "immediate_weight": 2.6, "policy_weight": 3.2, "persistence_hours": 168,
    })

FF_EXACT_TITLES = {
    "Core PCE": ["core pce price index m/m", "core pce price index y/y", "core pce price index"],
    "Headline PCE": ["pce price index m/m", "pce price index y/y", "pce price index"],
    "Core CPI": ["core cpi m/m", "core cpi y/y", "core cpi"],
    "Headline CPI": ["cpi m/m", "cpi y/y", "consumer price index"],
    "Core PPI": ["core ppi m/m", "core ppi"],
    "PPI": ["ppi m/m", "producer price index"],
    "ISM Prices Paid": ["ism manufacturing prices", "ism manufacturing prices index"],
    "ISM Services Prices": ["ism services prices", "ism services prices paid"],
    "Nonfarm Payrolls": ["non-farm employment change", "nonfarm payrolls", "non-farm payrolls"],
    "Unemployment Rate": ["unemployment rate"],
    "Average Hourly Earnings": ["average hourly earnings m/m", "average hourly earnings"],
    "Initial Jobless Claims": ["unemployment claims", "initial jobless claims"],
    "Continuing Claims": ["continuing jobless claims", "continuing claims"],
    "ADP Employment": ["adp non-farm employment change", "adp employment change"],
    "JOLTS": ["jolts job openings"],
    "ISM Manufacturing": ["ism manufacturing pmi"],
    "ISM Services": ["ism services pmi", "ism non-manufacturing pmi"],
    "GDP": ["advance gdp q/q", "prelim gdp q/q", "final gdp q/q", "gdp q/q"],
    "Core Retail Sales": ["core retail sales m/m", "core retail sales"],
    "Retail Sales": ["retail sales m/m", "retail sales"],
    "Consumer Confidence": ["cb consumer confidence", "consumer confidence"],
    "Consumer Sentiment": ["prelim uom consumer sentiment", "revised uom consumer sentiment", "uom consumer sentiment", "consumer sentiment"],
}

US_CONTEXT_TERMS = [
    "united states", "u.s.", "america", "american", "ایالات متحده", "آمریکا", "امریکا", "دلار آمریکا", "usd"
]
US_INTRINSIC_EVENTS = {
    "Core PCE", "Headline PCE", "Nonfarm Payrolls", "Initial Jobless Claims",
    "Continuing Claims", "ADP Employment", "JOLTS", "ISM Manufacturing",
    "ISM Prices Paid", "ISM Services", "ISM Services Prices",
}


def _profile_alias_markers(text):
    """Find event headings and suppress overlapping generic aliases.

    Example: 'Core Retail Sales' wins over the shorter 'Retail Sales' alias.
    This also lets one UtoTimes article safely contain both ISM PMI and ISM Prices.
    """
    lower = normalize_text(text)
    candidates = []
    for profile in EVENT_PROFILES:
        for alias in profile["aliases"]:
            a = normalize_text(alias)
            if not a:
                continue
            for m in re.finditer(re.escape(a), lower, flags=re.I):
                candidates.append((m.start(), m.end(), profile, a))

    kept = []
    for cand in sorted(candidates, key=lambda x: (-(x[1] - x[0]), x[0])):
        if any(not (cand[1] <= k[0] or cand[0] >= k[1]) for k in kept):
            continue
        kept.append(cand)
    kept.sort(key=lambda x: x[0])
    return lower, kept


def extract_event_sections(text):
    lower, markers = _profile_alias_markers(text)
    sections = []
    for i, marker in enumerate(markers):
        start = marker[0]
        end = markers[i + 1][0] if i + 1 < len(markers) else len(lower)
        end = min(end, start + 1600)
        sections.append((marker[2], lower[start:end].strip()))
    return sections


def _parse_unit_value(number_text, unit_text=""):
    value = parse_number(number_text)
    if value is None:
        return None
    unit = normalize_text(unit_text)
    if unit in ("میلیون", "m"):
        value *= 1000.0
    elif unit in ("میلیارد", "b"):
        value *= 1000000.0
    return value


def extract_previous_revision(block):
    """Return (original_previous, revised_previous, delta) when revision is explicit."""
    previous_label = extract_labeled_number(block, ["قبلی", "previous"])
    if previous_label is None:
        return None, None, None

    clean = normalize_digits(block).replace("٫", ".").replace("٬", ",")
    label = re.search(
        r"(?:قبلی|previous)\s*[:：]?\s*[\.…·_\-–—\s]*[+-]?\d+(?:\.\d+)?(?:\-)?\s*(?:%|درصد|هزار|میلیون|میلیارد|K|M|B)?",
        clean, flags=re.I,
    )
    snippet = clean[label.end():label.end() + 320] if label else clean[:320]
    num = r"([+-]?\d+(?:\.\d+)?)(?:\-)?\s*(%|درصد|هزار|میلیون|میلیارد|K|M|B)?"

    # Example: قبلی 198 ... (این داده از 196 هزار نفر تجدید شده است)
    m = re.search(rf"(?:از|revised\s+from|from)\s*{num}[^\)\]\n]{{0,100}}(?:تجدید|بازبینی|revis)", snippet, flags=re.I)
    if m:
        original = _parse_unit_value(m.group(1), m.group(2) or "")
        revised = previous_label
        return original, revised, (revised - original) if original is not None else None

    # Example: قبلی 214 ... (به 215 هزار نفر بازبینی شد)
    m = re.search(rf"(?:به|revised\s+to|to)\s*{num}[^\)\]\n]{{0,100}}(?:تجدید|بازبینی|revis)", snippet, flags=re.I)
    if m:
        revised = _parse_unit_value(m.group(1), m.group(2) or "")
        original = previous_label
        return original, revised, (revised - original) if revised is not None else None

    return None, previous_label, None


def _is_us_article(text, profiles):
    lower = normalize_text(text)
    if any(term in lower for term in US_CONTEXT_TERMS):
        return True
    return bool({p["name"] for p in profiles} & US_INTRINSIC_EVENTS)


def economic_article_candidate(title, content=""):
    body = BeautifulSoup(content or "", "html.parser").get_text(" ", strip=True)
    combined = f"{title} {body}"
    profiles = find_all_profiles(combined)
    return bool(profiles) and _is_us_article(combined, profiles)


def get_economic_articles(limit=24):
    items = []
    seen = set()
    for feed_url in UTOTIMES_FEEDS:
        for item in parse_rss_items(feed_url, limit=max(limit, 30)):
            link = item.get("link")
            if not link or link in seen:
                continue
            body = BeautifulSoup(item.get("content") or "", "html.parser").get_text(" ", strip=True)
            combined = f"{item.get('title','')} {body}"
            profiles = find_all_profiles(combined)
            if not profiles:
                continue

            page_date = None
            # Fetch full page if the RSS body is incomplete or does not prove U.S. context.
            if "واقعی" not in body and "actual" not in normalize_text(body) or not _is_us_article(combined, profiles):
                page_text, page_date = fetch_page(link)
                if page_text:
                    body = page_text
                    combined = f"{item.get('title','')} {body}"
                    profiles = find_all_profiles(combined)

            if not profiles or not _is_us_article(combined, profiles):
                continue

            seen.add(link)
            items.append({
                "title": item.get("title", ""), "link": link,
                "date": item.get("date") or page_date, "text": body,
            })
            if len(items) >= limit:
                return items
        if items:
            break
    return items


def _ff_title_match(profile_name, event_title):
    title = normalize_text(event_title)
    allowed = [normalize_text(x) for x in FF_EXACT_TITLES.get(profile_name, [])]
    return title in allowed


def ff_impact_for_profile(profile, event_date, ff_events):
    """Exact event-title matching only; never fuzzy-match one ISM subindex to another."""
    target_dt = parse_date(event_date)
    best = None
    best_hours = 9999.0
    for event in ff_events:
        if str(event.get("country", "")).upper() != "USD":
            continue
        if not _ff_title_match(profile["name"], event.get("title", "")):
            continue
        dt = parse_date(event.get("date"))
        if target_dt and dt:
            diff = abs((dt - target_dt).total_seconds()) / 3600.0
            if diff > 18:
                continue
        elif target_dt or dt:
            continue
        else:
            diff = 0.0
        if diff < best_hours:
            best, best_hours = event, diff
    return best


def score_release_v2(profile, actual, forecast, previous, date, impact, source, link,
                     two_year_change_bps, previous_original=None, previous_revised=None,
                     revision_delta=None):
    if actual is None:
        return None

    if forecast is not None:
        comparison, basis, confidence = actual - forecast, "forecast", 1.0
    elif previous is not None:
        comparison, basis, confidence = actual - previous, "previous", 0.45
    else:
        return None

    surprise = max(-3.0, min(3.0, comparison / profile["scale"]))
    signal = surprise * profile["direction"]
    imp = impact_weight(impact)
    immediate_main = signal * profile["immediate_weight"] * imp * confidence * immediate_decay(date)
    policy_main = signal * profile["policy_weight"] * imp * confidence * policy_decay(date, profile["persistence_hours"])

    revision_immediate = 0.0
    revision_policy = 0.0
    if revision_delta is not None and profile["scale"]:
        rev_surprise = max(-2.0, min(2.0, revision_delta / profile["scale"]))
        rev_signal = rev_surprise * profile["direction"]
        revision_immediate = max(-1.5, min(1.5, rev_signal * profile["immediate_weight"] * imp * 0.15 * immediate_decay(date)))
        revision_policy = max(-2.0, min(2.0, rev_signal * profile["policy_weight"] * imp * 0.25 * policy_decay(date, profile["persistence_hours"])))

    immediate = max(-10, min(10, immediate_main + revision_immediate))
    raw_policy = policy_main + revision_policy
    confirmation = session_yield_confirmation(raw_policy, two_year_change_bps, date)
    policy = max(-10, min(10, raw_policy * confirmation["multiplier"]))

    return {
        "name": profile["name"], "category": profile["category"],
        "actual": value_display(actual), "forecast": value_display(forecast), "previous": value_display(previous),
        "actual_num": actual, "forecast_num": forecast, "previous_num": previous,
        "previous_original": value_display(previous_original) if previous_original is not None else "-",
        "previous_revised": value_display(previous_revised) if previous_revised is not None else value_display(previous),
        "revision_delta": revision_delta, "revision_impact": round(revision_policy, 2),
        "impact": impact or "Unknown", "date": date, "basis": basis,
        "surprise": round(surprise, 2),
        "immediate_impact": round(immediate, 2), "policy_impact": round(policy, 2),
        "confirmation": confirmation["status"], "source": source, "link": link,
        "persistence_hours": profile["persistence_hours"],
    }


def extract_releases_from_article(article, ff_events, two_year_change_bps):
    results = []
    used = set()
    combined = f"{article.get('title','')} {article.get('text','')}"

    for profile, block in extract_event_sections(combined):
        if profile["name"] in used:
            continue
        actual = extract_labeled_number(block, ["واقعی", "actual"])
        if actual is None:
            continue

        forecast = extract_labeled_number(block, ["پیش‌بینی", "پیش بینی", "forecast"])
        previous_original, previous_revised, revision_delta = extract_previous_revision(block)
        previous = previous_revised

        ff_match = ff_impact_for_profile(profile, article.get("date"), ff_events)
        if ff_match:
            # UtoTimes is primary. FF only fills a missing field after an exact title match.
            if forecast is None:
                forecast = parse_number(ff_match.get("forecast"))
            if previous is None:
                previous = parse_number(ff_match.get("previous"))
                previous_revised = previous
            impact = ff_match.get("impact")
        else:
            impact = "Medium"

        scored = score_release_v2(
            profile, actual, forecast, previous, article.get("date"), impact,
            "UtoTimes", article.get("link"), two_year_change_bps,
            previous_original=previous_original, previous_revised=previous_revised,
            revision_delta=revision_delta,
        )
        if scored:
            results.append(scored)
            used.add(profile["name"])
    return results


def get_economic_monitor(two_year_change_bps=None):
    now = time.time()
    if ECON_CACHE["result"] is not None and now - ECON_CACHE["time"] < ECON_CACHE_SECONDS:
        return ECON_CACHE["result"]

    ff_events = fetch_ff_calendar()
    articles = get_economic_articles(24)
    scored = []
    for article in articles:
        scored.extend(extract_releases_from_article(article, ff_events, two_year_change_bps))
    scored = dedupe_releases(scored)

    active_policy = [e for e in scored if abs(e["policy_impact"]) > 0.01]
    active_immediate = [e for e in scored if abs(e["immediate_impact"]) > 0.01]
    market_shock = round(clamp(50 + sum(e["immediate_impact"] for e in active_immediate[:12])), 1)
    fed_policy = round(clamp(50 + sum(e["policy_impact"] for e in active_policy[:20])), 1)
    categories = build_category_scores(active_policy)
    underlying = round(categories["Labor"] * 0.40 + categories["Growth"] * 0.35 + categories["Consumption"] * 0.25, 1)
    economic_score = round(market_shock * 0.25 + fed_policy * 0.50 + underlying * 0.25, 1)

    result = {
        "score": economic_score, "market_shock_score": market_shock,
        "fed_policy_score": fed_policy, "underlying_score": underlying,
        "categories": categories, "events": scored[:15], "event_count": len(scored),
        "source": "UtoTimes exact-section parser + Forex Factory exact-title backup",
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
    ECON_CACHE["time"] = now
    ECON_CACHE["result"] = result
    ECON_CACHE["last_2y"] = two_year_change_bps
    return result


# =========================================================
# GLOBAL GEOPOLITICAL RISK ENGINE
# =========================================================

# Retrieval terms are used only to find potentially relevant items. They NEVER
# determine escalation/de-escalation direction or the score; the semantic model
# makes that judgment from context.
GEO_RETRIEVAL_TERMS = [
    "war", "conflict", "military", "strike", "airstrike", "missile", "drone",
    "troops", "deployment", "ceasefire", "peace deal", "sanctions", "nuclear",
    "blockade", "shipping", "red sea", "strait of hormuz", "taiwan", "ukraine",
    "russia", "iran", "israel", "gaza", "nato", "north korea", "south china sea",
    "tariff", "trade war", "export controls", "terror attack", "coup",
    "جنگ", "حمله", "موشک", "پهپاد", "تحریم", "آتش بس", "آتش‌بس", "صلح",
    "هسته ای", "هسته‌ای", "تنگه هرمز", "دریای سرخ", "تایوان", "اوکراین",
    "روسیه", "اسرائیل", "غزه", "تعرفه", "جنگ تجاری", "ناتو", "کره شمالی",
]

GEO_CREDIBILITY_DOMAINS = {
    "reuters.com": 1.00, "apnews.com": 0.99, "bloomberg.com": 0.97,
    "bbc.com": 0.95, "bbc.co.uk": 0.95, "ft.com": 0.95, "wsj.com": 0.94,
    "cnbc.com": 0.90, "nytimes.com": 0.90, "washingtonpost.com": 0.90,
    "theguardian.com": 0.87, "dw.com": 0.88, "france24.com": 0.87,
    "aljazeera.com": 0.84, "nikkei.com": 0.92, "scmp.com": 0.80,
    "whitehouse.gov": 0.99, "state.gov": 0.99, "defense.gov": 0.99,
    "centcom.mil": 0.99, "nato.int": 0.99, "un.org": 0.98,
    "truthsocial.com": 0.96, "x.com": 0.94,
    "utotimes.com": 0.78, "t.me": 0.76,
}

GDELT_GEO_QUERY = (
    '(war OR conflict OR missile OR airstrike OR ceasefire OR sanctions OR nuclear OR '
    'troops OR blockade OR tariff OR "trade war" OR "Strait of Hormuz" OR "Red Sea" '
    'OR Taiwan OR Ukraine OR Iran OR Israel OR NATO OR "North Korea")'
)


def _geo_parse_date(value):
    dt = parse_date(value)
    if dt:
        return dt
    raw = str(value or "").strip()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S", "%Y%m%dT%H%M%S"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def _geo_iso(value):
    dt = _geo_parse_date(value)
    return dt.isoformat() if dt else None


def _domain_credibility(domain):
    d = str(domain or "").lower().replace("www.", "").strip()
    for known, weight in GEO_CREDIBILITY_DOMAINS.items():
        if d == known or d.endswith("." + known):
            return weight
    return 0.68


def _geo_hours_since(value):
    dt = _geo_parse_date(value)
    if not dt:
        return 999.0
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0)


def _geo_decay(hours):
    if hours <= 3:
        return 1.00
    if hours <= 12:
        return 0.88
    if hours <= 24:
        return 0.72
    if hours <= 48:
        return 0.48
    if hours <= 72:
        return 0.30
    if hours <= 168:
        return 0.15
    return 0.0


def _looks_geopolitical(text):
    t = normalize_text(text)
    return any(term in t for term in GEO_RETRIEVAL_TERMS)


def get_gdelt_geopolitical_news(limit=45):
    """Global news radar. GDELT supplies broad worldwide coverage; AI decides relevance."""
    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {
        "query": GDELT_GEO_QUERY,
        "mode": "artlist",
        "format": "json",
        "timespan": "24h",
        "maxrecords": str(max(10, min(limit, 75))),
        "sort": "datedesc",
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=(4, 12))
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []

    items = []
    for article in data.get("articles", []) if isinstance(data, dict) else []:
        title = str(article.get("title") or "").strip()
        link = article.get("url") or article.get("url_mobile")
        domain = str(article.get("domain") or "").lower().replace("www.", "")
        date = _geo_iso(article.get("seendate") or article.get("date"))
        if not title or not link:
            continue
        items.append({
            "text": title[:700],
            "title": title[:300],
            "date": date,
            "link": link,
            "source": domain or "GDELT indexed source",
            "source_type": "GLOBAL NEWS",
            "domain": domain,
            "credibility": _domain_credibility(domain),
        })
    return items[:limit]


def get_trump_truth_posts(limit=10):
    """Best-effort direct public Trump Truth Social feed (Mastodon-compatible endpoint)."""
    url = f"https://truthsocial.com/api/v1/accounts/{TRUMP_TRUTH_ACCOUNT_ID}/statuses"
    try:
        r = requests.get(url, params={"limit": min(limit, 20)}, headers=HEADERS, timeout=(4, 10))
        r.raise_for_status()
        statuses = r.json()
    except Exception:
        return []

    result = []
    if not isinstance(statuses, list):
        return result
    for s in statuses:
        if not isinstance(s, dict) or s.get("reblog"):
            continue
        body = BeautifulSoup(s.get("content") or "", "html.parser").get_text(" ", strip=True)
        if not body:
            continue
        result.append({
            "text": body[:1200],
            "title": "Donald Trump — Truth Social",
            "date": _geo_iso(s.get("created_at")),
            "link": s.get("url") or s.get("uri"),
            "source": "Donald Trump — Truth Social",
            "source_type": "DIRECT STATEMENT",
            "domain": "truthsocial.com",
            "credibility": 0.96,
        })
    return result[:limit]


def _twitter_snowflake_date(value):
    try:
        millis = (int(str(value)) >> 22) + 1288834974657
        return datetime.fromtimestamp(millis / 1000.0, tz=timezone.utc).isoformat()
    except Exception:
        return None


def get_trump_x_posts(limit=8):
    """Best-effort public X embedded timeline. It is supplemental and may be unavailable."""
    url = "https://syndication.twitter.com/srv/timeline-profile/screen-name/realDonaldTrump"
    try:
        r = requests.get(url, headers=HEADERS, timeout=(4, 10))
        r.raise_for_status()
        m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S | re.I)
        if not m:
            return []
        root = json.loads(m.group(1))
    except Exception:
        return []

    found = {}
    def walk(obj):
        if isinstance(obj, dict):
            txt = obj.get("full_text") or obj.get("text")
            ident = obj.get("id_str") or obj.get("id") or obj.get("rest_id")
            user = obj.get("user") or obj.get("author") or {}
            screen = ""
            if isinstance(user, dict):
                legacy = user.get("legacy") if isinstance(user.get("legacy"), dict) else {}
                screen = str(user.get("screen_name") or user.get("username") or legacy.get("screen_name") or "")
            if isinstance(txt, str) and len(txt.strip()) > 15 and ident:
                if not screen or screen.lower() == "realdonaldtrump":
                    iid = str(ident)
                    date = obj.get("created_at") or obj.get("createdAt") or _twitter_snowflake_date(iid)
                    found[iid] = {
                        "text": txt.strip()[:1200],
                        "title": "Donald Trump — X",
                        "date": _geo_iso(date),
                        "link": f"https://x.com/realDonaldTrump/status/{iid}",
                        "source": "Donald Trump — X",
                        "source_type": "DIRECT STATEMENT",
                        "domain": "x.com",
                        "credibility": 0.94,
                    }
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
    walk(root)
    items = list(found.values())
    items.sort(key=lambda x: _geo_parse_date(x.get("date")) or datetime(2000,1,1,tzinfo=timezone.utc), reverse=True)
    return items[:limit]


def _uto_geo_candidates(telegram_news, utotimes_news):
    result = []
    for item in telegram_news:
        text = item.get("text") or ""
        if not _looks_geopolitical(text):
            continue
        result.append({
            "text": text[:1200], "title": text[:260], "date": _geo_iso(item.get("date")),
            "link": item.get("link"), "source": "UtoFX Telegram", "source_type": "UTO",
            "domain": "t.me", "credibility": 0.76,
        })
    for item in utotimes_news:
        title = item.get("title") or ""
        body = BeautifulSoup(item.get("content") or "", "html.parser").get_text(" ", strip=True)
        combined = f"{title} {body}".strip()
        if not _looks_geopolitical(combined):
            continue
        result.append({
            "text": combined[:1200], "title": title[:300], "date": _geo_iso(item.get("date")),
            "link": item.get("link"), "source": "UtoTimes", "source_type": "UTO",
            "domain": "utotimes.com", "credibility": 0.78,
        })
    return result


def _dedupe_geo_candidates(items):
    ordered = sorted(
        items,
        key=lambda x: (_geo_parse_date(x.get("date")) or datetime(2000,1,1,tzinfo=timezone.utc), x.get("credibility",0)),
        reverse=True,
    )
    unique = []
    for item in ordered:
        key = normalize_text(item.get("text") or "")[:500]
        if not key:
            continue
        duplicate = False
        for old in unique:
            oldkey = normalize_text(old.get("text") or "")[:500]
            if key == oldkey or SequenceMatcher(None, key[:260], oldkey[:260]).ratio() >= 0.90:
                duplicate = True
                break
        if not duplicate:
            unique.append(item)
    return unique


def _select_geo_candidates(items, limit=GEO_MAX_CANDIDATES):
    """Balance direct statements, high-quality wires and broad global coverage."""
    direct = [x for x in items if x.get("source_type") == "DIRECT STATEMENT" and _looks_geopolitical(x.get("text"))]
    trusted = [x for x in items if x.get("source_type") == "GLOBAL NEWS" and x.get("credibility",0) >= 0.87]
    other = [x for x in items if x not in direct and x not in trusted]
    result = []
    for bucket, cap in ((direct, 5), (trusted, 10), (other, limit)):
        for x in bucket:
            if x not in result:
                result.append(x)
            if len([y for y in result if y in bucket]) >= cap or len(result) >= limit:
                break
        if len(result) >= limit:
            break
    return result[:limit]


def _geo_fingerprint(items):
    payload = [{"text":x.get("text"),"date":x.get("date"),"source":x.get("source")} for x in items]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _groq_geopolitical_analysis(candidates):
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not configured")

    docs=[]
    for i,c in enumerate(candidates,1):
        docs.append({
            "id": i, "date": c.get("date"), "source": c.get("source"),
            "source_type": c.get("source_type"), "credibility": round(float(c.get("credibility",0.68)),2),
            "headline_or_text": (c.get("text") or "")[:1200],
        })

    system_prompt = """You are a global geopolitical-risk analyst for a GOLD macro dashboard.
Read the supplied items semantically. Do NOT score by keyword counts. The task is to identify DISTINCT current geopolitical events worldwide that can matter to gold, the U.S. dollar, rates, oil, or global risk appetite.

Coverage is GLOBAL: Middle East, Russia/Ukraine, Europe/NATO, China/Taiwan/South China Sea, Koreas, India/Pakistan, trade wars/tariffs/export controls, sanctions, nuclear risks, shipping chokepoints, terrorism/security, coups/major instability, and major diplomatic de-escalation.

Critical rules:
1. MERGE duplicate reports of the same real-world event into one event. More sources increase confidence, not event count.
2. Distinguish a STATEMENT/THREAT from PREPARATION and from a CONFIRMED_ACTION/ACTIVE_CONFLICT. A politician's post is evidence of what they said, not proof that an action happened.
3. Direct Trump X/Truth posts are important public statements. If a claim of action is not independently supported by another supplied source, do not upgrade it to confirmed action solely because the post says it happened.
4. Official/major-wire reporting has higher evidentiary value for confirming actions. Uto is useful secondary reporting.
5. DE-ESCALATION (ceasefire, credible negotiations, withdrawal, sanctions relief, peace agreement) must receive negative direction for gold geopolitical risk when materially important.
6. Ignore routine domestic politics, ordinary crime, sports, culture, or items with negligible global gold relevance.
7. Evaluate current market relevance, not moral importance.

For each distinct event return:
- event_key: short unique label
- summary: concise factual 1-2 sentence summary
- region: short region/country pair
- category: one of MILITARY, NUCLEAR, SANCTIONS, TRADE, SHIPPING, TERROR_SECURITY, POLITICAL_INSTABILITY, DIPLOMACY, ENERGY_SECURITY, OTHER
- direction: ESCALATION, DE_ESCALATION, or NEUTRAL
- stage: STATEMENT, THREAT, PREPARATION, CONFIRMED_ACTION, ACTIVE_CONFLICT, DIPLOMATIC_ACTION, CEASEFIRE_DEAL, SANCTIONS_ACTION, TRADE_ACTION
- severity: 0-100
- gold_relevance: 0-100
- oil_relevance: 0-100
- confidence: 0-100
- input_ids: list of supplied document IDs supporting the event

Return ONLY valid JSON: {"events":[...]}.
Return at most 8 events, prioritizing gold relevance and recency. Do not invent facts beyond the supplied items."""

    payload={
        "model": GEO_GROQ_MODEL,
        "messages":[
            {"role":"system","content":system_prompt},
            {"role":"user","content":json.dumps({"items":docs},ensure_ascii=False)},
        ],
        "temperature":0.1,
        "max_tokens":1500,
        "response_format":{"type":"json_object"},
    }
    headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"}
    r=requests.post(GROQ_API_URL,headers=headers,json=payload,timeout=(5,25))
    if r.status_code == 429:
        raise RuntimeError("GROQ RATE LIMIT")
    r.raise_for_status()
    parsed=_parse_json_object(r.json()["choices"][0]["message"]["content"])
    events=parsed.get("events")
    if not isinstance(events,list):
        raise ValueError("Geo AI response missing events array")
    return events[:GEO_MAX_EVENTS]


def _score_geopolitical_events(candidates, ai_events):
    by_id={i+1:c for i,c in enumerate(candidates)}
    stage_mult={
        "STATEMENT":0.30, "THREAT":0.48, "PREPARATION":0.68,
        "CONFIRMED_ACTION":0.88, "ACTIVE_CONFLICT":1.00,
        "DIPLOMATIC_ACTION":0.58, "CEASEFIRE_DEAL":0.92,
        "SANCTIONS_ACTION":0.72, "TRADE_ACTION":0.68,
    }
    events=[]
    net=0.0
    for e in ai_events:
        try:
            direction=str(e.get("direction") or "NEUTRAL").upper()
            sign=1 if direction=="ESCALATION" else (-1 if direction=="DE_ESCALATION" else 0)
            sev=clamp(float(e.get("severity",0)))
            rel=clamp(float(e.get("gold_relevance",0)))
            conf=clamp(float(e.get("confidence",50)))
            ids=[]
            for raw in e.get("input_ids") or []:
                try:
                    iid=int(raw)
                    if iid in by_id and iid not in ids:
                        ids.append(iid)
                except Exception:
                    pass
            if not ids or rel < 15:
                continue
            src=[by_id[i] for i in ids]
            latest=min((_geo_hours_since(x.get("date")) for x in src), default=999)
            decay=_geo_decay(latest)
            cred=max((float(x.get("credibility",0.68)) for x in src),default=0.68)
            cred=min(1.0,cred+0.025*max(0,len(src)-1))
            stage=str(e.get("stage") or "STATEMENT").upper()
            mult=stage_mult.get(stage,0.50)
            impact=sign*8.0*(sev/100)*(rel/100)*(conf/100)*mult*cred*decay
            impact=max(-8.0,min(8.0,impact))
            net+=impact
            primary=max(src,key=lambda x: float(x.get("credibility",0.68)))
            events.append({
                "event_key":str(e.get("event_key") or e.get("summary") or "Event")[:100],
                "summary":str(e.get("summary") or "")[:520],
                "region":str(e.get("region") or "Global")[:80],
                "category":str(e.get("category") or "OTHER")[:40].upper(),
                "direction":direction,
                "stage":stage,
                "severity":round(sev,0),
                "gold_relevance":round(rel,0),
                "oil_relevance":round(clamp(float(e.get("oil_relevance",0))),0),
                "confidence":round(conf,0),
                "impact":round(impact,2),
                "source_count":len(src),
                "sources":[x.get("source") for x in src[:4]],
                "link":primary.get("link"),
                "date":primary.get("date"),
            })
        except Exception:
            continue

    score=clamp(50+net,5,95)
    events.sort(key=lambda x:(abs(x.get("impact",0)),x.get("severity",0)),reverse=True)
    if score>=80:
        regime="EXTREME GLOBAL RISK — STRONG SUPPORT FOR GOLD"
    elif score>=65:
        regime="HIGH GLOBAL RISK — SUPPORTIVE FOR GOLD"
    elif score>=55:
        regime="ELEVATED GLOBAL RISK — MILD SUPPORT FOR GOLD"
    elif score<=35:
        regime="STRONG DE-ESCALATION — HEADWIND FOR GOLD"
    elif score<=45:
        regime="DE-ESCALATING — MILD HEADWIND FOR GOLD"
    else:
        regime="BALANCED / NEUTRAL"
    escalating=sum(1 for e in events if e["direction"]=="ESCALATION")
    deescalating=sum(1 for e in events if e["direction"]=="DE_ESCALATION")
    return {
        "score":round(score,1), "regime":regime, "events":events[:GEO_MAX_EVENTS],
        "event_count":len(events), "escalating":escalating, "deescalating":deescalating,
        "net_impact":round(net,2),
    }


def get_geopolitical_monitor(telegram_news, utotimes_news):
    now=time.time()
    if GEO_CACHE["result"] is not None and now-GEO_CACHE["time"]<GEO_CACHE_SECONDS:
        return GEO_CACHE["result"]

    # Fetch independent global sources concurrently so one slow provider cannot block the others.
    with ThreadPoolExecutor(max_workers=3) as pool:
        fg=pool.submit(get_gdelt_geopolitical_news,45)
        ft=pool.submit(get_trump_truth_posts,10)
        fx=pool.submit(get_trump_x_posts,8)
        try: gdelt=fg.result()
        except Exception: gdelt=[]
        try: truth=ft.result()
        except Exception: truth=[]
        try: xposts=fx.result()
        except Exception: xposts=[]

    uto=_uto_geo_candidates(telegram_news,utotimes_news)
    all_items=_dedupe_geo_candidates(gdelt+truth+xposts+uto)
    candidates=_select_geo_candidates(all_items,GEO_MAX_CANDIDATES)

    source_stats={
        "gdelt":len(gdelt), "truth":len(truth), "x":len(xposts), "uto":len(uto),
        "candidates":len(candidates),
    }

    if not candidates:
        result={
            "score":50.0,"regime":"NO CURRENT GEO DATA","events":[],"event_count":0,
            "escalating":0,"deescalating":0,"net_impact":0.0,"status":"NO CANDIDATES",
            "source_stats":source_stats,
        }
        GEO_CACHE["time"]=now; GEO_CACHE["result"]=result
        return result

    fingerprint=_geo_fingerprint(candidates)
    if GEO_AI_CACHE.get("fingerprint")==fingerprint and GEO_AI_CACHE.get("result"):
        result=GEO_AI_CACHE["result"]
        GEO_CACHE["time"]=now; GEO_CACHE["result"]=result
        return result

    try:
        ai_events=_groq_geopolitical_analysis(candidates)
        result=_score_geopolitical_events(candidates,ai_events)
        result["status"]="OK"
        result["source_stats"]=source_stats
        result["candidate_count"]=len(candidates)
        result["ai_event_count"]=len(ai_events)
        GEO_AI_CACHE.update({"fingerprint":fingerprint,"result":result,"time":now})
    except Exception as exc:
        previous=GEO_AI_CACHE.get("result")
        if previous:
            result=dict(previous); result["status"]="USING LAST AI RESULT"
        else:
            result={
                "score":50.0,"regime":"AI TEMPORARILY UNAVAILABLE","events":[],"event_count":0,
                "escalating":0,"deescalating":0,"net_impact":0.0,"status":"AI TEMPORARILY UNAVAILABLE",
                "error":str(exc)[:220],"source_stats":source_stats,
            }

    GEO_CACHE["time"]=now; GEO_CACHE["result"]=result
    return result


# =========================================================
# GOLD SCORE ENGINE
# =========================================================


def calculate_rates_engine(markets):
    """Convert Treasury yield moves to basis points and score their gold impact.

    Weighting:
      2Y  = 50%  (most sensitive to the expected Fed path)
      10Y = 35%  (important for the opportunity cost of holding gold)
      30Y = 15%  (long-duration inflation/fiscal signal)

    Positive weighted bps = yields rising = headwind for gold.
    Negative weighted bps = yields falling = support for gold.
    """

    y2 = markets["us2y"].get("change_bps")
    y10 = markets["us10y"].get("change_bps")
    y30 = markets["us30y"].get("change_bps")

    # If a quote is temporarily unavailable, use zero for the weighted score
    # but preserve None in the dashboard so the missing data is visible.
    y2_calc = float(y2) if y2 is not None else 0.0
    y10_calc = float(y10) if y10 is not None else 0.0
    y30_calc = float(y30) if y30 is not None else 0.0

    weighted_bps = (
        y2_calc * 0.50
        + y10_calc * 0.35
        + y30_calc * 0.15
    )

    # Calibration: a +10 bp weighted move takes Rates Score from 50 to 34;
    # a -10 bp move takes it from 50 to 66.
    score = clamp(50 - weighted_bps * 1.60)

    if weighted_bps >= 8:
        regime = "STRONG HEADWIND FOR GOLD"
    elif weighted_bps >= 2:
        regime = "HEADWIND FOR GOLD"
    elif weighted_bps <= -8:
        regime = "STRONG SUPPORT FOR GOLD"
    elif weighted_bps <= -2:
        regime = "SUPPORT FOR GOLD"
    else:
        regime = "NEUTRAL"

    return {
        "score": round(score, 1),
        "weighted_bps": round(weighted_bps, 1),
        "us2y_bps": y2,
        "us10y_bps": y10,
        "us30y_bps": y30,
        "regime": regime,
    }


def calculate_scores(markets, fed_score, economic_score, geopolitical_score):
    gold_change = markets["gold"].get("change_pct") or 0
    dxy_change = markets["dxy"].get("change_pct") or 0
    oil_change = markets["oil"].get("change_pct") or 0
    vix_change = markets["vix"].get("change_pct") or 0

    dollar_score = clamp(50 - dxy_change * 18)

    rates_engine = calculate_rates_engine(markets)
    rates_score = rates_engine["score"]

    technical_score = clamp(50 + gold_change * 12)
    market_flow_score = clamp(50 + vix_change * 1.5)
    oil_score = clamp(50 - oil_change * 3)

    components = {
        "Economic Data": round(economic_score, 1),
        "Federal Reserve": round(fed_score, 1),
        "Rates": round(rates_score, 1),
        "US Dollar": round(dollar_score, 1),
        "Geopolitical Risk": round(geopolitical_score, 1),
        "Oil / Inflation": round(oil_score, 1),
        "Market Flow": round(market_flow_score, 1),
        "Technical": round(technical_score, 1),
    }

    weights = {
        "Economic Data": 0.20,
        "Federal Reserve": 0.20,
        "Rates": 0.15,
        "US Dollar": 0.15,
        "Geopolitical Risk": 0.10,
        "Oil / Inflation": 0.07,
        "Market Flow": 0.05,
        "Technical": 0.08,
    }

    total = round(sum(components[k] * weights[k] for k in components), 1)

    if total >= 75:
        bias = "STRONGLY BULLISH"
    elif total >= 60:
        bias = "BULLISH"
    elif total >= 54:
        bias = "SLIGHTLY BULLISH"
    elif total <= 25:
        bias = "STRONGLY BEARISH"
    elif total <= 40:
        bias = "BEARISH"
    elif total <= 46:
        bias = "SLIGHTLY BEARISH"
    else:
        bias = "NEUTRAL"

    return total, bias, components, rates_engine

# =========================================================
# BUILD DASHBOARD
# =========================================================


def build_dashboard_data():
    now = time.time()
    if CACHE["data"] is not None and now - CACHE["time"] < CACHE_SECONDS:
        return CACHE["data"]
    treasury_curve = treasury_spot_curve()

    markets = {
        "gold": xau_spot_market(),
        "dxy": yahoo_market("DX-Y.NYB"),
        "us2y": treasury_curve["2Y"],
        "us10y": treasury_curve["10Y"],
        "us30y": treasury_curve["30Y"],
        "oil": yahoo_market("CL=F"),
        "vix": yahoo_market("^VIX"),
    }
    telegram_news = get_utofx_news(40)
    utotimes_news = get_utotimes_news(30)
    fed = get_fed_monitor(telegram_news, utotimes_news)
    # Only use 2Y as an event-time confirmation when the source is truly intraday.
    # Daily Treasury/FRED closes are useful for the Rates Engine, but using a stale
    # daily move to confirm a release from the last few hours would be misleading.
    two_year_confirmation_bps = (
        markets["us2y"].get("change_bps")
        if markets["us2y"].get("intraday")
        else None
    )
    economic = get_economic_monitor(two_year_confirmation_bps)
    geopolitical = get_geopolitical_monitor(telegram_news, utotimes_news)
    score, bias, components, rates_engine = calculate_scores(markets, fed["score"], economic["score"], geopolitical["score"])
    data = {
        "score": score, "bias": bias, "components": components, "markets": markets,
        "rates": rates_engine, "economic": economic, "fed": fed, "geopolitical": geopolitical, "telegram_news": telegram_news[:8],
        "utotimes_news": utotimes_news[:5],
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
    CACHE["time"] = now
    CACHE["data"] = data
    return data


def _initial_dashboard_data():
    market_blank = {
        "price": None, "previous": None, "change": None,
        "change_pct": None, "change_bps": None, "ok": False,
        "source": "Loading",
    }
    markets = {
        "gold": dict(market_blank),
        "dxy": dict(market_blank),
        "us2y": dict(market_blank),
        "us10y": dict(market_blank),
        "us30y": dict(market_blank),
        "oil": dict(market_blank),
        "vix": dict(market_blank),
    }
    components = {
        "Economic Data": 50.0,
        "Federal Reserve": 50.0,
        "Rates": 50.0,
        "US Dollar": 50.0,
        "Geopolitical Risk": 50.0,
        "Oil / Inflation": 50.0,
        "Market Flow": 50.0,
        "Technical": 50.0,
    }
    return {
        "score": 50.0,
        "bias": "LOADING",
        "components": components,
        "markets": markets,
        "rates": {
            "score": 50.0, "weighted_bps": 0.0,
            "us2y_bps": None, "us10y_bps": None, "us30y_bps": None,
            "regime": "INITIALIZING DATA",
        },
        "economic": {
            "score": 50.0, "market_shock_score": 50.0,
            "fed_policy_score": 50.0, "underlying_score": 50.0,
            "categories": {"Inflation": 50.0, "Labor": 50.0, "Growth": 50.0, "Consumption": 50.0},
            "events": [], "event_count": 0,
        },
        "fed": {"score": 50.0, "events": [], "event_count": 0, "average_stance": 0.0, "mode": "AI SEMANTIC", "model": GROQ_MODEL, "status": "INITIALIZING"},
        "geopolitical": {"score": 50.0, "regime": "INITIALIZING", "events": [], "event_count": 0, "escalating": 0, "deescalating": 0, "net_impact": 0.0, "status": "INITIALIZING", "source_stats": {}},
        "telegram_news": [], "utotimes_news": [],
        "updated": "Waiting for first data refresh…",
        "initializing": True,
        "refreshing": True,
    }


def _background_refresh():
    try:
        # Mark the main cache stale so this thread performs a real refresh.
        build_dashboard_data()
        REFRESH_STATE["last_error"] = None
    except Exception as exc:
        REFRESH_STATE["last_error"] = str(exc)[:300]
    finally:
        with REFRESH_LOCK:
            REFRESH_STATE["running"] = False


def _ensure_background_refresh():
    now = time.time()
    stale = CACHE["data"] is None or (now - CACHE["time"] >= CACHE_SECONDS)
    if not stale:
        return False
    with REFRESH_LOCK:
        if REFRESH_STATE["running"]:
            return True
        REFRESH_STATE["running"] = True
        REFRESH_STATE["started"] = now
        thread = threading.Thread(target=_background_refresh, daemon=True)
        thread.start()
        return True


def get_dashboard_snapshot():
    refreshing = _ensure_background_refresh()
    if CACHE["data"] is None:
        data = _initial_dashboard_data()
    else:
        # Shallow copy is enough because template rendering is read-only.
        data = dict(CACHE["data"])
        data["initializing"] = False
        data["refreshing"] = refreshing
    data["refresh_error"] = REFRESH_STATE.get("last_error")
    return data

@app.route("/api/status")
def api_status():
    return jsonify(get_dashboard_snapshot())

@app.route("/")
def dashboard():
    data = get_dashboard_snapshot()
    html = r'''
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FINAD Gold Intelligence</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#080b12;color:#fff;font-family:Arial,Helvetica,sans-serif}.container{max-width:1250px;margin:auto;padding:30px 20px 60px}.brand{font-size:14px;letter-spacing:4px;color:#d8b96c;font-weight:bold}h1{margin:8px 0 5px;font-size:clamp(28px,5vw,42px)}.subtitle{color:#8f98aa;margin-bottom:25px}.hero,.panel,.market-card,.component,.fed-card{background:#10151f;border:1px solid #222a39;border-radius:14px}.hero{padding:35px;text-align:center;border-radius:18px}.score-title{color:#8f98aa;font-size:13px;letter-spacing:2px}.score{font-size:clamp(60px,10vw,95px);font-weight:bold;margin-top:5px}.score span{font-size:22px;color:#6f7888}.bias{display:inline-block;padding:9px 18px;border-radius:30px;background:#1a2130;color:#d8b96c;font-weight:bold}.bar{max-width:650px;height:10px;background:#252c39;border-radius:10px;overflow:hidden;margin:30px auto 5px}.bar-fill{height:100%;width:{{ data.score }}%;background:linear-gradient(90deg,#c84a4a,#d8b96c,#51b77a)}.scale{max-width:650px;margin:auto;display:flex;justify-content:space-between;font-size:11px;color:#727b8b}.section-title{margin:35px 0 15px;font-size:21px}.market-grid,.components,.fed-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}.market-card,.component,.fed-card{padding:17px}.market-title,.component-name{color:#8e98a9;font-size:13px}.market-price{font-size:25px;font-weight:bold;margin-top:8px}.component-score{font-size:29px;font-weight:bold;margin-top:8px}.positive{color:#55c987}.negative{color:#e46c6c}.neutral{color:#9099a8}.panel{padding:20px}.fed-top{display:flex;align-items:center;justify-content:space-between;gap:12px}.speaker{font-weight:bold;font-size:16px}.badge{font-size:10px;padding:5px 8px;border-radius:12px;background:#1a2130;color:#8fa0b8}.tone{font-size:13px;font-weight:bold;margin-top:8px}.tone-dovish{color:#55c987}.tone-hawkish{color:#e46c6c}.impact{font-size:12px;color:#9ca6b6;margin-top:7px}.event-title{font-size:12px;color:#8792a3;line-height:1.5;margin-top:9px}.news-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.news-title{font-size:18px;font-weight:bold;margin-bottom:15px}.news-item{border-top:1px solid #222a39;padding:14px 0}.news-item:first-of-type{border-top:0}.news-text{font-size:14px;line-height:1.7;direction:rtl;text-align:right}.news-meta,.note{font-size:11px;color:#707a8b;margin-top:7px;line-height:1.6}.news-item a,.fed-card a{color:inherit;text-decoration:none}.status{margin-top:25px;background:#10151f;border:1px solid #222a39;border-radius:14px;padding:18px}.online{color:#55c987;font-weight:bold}@media(max-width:750px){.news-grid{grid-template-columns:1fr}}
</style>
</head>
<body><div class="container">
<div class="brand">FINAD</div><h1>Gold Intelligence Indicator</h1><div class="subtitle">Macro • Fed • Rates • Dollar • Geopolitics • Market Data</div>
<div class="hero"><div class="score-title">GOLD INTELLIGENCE SCORE</div><div class="score">{{ data.score }} <span>/100</span></div><div class="bias">{{ data.bias }}</div><div class="bar"><div class="bar-fill"></div></div><div class="scale"><span>BEARISH</span><span>NEUTRAL</span><span>BULLISH</span></div></div>

<div class="section-title">Live Markets</div><div class="market-grid">
{% set names={'gold':'XAUUSD Spot','dxy':'DXY','us2y':'US 2Y','us10y':'US 10Y','us30y':'US 30Y','oil':'WTI Oil','vix':'VIX'} %}
{% for key,item in data.markets.items() %}
<div class="market-card">
<div class="market-title">{{ names[key] }}</div>
<div class="market-price">{% if item.price is not none %}{{ item.price }}{% if key in ['us2y','us10y','us30y'] %}%{% endif %}{% else %}N/A{% endif %}</div>
{% if key in ['us2y','us10y','us30y'] %}
    {% if item.change_bps is not none %}
    <div class="{% if item.change_bps>0 %}negative{% elif item.change_bps<0 %}positive{% else %}neutral{% endif %}">{% if item.change_bps>0 %}+{% endif %}{{ item.change_bps }} bp</div>
    {% else %}<div class="neutral">Data unavailable</div>{% endif %}
{% else %}
    {% if item.change_pct is not none %}
    <div class="{% if item.change_pct>0 %}positive{% elif item.change_pct<0 %}negative{% else %}neutral{% endif %}">{% if item.change_pct>0 %}+{% endif %}{{ item.change_pct }}%</div>
    {% else %}<div class="neutral">Data unavailable</div>{% endif %}
{% endif %}
</div>
{% endfor %}
</div>

<div class="section-title">Rates Monitor</div>
<div class="components">
<div class="component"><div class="component-name">Rates Score</div><div class="component-score">{{ data.rates.score }} <span style="font-size:14px;color:#697282">/100</span></div></div>
<div class="component"><div class="component-name">US 2Y Move</div><div class="component-score">{{ data.rates.us2y_bps if data.rates.us2y_bps is not none else 'N/A' }} <span style="font-size:14px;color:#697282">bp</span></div></div>
<div class="component"><div class="component-name">US 10Y Move</div><div class="component-score">{{ data.rates.us10y_bps if data.rates.us10y_bps is not none else 'N/A' }} <span style="font-size:14px;color:#697282">bp</span></div></div>
<div class="component"><div class="component-name">US 30Y Move</div><div class="component-score">{{ data.rates.us30y_bps if data.rates.us30y_bps is not none else 'N/A' }} <span style="font-size:14px;color:#697282">bp</span></div></div>
<div class="component"><div class="component-name">Weighted Yield Move</div><div class="component-score">{{ data.rates.weighted_bps }} <span style="font-size:14px;color:#697282">bp</span></div></div>
</div>
<div class="panel" style="margin-top:12px"><div class="news-title">Rates Regime</div><div class="note"><strong>{{ data.rates.regime }}</strong> • Weighting: 2Y 50% / 10Y 35% / 30Y 15%. Positive bps means yields are rising and is a headwind for gold.</div><div class="note">Treasury source: <strong>{{ data.markets.us2y.source or "Unknown" }}</strong>{% if data.markets.us2y.as_of %} • Latest official close: <strong>{{ data.markets.us2y.as_of }}</strong>{% endif %}</div></div>

<div class="section-title">Gold Score Components</div><div class="components">
<div class="component"><div class="component-name">Federal Reserve</div><div class="component-score">{{ data.fed.score }} <span style="font-size:14px;color:#697282">/100</span></div></div>
{% for name,value in data.components.items() %}{% if name != 'Federal Reserve' %}<div class="component"><div class="component-name">{{ name }}</div><div class="component-score">{{ value }} <span style="font-size:14px;color:#697282">/100</span></div></div>{% endif %}{% endfor %}</div>

<div class="section-title">Economic Monitor</div><div class="components">
<div class="component"><div class="component-name">Economic Score</div><div class="component-score">{{ data.economic.score }} <span style="font-size:14px;color:#697282">/100</span></div></div>
<div class="component"><div class="component-name">Market Shock</div><div class="component-score">{{ data.economic.market_shock_score }} <span style="font-size:14px;color:#697282">/100</span></div></div>
<div class="component"><div class="component-name">Fed Policy Pressure</div><div class="component-score">{{ data.economic.fed_policy_score }} <span style="font-size:14px;color:#697282">/100</span></div></div>
<div class="component"><div class="component-name">Underlying Economy</div><div class="component-score">{{ data.economic.underlying_score }} <span style="font-size:14px;color:#697282">/100</span></div></div>
{% for category,value in data.economic.categories.items() %}<div class="component"><div class="component-name">{{ category }}</div><div class="component-score">{{ value }} <span style="font-size:14px;color:#697282">/100</span></div></div>{% endfor %}
</div>
<div class="panel" style="margin-top:12px"><div class="news-title">Latest U.S. Economic Releases</div>
{% if data.economic.events %}{% for event in data.economic.events[:10] %}<div class="news-item"><div style="font-weight:bold">{{ event.name }}</div><div class="note">Actual: <strong>{{ event.actual }}</strong> &nbsp;|&nbsp; Forecast: <strong>{{ event.forecast }}</strong> &nbsp;|&nbsp; Previous: <strong>{{ event.previous }}</strong></div>{% if event.previous_original != '-' or event.revision_delta is not none %}<div class="note">Previous originally reported: <strong>{{ event.previous_original }}</strong> &nbsp;|&nbsp; Previous revised: <strong>{{ event.previous_revised }}</strong> &nbsp;|&nbsp; Revision Gold Impact: <strong class="{% if event.revision_impact>0 %}positive{% elif event.revision_impact<0 %}negative{% else %}neutral{% endif %}">{% if event.revision_impact>0 %}+{% endif %}{{ event.revision_impact }}</strong></div>{% endif %}<div class="note">Immediate Gold Impact: <strong class="{% if event.immediate_impact>0 %}positive{% elif event.immediate_impact<0 %}negative{% else %}neutral{% endif %}">{% if event.immediate_impact>0 %}+{% endif %}{{ event.immediate_impact }}</strong> &nbsp;|&nbsp; Fed Policy Impact: <strong class="{% if event.policy_impact>0 %}positive{% elif event.policy_impact<0 %}negative{% else %}neutral{% endif %}">{% if event.policy_impact>0 %}+{% endif %}{{ event.policy_impact }}</strong></div><div class="note">2Y Confirmation: <strong>{{ event.confirmation }}</strong> &nbsp;|&nbsp; Category: {{ event.category }} &nbsp;|&nbsp; Source: {{ event.source }}</div></div>{% endfor %}{% else %}<div class="note">No parsed U.S. releases yet.</div>{% endif %}
</div>

<div class="section-title">Global Geopolitical Risk Monitor</div>
<div class="components">
<div class="component"><div class="component-name">Geopolitical Score</div><div class="component-score">{{ data.geopolitical.score }} <span style="font-size:14px;color:#697282">/100</span></div></div>
<div class="component"><div class="component-name">Active Events</div><div class="component-score">{{ data.geopolitical.event_count }}</div></div>
<div class="component"><div class="component-name">Escalating</div><div class="component-score">{{ data.geopolitical.escalating }}</div></div>
<div class="component"><div class="component-name">De-escalating</div><div class="component-score">{{ data.geopolitical.deescalating }}</div></div>
<div class="component"><div class="component-name">Net Gold Impact</div><div class="component-score">{% if data.geopolitical.net_impact>0 %}+{% endif %}{{ data.geopolitical.net_impact }}</div></div>
</div>
<div class="panel" style="margin-top:12px;margin-bottom:12px">
<div class="news-title">{{ data.geopolitical.regime }}</div>
<div class="note">Status: <strong>{{ data.geopolitical.status }}</strong> • GDELT global news: <strong>{{ data.geopolitical.source_stats.gdelt|default(0) }}</strong> • Trump Truth: <strong>{{ data.geopolitical.source_stats.truth|default(0) }}</strong> • Trump X: <strong>{{ data.geopolitical.source_stats.x|default(0) }}</strong> • Uto: <strong>{{ data.geopolitical.source_stats.uto|default(0) }}</strong> • Candidates analyzed: <strong>{{ data.geopolitical.source_stats.candidates|default(0) }}</strong></div>
{% if data.geopolitical.error %}<div class="note" style="color:#e6a36f">Geo engine detail: {{ data.geopolitical.error }}</div>{% endif %}
</div>
<div class="fed-grid">
{% if data.geopolitical.events %}
{% for event in data.geopolitical.events %}
<div class="fed-card">
{% if event.link %}<a href="{{ event.link }}" target="_blank">{% endif %}
<div class="fed-top"><div class="speaker">{{ event.region }}</div><div class="badge">{{ event.category }}</div></div>
{% set geoclass='tone-hawkish' if event.direction=='ESCALATION' else ('tone-dovish' if event.direction=='DE_ESCALATION' else '') %}
<div class="tone {{ geoclass }}">{{ event.direction }} • {{ event.stage }}</div>
<div class="impact">Severity: {{ event.severity }}/100 • Gold relevance: {{ event.gold_relevance }}/100 • Confidence: {{ event.confidence }}% • Gold impact: {% if event.impact>0 %}+{% endif %}{{ event.impact }}</div>
<div class="event-title" style="margin-top:8px">{{ event.summary }}</div>
<div class="note" style="margin-top:8px">Sources: {{ event.source_count }} • {% for s in event.sources %}{{ s }}{% if not loop.last %}, {% endif %}{% endfor %}</div>
<div class="news-meta">{{ event.date or '' }}</div>
{% if event.link %}</a>{% endif %}
</div>
{% endfor %}
{% else %}<div class="panel"><div class="note">No material global geopolitical event has been scored yet.</div></div>{% endif %}
</div>

<div class="section-title">Fed Monitor — Semantic Reading of Latest Stance</div>
<div class="panel" style="margin-bottom:12px">
Federal Reserve Score: <strong>{{ data.fed.score }}/100</strong>
<span class="note"> • {{ data.fed.event_count }} latest policy stances{% if data.fed.candidate_count is defined %} from {{ data.fed.candidate_count }} recent candidate documents{% endif %} • {{ data.fed.mode }}{% if data.fed.model %} • {{ data.fed.model }}{% endif %}</span>
<div class="note">Status: <strong>{{ data.fed.status }}</strong>{% if data.fed.average_stance is defined %} • Weighted stance: {{ data.fed.average_stance }} (-2 dovish → +2 hawkish){% endif %}</div>
{% if data.fed.analyzed_count is defined %}<div class="note">Fed candidate documents: <strong>{{ data.fed.candidate_count }}</strong>{% if data.fed.speaker_bundle_count is defined %} • Speaker bundles sent to AI: <strong>{{ data.fed.speaker_bundle_count }}</strong>{% endif %} • AI analyses returned: <strong>{{ data.fed.analyzed_count }}</strong>{% if data.fed.official_discovered is defined %} • Official discovered: <strong>{{ data.fed.official_discovered }}</strong> • Uto discovered: <strong>{{ data.fed.uto_discovered }}</strong>{% endif %}</div>{% endif %}
{% if data.fed.error %}<div class="note" style="color:#e6a36f">Fed engine detail: {{ data.fed.error }}</div>{% endif %}
<div class="note">Source policy: <strong>Official Federal Reserve System sources are primary</strong>; UtoFX/UtoTimes are secondary for timely quotes/Q&amp;A. If sources conflict, the official Fed source wins.</div>
{% if data.fed.status == 'API KEY MISSING' %}<div class="note" style="margin-top:6px">GROQ_API_KEY is not configured. Fed score is neutralized to 50 until semantic AI is available.</div>{% endif %}
</div>
<div class="fed-grid">
{% if data.fed.events %}
{% for event in data.fed.events %}
<div class="fed-card">
{% if event.link %}<a href="{{ event.link }}" target="_blank">{% endif %}
<div class="fed-top"><div class="speaker">{{ event.speaker }}</div><div class="badge">{{ '2026 VOTER' if event.voter else 'NON-VOTER' }}</div></div>
{% set toneclass='tone-dovish' if 'DOVISH' in event.tone else ('tone-hawkish' if 'HAWKISH' in event.tone else '') %}
<div class="tone {{ toneclass }}">{{ event.tone }}</div>
<div class="impact">Semantic stance: {{ event.stance_score }} • Confidence: {{ event.confidence }}% • Gold impact: {% if event.gold_impact>0 %}+{% endif %}{{ event.gold_impact }}</div>
{% if event.summary %}<div class="event-title" style="margin-top:8px">{{ event.summary }}</div>{% endif %}
<div class="note" style="margin-top:8px">Inflation: <strong>{{ event.inflation_view }}</strong> • Labor: <strong>{{ event.labor_view }}</strong> • Rate path: <strong>{{ event.rate_path_view }}</strong></div>
<div class="event-title" style="margin-top:8px">{{ event.title }}</div><div class="news-meta">{{ event.date or '' }} • {{ event.source }}{% if event.source_type %} • {{ event.source_type }}{% endif %}</div>
{% if event.link %}</a>{% endif %}
</div>
{% endfor %}
{% else %}<div class="panel"><div class="note">No semantic Fed analysis is available yet.</div></div>{% endif %}
</div>

<div class="section-title">Live News Monitor</div><div class="news-grid"><div class="panel"><div class="news-title">UtoFX Telegram</div>{% if data.telegram_news %}{% for news in data.telegram_news %}<div class="news-item">{% if news.link %}<a href="{{ news.link }}" target="_blank">{% endif %}<div class="news-text">{{ news.text }}</div><div class="news-meta">{{ news.date or '' }}</div>{% if news.link %}</a>{% endif %}</div>{% endfor %}{% else %}<div class="note">Telegram feed temporarily unavailable.</div>{% endif %}</div><div class="panel"><div class="news-title">UtoTimes</div>{% if data.utotimes_news %}{% for news in data.utotimes_news %}<div class="news-item">{% if news.link %}<a href="{{ news.link }}" target="_blank">{% endif %}<div class="news-text">{{ news.title }}</div><div class="news-meta">{{ news.date or '' }}</div>{% if news.link %}</a>{% endif %}</div>{% endfor %}{% else %}<div class="note">UtoTimes feed temporarily unavailable.</div>{% endif %}</div></div>

<div class="status">SYSTEM STATUS: <span class="online">{% if data.initializing %}INITIALIZING{% elif data.refreshing %}REFRESHING{% else %}ONLINE{% endif %}</span><div class="note">Last calculation: {{ data.updated }}</div><div class="note">Market refresh: 30 seconds • Fed/Economic/Geopolitical refresh: 5 minutes</div><div class="note">Rates Engine uses official U.S. Treasury nominal CMT yields and basis-point moves: 2Y 50% / 10Y 35% / 30Y 15%. FRED Daily is the fallback. These are latest official daily closes; intraday 2Y confirmation is disabled when only daily data is available.</div><div class="note">Fed Score uses official Federal Reserve System sources as primary and UtoFX/UtoTimes as secondary same-day sources. Official sources win when they overlap. AI compares the latest official/Uto documents speaker-by-speaker and returns one semantic stance per member; keyword repetition does not score hawkishness/dovishness.</div><div class="note">Economic Actuals are isolated by exact UtoTimes event section; Forex Factory is used only as exact-title backup. Explicit revisions are scored separately.</div><div class="note">Geopolitical Score is global: GDELT worldwide news + Trump Truth/X direct statements + Uto secondary reporting. AI clusters duplicate coverage into one event, separates statements/threats from confirmed actions, and applies recency decay.</div></div>
</div><script>setTimeout(function(){window.location.reload();}, {{ 5000 if data.initializing or data.refreshing else 30000 }});</script></body></html>
'''
    return render_template_string(html, data=data)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
