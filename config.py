import os

API_KEY = os.environ.get("ALPACA_API_KEY", "")
SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
PAPER = True

CORE_SYMBOLS = ["VOO", "VTI"]

SLEEVE_PCT = 0.10
TOP_N = 5
MOMENTUM_DAYS = 60
STOP_LOSS_PCT = 8.0

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
