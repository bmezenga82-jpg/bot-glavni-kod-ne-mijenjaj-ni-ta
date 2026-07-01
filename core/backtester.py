import datetime
from collections import defaultdict
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


def _simulate_grid(ohlcv, amount, buy_pct, sell_pct, fee_rate=FEE_RATE, total_capital=None, profit_mode='usdc'):
    """
    Simulate the bot's cyclic grid strategy against historical OHLCV data.

    profit_mode='usdc'  : prodaje sve, profit u USDC.
    profit_mode='crypto': prodaje samo toliko da pokrije USDC ulog, ostatak ostaje kao crypto.
                          Prati crypto_profit_qty i usdc_equivalent (usporedba s USDC modom).
    """
    balance = total_capital if total_capital is not None else amount
    starting_capital = balance

    sell_orders = []  # [{'price': float, 'qty': float, 'cost': float}]
    buy_order = None  # {'price': float, 'qty': float}
    net_profit = 0.0
    trade_count = 0
    trade_log = []
    crypto_profit_qty = 0.0  # akumulirani crypto profit (samo crypto mod)
    usdc_equivalent = 0.0    # što bi profit bio u USDC modu (za usporedbu)
    monthly = defaultdict(lambda: {'profit': 0.0, 'trades': 0})

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
            total_deployed = sum(s['cost'] for s in sell_orders)
            can_buy = balance >= amount and (total_deployed + amount) <= starting_capital
            if can_buy:
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
                # Capital limit reached — wait for sells before buying more
                buy_order = None

        # Check sell order fills using candle high
        filled = [s for s in sell_orders if high >= s['price']]
        for s in filled:
            full_proceeds = s['qty'] * s['price'] * (1 - fee_rate)
            trade_usdc_profit = full_proceeds - s['cost']  # profit ovog trejda u USDC modu
            usdc_equivalent += trade_usdc_profit

            if profit_mode == 'crypto':
                sell_qty = s['cost'] / (s['price'] * (1 - fee_rate))
                sell_qty = min(sell_qty, s['qty'])
                retained = s['qty'] - sell_qty
                proceeds = sell_qty * s['price'] * (1 - fee_rate)  # ≈ s['cost']
                profit = proceeds - s['cost']  # ≈ 0
                crypto_profit_qty += retained
                trade_log.append(
                    f'[{date}] SELL (crypto) {sell_qty:.5f} @ {s["price"]:.4f} | Zadržano: {retained:.6f} crypto | Balance: {balance + proceeds:.4f}'
                )
            else:
                proceeds = full_proceeds
                profit = trade_usdc_profit
                trade_log.append(
                    f'[{date}] SELL        {s["qty"]:.5f} @ {s["price"]:.4f} | Profit: {profit:+.4f} | Balance: {balance + proceeds:.4f}'
                )

            net_profit += profit
            balance += proceeds
            trade_count += 1
            sell_orders.remove(s)
            month = date[:7]
            monthly[month]['profit'] += trade_usdc_profit if profit_mode == 'crypto' else profit
            monthly[month]['trades'] += 1

        if filled:
            # Cancel current buy order after any sell fills (matches main.py behaviour)
            buy_order = None
            if sell_orders:
                # More sell orders still open — place new buy sell_pct% below this sell (mirrors main.py)
                lowest_filled_sell = min(s['price'] for s in filled)
                new_buy_price = lowest_filled_sell * (1 - sell_pct / 100)
                total_deployed = sum(s['cost'] for s in sell_orders)
                if balance >= amount and (total_deployed + amount) <= starting_capital:
                    buy_order = {'price': new_buy_price, 'qty': amount / new_buy_price}
                    trade_log.append(
                        f'[{date}] NEW BUY ORD @ {new_buy_price:.4f} (remaining lots: {len(sell_orders)})'
                    )
            # else: all sells filled — next candle starts a fresh cycle

    # Unrealized P&L on open positions at the last candle's close price
    last_close = ohlcv[-1][4] if ohlcv else 0.0
    unrealized_pnl = 0.0
    total_invested_open = 0.0
    total_qty_open = 0.0
    for s in sell_orders:
        current_value = s['qty'] * last_close * (1 - fee_rate)
        unrealized_pnl += current_value - s['cost']
        total_invested_open += s['cost']
        total_qty_open += s['qty']
    avg_buy_price = round(total_invested_open / total_qty_open, 6) if total_qty_open > 0 else 0.0
    breakeven_pct = round((avg_buy_price / last_close - 1) * 100, 2) if (last_close > 0 and avg_buy_price > 0) else 0.0

    crypto_value_usdc = round(crypto_profit_qty * last_close * (1 - fee_rate), 4) if profit_mode == 'crypto' else 0.0

    total_pnl = net_profit + unrealized_pnl
    roi_pct = round(net_profit / starting_capital * 100, 2) if starting_capital > 0 else 0.0
    total_roi_pct = round(total_pnl / starting_capital * 100, 2) if starting_capital > 0 else 0.0

    return {
        'profit_mode': profit_mode,
        'net_profit': round(net_profit, 4),
        'roi_pct': roi_pct,
        'unrealized_pnl': round(unrealized_pnl, 4),
        'total_pnl': round(total_pnl, 4),
        'total_roi_pct': total_roi_pct,
        'open_positions': len(sell_orders),
        'total_invested_open': round(total_invested_open, 4),
        'total_qty_open': round(total_qty_open, 8),
        'avg_buy_price': avg_buy_price,
        'breakeven_pct': breakeven_pct,
        'last_price': round(last_close, 6),
        'trade_count': trade_count,
        'total_capital': starting_capital,
        'crypto_profit_qty': round(crypto_profit_qty, 8),
        'crypto_value_usdc': crypto_value_usdc,
        'usdc_equivalent': round(usdc_equivalent, 4),
        'monthly_breakdown': dict(sorted(monthly.items())),
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

        profit_mode = pair.get('profit_mode', 'usdc')
        result = _simulate_grid(ohlcv, amount, buy_pct, sell_pct, total_capital=total_capital, profit_mode=profit_mode)
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


def _amount_for_coverage(total_capital: float, buy_pct: float, target_coverage_pct: float) -> float:
    """
    Izračunaj iznos po trejdu koji postiže target_coverage_pct pokrivenosti pada.

    coverage = 1 - (1 - buy_pct/100)^n  →  n = log(1-coverage) / log(1-buy_pct/100)
    amount = total_capital / (n + 1)
    """
    import math
    step = 1 - buy_pct / 100
    if step <= 0 or step >= 1 or target_coverage_pct <= 0:
        return total_capital
    target_coverage_pct = min(target_coverage_pct, 99.0)
    n = math.ceil(math.log(1 - target_coverage_pct / 100) / math.log(step))
    n = max(1, n)
    return max(round(total_capital / (n + 1), 2), 1.0)


def optimize_strategy(pair, buy_range, sell_range, start_date=None, end_date=None, top_n=5,
                      normalize_amount=False, target_coverage_pct=None, consistent=False):
    """
    Test all buy/sell % combinations and return the top_n by realized profit.

    normalize_amount=True: stari način — skalira amount proporcionalno buy%.
    target_coverage_pct (float, npr. 63.0): novi način — za svaki buy% izračunava
        amount koji postiže tu pokrivenost pada uz dani total_capital.
        Npr. 10000 USDC, 63% pokrivenost → 1% buy daje ~100 USDC, 2% buy daje ~196 USDC.
        Sve kombinacije pokrivaju isti pad, pa je usporedba profita poštena.
    """
    symbol = pair['symbol']
    exchange_name = pair['exchange']
    base_amount = pair['amount']
    ref_buy_pct = pair.get('buy_pct_ref', 1.0)
    timeframe = pair.get('timeframe', '1h')
    total_capital = pair.get('total_capital', base_amount)

    print(f"[OPTIMIZER] {symbol} on {exchange_name} — testing {len(buy_range) * len(sell_range)} combinations...")
    if target_coverage_pct:
        print(f"[OPTIMIZER] Način: fiksirana pokrivenost pada {target_coverage_pct}% | Kapital: {total_capital}")

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
        if target_coverage_pct:
            # Novi način: amount koji postiže fiksiranu pokrivenost pada
            amount = _amount_for_coverage(total_capital, abs(buy_pct), target_coverage_pct)
        elif normalize_amount:
            # Stari način: proporcionalno skaliranje
            amount = round(base_amount * abs(buy_pct) / ref_buy_pct, 2)
        else:
            amount = base_amount
        amount = max(amount, 1.0)

        # Stvarna pokrivenost za ovaj buy% i amount
        import math
        step = 1 - abs(buy_pct) / 100
        num_levels = max(1, int(total_capital / amount))
        actual_coverage = round((1 - step ** (num_levels - 1)) * 100, 1) if num_levels > 1 else 0.0

        for sell_pct in sell_range:
            r = _simulate_grid(ohlcv, amount, abs(buy_pct), abs(sell_pct), total_capital=total_capital)
            ann = None
            if period_days and r['total_roi_pct'] is not None:
                ann = round(((1 + r['total_roi_pct'] / 100) ** (365.0 / period_days) - 1) * 100, 2)
            results.append({
                'buy_pct': buy_pct,
                'sell_pct': sell_pct,
                'amount': round(amount, 2),
                'coverage_pct': actual_coverage,
                'total_pnl': r['total_pnl'],
                'net_profit': r['net_profit'],
                'unrealized_pnl': r['unrealized_pnl'],
                'total_invested_open': r['total_invested_open'],
                'trade_count': r['trade_count'],
                'open_positions': r['open_positions'],
                'roi_pct': r['total_roi_pct'],
                'annualized_roi': ann,
            })

    # U coverage načinu nema filtra po max_pozicija — amount je već izračunat za kapital
    if not target_coverage_pct:
        max_allowed_positions = int(total_capital / base_amount * 1.10)
        results = [r for r in results if r['open_positions'] <= max_allowed_positions]

    # Top po realiziranom profitu (stabilan, neovisno o smjeru tržišta)
    top_by_realized = sorted(results, key=lambda x: x['net_profit'], reverse=True)[:top_n]

    # Top po ukupnom P&L (realized + unrealized)
    top_by_pnl = sorted(results, key=lambda x: x['total_pnl'], reverse=True)[:top_n]

    # ── Konzistentno testiranje — 3 pod-perioda ──────────────────────────────
    consistent_results = None
    if consistent and len(ohlcv) >= 90:
        n = len(ohlcv)
        thirds = [ohlcv[:n//3], ohlcv[n//3:2*n//3], ohlcv[2*n//3:]]
        period_tops = []
        for part in thirds:
            if len(part) < 30:
                continue
            part_results = []
            for buy_pct in buy_range:
                if target_coverage_pct:
                    amount = _amount_for_coverage(total_capital, abs(buy_pct), target_coverage_pct)
                elif normalize_amount:
                    amount = round(base_amount * abs(buy_pct) / ref_buy_pct, 2)
                else:
                    amount = base_amount
                amount = max(amount, 1.0)
                for sell_pct in sell_range:
                    r = _simulate_grid(part, amount, abs(buy_pct), abs(sell_pct), total_capital=total_capital)
                    part_results.append({'buy_pct': buy_pct, 'sell_pct': sell_pct,
                                         'amount': round(amount, 2), 'net_profit': r['net_profit']})
            top_keys = {(r['buy_pct'], r['sell_pct'])
                        for r in sorted(part_results, key=lambda x: x['net_profit'], reverse=True)[:top_n]}
            period_tops.append(top_keys)

        # Broji konzistentnost — koliko pod-perioda je svaka kombinacija bila u top N
        consistency_count = {}
        for pt in period_tops:
            for key in pt:
                consistency_count[key] = consistency_count.get(key, 0) + 1

        # Spoji s ukupnim rezultatima
        results_map = {(r['buy_pct'], r['sell_pct']): r for r in results}
        consistent_list = []
        for (bp, sp), cnt in consistency_count.items():
            r = results_map.get((bp, sp))
            if r:
                stars = '★' * cnt + '☆' * (len(period_tops) - cnt)
                consistent_list.append({**r, 'consistency': cnt,
                                         'consistency_label': f"{stars} {cnt}/{len(period_tops)} perioda"})
        consistent_results = sorted(consistent_list,
                                    key=lambda x: (x['consistency'], x['net_profit']), reverse=True)[:top_n * 2]

    return {
        'top_by_pnl': top_by_pnl,
        'top_by_realized': top_by_realized,
        'coverage_mode': bool(target_coverage_pct),
        'target_coverage_pct': target_coverage_pct,
        'consistent_results': consistent_results,
    }
