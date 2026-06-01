import os

API_KEY = os.environ.get("ALPACA_API_KEY", "")
SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
PAPER = True

# --- 90%: インデックス積み立て ---
DCA_PLAN = {"VOO": 450, "VTI": 450}

# --- 10%: モメンタム・スキャン(旬の株を自動で選ぶ) ---
SLEEVE_PCT = 0.10        # 資産の10%まで
TOP_N = 5                # 勢い上位 何社を保有するか
MOMENTUM_DAYS = 60       # 直近何日の上昇率で勢いを測るか
STOP_LOSS_PCT = 8.0      # -8%で損切り

# スキャンする候補(ここから旬の上位TOP_N社が自動で選ばれる)
UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AMD",
    "NFLX", "AVGO", "CRM", "ADBE", "ORCL", "INTC", "QCOM", "CSCO",
    "JPM", "BAC", "V", "MA", "WMT", "COST", "HD", "MCD", "NKE",
    "DIS", "KO", "PEP", "PG", "JNJ", "UNH", "XOM", "CVX", "BA",
    "CAT", "GE", "UBER", "PYPL", "SHOP", "PLTR",
]
