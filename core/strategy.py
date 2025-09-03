# core/strategy.py
import logging

logger = logging.getLogger(__name__) # Get a logger instance for this module

class TradingStrategy:
    def __init__(self, exchange, config):
        self.exchange = exchange
        self.symbol = config['symbol']
        self.buy_pct = config['buy_percentage'] # This seems to be for the *next* buy, not initial.
        self.sell_pct = config['sell_percentage']
        self.amount = config['amount'] # This is the quote amount (e.g. USDT) for the initial buy

    def execute_cycle(self):
        # 1. Get current price (optional, as market_buy might get it, but good for logging)
        current_price = self.exchange.get_price(self.symbol)
        if current_price:
            logger.info(f"Current price for {self.symbol}: {current_price}")
        else:
            logger.warning(f"Could not retrieve current price for {self.symbol} before attempting buy.")

        # 2. Market Buy
        order = self.exchange.market_buy(self.symbol, self.amount)

        if order is None:
            logger.error(f"Market buy order failed for {self.symbol} with amount {self.amount}. No response from exchange.")
            return # Skip further processing in this cycle

        if isinstance(order, dict) and order.get('error') == 'INSUFFICIENT_FUNDS':
            alert_message = (
                f"[ALERT] Not enough balance to trade {order['symbol']} on {order['exchange']} "
                f"(needed: {order['required']:.2f}, available: {order['available']:.2f})"
            )
            logger.warning(alert_message) # Use warning or error level for alerts
            return # Skip further processing in this cycle

        # Check for other potential errors if market_buy could return other dicts for errors
        if isinstance(order, dict) and 'error' in order:
            logger.error(f"Market buy for {self.symbol} failed with error: {order.get('error_message', order['error'])}")
            return

        # Assuming successful order if we reach here and 'id' is present
        if not isinstance(order, dict) or 'order_id' not in order:
            logger.error(f"Market buy order for {self.symbol} did not return a valid order ID. Response: {order}")
            return

        buy_price = order.get('average')
        filled_amount_base = order.get('filled')

        if not buy_price or not filled_amount_base:
            logger.error(f"Market buy order for {self.symbol} executed but did not return 'average' price or 'filled' amount. Order: {order}")
            # Potentially check order status here or just return
            return

        logger.info(f"Market buy for {self.symbol} successful. Price: {buy_price}, Filled: {filled_amount_base} {self.symbol.split('/')[0]}. Order ID: {order['order_id']}")

        # 3. Place limit sell using configured sell percentage
        sell_price = buy_price * (1 + self.sell_pct / 100)
        # Ensure sell_price is formatted to exchange precision if necessary, or place_limit_order handles it
        logger.info(f"Calculated sell price for {self.symbol}: {sell_price}")

        sell_order = self.exchange.place_limit_order(self.symbol, "sell", sell_price, filled_amount_base)
        if sell_order and sell_order.get('order_id'):
            logger.info(f"Limit sell order placed for {self.symbol} at {sell_price:.4f}, Amount: {filled_amount_base}. Order ID: {sell_order['order_id']}")
        else:
            logger.error(f"Failed to place limit sell order for {self.symbol} at {sell_price:.4f}. Response: {sell_order}")
            # Decide if we should stop or try to place the next buy. For now, let's stop.
            return

        # 4. Place limit buy using configured buy percentage (relative to the recent buy_price)
        # The logic for 'next_buy_price' might need review based on strategy goals.
        # If buy_pct is a discount from current buy_price: buy_price * (1 - self.buy_pct / 100)
        # If it's an increment for a higher re-entry (less common for immediate next step): buy_price * (1 + self.buy_pct / 100)
        # Assuming buy_pct is a percentage *lower* than the price just bought at, for a dip.
        next_buy_price_target = buy_price * (1 - self.buy_pct / 100) # Example: buy_pct=1 means 1% lower
        logger.info(f"Calculated next buy price for {self.symbol}: {next_buy_price_target}")

        # The amount for the next buy order should be based on the initial quote currency amount (self.amount)
        # This assumes the strategy is to reinvest the same quote amount.
        next_buy_order = self.exchange.place_limit_order(self.symbol, "buy", next_buy_price_target, self.amount, params={'type': 'limit', 'cost': self.amount})
        # Note: CCXT's place_limit_order typically takes (symbol, side, amount_base, price).
        # If we want to place a limit buy with a specific *quote* amount (self.amount),
        # we might need to calculate the base amount at next_buy_price_target, or check if exchange supports quote amount for limit orders.
        # For simplicity, let's assume self.amount is quote and we need to calculate base for limit order:

        # Re-calculate base amount for the next limit buy order if price is available
        if next_buy_price_target > 0:
            amount_for_next_buy_base = self.amount / next_buy_price_target
            logger.info(f"Calculated base amount for next limit buy of {self.symbol}: {amount_for_next_buy_base} at price {next_buy_price_target}")

            next_buy_order_response = self.exchange.place_limit_order(self.symbol, "buy", next_buy_price_target, amount_for_next_buy_base)
            if next_buy_order_response and next_buy_order_response.get('order_id'):
                logger.info(f"Next limit buy order placed for {self.symbol} at {next_buy_price_target:.4f}, Base Amount: {amount_for_next_buy_base}. Order ID: {next_buy_order_response['order_id']}")
            else:
                logger.error(f"Failed to place next limit buy order for {self.symbol} at {next_buy_price_target:.4f}. Response: {next_buy_order_response}")
        else:
            logger.error(f"Could not place next limit buy order for {self.symbol} due to invalid next_buy_price_target: {next_buy_price_target}")
