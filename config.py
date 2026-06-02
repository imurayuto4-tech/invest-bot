import os

API_KEY = os.environ.get("ALPACA_API_KEY", "")
SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
PAPER = True

# --- 85%: インデックス・コア ---
CORE_SYMBOLS = ["VOO", "VTI"]

# --- 15%: モメンタム・スキャン(能動枠) ---
SLEEVE_PCT = 0.15
TOP_N = 5
MOMENTUM_DAYS = 60
STOP_LOSS_PCT = 8.0

# --- #6 リスク配分(逆ボラティリティ) ---
# "equal"=等金額 / "invvol"=穏やかな株を多め・激しい株を少なめ
WEIGHTING = "invvol"
VOL_DAYS = 20

# --- #8 暴落避難(リジーム・フィルター) ---
# 市場全体(SPY)が200日線を割ったら、コアを短期国債ETF(SGOV)に退避。回復で戻す。
CRASH_HEDGE = True
REGIME_SYMBOL = "SPY"     # 市場全体の代理(S&P500連動)
REGIME_SMA = 200          # 判定に使う移動平均(日数)
REGIME_BAND = 0.02        # 200日線×(1-0.02)割れで退避 / 線を上抜けで復帰(だまし対策)
SAFE_SYMBOL = "SGOV"      # 退避先:超短期米国債ETF

UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AMD",
    "AVGO", "ORCL", "ADBE", "CRM", "INTC", "QCOM", "CSCO", "TXN",
    "MU", "AMAT", "LRCX", "ADI", "INTU", "NOW", "PANW", "SNPS",
    "CDNS", "KLAC", "MRVL", "ARM", "SMCI", "DELL",
    "NFLX", "UBER", "SHOP", "PLTR", "SNOW", "CRWD", "DDOG", "NET",
    "ABNB", "PYPL", "SQ", "COIN", "ROKU", "SPOT", "ZM",
    "JPM", "BAC", "WFC", "GS", "MS", "C", "V", "MA", "AXP", "BLK", "SCHW",
    "WMT", "COST", "HD", "LOW", "TGT", "MCD", "SBUX", "NKE", "LULU",
    "DIS", "KO", "PEP", "PG", "CL", "MDLZ",
    "JNJ", "UNH", "LLY", "PFE", "MRK", "ABBV", "TMO", "ABT", "DHR", "AMGN",
    "XOM", "CVX", "COP", "SLB", "BA", "CAT", "GE", "HON", "DE",
    "LMT", "RTX", "UPS", "FDX",
    "T", "VZ", "CMCSA", "F", "GM", "DAL", "MMM",
]
