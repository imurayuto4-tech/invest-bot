import os

API_KEY = os.environ.get("ALPACA_API_KEY", "")
SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
PAPER = True

# --- 中長期コアは撤廃(短期特化) ---
# 中長期の積み立ては別口で運用するため、このボットは短期モメンタムに全振り。
CORE_SYMBOLS = []

# --- 短期モメンタム枠(ほぼ全力) ---
SLEEVE_PCT = 0.97         # 資産の約97%を投入(残り3%は現金=レバレッジ防止)
TOP_N = 5
MOMENTUM_DAYS = 20        # 短期化(60→20日モメンタム)。数日〜2週間のスイング
STOP_LOSS_PCT = 8.0       # STOP_MODE="fixed" のときの一律損切り幅 / atrの保険値

# --- リスク配分(均等=攻め型) ---
WEIGHTING = "equal"       # 均等配分。動きの大きい銘柄にもしっかり乗る
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
