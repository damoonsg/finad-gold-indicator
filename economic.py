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
# =========================================================

ECON_CACHE = {
    "time": 0,
    "result": None,
    "last_2y": None
}

ECON_CACHE_SECONDS = 300


# =========================================================
# EVENT PROFILES
#
# direction:
# +1 = higher actual tends to help Gold
# -1 = higher actual tends to hurt Gold
#
# immediate_weight:
# reaction around the release
#
# policy_weight:
# importance for Fed path
#
# persistence_hours:
# how long policy effect should matter
# =========================================================

EVENT_PROFILES = [

    # =====================================================
    # INFLATION
    # =====================================================

    {
        "keywords": [
            "core pce price index"
        ],
        "name": "Core PCE",
        "category": "Inflation",
        "direction": -1,
        "scale": 0.10,
        "immediate_weight": 3.5,
        "policy_weight": 5.0,
        "persistence_hours": 336
    },

    {
        "keywords": [
            "pce price index"
        ],
        "name": "Headline PCE",
        "category": "Inflation",
        "direction": -1,
        "scale": 0.10,
        "immediate_weight": 3.0,
        "policy_weight": 4.3,
        "persistence_hours": 336
    },

    {
        "keywords": [
            "core cpi"
        ],
        "name": "Core CPI",
        "category": "Inflation",
        "direction": -1,
        "scale": 0.10,
        "immediate_weight": 3.8,
        "policy_weight": 4.8,
        "persistence_hours": 336
    },

    {
        "keywords": [
            "cpi"
        ],
        "name": "Headline CPI",
        "category": "Inflation",
        "direction": -1,
        "scale": 0.10,
        "immediate_weight": 3.4,
        "policy_weight": 4.0,
        "persistence_hours": 240
    },

    {
        "keywords": [
            "core ppi"
        ],
        "name": "Core PPI",
        "category": "Inflation",
        "direction": -1,
        "scale": 0.15,
        "immediate_weight": 2.0,
        "policy_weight": 2.0,
        "persistence_hours": 120
    },

    {
        "keywords": [
            "ppi"
        ],
        "name": "PPI",
        "category": "Inflation",
        "direction": -1,
        "scale": 0.15,
        "immediate_weight": 1.7,
        "policy_weight": 1.6,
        "persistence_hours": 96
    },

    {
        "keywords": [
            "ism manufacturing prices",
            "ism prices paid"
        ],
        "name": "ISM Prices Paid",
        "category": "Inflation",
        "direction": -1,
        "scale": 2.0,
        "immediate_weight": 2.5,
        "policy_weight": 3.0,
        "persistence_hours": 168
    },

    {
        "keywords": [
            "ism services prices"
        ],
        "name": "ISM Services Prices",
        "category": "Inflation",
        "direction": -1,
        "scale": 2.0,
        "immediate_weight": 2.6,
        "policy_weight": 3.2,
        "persistence_hours": 168
    },


    # =====================================================
    # LABOR
    # =====================================================

    {
        "keywords": [
            "non-farm employment change",
            "nonfarm payrolls",
            "non-farm payrolls"
        ],
        "name": "Nonfarm Payrolls",
        "category": "Labor",
        "direction": -1,
        "scale": 50.0,
        "immediate_weight": 4.0,
        "policy_weight": 4.5,
        "persistence_hours": 336
    },

    {
        "keywords": [
            "unemployment rate"
        ],
        "name": "Unemployment Rate",
        "category": "Labor",
        "direction": +1,
        "scale": 0.10,
        "immediate_weight": 3.5,
        "policy_weight": 4.2,
        "persistence_hours": 336
    },

    {
        "keywords": [
            "average hourly earnings"
        ],
        "name": "Average Hourly Earnings",
        "category": "Labor",
        "direction": -1,
        "scale": 0.10,
        "immediate_weight": 3.0,
        "policy_weight": 3.8,
        "persistence_hours": 240
    },

    {
        "keywords": [
            "initial jobless claims",
            "unemployment claims"
        ],
        "name": "Initial Jobless Claims",
        "category": "Labor",
        "direction": +1,
        "scale": 10.0,
        "immediate_weight": 2.3,
        "policy_weight": 1.2,
        "persistence_hours": 72
    },

    {
        "keywords": [
            "continuing claims"
        ],
        "name": "Continuing Claims",
        "category": "Labor",
        "direction": +1,
        "scale": 25.0,
        "immediate_weight": 1.5,
        "policy_weight": 1.4,
        "persistence_hours": 96
    },

    {
        "keywords": [
            "adp non-farm",
            "adp employment"
        ],
        "name": "ADP Employment",
        "category": "Labor",
        "direction": -1,
        "scale": 40.0,
        "immediate_weight": 1.6,
        "policy_weight": 1.1,
        "persistence_hours": 72
    },

    {
        "keywords": [
            "jolts job openings"
        ],
        "name": "JOLTS",
        "category": "Labor",
        "direction": -1,
        "scale": 250.0,
        "immediate_weight": 1.8,
        "policy_weight": 1.8,
        "persistence_hours": 120
    },


    # =====================================================
    # GROWTH / ACTIVITY
    # =====================================================

    {
        "keywords": [
            "ism manufacturing pmi"
        ],
        "name": "ISM Manufacturing",
        "category": "Growth",
        "direction": -1,
        "scale": 1.0,
        "immediate_weight": 2.2,
        "policy_weight": 1.8,
        "persistence_hours": 120
    },

    {
        "keywords": [
            "ism services pmi",
            "ism non-manufacturing"
        ],
        "name": "ISM Services",
        "category": "Growth",
        "direction": -1,
        "scale": 1.0,
        "immediate_weight": 2.5,
        "policy_weight": 2.2,
        "persistence_hours": 144
    },

    {
        "keywords": [
            "advance gdp",
            "prelim gdp",
            "final gdp",
            "gdp"
        ],
        "name": "GDP",
        "category": "Growth",
        "direction": -1,
        "scale": 0.50,
        "immediate_weight": 2.0,
        "policy_weight": 2.0,
        "persistence_hours": 168
    },


    # =====================================================
    # CONSUMPTION
    # =====================================================

    {
        "keywords": [
            "core retail sales"
        ],
        "name": "Core Retail Sales",
        "category": "Consumption",
        "direction": -1,
        "scale": 0.30,
        "immediate_weight": 2.2,
        "policy_weight": 1.8,
        "persistence_hours": 120
    },

    {
        "keywords": [
            "retail sales"
        ],
        "name": "Retail Sales",
        "category": "Consumption",
        "direction": -1,
        "scale": 0.30,
        "immediate_weight": 2.0,
        "policy_weight": 1.6,
        "persistence_hours": 96
    },

    {
        "keywords": [
            "consumer confidence"
        ],
        "name": "Consumer Confidence",
        "category": "Consumption",
        "direction": -1,
        "scale": 3.0,
        "immediate_weight": 1.1,
        "policy_weight": 0.8,
        "persistence_hours": 72
    },

    {
        "keywords": [
            "consumer sentiment"
        ],
        "name": "Consumer Sentiment",
        "category": "Consumption",
        "direction": -1,
        "scale": 2.0,
        "immediate_weight": 1.1,
        "policy_weight": 0.8,
        "persistence_hours": 72
    }
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


def hours_since(value):

    dt = parse_event_date(
        value
    )


    if not dt:

        return None


    return max(

        0,

        (
            datetime.now(
                timezone.utc
            )
            - dt
        ).total_seconds()
        / 3600
    )


# =========================================================
# IMMEDIATE DECAY
#
# News shock should disappear relatively quickly.
# =========================================================

def immediate_decay(date_value):

    hours = hours_since(
        date_value
    )


    if hours is None:
        return 0.25


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


# =========================================================
# POLICY DECAY
#
# Policy effect persists much longer.
# =========================================================

def policy_decay(
    date_value,
    persistence_hours
):

    hours = hours_since(
        date_value
    )


    if hours is None:

        return 0.30


    if hours > persistence_hours:

        return 0.0


    ratio = (
        hours
        / persistence_hours
    )


    # Slow linear decay.
    # Still meaningful days later.

    return max(
        0.15,
        1.0 - ratio
    )


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


    return 0.45


# =========================================================
# PROFILE MATCH
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
# FOREX FACTORY
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
# 2Y CONFIRMATION
#
# two_year_change_pct:
#
# negative = 2Y falling
# positive = 2Y rising
#
# Dovish data should normally push 2Y down.
# Hawkish data should normally push 2Y up.
#
# This is confirmation only.
# It NEVER creates the original signal.
# =========================================================

def yield_confirmation(
    policy_signal,
    two_year_change_pct
):

    if (
        two_year_change_pct
        is None
        or
        abs(policy_signal) < 0.10
    ):

        return {
            "status": "NO CONFIRMATION DATA",
            "multiplier": 1.00
        }


    # Gold-positive / dovish signal

    if policy_signal > 0:

        if two_year_change_pct < -0.05:

            return {
                "status": "CONFIRMED",
                "multiplier": 1.20
            }

        elif two_year_change_pct > 0.05:

            return {
                "status": "REJECTED BY 2Y",
                "multiplier": 0.60
            }


    # Gold-negative / hawkish signal

    elif policy_signal < 0:

        if two_year_change_pct > 0.05:

            return {
                "status": "CONFIRMED",
                "multiplier": 1.20
            }

        elif two_year_change_pct < -0.05:

            return {
                "status": "REJECTED BY 2Y",
                "multiplier": 0.60
            }


    return {
        "status": "NOT CONFIRMED",
        "multiplier": 0.85
    }


# =========================================================
# EVENT SCORING
# =========================================================

def score_event(
    event,
    two_year_change_pct=None
):

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


    if actual is None:

        return None


    comparison = None
    comparison_basis = None
    confidence = 1.0


    if forecast is not None:

        comparison = (
            actual
            - forecast
        )

        comparison_basis = (
            "forecast"
        )


    elif previous is not None:

        comparison = (
            actual
            - previous
        )

        comparison_basis = (
            "previous"
        )

        confidence = 0.45


    else:

        return None


    normalized_surprise = (

        comparison
        / profile["scale"]
    )


    normalized_surprise = max(

        -3.0,

        min(
            3.0,
            normalized_surprise
        )
    )


    gold_direction_signal = (

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


    # =====================================================
    # IMMEDIATE IMPACT
    # =====================================================

    immediate = (

        gold_direction_signal

        * profile[
            "immediate_weight"
        ]

        * impact

        * confidence

        * immediate_decay(
            event.get(
                "date"
            )
        )
    )


    immediate = max(

        -10,

        min(
            10,
            immediate
        )
    )


    # =====================================================
    # FED POLICY IMPACT
    # =====================================================

    raw_policy = (

        gold_direction_signal

        * profile[
            "policy_weight"
        ]

        * impact

        * confidence

        * policy_decay(

            event.get(
                "date"
            ),

            profile[
                "persistence_hours"
            ]
        )
    )


    confirmation = (
        yield_confirmation(

            raw_policy,

            two_year_change_pct
        )
    )


    policy = (

        raw_policy

        * confirmation[
            "multiplier"
        ]
    )


    policy = max(

        -10,

        min(
            10,
            policy
        )
    )


    # =====================================================
    # LABELS
    # =====================================================

    def effect_label(value):

        if value >= 4:
            return "STRONGLY BULLISH"

        if value >= 1.5:
            return "BULLISH"

        if value >= 0.4:
            return "SLIGHTLY BULLISH"

        if value <= -4:
            return "STRONGLY BEARISH"

        if value <= -1.5:
            return "BEARISH"

        if value <= -0.4:
            return "SLIGHTLY BEARISH"

        return "NEUTRAL"


    return {

        "name":
            profile["name"],

        "category":
            profile["category"],

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
            comparison_basis,

        "surprise":
            round(
                normalized_surprise,
                2
            ),

        "immediate_impact":
            round(
                immediate,
                2
            ),

        "immediate_effect":
            effect_label(
                immediate
            ),

        "policy_impact":
            round(
                policy,
                2
            ),

        "policy_effect":
            effect_label(
                policy
            ),

        "confirmation":
            confirmation[
                "status"
            ],

        "persistence_hours":
            profile[
                "persistence_hours"
            ]
    }


# =========================================================
# CATEGORY SCORES
# =========================================================

def build_category_scores(
    events
):

    categories = {

        "Inflation": 50.0,
        "Labor": 50.0,
        "Growth": 50.0,
        "Consumption": 50.0
    }


    for category in categories:

        impact = sum(

            event[
                "policy_impact"
            ]

            for event in events

            if event[
                "category"
            ] == category
        )


        categories[
            category
        ] = round(

            clamp(
                50
                + impact
            ),

            1
        )


    return categories


# =========================================================
# UNDERLYING ECONOMY SCORE
#
# 50 = neutral
# >50 = softer economy / more Gold-friendly
# <50 = stronger economy / more Gold-negative
# =========================================================

def build_underlying_score(
    category_scores
):

    score = (

        category_scores[
            "Labor"
        ] * 0.40

        +

        category_scores[
            "Growth"
        ] * 0.35

        +

        category_scores[
            "Consumption"
        ] * 0.25
    )


    return round(
        score,
        1
    )


# =========================================================
# ECONOMIC MASTER ENGINE
# =========================================================

def get_economic_monitor(
    two_year_change_pct=None
):

    now = time.time()


    # If same 2Y input and cache still fresh,
    # return cached result.

    if (

        ECON_CACHE[
            "result"
        ] is not None

        and

        now
        - ECON_CACHE[
            "time"
        ]
        < ECON_CACHE_SECONDS

        and

        ECON_CACHE[
            "last_2y"
        ]
        ==
        two_year_change_pct
    ):

        return ECON_CACHE[
            "result"
        ]


    raw_events = (
        fetch_calendar()
    )


    scored_events = []


    for event in raw_events:

        currency = str(

            event.get(
                "country",
                ""
            )

        ).upper()


        if currency != "USD":

            continue


        scored = score_event(

            event,

            two_year_change_pct
        )


        if scored:

            scored_events.append(
                scored
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


    # =====================================================
    # IMMEDIATE SCORE
    # Only events still carrying short-term impact matter.
    # =====================================================

    immediate_events = [

        event

        for event
        in scored_events

        if abs(
            event[
                "immediate_impact"
            ]
        ) > 0.01
    ]


    immediate_total = sum(

        event[
            "immediate_impact"
        ]

        for event
        in immediate_events[:12]
    )


    market_shock_score = round(

        clamp(
            50
            + immediate_total
        ),

        1
    )


    # =====================================================
    # FED POLICY SCORE
    # Persistent.
    # =====================================================

    policy_events = [

        event

        for event
        in scored_events

        if abs(
            event[
                "policy_impact"
            ]
        ) > 0.01
    ]


    policy_total = sum(

        event[
            "policy_impact"
        ]

        for event
        in policy_events[:20]
    )


    fed_policy_score = round(

        clamp(
            50
            + policy_total
        ),

        1
    )


    # =====================================================
    # CATEGORY + UNDERLYING ECONOMY
    # =====================================================

    categories = build_category_scores(
        policy_events
    )


    underlying_score = (
        build_underlying_score(
            categories
        )
    )


    # =====================================================
    # FINAL ECONOMIC SCORE
    #
    # Policy gets largest weight because this is a
    # Gold / Fed-oriented model.
    # =====================================================

    economic_score = round(

        (
            market_shock_score
            * 0.25
        )

        +

        (
            fed_policy_score
            * 0.50
        )

        +

        (
            underlying_score
            * 0.25
        ),

        1
    )


    result = {

        "score":
            economic_score,

        "market_shock_score":
            market_shock_score,

        "fed_policy_score":
            fed_policy_score,

        "underlying_score":
            underlying_score,

        "categories":
            categories,

        "events":
            scored_events[:15],

        "source":
            "Forex Factory",

        "two_year_confirmation":
            two_year_change_pct,

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

    ECON_CACHE[
        "last_2y"
    ] = two_year_change_pct


    return result
