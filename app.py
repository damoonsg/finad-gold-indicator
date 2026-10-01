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
TREASURY_CACHE_SECONDS = 60
FED_CACHE = {"time": 0, "result": None}
FED_CACHE_SECONDS = 300
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


def treasury_spot_curve():
    """Return 2Y/10Y/30Y spot Treasury yields from one consistent source.

    MarketWatch is attempted first. All three tenors are fetched concurrently
    so one slow endpoint cannot make the page wait 30+ seconds. If any live
    quote fails, all three tenors fall back together to FRED daily data, also
    fetched concurrently.
    """
    now = time.time()

    if (
        TREASURY_CACHE["data"] is not None
        and now - TREASURY_CACHE["time"] < TREASURY_CACHE_SECONDS
    ):
        return TREASURY_CACHE["data"]

    tenors = ("2Y", "10Y", "30Y")
    curve = None

    try:
        live_curve = {}
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(_marketwatch_treasury_quote, tenor): tenor for tenor in tenors}
            for future in as_completed(futures):
                tenor = futures[future]
                live_curve[tenor] = future.result()
        if all(live_curve.get(x, {}).get("ok") for x in tenors):
            curve = {x: live_curve[x] for x in tenors}
    except Exception:
        curve = None

    if curve is None:
        try:
            series_map = {"2Y": "DGS2", "10Y": "DGS10", "30Y": "DGS30"}
            fred_raw = {}
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures = {pool.submit(_fred_series_latest, sid): tenor for tenor, sid in series_map.items()}
                for future in as_completed(futures):
                    tenor = futures[future]
                    fred_raw[tenor] = future.result()

            curve = {}
            for tenor in tenors:
                current, previous, current_date, previous_date = fred_raw[tenor]
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
        except Exception:
            curve = {
                tenor: {
                    "price": None, "previous": None, "change": None,
                    "change_pct": None, "change_bps": None, "ok": False,
                    "source": "Unavailable", "tenor": tenor,
                }
                for tenor in tenors
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
# FED ENGINE
# =========================================================


def has_strict_fed_context(text):
    lower = normalize_text(text)
    return any(term in lower for term in STRICT_FED_CONTEXT)


def detect_speaker(text, official_source=False):
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


def phrase_score(text, phrase_map):
    lower = normalize_text(text)
    return sum(lower.count(normalize_text(phrase)) * weight for phrase, weight in phrase_map.items())


def fed_recency_weight(date_value):
    hours = hours_since(date_value)
    if hours is None or hours > 168:
        return 0.0
    if hours <= 24:
        return 1.00
    if hours <= 72:
        return 0.70
    return 0.35


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


def analyze_fed_text(text, source, date=None, title=None, link=None, official_source=False):
    if not text:
        return None
    if not official_source and not has_strict_fed_context(text):
        return None
    speaker = detect_speaker(text, official_source=official_source)
    if not speaker:
        return None
    age_weight = fed_recency_weight(date)
    if age_weight <= 0:
        return None
    hawkish = phrase_score(text, HAWKISH_PHRASES)
    dovish = phrase_score(text, DOVISH_PHRASES)
    raw_signal = max(-6.0, min(6.0, dovish - hawkish))
    if abs(raw_signal) < 0.75:
        return None
    if raw_signal >= 2:
        tone = "DOVISH"
    elif raw_signal >= 0.75:
        tone = "SLIGHTLY DOVISH"
    elif raw_signal <= -2:
        tone = "HAWKISH"
    else:
        tone = "SLIGHTLY HAWKISH"
    speaker_weight = FED_SPEAKERS.get(speaker, {}).get("weight", 0.70)
    source_weight = 1.00 if official_source else (0.85 if source == "UtoFX Telegram" else 0.80)
    gold_impact = raw_signal * speaker_weight * source_weight * age_weight
    return {
        "speaker": speaker,
        "tone": tone,
        "raw_signal": round(raw_signal, 2),
        "gold_impact": round(gold_impact, 2),
        "source": source,
        "date": date,
        "title": (title or text[:180]).strip(),
        "link": link,
        "voter": speaker in FOMC_VOTERS_2026,
    }


def get_board_speeches(limit=8):
    items = []
    try:
        r = requests.get("https://www.federalreserve.gov/feeds/speeches.xml", headers=HEADERS, timeout=10)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        for item in root.findall(".//item")[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            date = (item.findtext("pubDate") or "").strip()
            description = (item.findtext("description") or "").strip()
            body, page_date = fetch_page(link) if link else ("", None)
            date = date or page_date
            analyzed = analyze_fed_text(
                f"{title} {description} {body}",
                source="Federal Reserve", date=date, title=title,
                link=link or None, official_source=True,
            )
            if analyzed:
                items.append(analyzed)
    except Exception:
        pass
    return items


def get_williams_speeches(limit=5):
    items = []
    try:
        index_url = "https://www.newyorkfed.org/newsevents/speeches/index"
        r = requests.get(index_url, headers=HEADERS, timeout=10)
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
            analyzed = analyze_fed_text(
                f"{label} {body}", source="New York Fed", date=date,
                title=label, link=link, official_source=True,
            )
            if analyzed:
                items.append(analyzed)
            if len(items) >= limit:
                break
    except Exception:
        pass
    return items


def event_similarity(a, b):
    if a.get("speaker") != b.get("speaker"):
        return 0.0
    ta = normalize_text(a.get("title", ""))[:500]
    tb = normalize_text(b.get("title", ""))[:500]
    if not ta or not tb:
        return 0.0
    return SequenceMatcher(None, ta, tb).ratio()


def dedupe_fed_events(events):
    priority = {"Federal Reserve": 3, "New York Fed": 3, "UtoFX Telegram": 2, "UtoTimes": 1}
    ordered = sorted(events, key=lambda e: priority.get(e.get("source"), 0), reverse=True)
    unique = []
    for event in ordered:
        duplicate = False
        for existing in unique:
            same_link = event.get("link") and existing.get("link") and event["link"] == existing["link"]
            if same_link or event_similarity(event, existing) >= 0.78:
                duplicate = True
                break
        if not duplicate:
            unique.append(event)
    unique.sort(key=lambda x: parse_date(x.get("date")) or datetime(2000, 1, 1, tzinfo=timezone.utc), reverse=True)
    return unique


def latest_stance_per_speaker(events):
    latest = {}
    for event in events:
        speaker = event.get("speaker")
        dt = parse_date(event.get("date"))
        if not speaker or not dt:
            continue
        if speaker not in latest or dt > parse_date(latest[speaker].get("date")):
            latest[speaker] = event
    result = list(latest.values())
    result.sort(key=lambda x: parse_date(x.get("date")) or datetime(2000, 1, 1, tzinfo=timezone.utc), reverse=True)
    return result


def get_fed_monitor(telegram_news, utotimes_news):
    now = time.time()
    if FED_CACHE["result"] is not None and now - FED_CACHE["time"] < FED_CACHE_SECONDS:
        return FED_CACHE["result"]
    events = []
    events.extend(get_board_speeches(8))
    events.extend(get_williams_speeches(5))
    for item in telegram_news:
        analyzed = analyze_fed_text(item["text"], source=item["source"], date=item.get("date"), title=item["text"][:220], link=item.get("link"), official_source=False)
        if analyzed:
            events.append(analyzed)
    for item in utotimes_news:
        analyzed = analyze_fed_text(item.get("title", ""), source="UtoTimes", date=item.get("date"), title=item.get("title", ""), link=item.get("link"), official_source=False)
        if analyzed:
            events.append(analyzed)
    unique = dedupe_fed_events(events)
    latest = latest_stance_per_speaker(unique)
    total_impact = sum(event["gold_impact"] for event in latest)
    fed_score = round(clamp(50 + total_impact * 2.2), 1)
    result = {"score": fed_score, "events": latest[:8], "event_count": len(latest)}
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


def calculate_scores(markets, fed_score, economic_score):
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
        "Geopolitical Risk": 50.0,
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
    telegram_news = get_utofx_news(12)
    utotimes_news = get_utotimes_news(8)
    fed = get_fed_monitor(telegram_news, utotimes_news)
    economic = get_economic_monitor(markets["us2y"].get("change_bps"))
    score, bias, components, rates_engine = calculate_scores(markets, fed["score"], economic["score"])
    data = {
        "score": score, "bias": bias, "components": components, "markets": markets,
        "rates": rates_engine, "economic": economic, "fed": fed, "telegram_news": telegram_news[:8],
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
        "fed": {"score": 50.0, "events": [], "event_count": 0},
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
<div class="panel" style="margin-top:12px"><div class="news-title">Rates Regime</div><div class="note"><strong>{{ data.rates.regime }}</strong> • Weighting: 2Y 50% / 10Y 35% / 30Y 15%. Positive bps means yields are rising and is a headwind for gold.</div><div class="note">Treasury source: <strong>{{ data.markets.us2y.source or "Unknown" }}</strong></div></div>

<div class="section-title">Gold Score Components</div><div class="components">{% for name,value in data.components.items() %}<div class="component"><div class="component-name">{{ name }}</div><div class="component-score">{{ value }} <span style="font-size:14px;color:#697282">/100</span></div></div>{% endfor %}</div>

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

<div class="section-title">Fed Monitor — Latest Stance Per Speaker</div><div class="panel" style="margin-bottom:12px">Federal Reserve Score: <strong>{{ data.fed.score }}/100</strong> <span class="note">• {{ data.fed.event_count }} current non-neutral speaker stances</span></div><div class="fed-grid">
{% if data.fed.events %}{% for event in data.fed.events %}<div class="fed-card">{% if event.link %}<a href="{{ event.link }}" target="_blank">{% endif %}<div class="fed-top"><div class="speaker">{{ event.speaker }}</div><div class="badge">{{ '2026 VOTER' if event.voter else 'NON-VOTER' }}</div></div>{% set toneclass='tone-dovish' if 'DOVISH' in event.tone else 'tone-hawkish' %}<div class="tone {{ toneclass }}">{{ event.tone }}</div><div class="impact">Gold impact: {% if event.gold_impact>0 %}+{% endif %}{{ event.gold_impact }} • {{ event.source }}</div><div class="event-title">{{ event.title }}</div><div class="news-meta">{{ event.date or '' }}</div>{% if event.link %}</a>{% endif %}</div>{% endfor %}{% else %}<div class="panel"><div class="note">No current non-neutral Fed stance detected.</div></div>{% endif %}
</div>

<div class="section-title">Live News Monitor</div><div class="news-grid"><div class="panel"><div class="news-title">UtoFX Telegram</div>{% if data.telegram_news %}{% for news in data.telegram_news %}<div class="news-item">{% if news.link %}<a href="{{ news.link }}" target="_blank">{% endif %}<div class="news-text">{{ news.text }}</div><div class="news-meta">{{ news.date or '' }}</div>{% if news.link %}</a>{% endif %}</div>{% endfor %}{% else %}<div class="note">Telegram feed temporarily unavailable.</div>{% endif %}</div><div class="panel"><div class="news-title">UtoTimes</div>{% if data.utotimes_news %}{% for news in data.utotimes_news %}<div class="news-item">{% if news.link %}<a href="{{ news.link }}" target="_blank">{% endif %}<div class="news-text">{{ news.title }}</div><div class="news-meta">{{ news.date or '' }}</div>{% if news.link %}</a>{% endif %}</div>{% endfor %}{% else %}<div class="note">UtoTimes feed temporarily unavailable.</div>{% endif %}</div></div>

<div class="status">SYSTEM STATUS: <span class="online">{% if data.initializing %}INITIALIZING{% elif data.refreshing %}REFRESHING{% else %}ONLINE{% endif %}</span><div class="note">Last calculation: {{ data.updated }}</div><div class="note">Market refresh: 30 seconds • Fed/Economic refresh: 5 minutes</div><div class="note">Rates Engine uses spot Treasury yields and basis-point moves: 2Y 50% / 10Y 35% / 30Y 15%. Primary source: MarketWatch; all three tenors fall back together to FRED daily if live parsing is unavailable. Economic 2Y confirmation also uses basis points.</div><div class="note">Fed Score uses only the latest dated stance from each speaker within 7 days. Economic Actuals are isolated by exact UtoTimes event section; Forex Factory is used only as exact-title backup. Explicit revisions are scored separately.</div><div class="note">Geopolitical Risk remains 50 until the next stage.</div></div>
</div><script>setTimeout(function(){window.location.reload();}, {{ 5000 if data.initializing or data.refreshing else 30000 }});</script></body></html>
'''
    return render_template_string(html, data=data)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
