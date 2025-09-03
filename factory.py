import os
import threading
import time
import logging
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, session, render_template, jsonify, request, current_app
from flask_socketio import SocketIO
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv
from core.extensions import db, migrate
from core.config import load_config
from modules.auth import load_user
from modules.utils import get_price, get_pairs
# Import get_buffered_strategy_logs globally
from core.logging_handlers import get_buffered_strategy_logs

socketio = SocketIO()
login_manager = LoginManager()
bcrypt = Bcrypt()

connected_clients = set()

def create_app():
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s - %(message)s')

    # Suppress Werkzeug's standard INFO logs (HTTP requests)
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.setLevel(logging.ERROR)

    app = Flask(__name__)
    app.secret_key = os.getenv('FLASK_SECRET_KEY', 'default_secret_key')

    config = load_config()
    app.config.update(config)

    # Init extensions
    db.init_app(app)
    migrate.init_app(app, db)
    socketio.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'login_route'
    bcrypt.init_app(app)

    # Import models so they’re registered
    from core import models

    # Register blueprints or routes here
    from core.routes import register_routes
    register_routes(app)

    # Initialize StrategyLogHandler with SocketIO instance
    # Note: get_buffered_strategy_logs is now imported globally, so it's available here too
    from core.logging_handlers import initialize_socketio_for_logging, StrategyLogHandler
    initialize_socketio_for_logging(socketio)

    # Configure a specific logger for strategy logs or add handler to root/app logger
    strategy_handler = StrategyLogHandler()
    strategy_handler.setLevel(logging.INFO) # Capture INFO and above for strategy logs

    # Add to Flask app's logger
    app.logger.addHandler(strategy_handler)

    with app.app_context():
        db.create_all()

    return app

@socketio.on('request_initial_strategy_logs')
def handle_request_initial_strategy_logs():
    """Sends the current buffer of strategy logs to the requesting client."""
    logs = get_buffered_strategy_logs()
    for log_entry in logs:
        socketio.emit('live_strategy_log', {'data': log_entry}, room=request.sid)

@login_manager.user_loader
def user_loader(username):
    return load_user(username)

PRICE_UPDATE_INTERVAL = 3  # seconds
PAIR_REFRESH_INTERVAL = 60  # seconds

def stream_prices(app):
    """Background task that emits price updates to connected clients."""
    from modules.utils import get_price  # Local import keeps startup fast
    from modules.bot_control import bot_manager

    # Initial pair load requires an application context
    with app.app_context():
        pairs = get_pairs()

    last_refresh = time.time()

    while connected_clients:
        with app.app_context():
            # Refresh trading pairs periodically to catch changes from settings
            if time.time() - last_refresh > PAIR_REFRESH_INTERVAL:
                pairs = get_pairs()
                last_refresh = time.time()

            prices: dict[str, float | str] = {}
            status: dict[str, bool] = {}

            def fetch(pair):
                symbol = pair['symbol']
                mode = pair.get('trading_mode', 'testnet')
                price_to_set = "N/A"
                current_exchange_name = pair['exchange']
                try:
                    if current_exchange_name.lower() != "binance" and mode == "testnet":
                        mode = "real"
                    price_to_set = get_price(current_exchange_name, symbol, mode)
                except ValueError as e:
                    app.logger.warning(
                        f"ValueError fetching price for {symbol} on {current_exchange_name} ({mode}): {str(e)}")
                except Exception as e:
                    app.logger.error(
                        f"Unexpected error fetching price for {symbol} on {current_exchange_name} ({mode}): {str(e)}",
                        exc_info=True)

                running = bot_manager.is_running(pair['id'])
                return symbol, price_to_set, running

            with ThreadPoolExecutor(max_workers=min(10, len(pairs) or 1)) as exc:
                for symbol, price, running in exc.map(fetch, pairs):
                    prices[symbol] = price
                    status[symbol] = running

            socketio.emit(
                'price_update',
                {'prices': prices, 'trade_status': status},
                namespace='/'
            )

        time.sleep(PRICE_UPDATE_INTERVAL)

@socketio.on('connect')
def handle_connect(auth=None):
    from flask_login import current_user # Keep local as it's specific to this function

    if current_user.is_authenticated and current_user.id not in connected_clients:
        connected_clients.add(current_user.id)
        if len(connected_clients) == 1:
            app = current_app._get_current_object()
            threading.Thread(target=stream_prices, args=(app,), daemon=True).start()
    else:
        msg = "unauthenticated user" if not current_user.is_authenticated else "duplicate connection"
        logging.info("Socket connection ignored: %s", msg)

@socketio.on('disconnect')
def handle_disconnect():
    from flask_login import current_user # Keep local
    if current_user.is_authenticated:
        connected_clients.discard(current_user.id)
