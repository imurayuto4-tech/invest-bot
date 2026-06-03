import sys
from datetime import datetime, timedelta
import config
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (MarketOrderRequest, StopOrderRequest,
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


def cancel_stops(t, sym):
    """板に残っている sym の売りストップ注文を取り消す(#4。入替/損切り前に呼ぶ)。"""
    try:
        for od in t.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN)):
            if od.symbol == sym and "sell" in str(od.side).lower():
                t.cancel_order_by_id(od.id)
    except Exception as e:
        print(f"  ストップ取消失敗 {sym}: {e}")


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


# ===================== コア(#8対応:通常=指数 / 退避=SGOV) =====================
def core(t, risk_on):
    print("=== インデックス・コア ===")
    safe = getattr(config, "SAFE_SYMBOL", "SGOV")
    acct = t.get_account()
    equity = float(acct.equity)
    cash = float(acct.cash)
    budget = equity * (1 - config.SLEEVE_PCT - RESERVE)
    pos = {p.symbol: p for p in t.get_all_positions()}

    if risk_on:
        targets = list(config.CORE_SYMBOLS)
        unwanted = [safe]
        print("  リジーム: 通常(指数を保有)")
    else:
        targets = [safe]
        unwanted = list(config.CORE_SYMBOLS)
        print(f"  リジーム: ★退避★ コアを {safe} に避難")

    for s in unwanted:
        if s in pos and float(pos[s].market_value) > 1:
            o = MarketOrderRequest(symbol=s, qty=pos[s].qty,
                                   side=OrderSide.SELL, time_in_force=TimeInForce.DAY)
            try:
                t.submit_order(o); print(f"  売却 {s} {pos[s].qty}株")
                cash += float(pos[s].market_value)
            except Exception as e:
                print(f"  売り失敗 {s}: {e}")

    cur_val = sum(float(pos[s].market_value) for s in targets if s in pos)
    deficit = budget - cur_val
    spendable = max(0.0, cash - equity * RESERVE)
    spend = min(deficit, spendable)
    print(f"  目標${budget:,.0f} / 現在${cur_val:,.0f} / 現金${cash:,.0f}")
    if spend < 1:
        print("  買い増しなし(目標達成か現金不足)。")
        return
    per = spend / len(targets)
    for s in targets:
        o = MarketOrderRequest(symbol=s, notional=round(per, 2),
                               side=OrderSide.BUY, time_in_force=TimeInForce.DAY)
        try:
            t.submit_order(o); print(f"  {s}: ${per:,.0f} 買付")
        except Exception as e:
            print(f"  {s}: 失敗 {e}")


# ===================== 能動枠(#6 逆ボラ + #4 ストップ/ボラ連動幅) =====================
def rank_universe(dc):
    md = config.MOMENTUM_DAYS
    vd = getattr(config, "VOL_DAYS", 20)
    df = all_bars(dc, config.UNIVERSE, 365)
    scored = []
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
        if price > sma200 and mom > 0:
            scored.append((sym, mom, price, vol))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


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


def momentum(t, dc):
    print("=== モメンタム・スキャン ===")
    safe = getattr(config, "SAFE_SYMBOL", "SGOV")
    use_stops = getattr(config, "USE_STOP_ORDERS", False)
    acct = t.get_account()
    equity = float(acct.equity)
    cash_left = float(acct.cash) - equity * RESERVE
    top_n = config.TOP_N
    pos = {p.symbol: p for p in t.get_all_positions()
           if p.symbol not in config.CORE_SYMBOLS and p.symbol != safe}
    ranked = rank_universe(dc)
    vol_map = {s: v for s, m, p, v in ranked}
    top = ranked[:top_n]
    targets = [s for s, m, p, v in top]
    prices = {s: p for s, m, p, v in top}
    top_vol = {s: v for s, m, p, v in top}
    weights = sleeve_weights(top)
    sleeve_budget = equity * config.SLEEVE_PCT
    target_notional = {s: sleeve_budget * weights[s] for s in targets}
    print(f"  重み付け: {getattr(config, 'WEIGHTING', 'equal')} / ストップ: "
          f"{getattr(config, 'STOP_MODE', 'fixed')} / 注文化: {use_stops}")
    print("  旬の上位:", ", ".join(f"{s}(+{m:.0f}%)" for s, m, p, v in top) or "該当なし")
    if targets:
        print("  配分目標:", ", ".join(f"{s} ${target_notional[s]:,.0f}" for s in targets))

    # 入替/損切り(#4: 板のストップを取り消してから売る。閾値はボラ連動)
    for sym, p in pos.items():
        gain = float(p.unrealized_plpc) * 100
        thr = stop_pct(vol_map[sym]) if sym in vol_map else config.STOP_LOSS_PCT
        if sym not in targets or gain <= -thr:
            why = "損切り" if gain <= -thr else "入替売り"
            if use_stops:
                cancel_stops(t, sym)
            o = MarketOrderRequest(symbol=sym, qty=p.qty, side=OrderSide.SELL,
                                   time_in_force=TimeInForce.DAY)
            try:
                t.submit_order(o); print(f"  → {why} {sym} {p.qty}株 ({gain:+.1f}%, 損切り{thr:.0f}%)")
                cash_left += float(p.market_value)
            except Exception as e:
                print(f"  売り失敗 {sym}: {e}")

    # 新規買い
    held = set(pos.keys())
    for sym in targets:
        if sym in held:
            continue
        notional = target_notional[sym]
        if notional < 1:
            continue
        sp = stop_pct(top_vol[sym])
        if use_stops:
            # #4: 整数株で買い、建値-損切り幅(ボラ連動)にGTCストップを板へ
            price = prices[sym]
            qty = int(notional // price)
            if qty < 1:
                print(f"  {sym}: 1株に満たず見送り(目標${notional:,.0f} < 株価${price:,.0f})")
                continue
            cost = qty * price
            if cash_left < cost:
                print(f"  {sym}: 現金不足のため見送り")
                continue
            try:
                t.submit_order(MarketOrderRequest(symbol=sym, qty=qty, side=OrderSide.BUY,
                                                  time_in_force=TimeInForce.DAY))
                stop_px = round(price * (1 - sp / 100.0), 2)
                t.submit_order(StopOrderRequest(symbol=sym, qty=qty, side=OrderSide.SELL,
                                                time_in_force=TimeInForce.GTC, stop_price=stop_px))
                print(f"  → 買い {sym} {qty}株 (${cost:,.0f}) + ストップ ${stop_px} (-{sp:.0f}%)")
                cash_left -= cost
            except Exception as e:
                print(f"  買い失敗 {sym}: {e}")
        else:
            if cash_left < notional:
                print(f"  {sym}: 現金不足のため見送り")
                continue
            try:
                t.submit_order(MarketOrderRequest(symbol=sym, notional=round(notional, 2),
                                                  side=OrderSide.BUY, time_in_force=TimeInForce.DAY))
                print(f"  → 買い {sym} ${notional:,.0f}"); cash_left -= notional
            except Exception as e:
                print(f"  買い失敗 {sym}: {e}")


def run(t, dc):
    if not market_open(t):
        print("市場は閉まっています。何もしません。")
        return
    safe = getattr(config, "SAFE_SYMBOL", "SGOV")
    held = {p.symbol for p in t.get_all_positions()}
    risk_on = market_risk_on(dc, safe in held)
    core(t, risk_on)
    momentum(t, dc)


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
