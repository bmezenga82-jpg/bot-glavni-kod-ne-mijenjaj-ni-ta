# core/routes.py

from flask import render_template, request, jsonify, session, send_file, flash, current_app, url_for, redirect
from flask_login import login_required, current_user

from modules.auth import login, logout
from modules.bot_control import bot_manager, control_bot, profit_tracker
from modules.data import get_data, get_profit_data, get_trade_data # Removed get_account_balances
from modules.notifications import get_notifications, clear_notifications
from modules.settings import (
    api_add_pair,
    api_change_password,
    api_remove_pair,
    api_update_api_keys,
    api_update_general,
    api_update_pairs,
    settings,
    set_base_currency,
    update_pair_config,
)
from modules.backtest import backtest, optimize
import logging
from concurrent.futures import ThreadPoolExecutor  # Added import
import io
import csv


from modules.utils import get_pairs, load_api_keys, get_exchange_pairs
from modules.exchange_config import ExchangeConfig

# connected_clients = set()  # Unused global in this file; factory.py has its own.
# trade_status = {}  # Unused global in this file; factory.py and data.py manage their own.

logging.basicConfig(
    level=logging.INFO, format="[%(asctime)s] %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


from core.models import ProfitLog, BacktestResult, BacktestFolder  # Added for P&L calculation
from sqlalchemy import func  # Added for P&L calculation
from datetime import datetime, timedelta

# Helper function for concurrent balance fetching
def _fetch_exchange_data_worker(args): # Renamed function
    # Now expects app object as the last argument
    ex_name, mode_str, global_base_currency, api_keys_data, all_configured_pairs, bot_manager_instance, app_instance = args
    # This function will be executed in a separate thread.

    from core.exchange import ExchangeConnector
    from core.extensions import db

    is_testnet_mode = mode_str == "testnet"
    balance_display_value = "N/A"
    active_pairs_count = 0
    pnl_for_exchange_mode = 0.0

    currency_to_fetch = global_base_currency
    if ex_name.lower() == 'bitmart':
        currency_to_fetch = 'USDT' # Bitmart will always show USDT balance

    # Calculate Active Pairs for this exchange/mode
    try:
        relevant_pairs = [
            p for p in all_configured_pairs
            if p['exchange'].lower() == ex_name.lower() and p['trading_mode'].lower() == mode_str.lower()
        ]
        active_pairs_count = sum(1 for p in relevant_pairs if bot_manager_instance.is_running(p['id']))
    except Exception as e:
        logger.error(f"Error calculating active pairs for {ex_name} ({mode_str}): {e}", exc_info=True)
        active_pairs_count = "Error" # Or 0

    # Fetch Balance
    try:
        exchange_id, params = ExchangeConfig.setup_exchange(ex_name, is_testnet=is_testnet_mode, api_keys_override=api_keys_data)
        connector = ExchangeConnector(exchange_id=exchange_id, params=params)
        raw_balance = connector.get_balance(currency_to_fetch)

        if raw_balance == "AUTH_ERROR":
            balance_display_value = "AUTH ERROR"
        elif raw_balance is None:
            balance_display_value = "N/A"
        elif isinstance(raw_balance, (int, float)):
            balance_display_value = f"{raw_balance:.2f}"
        else:
            logger.error(f"Unexpected balance type for {ex_name} ({mode_str}): {raw_balance} (type: {type(raw_balance)})")
            balance_display_value = "Invalid Data"
    except RuntimeError as e:
        logger.warning(f"API Key/Config Runtime Error for {ex_name} ({mode_str}) fetching balance: {e}")
        balance_display_value = "SETUP ERROR"
    except ValueError as e:
        logger.warning(f"Config Value Error for {ex_name} ({mode_str}) fetching balance: {e}")
        balance_display_value = "CONFIG ERROR"
    except Exception as e:
        logger.error(f"Unexpected error fetching balance for {ex_name} ({mode_str}) in worker: {e}", exc_info=True)
        balance_display_value = "ERROR"

    # Calculate P&L for this exchange/mode from ProfitLog
    try:
        with app_instance.app_context():
            # We need the app context for db.session to work correctly in a thread if not already handled by flask-sqlalchemy extension
            # However, this worker is called via ThreadPoolExecutor from a route, which should manage context.
            # If issues arise, app_context() might be needed here.
            pnl_sum = db.session.query(func.sum(ProfitLog.profit_usdt)).filter(
                ProfitLog.exchange == ex_name,
                ProfitLog.trading_mode == mode_str
            ).scalar()
            pnl_for_exchange_mode = round(pnl_sum or 0.0, 2)
    except Exception as e:
        logger.error(f"Error calculating P&L for {ex_name} ({mode_str}): {e}", exc_info=True)
        pnl_for_exchange_mode = "Error" # Or 0.0

    return {
        "exchange": ex_name,
        "mode": mode_str.capitalize(),
        "balance": balance_display_value,
        "active_pairs": active_pairs_count,
        "pnl": pnl_for_exchange_mode
    }



def register_routes(app):
    @app.route("/login", methods=["GET", "POST"])
    def login_route():
        return login()

    @app.route("/logout")
    @login_required
    def logout_route():
        return logout()

    @app.route("/")
    @login_required
    def home():
        if "theme" not in session:
            session["theme"] = "dark"
        if "base_currency" not in session:
            session["base_currency"] = app.config.get("base_currency", "USDC")

        # Load API keys once
        api_keys_data = load_api_keys()

        # Flash warnings for unconfigured Binance keys (original logic maintained)
        for mode in ["testnet", "real"]:
            k = api_keys_data.get("binance", {}).get(mode, {})
            if "your_" in k.get("api_key", "") or "your_" in k.get("secret_key", ""):
                flag = f"warned_{mode}"
                if not session.get(flag):
                    flash(
                        f"{mode.capitalize()} API keys not configured. Update api_keys.json or environment variables.",
                        "warning",
                    )
                    session[flag] = True

        exchanges_to_fetch = ["binance", "bybit", "gateio", "bitmart"] # Hardcoded list from original
        base_currency = session["base_currency"]

        all_pairs_data = get_pairs()
        pairs_with_status = []
        for pair in all_pairs_data:
            pair_copy = pair.copy()
            pair_copy['is_running'] = bot_manager.is_running(pair['id'])
            pairs_with_status.append(pair_copy)

        # Account information will be fetched asynchronously via /api/data
        account_info_results = []

        return render_template(
            "dashboard.html",
            pairs=pairs_with_status, # Use the augmented list
            notifications=[],
            base_currency=base_currency,
            trading_mode=app.config.get("trading_mode", "testnet"),
            exchanges=exchanges_to_fetch,
            balances=account_info_results,
        )

    @app.route("/trades")
    @login_required
    def trades():
        if "theme" not in session:
            session["theme"] = "dark"
        return render_template("trades.html", notifications=[])

    @app.route("/notifications")
    @login_required
    def notification_history():
        if "theme" not in session:
            session["theme"] = "dark"
        notifications = get_notifications()
        notification_list = [
            {
                "symbol": symbol,
                "message": msg["message"],
                "type": msg["type"],
                "timestamp": msg["timestamp"],
            }
            for symbol, messages in notifications.items()
            for msg in messages
        ]
        notification_list.sort(key=lambda x: x["timestamp"], reverse=True)
        return render_template("notifications.html", notifications=notification_list)

    @app.route("/backtest", methods=["GET", "POST"])
    @login_required
    def backtest_route():
        return backtest(app.config)

    @app.route("/optimize", methods=["POST"])
    @login_required
    def optimize_route():
        return optimize()

    @app.route("/api/backtest/folders", methods=["GET"])
    @login_required
    def get_backtest_folders():
        def folder_to_dict(f):
            return {
                'id': f.id, 'name': f.name, 'parent_id': f.parent_id,
                'children': [folder_to_dict(c) for c in sorted(f.children, key=lambda x: x.name)],
            }
        roots = BacktestFolder.query.filter_by(parent_id=None).order_by(BacktestFolder.name).all()
        return jsonify([folder_to_dict(f) for f in roots])

    @app.route("/api/backtest/folders", methods=["POST"])
    @login_required
    def create_backtest_folder():
        from core.extensions import db as _db
        data = request.get_json()
        f = BacktestFolder(name=data['name'], parent_id=data.get('parent_id'))
        _db.session.add(f)
        _db.session.commit()
        return jsonify({'id': f.id, 'name': f.name, 'parent_id': f.parent_id})

    @app.route("/api/backtest/folders/<int:folder_id>", methods=["PATCH"])
    @login_required
    def rename_backtest_folder(folder_id):
        from core.extensions import db as _db
        f = BacktestFolder.query.get_or_404(folder_id)
        data = request.get_json()
        f.name = data.get('name', f.name)
        _db.session.commit()
        return jsonify({'ok': True})

    @app.route("/api/backtest/folders/<int:folder_id>", methods=["DELETE"])
    @login_required
    def delete_backtest_folder(folder_id):
        from core.extensions import db as _db
        f = BacktestFolder.query.get_or_404(folder_id)
        # Premjesti testove u root (null folder)
        BacktestResult.query.filter_by(folder_id=folder_id).update({'folder_id': None})
        # Premjesti podmape u root
        BacktestFolder.query.filter_by(parent_id=folder_id).update({'parent_id': None})
        _db.session.delete(f)
        _db.session.commit()
        return jsonify({'ok': True})

    @app.route("/api/backtest/saved/<int:test_id>/move", methods=["PATCH"])
    @login_required
    def move_backtest_to_folder(test_id):
        from core.extensions import db as _db
        t = BacktestResult.query.get_or_404(test_id)
        data = request.get_json()
        t.folder_id = data.get('folder_id')  # None = root
        _db.session.commit()
        return jsonify({'ok': True})

    @app.route("/api/backtest/saved", methods=["GET"])
    @login_required
    def get_saved_backtests():
        from core.extensions import db as _db
        tests = BacktestResult.query.order_by(BacktestResult.created_at.desc()).all()
        return jsonify([{
            'id': t.id, 'name': t.name,
            'created_at': t.created_at.strftime('%Y-%m-%d %H:%M'),
            'symbol': t.symbol, 'exchange': t.exchange,
            'buy_pct': t.buy_pct, 'sell_pct': t.sell_pct,
            'amount': t.amount, 'total_capital': t.total_capital,
            'timeframe': t.timeframe, 'start_date': t.start_date, 'end_date': t.end_date,
            'folder_id': t.folder_id, 'profit_mode': t.profit_mode, 'net_profit': t.net_profit,
            'total_pnl': t.total_pnl, 'roi_pct': t.roi_pct,
            'annualized_roi': t.annualized_roi, 'trade_count': t.trade_count,
            'open_positions': t.open_positions, 'period_days': t.period_days,
        } for t in tests])

    @app.route("/api/backtest/save", methods=["POST"])
    @login_required
    def save_backtest():
        from core.extensions import db as _db
        data = request.get_json()
        t = BacktestResult(
            name=data.get('name', 'Test'),
            symbol=data['symbol'], exchange=data['exchange'],
            buy_pct=data['buy_pct'], sell_pct=data['sell_pct'],
            amount=data['amount'], total_capital=data['total_capital'],
            timeframe=data.get('timeframe', '1h'),
            start_date=data.get('start_date'), end_date=data.get('end_date'),
            profit_mode=data.get('profit_mode', 'usdc'),
            net_profit=data.get('net_profit'), total_pnl=data.get('total_pnl'),
            roi_pct=data.get('roi_pct'), annualized_roi=data.get('annualized_roi'),
            trade_count=data.get('trade_count'), open_positions=data.get('open_positions'),
            period_days=data.get('period_days'),
        )
        _db.session.add(t)
        _db.session.commit()
        return jsonify({'id': t.id})

    @app.route("/api/backtest/saved/<int:test_id>", methods=["PATCH"])
    @login_required
    def rename_backtest(test_id):
        from core.extensions import db as _db
        t = BacktestResult.query.get_or_404(test_id)
        data = request.get_json()
        t.name = data.get('name', t.name)
        _db.session.commit()
        return jsonify({'ok': True})

    @app.route("/api/backtest/saved/<int:test_id>", methods=["DELETE"])
    @login_required
    def delete_backtest(test_id):
        from core.extensions import db as _db
        t = BacktestResult.query.get_or_404(test_id)
        _db.session.delete(t)
        _db.session.commit()
        return jsonify({'ok': True})

    @app.route("/settings", methods=["GET", "POST"])
    @login_required
    def settings_route():
        return settings()

    @app.route("/api/update_general", methods=["POST"])
    @login_required
    def api_update_general_route():
        return api_update_general(app.config)

    @app.route("/api/update_pairs", methods=["POST"])
    @login_required
    def api_update_pairs_route():
        return api_update_pairs()

    @app.route("/api/add_pair", methods=["POST"])
    @login_required
    def api_add_pair_route():
        return api_add_pair()

    @app.route("/api/remove_pair", methods=["POST"])
    @login_required
    def api_remove_pair_route():
        return api_remove_pair()

    @app.route("/api/exchange_pairs")
    @login_required
    def api_exchange_pairs_route():
        ex = request.args.get("exchange", "binance")
        mode = current_app.config.get("trading_mode", "testnet")
        return jsonify({"pairs": get_exchange_pairs(ex, mode)})

    @app.route("/api/update_api_keys", methods=["POST"])
    @login_required
    def api_update_api_keys_route():
        return api_update_api_keys()

    @app.route("/api/change_password", methods=["POST"])
    @login_required
    def api_change_password_route():
        return api_change_password()

    @app.route("/set_base_currency", methods=["POST"])
    @login_required
    def set_base_currency_route():
        result = set_base_currency()
        result_data = result.get_json()
        if result_data.get("status") == "success":
            with app.app_context():
                app.config["CONFIG"]["base_currency"] = result_data.get(
                    "base_currency", "USDC"
                )
        return result

    @app.route("/api/update_pair_config", methods=["POST"])
    @login_required
    def update_pair_config_route():
        result = update_pair_config(app.config)
        return result

    @app.route("/api/data")
    @login_required
    def get_data_route():
        return get_data(app.config, bot_manager.bot_running, current_app._get_current_object(), bot_manager)

    @app.route("/api/control", methods=["POST"])
    @login_required
    def control_bot_route():
        # data = request.get_json()
        # action = data.get('action')
        # symbol = data.get('symbol')
        # if action in ['start', 'stop'] and symbol in [pair['symbol'] for pair in get_pairs()]:
        #     trade_status[symbol] = (action == 'start')
        #     control_bot()
        #     logger.info('Trade status updated for %s: %s', symbol, trade_status[symbol])
        #     return jsonify({'status': f'Successfully {action}ed bot for {symbol}'})
        # return jsonify({'status': 'Invalid action or symbol'}), 400
        return control_bot(app.config, app)

    @app.route("/api/profit_data")
    @login_required
    def get_profit_data_route():
        return get_profit_data()

    @app.route("/api/trade_data")
    @login_required
    def get_trade_data_route():
        trades = get_trade_data()
        # Filter for open orders (assuming 'status' field indicates open trades)
        open_orders = [
            trade for trade in trades if trade.get("status", "").lower() == "open"
        ]
        return jsonify(open_orders)

    @app.route("/api/open_positions")
    @login_required
    def get_open_positions_route():
        from modules.data import get_open_positions
        positions = get_open_positions()
        return jsonify(positions)

    @app.route("/api/clear_open_positions", methods=["POST"])
    @login_required
    def clear_open_positions_route():
        data = request.get_json() or {}
        symbol = data.get("symbol")
        exchange = data.get("exchange")
        mode = data.get("trading_mode")
        if not symbol or not exchange:
            return jsonify({"error": "symbol and exchange required"}), 400
        try:
            from modules.data import clear_open_positions
            clear_open_positions(symbol, exchange, mode)
            return jsonify({"status": "success"})
        except Exception as e:
            logger.error(f"Error clearing positions: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500

    @app.route("/api/notifications")
    @login_required
    def get_notifications_route():
        return jsonify(get_notifications())

    @app.route("/clear_notifications", methods=["POST"])
    @login_required
    def clear_notifications_route():
        return clear_notifications()

    @app.route("/download_trades")
    @login_required
    def download_trades():
        try:
            return send_file("trades.csv", as_attachment=True)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/download_profit_log")
    @login_required
    def download_profit_log():
        try:
            timeframe = request.args.get('timeframe', 'all')
            sort_by = request.args.get('sort', 'timestamp')

            query = ProfitLog.query
            if timeframe != 'all':
                days_map = {'day': 1, 'week': 7, 'month': 30}
                days = days_map.get(timeframe)
                if days:
                    cutoff = datetime.utcnow() - timedelta(days=days)
                    query = query.filter(ProfitLog.timestamp >= cutoff)

            if sort_by == 'symbol':
                query = query.order_by(ProfitLog.symbol.asc(), ProfitLog.timestamp.desc())
            else:
                query = query.order_by(ProfitLog.timestamp.desc())

            rows = query.all()

            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(['timestamp', 'symbol', 'exchange', 'trading_mode', 'buy_price', 'sell_price', 'amount', 'profit_usdt'])
            for row in rows:
                writer.writerow([
                    row.timestamp.isoformat() if row.timestamp else '',
                    row.symbol,
                    row.exchange,
                    row.trading_mode,
                    row.buy_price,
                    row.sell_price,
                    row.amount,
                    row.profit_usdt
                ])

            output.seek(0)
            return send_file(io.BytesIO(output.getvalue().encode()), as_attachment=True, download_name='profit_log.csv', mimetype='text/csv')
        except Exception as e:
            logger.error(f"Error downloading profit log: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500

    @app.route("/api/bot_statuses")
    @login_required
    def get_bot_statuses():
        statuses = {}
        pairs = get_pairs()  # Assuming get_pairs() returns a list of dicts with 'id'
        for pair in pairs:
            statuses[pair['id']] = bot_manager.is_running(pair['id'])
        return jsonify(statuses)

    @app.route("/api/profit_log_entries")
    @login_required
    def get_profit_log_entries_route():
        try:
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 20, type=int)
            timeframe = request.args.get('timeframe', 'all')
            sort_by = request.args.get('sort', 'timestamp')

            symbol_filter = request.args.get('symbol', 'all')
            exchange_filter = request.args.get('exchange', 'all')

            profit_entries_query = ProfitLog.query

            if timeframe == 'custom':
                date_from = request.args.get('date_from', '')
                date_to = request.args.get('date_to', '')
                if date_from:
                    profit_entries_query = profit_entries_query.filter(
                        ProfitLog.timestamp >= datetime.strptime(date_from, '%Y-%m-%d')
                    )
                if date_to:
                    from datetime import date as _date
                    dt_to = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
                    profit_entries_query = profit_entries_query.filter(ProfitLog.timestamp < dt_to)
            elif timeframe != 'all':
                days_map = {'day': 1, 'week': 7, 'month': 30}
                days = days_map.get(timeframe)
                if days:
                    cutoff = datetime.utcnow() - timedelta(days=days)
                    profit_entries_query = profit_entries_query.filter(ProfitLog.timestamp >= cutoff)

            if symbol_filter != 'all':
                profit_entries_query = profit_entries_query.filter(ProfitLog.symbol == symbol_filter)

            if exchange_filter != 'all':
                profit_entries_query = profit_entries_query.filter(ProfitLog.exchange == exchange_filter)

            if sort_by == 'symbol':
                profit_entries_query = profit_entries_query.order_by(ProfitLog.symbol.asc(), ProfitLog.timestamp.desc())
            else:
                profit_entries_query = profit_entries_query.order_by(ProfitLog.timestamp.desc())

            paginated_entries = profit_entries_query.paginate(page=page, per_page=per_page, error_out=False)

            results = [
                {
                    "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                    "symbol": entry.symbol,
                    "buy_price": entry.buy_price,
                    "sell_price": entry.sell_price,
                    "amount": entry.amount,
                    "profit_usdt": entry.profit_usdt,
                    "exchange": entry.exchange,
                    "trading_mode": entry.trading_mode,
                }
                for entry in paginated_entries.items
            ]
            return jsonify({
                "entries": results,
                "total_pages": paginated_entries.pages,
                "current_page": paginated_entries.page,
                "has_next": paginated_entries.has_next,
                "has_prev": paginated_entries.has_prev,
                "total_items": paginated_entries.total
            })
        except Exception as e:
            logger.error(f"Error fetching profit log entries: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500

    @app.route("/api/profit_log_filters")
    @login_required
    def get_profit_log_filters():
        try:
            from core.extensions import db as _db
            symbols = [r[0] for r in _db.session.query(ProfitLog.symbol).distinct().order_by(ProfitLog.symbol).all() if r[0]]
            exchanges = [r[0] for r in _db.session.query(ProfitLog.exchange).distinct().order_by(ProfitLog.exchange).all() if r[0]]
            return jsonify({"symbols": symbols, "exchanges": exchanges})
        except Exception as e:
            logger.error(f"Error fetching profit log filters: {e}", exc_info=True)
            return jsonify({"symbols": [], "exchanges": []}), 500

    @app.route("/api/capital_calc_data")
    @login_required
    def capital_calc_data():
        try:
            from core.models import TradingPair, TradeLog
            pairs = TradingPair.query.all()
            result = []
            for p in pairs:
                # Invested = sum of buy trades cost (price * amount) in TradeLog
                buys = TradeLog.query.filter_by(symbol=p.symbol, exchange=p.exchange, side='buy').all()
                sells = TradeLog.query.filter_by(symbol=p.symbol, exchange=p.exchange, side='sell').all()
                buy_count = len(buys)
                sell_count = len(sells)
                open_buys = buy_count - sell_count
                invested = sum(t.usdt_value for t in buys[-max(open_buys, 0):]) if open_buys > 0 else 0.0
                result.append({
                    'pair_id': p.id,
                    'symbol': p.symbol,
                    'exchange': p.exchange,
                    'trading_mode': p.trading_mode,
                    'usdc_amount': p.amount,
                    'buy_pct': abs(p.buy_percentage),
                    'is_running': bot_manager.is_running(p.id),
                    'invested': round(invested, 2),
                })
            return jsonify(result)
        except Exception as e:
            logger.error(f"Error fetching capital calc data: {e}", exc_info=True)
            return jsonify([]), 500

    @app.route("/api/pair_profit")
    @login_required
    def get_pair_profit_route():
        try:
            return jsonify(profit_tracker.get_all_pair_profits())
        except Exception as e:
            logger.error(f"Error fetching pair profit: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500

    @app.route("/api/reset_profit", methods=["POST"])
    @login_required
    def reset_pair_profit_route():
        data = request.get_json() or {}
        pair_id = data.get("pair_id")
        if pair_id is None:
            return jsonify({"error": "pair_id required"}), 400
        try:
            success = profit_tracker.reset_profit(int(pair_id))
            if success:
                return jsonify({"status": "success"})
            return jsonify({"status": "not_found"}), 404
        except Exception as e:
            logger.error(f"Error resetting profit: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500

    @app.route("/api/remove_pair_profit", methods=["POST"])
    @login_required
    def remove_pair_profit_route():
        data = request.get_json() or {}
        pair_id = data.get("pair_id")
        if pair_id is None:
            return jsonify({"error": "pair_id required"}), 400
        try:
            success = profit_tracker.remove_pair_profit(int(pair_id))
            if success:
                return jsonify({"status": "success"})
            return jsonify({"status": "not_found"}), 404
        except Exception as e:
            logger.error(f"Error removing pair profit: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500

    @app.route("/api/performance_report")
    @login_required
    def performance_report_route():
        try:
            days = request.args.get('days', 1, type=int)
            query = ProfitLog.query
            if days > 0:
                cutoff = datetime.utcnow() - timedelta(days=days)
                query = query.filter(ProfitLog.timestamp >= cutoff)
            rows = query.all()

            grouped = {}
            for r in rows:
                key = (r.symbol, r.exchange)
                if key not in grouped:
                    grouped[key] = {'sells': 0, 'profit': 0.0}
                grouped[key]['sells'] += 1
                grouped[key]['profit'] += r.profit_usdt

            result = [
                {
                    'symbol': sym,
                    'exchange': ex,
                    'sells': d['sells'],
                    'profit': round(d['profit'], 4),
                    'avg': round(d['profit'] / d['sells'], 4) if d['sells'] else 0,
                }
                for (sym, ex), d in sorted(grouped.items())
            ]
            return jsonify(result)
        except Exception as e:
            logger.error(f"Error fetching performance report: {e}", exc_info=True)
            return jsonify([]), 500

    @app.route("/statistics")
    @login_required
    def statistics_route():
        if "theme" not in session:
            session["theme"] = "dark"
        return render_template("statistics.html", notifications=[])

    @app.route("/api/stats/summary")
    @login_required
    def stats_summary():
        try:
            from core.extensions import db as _db
            rows = _db.session.query(
                ProfitLog.symbol,
                ProfitLog.exchange,
                func.count(ProfitLog.id).label('cycles'),
                func.sum(ProfitLog.profit_usdt).label('total_profit'),
                func.avg(ProfitLog.profit_usdt).label('avg_profit'),
                func.min(ProfitLog.timestamp).label('first_trade'),
                func.max(ProfitLog.timestamp).label('last_trade'),
            ).filter(ProfitLog.trading_mode != 'testnet') \
             .group_by(ProfitLog.symbol, ProfitLog.exchange) \
             .order_by(ProfitLog.symbol).all()

            result = []
            now = datetime.utcnow()
            for r in rows:
                days_active = max((now - r.first_trade).days, 1) if r.first_trade else 1
                result.append({
                    'symbol': r.symbol,
                    'exchange': r.exchange,
                    'cycles': r.cycles,
                    'total_profit': round(r.total_profit or 0, 2),
                    'avg_profit': round(r.avg_profit or 0, 4),
                    'days_active': days_active,
                    'profit_per_day': round((r.total_profit or 0) / days_active, 4),
                    'first_trade': r.first_trade.strftime('%Y-%m-%d') if r.first_trade else '-',
                })
            return jsonify(result)
        except Exception as e:
            logger.error(f"stats_summary error: {e}", exc_info=True)
            return jsonify([]), 500

    @app.route("/api/stats/chart")
    @login_required
    def stats_chart():
        try:
            from core.extensions import db as _db
            period = request.args.get('period', '30')
            symbol = request.args.get('symbol', 'all')
            cumulative = request.args.get('cumulative', '0') == '1'

            query = _db.session.query(ProfitLog).filter(ProfitLog.trading_mode != 'testnet')
            if period != 'all':
                cutoff = datetime.utcnow() - timedelta(days=int(period))
                query = query.filter(ProfitLog.timestamp >= cutoff)
            if symbol != 'all':
                query = query.filter(ProfitLog.symbol == symbol)

            rows = query.order_by(ProfitLog.timestamp.asc()).all()

            daily = {}
            for r in rows:
                day = r.timestamp.strftime('%Y-%m-%d') if r.timestamp else 'unknown'
                daily[day] = daily.get(day, 0) + (r.profit_usdt or 0)

            labels = sorted(daily.keys())
            values = [round(daily[d], 4) for d in labels]

            if cumulative:
                total = 0
                cum = []
                for v in values:
                    total += v
                    cum.append(round(total, 4))
                values = cum

            symbols = [r[0] for r in _db.session.query(ProfitLog.symbol).filter(
                ProfitLog.trading_mode != 'testnet').distinct().order_by(ProfitLog.symbol).all()]

            return jsonify({'labels': labels, 'values': values, 'symbols': symbols})
        except Exception as e:
            logger.error(f"stats_chart error: {e}", exc_info=True)
            return jsonify({'labels': [], 'values': [], 'symbols': []}), 500

    @app.route("/analysis")
    @login_required
    def analysis_route():
        if "theme" not in session:
            session["theme"] = "dark"
        return render_template("analysis.html", notifications=[])

    @app.route("/api/market_analysis")
    @login_required
    def market_analysis_route():
        try:
            from core.models import TradingPair
            from modules.market_analysis import analyze_all
            timeframe = request.args.get('timeframe', '1h')
            allowed = {'1h', '1d', '1w', '1M'}
            if timeframe not in allowed:
                timeframe = '1h'
            pairs = TradingPair.query.filter(TradingPair.trading_mode != 'testnet').all()
            pair_list = [{'symbol': p.symbol, 'exchange': p.exchange} for p in pairs]
            if not pair_list:
                return jsonify([])
            results = analyze_all(pair_list, timeframe=timeframe)
            return jsonify(results)
        except Exception as e:
            logger.error(f"market_analysis error: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500

    @app.route("/api/dca_analysis")
    @login_required
    def dca_analysis_route():
        try:
            from core.models import TradingPair
            from modules.market_analysis import analyze_dca_all
            pairs = TradingPair.query.filter(TradingPair.trading_mode != 'testnet').all()
            pair_list = [{'symbol': p.symbol, 'exchange': p.exchange,
                          'pair_id': p.id, 'profit_mode': p.profit_mode} for p in pairs]
            if not pair_list:
                return jsonify([])
            results = analyze_dca_all(pair_list)
            return jsonify(results)
        except Exception as e:
            logger.error(f"dca_analysis error: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500

    @app.route("/api/long_term_analysis", methods=["GET"])
    @login_required
    def long_term_analysis_route():
        try:
            from core.long_term_analysis import analyze_long_term
            symbol = request.args.get('symbol', 'BTC/USDT').upper()
            view_range = request.args.get('range', '1Y')
            if view_range not in ('1M', '3M', '6M', '1Y', '3Y'):
                view_range = '1Y'
            result = analyze_long_term(symbol, view_range)
            return jsonify(result)
        except Exception as e:
            logger.error(f"long_term_analysis error: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500

    @app.route("/api/long_term_scan/start", methods=["POST"])
    @login_required
    def long_term_scan_start():
        try:
            import core.long_term_analysis as _lta
            force = request.json and request.json.get('force', False)
            if force:
                _lta._scan_cache = {'data': None, 'ts': 0}
            if not _lta._scan_status['running']:
                import eventlet
                eventlet.spawn(_lta.scan_top_coins_bg, 25)
            return jsonify({'started': True})
        except Exception as e:
            logger.error(f"long_term_scan_start error: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500

    @app.route("/api/long_term_scan/poll", methods=["GET"])
    @login_required
    def long_term_scan_poll():
        try:
            from core.long_term_analysis import get_scan_state
            return jsonify(get_scan_state())
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/watchlist", methods=["GET"])
    @login_required
    def watchlist_get():
        try:
            from core.long_term_analysis import get_watchlist
            return jsonify(get_watchlist())
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/watchlist", methods=["POST"])
    @login_required
    def watchlist_set():
        try:
            from core.long_term_analysis import set_watchlist
            data = request.get_json() or {}
            scanner = data.get('scanner', [])
            spot_pairs = data.get('spot_pairs', [])
            set_watchlist(scanner, spot_pairs)
            return jsonify({'ok': True})
        except Exception as e:
            logger.error(f"watchlist_set error: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500

    @app.route("/api/notify_spot_change", methods=["POST"])
    @login_required
    def notify_spot_change():
        try:
            data = request.get_json() or {}
            symbol = data.get('symbol', '')
            old_rec = data.get('old_rec', '')
            new_rec = data.get('new_rec', '')
            from modules.notification_service import notify_spot_mode_change
            notify_spot_mode_change(symbol, old_rec, new_rec)
            return jsonify({'ok': True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/set_profit_mode", methods=["POST"])
    @login_required
    def set_profit_mode():
        try:
            from core.extensions import db as _db
            from core.models import TradingPair
            data = request.get_json() or {}
            pair_id = data.get('pair_id')
            mode = data.get('profit_mode')
            if not pair_id or mode not in ('usdc', 'crypto'):
                return jsonify({"error": "Neispravan zahtjev"}), 400
            pair = TradingPair.query.get(int(pair_id))
            if not pair:
                return jsonify({"error": "Par nije pronađen"}), 404
            pair.profit_mode = mode
            _db.session.commit()
            try:
                from modules.settings import save_settings_yaml
                save_settings_yaml(current_app.config)
            except Exception as se:
                logger.warning(f"set_profit_mode: save_settings_yaml failed: {se}")
            return jsonify({"status": "ok", "symbol": pair.symbol, "profit_mode": mode})
        except Exception as e:
            logger.error(f"set_profit_mode error: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500

    @app.route("/api/stats/delete_pair", methods=["POST"])
    @login_required
    def stats_delete_pair():
        try:
            from core.extensions import db as _db
            data = request.get_json() or {}
            symbol = data.get('symbol')
            exchange = data.get('exchange')
            if not symbol or not exchange:
                return jsonify({"error": "symbol i exchange su obavezni"}), 400
            deleted = _db.session.query(ProfitLog).filter_by(symbol=symbol, exchange=exchange).delete()
            _db.session.commit()
            return jsonify({"status": "ok", "deleted": deleted})
        except Exception as e:
            logger.error(f"stats_delete_pair error: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500

    # ── Portfolio / CMC ──────────────────────────────────────────────────────
    @app.route("/portfolio")
    @login_required
    def portfolio_route():
        if "theme" not in session:
            session["theme"] = "dark"
        return render_template("portfolio.html", notifications=[])

    @app.route("/api/cmc_key", methods=["GET", "POST"])
    @login_required
    def cmc_key_route():
        import json, os
        key_file = os.path.join(os.path.dirname(__file__), '..', 'api_keys.json')
        key_file = os.path.normpath(key_file)
        try:
            with open(key_file) as f:
                keys = json.load(f)
        except Exception:
            keys = {}
        if request.method == 'GET':
            cmc = keys.get('coinmarketcap', {})
            return jsonify({"api_key": cmc.get('api_key', '')})
        data = request.get_json() or {}
        keys['coinmarketcap'] = {'api_key': data.get('api_key', '')}
        with open(key_file, 'w') as f:
            json.dump(keys, f, indent=2)
        return jsonify({"status": "ok"})

    @app.route("/api/portfolio/list")
    @login_required
    def portfolio_list():
        from core.models import Portfolio
        portfolios = Portfolio.query.order_by(Portfolio.created_at).all()
        return jsonify([{"id": p.id, "name": p.name, "threshold_pct": p.threshold_pct} for p in portfolios])

    @app.route("/api/portfolio/create", methods=["POST"])
    @login_required
    def portfolio_create():
        from core.extensions import db as _db
        from core.models import Portfolio
        data = request.get_json() or {}
        name = data.get('name', '').strip()
        if not name:
            return jsonify({"error": "Naziv je obavezan"}), 400
        p = Portfolio(name=name, threshold_pct=float(data.get('threshold_pct', 5.0)))
        _db.session.add(p)
        _db.session.commit()
        return jsonify({"id": p.id, "name": p.name, "threshold_pct": p.threshold_pct})

    @app.route("/api/portfolio/<int:pid>", methods=["DELETE"])
    @login_required
    def portfolio_delete(pid):
        from core.extensions import db as _db
        from core.models import Portfolio
        p = Portfolio.query.get(pid)
        if not p:
            return jsonify({"error": "Nije pronađen"}), 404
        _db.session.delete(p)
        _db.session.commit()
        return jsonify({"status": "ok"})

    @app.route("/api/portfolio/<int:pid>/threshold", methods=["POST"])
    @login_required
    def portfolio_threshold(pid):
        from core.extensions import db as _db
        from core.models import Portfolio
        p = Portfolio.query.get(pid)
        if not p:
            return jsonify({"error": "Nije pronađen"}), 404
        data = request.get_json() or {}
        p.threshold_pct = float(data.get('threshold_pct', 5.0))
        _db.session.commit()
        return jsonify({"status": "ok"})

    @app.route("/api/portfolio/<int:pid>/holdings")
    @login_required
    def portfolio_holdings(pid):
        from core.models import Portfolio
        p = Portfolio.query.get(pid)
        if not p:
            return jsonify({"error": "Nije pronađen"}), 404
        return jsonify([{
            "id": h.id, "symbol": h.symbol, "name": h.name,
            "amount": h.amount, "target_pct": h.target_pct,
            "include_rebalancing": h.include_rebalancing
        } for h in p.holdings])

    @app.route("/api/portfolio/<int:pid>/holding", methods=["POST"])
    @login_required
    def portfolio_add_holding(pid):
        from core.extensions import db as _db
        from core.models import Portfolio, PortfolioHolding
        p = Portfolio.query.get(pid)
        if not p:
            return jsonify({"error": "Nije pronađen"}), 404
        data = request.get_json() or {}
        symbol = data.get('symbol', '').upper().strip()
        if not symbol:
            return jsonify({"error": "Symbol je obavezan"}), 400
        existing = PortfolioHolding.query.filter_by(portfolio_id=pid, symbol=symbol).first()
        if existing:
            existing.amount = float(data.get('amount', existing.amount))
            existing.target_pct = float(data.get('target_pct', existing.target_pct))
        else:
            h = PortfolioHolding(
                portfolio_id=pid, symbol=symbol,
                name=data.get('name', symbol),
                amount=float(data.get('amount', 0)),
                target_pct=float(data.get('target_pct', 0)),
            )
            _db.session.add(h)
        _db.session.commit()
        return jsonify({"status": "ok"})

    @app.route("/api/portfolio/holding/<int:hid>", methods=["DELETE"])
    @login_required
    def portfolio_delete_holding(hid):
        from core.extensions import db as _db
        from core.models import PortfolioHolding
        h = PortfolioHolding.query.get(hid)
        if not h:
            return jsonify({"error": "Nije pronađen"}), 404
        _db.session.delete(h)
        _db.session.commit()
        return jsonify({"status": "ok"})

    @app.route("/api/portfolio/holding/<int:hid>/toggle", methods=["POST"])
    @login_required
    def portfolio_toggle_rebalancing(hid):
        from core.extensions import db as _db
        from core.models import PortfolioHolding
        h = PortfolioHolding.query.get(hid)
        if not h:
            return jsonify({"error": "Nije pronađen"}), 404
        h.include_rebalancing = not h.include_rebalancing
        _db.session.commit()
        return jsonify({"status": "ok", "include_rebalancing": h.include_rebalancing})

    @app.route("/api/portfolio/holding/<int:hid>/target", methods=["POST"])
    @login_required
    def portfolio_set_target(hid):
        from core.extensions import db as _db
        from core.models import PortfolioHolding
        h = PortfolioHolding.query.get(hid)
        if not h:
            return jsonify({"error": "Nije pronađen"}), 404
        data = request.get_json() or {}
        h.target_pct = float(data.get('target_pct', h.target_pct))
        _db.session.commit()
        return jsonify({"status": "ok"})

    @app.route("/api/portfolio/<int:pid>/upload_csv", methods=["POST"])
    @login_required
    def portfolio_upload_csv(pid):
        from core.extensions import db as _db
        from core.models import Portfolio, PortfolioHolding
        import csv, io
        p = Portfolio.query.get(pid)
        if not p:
            return jsonify({"error": "Nije pronađen"}), 404
        f = request.files.get('file')
        if not f:
            return jsonify({"error": "Fajl nije poslan"}), 400
        content = f.read().decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(content))
        headers = [h.lower().strip() for h in (reader.fieldnames or [])]

        def find_col(candidates):
            for c in candidates:
                for h in (reader.fieldnames or []):
                    if c in h.lower():
                        return h
            return None

        sym_col    = find_col(['symbol', 'ticker'])
        name_col   = find_col(['name', 'cryptocurrency', 'coin'])
        amount_col = find_col(['amount', 'holdings', 'quantity', 'balance'])

        if not sym_col or not amount_col:
            return jsonify({"error": f"Ne mogu pronaći stupce u CSV-u. Pronađeni: {reader.fieldnames}"}), 400

        added = 0
        for row in reader:
            symbol = row.get(sym_col, '').upper().strip()
            try:
                amount = float(str(row.get(amount_col, '0')).replace(',', '').strip())
            except ValueError:
                continue
            if not symbol or amount <= 0:
                continue
            name = row.get(name_col, symbol) if name_col else symbol
            existing = PortfolioHolding.query.filter_by(portfolio_id=pid, symbol=symbol).first()
            if existing:
                existing.amount = amount
                existing.name = name
            else:
                _db.session.add(PortfolioHolding(
                    portfolio_id=pid, symbol=symbol, name=name, amount=amount
                ))
            added += 1
        _db.session.commit()
        return jsonify({"status": "ok", "added": added})

    @app.route("/api/global_targets")
    @login_required
    def global_targets_list():
        from core.models import GlobalTarget
        targets = GlobalTarget.query.all()
        return jsonify({t.symbol: {"target_pct": t.target_pct, "include_rebalancing": t.include_rebalancing} for t in targets})

    @app.route("/api/global_targets/<symbol>/target", methods=["POST"])
    @login_required
    def global_target_set(symbol):
        from core.extensions import db as _db
        from core.models import GlobalTarget
        symbol = symbol.upper()
        t = GlobalTarget.query.filter_by(symbol=symbol).first()
        if not t:
            t = GlobalTarget(symbol=symbol)
            _db.session.add(t)
        data = request.get_json() or {}
        t.target_pct = float(data.get('target_pct', t.target_pct))
        _db.session.commit()
        return jsonify({"status": "ok"})

    @app.route("/api/global_targets/<symbol>/toggle", methods=["POST"])
    @login_required
    def global_target_toggle(symbol):
        from core.extensions import db as _db
        from core.models import GlobalTarget
        symbol = symbol.upper()
        t = GlobalTarget.query.filter_by(symbol=symbol).first()
        if not t:
            t = GlobalTarget(symbol=symbol, include_rebalancing=False)
            _db.session.add(t)
        else:
            t.include_rebalancing = not t.include_rebalancing
        _db.session.commit()
        return jsonify({"status": "ok", "include_rebalancing": t.include_rebalancing})

    @app.route("/api/portfolio/<int:pid>/holding/<int:hid>/amount", methods=["POST"])
    @login_required
    def portfolio_update_amount(pid, hid):
        from core.extensions import db as _db
        from core.models import PortfolioHolding
        h = PortfolioHolding.query.filter_by(id=hid, portfolio_id=pid).first()
        if not h:
            return jsonify({"error": "Nije pronađen"}), 404
        data = request.get_json() or {}
        h.amount = float(data.get('amount', h.amount))
        _db.session.commit()
        return jsonify({"status": "ok", "amount": h.amount})

    @app.route("/api/portfolio/prices")
    @login_required
    def portfolio_prices():
        import json, os, requests as req
        key_file = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'api_keys.json'))
        try:
            with open(key_file) as f:
                keys = json.load(f)
        except Exception:
            keys = {}
        api_key = keys.get('coinmarketcap', {}).get('api_key', '')
        if not api_key:
            return jsonify({"error": "CMC API ključ nije postavljen"}), 400
        symbols = request.args.get('symbols', '')
        if not symbols:
            return jsonify({})
        try:
            r = req.get(
                'https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest',
                headers={'X-CMC_PRO_API_KEY': api_key, 'Accept': 'application/json'},
                params={'symbol': symbols, 'convert': 'USD'},
                timeout=10
            )
            data = r.json()
            if 'data' not in data:
                return jsonify({"error": data.get('status', {}).get('error_message', 'CMC greška')}), 400
            prices = {}
            for sym, info in data['data'].items():
                if isinstance(info, list):
                    info = info[0]
                prices[sym] = info['quote']['USD']['price']
            return jsonify(prices)
        except Exception as e:
            logger.error(f"portfolio_prices error: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500

    # ── Email / Password reset ────────────────────────────────────────────────
    @app.route("/forgot-password", methods=["GET", "POST"])
    def forgot_password():
        if request.method == "POST":
            from modules.auth import generate_reset_token, users
            from modules.email_sender import send_email, is_configured
            if not is_configured():
                flash("Email nije konfiguriran. Kontaktiraj admina.", "danger")
                return render_template("forgot_password.html")
            # Jedan korisnik (admin) — šaljemo link bez provjere emaila
            token = generate_reset_token("admin")
            reset_url = url_for("reset_password", token=token, _external=True)
            try:
                send_email(
                    subject="CryptoBot — Reset lozinke",
                    body=f"""
                    <p>Primili smo zahtjev za reset lozinke.</p>
                    <p><a href="{reset_url}" style="font-size:1.1em;">Klikni ovdje za novu lozinku</a></p>
                    <p>Link vrijedi <strong>1 sat</strong>. Ako nisi tražio reset, ignoriraj ovaj mail.</p>
                    <br><small>CryptoBot</small>
                    """
                )
                flash("Reset link poslan na tvoj mail!", "success")
            except Exception as e:
                logger.error(f"forgot_password email error: {e}", exc_info=True)
                flash(f"Greška pri slanju maila: {e}", "danger")
            return render_template("forgot_password.html")
        return render_template("forgot_password.html")

    @app.route("/reset-password/<token>", methods=["GET", "POST"])
    def reset_password(token):
        from modules.auth import validate_reset_token, consume_reset_token
        if not validate_reset_token(token):
            flash("Link je nevažeći ili je istekao.", "danger")
            return redirect(url_for("login_route"))
        if request.method == "POST":
            new_pw = request.form.get("password", "")
            confirm_pw = request.form.get("confirm_password", "")
            if len(new_pw) < 6:
                flash("Lozinka mora imati barem 6 znakova.", "danger")
                return render_template("reset_password.html", token=token)
            if new_pw != confirm_pw:
                flash("Lozinke se ne podudaraju.", "danger")
                return render_template("reset_password.html", token=token)
            consume_reset_token(token, new_pw)
            flash("Lozinka promijenjena! Prijavi se.", "success")
            return redirect(url_for("login_route"))
        return render_template("reset_password.html", token=token)

    @app.route("/api/email_config", methods=["GET", "POST"])
    @login_required
    def email_config():
        import json, os
        key_file = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'api_keys.json'))
        try:
            with open(key_file) as f:
                keys = json.load(f)
        except Exception:
            keys = {}
        if request.method == "GET":
            cfg = keys.get("email", {})
            return jsonify({
                "gmail_address": cfg.get("gmail_address", ""),
                "gmail_app_password": cfg.get("gmail_app_password", ""),
                "admin_email": cfg.get("admin_email", ""),
            })
        data = request.get_json() or {}
        keys["email"] = {
            "gmail_address": data.get("gmail_address", ""),
            "gmail_app_password": data.get("gmail_app_password", ""),
            "admin_email": data.get("admin_email", ""),
        }
        with open(key_file, "w") as f:
            json.dump(keys, f, indent=2)
        return jsonify({"status": "ok"})

    @app.route("/api/email_test", methods=["POST"])
    @login_required
    def email_test():
        from modules.email_sender import send_email
        try:
            send_email(
                subject="CryptoBot — Test mail",
                body="<p>Test mail radi! CryptoBot email je ispravno konfiguriran.</p>"
            )
            return jsonify({"status": "ok"})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/notification_config", methods=["GET", "POST"])
    @login_required
    def notification_config():
        import json, os
        key_file = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'api_keys.json'))
        try:
            with open(key_file) as f:
                keys = json.load(f)
        except Exception:
            keys = {}
        if request.method == "GET":
            return jsonify(keys.get("notifications", {}))
        data = request.get_json() or {}
        keys["notifications"] = data
        with open(key_file, "w") as f:
            json.dump(keys, f, indent=2)
        return jsonify({"status": "ok"})

    @app.route("/toggle_theme", methods=["POST"])
    def toggle_theme_route():
        current = session.get("theme", "dark")
        session["theme"] = "light" if current == "dark" else "dark"
        return jsonify({"theme": session["theme"]})
