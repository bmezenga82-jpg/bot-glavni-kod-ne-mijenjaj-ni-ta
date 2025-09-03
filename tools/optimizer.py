import itertools
from core.config import load_config
from core.exchange import ExchangeConnector
from modules.utils import get_pairs, load_api_keys
from core.portfolio import PortfolioManager
from core.tradelog import TradeLogger
from core.profit_tracker import ProfitTracker

def test_combo(symbol, amount, sell_pct, buy_pct):
    api_keys = load_api_keys()
    binance_keys = api_keys.get('binance', {}).get('testnet', {})
    exchange = ExchangeConnector("binance", binance_keys.get('api_key'), binance_keys.get('secret_key'))
    profit_tracker = ProfitTracker()
    portfolio = PortfolioManager(profit_tracker=profit_tracker)
    logger = TradeLogger("optimizer_results.csv")

    price = exchange.get_price(symbol)
    if price is None:
        return

    base_qty = amount / price
    sell_price = price * (1 + sell_pct / 100)
    buy_price = price * (1 + buy_pct / 100)

    profit_estimate = (sell_price - buy_price) * base_qty
    logger.log(symbol, f"test s{sell_pct}/b{buy_pct}", price, base_qty, "binance")

    print(f"Test: {symbol} | Sell: {sell_pct}% | Buy: {buy_pct}% | Profit ~ {profit_estimate:.2f} USDC")

def run_optimizer():
    config = load_config()
    pairs = get_pairs()
    symbol = pairs[0]
    amount = config['amount']

    sell_range = [1.0, 1.5, 2.0]
    buy_range = [-1.0, -1.5, -2.0]

    for sell_pct, buy_pct in itertools.product(sell_range, buy_range):
        test_combo(symbol, amount, sell_pct, buy_pct)

if __name__ == "__main__":
    run_optimizer()
