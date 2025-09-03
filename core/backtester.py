import datetime
import ccxt  # type: ignore

def run_backtest(pairs, start_date=None, end_date=None):
    """Run a simple backtest for the provided trading pairs."""
    print("[BACKTEST] Starting backtest simulation...")
    results = {}

    for pair in pairs:
        symbol = pair['symbol']
        exchange_name = pair['exchange']
        amount = pair['amount']
        buy_pct = pair['buy_percentage'] / 100
        sell_pct = pair['sell_percentage'] / 100
        timeframe = pair.get('timeframe', '1d')  # Default to 1d if not specified
        print(f"[SIM] Running backtest for {symbol} on {exchange_name}...")

        exchange_class = getattr(ccxt, exchange_name)
        exchange = exchange_class({
            'enableRateLimit': True,
        })

        # Convert provided dates to timestamps
        since = None
        until = None
        if start_date:
            since = exchange.parse8601(f"{start_date}T00:00:00Z")
        if end_date:
            until = exchange.parse8601(f"{end_date}T00:00:00Z")
        if since is None:
            since = exchange.parse8601('2023-01-01T00:00:00Z')

        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since)
            if until is not None:
                ohlcv = [c for c in ohlcv if c[0] <= until]
        except Exception as e:
            print(f"  [ERROR] Could not fetch OHLCV data for {symbol} on {exchange_name}: {e}")
            continue

        balance = amount
        position = 0
        buy_price = 0
        profit = 0
        trade_log = []

        for candle in ohlcv:
            timestamp, open_price, high, low, close_price, volume = candle
            price = close_price
            date = datetime.datetime.utcfromtimestamp(timestamp / 1000).strftime('%Y-%m-%d')

            print(f"  [PRICE] {symbol} on {date} = {price}")

            if position == 0 and balance >= amount:
                buy_price = price
                position = balance / price
                balance = 0
                trade_log.append(f"[BUY] Bought at {buy_price:.2f} -> {position:.6f} units")
                print(f"  [BUY] Bought at {buy_price:.2f} -> {position:.6f} units")

            elif position > 0 and price >= buy_price * (1 + sell_pct):
                sell_price = price
                proceeds = position * sell_price
                profit += proceeds - amount
                balance = proceeds
                position = 0
                trade_log.append(f"[SELL] Sold at {sell_price:.2f} -> Profit: {proceeds - amount:.2f}")
                print(f"  [SELL] Sold at {sell_price:.2f} -> Profit: {proceeds - amount:.2f}")

        results[symbol] = {
            'net_profit': profit,
            'trade_log': trade_log
        }
        print(f"[RESULT] {symbol}: Net Profit = {profit:.2f} USDC\n")

    print("[BACKTEST] Complete.")
    return results

def optimize_strategy(pair, buy_range, sell_range, start_date=None, end_date=None):
    symbol = pair['symbol']
    exchange_name = pair['exchange']
    amount = pair['amount']
    timeframe = pair.get('timeframe', '1d')

    print(f"[OPTIMIZER] Testing {symbol} on {exchange_name}...")

    exchange_class = getattr(ccxt, exchange_name)
    exchange = exchange_class({
        'enableRateLimit': True,
    })

    since = None
    until = None
    if start_date:
        since = exchange.parse8601(f"{start_date}T00:00:00Z")
    if end_date:
        until = exchange.parse8601(f"{end_date}T00:00:00Z")
    if since is None:
        since = exchange.parse8601('2023-01-01T00:00:00Z')

    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since)
        if until is not None:
            ohlcv = [c for c in ohlcv if c[0] <= until]
    except Exception as e:
        print(f"  [ERROR] Failed to fetch data for optimizer: {e}")
        return

    best_combo = None
    best_profit = -float('inf')

    for buy_pct in buy_range:
        for sell_pct in sell_range:
            balance = amount
            position = 0
            buy_price = 0
            profit = 0

            for candle in ohlcv:
                _, _, _, _, close_price, _ = candle
                price = close_price

                if position == 0 and balance >= amount:
                    buy_price = price
                    position = balance / price
                    balance = 0

                elif position > 0 and price >= buy_price * (1 + sell_pct / 100):
                    proceeds = position * price
                    profit += proceeds - amount
                    balance = proceeds
                    position = 0

            if profit > best_profit:
                best_profit = profit
                best_combo = (buy_pct, sell_pct)

    print(f"[OPTIMIZER RESULT] {symbol} best combo: Buy {best_combo[0]}%, Sell {best_combo[1]}% -> Profit {best_profit:.2f} USDC")  # type: ignore
    return best_combo
