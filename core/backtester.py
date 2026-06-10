import datetime
import ccxt  # type: ignore

FEE_RATE = 0.001  # 0.1% per trade (Binance standard)


def _fetch_ohlcv(exchange, symbol, timeframe, since, until):
    """Fetch all candles in batches to cover the full date range."""
    ohlcv = []
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=1000)
        if not batch:
            break
        ohlcv.extend(batch)
        if len(batch) < 1000:
            break
        since = batch[-1][0] + 1
    if until is not None:
        ohlcv = [c for c in ohlcv if c[0] <= until]
    return ohlcv


def _simulate_grid(ohlcv, amount, buy_pct, sell_pct, fee_rate=FEE_RATE, total_capital=None):
    """
    Simulate the bot's cyclic grid strategy against historical OHLCV data.

    Strategy (matches main.py trade_loop):
    - Market buy to start each cycle at candle open
    - Place limit sell at entry * (1 + sell_pct/100)
    - Place limit buy at entry * (1 - buy_pct/100)
    - On buy fill: add new lot, place new sell above + new buy even lower
    - On any sell fill: cancel buy, place new buy if more sells remain; else restart

    total_capital: total available USDC (defaults to amount if not provided).
    buy_pct and sell_pct are positive percentages (e.g. 2.0 = 2%).
    Uses candle high/low for fill detection.
    """
    balance = total_capital if total_capital is not None else amount
    starting_capital = balance

    sell_orders = []  # [{'price': float, 'qty': float, 'cost': float}]
    buy_order = None  # {'price': float, 'qty': float}
    net_profit = 0.0
    trade_count = 0
    trade_log = []

    for candle in ohlcv:
        _, open_p, high, low, _close, _ = candle
        date = datetime.datetime.utcfromtimestamp(candle[0] / 1000).strftime('%Y-%m-%d %H:%M')

        # Start new cycle when idle (no open sell or buy orders)
        if not sell_orders and buy_order is None:
            if balance < amount:
                trade_log.append(f'[{date}] Insufficient capital to start cycle (balance: {balance:.4f})')
                continue
            entry = open_p * (1 + fee_rate)
            qty = (amount * (1 - fee_rate)) / open_p
            balance -= amount

            sell_price = entry * (1 + sell_pct / 100)
            buy_price_next = entry * (1 - buy_pct / 100)

            sell_orders.append({'price': sell_price, 'qty': qty, 'cost': amount})
            buy_order = {'price': buy_price_next, 'qty': amount / buy_price_next}
            trade_log.append(f'[{date}] MARKET BUY  {qty:.5f} @ ~{open_p:.4f} | Sell→{sell_price:.4f} | Buy→{buy_price_next:.4f}')

        # Check limit buy fill using candle low
        if buy_order and low <= buy_order['price']:
            if balance >= amount:
                bp = buy_order['price']
                bq = buy_order['qty']
                balance -= amount
                new_sell_p = bp * (1 + sell_pct / 100)
                sell_orders.append({'price': new_sell_p, 'qty': bq, 'cost': amount})
                new_bp = bp * (1 - buy_pct / 100)
                buy_order = {'price': new_bp, 'qty': amount / new_bp}
                trade_log.append(
                    f'[{date}] LIMIT BUY   {bq:.5f} @ {bp:.4f} | Sell→{new_sell_p:.4f} | Buy→{new_bp:.4f} | Open lots: {len(sell_orders)}'
                )
            else:
                # No capital left for another grid level
                buy_order = None

        # Check sell order fills using candle high
        filled = [s for s in sell_orders if high >= s['price']]
        for s in filled:
            proceeds = s['qty'] * s['price'] * (1 - fee_rate)
            profit = proceeds - s['cost']
            net_profit += profit
            balance += proceeds
            trade_count += 1
            sell_orders.remove(s)
            trade_log.append(
                f'[{date}] SELL        {s["qty"]:.5f} @ {s["price"]:.4f} | Profit: {profit:+.4f} | Balance: {balance:.4f}'
            )

        if filled:
            # Cancel current buy order after any sell fills (matches main.py behaviour)
            buy_order = None
            if sell_orders:
                # More sell orders still open — place new buy below the lowest filled sell price
                lowest_filled_sell = min(s['price'] for s in filled)
                new_buy_price = lowest_filled_sell * (1 - buy_pct / 100)
                if balance >= amount:
                    buy_order = {'price': new_buy_price, 'qty': amount / new_buy_price}
                    trade_log.append(
                        f'[{date}] NEW BUY ORD @ {new_buy_price:.4f} (remaining lots: {len(sell_orders)})'
                    )
            # else: all sells filled — next candle starts a fresh cycle

    # Unrealized P&L on open positions at the last candle's close price
    last_close = ohlcv[-1][4] if ohlcv else 0.0
    unrealized_pnl = 0.0
    total_invested_open = 0.0
    for s in sell_orders:
        current_value = s['qty'] * last_close * (1 - fee_rate)
        unrealized_pnl += current_value - s['cost']
        total_invested_open += s['cost']

    total_pnl = net_profit + unrealized_pnl
    roi_pct = round(net_profit / starting_capital * 100, 2) if starting_capital > 0 else 0.0
    total_roi_pct = round(total_pnl / starting_capital * 100, 2) if starting_capital > 0 else 0.0

    return {
        'net_profit': round(net_profit, 4),
        'roi_pct': roi_pct,
        'unrealized_pnl': round(unrealized_pnl, 4),
        'total_pnl': round(total_pnl, 4),
        'total_roi_pct': total_roi_pct,
        'open_positions': len(sell_orders),
        'total_invested_open': round(total_invested_open, 4),
        'last_price': round(last_close, 6),
        'trade_count': trade_count,
        'total_capital': starting_capital,
        'trade_log': trade_log,
    }


def run_backtest(pairs, start_date=None, end_date=None):
    """Run grid strategy backtest for the provided trading pairs."""
    print("[BACKTEST] Starting...")
    results = {}

    for pair in pairs:
        symbol = pair['symbol']
        exchange_name = pair['exchange']
        amount = pair['amount']
        buy_pct = abs(pair['buy_percentage'])
        sell_pct = abs(pair['sell_percentage'])
        timeframe = pair.get('timeframe', '1h')
        total_capital = pair.get('total_capital', amount)

        print(f"[SIM] {symbol} | Buy: -{buy_pct}% | Sell: +{sell_pct}% | Per-trade: {amount} | Capital: {total_capital} | TF: {timeframe}")

        exchange_class = getattr(ccxt, exchange_name)
        exchange = exchange_class({'enableRateLimit': True})

        since = (
            exchange.parse8601(f"{start_date}T00:00:00Z")
            if start_date
            else exchange.parse8601('2023-01-01T00:00:00Z')
        )
        until = exchange.parse8601(f"{end_date}T23:59:59Z") if end_date else None

        try:
            ohlcv = _fetch_ohlcv(exchange, symbol, timeframe, since, until)
        except Exception as e:
            print(f"  [ERROR] {e}")
            results[symbol] = {'net_profit': 0, 'roi_pct': 0, 'trade_count': 0, 'total_capital': total_capital, 'trade_log': [f'Error fetching data: {e}']}
            continue

        if not ohlcv:
            results[symbol] = {'net_profit': 0, 'roi_pct': 0, 'trade_count': 0, 'total_capital': total_capital, 'trade_log': ['No data available for this range.']}
            continue

        result = _simulate_grid(ohlcv, amount, buy_pct, sell_pct, total_capital=total_capital)
        result['candles'] = len(ohlcv)
        result['timeframe'] = timeframe

        # Annualized ROI
        period_days = None
        if start_date and end_date:
            try:
                d1 = datetime.date.fromisoformat(start_date)
                d2 = datetime.date.fromisoformat(end_date)
                period_days = max(1, (d2 - d1).days)
            except Exception:
                pass
        result['period_days'] = period_days
        if period_days and result['total_roi_pct'] is not None:
            ann = ((1 + result['total_roi_pct'] / 100) ** (365.0 / period_days) - 1) * 100
            result['annualized_roi'] = round(ann, 2)
        else:
            result['annualized_roi'] = None

        results[symbol] = result
        print(f"  -> Net Profit: {result['net_profit']:.4f} ({result['roi_pct']}%) | Annual: {result['annualized_roi']}% | Trades: {result['trade_count']} | Candles: {len(ohlcv)}")

    print("[BACKTEST] Complete.")
    return results


def optimize_strategy(pair, buy_range, sell_range, start_date=None, end_date=None, top_n=5):
    """
    Test all buy/sell % combinations and return the top_n by total P&L
    (realized profit + unrealized P&L on open positions).
    """
    symbol = pair['symbol']
    exchange_name = pair['exchange']
    amount = pair['amount']
    timeframe = pair.get('timeframe', '1h')
    total_capital = pair.get('total_capital', amount)

    print(f"[OPTIMIZER] {symbol} on {exchange_name} — testing {len(buy_range) * len(sell_range)} combinations...")

    exchange_class = getattr(ccxt, exchange_name)
    exchange = exchange_class({'enableRateLimit': True})

    since = (
        exchange.parse8601(f"{start_date}T00:00:00Z")
        if start_date
        else exchange.parse8601('2023-01-01T00:00:00Z')
    )
    until = exchange.parse8601(f"{end_date}T23:59:59Z") if end_date else None

    try:
        ohlcv = _fetch_ohlcv(exchange, symbol, timeframe, since, until)
    except Exception as e:
        print(f"  [ERROR] {e}")
        return None

    if not ohlcv:
        return None

    period_days = None
    if start_date and end_date:
        try:
            d1 = datetime.date.fromisoformat(start_date)
            d2 = datetime.date.fromisoformat(end_date)
            period_days = max(1, (d2 - d1).days)
        except Exception:
            pass

    results = []

    for buy_pct in buy_range:
        for sell_pct in sell_range:
            r = _simulate_grid(ohlcv, amount, abs(buy_pct), abs(sell_pct), total_capital=total_capital)
            ann = None
            if period_days and r['total_roi_pct'] is not None:
                ann = round(((1 + r['total_roi_pct'] / 100) ** (365.0 / period_days) - 1) * 100, 2)
            results.append({
                'buy_pct': buy_pct,
                'sell_pct': sell_pct,
                'total_pnl': r['total_pnl'],
                'net_profit': r['net_profit'],
                'unrealized_pnl': r['unrealized_pnl'],
                'trade_count': r['trade_count'],
                'open_positions': r['open_positions'],
                'roi_pct': r['total_roi_pct'],
                'annualized_roi': ann,
            })

    # Sort by total P&L (realized + unrealized)
    results.sort(key=lambda x: x['total_pnl'], reverse=True)
    top = results[:top_n]

    for i, combo in enumerate(top, 1):
        print(
            f"  #{i}: Buy {combo['buy_pct']}% / Sell {combo['sell_pct']}% "
            f"-> Total P&L {combo['total_pnl']:+.4f} "
            f"(realized {combo['net_profit']:+.4f}, unrealized {combo['unrealized_pnl']:+.4f}) "
            f"| {combo['trade_count']} trades | {combo['open_positions']} open lots"
        )

    return top
