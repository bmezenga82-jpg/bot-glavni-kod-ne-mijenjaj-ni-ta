import os
import json
import logging
from core.models import TradingPair
from core.extensions import db
from sqlalchemy.exc import IntegrityError
from core.config import load_config
from core.exchange import ExchangeConnector
from modules.exchange_config import ExchangeConfig # Added import
import yaml
from modules.notifications import notifications, save_notifications

config = load_config()

logger = logging.getLogger(__name__)

# Global connector and market cache
_connectors: dict[tuple[str, str], ExchangeConnector] = {}
_cached_markets: dict[tuple[str, str], dict] = {}
# _warned_modes = set() # Moved to key_loader.py


# def load_api_keys(): # Moved to key_loader.py
#    ... (old function content removed) ...

# Import load_api_keys from its new location
from modules.key_loader import load_api_keys


def reset_connectors() -> None:
    """Clear cached exchange connectors and markets."""
    _connectors.clear()
    _cached_markets.clear()


def _get_connector(exchange: str, mode: str) -> ExchangeConnector:
    """Return a cached :class:`ExchangeConnector` for ``exchange`` and ``mode``."""
    if exchange != "binance" and mode == "testnet":
        mode = "real"
    key = (exchange, mode)
    # Ensure ExchangeConfig is imported if not already. Assuming it's available in the scope.
    # from modules.exchange_config import ExchangeConfig # Make sure this import is present at the top of utils.py

    connector = _connectors.get(key)
    if connector is None:
        try:
            # Use ExchangeConfig to get standardized parameters
            # load_api_keys() is called by ExchangeConfig if override is not provided
            exchange_id, ccxt_params = ExchangeConfig.setup_exchange(exchange, is_testnet=(mode == "testnet"))
            connector = ExchangeConnector(exchange_id, params=ccxt_params)
            _connectors[key] = connector
        except Exception as e:
            logger.error(f"Failed to create connector for {exchange} ({mode}): {e}", exc_info=True)
            # Decide how to handle this: raise, return None, or return a dummy/non-functional connector
            # For now, let's re-raise to make it visible, or the caller (get_price) will fail.
            raise
    return connector


def save_api_keys(api_keys):
    with open('api_keys.json', 'w') as f:
        json.dump(api_keys, f, indent=2)


def get_exchange_pairs(exchange_name: str, mode: str | None = None):
    """Return a sorted list of active spot trading pairs for ``exchange_name``.

    Parameters
    ----------
    exchange_name : str
        Name of the exchange.
    mode : str | None, optional
        ``"testnet"`` or ``"real"``. Defaults to the configured ``trading_mode``.
    """
    exchange_name = exchange_name.lower()
    mode = (mode or config.get("trading_mode", "testnet")).lower()

    connector = _get_connector(exchange_name, mode)
    key = (exchange_name, mode)

    if key not in _cached_markets:
        try:
            _cached_markets[key] = connector.exchange.load_markets()
        except Exception as e:
            logger.error("Error fetching %s (%s) pairs: %s", exchange_name, mode, str(e))
            return []

    markets = _cached_markets[key]
    return sorted([
        symbol for symbol, market in markets.items() if market.get("active") and market.get("spot")
    ])


# This function seems unused. Generic get_exchange_pairs is used.
# def get_binance_pairs(mode: str | None = None):
#     """Backwards compatible helper for Binance pairs."""
#     return get_exchange_pairs("binance", mode)


# This function seems unused. Generic get_price is used.
# def get_binance_price(symbol, mode: str | None = None):
#     """Backwards compatible helper for Binance price."""
#     return get_price("binance", symbol, mode)


def get_price(
    exchange_name: str, symbol: str, mode: str | None = None
):
    """Fetch the latest price for ``symbol`` from ``exchange_name``.

    Parameters
    ----------
    exchange_name : str
        Name of the exchange.
    symbol : str
        Trading pair symbol, e.g. ``"BTC/USDT"``.
    mode : str | None, optional
        ``"testnet"`` or ``"real"``. Defaults to the configured ``trading_mode``.
    """
    exchange_name = exchange_name.lower()
    mode = (mode or config.get("trading_mode", "testnet")).lower()

    connector = _get_connector(exchange_name, mode)
    key = (exchange_name, mode)

    available = get_exchange_pairs(exchange_name, mode)
    if symbol not in available:
        raise ValueError(
            f"{symbol} is not available on {exchange_name} in {mode} mode"
        )

    if key not in _cached_markets:
        try:
            _cached_markets[key] = connector.exchange.load_markets()
        except Exception as e:
            logger.error("Error loading %s (%s) markets: %s", exchange_name, mode, str(e))
            return "N/A"

    markets = _cached_markets[key]
    if symbol not in markets:
        logger.warning("Symbol not found in %s markets: %s", exchange_name, symbol)
        return "N/A"

    try:
        ticker = connector.exchange.fetch_ticker(symbol)
        return ticker.get("last", "N/A")
    except Exception as e:
        logger.error("Error fetching price for %s on %s (%s): %s", symbol, exchange_name, mode, str(e))
        return "N/A"


def get_binance_price(symbol, mode: str | None = None):
    """Backwards compatible helper for Binance price."""
    return get_price("binance", symbol, mode)



def seed_default_pairs_if_empty():
    if TradingPair.query.count() == 0:
        default_pairs_data = [
            {
                "symbol": "SUI/USDC",
                "amount": 6.0,
                "buy_percentage": -1.0,
                "sell_percentage": 0.5,
                "exchange": "binance",
                "trading_mode": "testnet",
                "profit_mode": "usdc",
            },
            {
                "symbol": "SUI/USDC",
                "amount": 6.0,
                "buy_percentage": -1.0,
                "sell_percentage": 0.5,
                "exchange": "bybit",
                "trading_mode": "real",
                "profit_mode": "usdc",
            },
            {
                "symbol": "SUI/USDC",
                "amount": 6.0,
                "buy_percentage": -1.0,
                "sell_percentage": 0.5,
                "exchange": "gateio",
                "trading_mode": "real",
                "profit_mode": "usdc",
            },
            {
                "symbol": "SUI/USDT",
                "amount": 6.0,
                "buy_percentage": -1.0,
                "sell_percentage": 0.5,
                "exchange": "bitmart",
                "trading_mode": "real",
                "profit_mode": "usdc",
            },
        ]
        default_pairs = []
        for pair in default_pairs_data:
            # Skip if pair already exists for this exchange
            if TradingPair.query.filter_by(symbol=pair["symbol"], exchange=pair["exchange"]).first():
                continue

            available = get_exchange_pairs(pair["exchange"], pair.get("trading_mode", "testnet"))
            if pair["symbol"] not in available:
                logger.warning(
                    "Skipping %s on %s (%s): pair not available",
                    pair["symbol"],
                    pair["exchange"],
                    pair.get("trading_mode", "testnet"),
                )
                continue
            default_pairs.append(
                TradingPair(
                    symbol=pair["symbol"],
                    exchange=pair["exchange"],
                    amount=pair["amount"],
                    buy_percentage=pair["buy_percentage"],
                    sell_percentage=pair["sell_percentage"],
                    trading_mode=pair.get("trading_mode", "testnet"),
                    profit_mode=pair.get("profit_mode", "usdc"),
                )
            )

        if default_pairs:
            try:
                db.session.bulk_save_objects(default_pairs)
                db.session.commit()
            except IntegrityError:
                db.session.rollback()

            for pair in default_pairs:
                notifications[pair.symbol] = []
            save_notifications(notifications)

def get_pairs():
    seed_default_pairs_if_empty()
    
    try:
        db_pairs = TradingPair.query.all()
        return [
            {
                "id": pair.id,
                "symbol": pair.symbol,
                "exchange": pair.exchange,
                "amount": pair.amount,
                "buy_percentage": pair.buy_percentage,
                "sell_percentage": pair.sell_percentage,
                "trading_mode": getattr(pair, "trading_mode", "testnet"),
                "profit_mode": getattr(pair, "profit_mode", "usdc"),
                "drop_alert_enabled": getattr(pair, "drop_alert_enabled", False),
                "drop_alert_pct": getattr(pair, "drop_alert_pct", 55.0),
                "drop_alert_auto": getattr(pair, "drop_alert_auto", False),
            }
            for pair in db_pairs
        ]
    except Exception as e:
        logger.warning("Failed to fetch trading pairs from DB: %s", e)
        for cfg_file in ("settings.yaml", "config.yaml"):
            try:
                with open(cfg_file, "r") as file:
                    config = yaml.safe_load(file) or {}
                    if "pairs" in config:
                        return config["pairs"]
            except Exception:
                continue
        logger.error("Failed to load config fallback")
        return []


def calculate_profit(exchange, mode, symbol):
    """Calculate profit by summing trade history."""
    try:
        trades = exchange.fetch_my_trades(symbol=symbol)
        total_buy = 0
        total_sell = 0
        for t in trades:
            qty = float(t['amount'])
            price = float(t['price'])
            usdc_value = qty * price
            if t['side'] == 'buy':
                total_buy += usdc_value
            elif t['side'] == 'sell':
                total_sell += usdc_value

        profit = total_sell - total_buy
        logger.info(
            "%s - Profit Summary for %s: BUY %.2f USDC, SELL %.2f USDC, Net %.2f USDC",
            mode.upper(),
            symbol,
            total_buy,
            total_sell,
            profit,
        )
    except Exception as e:
        logger.error("%s - Profit Calc Error: %s", mode.upper(), e)
