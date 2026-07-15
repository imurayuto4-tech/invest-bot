"""
backtest.py — live戦略(invest.py の run/trade_sleeve)を日足で忠実再現して検証。
ロング/ショート両対応。旧設定(負けてた本番) vs 新設定(①〜③反映) を直接比較する。

比較:
  (1) 指数のみ VOO
  (2) 旧設定       : SLEEVE0.97 / 入替ヒステリシス無し(keep=top) / トレンド割れ決済無し
  (3) 新設定 ①②③ : SLEEVE0.80 / keep=15 / 20日線割れで決済
  (4) 新設定・ロングのみ: (3)からショートを外し、ショートの寄与を切り分け

使い方: pip install yfinance pandas numpy
        python backtest.py --start 2018-01-01        (フル期間)
        python backtest.py --selftest                (ネット不要・エンジン確認)
注意: 手数料0・スリッページ無視・配当調整済み終値の近似。退避先BIL(ライブはSGOV)。
      実運用は毎営業日判断(end=now-1day)なので rebal=1(日次)を既定にして忠実性を上げている。
      ショートは日足終値ベースで近似(借株コスト・逆日歩は無視)。
"""
import argparse
import numpy as np
import pandas as pd

try:
    import config as C
    UNIVERSE = list(C.UNIVERSE)
    SLEEVE_PCT = float(C.SLEEVE_PCT); TOP_N = int(C.TOP_N)
    KEEP_N = int(getattr(C, "KEEP_N", TOP_N))
    MOMENTUM_DAYS = int(C.MOMENTUM_DAYS); STOP_LOSS_PCT = float(C.STOP_LOSS_PCT)
    EXIT_SMA = int(getattr(C, "EXIT_SMA", 20))
    VOL_DAYS = int(getattr(C, "VOL_DAYS", 20))
    WEIGHTING = str(getattr(C, "WEIGHTING", "equal"))
    ALLOW_SHORT = bool(getattr(C, "ALLOW_SHORT", True))
    REGIME_SMA = int(getattr(C, "REGIME_SMA", 200)); REGIME_BAND = float(getattr(C, "REGIME_BAND", 0.02))
    STOP_MODE = str(getattr(C, "STOP_MODE", "atr"))
    STOP_K = float(getattr(C, "STOP_K", 4.0)); STOP_MIN_PCT = float(getattr(C, "STOP_MIN_PCT", 5.0))
    STOP_MAX_PCT = float(getattr(C, "STOP_MAX_PCT", 18.0))
except Exception:
    SLEEVE_PCT, TOP_N, KEEP_N, MOMENTUM_DAYS, STOP_LOSS_PCT = 0.80, 10, 15, 20, 8.0
    EXIT_SMA, VOL_DAYS, WEIGHTING, ALLOW_SHORT = 20, 20, "equal", True
    REGIME_SMA, REGIME_BAND, STOP_MODE, STOP_K, STOP_MIN_PCT, STOP_MAX_PCT = 200, 0.02, "atr", 4.0, 5.0, 18.0
    UNIVERSE = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AMD"]

RESERVE = 0.01; SMA_DAYS = 200; REGIME_SYM = "SPY"; SAFE = "BIL"; BENCH = "VOO"; START_EQUITY = 100_000.0


def bt_stop_pct(vol_daily, mode):
    if mode == "atr" and vol_daily == vol_daily and vol_daily > 0:
        return min(max(STOP_K * vol_daily * 100.0, STOP_MIN_PCT), STOP_MAX_PCT)
    return STOP_LOSS_PCT


def load_prices(tickers, start, end):
    import yfinance as yf
    raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False, group_by="column")
    px = raw["Close"].copy() if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
    if BENCH in px.columns:
        px = px[px[BENCH].notna()]      # 株の営業日だけへ
    return px.ffill()


def synth_prices(tickers, start, end, seed=7):
    rng = np.random.default_rng(seed); idx = pd.bdate_range(start, end); out = {}
    for t in tickers:
        if t == SAFE: mu, sig = 0.02 / 252, 0.0007
        elif t == REGIME_SYM: mu, sig = 0.0002, 0.014
        else: mu, sig = rng.uniform(-0.0004, 0.0009), rng.uniform(0.01, 0.035)
        out[t] = 100.0 * np.exp(np.cumsum(rng.normal(mu, sig, len(idx))))
    return pd.DataFrame(out, index=idx)


def indicators(px):
    return {
        "sma": px.rolling(SMA_DAYS, min_periods=SMA_DAYS).mean().values,
        "smax": px.rolling(EXIT_SMA, min_periods=EXIT_SMA).mean().values,   # 個別トレンド割れ判定線
        "mom": (px / px.shift(MOMENTUM_DAYS) - 1.0).values,
        "vol": px.pct_change().rolling(VOL_DAYS, min_periods=VOL_DAYS).std().values,
        "rsma": px[REGIME_SYM].rolling(REGIME_SMA, min_periods=REGIME_SMA).mean().values,
    }


def run_live(px, IND, params):
    """invest.py の run/trade_sleeve を日足で忠実再現(ロング/ショート両対応)。
    params: sleeve_pct, top_n, keep_n, exit_sma(None=無効), allow_short, weighting, stop_mode, rebal
    """
    cols = list(px.columns); ci = {s: k for k, s in enumerate(cols)}; P = px.values
    SMA, SMAX, MOM, VOL = IND["sma"], IND["smax"], IND["mom"], IND["vol"]; rsma = IND["rsma"]
    uni_idx = [ci[s] for s in UNIVERSE if s in ci]; regime_i = ci[REGIME_SYM]; T = len(px)

    sleeve_pct = params["sleeve_pct"]; top_n = params["top_n"]
    keep_n = max(params.get("keep_n") or top_n, top_n)
    exit_sma_on = params.get("exit_sma") is not None
    allow_short = params.get("allow_short", True)
    weighting = params.get("weighting", "equal")
    stop_mode = params.get("stop_mode", "atr"); rebal = params.get("rebal", 1)

    cash = START_EQUITY
    sh, entry, estop, ref, side = {}, {}, {}, {}, {}   # sh=符号付き株数, ref=long:高値/short:安値, side=±1
    hedged = False; curve = np.empty(T)

    def val(i):
        s = 0.0
        for c, q in sh.items():
            v = P[i, c]
            if v == v: s += q * v
        return s

    def equity(i):
        return cash + val(i)

    def drop(c):
        for d in (sh, entry, estop, ref, side):
            d.pop(c, None)

    def close(c, i):
        nonlocal cash
        v = P[i, c]
        if v == v:
            cash += sh[c] * v          # ロング=売却で受取 / ショート=買戻しで支払(符号で自動処理)
        drop(c)

    def operate(direction, cands, i):
        nonlocal cash
        is_long = direction > 0
        keep_set = {c for c, m, v in cands[:keep_n]}
        targets = cands[:top_n]
        held = [c for c in list(sh) if side[c] == direction]

        # 1) 手仕舞い(ヒステリシス): keep圏外 or 自分の短期線(EXIT_SMA)割れ
        for c in held:
            if c not in keep_set:
                close(c, i); continue
            if exit_sma_on:
                sx = SMAX[i, c]; pr = P[i, c]
                if sx == sx and pr == pr and ((is_long and pr < sx) or (not is_long and pr > sx)):
                    close(c, i)

        # 2) 新規建て(レバ無し: 同方向総建玉 <= equity*sleeve_pct)
        held_now = {c for c in sh if side[c] == direction}
        newc = [(c, m, v) for c, m, v in targets if c not in held_now]
        if not newc:
            return
        budget = equity(i) * sleeve_pct
        deployed = sum(abs(sh[c] * P[i, c]) for c in sh
                       if side[c] == direction and P[i, c] == P[i, c])
        if weighting == "invvol":
            inv = {c: 1.0 / v for c, m, v in newc}; tot = sum(inv.values())
            w = {c: inv[c] / tot for c, m, v in newc}
        else:
            w = {c: 1.0 / len(targets) for c, m, v in newc}   # 均等(枠=top_n)
        for c, m, v in newc:
            pr = P[i, c]
            if pr != pr:
                continue
            notional = budget * w[c]
            if notional < 1 or deployed + notional > budget + 1:
                continue
            q = notional / pr; signed = q if is_long else -q
            cash -= signed * pr; sh[c] = signed; side[c] = direction
            entry[c] = pr; ref[c] = pr; estop[c] = bt_stop_pct(VOL[i, c], stop_mode)
            deployed += notional

    for i in range(T):
        # --- トレーリングストップ(毎日チェック) ---
        for c in list(sh):
            v = P[i, c]
            if v != v:
                continue
            if side[c] > 0:
                if v > ref[c]: ref[c] = v
                if v <= ref[c] * (1 - estop[c] / 100.0): close(c, i)
            else:
                if v < ref[c]: ref[c] = v
                if v >= ref[c] * (1 + estop[c] / 100.0): close(c, i)

        # --- リジーム判定(SPY 200日線 + band + ヒステリシス) ---
        if i >= REGIME_SMA:
            price, m = P[i, regime_i], rsma[i]
            if m == m:
                if not hedged and price < m * (1 - REGIME_BAND): hedged = True
                elif hedged and price > m: hedged = False
        risk_on = not hedged

        # --- リバランス(既定 rebal=1: live同様に毎営業日) ---
        if i >= SMA_DAYS and (i - SMA_DAYS) % rebal == 0:
            longs, shorts = [], []
            for c in uni_idx:
                price, sma, mom, vol = P[i, c], SMA[i, c], MOM[i, c], VOL[i, c]
                if not (sma == sma and mom == mom and price == price):
                    continue
                vv = vol if (vol == vol and vol > 0) else 1e-6
                if price > sma and mom > 0:
                    longs.append((c, mom, vv))
                elif price < sma and mom < 0:
                    shorts.append((c, mom, vv))
            longs.sort(key=lambda x: x[1], reverse=True)   # 強い順
            shorts.sort(key=lambda x: x[1])                # 弱い順

            if risk_on:
                for c in [c for c in list(sh) if side[c] < 0]:
                    close(c, i)                            # ショートを畳む
                operate(+1, longs, i)
            elif allow_short and shorts:
                for c in [c for c in list(sh) if side[c] > 0]:
                    close(c, i)                            # ロングを畳む
                operate(-1, shorts, i)
            else:
                for c in list(sh):
                    close(c, i)                            # 現金退避

        curve[i] = equity(i)
    return pd.Series(curve, index=px.index).iloc[SMA_DAYS:]


def benchmark(px):
    c = px[BENCH].ffill().iloc[SMA_DAYS:]
    return START_EQUITY * c / c.iloc[0]


def stats(curve):
    curve = curve.dropna(); ret = curve.pct_change().dropna()
    yrs = (curve.index[-1] - curve.index[0]).days / 365.25
    cagr = (curve.iloc[-1] / curve.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 and curve.iloc[0] > 0 else 0.0
    vol = ret.std() * np.sqrt(252)
    sharpe = ret.mean() * 252 / (ret.std() * np.sqrt(252)) if ret.std() > 0 else 0.0
    mdd = (curve / curve.cummax() - 1).min()
    return cagr, vol, sharpe, mdd, curve.iloc[-1]


def tail_years(curve, yrs):
    cutoff = curve.index[-1] - pd.Timedelta(days=int(365.25 * yrs))
    return curve[curve.index >= cutoff]


def print_table(title, results):
    print(f"\n================= {title} =================")
    print("%-26s %12s %8s %9s %8s %8s" % ("戦略", "最終額", "CAGR", "年率ボラ", "Sharpe", "最大DD"))
    for name, c in results.items():
        c = c.dropna()
        if len(c) < 2:
            print("%-26s %12s" % (name, "データ不足")); continue
        cg, vol, sh, mdd, fin = stats(c)
        print("%-26s %12s %7.1f%% %8.1f%% %8.2f %7.1f%%" %
              (name, format(int(fin), ","), cg * 100, vol * 100, sh, mdd * 100))
    print("=" * 82)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2018-01-01"); ap.add_argument("--end", default=None)
    ap.add_argument("--rebal", type=int, default=1); ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    tickers = sorted(set(UNIVERSE + [BENCH, REGIME_SYM, SAFE]))
    end = a.end or pd.Timestamp.today().strftime("%Y-%m-%d")
    if a.selftest:
        print("[selftest] 合成データでエンジン検証(数値に意味なし)…")
        px = synth_prices(tickers, "2016-01-01", "2024-01-01")
    else:
        print(f"データ取得中: {len(tickers)}銘柄 {a.start}〜{end} …")
        px = load_prices(tickers, a.start, end)
        print(f"取得: {px.shape[0]}営業日 × {px.shape[1]}銘柄")
    IND = indicators(px)

    old = dict(sleeve_pct=0.97, top_n=TOP_N, keep_n=TOP_N, exit_sma=None,
               allow_short=True, weighting=WEIGHTING, stop_mode=STOP_MODE, rebal=a.rebal)
    new = dict(sleeve_pct=SLEEVE_PCT, top_n=TOP_N, keep_n=KEEP_N, exit_sma=EXIT_SMA,
               allow_short=True, weighting=WEIGHTING, stop_mode=STOP_MODE, rebal=a.rebal)
    new_long = dict(new, allow_short=False)

    results = {
        "(1) 指数のみ VOO": benchmark(px),
        "(2) 旧設定(負けてた本番)": run_live(px, IND, old),
        "(3) 新設定 ①②③": run_live(px, IND, new),
        "(4) 新設定・ロングのみ": run_live(px, IND, new_long),
    }
    print_table("フル期間", results)
    recent = {k: tail_years(v, 2) for k, v in results.items()}
    print_table("直近2年", recent)


if __name__ == "__main__":
    main()
