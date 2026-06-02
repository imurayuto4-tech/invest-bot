"""
backtest.py — 最近データ(既定 2018-01-01〜今日)で戦略を検証する。
全ユニバースで比較:
  (1) 指数のみ VOO 買い持ち(基準)
  (2) コア+サヤ枠 等金額・退避なし
  (3) コア+サヤ枠 逆ボラ(#6)・退避なし
  (4) コア+サヤ枠 逆ボラ(#6)+ 暴落避難(#8)  ← 今のライブ設定
使い方(ネット必須):
  pip install yfinance pandas numpy
  python backtest.py                 # 2018-01-01〜今日
  python backtest.py --start 2015-01-01
  python backtest.py --rebal 5       # サヤ枠の入替間隔(営業日) 5=週次 21=月次(既定)
  python backtest.py --selftest      # ネット不要・合成データでエンジン検証のみ
注意: 手数料0・スリッページ無視・配当調整済み終値の近似。退避先は履歴の長いBILで代用(ライブはSGOV)。
"""
import argparse
import numpy as np
import pandas as pd

try:
    import config as C
    UNIVERSE = list(C.UNIVERSE)
    CORE = list(C.CORE_SYMBOLS)
    SLEEVE_PCT = float(C.SLEEVE_PCT)
    TOP_N = int(C.TOP_N)
    MOMENTUM_DAYS = int(C.MOMENTUM_DAYS)
    STOP_LOSS_PCT = float(C.STOP_LOSS_PCT)
    VOL_DAYS = int(getattr(C, "VOL_DAYS", 20))
    REGIME_SMA = int(getattr(C, "REGIME_SMA", 200))
    REGIME_BAND = float(getattr(C, "REGIME_BAND", 0.02))
except Exception:
    CORE = ["VOO", "VTI"]
    SLEEVE_PCT, TOP_N, MOMENTUM_DAYS, STOP_LOSS_PCT, VOL_DAYS = 0.15, 5, 60, 8.0, 20
    REGIME_SMA, REGIME_BAND = 200, 0.02
    UNIVERSE = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AMD"]

RESERVE = 0.01
SMA_DAYS = 200
REGIME_SYM = "SPY"
SAFE = "BIL"
BENCH = "VOO"
START_EQUITY = 100_000.0


def load_prices(tickers, start, end):
    import yfinance as yf
    raw = yf.download(tickers, start=start, end=end, auto_adjust=True,
                      progress=False, group_by="column")
    px = raw["Close"].copy() if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
    return px.dropna(how="all").ffill()


def synth_prices(tickers, start, end, seed=7):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, end)
    out = {}
    for t in tickers:
        if t == SAFE:
            mu, sig = 0.02 / 252, 0.0007
        elif t == REGIME_SYM:
            mu, sig = 0.0003, 0.012
        else:
            mu, sig = rng.uniform(-0.0002, 0.0008), rng.uniform(0.01, 0.035)
        out[t] = 100.0 * np.exp(np.cumsum(rng.normal(mu, sig, len(idx))))
    return pd.DataFrame(out, index=idx)


def run_strategy(px, IND, weighting, hedge, rebal=21):
    cols = list(px.columns)
    ci = {s: k for k, s in enumerate(cols)}
    P = px.values
    SMA, MOM, VOL = IND["sma"], IND["mom"], IND["vol"]
    rsma = IND["rsma"]
    uni_idx = [ci[s] for s in UNIVERSE if s in ci]
    core_idx = [ci[s] for s in CORE if s in ci]
    safe_idx = ci.get(SAFE)
    T = len(px)

    cash = START_EQUITY
    core_sh = {}
    sleeve_sh, entry = {}, {}
    hedged = False
    curve = np.empty(T)

    def val(book, i):
        s = 0.0
        for c, sh in book.items():
            v = P[i, c]
            if v == v:
                s += sh * v
        return s

    def equity(i):
        return cash + val(core_sh, i) + val(sleeve_sh, i)

    def set_core(targets, i):
        nonlocal cash
        for c in list(core_sh):
            v = P[i, c]
            if v == v:
                cash += core_sh[c] * v
            del core_sh[c]
        eq = equity(i)
        budget = eq * (1 - SLEEVE_PCT - RESERVE)
        usable = [c for c in targets if c is not None and P[i, c] == P[i, c]]
        if not usable:
            return
        per = budget / len(usable)
        for c in usable:
            sh = per / P[i, c]
            cash -= sh * P[i, c]
            core_sh[c] = sh

    for i in range(T):
        for c in list(sleeve_sh):
            v = P[i, c]
            if v == v and v <= entry[c] * (1 - STOP_LOSS_PCT / 100.0):
                cash += sleeve_sh[c] * v
                del sleeve_sh[c]; del entry[c]

        if hedge and i >= REGIME_SMA:
            price, m = P[i, ci[REGIME_SYM]], rsma[i]
            if m == m:
                nh = hedged
                if not hedged and price < m * (1 - REGIME_BAND):
                    nh = True
                elif hedged and price > m:
                    nh = False
                if nh != hedged:
                    hedged = nh
                    set_core([safe_idx] if hedged else core_idx, i)

        if i >= SMA_DAYS and (i - SMA_DAYS) % rebal == 0:
            set_core([safe_idx] if hedged else core_idx, i)
            cand = []
            for c in uni_idx:
                price, sma, mom, vol = P[i, c], SMA[i, c], MOM[i, c], VOL[i, c]
                if sma == sma and mom == mom and price > sma and mom > 0:
                    cand.append((c, mom, vol if (vol == vol and vol > 0) else 1e-6))
            cand.sort(key=lambda x: x[1], reverse=True)
            top = cand[:TOP_N]
            if top:
                if weighting == "invvol":
                    inv = {c: 1.0 / v for c, m, v in top}
                    tot = sum(inv.values())
                    w = {c: inv[c] / tot for c, m, v in top}
                else:
                    w = {c: 1.0 / len(top) for c, m, v in top}
            else:
                w = {}
            for c in list(sleeve_sh):
                if c not in w:
                    cash += sleeve_sh[c] * P[i, c]
                    del sleeve_sh[c]; del entry[c]
            budget = equity(i) * SLEEVE_PCT
            for c, wt in w.items():
                pr = P[i, c]
                if pr != pr:
                    continue
                tgt = budget * wt / pr
                cash -= (tgt - sleeve_sh.get(c, 0.0)) * pr
                sleeve_sh[c] = tgt
                entry.setdefault(c, pr)

        curve[i] = equity(i)

    return pd.Series(curve, index=px.index).iloc[SMA_DAYS:]


def indicators(px):
    return {
        "sma": px.rolling(SMA_DAYS, min_periods=SMA_DAYS).mean().values,
        "mom": (px / px.shift(MOMENTUM_DAYS) - 1.0).values,
        "vol": px.pct_change().rolling(VOL_DAYS, min_periods=VOL_DAYS).std().values,
        "rsma": px[REGIME_SYM].rolling(REGIME_SMA, min_periods=REGIME_SMA).mean().values,
    }


def benchmark(px):
    c = px[BENCH].ffill().iloc[SMA_DAYS:]
    return START_EQUITY * c / c.iloc[0]


def stats(curve):
    curve = curve.dropna()
    ret = curve.pct_change().dropna()
    yrs = (curve.index[-1] - curve.index[0]).days / 365.25
    cagr = (curve.iloc[-1] / curve.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else 0.0
    vol = ret.std() * np.sqrt(252)
    sharpe = ret.mean() * 252 / (ret.std() * np.sqrt(252)) if ret.std() > 0 else 0.0
    mdd = (curve / curve.cummax() - 1).min()
    return cagr, vol, sharpe, mdd, curve.iloc[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--rebal", type=int, default=21)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    tickers = sorted(set(UNIVERSE + CORE + [BENCH, REGIME_SYM, SAFE]))
    end = a.end or pd.Timestamp.today().strftime("%Y-%m-%d")

    if a.selftest:
        print("[selftest] 合成データでエンジン検証(数値に意味なし)…")
        px = synth_prices(tickers, "2016-01-01", "2024-01-01")
    else:
        print(f"データ取得中: {len(tickers)}銘柄 {a.start}〜{end} …")
        px = load_prices(tickers, a.start, end)
        print(f"取得: {px.shape[0]}営業日 × {px.shape[1]}銘柄")

    IND = indicators(px)
    results = {
        "(1) 指数のみ VOO": benchmark(px),
        "(2) 等金額・退避なし": run_strategy(px, IND, "equal", False, a.rebal),
        "(3) 逆ボラ#6・退避なし": run_strategy(px, IND, "invvol", False, a.rebal),
        "(4) 逆ボラ#6+#8退避(ライブ)": run_strategy(px, IND, "invvol", True, a.rebal),
    }
    print("\n================= 結果 =================")
    print("%-26s %12s %8s %9s %8s %8s" % ("戦略", "最終額", "CAGR", "年率ボラ", "Sharpe", "最大DD"))
    for name, c in results.items():
        cg, vol, sh, mdd, fin = stats(c)
        print("%-26s %12s %7.1f%% %8.1f%% %8.2f %7.1f%%" %
              (name, format(int(fin), ","), cg * 100, vol * 100, sh, mdd * 100))
    print("=" * 80)


if __name__ == "__main__":
    main()
