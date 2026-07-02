import uuid
import threading
import time
from flask import request, jsonify, render_template, session
from core.backtester import run_backtest, optimize_strategy
from modules.utils import get_pairs

_jobs: dict = {}  # job_id -> {status, result, error, ts}
_jobs_lock = threading.Lock()

def _cleanup_old_jobs():
    cutoff = time.time() - 3600  # starije od 1h
    with _jobs_lock:
        stale = [jid for jid, j in _jobs.items() if j.get('ts', 0) < cutoff]
        for jid in stale:
            del _jobs[jid]

def optimize_status(job_id):
    _cleanup_old_jobs()
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({'status': 'not_found'}), 404
    return jsonify({'status': job['status'], 'result': job.get('result'), 'error': job.get('error')})

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

        profit_mode = request.form.get('profit_mode', 'usdc')
        pairs = [
            {
                'symbol': sym,
                'exchange': exchange,
                'amount': amount,
                'total_capital': total_capital,
                'buy_percentage': -abs(buy_percentage),
                'sell_percentage': abs(sell_percentage),
                'timeframe': timeframe,
                'profit_mode': profit_mode,
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

    min_buy_pct  = max(0.2, min(float(request.form.get('min_buy_pct',  '0.2') or '0.2'), 10.0))
    max_buy_pct  = max(0.4, min(float(request.form.get('max_buy_pct',  '4.0') or '4.0'), 10.0))
    min_sell_pct = max(0.2, min(float(request.form.get('min_sell_pct', '0.2') or '0.2'), 15.0))
    max_sell_pct = max(0.4, min(float(request.form.get('max_sell_pct', '6.0') or '6.0'), 15.0))
    min_buy_pct  = min(min_buy_pct,  max_buy_pct)
    min_sell_pct = min(min_sell_pct, max_sell_pct)
    consistent = 'consistent' in request.form

    MAX_COMBINATIONS = 100 if consistent else 200
    step = 0.2
    buy_span  = max_buy_pct  - min_buy_pct  + step
    sell_span = max_sell_pct - min_sell_pct + step
    while True:
        n_buy  = max(1, int(buy_span  / step))
        n_sell = max(1, int(sell_span / step))
        if n_buy * n_sell <= MAX_COMBINATIONS or step >= 2.0:
            break
        step = round(step + 0.2, 2)

    buy_range  = [-round(min_buy_pct  + x * step, 2)
                  for x in range(int((max_buy_pct  - min_buy_pct)  / step) + 1)]
    sell_range = [ round(min_sell_pct + x * step, 2)
                  for x in range(int((max_sell_pct - min_sell_pct) / step) + 1)]

    buy_percentage = abs(float(request.form.get('buy_percentage', 1.0)))
    normalize_amount = 'normalize_amount' in request.form
    target_coverage_raw = request.form.get('target_coverage_pct', '').strip()
    target_coverage_pct = float(target_coverage_raw) if target_coverage_raw else None

    pair = {
        'symbol': symbol, 'exchange': exchange, 'amount': amount,
        'buy_pct_ref': buy_percentage, 'total_capital': total_capital, 'timeframe': timeframe,
    }
    meta_base = {
        'symbol': symbol, 'exchange': exchange, 'start_date': start_date, 'end_date': end_date,
        'timeframe': timeframe, 'amount': amount, 'buy_pct_ref': buy_percentage,
        'total_capital': total_capital, 'normalize_amount': normalize_amount,
        'target_coverage_pct': target_coverage_pct, 'combinations_tested': len(buy_range) * len(sell_range),
        'step_used': step, 'consistent': consistent,
    }

    job_id = uuid.uuid4().hex[:10]
    with _jobs_lock:
        _jobs[job_id] = {'status': 'running', 'result': None, 'error': None, 'ts': time.time()}

    def _run():
        try:
            opt = optimize_strategy(
                pair, buy_range, sell_range, start_date, end_date, top_n=5,
                normalize_amount=normalize_amount,
                target_coverage_pct=target_coverage_pct,
                consistent=consistent,
            )
            if not opt or not opt.get('top_by_pnl'):
                with _jobs_lock:
                    _jobs[job_id] = {'status': 'error', 'error': 'Nema podataka ili rezultata', 'ts': time.time()}
                return
            result = {
                'top_combos': opt['top_by_pnl'],
                'top_by_realized': opt['top_by_realized'],
                'meta': {**meta_base, 'coverage_mode': opt.get('coverage_mode', False),
                         'consistent_results': opt.get('consistent_results')},
            }
            with _jobs_lock:
                _jobs[job_id] = {'status': 'done', 'result': result, 'error': None, 'ts': time.time()}
        except Exception as e:
            with _jobs_lock:
                _jobs[job_id] = {'status': 'error', 'error': str(e), 'ts': time.time()}

    threading.Thread(target=_run, daemon=True, name=f'optimize-{job_id}').start()
    return jsonify({'job_id': job_id})
