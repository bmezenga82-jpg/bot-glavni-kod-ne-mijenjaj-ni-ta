from enum import Enum, auto
from logger import strategy_logger # Use the globally configured logger
import mock_exchange as exchange

# Give the mock_exchange our logger instance
exchange.set_logger(strategy_logger)

class StrategyState(Enum):
    IDLE = auto()          # Strategy is inactive or just initialized for a pair.
    MARKET_BUYING = auto() # Initial market buy is in progress.
    BOUGHT_WAITING_ORDERS = auto() # Market buy complete, placing initial limit sell & limit buy.
    WAITING_SELL_AND_BUY = auto() # Initial orders placed, waiting for either to fill.
    BUY_FILLED_PROCESSING = auto() # A limit buy filled, processing new orders.
    SELL_FILLED_PROCESSING = auto() # A limit sell filled, processing new orders or restart.
    FULLY_SOLD_CHECKING_BALANCE = auto() # All tokens sold, confirming zero balance before restart.
    RESTARTING = auto()    # Strategy is in the process of restarting.
    ERROR = auto()         # An error occurred, strategy might be paused.

class StrategyInstance:
    def __init__(self, pair_symbol, base_amount_usdc, sell_percentage_x=0.02, buy_percentage_y=0.01):
        self.pair_symbol = pair_symbol
        self.base_currency, self.quote_currency = pair_symbol.split('/')
        self.base_amount_usdc = base_amount_usdc # e.g., 10 USDC

        # Validate and set percentages
        if not (0 < sell_percentage_x < 1): # Assuming X is like 0.02 (2%), not 2. And positive.
            strategy_logger.warning(f"[{self.pair_symbol}] Invalid sell_percentage_x: {sell_percentage_x}. Must be between 0 (exclusive) and 1 (exclusive). Defaulting to 0.02.")
            self.sell_percentage_x = 0.02
        else:
            self.sell_percentage_x = sell_percentage_x

        if not (0 < buy_percentage_y < 1): # Assuming Y is like 0.01 (1%), not 1. And positive.
            strategy_logger.warning(f"[{self.pair_symbol}] Invalid buy_percentage_y: {buy_percentage_y}. Must be between 0 (exclusive) and 1 (exclusive). Defaulting to 0.01.")
            self.buy_percentage_y = 0.01
        else:
            self.buy_percentage_y = buy_percentage_y

        self.current_state = StrategyState.IDLE
        self.last_buy_price = 0.0
        self.last_sell_price = 0.0 # Price of the last sell that led to a new buy or restart

        # Token balance for the base currency of the pair (e.g., ETH in ETH/USDC)
        self.current_token_balance = 0.0

        self.open_buy_order_id = None
        self.open_sell_order_id = None

        self.initial_market_buy_price = 0.0 # Price of the very first market buy in a cycle

        strategy_logger.info(f"StrategyInstance created for {self.pair_symbol} with base amount {self.base_amount_usdc} {self.quote_currency}, Sell X: {self.sell_percentage_x*100}%, Buy Y: {self.buy_percentage_y*100}%")

    def update_token_balance(self, new_balance):
        strategy_logger.debug(f"[{self.pair_symbol}] Updating token balance from {self.current_token_balance} to {new_balance}")
        self.current_token_balance = new_balance

    def set_state(self, new_state):
        if self.current_state != new_state:
            strategy_logger.info(f"[{self.pair_symbol}] State transition: {self.current_state.name} -> {new_state.name}")
            self.current_state = new_state
        else:
            strategy_logger.debug(f"[{self.pair_symbol}] State remains: {new_state.name}")


class StrategyManager:
    def __init__(self):
        self.strategies = {} # Key: pair_symbol (e.g., "ETH/USDC"), Value: StrategyInstance
        strategy_logger.info("StrategyManager initialized.")

    def get_strategy(self, pair_symbol):
        return self.strategies.get(pair_symbol)

    def _safe_cancel_order(self, strategy_instance, order_id_attr_name):
        """Safely cancels an order if its ID is stored in the strategy instance."""
        order_id = getattr(strategy_instance, order_id_attr_name, None)
        if order_id:
            strategy_logger.info(f"[{strategy_instance.pair_symbol}] Attempting to cancel order ID {order_id} (stored as {order_id_attr_name}).")
            cancelled = exchange.cancel_order(order_id)
            if cancelled:
                strategy_logger.info(f"[{strategy_instance.pair_symbol}] Successfully cancelled order {order_id}.")
                setattr(strategy_instance, order_id_attr_name, None)
            else:
                # If cancellation failed, it might be already filled or non-existent.
                # Check status to be sure.
                status, _, _, _, _, _ = exchange.get_order_status(order_id)
                strategy_logger.warning(f"[{strategy_instance.pair_symbol}] Failed to cancel order {order_id} or it was already processed. Status: {status}.")
                if status != "open": # If it's not open anymore (filled, cancelled, not_found), clear the ID.
                    setattr(strategy_instance, order_id_attr_name, None)
            return cancelled
        return False # No order ID to cancel

    def create_and_start_strategy(self, pair_symbol, base_amount_usdc=10.0, sell_percentage_x=0.02, buy_percentage_y=0.01):
        if pair_symbol in self.strategies and self.strategies[pair_symbol].current_state != StrategyState.IDLE:
            strategy_logger.warning(f"Strategy for {pair_symbol} already exists and is active. Cannot create duplicate.")
            return None

        strategy = StrategyInstance(pair_symbol, base_amount_usdc, sell_percentage_x, buy_percentage_y)
        self.strategies[pair_symbol] = strategy
        # Logging of creation details (including X% and Y%) is now handled in StrategyInstance.__init__
        # strategy_logger.info(f"Strategy created and registered for {pair_symbol}.")
        self.start_strategy_cycle(strategy)
        return strategy

    def start_strategy_cycle(self, strategy: StrategyInstance):
        """Initiates or restarts the strategy cycle with a market buy."""
        if strategy.current_state not in [StrategyState.IDLE, StrategyState.FULLY_SOLD_CHECKING_BALANCE, StrategyState.RESTARTING]:
            strategy_logger.error(f"[{strategy.pair_symbol}] Cannot start strategy cycle from state {strategy.current_state.name}.")
            strategy.set_state(StrategyState.ERROR)
            return

        strategy_logger.info(f"[{strategy.pair_symbol}] Starting strategy cycle. Current token balance: {strategy.current_token_balance}")

        # Ensure any old orders are cleared, especially for restarts
        self._safe_cancel_order(strategy, 'open_buy_order_id')
        self._safe_cancel_order(strategy, 'open_sell_order_id')
        strategy.open_buy_order_id = None
        strategy.open_sell_order_id = None

        strategy.set_state(StrategyState.MARKET_BUYING)

        # Simulate fetching current balance of the quote currency (e.g., USDC)
        # For this simulation, we assume sufficient USDC is available as per mock_exchange setup
        # In a real scenario:
        # usdc_balance = exchange.get_token_balance(strategy.quote_currency)
        # if usdc_balance < strategy.base_amount_usdc:
        #     strategy_logger.error(f"[{strategy.pair_symbol}] Insufficient {strategy.quote_currency} balance to start cycle.")
        #     strategy.set_state(StrategyState.ERROR)
        #     return

        order_id, buy_price, token_amount_received = exchange.market_buy(strategy.pair_symbol, strategy.base_amount_usdc)

        if order_id and token_amount_received > 0:
            strategy_logger.info(f"[{strategy.pair_symbol}] Market Buy successful. Order ID: {order_id}, Price: {buy_price}, Amount Received: {token_amount_received} {strategy.base_currency}")
            strategy.last_buy_price = buy_price
            strategy.initial_market_buy_price = buy_price # Mark the start of cycle
            strategy.update_token_balance(strategy.current_token_balance + token_amount_received) # Add to existing if any (should be 0 on fresh start)

            self.place_initial_orders(strategy, buy_price, strategy.current_token_balance)
        else:
            strategy_logger.error(f"[{strategy.pair_symbol}] Market Buy failed.")
            strategy.set_state(StrategyState.ERROR)

    def place_initial_orders(self, strategy: StrategyInstance, buy_price: float, total_token_amount: float):
        """Places the initial Limit Sell (+2%) and Limit Buy (-1%) orders."""
        strategy.set_state(StrategyState.BOUGHT_WAITING_ORDERS)

        # Calculate prices using stored percentages
        # For initial orders, 'buy_price' parameter is the initial_market_buy_price
        sell_price = strategy.initial_market_buy_price * (1 + strategy.sell_percentage_x)
        # Per Step 2: "Place a Limit Buy at -Y% below the initial buy price"
        next_buy_price = strategy.initial_market_buy_price * (1 - strategy.buy_percentage_y)

        strategy_logger.info(f"[{strategy.pair_symbol}] Placing initial orders (X={strategy.sell_percentage_x*100}%, Y={strategy.buy_percentage_y*100}%). Initial Market Buy Price: {strategy.initial_market_buy_price:.2f}. Sell at {sell_price:.2f} for {total_token_amount:.8f} {strategy.base_currency}. Buy at {next_buy_price:.2f} for {strategy.base_amount_usdc} {strategy.quote_currency}.")

        # Place Limit Sell for the full token amount received
        sell_order_id = exchange.limit_sell(strategy.pair_symbol, total_token_amount, sell_price)
        if sell_order_id:
            strategy.open_sell_order_id = sell_order_id
            strategy_logger.info(f"[{strategy.pair_symbol}] Limit Sell order placed. ID: {sell_order_id}")
        else:
            strategy_logger.error(f"[{strategy.pair_symbol}] Failed to place Limit Sell order.")
            strategy.set_state(StrategyState.ERROR)
            # Potentially try to market sell tokens as a fallback or alert
            return

        # Place Limit Buy for another base amount
        buy_order_id = exchange.limit_buy(strategy.pair_symbol, strategy.base_amount_usdc, next_buy_price)
        if buy_order_id:
            strategy.open_buy_order_id = buy_order_id
            strategy_logger.info(f"[{strategy.pair_symbol}] Limit Buy order placed. ID: {buy_order_id}")
        else:
            strategy_logger.error(f"[{strategy.pair_symbol}] Failed to place Limit Buy order.")
            # Critical error: we have tokens but can't place the next buy.
            # We should still have the sell order open.
            # Consider if we need to cancel the sell or let it be. For now, let it be.
            # The strategy is in an error state regarding the buy side.
            strategy.set_state(StrategyState.ERROR)
            # Fallback: If the sell order also failed, this is a bigger issue.
            if not strategy.open_sell_order_id:
                 strategy_logger.critical(f"[{strategy.pair_symbol}] CRITICAL: Failed to place both initial sell and buy orders after market purchase.")
            return

        if strategy.open_sell_order_id and strategy.open_buy_order_id:
            strategy.set_state(StrategyState.WAITING_SELL_AND_BUY)
        else:
            # This case should be covered by individual order failures setting ERROR state
            strategy_logger.error(f"[{strategy.pair_symbol}] Not all initial orders were placed successfully.")


    def handle_limit_buy_filled(self, strategy: StrategyInstance, filled_buy_price: float, bought_token_amount: float):
        strategy_logger.info(f"[{strategy.pair_symbol}] Limit Buy order filled. Price: {filled_buy_price}, Amount: {bought_token_amount} {strategy.base_currency}.")
        strategy.set_state(StrategyState.BUY_FILLED_PROCESSING)

        strategy.last_buy_price = filled_buy_price
        strategy.update_token_balance(strategy.current_token_balance + bought_token_amount)
        strategy.open_buy_order_id = None # Mark as filled

        # Cancel any previously open sell order (IMPORTANT: avoid crossing)
        # This sell would be based on an OLDER buy price.
        self._safe_cancel_order(strategy, 'open_sell_order_id')

        # Place new Limit Sell at +X% of the NEW buy price
        new_sell_price = filled_buy_price * (1 + strategy.sell_percentage_x)
        # Sell ALL current tokens
        sell_order_id = exchange.limit_sell(strategy.pair_symbol, strategy.current_token_balance, new_sell_price)
        if sell_order_id:
            strategy.open_sell_order_id = sell_order_id
            strategy_logger.info(f"[{strategy.pair_symbol}] (Buy Filled) New Limit Sell (X={strategy.sell_percentage_x*100}%) placed at {new_sell_price:.2f} for {strategy.current_token_balance:.8f} {strategy.base_currency}. ID: {sell_order_id}")
        else:
            strategy_logger.error(f"[{strategy.pair_symbol}] (Buy Filled) Failed to place new Limit Sell order. Strategy may be stuck with tokens.")
            strategy.set_state(StrategyState.ERROR)
            return

        # Place new Limit Buy at -Y% of the LATEST buy price (filled_buy_price)
        new_buy_price = filled_buy_price * (1 - strategy.buy_percentage_y)
        buy_order_id = exchange.limit_buy(strategy.pair_symbol, strategy.base_amount_usdc, new_buy_price)
        if buy_order_id:
            strategy.open_buy_order_id = buy_order_id
            strategy_logger.info(f"[{strategy.pair_symbol}] (Buy Filled) New Limit Buy (Y={strategy.buy_percentage_y*100}%) placed at {new_buy_price:.2f} for {strategy.base_amount_usdc} {strategy.quote_currency}. ID: {buy_order_id}")
        else:
            strategy_logger.error(f"[{strategy.pair_symbol}] (Buy Filled) Failed to place new Limit Buy order.")
            # Sell order is already placed, so we are waiting for a sell.
            # This means we can't average down further if price drops.
            # It's not ideal, but the strategy can continue on the sell side.
            # No state change to ERROR yet, but log as warning/error.
            # If the sell also failed, then it's an error.
            if not strategy.open_sell_order_id : # Should not happen given check above
                 strategy.set_state(StrategyState.ERROR)
                 return


        if strategy.open_sell_order_id and strategy.open_buy_order_id:
            strategy.set_state(StrategyState.WAITING_SELL_AND_BUY)
        elif strategy.open_sell_order_id : # Only sell order is open
             strategy_logger.warning(f"[{strategy.pair_symbol}] Only new sell order is active after buy fill. Waiting for sell.")
             # A state like WAITING_SELL_ONLY might be useful if this is a common valid path.
             # For now, WAITING_SELL_AND_BUY implies we'd ideally want both.
             # Or, if the logic is that after a buy, we *must* have a subsequent buy, then this is an error.
             # Based on flow: "Place new Limit Sell... Place new Limit Buy..." - implies both.
             # So if the new buy fails, it's an issue.
             strategy.set_state(StrategyState.ERROR) # Re-evaluating this: if new buy fails, it's a deviation.
        else: # Should be caught by individual order failures
            strategy_logger.error(f"[{strategy.pair_symbol}] Not all orders were placed successfully after buy fill.")
            strategy.set_state(StrategyState.ERROR)


    def handle_limit_sell_filled(self, strategy: StrategyInstance, filled_sell_price: float, sold_token_amount: float):
        strategy_logger.info(f"[{strategy.pair_symbol}] Limit Sell order filled. Price: {filled_sell_price}, Amount Sold: {sold_token_amount} {strategy.base_currency}.")
        strategy.set_state(StrategyState.SELL_FILLED_PROCESSING)

        strategy.last_sell_price = filled_sell_price
        strategy.update_token_balance(strategy.current_token_balance - sold_token_amount)
        strategy.open_sell_order_id = None # Mark as filled

        # Cancel the open buy order (if still active)
        self._safe_cancel_order(strategy, 'open_buy_order_id')

        # Check if ALL tokens have been sold
        # Need to be careful with floating point precision for balance
        # Fetching actual balance from exchange is best. Here we simulate.
        # For simulation, we use a small epsilon.
        # In a real scenario, fetch from exchange:
        # strategy.current_token_balance = exchange.get_token_balance(strategy.base_currency, strategy.pair_symbol)

        effective_balance = strategy.current_token_balance
        # If using exchange.get_token_balance:
        # effective_balance = exchange.get_token_balance(strategy.base_currency)

        strategy_logger.info(f"[{strategy.pair_symbol}] Token balance after sell: {effective_balance} {strategy.base_currency}")

        if effective_balance < 1e-8: # Consider a very small amount as zero
            strategy_logger.info(f"[{strategy.pair_symbol}] All tokens sold (balance: {effective_balance}). Attempting restart.")
            strategy.current_token_balance = 0 # Normalize to zero
            self.attempt_restart_strategy(strategy)
        else:
            # Place new Limit Buy at -Y% of the last sell price
            new_buy_price = filled_sell_price * (1 - strategy.buy_percentage_y)
            buy_order_id = exchange.limit_buy(strategy.pair_symbol, strategy.base_amount_usdc, new_buy_price)
            if buy_order_id:
                strategy.open_buy_order_id = buy_order_id
                strategy_logger.info(f"[{strategy.pair_symbol}] (Sell Partially Filled) New Limit Buy (Y={strategy.buy_percentage_y*100}%) placed at {new_buy_price:.2f} (based on last sell price {filled_sell_price:.2f}). ID: {buy_order_id}")
                # State remains WAITING_SELL_AND_BUY, but effectively only waiting for this new buy.
                # No new sell is placed at this point according to the rules.
                strategy.set_state(StrategyState.WAITING_SELL_AND_BUY)
            else:
                strategy_logger.error(f"[{strategy.pair_symbol}] (Sell Partially Filled) Failed to place new Limit Buy order.")
                strategy.set_state(StrategyState.ERROR)


    def attempt_restart_strategy(self, strategy: StrategyInstance):
        strategy.set_state(StrategyState.FULLY_SOLD_CHECKING_BALANCE)

        # In a real system, explicitly query exchange for the token balance.
        # For simulation, we trust our internal tracking, which should be 0 here.
        # actual_balance_from_exchange = exchange.get_token_balance(strategy.base_currency)
        # strategy.update_token_balance(actual_balance_from_exchange)

        if abs(strategy.current_token_balance) < 1e-8: # Confirming it's zero
            strategy_logger.info(f"[{strategy.pair_symbol}] Confirmed zero token balance. Restarting strategy.")
            strategy.set_state(StrategyState.RESTARTING)
            # Reset strategy-specific cycle variables (prices, etc.)
            strategy.last_buy_price = 0.0
            strategy.last_sell_price = 0.0
            strategy.initial_market_buy_price = 0.0
            # strategy.current_token_balance is already 0
            # Order IDs should be None already or will be handled by start_strategy_cycle

            self.start_strategy_cycle(strategy)
        else:
            strategy_logger.error(f"[{strategy.pair_symbol}] Attempted restart but token balance is {strategy.current_token_balance} (not zero). Strategy in ERROR.")
            # This is a critical state. Strategy thought it sold everything but didn't.
            # Manual intervention might be needed. Or try to sell remaining.
            strategy.set_state(StrategyState.ERROR)


    def process_event(self, event_details):
        """
        Simulates receiving an event, e.g., an order fill from the exchange.
        In a real application, this would be triggered by WebSocket messages or API polling.
        """
        pair_symbol = event_details.get("pair_symbol")
        order_id = event_details.get("order_id")
        event_type = event_details.get("event_type") # "order_filled"

        strategy = self.get_strategy(pair_symbol)
        if not strategy:
            strategy_logger.warning(f"Received event for unknown strategy or pair: {pair_symbol}. Ignoring.")
            return

        strategy_logger.info(f"[{pair_symbol}] Processing event: {event_type} for order {order_id}")

        if event_type == "order_filled":
            # In a real scenario, you'd get fill details (price, amount) from the event or by querying the order.
            # Here, we'll use the mock exchange's simulate_fill_order to get these details.
            # This is a bit circular for simulation but helps test.
            # In reality, the exchange would push this data.

            # We need to know if it was a buy or sell, and the fill details.
            # Let's assume event_details contains this for simulation.
            # e.g. event_details = {"event_type": "order_filled", "pair_symbol": "ETH/USDC", "order_id": "xyz",
            #                         "side": "buy", "filled_price": 1950, "filled_amount_token": 0.005}

            side = event_details.get("side")
            filled_price = event_details.get("filled_price")
            filled_amount_token = event_details.get("filled_amount_token") # This is token amount for both buy and sell fills

            if not all([side, filled_price, filled_amount_token is not None]): # filled_amount_token can be 0 if order fully cancelled before fill
                 strategy_logger.error(f"[{pair_symbol}] Order filled event for {order_id} is missing crucial details (side, price, amount). Cannot process.")
                 # Potentially query the order status from exchange here as a fallback
                 return


            if side == "buy":
                if order_id == strategy.open_buy_order_id:
                    self.handle_limit_buy_filled(strategy, filled_price, filled_amount_token)
                else:
                    strategy_logger.warning(f"[{pair_symbol}] Received fill for buy order {order_id}, but expected open buy order ID is {strategy.open_buy_order_id}. Might be a stale event or logic error.")
            elif side == "sell":
                if order_id == strategy.open_sell_order_id:
                    self.handle_limit_sell_filled(strategy, filled_price, filled_amount_token)
                else:
                    strategy_logger.warning(f"[{pair_symbol}] Received fill for sell order {order_id}, but expected open sell order ID is {strategy.open_sell_order_id}. Might be a stale event or logic error.")
            else:
                strategy_logger.error(f"[{pair_symbol}] Unknown order side '{side}' in filled event for order {order_id}.")
        else:
            strategy_logger.warning(f"[{pair_symbol}] Received unhandled event type: {event_type}")


if __name__ == '__main__':
    # Enhanced test scenario
    exchange.reset_mock_exchange() # Reset mock exchange state
    manager = StrategyManager()

    # ---- Test Case 1: Full Cycle with Restart ----
    strategy_logger.info("\n\n---- TEST CASE 1: ETH/USDC Full Cycle & Restart (Custom X=3%, Y=1.5%) ----")
    eth_pair = "ETH/USDC"
    eth_base_amount = 10
    eth_sell_x = 0.03  # +3%
    eth_buy_y = 0.015 # -1.5%
    # Mock ETH price from mock_exchange is 2000 for ETH/USDC.
    # So, 10 USDC buys 10 / 2000 = 0.005 ETH.

    eth_strategy = manager.create_and_start_strategy(eth_pair, eth_base_amount, sell_percentage_x=eth_sell_x, buy_percentage_y=eth_buy_y)
    if not eth_strategy:
        strategy_logger.error("Failed to create ETH strategy for test case 1")
        exit()

    # The create_and_start_strategy method now immediately starts the cycle,
    # so the state will be WAITING_SELL_AND_BUY if successful.
    print(f"ETH strategy after start: State={eth_strategy.current_state.name}, Token Balance={eth_strategy.current_token_balance}")
    # Expected: Market buy (10 USDC @ 2000 = 0.005 ETH), then initial orders.
    # Sell @ 2000*1.02 = 2040 for 0.005 ETH
    # Buy @ 2000*0.99 = 1980 for 10 USDC

    # print(f"Initial state: {eth_strategy.current_state.name}") # Covered by print above
    # Expected: Market buy (10 USDC @ ~2000 = 0.005 ETH), then initial orders.
    # Sell @ 2000*1.02 = 2040 for 0.005 ETH
    # Buy @ 2000*0.99 = 1980 for 10 USDC

    print(f"ETH strategy after start: State={eth_strategy.current_state.name}, Token Balance={eth_strategy.current_token_balance}")
    print(f"Open Buy ID: {eth_strategy.open_buy_order_id}, Open Sell ID: {eth_strategy.open_sell_order_id}")
    print(f"Last Buy Price: {eth_strategy.last_buy_price}, Initial Market Buy Price: {eth_strategy.initial_market_buy_price}")

    # Simulate the first limit buy getting filled (price drops)
    # Original buy was at ~2000. New limit buy at 1980.
    if eth_strategy.open_buy_order_id and eth_strategy.current_state == StrategyState.WAITING_SELL_AND_BUY:
        strategy_logger.info("\n---- Simulating First Limit Buy Fill (Price Drop) ----")
        buy_order_to_fill = eth_strategy.open_buy_order_id
        # The limit buy was placed for 10 USDC at 1980.
        # Amount of token received = 10 / 1980 = ~0.0050505 ETH
        # We need the fill price and the amount of TOKEN received from the fill.
        # The mock_exchange.simulate_fill_order calculates this.

        # Get the actual price of the buy order we are about to fill
        _, _, _, _, order_price, _ = exchange.get_order_status(buy_order_to_fill)

        # Simulate the fill. For a buy, the filled_price is the token price.
        # The amount for the event is the token amount received.
        success, filled_price, token_amount = exchange.simulate_fill_order(buy_order_to_fill, fill_price=order_price) # Fill at its set price
        if success:
            manager.process_event({
                "event_type": "order_filled", "pair_symbol": eth_pair, "order_id": buy_order_to_fill,
                "side": "buy", "filled_price": filled_price, "filled_amount_token": token_amount
            })
            print(f"After first limit buy fill: State={eth_strategy.current_state.name}, Token Balance={eth_strategy.current_token_balance}")
            print(f"New Open Buy ID: {eth_strategy.open_buy_order_id}, New Open Sell ID: {eth_strategy.open_sell_order_id}")
            print(f"Last Buy Price: {eth_strategy.last_buy_price}") # Should be 1980
            # Expected: Old sell (at 2040) cancelled.
            # New sell for total tokens (0.005 + 0.0050505 = ~0.0100505 ETH) at 1980*1.02 = 2019.6
            # New buy for 10 USDC at 1980*0.99 = 1960.2
        else:
            strategy_logger.error(f"Test Case 1: Failed to simulate fill for order {buy_order_to_fill}")

    # Simulate the sell order getting filled (price rises)
    # Current sell is for ~0.0100505 ETH at 2019.6
    if eth_strategy.open_sell_order_id and eth_strategy.current_state == StrategyState.WAITING_SELL_AND_BUY:
        strategy_logger.info("\n---- Simulating Sell Fill (Price Rise) ----")
        sell_order_to_fill = eth_strategy.open_sell_order_id

        _, _, _, _, order_price, order_token_amount = exchange.get_order_status(sell_order_to_fill)

        # Simulate the fill. For a sell, filled_price is the token price.
        # The amount for the event is the token amount sold.
        success, filled_price, token_amount_sold = exchange.simulate_fill_order(sell_order_to_fill, fill_price=order_price)
        if success:
            manager.process_event({
                "event_type": "order_filled", "pair_symbol": eth_pair, "order_id": sell_order_to_fill,
                "side": "sell", "filled_price": filled_price, "filled_amount_token": token_amount_sold
            })
            print(f"After sell fill: State={eth_strategy.current_state.name}, Token Balance={eth_strategy.current_token_balance}")
            # Expected: Token balance becomes 0 (or very close). Strategy should restart.
            # Open buy (at 1960.2) should be cancelled.
            # New market buy for 10 USDC.
            # Then new initial sell/buy orders.
            print(f"Open Buy ID: {eth_strategy.open_buy_order_id}, Open Sell ID: {eth_strategy.open_sell_order_id}")
            print(f"Last Sell Price: {eth_strategy.last_sell_price}") # Should be 2019.6
            print(f"Initial Market Buy Price (should be new cycle): {eth_strategy.initial_market_buy_price}")
            # Check if it indeed restarted (new market buy price will be different from the very first one if price changed, or same if stable)
            # More importantly, state should be WAITING_SELL_AND_BUY and new order IDs.
        else:
            strategy_logger.error(f"Test Case 1: Failed to simulate fill for order {sell_order_to_fill}")

    # ---- Test Case 2: Duplicate Strategy Prevention ----
    strategy_logger.info("\n\n---- TEST CASE 2: Duplicate Strategy Prevention ----")
    eth_strategy_dup = manager.create_and_start_strategy(eth_pair, 20)
    if not eth_strategy_dup:
        strategy_logger.info(f"Successfully prevented duplicate strategy creation for {eth_pair} while active.")
    else:
        strategy_logger.error(f"Allowed duplicate strategy for {eth_pair}!")

    # ---- Test Case 3: Sell leads to partial balance, then another buy ----
    strategy_logger.info("\n\n---- TEST CASE 3: BTC/USDC Partial Sell then New Buy (Custom X=2.5%, Y=0.5%) ----")
    btc_pair = "BTC/USDC"
    btc_base_amount = 100
    btc_sell_x = 0.025 # +2.5%
    btc_buy_y = 0.005  # -0.5%
    # Mock BTC price from mock_exchange is 30000 for BTC/USDC. Base amount 100 USDC.
    # 100 USDC buys 100/30000 = 0.003333... BTC

    btc_strategy = manager.create_and_start_strategy(btc_pair, btc_base_amount, sell_percentage_x=btc_sell_x, buy_percentage_y=btc_buy_y)
    if not btc_strategy:
        strategy_logger.error("Failed to create BTC strategy for test case 3")
        exit()

    print(f"BTC strategy after start: State={btc_strategy.current_state.name}, Token Balance={btc_strategy.current_token_balance:.8f}")
    # Expected: Market buy (100 USDC @ ~30000 = ~0.003333 BTC).
    # Sell @ 30000*1.02 = 30600 for ~0.003333 BTC
    # Buy @ 30000*0.99 = 29700 for 100 USDC

    # Simulate the initial sell order getting PARTIALLY filled (e.g. if it was a large order)
    # Our current logic sells the *full* token amount. So a partial fill of that order means not all tokens sold.
    # The mock_exchange.simulate_fill_order fills the whole order.
    # To test "partial sell", we'd need the strategy to place a sell, then that sell fills,
    # but the `sold_token_amount` is LESS than `strategy.current_token_balance` at the time of fill.
    # This means the `handle_limit_sell_filled` would see `effective_balance > 1e-8`.

    # Let's assume the first sell order (for all tokens) gets filled.
    # This will lead to a restart if all tokens are sold.
    # To test the "partial sell" logic branch in handle_limit_sell_filled,
    # we need a scenario where a sell fills, but current_token_balance is NOT zero after.
    # This happens if:
    # 1. Initial market buy -> places sell S1 (all tokens T1) and buy B1.
    # 2. B1 fills -> new tokens T2 bought. Total tokens T1+T2. Old S1 cancelled. New sell S2 (for T1+T2) and buy B2 placed.
    # 3. S2 fills -> all T1+T2 sold. Balance is 0. Restart. (This is normal full sell)

    # The scenario "Place new Limit Buy at -1% of the last sell price" (after a sell)
    # implies that not all tokens were sold by that sell.
    # This means the sell order was for an amount X, and after selling X, there's still Y tokens left.
    # Our current strategy: "Place Limit Sell at +2% of the buy price, for the full token amount received."
    # And after a buy fill: "Place new Limit Sell at +2% of the new buy price [for the total current token balance]."
    # So, sells are always for the *full current balance*.
    # If such a sell fills, the balance *must* go to zero.

    # The only way `effective_balance < 1e-8` is FALSE after a sell fill is if `sold_token_amount`
    # passed to `handle_limit_sell_filled` is somehow less than the balance the strategy *thought* it had.
    # This could be due to exchange fees not accounted for, or precision issues, or if the `sold_token_amount`
    # from the fill event is unexpectedly small.

    # Let's force this scenario by manually adjusting balance before calling handle_limit_sell_filled,
    # or by providing a `sold_token_amount` that doesn't clear the balance.
    if btc_strategy.open_sell_order_id and btc_strategy.current_state == StrategyState.WAITING_SELL_AND_BUY:
        strategy_logger.info("\n---- Simulating BTC Sell Fill (but not all tokens, to test partial logic) ----")

        # Current balance from initial market buy: btc_strategy.current_token_balance
        # Sell order is for this full amount.
        # If this sell order fills completely, balance will be 0.

        # To test the "else" branch of `if effective_balance < 1e-8:` in `handle_limit_sell_filled`,
        # we need `sold_token_amount` to be less than `btc_strategy.current_token_balance`
        # when `handle_limit_sell_filled` is called.

        # Let's simulate the sell fill, but imagine the fill event says slightly fewer tokens were sold
        # than what the order was for (e.g. due to a hypothetical dust issue or fee not perfectly modeled).
        sell_order_to_fill = btc_strategy.open_sell_order_id
        _, _, _, _, order_price, order_token_amount = exchange.get_order_status(sell_order_to_fill) # order_token_amount is what the order was placed for

        # Simulate the fill, but let's say only 90% of the order amount was actually sold and reported in the fill event
        simulated_sold_amount = order_token_amount * 0.9

        # Manually trigger the fill in the mock exchange for the *actual* order amount,
        # so the exchange's internal balance tracking for USDC is correct for a full fill.
        # But then, we'll call our handler with the *simulated_sold_amount*.
        success, filled_price, _ = exchange.simulate_fill_order(sell_order_to_fill, fill_price=order_price) # fill it at its price

        if success:
            # Now call our handler with the reduced amount
            strategy_logger.info(f"[{btc_pair}] Original token amount in sell order: {order_token_amount:.8f}. Simulating fill for {simulated_sold_amount:.8f}.")
            manager.process_event({
                "event_type": "order_filled", "pair_symbol": btc_pair, "order_id": sell_order_to_fill,
                "side": "sell", "filled_price": filled_price, "filled_amount_token": simulated_sold_amount
            })
            print(f"BTC after 'partial' sell fill: State={btc_strategy.current_state.name}, Token Balance={btc_strategy.current_token_balance:.8f}")
            # Expected: Old buy cancelled. Token balance is NOT zero.
            # New limit buy placed at -1% of filled_sell_price.
            # State should be WAITING_SELL_AND_BUY (but only buy is active).
            print(f"Open Buy ID: {btc_strategy.open_buy_order_id}, Open Sell ID: {btc_strategy.open_sell_order_id}") # Sell should be None
            print(f"Last Sell Price: {btc_strategy.last_sell_price}")

            # Now, if this new buy order fills...
            if btc_strategy.open_buy_order_id and not btc_strategy.open_sell_order_id: # Only buy is open
                strategy_logger.info("\n---- Simulating subsequent Buy Fill (after partial sell) ----")
                buy_order_to_fill = btc_strategy.open_buy_order_id
                _, _, _, _, order_price_buy, _ = exchange.get_order_status(buy_order_to_fill)

                success_buy, filled_price_buy, token_amount_buy = exchange.simulate_fill_order(buy_order_to_fill, fill_price=order_price_buy)
                if success_buy:
                    manager.process_event({
                        "event_type": "order_filled", "pair_symbol": btc_pair, "order_id": buy_order_to_fill,
                        "side": "buy", "filled_price": filled_price_buy, "filled_amount_token": token_amount_buy
                    })
                    print(f"BTC after subsequent buy fill: State={btc_strategy.current_state.name}, Token Balance={btc_strategy.current_token_balance:.8f}")
                    # Expected: New sell for ALL current tokens. New buy.
                    print(f"Open Buy ID: {btc_strategy.open_buy_order_id}, Open Sell ID: {btc_strategy.open_sell_order_id}")
                else:
                    strategy_logger.error(f"Test Case 3: Failed to simulate fill for subsequent buy order {buy_order_to_fill}")
        else:
            strategy_logger.error(f"Test Case 3: Failed to simulate fill for initial BTC sell order {sell_order_to_fill}")


    # Restore original mock ETH price if changed
    # if "ETH_PRICE" in exchange.MOCK_ORDERS: # if we used the hack
    #     if original_eth_price_in_mock is not None :
    #         exchange.MOCK_ORDERS["ETH_PRICE"] = original_eth_price_in_mock
    #     else:
    #         del exchange.MOCK_ORDERS["ETH_PRICE"]

    strategy_logger.info("\n\n---- END OF TESTS ----")
    print("\nCheck strategy.log and mock_exchange.log for detailed logs.")
# Ensure the old __main__ block is removed if it was separate and conflicting.
# The primary test harness is already included above.
