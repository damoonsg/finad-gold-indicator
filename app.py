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
#
# Full names can be detected directly.
# Short surnames ONLY count if the text clearly refers to
# the U.S. Federal Reserve.
# =========================================================

FED_SPEAKERS = {

    "Kevin Warsh": {
        "full": [
            "kevin warsh",
            "کوین وارش"
        ],
        "short": [
            "warsh",
            "وارش"
        ],
        "weight": 1.50,
    },

    "John Williams": {
        "full": [
            "john williams",
            "john c. williams",
            "جان ویلیامز"
        ],
        "short": [
            "williams",
            "ویلیامز"
        ],
        "weight": 1.35,
    },

    "Philip Jefferson": {
        "full": [
            "philip jefferson",
            "philip n. jefferson",
            "فیلیپ جفرسون"
        ],
        "short": [
            "jefferson",
            "جفرسون"
        ],
        "weight": 1.25,
    },

    "Jerome Powell": {
        "full": [
            "jerome powell",
            "jerome h. powell",
            "جروم پاول"
        ],
        "short": [
            "powell",
            "پاول"
        ],
        "weight": 1.15,
    },

    "Christopher Waller": {
        "full": [
            "christopher waller",
            "christopher j. waller",
            "کریستوفر والر"
        ],
        "short": [
            "waller",
            "والر"
        ],
        "weight": 1.10,
    },

    "Michelle Bowman": {
        "full": [
            "michelle bowman",
            "michelle w. bowman",
            "میشل بومن"
        ],
        "short": [
            "bowman",
            "بومن"
        ],
        "weight": 1.10,
    },

    "Lisa Cook": {
        "full": [
            "lisa cook",
            "lisa d. cook",
            "لیزا کوک"
        ],
        "short": [
            "cook",
            "کوک"
        ],
        "weight": 1.10,
    },

    "Michael Barr": {
        "full": [
            "michael barr",
            "michael s. barr",
            "مایکل بار"
        ],
        "short": [
            "barr",
            "بار"
        ],
        "weight": 1.10,
    },

    "Beth Hammack": {
        "full": [
            "beth hammack",
            "beth m. hammack",
            "بث همک"
        ],
        "short": [
            "hammack",
            "همک"
        ],
        "weight": 1.00,
    },

    "Neel Kashkari": {
        "full": [
            "neel kashkari",
            "نیل کشکاری"
        ],
        "short": [
            "kashkari",
            "کشکاری"
        ],
        "weight": 1.00,
    },

    "Lorie Logan": {
        "full": [
            "lorie logan",
            "لوری لوگان"
        ],
        "short": [
            "logan",
            "لوگان"
        ],
        "weight": 1.00,
    },

    "Anna Paulson": {
        "full": [
            "anna paulson",
            "آنا پالسون"
        ],
        "short": [
            "paulson",
            "پالسون"
        ],
        "weight": 1.00,
    },

    "Mary Daly": {
        "full": [
            "mary daly",
            "مری دالی"
        ],
        "short": [
            "daly",
            "دالی"
        ],
        "weight": 0.75,
    },

    "Austan Goolsbee": {
        "full": [
            "austan goolsbee",
            "آستن گولزبی"
        ],
        "short": [
            "goolsbee",
            "گولزبی"
        ],
        "weight": 0.75,
    },

    "Thomas Barkin": {
        "full": [
            "thomas barkin",
            "توماس بارکین"
        ],
        "short": [
            "barkin",
            "بارکین"
        ],
        "weight": 0.75,
    },

    "Susan Collins": {
        "full": [
            "susan collins",
            "سوزان کالینز"
        ],
        "short": [
            "collins",
            "کالینز"
        ],
        "weight": 0.75,
    },

    "Alberto Musalem": {
        "full": [
            "alberto musalem",
            "آلبرتو موسالم"
        ],
        "short": [
            "musalem",
            "موسالم"
        ],
        "weight": 0.75,
    },

    "Jeffrey Schmid": {
        "full": [
            "jeffrey schmid",
            "جفری اشمید"
        ],
        "short": [
            "schmid",
            "اشمید"
        ],
        "weight": 0.75,
    },
}


# =========================================================
# STRICT FED CONTEXT
# =========================================================

STRICT_FED_CONTEXT = [

    "federal reserve",
    "fomc",
    "fed governor",
    "fed chair",
    "fed vice chair",
    "federal reserve bank",
    "the fed",
    "u.s. central bank",
    "us central bank",

    "فدرال رزرو",
    "عضو فد",
    "عضو فدرال رزرو",
    "رئیس فد",
    "رئیس فدرال رزرو",
    "بانک فدرال رزرو",
    "کمیته بازار آزاد",
]


# =========================================================
# HAWKISH LANGUAGE
# =========================================================

HAWKISH_PHRASES = {

    "further tightening": 3.0,
    "additional tightening": 3.0,

    "further rate increase": 3.0,
    "additional rate increase": 3.0,

    "need to raise rates": 3.0,
    "rates may need to rise": 3.0,

    "inflation remains too high": 2.5,
    "inflation is too high": 2.5,
    "inflation has been too high": 2.5,

    "upside risks to inflation": 2.0,

    "higher for longer": 2.0,
    "more restrictive": 2.0,

    "not ready to cut": 2.0,
    "premature to cut": 2.0,

    "persistent inflation": 1.5,
    "price pressures remain": 1.5,

    "more work to do": 1.5,


    "تورم همچنان بالاست": 2.5,
    "تورم هنوز بالاست": 2.5,

    "تورم بیش از حد بالاست": 2.5,

    "نیاز به افزایش نرخ": 3.0,

    "افزایش بیشتر نرخ": 3.0,

    "افزایش نرخ بهره": 1.5,

    "نرخ بهره بالاتر": 2.0,

    "فشار تورمی": 1.5,

    "سیاست انقباضی‌تر": 2.0,

    "کاهش نرخ زود است": 2.0,

    "برای کاهش نرخ زود است": 2.0,
}


# =========================================================
# DOVISH LANGUAGE
# =========================================================

DOVISH_PHRASES = {

    "no urgency": 3.0,
    "no rush": 3.0,

    "can be patient": 2.5,
    "policy can be patient": 2.5,

    "wait and see": 2.0,

    "hold rates": 2.0,
    "keep rates unchanged": 2.0,

    "pause rate": 2.0,

    "no need to raise": 3.0,
    "do not need to raise": 3.0,

    "rate cuts": 2.0,
    "lower rates": 2.0,

    "less restrictive": 2.0,

    "labor market cooling": 2.0,
    "labour market cooling": 2.0,

    "downside risks to employment": 2.0,

    "inflation has eased": 1.5,

    "disinflation": 1.5,


    "نیازی به عجله": 3.0,

    "عجله‌ای برای افزایش": 3.0,

    "نیازی به افزایش سریع": 3.0,

    "نیازی به افزایش": 2.5,

    "صبر کنیم": 2.0,

    "می‌توانیم صبر کنیم": 2.5,

    "ثابت نگه داشتن نرخ": 2.0,

    "توقف افزایش نرخ": 2.5,

    "کاهش نرخ بهره": 2.0,

    "بازار کار ضعیف": 2.0,

    "بازار کار سرد": 2.0,

    "کاهش تورم": 1.5,

    "تورم کاهش یافته": 1.5,

    "ریسک اشتغال": 1.5,
}


# =========================================================
# HELPERS
# =========================================================

def clamp(value, minimum=0, maximum=100):

    return max(
        minimum,
        min(maximum, value)
    )


def safe_round(value, digits=2):

    try:

        if value is None:
            return None

        return round(
            float(value),
            digits
        )

    except Exception:

        return None


def normalize_text(text):

    text = (
        text
        or ""
    ).lower()

    text = re.sub(
        r"https?://\S+",
        " ",
        text
    )

    text = re.sub(
        r"[\u200c\u200f\u202a-\u202e]",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# =========================================================
# WORD BOUNDARY FIX
#
# This is the important fix.
#
# Example:
# Persian "بار" must NOT match inside "بازار".
# =========================================================

def token_pattern(alias):

    return (

        r"(?<![\w\u0600-\u06FF])"

        + re.escape(
            alias.lower()
        )

        + r"(?![\w\u0600-\u06FF])"
    )


# =========================================================
# FED CONTEXT
# =========================================================

def has_strict_fed_context(text):

    lower = normalize_text(
        text
    )

    return any(

        term in lower

        for term
        in STRICT_FED_CONTEXT
    )


# =========================================================
# SPEAKER DETECTION
# =========================================================

def detect_speaker(
    text,
    official_source=False
):

    lower = normalize_text(
        text
    )


    # Full name detection

    for speaker, info in (
        FED_SPEAKERS.items()
    ):

        for alias in (
            info["full"]
        ):

            if re.search(
                token_pattern(alias),
                lower,
                flags=re.IGNORECASE
            ):

                return speaker


    # Short surname detection.
    # Only allowed when Fed context exists.

    if (
        official_source
        or has_strict_fed_context(
            lower
        )
    ):

        for speaker, info in (
            FED_SPEAKERS.items()
        ):

            for alias in (
                info["short"]
            ):

                if re.search(
                    token_pattern(alias),
                    lower,
                    flags=re.IGNORECASE
                ):

                    return speaker


    return None


# =========================================================
# PHRASE SCORING
# =========================================================

def phrase_score(
    text,
    phrase_map
):

    lower = normalize_text(
        text
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
# DATE
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


        meta = result[
            "meta"
        ]


        price = meta.get(
            "regularMarketPrice"
        )


        previous = (

            meta.get(
                "chartPreviousClose"
            )

            or

            meta.get(
                "previousClose"
            )
        )


        change = None

        change_pct = None


        if (
            price is not None
            and previous
        ):

            change = (
                price
                - previous
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
# UTOFX
# =========================================================

def get_utofx_news(
    limit=12
):

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


            text_box = (
                message.select_one(
                    ".tgme_widget_message_text"
                )
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

def get_utotimes_news(
    limit=8
):

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


            if not title:
                continue


            news.append({

                "source":
                    "UtoTimes",

                "text":
                    title,

                "date":
                    (
                        item.findtext(
                            "pubDate"
                        )
                        or ""
                    ).strip(),

                "link":
                    (
                        item.findtext(
                            "link"
                        )
                        or ""
                    ).strip()
                    or None
            })


        return news


    except Exception:

        return []


# =========================================================
# FETCH PAGE
# =========================================================

def fetch_page(url):

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


        page_date = None


        time_tag = soup.find(

            "time",

            attrs={
                "datetime": True
            }
        )


        if time_tag:

            page_date = (
                time_tag.get(
                    "datetime"
                )
            )


        if not page_date:

            meta = soup.find(

                "meta",

                attrs={
                    "property":
                    "article:published_time"
                }
            )


            if meta:

                page_date = (
                    meta.get(
                        "content"
                    )
                )


        for tag in soup([

            "script",
            "style",
            "nav",
            "footer"

        ]):

            tag.decompose()


        main = (

            soup.find(
                "main"
            )

            or

            soup.find(
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
            in main.find_all(
                "p"
            )
        ]


        return (

            " ".join(
                paragraphs
            )[:30000],

            page_date
        )


    except Exception:

        return "", None


# =========================================================
# ANALYZE FED TEXT
# =========================================================

def analyze_fed_text(

    text,

    source,

    date=None,

    title=None,

    link=None,

    official_source=False
):


    if not text:

        return None


    # Secondary news MUST explicitly mention
    # the U.S. Federal Reserve.

    if (
        not official_source
        and
        not has_strict_fed_context(
            text
        )
    ):

        return None


    speaker = detect_speaker(

        text,

        official_source=
            official_source
    )


    if not speaker:

        return None


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

        -6.0,

        min(
            6.0,
            raw_signal
        )
    )


    # Neutral items have no score impact
    # and are not displayed.

    if abs(
        raw_signal
    ) < 0.75:

        return None


    if raw_signal >= 2:

        tone = "DOVISH"


    elif raw_signal >= 0.75:

        tone = (
            "SLIGHTLY DOVISH"
        )


    elif raw_signal <= -2:

        tone = "HAWKISH"


    else:

        tone = (
            "SLIGHTLY HAWKISH"
        )


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


    if official_source:

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
            ).strip(),

        "link":
            link,

        "voter":
            (
                speaker
                in
                FOMC_VOTERS_2026
            )
    }


# =========================================================
# FEDERAL RESERVE OFFICIAL SPEECHES
# =========================================================

def get_board_speeches(
    limit=6
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


            if link:

                body, page_date = (
                    fetch_page(
                        link
                    )
                )

            else:

                body = ""
                page_date = None


            date = (
                date
                or page_date
            )


            analyzed = (
                analyze_fed_text(

                    f"""
                    {title}
                    {description}
                    {body}
                    """,

                    source=
                        "Federal Reserve",

                    date=date,

                    title=title,

                    link=
                        link
                        or None,

                    official_source=True
                )
            )


            if analyzed:

                items.append(
                    analyzed
                )


    except Exception:

        pass


    return items


# =========================================================
# NEW YORK FED / WILLIAMS
# =========================================================

def get_williams_speeches(
    limit=3
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
                "williams"
                not in label.lower()
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


            body, page_date = (
                fetch_page(
                    link
                )
            )


            analyzed = (
                analyze_fed_text(

                    f"""
                    {label}
                    {body}
                    """,

                    source=
                        "New York Fed",

                    date=
                        page_date,

                    title=
                        label,

                    link=
                        link,

                    official_source=True
                )
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
# DUPLICATE DETECTION
# =========================================================

def event_similarity(
    a,
    b
):


    if (
        a.get(
            "speaker"
        )
        !=
        b.get(
            "speaker"
        )
    ):

        return 0.0


    text_a = normalize_text(

        a.get(
            "title",
            ""
        )

    )[:500]


    text_b = normalize_text(

        b.get(
            "title",
            ""
        )

    )[:500]


    if (
        not text_a
        or
        not text_b
    ):

        return 0.0


    return SequenceMatcher(

        None,

        text_a,

        text_b
    ).ratio()


def dedupe_fed_events(
    events
):


    # Official sources get priority

    priority = {

        "Federal Reserve": 3,

        "New York Fed": 3,

        "UtoFX Telegram": 2,

        "UtoTimes": 1
    }


    ordered = sorted(

        events,

        key=lambda e:

            priority.get(
                e.get(
                    "source"
                ),
                0
            ),

        reverse=True
    )


    unique = []


    for event in ordered:


        duplicate = False


        for existing in unique:


            same_link = (

                event.get(
                    "link"
                )

                and

                existing.get(
                    "link"
                )

                and

                event["link"]
                ==
                existing["link"]
            )


            similar = (

                event_similarity(
                    event,
                    existing
                )

                >= 0.78
            )


            if (
                same_link
                or similar
            ):

                duplicate = True

                break


        if not duplicate:

            unique.append(
                event
            )


    unique.sort(

        key=lambda x:

            parse_date(
                x.get(
                    "date"
                )
            )

            or

            datetime(
                2000,
                1,
                1,
                tzinfo=timezone.utc
            ),

        reverse=True
    )


    return unique


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


    # Official Fed

    events.extend(

        get_board_speeches(
            6
        )
    )


    # Williams / NY Fed

    events.extend(

        get_williams_speeches(
            3
        )
    )


    # UtoFX

    for item in telegram_news:


        analyzed = (
            analyze_fed_text(

                item["text"],

                source=
                    item["source"],

                date=
                    item.get(
                        "date"
                    ),

                title=
                    item["text"][:220],

                link=
                    item.get(
                        "link"
                    ),

                official_source=False
            )
        )


        if analyzed:

            events.append(
                analyzed
            )


    # UtoTimes

    for item in utotimes_news:


        analyzed = (
            analyze_fed_text(

                item["text"],

                source=
                    item["source"],

                date=
                    item.get(
                        "date"
                    ),

                title=
                    item["text"][:220],

                link=
                    item.get(
                        "link"
                    ),

                official_source=False
            )
        )


        if analyzed:

            events.append(
                analyzed
            )


    # Remove duplicates

    unique = dedupe_fed_events(
        events
    )


    # Only most recent distinct events
    # influence the score

    total_impact = sum(

        event[
            "gold_impact"
        ]

        for event
        in unique[:10]
    )


    fed_score = (

        50

        + total_impact
        * 2.2
    )


    fed_score = round(

        clamp(
            fed_score
        ),

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


    FED_CACHE["result"] = (
        result
    )


    return result


# =========================================================
# GOLD SCORE ENGINE
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


    # Dollar

    dollar_score = clamp(

        50
        - dxy_change
        * 18
    )


    # Rates

    rate_move = (

        y2_change
        + y10_change
        + y30_change

    ) / 3


    rates_score = clamp(

        50
        - rate_move
        * 10
    )


    # Technical

    technical_score = clamp(

        50
        + gold_change
        * 12
    )


    # VIX

    market_flow_score = clamp(

        50
        + vix_change
        * 1.5
    )


    # Oil

    oil_score = clamp(

        50
        - oil_change
        * 3
    )


    components = {

        "Economic Data":
            50.0,

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
            50.0,

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

        "Economic Data":
            0.20,

        "Federal Reserve":
            0.20,

        "Rates":
            0.15,

        "US Dollar":
            0.15,

        "Geopolitical Risk":
            0.10,

        "Oil / Inflation":
            0.07,

        "Market Flow":
            0.05,

        "Technical":
            0.08
    }


    total = round(

        sum(

            components[name]
            *
            weights[name]

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
# BUILD DATA
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

        return CACHE[
            "data"
        ]


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


    score, bias, components = (

        calculate_scores(

            markets,

            fed["score"]
        )
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

font-family:
Arial,
Helvetica,
sans-serif

}


.container{

max-width:1250px;

margin:auto;

padding:
30px 20px 60px

}


.brand{

font-size:14px;

letter-spacing:4px;

color:#d8b96c;

font-weight:bold

}


h1{

margin:
8px 0 5px;

font-size:
clamp(
28px,
5vw,
42px
)

}


.subtitle{

color:#8f98aa;

margin-bottom:25px

}


.hero,
.panel,
.market-card,
.component,
.fed-card{

background:#10151f;

border:
1px solid #222a39;

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

font-size:
clamp(
60px,
10vw,
95px
);

font-weight:bold;

margin-top:5px

}


.score span{

font-size:22px;

color:#6f7888

}


.bias{

display:inline-block;

padding:
9px 18px;

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

margin:
30px auto 5px

}


.bar-fill{

height:100%;

width:
{{ data.score }}%;

background:
linear-gradient(
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

justify-content:
space-between;

font-size:11px;

color:#727b8b

}


.section-title{

margin:
35px 0 15px;

font-size:21px

}


.market-grid{

display:grid;

grid-template-columns:
repeat(
auto-fit,
minmax(
155px,
1fr
)
);

gap:12px

}


.market-card,
.component,
.fed-card{

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
repeat(
auto-fit,
minmax(
210px,
1fr
)
);

gap:12px

}


.component-score{

font-size:29px;

font-weight:bold;

margin-top:8px

}


.fed-grid{

display:grid;

grid-template-columns:
repeat(
auto-fit,
minmax(
260px,
1fr
)
);

gap:12px

}


.fed-top{

display:flex;

align-items:center;

justify-content:
space-between;

gap:12px

}


.speaker{

font-weight:bold;

font-size:16px

}


.badge{

font-size:10px;

padding:
5px 8px;

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

grid-template-columns:
1fr 1fr;

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

border-top:
1px solid #222a39;

padding:
14px 0

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

border:
1px solid #222a39;

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


@media(
max-width:750px
){

.news-grid{

grid-template-columns:
1fr

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

Macro • Fed • Rates • Dollar
• Geopolitics • Market Data

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


{% for key,item
in data.markets.items() %}


<div class="market-card">


<div class="market-title">

{{ names[key] }}

</div>


<div class="market-price">

{{ item.price
if item.price is not none
else 'N/A' }}

</div>


{% if item.change_pct
is not none %}


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


{% for name,value
in data.components.items() %}


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

•
{{ data.fed.event_count }}

distinct non-neutral Fed items detected

</span>


</div>



<div class="fed-grid">


{% if data.fed.events %}


{% for event
in data.fed.events %}


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
else 'NON-VOTER' }}

</div>


</div>


{% set toneclass =
'tone-dovish'
if 'DOVISH' in event.tone
else 'tone-hawkish'
%}


<div class="
tone
{{ toneclass }}
">

{{ event.tone }}

</div>


<div class="impact">

Gold impact:

{% if event.gold_impact > 0 %}

+

{% endif %}

{{ event.gold_impact }}

•

{{ event.source }}

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

No non-neutral Fed items detected yet.

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


{% for news
in data.telegram_news %}


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


{% for news
in data.utotimes_news %}


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

Fed news now requires explicit
U.S. Federal Reserve context.

Ambiguous surname matches are blocked
and duplicate items are removed.

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
