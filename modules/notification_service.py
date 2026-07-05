"""
Notification service — provjerava uvjete i šalje email notifikacije.
Background thread se pokreće iz factory.py i radi check_all() svakih 5 minuta.
"""
import json
import os
import threading
import time
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

KEY_FILE = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'api_keys.json'))
_STATE_FILE = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'notification_state.json'))

# In-memory cooldown tracker — sprječava duplikate
# {key: datetime_last_sent}
_last_sent = {}

def _load_state():
    try:
        with open(_STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def _save_state(state):
    try:
        with open(_STATE_FILE, 'w') as f:
            json.dump(state, f)
    except Exception:
        pass
COOLDOWN = {
    'bot_error':           timedelta(hours=1),
    'bot_inactive':        timedelta(hours=2),
    'server_restart':      timedelta(minutes=5),
    'balance_low':         timedelta(hours=4),
    'missing_orders':      timedelta(hours=1),
    'rebalancing':         timedelta(hours=12),
    'big_profit':          timedelta(minutes=5),
    'no_cycles':           timedelta(hours=12),
    'cumulative_milestone':timedelta(hours=1),
    'daily_summary':       timedelta(hours=20),
    'weekly_summary':      timedelta(days=6),
}

def _load_config():
    try:
        with open(KEY_FILE) as f:
            keys = json.load(f)
        return keys.get('notifications', {})
    except Exception:
        return {}

def _can_send(key):
    cd = COOLDOWN.get(key, timedelta(hours=1))
    last = _last_sent.get(key)
    return last is None or datetime.utcnow() - last > cd

def _mark_sent(key):
    _last_sent[key] = datetime.utcnow()

def _send(subject, body):
    from modules.email_sender import send_email
    try:
        send_email(subject, body)
    except Exception as e:
        logger.error(f"notification send error: {e}")

def _cfg(cfg, key, sub=None, default=None):
    section = cfg.get(key, {})
    if not section.get('enabled'):
        return None
    if sub:
        return section.get(sub, default)
    return section

# ── Direktni triggeri (pozivaju se iz koda) ───────────────────────────────────

def notify_signal_change(symbol, old_signal, new_signal, buy_score, sell_score):
    """Šalje email kad se promjeni signal za praćeni coin (scanner watchlist)."""
    cfg = _load_config()
    if not cfg.get('signal_change', {}).get('enabled', True):
        return
    key = f'signal_change_{symbol}'
    cd = timedelta(hours=4)
    last = _last_sent.get(key)
    if last and datetime.utcnow() - last < cd:
        return
    _mark_sent(key)
    _send(
        f"📊 CryptoBot — Signal promijenjen: {symbol.replace('/USDT','')}",
        f"""<h3>Signal promijenjen za {symbol}</h3>
        <p><b>Stari signal:</b> {old_signal}</p>
        <p><b>Novi signal:</b> <strong>{new_signal}</strong></p>
        <p><b>BUY Score:</b> {buy_score}/100 &nbsp;|&nbsp; <b>SELL Score:</b> {sell_score}/100</p>
        <p><small>{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC</small></p>"""
    )

def notify_spot_mode_change(pair_symbol, old_mode, new_mode):
    """Šalje email kad se promjeni preporučeni profit mode za spot par."""
    cfg = _load_config()
    if not cfg.get('signal_change', {}).get('enabled', True):
        return
    key = f'spot_mode_{pair_symbol}'
    cd = timedelta(hours=8)
    last = _last_sent.get(key)
    if last and datetime.utcnow() - last < cd:
        return
    _mark_sent(key)
    mode_hr = {'usdc': 'Uzmi USDC profit', 'crypto': 'Zadrži kripto'}
    _send(
        f"🔄 CryptoBot — Profit mode promijenjen: {pair_symbol}",
        f"""<h3>Preporučeni profit mode se promijenio</h3>
        <p><b>Par:</b> {pair_symbol}</p>
        <p><b>Bio:</b> {mode_hr.get(old_mode, old_mode)}</p>
        <p><b>Sada:</b> <strong>{mode_hr.get(new_mode, new_mode)}</strong></p>
        <p><small>{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC</small></p>"""
    )


def notify_bot_error(pair_symbol, exchange, error_msg):
    cfg = _load_config()
    if not _cfg(cfg, 'bot_error'):
        return
    key = f'bot_error_{pair_symbol}_{exchange}'
    if not _can_send(key):
        return
    _mark_sent(key)
    _send(
        f"⚠️ CryptoBot — Bot stao: {pair_symbol}",
        f"""<h3>Bot stao zbog greške</h3>
        <p><b>Par:</b> {pair_symbol} | <b>Exchange:</b> {exchange}</p>
        <p><b>Greška:</b> {error_msg}</p>
        <p><small>{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC</small></p>"""
    )

def notify_server_restart():
    cfg = _load_config()
    if not _cfg(cfg, 'server_restart'):
        return
    if not _can_send('server_restart'):
        return
    _mark_sent('server_restart')
    _send(
        "🔄 CryptoBot — Server restart",
        f"""<h3>Server je restartao</h3>
        <p>CryptoBot je ponovo pokrenut.</p>
        <p><small>{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC</small></p>"""
    )

def notify_big_profit(pair_symbol, exchange, profit_usdc):
    cfg = _load_config()
    threshold = _cfg(cfg, 'big_profit', 'usdc', 10)
    if threshold is None:
        return
    if profit_usdc < float(threshold):
        return
    key = f'big_profit_{pair_symbol}'
    if not _can_send(key):
        return
    _mark_sent(key)
    _send(
        f"💰 CryptoBot — Veliki profit: {pair_symbol}",
        f"""<h3>Veliki profit na jednom ciklusu!</h3>
        <p><b>Par:</b> {pair_symbol} | <b>Exchange:</b> {exchange}</p>
        <p><b>Profit:</b> <span style="color:green;font-size:1.3em;">${profit_usdc:.2f} USDC</span></p>
        <p><small>{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC</small></p>"""
    )

def notify_cumulative_milestone(total_profit):
    cfg = _load_config()
    milestone = _cfg(cfg, 'cumulative_milestone', 'usdc', 500)
    if milestone is None:
        return
    milestone = float(milestone)
    # Provjeri je li prešao granicu — persistirano u fajlu da preživi restart
    state = _load_state()
    last_milestone = state.get('cumulative_milestone_value', 0)
    current_milestone = int(total_profit / milestone) * milestone
    if current_milestone > last_milestone and total_profit >= milestone:
        state['cumulative_milestone_value'] = current_milestone
        _save_state(state)
        _send(
            f"🏆 CryptoBot — Kumulativni profit: ${current_milestone:.0f}+",
            f"""<h3>Dostignut novi profit milestone!</h3>
            <p>Ukupni kumulativni profit je prešao <b>${current_milestone:.0f} USDC</b>!</p>
            <p><b>Trenutni ukupni profit:</b> ${total_profit:.2f} USDC</p>
            <p><small>{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC</small></p>"""
        )

# ── Background provjere ───────────────────────────────────────────────────────

def _check_bot_inactive(cfg, pairs_status):
    hours = _cfg(cfg, 'bot_inactive', 'hours', 2)
    if hours is None:
        return
    hours = float(hours)
    from core.models import ProfitLog
    from core.extensions import db
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    for pair in pairs_status:
        if not pair.get('running'):
            continue
        symbol = pair.get('symbol', '')
        exchange = pair.get('exchange', '')
        last = ProfitLog.query.filter_by(symbol=symbol, exchange=exchange)\
            .order_by(ProfitLog.timestamp.desc()).first()
        if last and last.timestamp < cutoff:
            key = f'bot_inactive_{symbol}_{exchange}'
            if _can_send(key):
                _mark_sent(key)
                _send(
                    f"⏰ CryptoBot — Bot neaktivan: {symbol}",
                    f"""<h3>Bot je neaktivan dulje od {hours:.0f}h</h3>
                    <p><b>Par:</b> {symbol} | <b>Exchange:</b> {exchange}</p>
                    <p>Zadnji ciklus: {last.timestamp.strftime('%Y-%m-%d %H:%M')} UTC</p>"""
                )

def _check_balance_low(cfg):
    section = cfg.get('balance_low', {})
    if not section.get('enabled'):
        return
    limits = section.get('limits', {})
    if not limits:
        return
    try:
        import json as _json
        from core.exchange import ExchangeConnector
        from modules.exchange_config import ExchangeConfig
        with open(KEY_FILE) as f:
            keys = _json.load(f)
    except Exception as e:
        logger.warning(f"balance check — ne mogu učitati api_keys.json: {e}")
        return

    for ex_name, limit_val in limits.items():
        try:
            limit = float(limit_val)
            if limit <= 0:
                continue
            exchange_id, params = ExchangeConfig.setup_exchange(ex_name, is_testnet=False, api_keys_override=keys)
            connector = ExchangeConnector(exchange_id=exchange_id, params=params)
            raw = connector.get_balance('USDC')
            if raw is None or raw == 'AUTH_ERROR':
                continue
            balance = float(raw)
            if balance < limit:
                key = f'balance_low_{ex_name}'
                if _can_send(key):
                    _mark_sent(key)
                    _send(
                        f"💸 CryptoBot — Nizak saldo: {ex_name}",
                        f"""<h3>Saldo ispod limita</h3>
                        <p><b>Exchange:</b> {ex_name}</p>
                        <p><b>Trenutni saldo:</b> ${balance:.2f} USDC</p>
                        <p><b>Minimalni limit:</b> ${limit:.2f} USDC</p>"""
                    )
        except Exception as e:
            logger.warning(f"balance check greška za {ex_name}: {e}")

def _check_missing_orders(cfg):
    minutes = _cfg(cfg, 'missing_orders', 'minutes', 10)
    if minutes is None:
        return
    minutes = float(minutes)
    try:
        from core.models import TradingPair, Order
        from modules.bot_control import bot_manager
        for pair_id, status in bot_manager.get_status().items():
            if not status.get('running'):
                continue
            pair = TradingPair.query.get(pair_id)
            if not pair:
                continue
            open_orders = Order.query.filter_by(
                symbol=pair.symbol, exchange=pair.exchange, status='open'
            ).all()
            sides = {o.side for o in open_orders}
            if 'buy' in sides and 'sell' in sides:
                continue
            # Provjeri je li par tek startao (manji od X minuta)
            oldest = min((o.created_at for o in open_orders), default=None)
            if oldest and (datetime.utcnow() - oldest).total_seconds() < minutes * 60:
                continue
            key = f'missing_orders_{pair.symbol}_{pair.exchange}'
            if _can_send(key):
                _mark_sent(key)
                missing = 'sell' if 'sell' not in sides else 'buy'
                _send(
                    f"🔍 CryptoBot — Nedostaje {missing} order: {pair.symbol} ({pair.exchange})",
                    f"""<h3>Nedostaju orderi na {pair.exchange}</h3>
                    <p><b>Par:</b> {pair.symbol}</p>
                    <p><b>Exchange:</b> {pair.exchange}</p>
                    <p>Nedostaje <b>{missing}</b> order dulje od {minutes:.0f} minuta.</p>
                    <p><small>{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC</small></p>"""
                )
    except Exception as e:
        logger.warning(f"missing orders check error: {e}")

def _check_no_cycles(cfg):
    days = _cfg(cfg, 'no_cycles', 'days', 3)
    if days is None:
        return
    days = float(days)
    try:
        from core.models import TradingPair, ProfitLog
        from modules.bot_control import bot_manager
        cutoff = datetime.utcnow() - timedelta(days=days)
        for pair_id, status in bot_manager.get_status().items():
            if not status.get('running'):
                continue
            pair = TradingPair.query.get(pair_id)
            if not pair:
                continue
            last = ProfitLog.query.filter_by(symbol=pair.symbol, exchange=pair.exchange)\
                .order_by(ProfitLog.timestamp.desc()).first()
            if last and last.timestamp < cutoff:
                key = f'no_cycles_{pair.symbol}_{pair.exchange}'
                if _can_send(key):
                    _mark_sent(key)
                    _send(
                        f"📉 CryptoBot — Nema ciklusa: {pair.symbol}",
                        f"""<h3>Par nije napravio nijedan ciklus</h3>
                        <p><b>Par:</b> {pair.symbol} | <b>Exchange:</b> {pair.exchange}</p>
                        <p>Zadnji ciklus: {last.timestamp.strftime('%Y-%m-%d %H:%M')} UTC</p>
                        <p>Nema ciklusa <b>{days:.0f} dana</b> — cijena je možda izašla iz grida.</p>"""
                    )
    except Exception as e:
        logger.warning(f"no cycles check error: {e}")

def _check_rebalancing(cfg):
    if not _cfg(cfg, 'rebalancing'):
        return
    if not _can_send('rebalancing'):
        return
    try:
        from core.models import Portfolio, PortfolioHolding, GlobalTarget
        import requests as req
        import json as _json
        with open(KEY_FILE) as f:
            keys = _json.load(f)
        api_key = keys.get('coinmarketcap', {}).get('api_key', '')
        if not api_key:
            return
        portfolios = Portfolio.query.all()
        alerts = []
        for pf in portfolios:
            holdings = pf.holdings
            if not holdings:
                continue
            symbols = [h.symbol for h in holdings]
            r = req.get(
                'https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest',
                headers={'X-CMC_PRO_API_KEY': api_key},
                params={'symbol': ','.join(symbols), 'convert': 'USD'},
                timeout=10
            )
            prices = {}
            for sym, info in r.json().get('data', {}).items():
                if isinstance(info, list): info = info[0]
                prices[sym] = info['quote']['USD']['price']
            total = sum(h.amount * prices.get(h.symbol, 0) for h in holdings if h.include_rebalancing)
            if total <= 0:
                continue
            for h in holdings:
                if not h.include_rebalancing or h.target_pct <= 0:
                    continue
                val = h.amount * prices.get(h.symbol, 0)
                pct = val / total * 100
                diff = abs(pct - h.target_pct)
                if diff >= pf.threshold_pct:
                    action = 'Prodaj' if pct > h.target_pct else 'Kupi'
                    alerts.append(f"{h.symbol} ({pf.name}): {action} — odstupanje {diff:.1f}%")
        if alerts:
            _mark_sent('rebalancing')
            _send(
                "⚖️ CryptoBot — Rebalancing portfolija",
                f"""<h3>Potreban rebalancing portfolija</h3>
                <ul>{''.join(f'<li>{a}</li>' for a in alerts)}</ul>"""
            )
    except Exception as e:
        logger.warning(f"rebalancing check error: {e}")

def _check_daily_summary(cfg):
    section = cfg.get('daily_summary', {})
    if not section.get('enabled'):
        return
    send_time = section.get('time', '20:00')
    now = datetime.utcnow()
    try:
        h, m = map(int, send_time.split(':'))
    except Exception:
        return
    if now.hour != h or now.minute > m + 5:
        return
    if not _can_send('daily_summary'):
        return
    try:
        from core.models import ProfitLog
        # Jučer — cijeli dan od 00:00 do 23:59
        yesterday = (now - timedelta(days=1)).date()
        day_start = datetime.combine(yesterday, datetime.min.time())
        day_end   = datetime.combine(now.date(), datetime.min.time())
        logs = ProfitLog.query.filter(
            ProfitLog.timestamp >= day_start,
            ProfitLog.timestamp < day_end
        ).all()
        if not logs:
            return
        total = sum(l.profit_usdt for l in logs)
        cycles = len(logs)
        by_pair = {}
        for l in logs:
            key = f"{l.symbol} ({l.exchange})"
            by_pair[key] = by_pair.get(key, 0) + l.profit_usdt
        rows = ''.join(f'<tr><td>{k}</td><td style="color:green;">${v:.2f}</td></tr>' for k, v in sorted(by_pair.items(), key=lambda x: -x[1]))
        _mark_sent('daily_summary')
        _send(
            f"📊 CryptoBot — Dnevni summary {yesterday}",
            f"""<h3>Dnevni summary — {yesterday}</h3>
            <p><b>Ukupni profit:</b> <span style="color:green;font-size:1.3em;">${total:.2f} USDC</span></p>
            <p><b>Broj ciklusa:</b> {cycles}</p>
            <table border="1" cellpadding="4" style="border-collapse:collapse;">
            <tr><th>Par</th><th>Profit</th></tr>{rows}</table>"""
        )
    except Exception as e:
        logger.debug(f"daily summary error: {e}")

def _check_weekly_summary(cfg):
    section = cfg.get('weekly_summary', {})
    if not section.get('enabled'):
        return
    send_day = section.get('day', 'monday').lower()
    send_time = section.get('time', '09:00')
    now = datetime.utcnow()
    days = ['monday','tuesday','wednesday','thursday','friday','saturday','sunday']
    if now.weekday() != days.index(send_day):
        return
    try:
        h, m = map(int, send_time.split(':'))
    except Exception:
        return
    if now.hour != h or now.minute > m + 5:
        return
    if not _can_send('weekly_summary'):
        return
    try:
        from core.models import ProfitLog
        # Prošli tjedan: ponedjeljak 00:00 → nedjelja 23:59
        # now.weekday() == 0 znači danas je ponedjeljak → prošli tjedan počeo 7 dana unazad
        today = now.date()
        week_end   = datetime.combine(today, datetime.min.time())           # danas 00:00 = kraj prošle ned.
        week_start = datetime.combine(today - timedelta(days=7), datetime.min.time())  # prije 7 dana 00:00
        week_start_date = week_start.date()
        week_end_date   = (week_end - timedelta(seconds=1)).date()
        logs = ProfitLog.query.filter(
            ProfitLog.timestamp >= week_start,
            ProfitLog.timestamp < week_end
        ).all()
        if not logs:
            return
        total = sum(l.profit_usdt for l in logs)
        cycles = len(logs)
        by_pair = {}
        for l in logs:
            key = f"{l.symbol} ({l.exchange})"
            by_pair[key] = by_pair.get(key, 0) + l.profit_usdt
        rows = ''.join(f'<tr><td>{k}</td><td style="color:{"green" if v>=0 else "red"};">${v:.2f}</td></tr>' for k, v in sorted(by_pair.items(), key=lambda x: -x[1]))
        _mark_sent('weekly_summary')
        _send(
            f"📈 CryptoBot — Tjedni summary ({week_start_date} — {week_end_date})",
            f"""<h3>Tjedni summary</h3>
            <p><b>Period:</b> {week_start_date} — {week_end_date}</p>
            <p><b>Ukupni profit:</b> <span style="color:green;font-size:1.3em;">${total:.2f} USDC</span></p>
            <p><b>Broj ciklusa:</b> {cycles}</p>
            <table border="1" cellpadding="4" style="border-collapse:collapse;">
            <tr><th>Par</th><th>Profit</th></tr>{rows}</table>"""
        )
    except Exception as e:
        logger.debug(f"weekly summary error: {e}")

def _check_price_drop_from_sell(cfg):
    section = cfg.get('price_drop_alert', {})
    if not section.get('enabled'):
        return
    drop_pct = float(section.get('drop_pct', 55))
    try:
        from core.models import TradingPair, Order
        from modules.bot_control import bot_manager
        from modules.utils import get_price
        state = _load_state()
        drop_state = state.get('price_drop_state', {})
        changed = False

        # ── Provjera pada — samo za pokrenute parove koji imaju sell ordere ──
        for pair_id, status in bot_manager.get_status().items():
            if not status.get('running'):
                continue
            pair = TradingPair.query.get(pair_id)
            if not pair:
                continue
            sell_orders = Order.query.filter_by(
                symbol=pair.symbol, exchange=pair.exchange, side='sell', status='open'
            ).all()
            if not sell_orders:
                continue
            highest_sell = max(o.price for o in sell_orders)
            lowest_sell  = min(o.price for o in sell_orders)
            current = get_price(pair.exchange, pair.symbol, pair.trading_mode)
            if not isinstance(current, (int, float)):
                continue
            drop = (highest_sell - current) / highest_sell * 100
            key = f"{pair.symbol}|{pair.exchange}"
            if drop_state.get(key, {}).get('status') == 'normal' and drop >= drop_pct:
                drop_state[key] = {'status': 'dropped', 'lowest_sell': lowest_sell}
                changed = True
                _send(
                    f"⚠️ CryptoBot — Veliki pad: {pair.symbol} ({pair.exchange})",
                    f"""<h3>Cijena pala {drop:.1f}% ispod sell ordera</h3>
                    <p><b>Par:</b> {pair.symbol} | <b>Exchange:</b> {pair.exchange}</p>
                    <p><b>Najviši sell order:</b> ${highest_sell:.4f}</p>
                    <p><b>Najniži sell order:</b> ${lowest_sell:.4f}</p>
                    <p><b>Trenutna cijena:</b> ${current:.4f} ({drop:.1f}% ispod)</p>
                    <p><b>Preporuka:</b> Ugasi par — čekaj oporavak iznad ${lowest_sell:.4f}.</p>
                    <p><small>{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC</small></p>"""
                )

        # ── Provjera oporavka — za sve parove u 'dropped' stanju (i zaustavljene) ──
        all_pairs = TradingPair.query.all()
        for pair in all_pairs:
            key = f"{pair.symbol}|{pair.exchange}"
            pair_info = drop_state.get(key, {})
            if pair_info.get('status') != 'dropped':
                continue
            lowest_sell = pair_info.get('lowest_sell')
            if not lowest_sell:
                continue
            current = get_price(pair.exchange, pair.symbol, pair.trading_mode)
            if not isinstance(current, (int, float)):
                continue
            if current >= lowest_sell:
                drop_state[key] = {'status': 'normal', 'lowest_sell': None}
                changed = True
                _send(
                    f"✅ CryptoBot — Oporavak: {pair.symbol} ({pair.exchange})",
                    f"""<h3>Cijena prešla najniži sell order — {pair.symbol}</h3>
                    <p><b>Par:</b> {pair.symbol} | <b>Exchange:</b> {pair.exchange}</p>
                    <p><b>Referentna cijena (najniži sell):</b> ${lowest_sell:.4f}</p>
                    <p><b>Trenutna cijena:</b> ${current:.4f}</p>
                    <p><b>Preporuka:</b> Možeš ponovno upaliti par.</p>
                    <p><small>{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC</small></p>"""
                )

        if changed:
            state['price_drop_state'] = drop_state
            _save_state(state)
    except Exception as e:
        logger.warning(f"price drop check error: {e}")

# ── Glavni checker (poziva se iz background threada) ─────────────────────────

def check_all(app, pairs_status=None):
    with app.app_context():
        cfg = _load_config()
        if not cfg:
            return
        from modules.email_sender import is_configured
        if not is_configured():
            return
        _check_bot_inactive(cfg, pairs_status or [])
        _check_balance_low(cfg)
        _check_missing_orders(cfg)
        _check_no_cycles(cfg)
        _check_rebalancing(cfg)
        _check_daily_summary(cfg)
        _check_weekly_summary(cfg)
        _check_price_drop_from_sell(cfg)

# ── Background thread ─────────────────────────────────────────────────────────

_checker_thread = None

def start_notification_checker(app):
    global _checker_thread
    if _checker_thread and _checker_thread.is_alive():
        return

    def run():
        time.sleep(30)  # Čekaj da se app potpuno pokrene
        while True:
            try:
                from modules.bot_control import bot_manager
                pairs_status = [
                    {'symbol': s.get('symbol'), 'exchange': s.get('exchange'), 'running': s.get('running')}
                    for s in bot_manager.get_status().values()
                ]
                check_all(app, pairs_status)
            except Exception as e:
                logger.debug(f"notification checker error: {e}")
            time.sleep(300)  # Svake 5 minuta

    _checker_thread = threading.Thread(target=run, daemon=True, name='notification-checker')
    _checker_thread.start()
    logger.info("Notification checker pokrenut")
