from flask import Flask, jsonify, render_template_string
from datetime import datetime, timezone
from urllib.parse import quote, urljoin
from bs4 import BeautifulSoup
from email.utils import parsedate_to_datetime
import requests
import time
import re
import xml.etree.ElementTree as ET

app = Flask(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 Chrome/120 Safari/537.36"
}

CACHE = {"time": 0, "data": None}
CACHE_SECONDS = 25

FED_CACHE = {"time": 0, "result": None}
FED_CACHE_SECONDS = 300


# =========================================================
# 2026 FOMC VOTERS
# =========================================================

FOMC_VOTERS_2026 = {
    "Kevin Warsh",
    "John Williams",
    "Michael Barr",
    "Michelle Bowman",
    "Lisa Cook",
    "Beth Hammack",
    "Philip Jefferson",
    "Neel Kashkari",
    "Lorie Logan",
    "Anna Paulson",
    "Jerome Powell",
    "Christopher Waller",
}


# =========================================================
# FED SPEAKERS
# Weight = importance inside our GOLD model
# =========================================================

FED_SPEAKERS = {

    "Kevin Warsh": {
        "aliases": [
            "kevin warsh",
            "warsh",
            "کوین وارش",
            "وارش",
        ],
        "weight": 1.50,
    },

    "John Williams": {
        "aliases": [
            "john williams",
            "williams",
            "جان ویلیامز",
            "ویلیامز",
            "ویلیام",
        ],
        "weight": 1.35,
    },

    "Philip Jefferson": {
        "aliases": [
            "philip jefferson",
            "jefferson",
            "فیلیپ جفرسون",
            "جفرسون",
        ],
        "weight": 1.25,
    },

    "Jerome Powell": {
        "aliases": [
            "jerome powell",
            "powell",
            "جروم پاول",
            "پاول",
        ],
        "weight": 1.15,
    },

    "Christopher Waller": {
        "aliases": [
            "christopher waller",
            "waller",
            "کریستوفر والر",
            "والر",
        ],
        "weight": 1.10,
    },

    "Michelle Bowman": {
        "aliases": [
            "michelle bowman",
            "bowman",
            "میشل بومن",
            "بومن",
        ],
        "weight": 1.10,
    },

    "Lisa Cook": {
        "aliases": [
            "lisa cook",
            "cook",
            "لیزا کوک",
            "کوک",
        ],
        "weight": 1.10,
    },

    "Michael Barr": {
        "aliases": [
            "michael barr",
            "barr",
            "مایکل بار",
            "بار",
        ],
        "weight": 1.10,
    },

    "Beth Hammack": {
        "aliases": [
            "beth hammack",
            "hammack",
            "بث همک",
            "همک",
        ],
        "weight": 1.00,
    },

    "Neel Kashkari": {
        "aliases": [
            "neel kashkari",
            "kashkari",
            "نیل کشکاری",
            "کشکاری",
        ],
        "weight": 1.00,
    },

    "Lorie Logan": {
        "aliases": [
            "lorie logan",
            "logan",
            "لوری لوگان",
            "لوگان",
        ],
        "weight": 1.00,
    },

    "Anna Paulson": {
        "aliases": [
            "anna paulson",
            "paulson",
            "آنا پالسون",
            "پالسون",
        ],
        "weight": 1.00,
    },

    "Mary Daly": {
        "aliases": [
            "mary daly",
            "daly",
            "مری دالی",
            "دالی",
        ],
        "weight": 0.75,
    },

    "Austan Goolsbee": {
        "aliases": [
            "austan goolsbee",
            "goolsbee",
            "آستن گولزبی",
            "گولزبی",
        ],
        "weight": 0.75,
    },

    "Thomas Barkin": {
        "aliases": [
            "thomas barkin",
            "barkin",
            "توماس بارکین",
            "بارکین",
        ],
        "weight": 0.75,
    },

    "Susan Collins": {
        "aliases": [
            "susan collins",
            "collins",
            "سوزان کالینز",
            "کالینز",
        ],
        "weight": 0.75,
    },

    "Alberto Musalem": {
        "aliases": [
            "alberto musalem",
            "musalem",
            "آلبرتو موسالم",
            "موسالم",
        ],
        "weight": 0.75,
    },

    "Jeffrey Schmid": {
        "aliases": [
            "jeffrey schmid",
            "schmid",
            "جفری اشمید",
            "اشمید",
        ],
        "weight": 0.75,
    },

}


# =========================================================
# HAWKISH LANGUAGE
# =========================================================

HAWKISH_PHRASES = {

    "further tightening": 3,
    "additional tightening": 3,
    "further rate increase": 3,
    "additional rate increase": 3,
    "need to raise rates": 3,
    "rates may need to rise": 3,

    "inflation remains too high": 2.5,
    "inflation is too high": 2.5,
    "inflation has been too high": 2.5,

    "upside risks to inflation": 2,
    "higher for longer": 2,
    "more restrictive": 2,
    "not ready to cut": 2,
    "premature to cut": 2,

    "persistent inflation": 1.5,
    "price pressures remain": 1.5,
    "more work to do": 1.5,

    "تورم همچنان بالاست": 2.5,
    "تورم هنوز بالاست": 2.5,
    "تورم بیش از حد بالاست": 2.5,

    "نیاز به افزایش نرخ": 3,
    "افزایش بیشتر نرخ": 3,
    "افزایش نرخ بهره": 1.5,

    "نرخ بهره بالاتر": 2,
    "فشار تورمی": 1.5,

    "سیاست انقباضی‌تر": 2,
    "سیاست انقباضی": 1,

    "کاهش نرخ زود است": 2,
    "برای کاهش نرخ زود است": 2,
}


# =========================================================
# DOVISH LANGUAGE
# =========================================================

DOVISH_PHRASES = {

    "no urgency": 3,
    "no rush": 3,

    "can be patient": 2.5,
    "policy can be patient": 2.5,

    "wait and see": 2,

    "hold rates": 2,
    "keep rates unchanged": 2,
    "pause rate": 2,

    "no need to raise": 3,
    "do not need to raise": 3,

    "rate cuts": 2,
    "lower rates": 2,
    "less restrictive": 2,

    "labor market cooling": 2,
    "labour market cooling": 2,

    "downside risks to employment": 2,

    "inflation has eased": 1.5,
    "disinflation": 1.5,

    "نیازی به عجله": 3,
    "عجله‌ای برای افزایش": 3,

    "نیازی به افزایش سریع": 3,
    "نیازی به افزایش": 2.5,

    "صبر کنیم": 2,
    "می‌توانیم صبر کنیم": 2.5,

    "ثابت نگه داشتن نرخ": 2,
    "توقف افزایش نرخ": 2.5,

    "کاهش نرخ بهره": 2,

    "بازار کار ضعیف": 2,
    "بازار کار سرد": 2,

    "کاهش تورم": 1.5,
    "تورم کاهش یافته": 1.5,

    "ریسک اشتغال": 1.5,
}


FED_CONTEXT_TERMS = [

    "federal reserve",
    "fomc",
    "fed ",
    "monetary policy",
    "interest rate",
    "inflation",
    "employment",
    "labor market",
    "labour market",

    "فدرال رزرو",
    "فد ",
    "نرخ بهره",
    "تورم",
    "سیاست پولی",
    "بازار کار",
]


# =========================================================
# HELPERS
# =========================================================

def clamp(value, minimum=0, maximum=100):

    return max(
        minimum,
        min(maximum, value)
    )


def safe_round(value, digits=2):

    if value is None:
        return None

    try:
        return round(
            float(value),
            digits
        )

    except Exception:
        return None


# =========================================================
# MARKET DATA
# =========================================================

def yahoo_market(symbol):

    try:

        encoded = quote(
            symbol,
            safe=""
        )

        url = (
            "https://query1.finance.yahoo.com/"
            "v8/finance/chart/"
            f"{encoded}"
            "?interval=5m&range=1d"
        )

        r = requests.get(
            url,
            headers=HEADERS,
            timeout=8
        )

        r.raise_for_status()

        result = (
            r.json()
            ["chart"]
            ["result"][0]
        )

        meta = result["meta"]

        price = meta.get(
            "regularMarketPrice"
        )

        previous = (
            meta.get("chartPreviousClose")
            or meta.get("previousClose")
        )

        change = None
        change_pct = None

        if (
            price is not None
            and previous
        ):

            change = (
                price - previous
            )

            change_pct = (
                change
                / previous
                * 100
            )

        return {

            "price":
                safe_round(
                    price,
                    3
                ),

            "previous":
                safe_round(
                    previous,
                    3
                ),

            "change":
                safe_round(
                    change,
                    3
                ),

            "change_pct":
                safe_round(
                    change_pct,
                    2
                ),

            "ok": True
        }


    except Exception:

        return {

            "price": None,
            "previous": None,
            "change": None,
            "change_pct": None,
            "ok": False
        }


# =========================================================
# UTOFX TELEGRAM
# =========================================================

def get_utofx_news(limit=12):

    try:

        r = requests.get(
            "https://t.me/s/UtoFx",
            headers=HEADERS,
            timeout=10
        )

        r.raise_for_status()

        soup = BeautifulSoup(
            r.text,
            "html.parser"
        )

        messages = []


        for message in soup.select(
            ".tgme_widget_message"
        ):

            text_box = message.select_one(
                ".tgme_widget_message_text"
            )

            if not text_box:
                continue


            text = " ".join(
                text_box.stripped_strings
            )

            if not text:
                continue


            date_tag = (
                message.select_one(
                    "time"
                )
            )

            link_tag = (
                message.select_one(
                    ".tgme_widget_message_date"
                )
            )


            messages.append({

                "source":
                    "UtoFX Telegram",

                "text":
                    text[:1200],

                "date":
                    (
                        date_tag.get(
                            "datetime"
                        )
                        if date_tag
                        else None
                    ),

                "link":
                    (
                        link_tag.get(
                            "href"
                        )
                        if link_tag
                        else None
                    )
            })


        return (
            messages[-limit:]
            [::-1]
        )


    except Exception:

        return []


# =========================================================
# UTOTIMES
# =========================================================

def get_utotimes_news(limit=8):

    try:

        r = requests.get(
            "https://utotimes.com/feed/",
            headers=HEADERS,
            timeout=10
        )

        r.raise_for_status()

        root = ET.fromstring(
            r.content
        )

        news = []


        for item in (
            root.findall(".//item")
            [:limit]
        ):

            title = (
                item.findtext(
                    "title"
                )
            )

            link = (
                item.findtext(
                    "link"
                )
            )

            date = (
                item.findtext(
                    "pubDate"
                )
            )


            if title:

                news.append({

                    "source":
                        "UtoTimes",

                    "text":
                        title.strip(),

                    "date":
                        date,

                    "link":
                        link
                })


        return news


    except Exception:

        return []


# =========================================================
# DATE / RECENCY
# =========================================================

def parse_date(value):

    if not value:
        return None


    try:

        dt = datetime.fromisoformat(
            value.replace(
                "Z",
                "+00:00"
            )
        )

        if dt.tzinfo is None:

            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(
            timezone.utc
        )


    except Exception:
        pass


    try:

        dt = parsedate_to_datetime(
            value
        )

        if dt.tzinfo is None:

            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(
            timezone.utc
        )


    except Exception:

        return None


def recency_weight(date_value):

    dt = parse_date(
        date_value
    )

    if not dt:

        return 0.45


    hours = max(

        0,

        (
            datetime.now(
                timezone.utc
            )
            - dt
        ).total_seconds()
        / 3600
    )


    if hours <= 6:
        return 1.00

    if hours <= 24:
        return 0.85

    if hours <= 72:
        return 0.60

    if hours <= 168:
        return 0.35

    return 0.15


# =========================================================
# SPEAKER DETECTION
# =========================================================

def detect_speaker(text):

    lower = text.lower()


    for speaker, info in (
        FED_SPEAKERS.items()
    ):

        for alias in (
            info["aliases"]
        ):

            if (
                alias.lower()
                in lower
            ):

                return speaker


    return None


def has_fed_context(text):

    lower = text.lower()


    if detect_speaker(text):

        return True


    return any(

        term.lower()
        in lower

        for term
        in FED_CONTEXT_TERMS
    )


# =========================================================
# LANGUAGE SCORING
# =========================================================

def phrase_score(
    text,
    phrase_map
):

    lower = re.sub(
        r"\s+",
        " ",
        text.lower()
    )

    total = 0.0


    for phrase, weight in (
        phrase_map.items()
    ):

        count = lower.count(
            phrase.lower()
        )

        if count:

            total += (
                count
                * weight
            )


    return total


# =========================================================
# FED TEXT ANALYSIS
# =========================================================

def analyze_fed_text(
    text,
    source="News",
    date=None,
    title=None,
    link=None
):

    if (
        not text
        or not has_fed_context(
            text
        )
    ):

        return None


    speaker = (
        detect_speaker(text)
        or "Federal Reserve"
    )


    hawkish = phrase_score(
        text,
        HAWKISH_PHRASES
    )


    dovish = phrase_score(
        text,
        DOVISH_PHRASES
    )


    raw_signal = (
        dovish
        - hawkish
    )


    raw_signal = max(
        -6,
        min(
            6,
            raw_signal
        )
    )


    if raw_signal >= 2:

        tone = "DOVISH"


    elif raw_signal >= 0.75:

        tone = "SLIGHTLY DOVISH"


    elif raw_signal <= -2:

        tone = "HAWKISH"


    elif raw_signal <= -0.75:

        tone = "SLIGHTLY HAWKISH"


    else:

        tone = "NEUTRAL"


    speaker_weight = (

        FED_SPEAKERS
        .get(
            speaker,
            {}
        )
        .get(
            "weight",
            0.70
        )
    )


    if source in [
        "Federal Reserve",
        "New York Fed"
    ]:

        source_weight = 1.00


    elif source == "UtoFX Telegram":

        source_weight = 0.85


    else:

        source_weight = 0.80


    age_weight = recency_weight(
        date
    )


    gold_impact = (

        raw_signal
        * speaker_weight
        * source_weight
        * age_weight
    )


    return {

        "speaker":
            speaker,

        "tone":
            tone,

        "raw_signal":
            round(
                raw_signal,
                2
            ),

        "hawkish":
            round(
                hawkish,
                2
            ),

        "dovish":
            round(
                dovish,
                2
            ),

        "gold_impact":
            round(
                gold_impact,
                2
            ),

        "source":
            source,

        "date":
            date,

        "title":
            (
                title
                or text[:180]
            ),

        "link":
            link,

        "voter":
            (
                speaker
                in FOMC_VOTERS_2026
            )
    }


# =========================================================
# FETCH FULL SPEECH
# =========================================================

def fetch_page_text(url):

    try:

        r = requests.get(
            url,
            headers=HEADERS,
            timeout=10
        )

        r.raise_for_status()

        soup = BeautifulSoup(
            r.text,
            "html.parser"
        )


        for tag in soup([
            "script",
            "style",
            "nav",
            "footer"
        ]):

            tag.decompose()


        main = (
            soup.find("main")
            or soup.find(
                id="content"
            )
            or soup
        )


        paragraphs = [

            p.get_text(
                " ",
                strip=True
            )

            for p
            in main.find_all("p")
        ]


        return (
            " ".join(
                paragraphs
            )
            [:30000]
        )


    except Exception:

        return ""


# =========================================================
# OFFICIAL FED SPEECH RSS
# =========================================================

def get_board_speeches(
    limit=5
):

    items = []


    try:

        r = requests.get(

            "https://www.federalreserve.gov/"
            "feeds/speeches.xml",

            headers=HEADERS,
            timeout=10
        )

        r.raise_for_status()

        root = ET.fromstring(
            r.content
        )


        for item in (
            root.findall(
                ".//item"
            )
            [:limit]
        ):

            title = (
                item.findtext(
                    "title"
                )
                or ""
            ).strip()


            link = (
                item.findtext(
                    "link"
                )
                or ""
            ).strip()


            date = (
                item.findtext(
                    "pubDate"
                )
                or ""
            ).strip()


            description = (
                item.findtext(
                    "description"
                )
                or ""
            ).strip()


            body = (
                fetch_page_text(
                    link
                )
                if link
                else ""
            )


            full_text = " ".join([

                title,
                description,
                body
            ])


            analyzed = analyze_fed_text(

                full_text,

                source=
                    "Federal Reserve",

                date=date,

                title=title,

                link=link
            )


            if analyzed:

                items.append(
                    analyzed
                )


    except Exception:

        pass


    return items


# =========================================================
# WILLIAMS / NEW YORK FED
# =========================================================

def get_williams_speeches(
    limit=2
):

    items = []


    try:

        index_url = (
            "https://www.newyorkfed.org/"
            "newsevents/speeches/index"
        )


        r = requests.get(
            index_url,
            headers=HEADERS,
            timeout=10
        )

        r.raise_for_status()


        soup = BeautifulSoup(
            r.text,
            "html.parser"
        )


        seen = set()


        for a in soup.find_all(
            "a",
            href=True
        ):

            label = " ".join(
                a.stripped_strings
            )

            href = a.get(
                "href",
                ""
            )


            if (
                "Williams:"
                not in label
                and "Williams"
                not in label
            ):

                continue


            if (
                "/newsevents/speeches/2026/"
                not in href
            ):

                continue


            link = urljoin(
                index_url,
                href
            )


            if link in seen:

                continue


            seen.add(
                link
            )


            body = fetch_page_text(
                link
            )


            analyzed = analyze_fed_text(

                f"{label} {body}",

                source=
                    "New York Fed",

                date=None,

                title=label,

                link=link
            )


            if analyzed:

                items.append(
                    analyzed
                )


            if (
                len(items)
                >= limit
            ):

                break


    except Exception:

        pass


    return items


# =========================================================
# FED MASTER ENGINE
# =========================================================

def get_fed_monitor(
    telegram_news,
    utotimes_news
):

    now = time.time()


    if (

        FED_CACHE["result"]
        is not None

        and
        now
        - FED_CACHE["time"]
        < FED_CACHE_SECONDS

    ):

        return FED_CACHE[
            "result"
        ]


    events = []


    # Official Board speeches

    events.extend(
        get_board_speeches(
            5
        )
    )


    # Williams / NY Fed

    events.extend(
        get_williams_speeches(
            2
        )
    )


    # UtoFX news

    for item in telegram_news:

        analyzed = analyze_fed_text(

            item["text"],

            source=
                item["source"],

            date=
                item.get(
                    "date"
                ),

            title=
                item["text"][:180],

            link=
                item.get(
                    "link"
                )
        )


        if analyzed:

            events.append(
                analyzed
            )


    # UtoTimes news

    for item in utotimes_news:

        analyzed = analyze_fed_text(

            item["text"],

            source=
                item["source"],

            date=
                item.get(
                    "date"
                ),

            title=
                item["text"][:180],

            link=
                item.get(
                    "link"
                )
        )


        if analyzed:

            events.append(
                analyzed
            )


    # Remove duplicate events

    unique = []

    seen = set()


    for event in events:

        key = (

            event.get(
                "speaker"
            ),

            event.get(
                "title"
            ),

            event.get(
                "link"
            )
        )


        if key in seen:

            continue


        seen.add(
            key
        )


        unique.append(
            event
        )


    # Newest first

    unique.sort(

        key=lambda x:

            parse_date(
                x.get(
                    "date"
                )
            )

            or datetime(
                2000,
                1,
                1,
                tzinfo=
                    timezone.utc
            ),

        reverse=True
    )


    # Last 12 relevant Fed items influence score

    total_impact = sum(

        event[
            "gold_impact"
        ]

        for event
        in unique[:12]
    )


    fed_score = clamp(

        50
        + total_impact
        * 2.2
    )


    fed_score = round(
        fed_score,
        1
    )


    result = {

        "score":
            fed_score,

        "events":
            unique[:8],

        "event_count":
            len(unique)
    }


    FED_CACHE["time"] = now

    FED_CACHE[
        "result"
    ] = result


    return result


# =========================================================
# GOLD SCORE
# =========================================================

def calculate_scores(
    markets,
    fed_score
):

    gold_change = (
        markets["gold"]
        .get(
            "change_pct"
        )
        or 0
    )


    dxy_change = (
        markets["dxy"]
        .get(
            "change_pct"
        )
        or 0
    )


    y2_change = (
        markets["us2y"]
        .get(
            "change_pct"
        )
        or 0
    )


    y10_change = (
        markets["us10y"]
        .get(
            "change_pct"
        )
        or 0
    )


    y30_change = (
        markets["us30y"]
        .get(
            "change_pct"
        )
        or 0
    )


    oil_change = (
        markets["oil"]
        .get(
            "change_pct"
        )
        or 0
    )


    vix_change = (
        markets["vix"]
        .get(
            "change_pct"
        )
        or 0
    )


    # Dollar rising = pressure on Gold

    dollar_score = clamp(

        50
        - dxy_change
        * 18
    )


    # Yields rising = pressure on Gold

    average_rate_move = (

        y2_change
        + y10_change
        + y30_change

    ) / 3


    rates_score = clamp(

        50
        - average_rate_move
        * 10
    )


    # Gold momentum

    technical_score = clamp(

        50
        + gold_change
        * 12
    )


    # Risk / VIX

    market_flow_score = clamp(

        50
        + vix_change
        * 1.5
    )


    # Oil / inflation pressure

    oil_score = clamp(

        50
        - oil_change
        * 3
    )


    # Next stages

    economic_score = 50

    geopolitical_score = 50


    components = {

        "Economic Data":
            round(
                economic_score,
                1
            ),

        "Federal Reserve":
            round(
                fed_score,
                1
            ),

        "Rates":
            round(
                rates_score,
                1
            ),

        "US Dollar":
            round(
                dollar_score,
                1
            ),

        "Geopolitical Risk":
            round(
                geopolitical_score,
                1
            ),

        "Oil / Inflation":
            round(
                oil_score,
                1
            ),

        "Market Flow":
            round(
                market_flow_score,
                1
            ),

        "Technical":
            round(
                technical_score,
                1
            )
    }


    weights = {

        "Economic Data": 0.20,

        "Federal Reserve": 0.20,

        "Rates": 0.15,

        "US Dollar": 0.15,

        "Geopolitical Risk": 0.10,

        "Oil / Inflation": 0.07,

        "Market Flow": 0.05,

        "Technical": 0.08
    }


    total = round(

        sum(

            components[name]
            * weights[name]

            for name
            in components
        ),

        1
    )


    if total >= 75:

        bias = (
            "STRONGLY BULLISH"
        )


    elif total >= 60:

        bias = "BULLISH"


    elif total >= 54:

        bias = (
            "SLIGHTLY BULLISH"
        )


    elif total <= 25:

        bias = (
            "STRONGLY BEARISH"
        )


    elif total <= 40:

        bias = "BEARISH"


    elif total <= 46:

        bias = (
            "SLIGHTLY BEARISH"
        )


    else:

        bias = "NEUTRAL"


    return (
        total,
        bias,
        components
    )


# =========================================================
# BUILD DASHBOARD DATA
# =========================================================

def build_dashboard_data():

    now = time.time()


    if (

        CACHE["data"]
        is not None

        and

        now
        - CACHE["time"]
        < CACHE_SECONDS

    ):

        return CACHE["data"]


    markets = {

        "gold":
            yahoo_market(
                "GC=F"
            ),

        "dxy":
            yahoo_market(
                "DX-Y.NYB"
            ),

        "us2y":
            yahoo_market(
                "2YY=F"
            ),

        "us10y":
            yahoo_market(
                "^TNX"
            ),

        "us30y":
            yahoo_market(
                "^TYX"
            ),

        "oil":
            yahoo_market(
                "CL=F"
            ),

        "vix":
            yahoo_market(
                "^VIX"
            )
    }


    telegram_news = (
        get_utofx_news(
            12
        )
    )


    utotimes_news = (
        get_utotimes_news(
            8
        )
    )


    fed = get_fed_monitor(

        telegram_news,
        utotimes_news
    )


    (
        score,
        bias,
        components

    ) = calculate_scores(

        markets,
        fed["score"]
    )


    data = {

        "score":
            score,

        "bias":
            bias,

        "components":
            components,

        "markets":
            markets,

        "fed":
            fed,

        "telegram_news":
            telegram_news[:8],

        "utotimes_news":
            utotimes_news[:5],

        "updated":

            datetime.now(
                timezone.utc
            )
            .strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )
    }


    CACHE["time"] = now

    CACHE["data"] = data


    return data


# =========================================================
# API
# =========================================================

@app.route(
    "/api/status"
)

def api_status():

    return jsonify(
        build_dashboard_data()
    )


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/")

def dashboard():

    data = build_dashboard_data()


    html = """
<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">

<meta name="viewport"
content="width=device-width,initial-scale=1">

<title>
FINAD Gold Intelligence
</title>


<style>

*{
box-sizing:border-box
}

body{
margin:0;
background:#080b12;
color:#fff;
font-family:Arial,Helvetica,sans-serif
}

.container{
max-width:1250px;
margin:auto;
padding:30px 20px 60px
}

.brand{
font-size:14px;
letter-spacing:4px;
color:#d8b96c;
font-weight:bold
}

h1{
margin:8px 0 5px;
font-size:clamp(28px,5vw,42px)
}

.subtitle{
color:#8f98aa;
margin-bottom:25px
}

.hero,
.panel,
.market-card,
.component{
background:#10151f;
border:1px solid #222a39;
border-radius:14px
}

.hero{
padding:35px;
text-align:center;
border-radius:18px
}

.score-title{
color:#8f98aa;
font-size:13px;
letter-spacing:2px
}

.score{
font-size:clamp(60px,10vw,95px);
font-weight:bold;
margin-top:5px
}

.score span{
font-size:22px;
color:#6f7888
}

.bias{
display:inline-block;
padding:9px 18px;
border-radius:30px;
background:#1a2130;
color:#d8b96c;
font-weight:bold
}

.bar{
max-width:650px;
height:10px;
background:#252c39;
border-radius:10px;
overflow:hidden;
margin:30px auto 5px
}

.bar-fill{
height:100%;
width:{{ data.score }}%;
background:linear-gradient(
90deg,
#c84a4a,
#d8b96c,
#51b77a
)
}

.scale{
max-width:650px;
margin:auto;
display:flex;
justify-content:space-between;
font-size:11px;
color:#727b8b
}

.section-title{
margin:35px 0 15px;
font-size:21px
}

.market-grid{
display:grid;
grid-template-columns:
repeat(auto-fit,minmax(155px,1fr));
gap:12px
}

.market-card{
padding:17px
}

.market-title,
.component-name{
color:#8e98a9;
font-size:13px
}

.market-price{
font-size:25px;
font-weight:bold;
margin-top:8px
}

.positive{
color:#55c987
}

.negative{
color:#e46c6c
}

.neutral{
color:#9099a8
}

.components{
display:grid;
grid-template-columns:
repeat(auto-fit,minmax(210px,1fr));
gap:12px
}

.component{
padding:18px
}

.component-score{
font-size:29px;
font-weight:bold;
margin-top:8px
}

.fed-grid{
display:grid;
grid-template-columns:
repeat(auto-fit,minmax(260px,1fr));
gap:12px
}

.fed-card{
background:#10151f;
border:1px solid #222a39;
border-radius:14px;
padding:17px
}

.fed-top{
display:flex;
align-items:center;
justify-content:space-between;
gap:12px
}

.speaker{
font-weight:bold;
font-size:16px
}

.badge{
font-size:10px;
padding:5px 8px;
border-radius:12px;
background:#1a2130;
color:#8fa0b8
}

.tone{
font-size:13px;
font-weight:bold;
margin-top:8px
}

.tone-dovish{
color:#55c987
}

.tone-hawkish{
color:#e46c6c
}

.tone-neutral{
color:#d8b96c
}

.impact{
font-size:12px;
color:#9ca6b6;
margin-top:7px
}

.event-title{
font-size:12px;
color:#8792a3;
line-height:1.5;
margin-top:9px
}

.news-grid{
display:grid;
grid-template-columns:1fr 1fr;
gap:18px
}

.panel{
padding:20px
}

.news-title{
font-size:18px;
font-weight:bold;
margin-bottom:15px
}

.news-item{
border-top:1px solid #222a39;
padding:14px 0
}

.news-item:first-of-type{
border-top:0
}

.news-text{
font-size:14px;
line-height:1.7;
direction:rtl;
text-align:right
}

.news-meta{
font-size:11px;
color:#707a8b;
margin-top:7px
}

.news-item a,
.fed-card a{
color:inherit;
text-decoration:none
}

.status{
margin-top:25px;
background:#10151f;
border:1px solid #222a39;
border-radius:14px;
padding:18px
}

.online{
color:#55c987;
font-weight:bold
}

.note{
color:#778192;
font-size:12px;
line-height:1.6;
margin-top:10px
}

@media(max-width:750px){

.news-grid{
grid-template-columns:1fr
}

}

</style>

</head>


<body>


<div class="container">


<div class="brand">
FINAD
</div>


<h1>
Gold Intelligence Indicator
</h1>


<div class="subtitle">
Macro • Fed • Rates • Dollar • Geopolitics • Market Data
</div>


<div class="hero">


<div class="score-title">
GOLD INTELLIGENCE SCORE
</div>


<div class="score">

{{ data.score }}

<span>
/100
</span>

</div>


<div class="bias">
{{ data.bias }}
</div>


<div class="bar">

<div class="bar-fill">
</div>

</div>


<div class="scale">

<span>
BEARISH
</span>

<span>
NEUTRAL
</span>

<span>
BULLISH
</span>

</div>


</div>


<div class="section-title">
Live Markets
</div>


<div class="market-grid">


{% set names = {

'gold':'Gold Futures',

'dxy':'DXY',

'us2y':'US 2Y',

'us10y':'US 10Y',

'us30y':'US 30Y',

'oil':'WTI Oil',

'vix':'VIX'

} %}


{% for key,item in data.markets.items() %}


<div class="market-card">


<div class="market-title">
{{ names[key] }}
</div>


<div class="market-price">

{{ item.price if item.price is not none else 'N/A' }}

</div>


{% if item.change_pct is not none %}


<div class="
{% if item.change_pct > 0 %}
positive
{% elif item.change_pct < 0 %}
negative
{% else %}
neutral
{% endif %}
">


{% if item.change_pct > 0 %}
+
{% endif %}

{{ item.change_pct }}%

</div>


{% else %}


<div class="neutral">
Data unavailable
</div>


{% endif %}


</div>


{% endfor %}


</div>


<div class="section-title">
Gold Score Components
</div>


<div class="components">


{% for name,value in data.components.items() %}


<div class="component">


<div class="component-name">
{{ name }}
</div>


<div class="component-score">

{{ value }}

<span style="
font-size:14px;
color:#697282
">

/100

</span>


</div>


</div>


{% endfor %}


</div>


<div class="section-title">
Fed Monitor
</div>


<div class="panel"
style="margin-bottom:12px">


Federal Reserve Score:

<strong>

{{ data.fed.score }}/100

</strong>


<span class="note">

• {{ data.fed.event_count }}
relevant Fed items detected

</span>


</div>


<div class="fed-grid">


{% if data.fed.events %}


{% for event in data.fed.events %}


<div class="fed-card">


{% if event.link %}

<a
href="{{ event.link }}"
target="_blank">

{% endif %}


<div class="fed-top">


<div class="speaker">

{{ event.speaker }}

</div>


<div class="badge">

{{ '2026 VOTER'
if event.voter
else 'NON-VOTER / GENERIC' }}

</div>


</div>


{% set toneclass =
'tone-neutral' %}


{% if 'DOVISH'
in event.tone %}

{% set toneclass =
'tone-dovish' %}

{% elif 'HAWKISH'
in event.tone %}

{% set toneclass =
'tone-hawkish' %}

{% endif %}


<div class="tone {{ toneclass }}">

{{ event.tone }}

</div>


<div class="impact">

Gold impact:

{% if event.gold_impact > 0 %}
+
{% endif %}

{{ event.gold_impact }}

• {{ event.source }}

</div>


<div class="event-title">

{{ event.title }}

</div>


<div class="news-meta">

{{ event.date or '' }}

</div>


{% if event.link %}

</a>

{% endif %}


</div>


{% endfor %}


{% else %}


<div class="panel">

<div class="note">

No Fed items detected yet.

</div>

</div>


{% endif %}


</div>


<div class="section-title">
Live News Monitor
</div>


<div class="news-grid">


<div class="panel">


<div class="news-title">
UtoFX Telegram
</div>


{% if data.telegram_news %}


{% for news in data.telegram_news %}


<div class="news-item">


{% if news.link %}

<a
href="{{ news.link }}"
target="_blank">

{% endif %}


<div class="news-text">

{{ news.text }}

</div>


<div class="news-meta">

{{ news.date or '' }}

</div>


{% if news.link %}

</a>

{% endif %}


</div>


{% endfor %}


{% else %}


<div class="note">

Telegram feed temporarily unavailable.

</div>


{% endif %}


</div>


<div class="panel">


<div class="news-title">
UtoTimes
</div>


{% if data.utotimes_news %}


{% for news in data.utotimes_news %}


<div class="news-item">


{% if news.link %}

<a
href="{{ news.link }}"
target="_blank">

{% endif %}


<div class="news-text">

{{ news.text }}

</div>


<div class="news-meta">

{{ news.date or '' }}

</div>


{% if news.link %}

</a>

{% endif %}


</div>


{% endfor %}


{% else %}


<div class="note">

UtoTimes feed temporarily unavailable.

</div>


{% endif %}


</div>


</div>


<div class="status">


SYSTEM STATUS:

<span class="online">
ONLINE
</span>


<div class="note">

Last calculation:
{{ data.updated }}

</div>


<div class="note">

Market dashboard refresh:
30 seconds

</div>


<div class="note">

Fed analysis refresh:
5 minutes

</div>


<div class="note">

Fed Engine uses official Federal Reserve speeches,
New York Fed Williams speeches,
UtoFX and UtoTimes.

No paid AI API is used.

</div>


<div class="note">

Economic Data and Geopolitical Risk
remain at 50 until the next stages.

</div>


</div>


</div>


<script>

setTimeout(

function(){

window.location.reload();

},

30000

);

</script>


</body>

</html>
"""


    return render_template_string(

        html,

        data=data
    )


if __name__ == "__main__":

    app.run(

        host="0.0.0.0",

        port=10000
    )
