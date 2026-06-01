import sys
from datetime import datetime, timedelta
import config
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed


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


def core(t):
    print("=== インデックス・コア(目標90%まで) ===")
    acct = t.get_account()
    equity = float(acct.equity)
    cash = float(acct.cash)
    target = equity * (1 - config.SLEEVE_PCT)
    pos = {p.symbol: float(p.market_value) for p in t.get_all_positions()}
    core_val = sum(pos.get(s, 0.0) for s in config.CORE_SYMBOLS)
    deficit = target - core_val
    print(f"  指数 現在${core_val:,.0f} / 目標${target:,.0f} / 現金${cash:,.0f}")
    if deficit < 50:
        print("  目標達成済み。買い増しなし。")
        return
    spend = min(deficit, cash * 0.95)
    per = spend / len(config.CORE_SYMBOLS)
    if per < 1:
        print("  現金が不足。今回は見送り。")
        return
    for s in config.CORE_SYMBOLS:
        o = MarketOrderRequest(symbol=s, notional=round(per, 2),
                               side=OrderSide.BUY, time_in_force=TimeInForce.DAY)
        try:
            t.submit_order(o); print(f"  {s}: ${per:,.0f} 買付")
        except Exception as e:
            print(f"  {s}: 失敗 {e}")


def rank_universe(dc):
    md = config.MOMENTUM_DAYS
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
        if price > sma200 and mom > 0:
            scored.append((sym, mom, price))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def momentum(t, dc):
    print("=== モメンタム・スキャン(10%) ===")
    equity = float(t.get_account().equity)
    top_n = config.TOP_N
    per = equity * config.SLEEVE_PCT / top_n
    pos = {p.symbol: p for p in t.get_all_positions()
           if p.symbol not in config.CORE_SYMBOLS}
    ranked = rank_universe(dc)
    targets = [s for s, m, p in ranked[:top_n]]
    print("  旬の上位:", ", ".join(f"{s}(+{m:.0f}%)" for s, m, p in ranked[:top_n]) or "該当なし")
    for sym, p in pos.items():
        gain = float(p.unrealized_plpc) * 100
        if sym not in targets or gain <= -config.STOP_LOSS_PCT:
            why = "損切り" if gain <= -config.STOP_LOSS_PCT else "入替売り"
            o = MarketOrderRequest(symbol=sym, qty=p.qty, side=OrderSide.SELL,
                                   time_in_force=TimeInForce.DAY)
            try:
                t.submit_order(o); print(f"  → {why} {sym} {p.qty}株 ({gain:+.1f}%)")
            except Exception as e:
                print(f"  売り失敗 {sym}: {e}")
    held = set(pos.keys())
    for sym in targets:
        if sym not in held:
            o = MarketOrderRequest(symbol=sym, notional=round(per, 2),
                                   side=OrderSide.BUY, time_in_force=TimeInForce.DAY)
            try:
                t.submit_order(o); print(f"  → 買い {sym} ${per:.0f}")
            except Exception as e:
                print(f"  買い失敗 {sym}: {e}")


def run(t, dc):
    if not market_open(t):
        print("市場は閉まっています。何もしません。")
        return
    core(t)
    momentum(t, dc)


def status(t):
    a = t.get_account()
    print(f"評価額 ${float(a.equity):,.2f} / 現金 ${float(a.cash):,.2f}")
    for p in t.get_all_positions():
        print(f"  {p.symbol:5s} {p.qty}株 {float(p.unrealized_plpc)*100:+.1f}%")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd in ("trade", "dca", "run"):
        t, dc = clients(); run(t, dc)
    elif cmd == "status":
        t, _ = clients(); status(t)
    else:
        print("使い方: python invest.py [run | status]")


if __name__ == "__main__":
    main()
