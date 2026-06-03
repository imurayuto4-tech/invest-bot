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
STOP_LOSS_PCT = 8.0       # STOP_MODE="fixed" のときの一律損切り幅 / atrの保険値

# --- #6 リスク配分(逆ボラティリティ) ---
WEIGHTING = "invvol"
VOL_DAYS = 20

# --- #8 暴落避難(リジーム・フィルター) ---
CRASH_HEDGE = True
REGIME_SYMBOL = "SPY"
REGIME_SMA = 200
REGIME_BAND = 0.02
SAFE_SYMBOL = "SGOV"

# --- #4 本物の損切り注文 ---
USE_STOP_ORDERS = True
# 損切り幅: "fixed"=一律 STOP_LOSS_PCT% / "atr"=ボラ連動(STOP_K×日次ボラ%, MIN〜MAXで挟む)
STOP_MODE = "atr"
STOP_K = 4.0
STOP_MIN_PCT = 5.0
STOP_MAX_PCT = 18.0

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
