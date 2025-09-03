# core/routes.py

from flask import render_template, request, jsonify, session, send_file, flash, current_app
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


from core.models import ProfitLog  # Added for P&L calculation
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

    @app.route("/settings", methods=["GET", "POST"])
    @login_required
    def settings_route():
        return settings()

    @app.route("/api/update_general", methods=["POST"])
    def api_update_general_route():
        return api_update_general(app.config)

    @app.route("/api/update_pairs", methods=["POST"])
    def api_update_pairs_route():
        return api_update_pairs()

    @app.route("/api/add_pair", methods=["POST"])
    def api_add_pair_route():
        return api_add_pair()

    @app.route("/api/remove_pair", methods=["POST"])
    def api_remove_pair_route():
        return api_remove_pair()

    @app.route("/api/exchange_pairs")
    def api_exchange_pairs_route():
        ex = request.args.get("exchange", "binance")
        mode = current_app.config.get("trading_mode", "testnet")
        return jsonify({"pairs": get_exchange_pairs(ex, mode)})

    @app.route("/api/update_api_keys", methods=["POST"])
    def api_update_api_keys_route():
        return api_update_api_keys()

    @app.route("/api/change_password", methods=["POST"])
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

            profit_entries_query = ProfitLog.query

            if timeframe != 'all':
                days_map = {
                    'day': 1,
                    'week': 7,
                    'month': 30
                }
                days = days_map.get(timeframe)
                if days:
                    cutoff = datetime.utcnow() - timedelta(days=days)
                    profit_entries_query = profit_entries_query.filter(ProfitLog.timestamp >= cutoff)

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

    @app.route("/toggle_theme", methods=["POST"])
    def toggle_theme_route():
        current = session.get("theme", "dark")
        session["theme"] = "light" if current == "dark" else "dark"
        return jsonify({"theme": session["theme"]})
