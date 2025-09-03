import threading
from contextlib import nullcontext
from core.models import Position, TradingPair
from flask import request, jsonify
from core.exchange import ExchangeConnector
from core.portfolio import PortfolioManager
from core.order import OrderManager
from core.tradelog import TradeLogger
from core.profit_tracker import ProfitTracker
from modules.notifications import add_notification
from modules.utils import get_pairs, load_api_keys, calculate_profit
from modules.exchange_config import ExchangeConfig
from core.extensions import db
from flask import current_app

profit_tracker = ProfitTracker()
portfolio = PortfolioManager(profit_tracker=profit_tracker)
order_mgr = OrderManager()
trade_logger = TradeLogger()



class BotManager:
    """Minimal manager tracking running bot threads."""

    def __init__(self):
        # Maps ``pair_id`` -> thread/running flag
        self.bot_threads: dict[int, threading.Thread] = {}
        self.bot_running: dict[int, bool] = {}
        self.lock = threading.RLock()

    def is_running(self, pair_id: int) -> bool:
        """Return ``True`` if the bot thread for ``pair_id`` is active."""
        with self.lock:
            return self.bot_running.get(pair_id, False)

    def stop_bot(self, pair_id: int) -> None:
        """Stop and clean up the bot thread for ``pair_id``."""
        with self.lock:
            self.bot_running[pair_id] = False
            thread = self.bot_threads.pop(pair_id, None)

        if thread:
            thread.join(timeout=5)

        pair = TradingPair.query.get(pair_id)
        if pair:
            try:
                # Ensure order_mgr is accessible, it's a global in this module
                order_mgr.cancel_orders(pair.symbol)
            except Exception as e:
                # Log this error
                current_app.logger.error(f"Error cancelling orders for {pair.symbol} during stop_bot: {e}", exc_info=True)



    def start_bot(self, pair_id: int, symbol: str, pair_config: dict, app_config, flask_app_instance) -> bool:
        """Starts a bot for the given pair_id if not already running."""
        with self.lock:
            if self.is_running(pair_id): # Check using instance's state
                return False # Already running

            self.bot_running[pair_id] = True
            thread = threading.Thread(
                target=run_bot, # run_bot is a global function in this module
                args=(symbol, pair_config, app_config, flask_app_instance, pair_id, self), # Pass self (BotManager instance)
                daemon=True,
            )
            self.bot_threads[pair_id] = thread
            thread.start()
            return True


def run_bot(symbol, pair_config, config, app=None, pair_id=None, bot_manager_instance=None):  # Added bot_manager_instance
    """Run the trading loop for ``symbol`` using ``config`` settings."""

    context = app.app_context() if app else nullcontext()
    with context:
        from main import trade_loop  # Imported here to avoid circular import
        trading_mode = pair_config.get('trading_mode', config.get('trading_mode', 'testnet'))
        # Determine if testnet mode is applicable for ExchangeConfig.setup_exchange
        # It's testnet if mode is 'testnet'. ExchangeConfig handles Binance-specific URLs.
        is_testnet_mode_for_config = (trading_mode == 'testnet')

        # Use ExchangeConfig to get standardized parameters
        # api_keys_override can be passed if api_keys were loaded once and passed down,
        # otherwise ExchangeConfig.setup_exchange will call load_api_keys() itself.
        # For simplicity here, assuming ExchangeConfig calls load_api_keys.
        exchange_id, ccxt_params = ExchangeConfig.setup_exchange(
            pair_config['exchange'],
            is_testnet=is_testnet_mode_for_config
        )

        # Create connector using the new signature
        exchange = ExchangeConnector(exchange_id, params=ccxt_params)

        try:
            trade_loop(
                symbol,
                pair_config,
                exchange,
                portfolio,
                order_mgr,
                trade_logger,
                profit_tracker,
                pair_id,
            )
            calculate_profit(exchange, trading_mode, symbol)
            profit = profit_tracker.get_symbol_profit(symbol)
            if profit >= 10.0:
                add_notification(symbol, f'High profit trade for {symbol}: {profit:.2f} USDC', 'success')
            elif profit <= -10.0:
                add_notification(symbol, f'Significant loss for {symbol}: {profit:.2f} USDC', 'error')
            add_notification(symbol, f'Trade cycle completed for {symbol}', 'success')
        except Exception as e:
            add_notification(symbol, f'Error: {str(e)}', 'error')
        finally:
            if pair_id is not None and bot_manager_instance is not None:
                # Update state via the BotManager instance
                with bot_manager_instance.lock:
                    bot_manager_instance.bot_running[pair_id] = False
                    bot_manager_instance.bot_threads.pop(pair_id, None)
            try:
                order_mgr.cancel_orders(symbol) # order_mgr is global
            except Exception as e:
                # Log this error
                if app: # if app context is available for logger
                    app.logger.error(f"Error cancelling orders for {symbol} at end of run_bot: {e}", exc_info=True)


def control_bot(config, app=None): # app is the flask_app_instance
    # No more global bot_threads, bot_running. Use bot_manager instance.
    action = request.json.get('action')
    pair_id_raw = request.json.get('pair_id')
    try:
        pair_id = int(pair_id_raw) if pair_id_raw is not None else None
    except (TypeError, ValueError):
        return jsonify({'status': 'Invalid pair'}), 400

    pair = TradingPair.query.get(pair_id) if pair_id is not None else None

    if not pair:
        return jsonify({'status': 'Invalid pair_id provided.', 'pair_id': pair_id_raw, 'bot_is_running': False}), 400

    symbol = pair.symbol
    # pairs_data = get_pairs() # Not strictly needed here if pair_config comes from 'pair' object

    if action == 'start':
        if bot_manager.is_running(pair_id):
            return jsonify({'status': f'Bot for {symbol} is already running.', 'pair_id': pair_id, 'bot_is_running': True})

        # Construct pair_config from the 'pair' object fetched from DB
        pair_config = {
            "id": pair.id,
            "symbol": pair.symbol,
            "exchange": pair.exchange,
            "amount": pair.amount,
            "buy_percentage": pair.buy_percentage,
            "sell_percentage": pair.sell_percentage,
            "trading_mode": getattr(pair, "trading_mode", config.get('trading_mode', 'testnet')),
            "profit_mode": getattr(pair, "profit_mode", 'usdc'),
        }
        app_obj = app or current_app._get_current_object() # Ensure we have a Flask app instance

        if bot_manager.start_bot(pair_id, symbol, pair_config, config, app_obj):
            return jsonify({'status': f'Bot started for {symbol} on {pair.exchange}.', 'pair_id': pair_id, 'bot_is_running': True})
        else:
            # This case should ideally be caught by is_running above, but as a fallback:
            return jsonify({'status': f'Bot for {symbol} could not be started (possibly already running).', 'pair_id': pair_id, 'bot_is_running': bot_manager.is_running(pair_id)})

    elif action == 'stop':
        if not bot_manager.is_running(pair_id):
            return jsonify({'status': f'Bot for {symbol} is not running.', 'pair_id': pair_id, 'bot_is_running': False})

        bot_manager.stop_bot(pair_id)
        # Position cleanup logic - ensure db and portfolio are accessible
        try:
            with (app or current_app._get_current_object()).app_context():
                position = Position.query.filter_by(symbol=symbol).first()
                if position:
                    db.session.delete(position)
                    db.session.commit()
                    portfolio._load_positions() # portfolio is a global
        except Exception as e:
            current_app.logger.error(f"Error during position cleanup for {symbol} on stop: {e}", exc_info=True)
            # Decide if this should make the overall stop action fail

        return jsonify({'status': f'Bot stopped for {symbol} on {pair.exchange}.', 'pair_id': pair_id, 'bot_is_running': False})

    else:
        return jsonify({'status': f'Invalid action: {action}.', 'pair_id': pair_id, 'bot_is_running': bot_manager.is_running(pair_id)}), 400

bot_manager = BotManager()
# Remove global aliases:
# bot_threads = bot_manager.bot_threads
# bot_running = bot_manager.bot_running
