from flask import Flask, jsonify, render_template_string
from datetime import datetime, timezone
from urllib.parse import quote
from bs4 import BeautifulSoup
import requests
import time
import xml.etree.ElementTree as ET

app = Flask(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 Chrome/120 Safari/537.36"
}

CACHE = {
    "time": 0,
    "data": None
}

CACHE_SECONDS = 25


# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def clamp(value, minimum=0, maximum=100):
    return max(minimum, min(maximum, value))


def safe_round(value, digits=2):
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except Exception:
        return None


# --------------------------------------------------
# YAHOO MARKET DATA
# --------------------------------------------------

def yahoo_market(symbol):
    try:
        encoded = quote(symbol, safe="")
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{encoded}?interval=5m&range=1d"
        )

        r = requests.get(
            url,
            headers=HEADERS,
            timeout=8
        )

        r.raise_for_status()

        result = r.json()["chart"]["result"][0]
        meta = result["meta"]

        price = meta.get("regularMarketPrice")

        previous = (
            meta.get("chartPreviousClose")
            or meta.get("previousClose")
        )

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


# --------------------------------------------------
# TELEGRAM UTOFX
# --------------------------------------------------

def get_utofx_news(limit=8):
    try:
        url = "https://t.me/s/UtoFx"

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

            date_tag = message.select_one("time")

            date = None

            if date_tag:
                date = date_tag.get("datetime")

            link_tag = message.select_one(
                ".tgme_widget_message_date"
            )

            link = None

            if link_tag:
                link = link_tag.get("href")

            messages.append({
                "source": "UtoFX Telegram",
                "text": text[:700],
                "date": date,
                "link": link
            })

        return messages[-limit:][::-1]

    except Exception:
        return []


# --------------------------------------------------
# UTOTIMES
# --------------------------------------------------

def get_utotimes_news(limit=5):
    try:
        url = "https://utotimes.com/feed/"

        r = requests.get(
            url,
            headers=HEADERS,
            timeout=10
        )

        r.raise_for_status()

        root = ET.fromstring(r.content)

        news = []

        for item in root.findall(".//item")[:limit]:

            title = item.findtext("title")
            link = item.findtext("link")
            date = item.findtext("pubDate")

            if title:
                news.append({
                    "source": "UtoTimes",
                    "text": title.strip(),
                    "date": date,
                    "link": link
                })

        return news

    except Exception:
        return []


# --------------------------------------------------
# SCORING ENGINE
# --------------------------------------------------

def calculate_scores(markets):

    gold_change = (
        markets["gold"].get("change_pct")
        or 0
    )

    dxy_change = (
        markets["dxy"].get("change_pct")
        or 0
    )

    y2_change = (
        markets["us2y"].get("change_pct")
        or 0
    )

    y10_change = (
        markets["us10y"].get("change_pct")
        or 0
    )

    y30_change = (
        markets["us30y"].get("change_pct")
        or 0
    )

    oil_change = (
        markets["oil"].get("change_pct")
        or 0
    )

    vix_change = (
        markets["vix"].get("change_pct")
        or 0
    )


    # Dollar rising generally pressures gold
    dollar_score = clamp(
        50 - (dxy_change * 18)
    )


    # Rising yields generally pressure gold
    average_rate_move = (
        y2_change +
        y10_change +
        y30_change
    ) / 3

    rates_score = clamp(
        50 - (average_rate_move * 10)
    )


    # Gold intraday momentum
    technical_score = clamp(
        50 + (gold_change * 12)
    )


    # Rising VIX can support safe-haven demand
    market_flow_score = clamp(
        50 + (vix_change * 1.5)
    )


    # Oil rise may increase inflation/rate pressure.
    # Geopolitical effects will be handled separately later.
    oil_score = clamp(
        50 - (oil_change * 3)
    )


    # These three will be connected to the
    # economic calendar / Fed speech / NLP engine next.
    economic_score = 50
    fed_score = 50
    geopolitical_score = 50


    components = {
        "Economic Data": round(economic_score, 1),
        "Federal Reserve": round(fed_score, 1),
        "Rates": round(rates_score, 1),
        "US Dollar": round(dollar_score, 1),
        "Geopolitical Risk": round(geopolitical_score, 1),
        "Oil / Inflation": round(oil_score, 1),
        "Market Flow": round(market_flow_score, 1),
        "Technical": round(technical_score, 1)
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


    total = sum(
        components[name] * weights[name]
        for name in components
    )


    total = round(total, 1)


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


    return total, bias, components


# --------------------------------------------------
# MAIN DATA ENGINE
# --------------------------------------------------

def build_dashboard_data():

    now = time.time()

    if (
        CACHE["data"] is not None
        and now - CACHE["time"] < CACHE_SECONDS
    ):
        return CACHE["data"]


    markets = {

        "gold":
            yahoo_market("GC=F"),

        "dxy":
            yahoo_market("DX-Y.NYB"),

        "us2y":
            yahoo_market("2YY=F"),

        "us10y":
            yahoo_market("^TNX"),

        "us30y":
            yahoo_market("^TYX"),

        "oil":
            yahoo_market("CL=F"),

        "vix":
            yahoo_market("^VIX")
    }


    score, bias, components = (
        calculate_scores(markets)
    )


    telegram_news = get_utofx_news(8)

    utotimes_news = get_utotimes_news(5)


    data = {

        "score": score,

        "bias": bias,

        "components": components,

        "markets": markets,

        "telegram_news": telegram_news,

        "utotimes_news": utotimes_news,

        "updated":
            datetime.now(timezone.utc)
            .strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )
    }


    CACHE["time"] = now
    CACHE["data"] = data

    return data


# --------------------------------------------------
# API
# --------------------------------------------------

@app.route("/api/status")
def api_status():

    return jsonify(
        build_dashboard_data()
    )


# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------

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

* {
box-sizing:border-box;
}

body {

margin:0;

background:#080b12;

color:#fff;

font-family:
Arial,
Helvetica,
sans-serif;

}


.container {

max-width:1250px;

margin:auto;

padding:
30px 20px 60px;

}


.brand {

font-size:14px;

letter-spacing:4px;

color:#d8b96c;

font-weight:bold;

}


h1 {

margin:
8px 0 5px;

font-size:
clamp(
28px,
5vw,
42px
);

}


.subtitle {

color:#8f98aa;

margin-bottom:25px;

}


.hero {

background:#10151f;

border:
1px solid #222a39;

border-radius:18px;

padding:35px;

text-align:center;

}


.score-title {

color:#8f98aa;

font-size:13px;

letter-spacing:2px;

}


.score {

font-size:
clamp(
60px,
10vw,
95px
);

font-weight:bold;

margin-top:5px;

}


.score span {

font-size:22px;

color:#6f7888;

}


.bias {

display:inline-block;

padding:
9px 18px;

border-radius:30px;

background:#1a2130;

color:#d8b96c;

font-weight:bold;

}


.bar {

max-width:650px;

height:10px;

background:#252c39;

border-radius:10px;

overflow:hidden;

margin:
30px auto 5px;

}


.bar-fill {

height:100%;

width:{{ data.score }}%;

background:
linear-gradient(
90deg,
#c84a4a,
#d8b96c,
#51b77a
);

}


.scale {

max-width:650px;

margin:auto;

display:flex;

justify-content:
space-between;

font-size:11px;

color:#727b8b;

}


.section-title {

margin:
35px 0 15px;

font-size:21px;

}


.market-grid {

display:grid;

grid-template-columns:
repeat(
auto-fit,
minmax(
155px,
1fr
)
);

gap:12px;

}


.market-card {

background:#10151f;

border:
1px solid #222a39;

border-radius:14px;

padding:17px;

}


.market-title {

color:#8e98a9;

font-size:13px;

}


.market-price {

font-size:25px;

font-weight:bold;

margin-top:8px;

}


.positive {

color:#55c987;

}


.negative {

color:#e46c6c;

}


.neutral {

color:#9099a8;

}


.components {

display:grid;

grid-template-columns:
repeat(
auto-fit,
minmax(
210px,
1fr
)
);

gap:12px;

}


.component {

background:#10151f;

border:
1px solid #222a39;

border-radius:14px;

padding:18px;

}


.component-name {

color:#929bab;

font-size:13px;

}


.component-score {

font-size:29px;

font-weight:bold;

margin-top:8px;

}


.news-grid {

display:grid;

grid-template-columns:
1fr 1fr;

gap:18px;

}


.news-column {

background:#10151f;

border:
1px solid #222a39;

border-radius:14px;

padding:20px;

}


.news-title {

font-size:18px;

font-weight:bold;

margin-bottom:15px;

}


.news-item {

border-top:
1px solid #222a39;

padding:
14px 0;

}


.news-item:first-of-type {

border-top:0;

}


.news-text {

font-size:14px;

line-height:1.7;

direction:rtl;

text-align:right;

}


.news-meta {

font-size:11px;

color:#707a8b;

margin-top:7px;

}


.news-item a {

color:inherit;

text-decoration:none;

}


.status {

margin-top:25px;

background:#10151f;

border:
1px solid #222a39;

border-radius:14px;

padding:18px;

}


.online {

color:#55c987;

font-weight:bold;

}


.note {

color:#778192;

font-size:12px;

line-height:1.6;

margin-top:10px;

}


@media
(max-width:750px) {

.news-grid {

grid-template-columns:1fr;

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

<div
class="bar-fill">

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


{% for key, item in data.markets.items() %}


<div class="market-card">


<div class="market-title">

{{ names[key] }}

</div>


<div class="market-price">

{% if item.price is not none %}

{{ item.price }}

{% else %}

N/A

{% endif %}

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

<span
style="
font-size:14px;
color:#697282;
">

/100

</span>


</div>


</div>


{% endfor %}


</div>



<div class="section-title">

Live News Monitor

</div>


<div class="news-grid">


<div class="news-column">


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

{{ news.date or "" }}

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



<div class="news-column">


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

{{ news.date or "" }}

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

Dashboard refresh:
30 seconds

</div>


<div class="note">

Economic Data, Fed speech analysis
and Geopolitical NLP scoring
will be connected in the next stage.

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
