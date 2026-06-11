import sys
from datetime import datetime, timedelta
import config
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (MarketOrderRequest, TrailingStopOrderRequest,
                                      GetOrdersRequest)
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

RESERVE = 0.01  # 約1%だけ余白(借金=レバレッジを絶対にしないため)


def clients():
    if not config.API_KEY or not config.SECRET_KEY:
        sys.exit("APIキーが設定されていません(GitHub Secretsを確認)。")
    print("モード:", "ペーパー(仮想)" if config.PAPER else "★ライブ(本物)★")
    return (TradingClient(config.API_KEY, config.SECRET_KEY, paper=config.PAPER),
            StockHistoricalDataClient(config.API_KEY, config.SECRET_KEY))


def market_open(t):
    try:
        return t.get_clock().is_open
    except Exception:
        return False


def all_bars(dc, symbols, days):
    end = datetime.now() - timedelta(days=1)
    start = end - timedelta(days=days)
    req = StockBarsRequest(symbol_or_symbols=symbols, timeframe=TimeFrame.Day,
                           start=start, end=end, feed=DataFeed.IEX)
    return dc.get_stock_bars(req).df


def stop_pct(vol_daily):
    """損切り幅(%)。fixed=一律 STOP_LOSS_PCT / atr=ボラ連動(下限・上限でクランプ)。"""
    if getattr(config, "STOP_MODE", "fixed") == "atr" and vol_daily and vol_daily > 0:
        p = getattr(config, "STOP_K", 4.0) * float(vol_daily) * 100.0
        lo = getattr(config, "STOP_MIN_PCT", 5.0)
        hi = getattr(config, "STOP_MAX_PCT", 18.0)
        return min(max(p, lo), hi)
    return config.STOP_LOSS_PCT


def cancel_open_orders(t, sym):
    """sym に紐づく未約定注文(トレーリングストップ等)を全部取り消す。
    ポジションを手仕舞う/入れ替える前に呼ぶ(売り・買いどちらの保護注文も対象)。"""
    try:
        for od in t.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN)):
            if od.symbol == sym:
                t.cancel_order_by_id(od.id)
    except Exception as e:
        print(f"  注文取消失敗 {sym}: {e}")


# ===================== #8 暴落避難(リジーム判定) =====================
def market_risk_on(dc, hedged_now):
    if not getattr(config, "CRASH_HEDGE", False):
        return True
    sym = getattr(config, "REGIME_SYMBOL", "SPY")
    n = getattr(config, "REGIME_SMA", 200)
    band = getattr(config, "REGIME_BAND", 0.0)
    try:
        c = all_bars(dc, [sym], n + 80).loc[sym]["close"].reset_index(drop=True)
    except Exception:
        return True                       # データ取得失敗なら安全側=通常運用のまま
    if len(c) < n:
        return True
    price = float(c.iloc[-1])
    sma = float(c.tail(n).mean())
    if hedged_now:
        return price > sma                # 復帰は線をしっかり上抜けたら
    return price >= sma * (1 - band)      # 退避は線-band%を割れたら


# ===================== ポジションの手仕舞い =====================
def close_symbol(t, sym, reason=""):
    """sym の保護注文を取り消してから成行で全クローズ(ロング=売り/ショート=買い戻し)。"""
    cancel_open_orders(t, sym)
    try:
        t.close_position(sym)
        print(f"  クローズ {sym} {reason}".rstrip())
    except Exception as e:
        print(f"  クローズ失敗 {sym}: {e}")


def close_wrong_side(t, keep, safe):
    """保ちたい方向(keep='long'/'short')と逆のポジション、および退避用SGOVを畳む。"""
    for p in t.get_all_positions():
        if p.symbol in config.CORE_SYMBOLS:
            continue
        q = float(p.qty)
        wrong = (keep == "long" and q < 0) or (keep == "short" and q > 0)
        if p.symbol == safe or wrong:
            close_symbol(t, p.symbol, "(方向転換)")


# ===================== ランキング(ロング候補 / ショート候補) =====================
def rank_universe(dc):
    """ユニバースを順位付け。
    longs : 上昇トレンド(200日線超 & モメンタム+) を強い順
    shorts: 下降トレンド(200日線割れ & モメンタム-) を弱い(最も下落)順
    返り値: (longs, shorts, vol_map, price_map)。各候補は (sym, mom, price, vol)。
    """
    md = config.MOMENTUM_DAYS
    vd = getattr(config, "VOL_DAYS", 20)
    df = all_bars(dc, config.UNIVERSE, 365)
    longs, shorts, vol_map, price_map = [], [], {}, {}
    for sym in config.UNIVERSE:
        try:
            c = df.loc[sym]["close"].reset_index(drop=True)
        except Exception:
            continue
        if len(c) < 200:
            continue
        price = float(c.iloc[-1])
        sma200 = float(c.tail(200).mean())
        mom = (price / float(c.iloc[-md]) - 1) * 100
        daily = c.pct_change().dropna()
        vol = float(daily.tail(vd).std())
        if not (vol > 0):
            vol = float(daily.std()) if len(daily) else 1e-6
            vol = vol if vol > 0 else 1e-6
        vol_map[sym] = vol
        price_map[sym] = price
        if price > sma200 and mom > 0:
            longs.append((sym, mom, price, vol))
        elif price < sma200 and mom < 0:
            shorts.append((sym, mom, price, vol))
    longs.sort(key=lambda x: x[1], reverse=True)   # 強い順
    shorts.sort(key=lambda x: x[1])                # 弱い(最も下落)順
    return longs, shorts, vol_map, price_map


def sleeve_weights(top):
    mode = getattr(config, "WEIGHTING", "equal")
    syms = [s for s, m, p, v in top]
    if not syms:
        return {}
    if mode == "invvol":
        inv = {s: 1.0 / max(v, 1e-6) for s, m, p, v in top}
        tot = sum(inv.values())
        return {s: inv[s] / tot for s in syms}
    n = len(syms)
    return {s: 1.0 / n for s in syms}


def trade_sleeve(t, direction, cands, vol_map, price_map):
    """direction='long'/'short' の枠を「条件を満たした分だけ最大TOP_N銘柄」で運用。
    - 目標から外れた同方向ポジションは入替で手仕舞い
    - 継続保有はトレーリングストップで利を伸ばす(無ければ付け直す)
    - 新規は均等配分で建て、必ずトレーリングストップを付ける
    - レバ無し: 同方向の総建玉 <= 資産 * SLEEVE_PCT で打ち止め
    """
    is_long = direction == "long"
    label = "ロング" if is_long else "ショート"
    entry_side = OrderSide.BUY if is_long else OrderSide.SELL
    stop_side = OrderSide.SELL if is_long else OrderSide.BUY
    arrow = "買い" if is_long else "空売り"
    print(f"=== モメンタム・スキャン({label}) ===")

    acct = t.get_account()
    equity = float(acct.equity)
    sleeve_budget = equity * config.SLEEVE_PCT
    max_n = config.TOP_N

    top = cands[:max_n]
    targets = [s for s, m, p, v in top]
    weights = sleeve_weights(top)
    target_notional = {s: sleeve_budget * weights[s] for s in targets}

    # 同方向の既存ポジション(コアは対象外)
    pos = {}
    for p in t.get_all_positions():
        if p.symbol in config.CORE_SYMBOLS:
            continue
        q = float(p.qty)
        if (is_long and q > 0) or (not is_long and q < 0):
            pos[p.symbol] = p

    try:
        protected = {od.symbol for od in
                     t.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))}
    except Exception:
        protected = set()

    print(f"  候補{len(cands)}件 / 最大{max_n}銘柄 / 重み:{getattr(config, 'WEIGHTING', 'equal')}")
    print("  旬の上位: " + (", ".join(f"{s}({m:+.0f}%)" for s, m, p, v in top) or "該当なし"))

    # 1) 目標から外れた同方向ポジションは入替で手仕舞い
    for sym in list(pos.keys()):
        if sym not in targets:
            close_symbol(t, sym, "(入替)")
            pos.pop(sym, None)

    # 2) 継続保有に保護ストップが無ければ付け直す(建て直後の取りこぼし救済)
    for sym, p in pos.items():
        if sym not in protected:
            qty = abs(int(float(p.qty)))
            if qty >= 1:
                sp = stop_pct(vol_map.get(sym))
                try:
                    t.submit_order(TrailingStopOrderRequest(
                        symbol=sym, qty=qty, side=stop_side,
                        time_in_force=TimeInForce.GTC, trail_percent=round(sp, 2)))
                    print(f"  ストップ補填 {sym} {qty}株 トレール{sp:.0f}%")
                except Exception as e:
                    print(f"  ストップ補填失敗 {sym}: {e}")

    # 3) 新規建て(レバ無し: 同方向の総建玉が枠を超えない範囲で)
    deployed = sum(abs(float(p.market_value)) for p in pos.values())
    held = set(pos.keys())
    for sym in targets:
        if sym in held:
            continue
        notional = target_notional.get(sym, 0.0)
        price = price_map.get(sym, 0.0)
        if notional < 1 or price <= 0:
            continue
        if deployed + notional > sleeve_budget + 1:
            continue
        qty = int(notional // price)
        if qty < 1:
            print(f"  {sym}: 1株に満たず見送り(目標${notional:,.0f} < 株価${price:,.0f})")
            continue
        sp = stop_pct(vol_map.get(sym))
        try:
            t.submit_order(MarketOrderRequest(symbol=sym, qty=qty, side=entry_side,
                                              time_in_force=TimeInForce.DAY))
            t.submit_order(TrailingStopOrderRequest(
                symbol=sym, qty=qty, side=stop_side,
                time_in_force=TimeInForce.GTC, trail_percent=round(sp, 2)))
            print(f"  → {arrow} {sym} {qty}株 (${qty * price:,.0f}) + トレール{sp:.0f}%")
            deployed += qty * price
        except Exception as e:
            print(f"  {label}建て失敗 {sym}: {e}")


def run(t, dc):
    if not market_open(t):
        print("市場は閉まっています。何もしません。")
        return
    safe = getattr(config, "SAFE_SYMBOL", "SGOV")
    positions = t.get_all_positions()
    # 守りに入っているか(=ショート保有 or SGOV保有)でヒステリシス判定
    defensive_now = (safe in {p.symbol for p in positions}) \
        or any(float(p.qty) < 0 for p in positions)
    risk_on = market_risk_on(dc, defensive_now)
    longs, shorts, vol_map, price_map = rank_universe(dc)

    if risk_on:
        print("リジーム: 通常(攻め=強い銘柄をロング)")
        close_wrong_side(t, "long", safe)          # ショート/退避を畳む
        trade_sleeve(t, "long", longs, vol_map, price_map)
    elif getattr(config, "ALLOW_SHORT", False) and shorts:
        print("リジーム: ★下落★ 弱い銘柄をショート")
        close_wrong_side(t, "short", safe)         # ロングを畳む
        trade_sleeve(t, "short", shorts, vol_map, price_map)
    else:
        print("リジーム: ★下落★ ショート不可/候補なし → 現金で待機")
        close_wrong_side(t, "short", safe)         # ロングを畳んで現金化


def status(t):
    a = t.get_account()
    print(f"評価額 ${float(a.equity):,.2f} / 現金 ${float(a.cash):,.2f}")
    for p in t.get_all_positions():
        print(f"  {p.symbol:5s} {p.qty}株 {float(p.unrealized_plpc)*100:+.1f}%")


def log_history(t):
    """#10: 評価額・現金・保有を history.csv に追記(成績記録 + 60日自動停止の防止)。"""
    import csv, os, datetime
    a = t.get_account()
    positions = ";".join(f"{p.symbol}:{p.qty}" for p in t.get_all_positions())
    path = "history.csv"
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["date", "equity", "cash", "positions"])
        w.writerow([datetime.date.today().isoformat(),
                    f"{float(a.equity):.2f}", f"{float(a.cash):.2f}", positions])
    print(f"記録: equity ${float(a.equity):,.2f} / 保有 {positions}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd in ("trade", "dca", "run"):
        t, dc = clients(); run(t, dc)
    elif cmd == "status":
        t, _ = clients(); status(t)
    elif cmd == "log":
        t, _ = clients(); log_history(t)
    else:
        print("使い方: python invest.py [run | status | log]")


if __name__ == "__main__":
    main()
