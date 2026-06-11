import os

API_KEY = os.environ.get("ALPACA_API_KEY", "")
SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
PAPER = True

# --- 中長期コアは撤廃(短期特化) ---
# 中長期の積み立ては別口で運用するため、このボットは短期モメンタムに全振り。
CORE_SYMBOLS = []

# --- 短期モメンタム枠(ほぼ全力) ---
SLEEVE_PCT = 0.97         # ロング/ショート合計で資産の約97%まで(残り3%現金=レバ防止)
TOP_N = 10                # 「条件を満たした分だけ最大10銘柄」の可変式(少なければ自動で現金多め)
MOMENTUM_DAYS = 20        # 短期化(60→20日モメンタム)。数日〜2週間のスイング
STOP_LOSS_PCT = 8.0       # STOP_MODE="fixed" のときの一律損切り幅 / atrの保険値

# --- ショート(空売り) ---
# 通常はロングのみ。下落局面(SPYが200日線割れ)では現金退避の代わりに弱い銘柄を空売り。
# レバ無し維持: 同方向の総建玉<=SLEEVE_PCT。出口はトレーリングストップ(安値から戻したら買戻し)。
ALLOW_SHORT = True

# --- リスク配分(均等=攻め型) ---
WEIGHTING = "equal"       # 均等配分。動きの大きい銘柄にもしっかり乗る
VOL_DAYS = 20

# --- #8 暴落避難(リジーム・フィルター) ---
CRASH_HEDGE = True
REGIME_SYMBOL = "SPY"
REGIME_SMA = 200
REGIME_BAND = 0.02
SAFE_SYMBOL = "SGOV"

# --- ストップ(トレーリング: 利を伸ばし、ピークから戻したら自動決済) ---
# トレール幅(%): "fixed"=一律 STOP_LOSS_PCT% / "atr"=ボラ連動(STOP_K×日次ボラ%, MIN〜MAXで挟む)
STOP_MODE = "atr"
STOP_K = 4.0
STOP_MIN_PCT = 5.0
STOP_MAX_PCT = 18.0

# 流動性の高い米国上場株 約200銘柄(無料IEXデータで精度を保てる範囲)。
UNIVERSE = [
    # --- メガキャップ/テック ---
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "ORCL", "ADBE", "CRM",
    # --- 半導体 ---
    "AMD", "INTC", "QCOM", "TXN", "MU", "AMAT", "LRCX", "ADI", "KLAC", "MRVL", "ARM",
    "SMCI", "MCHP", "NXPI", "ON", "SWKS", "QRVO", "TER", "ASML", "TSM", "ANET", "GLW",
    # --- ハードウェア/通信機器 ---
    "DELL", "HPQ", "HPE", "NTAP", "STX", "WDC", "CSCO",
    # --- ソフトウェア/ネット ---
    "NOW", "PANW", "SNPS", "CDNS", "INTU", "NFLX", "UBER", "SHOP", "PLTR", "SNOW", "CRWD",
    "DDOG", "NET", "ZS", "OKTA", "MDB", "TEAM", "WDAY", "HUBS", "TTD", "FTNT", "DOCU",
    "TWLO", "GTLB", "PATH", "ROKU", "SPOT", "ZM", "SNAP", "PINS", "MTCH", "EA", "TTWO",
    "RBLX", "U", "DASH", "ABNB",
    # --- フィンテック/決済 ---
    "PYPL", "XYZ", "COIN", "AFRM", "HOOD", "SOFI", "V", "MA", "AXP",
    # --- 中国/海外ADR ---
    "BABA", "PDD", "JD", "SE", "MELI", "NU",
    # --- 銀行/金融 ---
    "JPM", "BAC", "WFC", "GS", "MS", "C", "BLK", "SCHW", "USB", "PNC", "TFC", "COF",
    "SYF", "ICE", "CME", "SPGI", "MCO", "MSCI", "MMC", "PGR", "TRV", "ALL", "CB",
    "MET", "PRU", "AIG", "KKR", "BX", "APO",
    # --- 消費(裁量) ---
    "WMT", "COST", "HD", "LOW", "TGT", "MCD", "SBUX", "NKE", "LULU", "CMG", "ORLY", "AZO",
    "ROST", "TJX", "DG", "DLTR", "YUM", "MAR", "HLT", "RCL", "CCL", "LVS", "WYNN", "MGM",
    "DKNG", "ELF",
    # --- 消費(生活必需品)/メディア ---
    "DIS", "KO", "PEP", "PG", "CL", "MDLZ", "KMB", "GIS", "KHC", "MNST", "KDP", "STZ",
    "CLX", "HSY",
    # --- ヘルスケア ---
    "JNJ", "UNH", "LLY", "PFE", "MRK", "ABBV", "TMO", "ABT", "DHR", "AMGN", "ISRG", "VRTX",
    "REGN", "GILD", "BMY", "CVS", "CI", "ELV", "MCK", "ZTS", "BSX", "SYK", "MDT", "EW",
    "IDXX", "DXCM", "MRNA", "BIIB", "HCA", "RMD", "BDX",
    # --- 資本財/工業 ---
    "BA", "CAT", "GE", "HON", "DE", "LMT", "RTX", "UPS", "FDX", "MMM", "EMR", "ETN", "PH",
    "ITW", "GD", "NOC", "TDG", "CSX", "NSC", "UNP", "ODFL", "WM", "RSG", "PCAR", "CMI",
    "ROK", "AME",
    # --- エネルギー ---
    "XOM", "CVX", "COP", "SLB", "EOG", "PSX", "MPC", "VLO", "OXY", "WMB", "KMI", "OKE",
    "HAL", "DVN", "FANG",
    # --- 素材 ---
    "LIN", "APD", "SHW", "FCX", "NEM", "NUE", "DOW", "ECL",
    # --- 通信/自動車 ---
    "T", "VZ", "CMCSA", "F", "GM", "DAL",
]
