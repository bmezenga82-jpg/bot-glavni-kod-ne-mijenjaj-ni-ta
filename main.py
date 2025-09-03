import time
import logging
from datetime import datetime
from core.config import load_config
from core.exchange import ExchangeConnector
from modules.utils import get_pairs, load_api_keys
from core.portfolio import PortfolioManager
from core.order import OrderManager
from core.tradelog import TradeLogger
from core.profit_tracker import ProfitTracker
from modules.notifications import add_notification

logger = logging.getLogger(__name__)
from core.backtester import run_backtest

"""Main trading loop used by the bot threads."""


def trade_loop(
    symbol,
    settings,
    exchange,
    portfolio,
    order_mgr,
    trade_logger,
    profit_tracker,
    pair_id,
):
    """Execute trades for a single symbol until stopped via ``bot_control``."""
    from modules.bot_control import bot_manager

    usdc_amount = settings['amount']
    sell_pct = settings['sell_percentage']
    buy_pct = abs(settings['buy_percentage'])
    profit_mode = settings.get('profit_mode', 'usdc')

    buy_order_id: str | None = None
    # Use a list to track multiple sell orders
    sell_orders = []

    def cancel_all_orders():
        """Cancels all open orders for the symbol and resets local state."""
        nonlocal buy_order_id
        if buy_order_id:
            exchange.cancel_order(buy_order_id, symbol)
            buy_order_id = None
        for order in sell_orders:
            exchange.cancel_order(order['id'], symbol)
        sell_orders.clear()
        order_mgr.cancel_orders(symbol)

    # Clean up any lingering orders before starting
    cancel_all_orders()

    while bot_manager.is_running(pair_id):
        try:
            time.sleep(5)

            # Check status of sell orders
            for sell_order in sell_orders[:]:  # Iterate over a copy
                status = exchange.check_order_status(sell_order['id'], symbol)
                if status['status'] == 'closed':
                    price = sell_order['price']
                    qty = sell_order['amount']
                    retained_qty = sell_order.get('retained_qty', 0.0)

                    logger.info(
                        f"Sold {qty} at {price} — Retained {retained_qty} (Mode: {profit_mode})"
                    )

                    # Record the sell
                    portfolio.record_sell(
                        symbol,
                        price,
                        qty,
                        sell_order['buy_price'],
                        exchange=settings['exchange'],
                        trading_mode=settings['trading_mode'],
                        pair_id=pair_id,
                        retained_qty=retained_qty,
                        profit_mode=profit_mode,
                    )
                    trade_logger.log(
                        symbol,
                        'sell',
                        price,
                        qty,
                        settings.get('exchange', 'binance'),
                        settings.get('trading_mode', 'testnet'),
                    )

                    # Remove from active sell orders
                    sell_orders.remove(sell_order)
                    order_mgr.cancel_orders(symbol, order_id=sell_order['id'])

                    # If a buy order is active, cancel it
                    if buy_order_id:
                        logger.info(f"Attempting to cancel buy order {buy_order_id} after sell.")
                        exchange.cancel_order(buy_order_id, symbol)
                        order_mgr.cancel_orders(symbol, side='buy')
                        buy_order_id = None
                        logger.info(f"Canceled buy order after sell.")

                    if sell_orders:
                        # More sells remain -> place next buy 1% below this sell price
                        new_buy_price = price * (1 - buy_pct / 100)
                        new_buy_qty = usdc_amount / new_buy_price
                        new_buy_order = exchange.place_limit_order(symbol, 'buy', new_buy_price, new_buy_qty)
                        if new_buy_order and 'order_id' in new_buy_order:
                            buy_order_id = new_buy_order['order_id']
                            order_mgr.set_order(
                                symbol,
                                'buy',
                                new_buy_price,
                                new_buy_qty,
                                buy_order_id,
                                exchange=settings['exchange'],
                            )
                            logger.info(
                                f"Placed new buy order {buy_order_id} at {new_buy_price}."
                            )
                    else:
                        # Last sell filled -> wait for cycle restart at loop end
                        logger.info(
                            f"All sell orders filled for {symbol}. Preparing to restart cycle."
                        )

                elif status['status'] in ('canceled', 'not_found'):
                    sell_orders.remove(sell_order)
                    order_mgr.cancel_orders(symbol, order_id=sell_order['id'])


            # Check status of the buy order
            if buy_order_id:
                status = exchange.check_order_status(buy_order_id, symbol)
                if status['status'] == 'closed':
                    buy_price = order_mgr.get_order(symbol, 'buy').price
                    qty = status.get('filled', order_mgr.get_order(symbol, 'buy').amount)

                    logger.info(f"Buy order {buy_order_id} for {qty} {symbol} at {buy_price} filled.")

                    portfolio.record_buy(symbol, usdc_amount, buy_price)
                    trade_logger.log(
                        symbol,
                        'buy',
                        buy_price,
                        qty,
                        settings.get('exchange', 'binance'),
                        settings.get('trading_mode', 'testnet'),
                    )

                    # Cancel previous buy order from manager and set new one
                    order_mgr.cancel_orders(symbol, side='buy')

                    # Place a new sell order for this buy
                    sell_price = buy_price * (1 + sell_pct / 100)
                    if profit_mode == 'crypto':
                        sell_qty = min(qty, usdc_amount / sell_price)
                        retained_qty = max(0.0, qty - sell_qty)
                    else:
                        sell_qty = qty
                        retained_qty = 0.0
                    sell_qty = round(sell_qty, 6)
                    retained_qty = round(retained_qty, 6)
                    sell_order = exchange.place_limit_order(symbol, 'sell', sell_price, sell_qty)
                    if sell_order and 'order_id' in sell_order:
                        sell_order_id = sell_order['order_id']
                        sell_orders.append({'id': sell_order_id, 'price': sell_price, 'amount': sell_qty, 'buy_price': buy_price, 'retained_qty': retained_qty})
                        order_mgr.set_order(symbol, 'sell', sell_price, sell_qty, sell_order_id, exchange=settings['exchange'])
                        logger.info(f"Placed new sell order {sell_order_id} for {sell_qty} at {sell_price}. Retained {retained_qty} (Mode: {profit_mode})")

                    # Place the next buy order
                    next_buy_price = buy_price * (1 - buy_pct / 100)
                    next_buy_qty = usdc_amount / next_buy_price
                    new_buy_order = exchange.place_limit_order(symbol, 'buy', next_buy_price, next_buy_qty)
                    if new_buy_order and 'order_id' in new_buy_order:
                        buy_order_id = new_buy_order['order_id']
                        order_mgr.set_order(symbol, 'buy', next_buy_price, next_buy_qty, buy_order_id, exchange=settings['exchange'])
                        logger.info(f"Placed next buy order {buy_order_id} at {next_buy_price}.")
                    else:
                        buy_order_id = None # Ensure buy_order_id is cleared if order fails

                elif status['status'] in ('canceled', 'not_found'):
                    buy_order_id = None


            # Initial start of the bot or restart after all sells are filled
            if not buy_order_id and not sell_orders:
                logger.info(f"Starting new cycle for {symbol}.")

                # Ensure any leftover orders are cleared before starting a new cycle
                cancel_all_orders()

                # Market buy to start the cycle
                market_order = exchange.market_buy(symbol, usdc_amount)
                if not market_order or 'average' not in market_order:
                    logger.error("Market buy failed or did not return expected data.")
                    continue

                price = market_order['average']
                qty = market_order['filled']

                portfolio.record_buy(symbol, usdc_amount, price)
                trade_logger.log(
                    symbol,
                    'buy',
                    price,
                    qty,
                    settings.get('exchange', 'binance'),
                    settings.get('trading_mode', 'testnet'),
                )

                # Place initial sell order
                sell_price = price * (1 + sell_pct / 100)
                if profit_mode == 'crypto':
                    sell_qty = min(qty, usdc_amount / sell_price)
                    retained_qty = max(0.0, qty - sell_qty)
                else:
                    sell_qty = qty
                    retained_qty = 0.0
                sell_qty = round(sell_qty, 6)
                retained_qty = round(retained_qty, 6)
                sell = exchange.place_limit_order(symbol, 'sell', sell_price, sell_qty)
                if sell and 'order_id' in sell:
                    sell_order_id = sell['order_id']
                    sell_orders.append({'id': sell_order_id, 'price': sell_price, 'amount': sell_qty, 'buy_price': price, 'retained_qty': retained_qty})
                    order_mgr.set_order(symbol, 'sell', sell_price, sell_qty, sell_order_id, exchange=settings['exchange'])

                # Place initial buy order
                buy_price = price * (1 - buy_pct / 100)
                next_qty = usdc_amount / buy_price
                buy = exchange.place_limit_order(symbol, 'buy', buy_price, next_qty)
                if buy and 'order_id' in buy:
                    buy_order_id = buy['order_id']
                    order_mgr.set_order(symbol, 'buy', buy_price, next_qty, buy_order_id, exchange=settings['exchange'])

            portfolio.print_status()
            order_mgr.print_orders()

        except KeyboardInterrupt:
            logger.info("Bot for %s stopped manually", symbol)
            break
        except Exception as e:
            logger.error("Unexpected error in %s loop: %s", symbol, e)
# The main() function and its __main__ guard appear to be unused legacy code.
# The application is launched via app.py (Flask/SocketIO) and bots are controlled
# via the BotManager and API calls.
# def main():
#     logger.info("CryptoBot initializing...")

#     config = load_config()
#     api_keys = load_api_keys()
#     profit_tracker = ProfitTracker()
#     portfolio = PortfolioManager(profit_tracker=profit_tracker)
#     order_mgr = OrderManager()
#     trade_logger = TradeLogger()

#     pairs = get_pairs()
#     if 'backtest' in config and config['backtest']:
        
#         run_backtest(pairs)
#         return

#     if 'pairs' not in config:
#         logger.error("No trading pairs defined in config.yaml.")
#         return

#     for pair_config in pairs:
#         symbol = pair_config['symbol']
#         mode = pair_config.get('trading_mode', config.get('trading_mode', 'testnet'))
#         exchange = ExchangeConnector( # This would also need updating to new constructor style if used
#             pair_config['exchange'],
#             api_keys.get(pair_config['exchange'], {}).get(mode, {}).get('api_key'),
#             api_keys.get(pair_config['exchange'], {}).get(mode, {}).get('secret_key'),
#             sandbox=(mode == 'testnet')
#         )
#         trade_loop(
#             symbol,
#             pair_config,
#             exchange,
#             portfolio,
#             order_mgr,
#             trade_logger,
#             profit_tracker,
#             pair_config.get('id'),
#         )

# if __name__ == "__main__":
#     main()
