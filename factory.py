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
    strategy_handler.setFormatter(logging.Formatter('%(asctime)s %(message)s', datefmt='%d.%m. %H:%M'))

    # Add to Flask app's logger
    app.logger.addHandler(strategy_handler)

    with app.app_context():
        db.create_all()
        # Očisti stare ordere koji su ostali od prethodnog procesa (VPS restart, crash)
        try:
            from core.models import Order
            from core.extensions import db as _db
            stale = Order.query.all()
            if stale:
                for o in stale:
                    _db.session.delete(o)
                _db.session.commit()
                logging.getLogger(__name__).info(f"Startup: obrisano {len(stale)} starih ordera iz baze")
        except Exception as e:
            logging.getLogger(__name__).warning(f"Startup: nije mogao obrisati stare ordere: {e}")

    # Pokreni dnevni cleanup TradeLog zapisa starijih od 30 dana
    _start_trade_cleanup(app)

    # Pokreni notification checker i pošalji server restart notifikaciju
    try:
        from modules.notification_service import start_notification_checker, notify_server_restart
        start_notification_checker(app)
        threading.Thread(target=lambda: (time.sleep(5), notify_server_restart()), daemon=True).start()
    except Exception as e:
        logging.getLogger(__name__).warning(f"Notification checker nije pokrenut: {e}")

    # Pokreni periodički scanner svake 4 sata (long-term analiza)
    _start_periodic_scanner(app)

    # Auto-start botova koji su bili aktivni prije restarta
    _auto_start_bots(app)

    return app


def _auto_start_bots(app):
    """Pri pokretanju servera automatski pokreni sve parove koji su imali auto_start=True."""
    def _start():
        time.sleep(10)  # Čekaj da se Flask i DB potpuno podigne
        with app.app_context():
            try:
                from core.models import TradingPair
                from core.config import load_config
                from modules.bot_control import bot_manager, control_bot
                from modules.utils import load_api_keys

                config = load_config()
                pairs = TradingPair.query.filter_by(auto_start=True).all()
                if not pairs:
                    return

                log = logging.getLogger(__name__)
                log.info(f"Auto-start: pronađeno {len(pairs)} par(ova) za pokretanje")

                _exchange_defaults = {'binance': 0.001, 'bybit': 0.001, 'gateio': 0.002, 'bitmart': 0.002}
                _api_keys = load_api_keys()

                for pair in pairs:
                    try:
                        if bot_manager.is_running(pair.id):
                            continue
                        _fee_rate = _api_keys.get(pair.exchange, {}).get(
                            'fee_rate', _exchange_defaults.get(pair.exchange, 0.001))
                        pair_config = {
                            "id": pair.id,
                            "symbol": pair.symbol,
                            "exchange": pair.exchange,
                            "amount": pair.amount,
                            "buy_percentage": pair.buy_percentage,
                            "sell_percentage": pair.sell_percentage,
                            "trading_mode": pair.trading_mode or config.get('trading_mode', 'testnet'),
                            "profit_mode": pair.profit_mode or 'usdc',
                            "fee_rate": _fee_rate,
                        }
                        bot_manager.start_bot(pair.id, pair.symbol, pair_config, config, app)
                        log.info(f"Auto-start: {pair.symbol} ({pair.exchange}) pokrenut")
                        time.sleep(2)  # Mali razmak između pokretanja više parova
                    except Exception as e:
                        logging.getLogger(__name__).error(f"Auto-start greška za {pair.symbol}: {e}", exc_info=True)
            except Exception as e:
                logging.getLogger(__name__).error(f"Auto-start inicijalizacija greška: {e}", exc_info=True)

    threading.Thread(target=_start, daemon=True, name='auto-start-bots').start()


def _start_periodic_scanner(app):
    """Pokretanje long-term scanera svake 4 sata u pozadini."""
    INTERVAL = 4 * 60 * 60

    def loop():
        time.sleep(60)  # Čekaj da se app podigne
        while True:
            try:
                import core.long_term_analysis as _lta
                _lta.scan_top_coins_bg(25, notify_changes=True)
                logging.getLogger(__name__).info("Periodički scanner završio")
            except Exception as e:
                logging.getLogger(__name__).warning(f"Periodički scanner greška: {e}")
            time.sleep(INTERVAL)

    t = threading.Thread(target=loop, daemon=True, name='periodic-scanner')
    t.start()
    logging.getLogger(__name__).info("Periodički scanner pokrenut (svake 4h)")


def _cleanup_old_trades(app):
    """Briše TradeLog zapise starije od 30 dana. Čuva buyeve bez sell-a (otvorene pozicije)."""
    from datetime import datetime, timedelta
    from core.models import TradeLog
    from core.extensions import db as _db

    cutoff = datetime.utcnow() - timedelta(days=30)
    log = logging.getLogger(__name__)

    try:
        with app.app_context():
            # Simboli koji imaju nedavne sellove (ciklus završen) — stari buyevi se mogu brisati
            recent_sell_symbols = {
                r.symbol for r in
                _db.session.query(TradeLog.symbol)
                .filter(TradeLog.side == 'sell', TradeLog.timestamp >= cutoff)
                .distinct().all()
            }

            # Briši sve sellove starije od 30 dana (već u ProfitLog-u)
            deleted_sells = TradeLog.query.filter(
                TradeLog.side == 'sell',
                TradeLog.timestamp < cutoff
            ).delete(synchronize_session=False)

            # Briši stare buyeve samo za simbole koji aktivno cikliraju
            deleted_buys = 0
            if recent_sell_symbols:
                deleted_buys = TradeLog.query.filter(
                    TradeLog.side == 'buy',
                    TradeLog.timestamp < cutoff,
                    TradeLog.symbol.in_(recent_sell_symbols)
                ).delete(synchronize_session=False)

            _db.session.commit()
            if deleted_sells or deleted_buys:
                log.info(f"TradeLog cleanup: obrisano {deleted_sells} sellova + {deleted_buys} buyeva starijih od 30 dana")
    except Exception as e:
        log.warning(f"TradeLog cleanup greška: {e}")
        try:
            with app.app_context():
                _db.session.rollback()
        except Exception:
            pass


def _start_trade_cleanup(app):
    """Pokreće dnevni cleanup u background threadu."""
    INTERVAL = 24 * 60 * 60  # jednom dnevno

    def loop():
        while True:
            time.sleep(INTERVAL)
            _cleanup_old_trades(app)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    logging.getLogger(__name__).info("TradeLog cleanup: pokrenut, izvršava se jednom dnevno")

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
