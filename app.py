from flask import Flask, jsonify, render_template_string
from datetime import datetime, timezone

app = Flask(__name__)


def calculate_gold_score():
    """
    Initial version of the Gold Intelligence Indicator.

    Live economic, Fed, rates, DXY, geopolitical and technical
    data sources will be connected in the next stage.

    50 = Neutral
    100 = Strongly bullish for gold
    0 = Strongly bearish for gold
    """

    components = {
        "Economic Data": 50,
        "Federal Reserve": 50,
        "Rates": 50,
        "US Dollar": 50,
        "Geopolitical Risk": 50,
        "Oil / Inflation": 50,
        "Market Flow": 50,
        "Technical": 50,
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

    score = sum(
        components[name] * weights[name]
        for name in components
    )

    if score >= 70:
        bias = "BULLISH"
    elif score >= 57:
        bias = "MODERATELY BULLISH"
    elif score <= 30:
        bias = "BEARISH"
    elif score <= 43:
        bias = "MODERATELY BEARISH"
    else:
        bias = "NEUTRAL"

    return {
        "score": round(score, 1),
        "bias": bias,
        "components": components,
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "status": "Engine online — live data connections pending",
    }


@app.route("/api/status")
def api_status():
    return jsonify(calculate_gold_score())


@app.route("/")
def dashboard():
    data = calculate_gold_score()

    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">

        <title>FINAD Gold Intelligence</title>

        <style>

            * {
                box-sizing: border-box;
            }

            body {
                margin: 0;
                background: #080b12;
                color: #ffffff;
                font-family: Arial, Helvetica, sans-serif;
            }

            .container {
                max-width: 1200px;
                margin: auto;
                padding: 30px 20px 60px;
            }

            .top {
                margin-bottom: 30px;
            }

            .brand {
                font-size: 14px;
                letter-spacing: 4px;
                color: #d8b96c;
                font-weight: bold;
            }

            h1 {
                margin-top: 8px;
                margin-bottom: 5px;
                font-size: 34px;
            }

            .subtitle {
                color: #8f98aa;
            }

            .hero {
                background: #10151f;
                border: 1px solid #222a39;
                border-radius: 18px;
                padding: 35px;
                margin-top: 25px;
                text-align: center;
            }

            .score-title {
                color: #8f98aa;
                font-size: 14px;
                letter-spacing: 2px;
            }

            .score {
                font-size: 84px;
                font-weight: bold;
                margin-top: 10px;
            }

            .score span {
                font-size: 24px;
                color: #777f8f;
            }

            .bias {
                display: inline-block;
                margin-top: 5px;
                padding: 10px 18px;
                border-radius: 30px;
                background: #1a2130;
                color: #d8b96c;
                font-weight: bold;
                letter-spacing: 1px;
            }

            .bar {
                max-width: 600px;
                height: 10px;
                border-radius: 10px;
                overflow: hidden;
                background: #252c39;
                margin: 30px auto 5px;
            }

            .bar-fill {
                height: 100%;
                width: {{ data.score }}%;
                background: linear-gradient(
                    90deg,
                    #c84a4a,
                    #d8b96c,
                    #51b77a
                );
            }

            .scale {
                max-width: 600px;
                margin: 5px auto;
                display: flex;
                justify-content: space-between;
                color: #737d8e;
                font-size: 12px;
            }

            .grid {
                margin-top: 28px;
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                gap: 15px;
            }

            .card {
                background: #10151f;
                border: 1px solid #222a39;
                border-radius: 14px;
                padding: 20px;
            }

            .card-name {
                color: #919aaa;
                font-size: 14px;
            }

            .card-score {
                font-size: 30px;
                margin-top: 8px;
                font-weight: bold;
            }

            .card-score span {
                color: #616979;
                font-size: 16px;
            }

            .status-box {
                margin-top: 25px;
                padding: 18px 20px;
                background: #10151f;
                border: 1px solid #222a39;
                border-radius: 14px;
            }

            .online {
                color: #53c985;
                font-weight: bold;
            }

            .updated {
                margin-top: 8px;
                color: #747e90;
                font-size: 13px;
            }

            .warning {
                margin-top: 20px;
                color: #7f899a;
                font-size: 13px;
                line-height: 1.7;
            }

        </style>

    </head>

    <body>

        <div class="container">

            <div class="top">

                <div class="brand">
                    FINAD
                </div>

                <h1>
                    Gold Intelligence Indicator
                </h1>

                <div class="subtitle">
                    Macro • Federal Reserve • Rates • Dollar • Geopolitics • Technical
                </div>

            </div>


            <div class="hero">

                <div class="score-title">
                    GOLD SCORE
                </div>

                <div class="score">
                    {{ data.score }}
                    <span>/ 100</span>
                </div>

                <div class="bias">
                    {{ data.bias }}
                </div>


                <div class="bar">
                    <div class="bar-fill"></div>
                </div>

                <div class="scale">
                    <span>BEARISH</span>
                    <span>NEUTRAL</span>
                    <span>BULLISH</span>
                </div>

            </div>


            <div class="grid">

                {% for name, value in data.components.items() %}

                <div class="card">

                    <div class="card-name">
                        {{ name }}
                    </div>

                    <div class="card-score">
                        {{ value }}
                        <span>/100</span>
                    </div>

                </div>

                {% endfor %}

            </div>


            <div class="status-box">

                <div>
                    SYSTEM STATUS:
                    <span class="online">
                        ONLINE
                    </span>
                </div>

                <div class="updated">
                    {{ data.status }}
                </div>

                <div class="updated">
                    Last calculation:
                    {{ data.updated }}
                </div>

            </div>


            <div class="warning">
                V1 infrastructure test. Scores are neutral placeholders until
                live market, economic calendar, Federal Reserve and news feeds
                are connected.
            </div>

        </div>


        <script>

            setTimeout(function () {
                window.location.reload();
            }, 30000);

        </script>

    </body>

    </html>
    """

    return render_template_string(html, data=data)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
