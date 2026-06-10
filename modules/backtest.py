from flask import request, jsonify, render_template, session
from core.backtester import run_backtest, optimize_strategy
from modules.utils import get_pairs

def backtest(config):
    if 'theme' not in session:
        session['theme'] = 'dark'
    if request.method == 'POST':
        primary_symbol = request.form['symbol']
        exchange = request.form.get('exchange', 'binance')
        start_date = request.form['start_date']
        end_date = request.form['end_date']
        buy_percentage = float(request.form['buy_percentage'])
        sell_percentage = float(request.form['sell_percentage'])
        amount = float(request.form.get('amount', 100.0))
        total_capital = float(request.form.get('total_capital', amount))
        timeframe = request.form.get('timeframe', '1h')

        all_symbols = [primary_symbol]
        compare_raw = request.form.get('compare_symbols', '').strip()
        if compare_raw:
            extras = [s.strip() for s in compare_raw.split(',') if s.strip()]
            all_symbols.extend(extras)

        pairs = [
            {
                'symbol': sym,
                'exchange': exchange,
                'amount': amount,
                'total_capital': total_capital,
                'buy_percentage': -abs(buy_percentage),
                'sell_percentage': abs(sell_percentage),
                'timeframe': timeframe,
            }
            for sym in all_symbols
        ]
        results = run_backtest(pairs, start_date, end_date)
        return jsonify({'results': results})
    exchanges = ['binance', 'bybit', 'gateio', 'bitmart']
    return render_template('backtest.html', pairs=get_pairs(), exchanges=exchanges, notifications={})

def optimize():
    symbol = request.form['symbol']
    exchange = request.form.get('exchange', 'binance')
    start_date = request.form['start_date']
    end_date = request.form['end_date']
    amount = float(request.form.get('amount', 100.0))
    total_capital = float(request.form.get('total_capital', amount))
    timeframe = request.form.get('timeframe', '1h')

    # 0.2% steps from 0.2% to 3.0% — 225 combinations, ~10-20s for 2yr of 1h data
    buy_range = [-round(x * 0.2, 1) for x in range(1, 16)]   # -0.2% to -3.0%
    sell_range = [round(x * 0.2, 1) for x in range(1, 16)]   # +0.2% to +3.0%

    pair = {
        'symbol': symbol,
        'exchange': exchange,
        'amount': amount,
        'total_capital': total_capital,
        'timeframe': timeframe,
    }
    top_combos = optimize_strategy(pair, buy_range, sell_range, start_date, end_date, top_n=5)
    if not top_combos:
        return jsonify({'error': 'Could not fetch data or no results'}), 500
    return jsonify({
        'top_combos': top_combos,
        'meta': {
            'symbol': symbol,
            'exchange': exchange,
            'start_date': start_date,
            'end_date': end_date,
            'timeframe': timeframe,
            'amount': amount,
            'total_capital': total_capital,
        }
    })
