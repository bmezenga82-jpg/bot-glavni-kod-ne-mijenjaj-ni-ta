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
    fee_rate = settings.get('fee_rate', 0.001)

    buy_order_id: str | None = None
    sell_orders = []
    processed_sell_ids: set = set()  # guard against double-processing the same fill

    def reload_settings():
        """Reload mutable trading parameters from DB (hot config update)."""
        try:
            from core.models import TradingPair
            from core.extensions import db as _db
            pair_db = TradingPair.query.get(pair_id)
            if pair_db:
                return (
                    pair_db.amount,
                    pair_db.sell_percentage,
                    abs(pair_db.buy_percentage),
                    pair_db.profit_mode,
                )
        except Exception as e:
            logger.warning(f"reload_settings failed for pair {pair_id}: {e}")
            try:
                from core.extensions import db as _db
                _db.session.rollback()
            except Exception:
                pass
        return usdc_amount, sell_pct, buy_pct, profit_mode

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

    # Recovery: provjeri exchange za postojeće ordere — nastavi od tuda umjesto svježeg starta
    recovered = False
    try:
        open_orders = exchange.exchange.fetch_open_orders(symbol)
        ex_sells = [o for o in open_orders if o['side'] == 'sell']
        ex_buys  = [o for o in open_orders if o['side'] == 'buy']

        if ex_sells or ex_buys:
            for o in ex_sells:
                implied_buy = o['price'] / (1 + sell_pct / 100)
                # U crypto modu rekonstruiraj retained_qty: ukupna qty pri implied_buy minus sell qty
                if profit_mode == 'crypto':
                    estimated_total_qty = usdc_amount / implied_buy
                    rec_retained = max(0.0, round(estimated_total_qty - o['amount'], 8))
                else:
                    rec_retained = 0.0
                sell_orders.append({
                    'id': o['id'],
                    'price': o['price'],
                    'amount': o['amount'],
                    'buy_price': implied_buy,
                    'retained_qty': rec_retained,
                    'profit_mode': profit_mode,
                })
                order_mgr.set_order(symbol, 'sell', o['price'], o['amount'], o['id'], exchange=settings['exchange'])
            if ex_buys:
                b = ex_buys[0]
                buy_order_id = b['id']
                order_mgr.set_order(symbol, 'buy', b['price'], b['amount'], b['id'], exchange=settings['exchange'])

            # Provjeri jesu li se buy orderi ispunili dok je bot bio dole (zadnjih 10 min)
            try:
                since_ms = int((time.time() - 600) * 1000)
                recent_trades = exchange.exchange.fetch_my_trades(symbol, since=since_ms)
                open_sell_prices = {o['price'] for o in ex_sells}
                for t in recent_trades:
                    if t['side'] != 'buy' or not t.get('amount', 0):
                        continue
                    expected_sell = t['price'] * (1 + sell_pct / 100)
                    # Provjeri je li ovaj buy već pokriven sell orderom
                    already_covered = any(
                        abs(sp - expected_sell) / expected_sell < 0.002
                        for sp in open_sell_prices
                    )
                    if not already_covered:
                        new_sell = exchange.place_limit_order(symbol, 'sell', expected_sell, t['amount'])
                        if new_sell and 'order_id' in new_sell:
                            if profit_mode == 'crypto':
                                est_total = usdc_amount / t['price']
                                dt_retained = max(0.0, round(est_total - t['amount'], 8))
                            else:
                                dt_retained = 0.0
                            sell_orders.append({
                                'id': new_sell['order_id'],
                                'price': expected_sell,
                                'amount': t['amount'],
                                'buy_price': t['price'],
                                'retained_qty': dt_retained,
                                'profit_mode': profit_mode,
                            })
                            order_mgr.set_order(symbol, 'sell', expected_sell, t['amount'], new_sell['order_id'], exchange=settings['exchange'])
                            open_sell_prices.add(expected_sell)
                            logger.info(f"[RECOVERY] Sell postavljen za buy ispunjen u downtime: {t['amount']} @ {expected_sell:.4f}")
                            add_notification(symbol, f"Recovery: sell za downtime buy ({t['amount']:.5f} @ {expected_sell:.4f})", 'success')
            except Exception as e:
                logger.warning(f"[RECOVERY] Nije mogao provjeriti downtime fillove: {e}")

            # Ako imamo sell ordere ali nema aktivnog buy ordera → postavi buy ispod najnižeg sella
            if sell_orders and not buy_order_id:
                try:
                    lowest_sell = min(sell_orders, key=lambda o: o['price'])
                    new_buy_price = lowest_sell['price'] * (1 - buy_pct / 100)
                    new_buy_qty = usdc_amount / new_buy_price
                    new_buy = exchange.place_limit_order(symbol, 'buy', new_buy_price, new_buy_qty)
                    if new_buy and 'order_id' in new_buy:
                        buy_order_id = new_buy['order_id']
                        order_mgr.set_order(symbol, 'buy', new_buy_price, new_buy_qty, buy_order_id, exchange=settings['exchange'])
                        logger.info(f"[RECOVERY] {symbol}: buy postavljen @ {new_buy_price:.4f} ispod najnižeg sella @ {lowest_sell['price']:.4f}")
                        add_notification(symbol, f"Recovery: buy @ {new_buy_price:.4f} (ispod sella @ {lowest_sell['price']:.4f})", 'success')
                except Exception as e:
                    logger.warning(f"[RECOVERY] Nije mogao postaviti buy u recovery: {e}")

            # Rekonstruiraj TradeLog pozicije ako su obrisane (npr. Clear positions)
            # ali sell orderi i dalje postoje na burzi
            if sell_orders:
                try:
                    from core.models import TradeLog as _TL
                    from sqlalchemy import func as _func
                    buy_count  = _TL.query.filter_by(symbol=symbol, side='buy').count()
                    sell_count = _TL.query.filter_by(symbol=symbol, side='sell').count()
                    # Ako nema niti jednog buy zapisa (ili su svi već pokriti sellovima) → dodaj sintetičke
                    if buy_count <= sell_count:
                        for order in sell_orders:
                            trade_logger.log(
                                symbol, 'buy',
                                order['buy_price'], order['amount'],
                                settings['exchange'], settings.get('trading_mode', 'testnet'),
                            )
                        logger.info(f"[RECOVERY] {symbol}: dodano {len(sell_orders)} sintetičkih buy zapisa u TradeLog")
                        add_notification(symbol, f"Recovery: rekonstruirane pozicije ({len(sell_orders)} sell ordera)", 'info')
                except Exception as e:
                    logger.warning(f"[RECOVERY] Nije mogao rekonstruirati TradeLog pozicije: {e}")

            recovered = True
            add_notification(symbol, f"Recovery: nastavljam s {len(sell_orders)} sell + {len(ex_buys)} buy ordera", 'success')
            logger.info(f"[RECOVERY] {symbol}: {len(sell_orders)} sell, {len(ex_buys)} buy — nastavlja bez market buy")
    except Exception as e:
        logger.warning(f"[RECOVERY] {symbol}: nije mogao dohvatiti ordere, svježi start ({e})")

    if not recovered:
        cancel_all_orders()

    while bot_manager.is_running(pair_id):
        try:
            time.sleep(5)

            # Hot reload: apply any settings changes saved from the dashboard
            usdc_amount, sell_pct, buy_pct, profit_mode = reload_settings()

            # Check status of sell orders
            for sell_order in sell_orders[:]:  # Iterate over a copy
                status = exchange.check_order_status(sell_order['id'], symbol)
                if status['status'] in ('closed', 'filled'):
                    if sell_order['id'] in processed_sell_ids:
                        logger.warning(f"Sell {sell_order['id']} already processed — skipping duplicate")
                        sell_orders.remove(sell_order)
                        continue
                    processed_sell_ids.add(sell_order['id'])
                    price = sell_order['price']
                    qty = sell_order['amount']
                    retained_qty = sell_order.get('retained_qty', 0.0)
                    order_profit_mode = sell_order.get('profit_mode', profit_mode)

                    logger.info(
                        f"Sold {qty} at {price} — Retained {retained_qty} (Mode: {order_profit_mode})"
                    )

                    # Svaki korak je nezavisan — pad jednog ne smije blokirati ostale
                    try:
                        portfolio.record_sell(
                            symbol, price, qty, sell_order['buy_price'],
                            exchange=settings['exchange'],
                            trading_mode=settings['trading_mode'],
                            pair_id=pair_id,
                            retained_qty=retained_qty,
                            profit_mode=order_profit_mode,
                            fee_rate=fee_rate,
                        )
                    except Exception as e:
                        logger.error(f"record_sell failed for {symbol}: {e}", exc_info=True)

                    try:
                        trade_logger.log(
                            symbol, 'sell', price, qty,
                            settings.get('exchange', 'binance'),
                            settings.get('trading_mode', 'testnet'),
                        )
                    except Exception as e:
                        logger.error(f"trade_logger.log sell failed for {symbol}: {e}", exc_info=True)

                    # Cleanup uvijek mora proći
                    sell_orders.remove(sell_order)
                    try:
                        order_mgr.cancel_orders(symbol, order_id=sell_order['id'])
                    except Exception as e:
                        logger.error(f"order_mgr.cancel_orders sell failed for {symbol}: {e}", exc_info=True)

                    # If a buy order is active, cancel it
                    if buy_order_id:
                        logger.info(f"Attempting to cancel buy order {buy_order_id} after sell.")
                        try:
                            exchange.cancel_order(buy_order_id, symbol)
                            order_mgr.cancel_orders(symbol, side='buy')
                            logger.info(f"Canceled buy order after sell.")
                        except Exception as e:
                            logger.error(f"Failed to cancel buy {buy_order_id} after sell: {e}", exc_info=True)
                        finally:
                            buy_order_id = None

                    if sell_orders:
                        # More sells remain -> place next buy sell_pct% below this sell price
                        # (avoids echo/duplicate sells near existing open orders)
                        new_buy_price = price * (1 - sell_pct / 100)
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
                if status['status'] in ('closed', 'filled'):
                    buy_record = order_mgr.get_order(symbol, 'buy')
                    buy_price = buy_record.price if buy_record else None
                    qty = status.get('filled') or (buy_record.amount if buy_record else 0)

                    if not buy_price:
                        logger.error(f"Buy fill detected for {symbol} but no buy record found — skipping")
                        buy_order_id = None
                    else:
                        logger.info(f"Buy order {buy_order_id} for {qty} {symbol} at {buy_price} filled.")

                        try:
                            portfolio.record_buy(symbol, usdc_amount, buy_price)
                        except Exception as e:
                            logger.error(f"record_buy failed for {symbol}: {e}", exc_info=True)

                        try:
                            trade_logger.log(
                                symbol, 'buy', buy_price, qty,
                                settings.get('exchange', 'binance'),
                                settings.get('trading_mode', 'testnet'),
                            )
                        except Exception as e:
                            logger.error(f"trade_logger.log buy failed for {symbol}: {e}", exc_info=True)

                        # Cleanup uvijek mora proći
                        try:
                            order_mgr.cancel_orders(symbol, side='buy')
                        except Exception as e:
                            logger.error(f"order_mgr.cancel_orders buy failed for {symbol}: {e}", exc_info=True)

                        # Place a new sell order for this buy
                        sell_price = buy_price * (1 + sell_pct / 100)
                        if profit_mode == 'crypto':
                            sell_qty = min(qty, usdc_amount / sell_price)
                            retained_qty = max(0.0, qty - sell_qty)
                        else:
                            sell_qty = qty
                            retained_qty = 0.0
                        sell_qty = round(sell_qty, 8)
                        retained_qty = round(retained_qty, 8)
                        sell_order = exchange.place_limit_order(symbol, 'sell', sell_price, sell_qty)
                        if sell_order and 'order_id' in sell_order:
                            sell_order_id = sell_order['order_id']
                            sell_orders.append({'id': sell_order_id, 'price': sell_price, 'amount': sell_qty, 'buy_price': buy_price, 'retained_qty': retained_qty, 'profit_mode': profit_mode})
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
                            buy_order_id = None

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
                sell_qty = round(sell_qty, 8)
                retained_qty = round(retained_qty, 8)
                sell = exchange.place_limit_order(symbol, 'sell', sell_price, sell_qty)
                if sell and 'order_id' in sell:
                    sell_order_id = sell['order_id']
                    sell_orders.append({'id': sell_order_id, 'price': sell_price, 'amount': sell_qty, 'buy_price': price, 'retained_qty': retained_qty, 'profit_mode': profit_mode})
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
            try:
                from modules.notification_service import notify_bot_error
                notify_bot_error(symbol, settings.get('exchange', ''), str(e))
            except Exception:
                pass
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
