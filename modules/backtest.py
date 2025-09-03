from flask import request, jsonify, render_template, session
from core.backtester import run_backtest, optimize_strategy
from modules.utils import get_pairs

def backtest(config):
    if 'theme' not in session:
        session['theme'] = 'dark'
    if request.method == 'POST':
        symbol = request.form['symbol']
        exchange = request.form.get('exchange', 'binance')
        start_date = request.form['start_date']
        end_date = request.form['end_date']
        buy_percentage = float(request.form['buy_percentage'])
        sell_percentage = float(request.form['sell_percentage'])
        amount = float(request.form.get('amount', 100.0))
        pair = {
            'symbol': symbol,
            'exchange': exchange,
            'amount': amount,
            'buy_percentage': -abs(buy_percentage),  # Ensure negative
            'sell_percentage': abs(sell_percentage)  # Ensure positive
        }
        results = run_backtest([pair], start_date, end_date)
        return jsonify({'results': results})
    exchanges = ['binance', 'bybit', 'gateio', 'bitmart']
    return render_template('backtest.html', pairs=get_pairs(), exchanges=exchanges, notifications={})

def optimize():
    symbol = request.form['symbol']
    exchange = request.form.get('exchange', 'binance')
    start_date = request.form['start_date']
    end_date = request.form['end_date']
    amount = float(request.form.get('amount', 100.0))
    buy_range = [x * -0.5 for x in range(1, 11)]  # Negative buy percentages
    sell_range = [x * 0.5 for x in range(2, 21)]  # Positive sell percentages
    pair = {
        'symbol': symbol,
        'exchange': exchange,
        'amount': amount
    }
    best_combo = optimize_strategy(pair, buy_range, sell_range, start_date, end_date)
    return jsonify({'best_buy_percentage': best_combo[0], 'best_sell_percentage': best_combo[1]})
