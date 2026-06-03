"""
backtest.py — 最近データ(既定 2018-01-01〜今日)で戦略を検証。
比較:
  (1) 指数のみ VOO
  (2) 現行       : 逆ボラ#6 + #8退避 + ボラ連動ストップ(rank入替・株のみ)
  (3) 勝ち伸ばし : 上をトレーリングストップ&崩れるまで保有(株のみ)
  (4) +crypto    : 勝ち伸ばし に BTC/ETH を同ルールで追加
使い方: pip install yfinance pandas numpy ; python backtest.py --start 2018-01-01
        python backtest.py --selftest   (ネット不要・エンジン確認)
注意: 手数料0・スリッページ無視・配当調整済み終値の近似。退避先BIL(ライブはSGOV)。
      cryptoは日足を株の営業日に合わせてサンプリング(週末の値動きは粗く扱う近似)。
"""
import argparse
import numpy as np
import pandas as pd

try:
    import config as C
    UNIVERSE = list(C.UNIVERSE); CORE = list(C.CORE_SYMBOLS)
    SLEEVE_PCT = float(C.SLEEVE_PCT); TOP_N = int(C.TOP_N)
    MOMENTUM_DAYS = int(C.MOMENTUM_DAYS); STOP_LOSS_PCT = float(C.STOP_LOSS_PCT)
    VOL_DAYS = int(getattr(C, "VOL_DAYS", 20))
    REGIME_SMA = int(getattr(C, "REGIME_SMA", 200)); REGIME_BAND = float(getattr(C, "REGIME_BAND", 0.02))
    STOP_K = float(getattr(C, "STOP_K", 4.0)); STOP_MIN_PCT = float(getattr(C, "STOP_MIN_PCT", 5.0))
    STOP_MAX_PCT = float(getattr(C, "STOP_MAX_PCT", 18.0))
except Exception:
    CORE = ["VOO", "VTI"]
    SLEEVE_PCT, TOP_N, MOMENTUM_DAYS, STOP_LOSS_PCT, VOL_DAYS = 0.15, 5, 60, 8.0, 20
    REGIME_SMA, REGIME_BAND, STOP_K, STOP_MIN_PCT, STOP_MAX_PCT = 200, 0.02, 4.0, 5.0, 18.0
    UNIVERSE = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AMD"]

CRYPTO = ["BTC-USD", "ETH-USD"]
RESERVE = 0.01; SMA_DAYS = 200; REGIME_SYM = "SPY"; SAFE = "BIL"; BENCH = "VOO"; START_EQUITY = 100_000.0


def bt_stop_pct(vol_daily, mode):
    if mode == "atr" and vol_daily == vol_daily and vol_daily > 0:
        return min(max(STOP_K * vol_daily * 100.0, STOP_MIN_PCT), STOP_MAX_PCT)
    return STOP_LOSS_PCT


def load_prices(tickers, start, end):
    import yfinance as yf
    raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False, group_by="column")
    px = raw["Close"].copy() if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
    px = px.dropna(how="all").ffill()
    if BENCH in px:
        px = px.loc[px[BENCH].notna()]
    return px


def synth_prices(tickers, start, end, seed=7):
    rng = np.random.default_rng(seed); idx = pd.bdate_range(start, end); out = {}
    for t in tickers:
        if t == SAFE: mu, sig = 0.02 / 252, 0.0007
        elif t == REGIME_SYM: mu, sig = 0.0003, 0.012
        elif t in CRYPTO: mu, sig = rng.uniform(0.0, 0.0012), rng.uniform(0.04, 0.06)
        else: mu, sig = rng.uniform(-0.0002, 0.0008), rng.uniform(0.01, 0.035)
        out[t] = 100.0 * np.exp(np.cumsum(rng.normal(mu, sig, len(idx))))
    return pd.DataFrame(out, index=idx)


def run_strategy(px, IND, weighting, hedge, rebal=21, stop_mode="fixed",
                 sleeve_style="rotate", use_crypto=False):
    cols = list(px.columns); ci = {s: k for k, s in enumerate(cols)}; P = px.values
    SMA, MOM, VOL = IND["sma"], IND["mom"], IND["vol"]; rsma = IND["rsma"]
    uni = list(UNIVERSE) + (CRYPTO if use_crypto else [])
    uni_idx = [ci[s] for s in uni if s in ci]
    core_idx = [ci[s] for s in CORE if s in ci]; safe_idx = ci.get(SAFE); T = len(px)
    cash = START_EQUITY; core_sh = {}; sleeve_sh, entry, estop, hi = {}, {}, {}, {}; hedged = False
    curve = np.empty(T)

    def val(book, i):
        s = 0.0
        for c, sh in book.items():
            v = P[i, c]
            if v == v: s += sh * v
        return s

    def equity(i): return cash + val(core_sh, i) + val(sleeve_sh, i)

    def drop(c):
        for d in (sleeve_sh, entry, estop, hi):
            d.pop(c, None)

    def set_core(targets, i):
        nonlocal cash
        for c in list(core_sh):
            v = P[i, c]
            if v == v: cash += core_sh[c] * v
            del core_sh[c]
        eq = equity(i); budget = eq * (1 - SLEEVE_PCT - RESERVE)
        usable = [c for c in targets if c is not None and P[i, c] == P[i, c]]
        if not usable: return
        per = budget / len(usable)
        for c in usable:
            sh = per / P[i, c]; cash -= sh * P[i, c]; core_sh[c] = sh

    for i in range(T):
        for c in list(sleeve_sh):
            v = P[i, c]
            if v != v: continue
            if v > hi[c]: hi[c] = v
            ref = hi[c] if sleeve_style == "trail" else entry[c]
            if v <= ref * (1 - estop[c] / 100.0):
                cash += sleeve_sh[c] * v; drop(c)

        if hedge and i >= REGIME_SMA:
            price, m = P[i, ci[REGIME_SYM]], rsma[i]
            if m == m:
                nh = hedged
                if not hedged and price < m * (1 - REGIME_BAND): nh = True
                elif hedged and price > m: nh = False
                if nh != hedged:
                    hedged = nh; set_core([safe_idx] if hedged else core_idx, i)

        if i >= SMA_DAYS and (i - SMA_DAYS) % rebal == 0:
            set_core([safe_idx] if hedged else core_idx, i)
            cand = []
            for c in uni_idx:
                price, sma, mom, vol = P[i, c], SMA[i, c], MOM[i, c], VOL[i, c]
                if sma == sma and mom == mom and price > sma and mom > 0:
                    cand.append((c, mom, vol if (vol == vol and vol > 0) else 1e-6))
            cand.sort(key=lambda x: x[1], reverse=True)

            if sleeve_style == "trail":
                cset = {c for c, m, v in cand}
                for c in list(sleeve_sh):
                    if c not in cset:
                        cash += sleeve_sh[c] * P[i, c]; drop(c)
                slots = TOP_N - len(sleeve_sh)
                if slots > 0:
                    new = [(c, m, v) for c, m, v in cand if c not in sleeve_sh][:slots]
                    budget = max(0.0, equity(i) * SLEEVE_PCT - val(sleeve_sh, i))
                    if new and budget > 0:
                        if weighting == "invvol":
                            inv = {c: 1.0 / v for c, m, v in new}; tot = sum(inv.values())
                            w = {c: inv[c] / tot for c, m, v in new}
                        else:
                            w = {c: 1.0 / len(new) for c, m, v in new}
                        for c, wt in w.items():
                            pr = P[i, c]
                            if pr != pr: continue
                            sh = budget * wt / pr
                            cash -= sh * pr; sleeve_sh[c] = sh
                            entry[c] = pr; hi[c] = pr; estop[c] = bt_stop_pct(VOL[i, c], stop_mode)
            else:
                top = cand[:TOP_N]
                if top:
                    if weighting == "invvol":
                        inv = {c: 1.0 / v for c, m, v in top}; tot = sum(inv.values())
                        w = {c: inv[c] / tot for c, m, v in top}
                    else:
                        w = {c: 1.0 / len(top) for c, m, v in top}
                else:
                    w = {}
                for c in list(sleeve_sh):
                    if c not in w:
                        cash += sleeve_sh[c] * P[i, c]; drop(c)
                budget = equity(i) * SLEEVE_PCT
                for c, wt in w.items():
                    pr = P[i, c]
                    if pr != pr: continue
                    tgt = budget * wt / pr; cash -= (tgt - sleeve_sh.get(c, 0.0)) * pr; sleeve_sh[c] = tgt
                    if c not in entry:
                        entry[c] = pr; hi[c] = pr; estop[c] = bt_stop_pct(VOL[i, c], stop_mode)

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
    curve = curve.dropna(); ret = curve.pct_change().dropna()
    yrs = (curve.index[-1] - curve.index[0]).days / 365.25
    cagr = (curve.iloc[-1] / curve.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else 0.0
    vol = ret.std() * np.sqrt(252)
    sharpe = ret.mean() * 252 / (ret.std() * np.sqrt(252)) if ret.std() > 0 else 0.0
    mdd = (curve / curve.cummax() - 1).min()
    return cagr, vol, sharpe, mdd, curve.iloc[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2018-01-01"); ap.add_argument("--end", default=None)
    ap.add_argument("--rebal", type=int, default=21); ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    tickers = sorted(set(UNIVERSE + CRYPTO + CORE + [BENCH, REGIME_SYM, SAFE]))
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
        "(2) 現行(入替・株のみ)": run_strategy(px, IND, "invvol", True, a.rebal, "atr", "rotate", False),
        "(3) 勝ち伸ばし(株のみ)": run_strategy(px, IND, "invvol", True, a.rebal, "atr", "trail", False),
        "(4) 勝ち伸ばし+crypto": run_strategy(px, IND, "invvol", True, a.rebal, "atr", "trail", True),
    }
    print("\n================= 結果 =================")
    print("%-24s %12s %8s %9s %8s %8s" % ("戦略", "最終額", "CAGR", "年率ボラ", "Sharpe", "最大DD"))
    for name, c in results.items():
        cg, vol, sh, mdd, fin = stats(c)
        print("%-24s %12s %7.1f%% %8.1f%% %8.2f %7.1f%%" %
              (name, format(int(fin), ","), cg * 100, vol * 100, sh, mdd * 100))
    print("=" * 80)


if __name__ == "__main__":
    main()
