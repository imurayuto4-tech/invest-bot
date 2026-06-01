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


def bars(dc, sym, days):
    end = datetime.now() - timedelta(days=1)
    start = end - timedelta(days=days)
    req = StockBarsRequest(symbol_or_symbols=sym, timeframe=TimeFrame.Day,
                           start=start, end=end, feed=DataFeed.IEX)
    return dc.get_stock_bars(req).df


def dca(t):
    print("=== インデックス積み立て(90%) ===")
    for sym, amt in config.DCA_PLAN.items():
        o = MarketOrderRequest(symbol=sym, notional=amt, side=OrderSide.BUY,
                               time_in_force=TimeInForce.DAY)
        try:
            t.submit_order(o); print(f"  {sym}: ${amt} 買付")
        except Exception as e:
            print(f"  {sym}: 失敗 {e}")


def trade(t, dc):
    if not market_open(t):
        print("市場は閉まっています。何もしません。")
        return
    print("=== モメンタム(10%) ===")
    equity = float(t.get_account().equity)
    per = equity * config.SLEEVE_PCT / max(len(config.SLEEVE_SYMBOLS), 1)
    pos = {p.symbol: p for p in t.get_all_positions()}
    bd = config.BREAKOUT_DAYS
    for sym in config.SLEEVE_SYMBOLS:
        df = bars(dc, sym, bd + 15)
        if df.empty or len(df) < bd + 1:
            print(f"  {sym}: データ不足"); continue
        c = df["close"].reset_index(drop=True)
        price = float(c.iloc[-1])
        prev_high = float(c.iloc[-(bd + 1):-1].max())
        held = sym in pos
        if held:
            gain = float(pos[sym].unrealized_plpc) * 100
            print(f"  {sym}: 含み{gain:+.1f}% 保有中")
            if gain >= config.TAKE_PROFIT_PCT or gain <= -config.STOP_LOSS_PCT:
                why = "利確" if gain > 0 else "損切り"
                o = MarketOrderRequest(symbol=sym, qty=pos[sym].qty,
                                       side=OrderSide.SELL, time_in_force=TimeInForce.DAY)
                try:
                    t.submit_order(o); print(f"    → {why} 売り {pos[sym].qty}株")
                except Exception as e:
                    print(f"    失敗 {e}")
        else:
            print(f"  {sym}: ${price:.2f} 直近{bd}日高値${prev_high:.2f} {'(更新!)' if price > prev_high else ''}")
            if price > prev_high:
                o = MarketOrderRequest(symbol=sym, notional=round(per, 2),
                                       side=OrderSide.BUY, time_in_force=TimeInForce.DAY)
                try:
                    t.submit_order(o); print(f"    → 買い ${per:.0f}")
                except Exception as e:
                    print(f"    失敗 {e}")


def status(t):
    a = t.get_account()
    print(f"評価額 ${float(a.equity):,.2f} / 現金 ${float(a.cash):,.2f}")
    for p in t.get_all_positions():
        print(f"  {p.symbol:5s} {p.qty}株 {float(p.unrealized_plpc)*100:+.1f}%")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "dca":
        t, _ = clients(); dca(t)
    elif cmd == "trade":
        t, dc = clients(); trade(t, dc)
    elif cmd == "status":
        t, _ = clients(); status(t)
    else:
        print("使い方: python invest.py [dca | trade | status]")


if __name__ == "__main__":
    main()
