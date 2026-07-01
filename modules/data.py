import pandas as pd
from core.models import Position, ProfitLog, TradeLog, PairProfit, TradingPair
from flask import jsonify, session
from modules.bot_control import portfolio, order_mgr, profit_tracker
from modules.utils import get_price, get_pairs, load_api_keys
from core.exchange import ExchangeConnector
from modules.exchange_config import ExchangeConfig # Added import
from concurrent.futures import ThreadPoolExecutor
import logging
from sqlalchemy import func
from core.extensions import db # Added import


logger = logging.getLogger(__name__)

# Ensure ExchangeConfig is imported if not already at the top of the file
# from modules.exchange_config import ExchangeConfig

_internal_connectors_data_py: dict[tuple[str, str], ExchangeConnector] = {}  # Renamed to avoid conflict if utils._connectors is accessed

def reset_cached_connectors() -> None:
    """Clear cached connectors maintained by this module."""
    _internal_connectors_data_py.clear()

def _get_connector_data_py(exchange_name: str, mode: str, api_keys_data: dict) -> ExchangeConnector:
    """
    Gets a cached ExchangeConnector instance, specific to modules/data.py.
    Uses ExchangeConfig for setup.
    """
    # Ensure mode is 'real' if testnet is requested for non-Binance exchanges
    if exchange_name != "binance" and mode == "testnet":
        mode = "real"

    key = (exchange_name, mode)
    connector = _internal_connectors_data_py.get(key)

    if connector is None:
        try:
            # Use ExchangeConfig to get standardized parameters
            # Pass api_keys_data for ExchangeConfig to use
            exchange_id, ccxt_params = ExchangeConfig.setup_exchange(
                exchange_name,
                is_testnet=(mode == "testnet"),
                api_keys_override=api_keys_data # Important: pass the loaded keys
            )
            connector = ExchangeConnector(exchange_id, params=ccxt_params)
            _internal_connectors_data_py[key] = connector
        except Exception as e:
            logger.error(f"Failed to create connector for {exchange_name} ({mode}) in data.py: {e}", exc_info=True)
            raise # Or handle more gracefully depending on requirements
    return connector


# Modified signature to accept app_instance and bot_manager_instance
def get_data(config, bot_running, app_instance, bot_manager_instance):
    base_currency = session.get("base_currency", "USDC")
    all_pairs_data = get_pairs() # Load all pairs once for active_pairs calculation

    data = {
        "prices": {},
        "portfolio": {
            p.symbol: {"amount": p.amount, "buy_price": p.buy_price}
            for p in Position.query.all()
        },
        "orders": {},
        "total_profit": profit_tracker.get_total_profit(), # This is global total profit
        "active_pairs": sum(1 for pair_id in bot_running if bot_running[pair_id]), # This is global active pairs
        "trade_status": {
            pair["symbol"]: bool(bot_running.get(pair["id"]))
            for pair in all_pairs_data # Use all_pairs_data here
        },
        "account_info": {},  # This will be populated with detailed info
    }
    # Prikaži ordere samo za parove koji trenutno rade
    running_symbols = {
        pair['symbol']
        for pair in all_pairs_data
        if bot_manager_instance.is_running(pair['id'])
    }
    for order in order_mgr.get_orders():
        if order.symbol in running_symbols:
            data["orders"].setdefault(order.symbol, {})[order.side] = {
                "price": round(order.price, 8),
                "amount": round(order.amount, 8),
                "order_id": order.order_id,
                "exchange": order.exchange,
            }


    api_keys = load_api_keys()
    # exchanges list is implicitly defined by tasks below

    data["account_info"] = {}

    # This worker function now fetches balance, P&L, and active pairs per exchange/mode
    def fetch_exchange_details(args):
        ex_name, mode_str = args
        # api_keys, base_currency, all_pairs_data, bot_manager_instance, app_instance are from outer scope

        balance_display_value = "N/A"
        pnl_for_exchange_mode = 0.0
        active_pairs_count = 0

        currency_to_fetch = base_currency
        if ex_name.lower() == 'bitmart':
            currency_to_fetch = 'USDT'

        # Fetch Balance
        try:
            connector = _get_connector_data_py(ex_name, mode_str, api_keys_data=api_keys)
            raw_balance = connector.get_balance(currency_to_fetch)
            if raw_balance == "AUTH_ERROR":
                balance_display_value = "AUTH ERROR"
            elif raw_balance is None:
                balance_display_value = "N/A"
            elif isinstance(raw_balance, (int, float)):
                balance_display_value = f"{raw_balance:.2f}"
            else:
                logger.error(f"Unexpected balance type for {ex_name} ({mode_str}) in get_data worker: {raw_balance} (type: {type(raw_balance)})")
                balance_display_value = "Invalid Data"
        except RuntimeError:
             balance_display_value = "SETUP ERROR"
        except Exception as e:
            logger.error(f"Failed to fetch balance for {ex_name} {mode_str} in get_data worker: {e}", exc_info=True)
            balance_display_value = "ERROR"

        # Calculate P&L
        try:
            with app_instance.app_context():
                pnl_usdc, pnl_crypto = db.session.query(
                    func.sum(PairProfit.profit_usdc),
                    func.sum(PairProfit.profit_crypto)
                ).filter(
                    PairProfit.exchange == ex_name,
                    PairProfit.trading_mode == mode_str
                ).first()
                pnl_for_exchange_mode = {
                    "usdc": round(pnl_usdc or 0.0, 2),
                    "crypto": round(pnl_crypto or 0.0, 6)
                }
        except Exception as e:
            logger.error(
                f"Error calculating P&L for {ex_name} ({mode_str}) in get_data worker: {e}",
                exc_info=True,
            )
            pnl_for_exchange_mode = {"usdc": "Error", "crypto": "Error"}

        # Calculate Active Pairs for this exchange/mode
        try:
            relevant_pairs = [
                p for p in all_pairs_data
                if p['exchange'].lower() == ex_name.lower() and p['trading_mode'].lower() == mode_str.lower()
            ]
            active_pairs_count = sum(1 for p in relevant_pairs if bot_manager_instance.is_running(p['id']))
        except Exception as e:
            logger.error(f"Error calculating active pairs for {ex_name} ({mode_str}) in get_data worker: {e}", exc_info=True)
            active_pairs_count = "Error"

        return ex_name, mode_str, {
            "balance": balance_display_value,
            "pnl": pnl_for_exchange_mode,
            "active_pairs": active_pairs_count
        }

    tasks = [
        ("binance", "testnet"),
        ("binance", "real"),
        ("bybit", "real"),
        ("gateio", "real"),
        ("bitmart", "real"),
    ]

    with ThreadPoolExecutor(max_workers=5) as exc:
        results = list(exc.map(fetch_exchange_details, tasks))

    for ex_name, mode_str, details_dict in results:
        data["account_info"][f"{ex_name}_{mode_str}"] = details_dict

    pairs = all_pairs_data # Use already fetched all_pairs_data

    def fetch_price(pair):
        symbol = pair["symbol"]
        mode = pair.get("trading_mode", "testnet")
        try:
            price = get_price(pair["exchange"], symbol, mode)
        except ValueError as e:
            logger.warning(str(e))
            return symbol, "N/A"
        return symbol, price

    if pairs:
        with ThreadPoolExecutor(max_workers=min(5, len(pairs))) as exc:
            for symbol, price in exc.map(fetch_price, pairs):
                data["prices"][symbol] = price if price != "N/A" else "N/A"
    return jsonify(data)


def get_account_balances() -> dict:
    """Return current balances for configured exchanges as a dict."""
    base_currency = session.get("base_currency", "USDC")
    api_keys = load_api_keys()

    def fetch_balance(args: tuple[str, str]):
        ex_name, mode = args
        keys = api_keys.get(ex_name, {}).get(mode, {})
        configured = bool(keys.get("api_key")) and "your_" not in keys.get(
            "api_key", ""
        )
        if not configured:
            return ex_name, mode, "NO API KEY"
        ex = _get_connector(
            mode,
            ex_name,
            keys.get("api_key"),
            keys.get("secret_key"),
            keys.get("uid"),
        )
        bal = ex.get_balance(base_currency)
        if bal == "AUTH_ERROR":
            return ex_name, mode, "FIX API PERMISION"
        return ex_name, mode, bal if bal is not None else "N/A"

    tasks = [
        ("binance", "testnet"),
        ("binance", "real"),
        ("bybit", "real"),
        ("gateio", "real"),
        ("bitmart", "real"),
    ]

    balances: dict[str, str | float] = {}
    with ThreadPoolExecutor(max_workers=5) as exc:
        for ex_name, mode, bal in exc.map(fetch_balance, tasks):
            balances[f"{ex_name}_{mode}"] = bal

    return balances


# This function seems unused. Dashboard home() route fetches balances directly.
# /api/data also fetches balances inline.
# def get_account_balances() -> dict:
#     """Return current balances for configured exchanges as a dict."""
#     base_currency = session.get("base_currency", "USDC")
#     api_keys = load_api_keys()

#     def fetch_balance(args: tuple[str, str]):
#         ex_name, mode = args
#         keys = api_keys.get(ex_name, {}).get(mode, {})
#         configured = bool(keys.get("api_key")) and "your_" not in keys.get(
#             "api_key", ""
#         )
#         if not configured:
#             return ex_name, mode, "NO API KEY"
#         ex = _get_connector_data_py( # Assuming _get_connector_data_py is the updated one
#             ex_name,
#             mode,
#             api_keys_data=api_keys
#         )
#         bal = ex.get_balance(base_currency)
#         if bal == "AUTH_ERROR":
#             return ex_name, mode, "AUTH ERROR" # Consistent error message
#         return ex_name, mode, bal if bal is not None else "N/A"

#     tasks = [
#         ("binance", "testnet"),
#         ("binance", "real"),
#         ("bybit", "real"),
#         ("gateio", "real"),
#         ("bitmart", "real"),
#     ]

#     balances: dict[str, str | float] = {}
#     with ThreadPoolExecutor(max_workers=5) as exc:
#         for ex_name, mode, bal in exc.map(fetch_balance, tasks):
#             balances[f"{ex_name}_{mode}"] = bal
#     return balances


def get_profit_data():
    try:
        # Fetch and sort all profit logs
        logs = ProfitLog.query.order_by(ProfitLog.timestamp).all()

        if not logs:
            return jsonify({"timestamps": [], "profits": []})

        # Build a DataFrame
        df = pd.DataFrame(
            [
                {"timestamp": log.timestamp, "profit_usdt": log.profit_usdt}
                for log in logs
            ]
        )

        df_grouped = df.groupby("timestamp")["profit_usdt"].sum().reset_index()
        df_grouped["cumulative_profit"] = df_grouped["profit_usdt"].cumsum()

        return jsonify(
            {
                "timestamps": df_grouped["timestamp"].astype(str).tolist(),
                "profits": df_grouped["cumulative_profit"].tolist(),
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def get_trade_data():
    """
    Fetches trades that are considered 'open'.
    An open trade is a 'buy' for a symbol that has not subsequently been 'sold'.
    This implementation assumes that any 'sell' of a symbol closes out prior 'buys' for that symbol.
    Optimized to reduce fetching all trade objects if TradeLog is large.
    """
    try:
        # 1. Get all unique symbols that have at least one 'sell' record.
        sold_symbols_query = db.session.query(TradeLog.symbol).filter(TradeLog.side == 'sell').distinct()
        closed_symbols = {result[0] for result in sold_symbols_query.all()}

        # 2. Fetch all 'buy' trades for symbols that are NOT in the set of closed_symbols.
        # These are considered to have open positions.
        # Add order_by if a specific order is needed, e.g., latest first.
        open_trades_query = TradeLog.query.filter(
            TradeLog.side == 'buy',
            ~TradeLog.symbol.in_(closed_symbols)
        ).order_by(TradeLog.timestamp.desc()) # Example: get latest open buys first

        # If you expect multiple open 'buy' trades for the same symbol, use .all()
        # If only the latest 'buy' for a symbol that isn't sold is considered "the open trade",
        # further logic would be needed (e.g. group by symbol, take max timestamp).
        # The original logic implies any buy for a symbol not in closed_symbols is open.
        open_trades = open_trades_query.all()

        # Deduplicate if multiple buys for the same symbol are fetched by query above
        # and we only want to show one "open position" per symbol based on the latest buy.
        # The original logic would list all such buys. Let's stick to that for now.
        # If we wanted only the latest open buy per symbol:
        # seen_symbols_for_open_trades = set()
        # unique_open_trades = []
        # for trade in open_trades: # Assuming ordered by timestamp desc
        #    if trade.symbol not in seen_symbols_for_open_trades:
        #        unique_open_trades.append(trade)
        #        seen_symbols_for_open_trades.add(trade.symbol)
        # open_trades = unique_open_trades


        return [
            {
                "timestamp": trade.timestamp.isoformat(),
                "symbol": trade.symbol,
                "exchange": trade.exchange,
                "side": trade.side,
                "price": trade.price,
                "amount": trade.amount,
                "usdt_value": trade.usdt_value,
                "status": "open",  # Add status for clarity
            }
            for trade in open_trades
        ]

    except Exception as e:
        raise RuntimeError(f"Trade query failed: {e}")


def get_open_positions():
    """Return a list of open buy positions with unrealized P/L."""
    try:
        trades = TradeLog.query.order_by(TradeLog.timestamp).all()
        grouped: dict[tuple[str, str, str], list[TradeLog]] = {}
        for t in trades:
            key = (t.symbol, t.exchange, t.trading_mode)
            grouped.setdefault(key, []).append(t)

        positions = []
        for (symbol, exchange, mode), tlist in grouped.items():
            pair = TradingPair.query.filter_by(symbol=symbol, exchange=exchange, trading_mode=mode).first()
            profit_mode = pair.profit_mode if pair else 'usdc'

            queue: list[list[float]] = []  # [qty, price]
            for tr in tlist:
                if tr.side.lower() == "buy":
                    queue.append([tr.amount, tr.price])
                elif tr.side.lower() == "sell":
                    qty = tr.amount
                    while qty > 0 and queue:
                        buy_qty, buy_price = queue[-1]
                        if buy_qty <= qty + 1e-8:
                            qty -= buy_qty
                            queue.pop()
                        else:
                            queue[-1][0] = buy_qty - qty
                            qty = 0

            if not queue:
                continue

            current_price = get_price(exchange, symbol, mode)
            if current_price == "N/A":
                current_price = None

            for qty, buy_price in queue:
                if qty < 0.00001:  # skip floating-point dust from partial fills
                    continue
                pnl = None
                if current_price is not None:
                    pnl = (current_price - buy_price) * qty
                positions.append(
                    {
                        "symbol": symbol,
                        "exchange": exchange,
                        "trading_mode": mode,
                        "buy_price": buy_price,
                        "quantity": qty,
                        "current_price": current_price,
                        "current_pnl": pnl,
                        "profit_mode": profit_mode
                    }
                )
        return positions
    except Exception as e:
        logger.error("Failed to compute open positions: %s", e, exc_info=True)
        return []


def clear_open_positions(symbol: str, exchange: str, mode: str | None = None) -> bool:
    """Delete open buy trades for a given symbol/exchange (and optional mode)."""
    try:
        query = TradeLog.query.filter_by(symbol=symbol, exchange=exchange)
        if mode:
            query = query.filter_by(trading_mode=mode)
        trades = query.order_by(TradeLog.timestamp).all()

        queue: list[tuple[TradeLog, float]] = []
        for tr in trades:
            if tr.side.lower() == "buy":
                queue.append((tr, tr.amount))
            elif tr.side.lower() == "sell":
                qty = tr.amount
                while qty > 0 and queue:
                    buy_tr, buy_qty = queue[0]
                    if buy_qty <= qty + 1e-8:
                        qty -= buy_qty
                        queue.pop(0)
                    else:
                        queue[0] = (buy_tr, buy_qty - qty)
                        qty = 0

        for buy_tr, _ in queue:
            db.session.delete(buy_tr)
        db.session.commit()
        return True
    except Exception as e:  # pragma: no cover - DB issues
        logger.error("Failed to clear open positions: %s", e, exc_info=True)
        db.session.rollback()
        return False
