import requests
import time
import re

from datetime import datetime, timezone


# =========================================================
# FREE ECONOMIC CALENDAR
# =========================================================

FF_URL = (
    "https://nfs.faireconomy.media/"
    "ff_calendar_thisweek.json"
)

HEADERS = {
    "User-Agent":
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64)"
}


# =========================================================
# CACHE
#
# Important:
# Do NOT request Forex Factory every 30 seconds.
# =========================================================

ECON_CACHE = {
    "time": 0,
    "result": None
}

ECON_CACHE_SECONDS = 300


# =========================================================
# EVENT PROFILES
#
# direction:
#
# +1 = Higher actual tends to HELP gold
#      Example: Jobless Claims / Unemployment
#
# -1 = Higher actual tends to HURT gold
#      Example: CPI / PCE / NFP
#
# scale:
# Typical surprise size used to normalize the event.
#
# weight:
# Importance inside Economic Score.
# =========================================================

EVENT_PROFILES = [

    # -------------------------
    # PCE
    # -------------------------

    {
        "keywords": [
            "core pce price index"
        ],
        "direction": -1,
        "scale": 0.10,
        "weight": 3.4,
        "name": "Core PCE"
    },

    {
        "keywords": [
            "pce price index"
        ],
        "direction": -1,
        "scale": 0.10,
        "weight": 3.0,
        "name": "PCE"
    },


    # -------------------------
    # CPI
    # -------------------------

    {
        "keywords": [
            "core cpi"
        ],
        "direction": -1,
        "scale": 0.10,
        "weight": 3.4,
        "name": "Core CPI"
    },

    {
        "keywords": [
            "cpi"
        ],
        "direction": -1,
        "scale": 0.10,
        "weight": 3.1,
        "name": "CPI"
    },


    # -------------------------
    # LABOR
    # -------------------------

    {
        "keywords": [
            "non-farm employment change",
            "nonfarm payrolls",
            "non-farm payrolls"
        ],
        "direction": -1,
        "scale": 50.0,
        "weight": 3.3,
        "name": "Nonfarm Payrolls"
    },

    {
        "keywords": [
            "unemployment rate"
        ],
        "direction": +1,
        "scale": 0.10,
        "weight": 3.0,
        "name": "Unemployment Rate"
    },

    {
        "keywords": [
            "average hourly earnings"
        ],
        "direction": -1,
        "scale": 0.10,
        "weight": 2.6,
        "name": "Average Hourly Earnings"
    },

    {
        "keywords": [
            "initial jobless claims",
            "unemployment claims"
        ],
        "direction": +1,
        "scale": 10.0,
        "weight": 2.0,
        "name": "Initial Jobless Claims"
    },

    {
        "keywords": [
            "continuing claims"
        ],
        "direction": +1,
        "scale": 25.0,
        "weight": 1.5,
        "name": "Continuing Claims"
    },

    {
        "keywords": [
            "adp non-farm",
            "adp employment"
        ],
        "direction": -1,
        "scale": 40.0,
        "weight": 1.5,
        "name": "ADP Employment"
    },

    {
        "keywords": [
            "jolts job openings"
        ],
        "direction": -1,
        "scale": 250.0,
        "weight": 1.6,
        "name": "JOLTS"
    },


    # -------------------------
    # ISM
    # -------------------------

    {
        "keywords": [
            "ism manufacturing prices",
            "ism prices paid"
        ],
        "direction": -1,
        "scale": 2.0,
        "weight": 2.5,
        "name": "ISM Prices Paid"
    },

    {
        "keywords": [
            "ism services prices"
        ],
        "direction": -1,
        "scale": 2.0,
        "weight": 2.6,
        "name": "ISM Services Prices"
    },

    {
        "keywords": [
            "ism manufacturing pmi"
        ],
        "direction": -1,
        "scale": 1.0,
        "weight": 2.0,
        "name": "ISM Manufacturing"
    },

    {
        "keywords": [
            "ism services pmi",
            "ism non-manufacturing"
        ],
        "direction": -1,
        "scale": 1.0,
        "weight": 2.2,
        "name": "ISM Services"
    },


    # -------------------------
    # RETAIL SALES
    # -------------------------

    {
        "keywords": [
            "core retail sales"
        ],
        "direction": -1,
        "scale": 0.30,
        "weight": 2.0,
        "name": "Core Retail Sales"
    },

    {
        "keywords": [
            "retail sales"
        ],
        "direction": -1,
        "scale": 0.30,
        "weight": 1.9,
        "name": "Retail Sales"
    },


    # -------------------------
    # GDP
    # -------------------------

    {
        "keywords": [
            "advance gdp",
            "prelim gdp",
            "final gdp",
            "gdp"
        ],
        "direction": -1,
        "scale": 0.50,
        "weight": 1.8,
        "name": "GDP"
    },


    # -------------------------
    # PPI
    # -------------------------

    {
        "keywords": [
            "core ppi"
        ],
        "direction": -1,
        "scale": 0.15,
        "weight": 1.8,
        "name": "Core PPI"
    },

    {
        "keywords": [
            "ppi"
        ],
        "direction": -1,
        "scale": 0.15,
        "weight": 1.6,
        "name": "PPI"
    },


    # -------------------------
    # CONSUMER
    # -------------------------

    {
        "keywords": [
            "consumer confidence"
        ],
        "direction": -1,
        "scale": 3.0,
        "weight": 1.1,
        "name": "Consumer Confidence"
    },

    {
        "keywords": [
            "consumer sentiment"
        ],
        "direction": -1,
        "scale": 2.0,
        "weight": 1.1,
        "name": "Consumer Sentiment"
    },
]


# =========================================================
# HELPERS
# =========================================================

def clamp(value, minimum=0, maximum=100):

    return max(
        minimum,
        min(maximum, value)
    )


def clean_title(value):

    return re.sub(
        r"\s+",
        " ",
        str(value or "")
    ).strip()


# =========================================================
# NUMBER PARSER
#
# Examples:
#
# 197K   -> 197
# 1.72M  -> 1720
# 3.4%   -> 3.4
# =========================================================

def parse_number(value):

    if value is None:
        return None


    text = str(value).strip()


    if not text:
        return None


    text = (
        text
        .replace(",", "")
        .replace("%", "")
        .replace("$", "")
    )


    multiplier = 1.0


    if text.upper().endswith("K"):

        multiplier = 1.0

        text = text[:-1]


    elif text.upper().endswith("M"):

        multiplier = 1000.0

        text = text[:-1]


    elif text.upper().endswith("B"):

        multiplier = 1000000.0

        text = text[:-1]


    try:

        return (
            float(text)
            * multiplier
        )

    except Exception:

        return None


# =========================================================
# DATE
# =========================================================

def parse_event_date(value):

    if not value:

        return None


    try:

        dt = datetime.fromisoformat(
            str(value).replace(
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

        return None


def recency_weight(date_value):

    dt = parse_event_date(
        date_value
    )


    if not dt:

        return 0.50


    now = datetime.now(
        timezone.utc
    )


    hours = (

        now - dt

    ).total_seconds() / 3600


    if hours < 0:

        return 0.0


    if hours <= 6:

        return 1.00


    if hours <= 24:

        return 0.85


    if hours <= 48:

        return 0.65


    if hours <= 72:

        return 0.45


    if hours <= 168:

        return 0.20


    return 0.0


# =========================================================
# IMPACT WEIGHT
# =========================================================

def impact_weight(value):

    text = str(
        value or ""
    ).lower()


    if "high" in text:

        return 1.00


    if "medium" in text:

        return 0.65


    if "low" in text:

        return 0.30


    return 0.40


# =========================================================
# EVENT PROFILE MATCH
# =========================================================

def find_profile(title):

    lower = clean_title(
        title
    ).lower()


    for profile in EVENT_PROFILES:

        for keyword in profile[
            "keywords"
        ]:

            if keyword in lower:

                return profile


    return None


# =========================================================
# FETCH FOREX FACTORY
# =========================================================

def fetch_calendar():

    try:

        r = requests.get(

            FF_URL,

            headers=HEADERS,

            timeout=12
        )


        r.raise_for_status()


        data = r.json()


        if not isinstance(
            data,
            list
        ):

            return []


        return data


    except Exception:

        return []


# =========================================================
# EVENT SCORING
# =========================================================

def score_event(event):

    title = clean_title(
        event.get(
            "title"
        )
    )


    profile = find_profile(
        title
    )


    if not profile:

        return None


    actual = parse_number(
        event.get(
            "actual"
        )
    )


    forecast = parse_number(
        event.get(
            "forecast"
        )
    )


    previous = parse_number(
        event.get(
            "previous"
        )
    )


    # Event not released yet

    if actual is None:

        return None


    # Best comparison:
    # Actual vs Forecast

    comparison = None

    confidence = 1.0

    basis = None


    if forecast is not None:

        comparison = (
            actual
            - forecast
        )

        basis = "forecast"


    elif previous is not None:

        comparison = (
            actual
            - previous
        )

        basis = "previous"

        # Previous comparison is weaker
        # than consensus surprise.

        confidence = 0.45


    else:

        return None


    scale = profile[
        "scale"
    ]


    if not scale:

        return None


    normalized_surprise = (

        comparison
        / scale
    )


    # Prevent one unusual release
    # destroying the whole index.

    normalized_surprise = max(

        -3.0,

        min(
            3.0,
            normalized_surprise
        )
    )


    # Gold direction

    gold_signal = (

        normalized_surprise

        * profile[
            "direction"
        ]
    )


    impact = impact_weight(
        event.get(
            "impact"
        )
    )


    recency = recency_weight(
        event.get(
            "date"
        )
    )


    contribution = (

        gold_signal

        * profile[
            "weight"
        ]

        * impact

        * recency

        * confidence

        * 1.70
    )


    contribution = max(

        -10,

        min(
            10,
            contribution
        )
    )


    if contribution >= 2.5:

        gold_effect = (
            "BULLISH"
        )


    elif contribution >= 0.5:

        gold_effect = (
            "SLIGHTLY BULLISH"
        )


    elif contribution <= -2.5:

        gold_effect = (
            "BEARISH"
        )


    elif contribution <= -0.5:

        gold_effect = (
            "SLIGHTLY BEARISH"
        )


    else:

        gold_effect = (
            "NEUTRAL"
        )


    return {

        "name":
            profile["name"],

        "title":
            title,

        "actual":
            event.get(
                "actual"
            ),

        "forecast":
            event.get(
                "forecast"
            ),

        "previous":
            event.get(
                "previous"
            ),

        "impact":
            event.get(
                "impact"
            ),

        "date":
            event.get(
                "date"
            ),

        "basis":
            basis,

        "surprise":
            round(
                normalized_surprise,
                2
            ),

        "gold_effect":
            gold_effect,

        "gold_impact":
            round(
                contribution,
                2
            )
    }


# =========================================================
# ECONOMIC MASTER ENGINE
# =========================================================

def get_economic_monitor():

    now = time.time()


    if (

        ECON_CACHE["result"]
        is not None

        and

        now
        - ECON_CACHE["time"]

        < ECON_CACHE_SECONDS
    ):

        return ECON_CACHE[
            "result"
        ]


    raw_events = fetch_calendar()


    scored_events = []


    for event in raw_events:

        # Forex Factory calls
        # currency field "country".

        currency = str(

            event.get(
                "country",
                ""
            )

        ).upper()


        if currency != "USD":

            continue


        result = score_event(
            event
        )


        if result:

            scored_events.append(
                result
            )


    scored_events.sort(

        key=lambda x:

            parse_event_date(
                x.get(
                    "date"
                )
            )

            or datetime(
                2000,
                1,
                1,
                tzinfo=timezone.utc
            ),

        reverse=True
    )


    # Only recent relevant releases
    # should influence current bias.

    relevant = [

        event

        for event
        in scored_events

        if recency_weight(
            event.get(
                "date"
            )
        ) > 0
    ]


    total_impact = sum(

        event[
            "gold_impact"
        ]

        for event
        in relevant[:15]
    )


    economic_score = clamp(

        50
        + total_impact
    )


    economic_score = round(

        economic_score,
        1
    )


    if economic_score >= 65:

        bias = (
            "BULLISH FOR GOLD"
        )


    elif economic_score >= 54:

        bias = (
            "SLIGHTLY BULLISH"
        )


    elif economic_score <= 35:

        bias = (
            "BEARISH FOR GOLD"
        )


    elif economic_score <= 46:

        bias = (
            "SLIGHTLY BEARISH"
        )


    else:

        bias = "NEUTRAL"


    result = {

        "score":
            economic_score,

        "bias":
            bias,

        "events":
            relevant[:10],

        "event_count":
            len(relevant),

        "source":
            "Forex Factory",

        "updated":

            datetime.now(
                timezone.utc
            ).strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )
    }


    ECON_CACHE["time"] = now

    ECON_CACHE["result"] = (
        result
    )


    return result
