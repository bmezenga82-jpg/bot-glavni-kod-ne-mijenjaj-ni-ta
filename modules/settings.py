from core.models import TradingPair
from flask import request, redirect, url_for, flash, render_template, session, jsonify, current_app
from modules.utils import get_pairs, load_api_keys, save_api_keys, get_exchange_pairs, reset_connectors
from modules.data import reset_cached_connectors
import yaml
from modules.notifications import notifications, save_notifications, add_notification
from modules.bot_control import bot_manager
from modules.auth import users, bcrypt
from core.extensions import db


def save_settings_yaml(config):
    data = {
        'base_currency': config.get('base_currency', 'USDC'),
        'trading_mode': config.get('trading_mode', 'testnet'),
        'database': config.get('database', {}),
        'pairs': get_pairs(),
    }
    with open('settings.yaml', 'w') as f:
        yaml.safe_dump(data, f)

def settings():
    if 'theme' not in session:
        session['theme'] = 'dark'
    
    api_keys = load_api_keys()
    exchanges = ['binance', 'bybit', 'gateio', 'bitmart']

    all_pairs = get_pairs()
    selected_symbols = [pair['symbol'] for pair in all_pairs]
    enumerated_pairs = list(enumerate(all_pairs))

    first_exchange = all_pairs[0]['exchange'] if all_pairs else None
    if first_exchange:
        available_pairs = get_exchange_pairs(first_exchange, current_app.config.get('trading_mode', 'testnet'))
    else:
        available_pairs = []

    return render_template('settings.html',
                           pairs=enumerated_pairs,
                           notifications=dict(notifications),
                           available_pairs=available_pairs,
                           exchanges=exchanges,
                           saved_pairs=all_pairs,
                           api_keys=api_keys,
                           selected_symbols=selected_symbols,
                           
                           current_theme=session['theme'])
def api_update_general(config):
    mode = request.form.get('trading_mode', 'testnet')
    if mode not in ['testnet', 'real']:
        mode = 'testnet'
    config['trading_mode'] = mode
    session['theme'] = request.form.get('theme', 'dark')

    save_settings_yaml(config)

    return jsonify({'status': 'success', 'message': 'General settings updated successfully!'})

def api_update_pairs(): 
    selected_pairs = request.form.getlist('selected_pairs')

    # Remove pairs not selected
    existing_ids = {pair.id for pair in TradingPair.query.all()}
    ids_to_delete = existing_ids - set(map(int, selected_pairs))
    if ids_to_delete:
        TradingPair.query.filter(TradingPair.id.in_(ids_to_delete)).delete(synchronize_session=False)

    for pair_id in selected_pairs:
        pair_id = int(pair_id)
        try:
            buy_pct = float(request.form.get(f'buy_percentage_{pair_id}', '2.0'))
            sell_pct = float(request.form.get(f'sell_percentage_{pair_id}', '3.0'))
            amount = float(request.form.get(f'amount_{pair_id}', '100.0'))
            exchange = request.form.get(f'exchange_{pair_id}', 'binance')
            mode = request.form.get(f'trading_mode_{pair_id}', 'testnet')
            profit_mode = request.form.get(f'profit_mode_{pair_id}', 'usdc')
        except ValueError:
            return jsonify({'status': 'error', 'message': f'Invalid numeric input for pair {pair_id}.'}), 400

        pair = TradingPair.query.get(pair_id)
        pair_symbol = pair.symbol if pair else f'pair {pair_id}'

        if buy_pct >= 0:
            return jsonify({'status': 'error', 'message': f'Invalid Buy % for {pair_symbol}. Must be negative.'}), 400

        available = get_exchange_pairs(exchange, mode)
        if pair and pair.symbol not in available:
            return jsonify({'status': 'error', 'message': f'{pair.symbol} not available on {exchange}.'}), 400

        if pair:
            pair.amount = amount
            pair.buy_percentage = buy_pct
            pair.sell_percentage = sell_pct
            pair.exchange = exchange
            pair.trading_mode = mode
            pair.profit_mode = profit_mode if profit_mode in ['usdc', 'crypto'] else 'usdc'

    db.session.commit()

    save_settings_yaml(current_app.config)

    # Update notifications
    notifications.clear()
    for pair_id in selected_pairs:
        pair = TradingPair.query.get(int(pair_id))
        if pair:
            notifications[pair.symbol] = []
    save_notifications(notifications)

    return jsonify({'status': 'success', 'message': 'Trading pairs updated successfully!'})


def api_add_pair():
    exchange = request.form.get('exchange', 'binance')
    new_pair = request.form.get('new_pair')
    mode = request.form.get('trading_mode', 'testnet')
    profit_mode = request.form.get('profit_mode', 'usdc')
    available_pairs = get_exchange_pairs(exchange, mode)

    if not new_pair:
        return jsonify({'status': 'error', 'message': 'Pair symbol missing.'}), 400

    if new_pair not in available_pairs:
        return jsonify({'status': 'error', 'message': 'Invalid trading pair.'}), 400

    existing = TradingPair.query.filter_by(symbol=new_pair, exchange=exchange).first()
    if existing:
        return jsonify({'status': 'error', 'message': 'Pair already exists.'}), 400

    pair = TradingPair(
        symbol=new_pair,
        exchange=exchange,
        amount=100.0,
        buy_percentage=-2.0,
        sell_percentage=3.0,
        trading_mode=mode,
        profit_mode='usdc' if profit_mode not in ['usdc', 'crypto'] else profit_mode
    )
    db.session.add(pair)
    db.session.commit()

    notifications[new_pair] = []
    save_notifications(notifications)

    return jsonify({'status': 'success', 'message': f'Added {new_pair} successfully!'})


def api_remove_pair():
    pair_id = request.form.get('pair_id', type=int)

    if not pair_id:
        return jsonify({'status': 'error', 'message': 'No pair provided.'}), 400

    pair = TradingPair.query.get(pair_id)

    if bot_manager.is_running(pair_id):
        bot_manager.stop_bot(pair_id)

    TradingPair.query.filter_by(id=pair_id).delete()
    db.session.commit()

    if pair:
        notifications.pop(pair.symbol, None)

    save_notifications(notifications)

    return jsonify({'status': 'success', 'message': 'Removed pair successfully!'})


def api_update_api_keys():
    api_keys = load_api_keys()

    api_keys['binance']['testnet']['api_key'] = request.form.get('binance_testnet_api_key', 'your_testnet_api_key')
    api_keys['binance']['testnet']['secret_key'] = request.form.get('binance_testnet_secret_key', 'your_testnet_secret_key')
    api_keys['binance']['real']['api_key'] = request.form.get('binance_real_api_key', 'your_real_api_key')
    api_keys['binance']['real']['secret_key'] = request.form.get('binance_real_secret_key', 'your_real_secret_key')

    for ex in ['bybit', 'gateio', 'bitmart']:
        api_keys.setdefault(ex, {'real': {}})
        api_keys[ex]['real']['api_key'] = request.form.get(f'{ex}_real_api_key', '')
        api_keys[ex]['real']['secret_key'] = request.form.get(f'{ex}_real_secret_key', '')
        if ex == 'bitmart':
            api_keys[ex]['real']['uid'] = request.form.get('bitmart_real_uid', '')

    save_api_keys(api_keys)
    reset_connectors()
    reset_cached_connectors()

    return jsonify({'status': 'success', 'message': 'API keys updated successfully!'})


def api_change_password():
    from modules.auth import _persist_password
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')

    if not current_password or not new_password:
        return jsonify({'status': 'error', 'message': 'Missing password fields.'}), 400

    if not bcrypt.check_password_hash(users['admin']['password'], current_password):
        return jsonify({'status': 'error', 'message': 'Current password is incorrect.'}), 400

    hashed = bcrypt.generate_password_hash(new_password).decode('utf-8')
    users['admin']['password'] = hashed
    _persist_password(hashed)

    return jsonify({'status': 'success', 'message': 'Password changed successfully!'})

def set_base_currency():
    base_currency = request.json.get('base_currency', 'USDC')
    session['base_currency'] = base_currency.upper()
    return jsonify({'status': 'Base currency updated', 'base_currency': session['base_currency']})


def update_pair_config(config):
    """Update individual pair settings from the dashboard edit modal."""
    data = request.json or {}
    pair_id = data.get('pair_id')
    if pair_id is None:
        return jsonify({'status': 'error', 'message': 'Pair ID missing'}), 400

    pair = TradingPair.query.get(pair_id)
    if not pair:
        return jsonify({'status': 'error', 'message': 'Pair not found'}), 404

    try:
        buy_pct = float(data.get('buy_percentage', pair.buy_percentage))
        if buy_pct >= 0:
            return jsonify({'status': 'error', 'message': 'Buy percentage must be negative'}), 400
        pair.sell_percentage = float(data.get('sell_percentage', pair.sell_percentage))
        pair.amount = float(data.get('amount', pair.amount))
        exchange = data.get('exchange', pair.exchange)
        mode = data.get('trading_mode', pair.trading_mode)
        profit_mode = data.get('profit_mode', pair.profit_mode)
        available = get_exchange_pairs(exchange, mode)
        if pair.symbol not in available:
            return jsonify({'status': 'error', 'message': f'{pair.symbol} not available on {exchange}.'}), 400
        pair.exchange = exchange
        pair.trading_mode = mode
        if profit_mode in ['usdc', 'crypto']:
            pair.profit_mode = profit_mode
        pair.drop_alert_enabled = bool(data.get('drop_alert_enabled', False))
        pair.drop_alert_pct = float(data.get('drop_alert_pct', 55.0))
        pair.drop_alert_auto = bool(data.get('drop_alert_auto', False))
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Invalid values'}), 400

    pair.buy_percentage = buy_pct
    db.session.commit()

    running = bot_manager.is_running(pair_id)
    if running:
        add_notification(pair.symbol, f'Postavke ažurirane — primjenjuju se na sljedeće narudžbe (bot radi)', 'info')
        return jsonify({'status': 'success', 'bot_running': True,
                        'message': 'Postavke su snimljene. Bot nastavlja s postojećim orderima, novi orderi koristit će nove parametre.'})
    return jsonify({'status': 'success', 'bot_running': False})
