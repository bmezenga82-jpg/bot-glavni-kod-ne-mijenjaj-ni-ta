import uuid
import time

# Mock database for orders and balances
MOCK_ORDERS = {}
MOCK_BALANCES = {
    "USDC": 1000.0
} # Initial USDC balance
MOCK_TRADE_HISTORY = []

strategy_logger = None # Will be set by strategy_manager

def set_logger(logger):
    global strategy_logger
    strategy_logger = logger

class MockOrder:
    def __init__(self, order_id, pair_symbol, order_type, side, amount, price=None, status="open"):
        self.order_id = order_id
        self.pair_symbol = pair_symbol
        self.order_type = order_type # "market" or "limit"
        self.side = side # "buy" or "sell"
        self.amount = amount # For limit sell (token quantity), for limit buy (USDC quantity), for market buy (USDC quantity)
        self.price = price # None for market orders
        self.status = status # "open", "filled", "cancelled"
        self.filled_amount = 0 # Amount of token bought or sold
        self.created_at = time.time()
        self.filled_price = None # Average price at which the order was filled

def market_buy(pair_symbol, usdc_amount):
    if not strategy_logger:
        print("Logger not set for mock_exchange") # Fallback
        # Or raise an exception: raise Exception("Logger not set for mock_exchange")

    base_currency, quote_currency = pair_symbol.split('/')
    if MOCK_BALANCES.get(quote_currency, 0) < usdc_amount:
        strategy_logger.error(f"MockExchange: Insufficient {quote_currency} balance for market buy.")
        return None, 0, 0 # Order ID, Price, Amount

    # Simulate a price - e.g., a fixed price or a slightly varying one
    # For simplicity, let's use a fixed price for now, e.g., 1 token = 10 USDC
    # More realistically, this would fluctuate.
    simulated_price = 10.0 # Example: 1 TOKEN = 10 USDC for a TOKEN/USDC pair
    if pair_symbol == "ETH/USDC":
        simulated_price = 2000.0
    elif pair_symbol == "BTC/USDC":
        simulated_price = 30000.0

    token_amount_received = usdc_amount / simulated_price

    MOCK_BALANCES[quote_currency] -= usdc_amount
    MOCK_BALANCES[base_currency] = MOCK_BALANCES.get(base_currency, 0) + token_amount_received

    order_id = str(uuid.uuid4())
    MOCK_TRADE_HISTORY.append({
        "order_id": order_id,
        "pair": pair_symbol,
        "type": "market",
        "side": "buy",
        "price": simulated_price,
        "amount_usdc": usdc_amount,
        "amount_token": token_amount_received,
        "timestamp": time.time()
    })
    strategy_logger.info(f"MockExchange: Market Buy Executed for {pair_symbol}. Spent: {usdc_amount} {quote_currency}, Received: {token_amount_received} {base_currency} @ {simulated_price}")
    return order_id, simulated_price, token_amount_received

def limit_order(pair_symbol, order_type, side, amount, price):
    if not strategy_logger:
        print("Logger not set for mock_exchange") # Fallback

    order_id = str(uuid.uuid4())
    MOCK_ORDERS[order_id] = MockOrder(order_id, pair_symbol, order_type, side, amount, price)
    strategy_logger.info(f"MockExchange: Limit {side} order placed for {pair_symbol}. Amount: {amount}, Price: {price}. Order ID: {order_id}")
    return order_id

def limit_sell(pair_symbol, token_amount, price):
    return limit_order(pair_symbol, "limit", "sell", token_amount, price)

def limit_buy(pair_symbol, usdc_amount, price):
    # For limit buys, 'amount' is the USDC amount to spend
    return limit_order(pair_symbol, "limit", "buy", usdc_amount, price)


def cancel_order(order_id):
    if not strategy_logger:
        print("Logger not set for mock_exchange") # Fallback

    if order_id in MOCK_ORDERS:
        if MOCK_ORDERS[order_id].status == "open":
            MOCK_ORDERS[order_id].status = "cancelled"
            strategy_logger.info(f"MockExchange: Order {order_id} cancelled.")
            return True
        else:
            strategy_logger.warning(f"MockExchange: Order {order_id} could not be cancelled, status is {MOCK_ORDERS[order_id].status}.")
            return False
    else:
        strategy_logger.error(f"MockExchange: Order {order_id} not found for cancellation.")
        return False

def get_order_status(order_id):
    if order_id in MOCK_ORDERS:
        return MOCK_ORDERS[order_id].status, MOCK_ORDERS[order_id].filled_price, MOCK_ORDERS[order_id].filled_amount, MOCK_ORDERS[order_id].side, MOCK_ORDERS[order_id].price, MOCK_ORDERS[order_id].amount
    return "not_found", None, 0, None, None, None

def get_token_balance(token_symbol):
    return MOCK_BALANCES.get(token_symbol, 0.0)

# --- Simulation Functions ---
def simulate_fill_order(order_id, fill_price=None):
    """
    Manually simulates an order fill.
    For a buy order, fill_price is the price of the token bought.
    For a sell order, fill_price is the price the token was sold at.
    """
    if not strategy_logger:
        print("Logger not set for mock_exchange") # Fallback

    if order_id not in MOCK_ORDERS:
        strategy_logger.error(f"MockExchange (Simulate): Order {order_id} not found.")
        return False, None, 0

    order = MOCK_ORDERS[order_id]
    if order.status != "open":
        strategy_logger.warning(f"MockExchange (Simulate): Order {order_id} is not open, current status: {order.status}.")
        return False, None, 0

    order.status = "filled"

    base_currency, quote_currency = order.pair_symbol.split('/')

    if order.side == "buy":
        order.filled_price = fill_price if fill_price is not None else order.price
        # order.amount is USDC for limit buy
        token_bought = order.amount / order.filled_price
        order.filled_amount = token_bought

        MOCK_BALANCES[quote_currency] = MOCK_BALANCES.get(quote_currency, 0) - order.amount # Spend USDC
        MOCK_BALANCES[base_currency] = MOCK_BALANCES.get(base_currency, 0) + token_bought
        strategy_logger.info(f"MockExchange (Simulate): Limit Buy Order {order_id} for {order.pair_symbol} FILLED. Bought: {token_bought} {base_currency} @ {order.filled_price} {quote_currency} (spent {order.amount} {quote_currency})")
        return True, order.filled_price, token_bought

    elif order.side == "sell":
        order.filled_price = fill_price if fill_price is not None else order.price
        # order.amount is token quantity for limit sell
        usdc_received = order.amount * order.filled_price
        order.filled_amount = order.amount # Token amount sold

        MOCK_BALANCES[base_currency] = MOCK_BALANCES.get(base_currency, 0) - order.amount # Reduce token
        MOCK_BALANCES[quote_currency] = MOCK_BALANCES.get(quote_currency, 0) + usdc_received
        strategy_logger.info(f"MockExchange (Simulate): Limit Sell Order {order_id} for {order.pair_symbol} FILLED. Sold: {order.amount} {base_currency} @ {order.filled_price} {quote_currency} (received {usdc_received} {quote_currency})")
        return True, order.filled_price, order.amount # True, filled_price, token_amount_sold

    return False, None, 0


def reset_mock_exchange():
    global MOCK_ORDERS, MOCK_BALANCES, MOCK_TRADE_HISTORY
    MOCK_ORDERS = {}
    MOCK_BALANCES = {"USDC": 1000.0}
    MOCK_TRADE_HISTORY = []
    if strategy_logger:
        strategy_logger.info("MockExchange: Reset to initial state.")
    else:
        print("MockExchange: Reset to initial state. (Logger not set)")

if __name__ == "__main__":
    # Basic test
    # This would typically be in a separate test file
    from logger import setup_logger
    test_logger = setup_logger('mock_exchange_test', 'mock_exchange_test.log')
    set_logger(test_logger)

    reset_mock_exchange()

    print(f"Initial Balances: {MOCK_BALANCES}")

    # Test Market Buy
    buy_order_id, buy_price, token_bought = market_buy("ETH/USDC", 100) # Buy 100 USDC worth of ETH
    print(f"Market Buy: ID={buy_order_id}, Price={buy_price}, ETH Bought={token_bought}")
    print(f"Balances after market buy: {MOCK_BALANCES}")

    # Test Limit Sell
    sell_order_id = limit_sell("ETH/USDC", token_bought, buy_price * 1.02)
    print(f"Limit Sell Placed: ID={sell_order_id}")
    print(f"Order Status: {get_order_status(sell_order_id)[0]}")

    # Simulate Sell Fill
    filled, filled_price, sold_amount = simulate_fill_order(sell_order_id)
    print(f"Sell Order Fill: Success={filled}, Filled Price={filled_price}, ETH Sold={sold_amount}")
    print(f"Order Status: {get_order_status(sell_order_id)[0]}")
    print(f"Balances after sell: {MOCK_BALANCES}")

    # Test Limit Buy
    limit_buy_order_id = limit_buy("ETH/USDC", 10, buy_price * 0.99) # Buy 10 USDC worth of ETH
    print(f"Limit Buy Placed: ID={limit_buy_order_id}")

    # Simulate Buy Fill
    filled, filled_price, bought_amount = simulate_fill_order(limit_buy_order_id)
    print(f"Buy Order Fill: Success={filled}, Filled Price={filled_price}, ETH Bought={bought_amount}")
    print(f"Order Status: {get_order_status(limit_buy_order_id)[0]}")
    print(f"Balances after limit buy: {MOCK_BALANCES}")

    print("\nMock Orders:")
    for id, order in MOCK_ORDERS.items():
        print(f"  ID: {id}, Pair: {order.pair_symbol}, Type: {order.order_type}, Side: {order.side}, Amount: {order.amount}, Price: {order.price}, Status: {order.status}, Filled Price: {order.filled_price}")

    print("\nTrade History:")
    for trade in MOCK_TRADE_HISTORY:
        print(f"  {trade}")
