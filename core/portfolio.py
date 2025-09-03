import logging
from core.profit_tracker import ProfitTracker
from .models import Position
from core.extensions import db

logger = logging.getLogger(__name__)

class PortfolioManager:
    def __init__(self, profit_tracker=None):
        self.profit_tracker = profit_tracker or ProfitTracker()
        self.total_profit = self._load_total_profit()

    def _load_positions(self):
        """Load positions from the database into an in-memory dictionary."""
        self.positions = {
            p.symbol: {"amount": p.amount, "buy_price": p.buy_price}
            for p in Position.query.all()
        }

    def _load_total_profit(self):
        """Optionally load total profit from a DB table, or return 0."""
        # This assumes you're not tracking profit persistently yet
        # If you are, fetch from a DB table or calculate from a log table
        return 0

    def record_buy(self, symbol, amount, price, append=False):
        """Record a buy in USDC ``amount`` at ``price``.

        If ``append`` is True and an existing position is found, the amount is
        added to the current position and the average buy price is updated.
        """
        position = Position.query.filter_by(symbol=symbol).first()
        if position and append:
            existing_tokens = position.amount / position.buy_price
            new_tokens = amount / price
            total_tokens = existing_tokens + new_tokens
            position.amount += amount
            position.buy_price = (
                (position.buy_price * existing_tokens + price * new_tokens)
                / total_tokens
            )
        elif position:
            position.amount = amount
            position.buy_price = price
        else:
            position = Position(symbol=symbol, amount=amount, buy_price=price)
            db.session.add(position)

        db.session.commit()
        self._load_positions()  # Refresh in-memory state

    def record_sell(self, symbol, sell_price, asset_quantity_sold, buy_price, **kwargs):
        """
        Records a sell transaction and logs the profit. This method is now stateless regarding the buy price.
        """
        if buy_price is None or buy_price == 0:
            logger.error(f"Cannot record sell for {symbol}: buy_price is invalid (None or zero).")
            return

        profit = (sell_price - buy_price) * asset_quantity_sold
        self.total_profit += profit

        exchange_name = kwargs.get('exchange', 'unknown')
        trading_mode_name = kwargs.get('trading_mode', 'unknown')
        pair_id = kwargs.get('pair_id')
        retained_qty = kwargs.get('retained_qty', 0.0)
        profit_mode = kwargs.get('profit_mode', 'usdc')

        # Log the profit and update pair totals
        self.profit_tracker.log_profit(
            symbol,
            buy_price,
            sell_price,
            asset_quantity_sold,
            exchange_name,
            trading_mode_name,
            pair_id=pair_id,
            retained_qty=retained_qty,
            profit_mode=profit_mode,
        )

        logger.info(
            "Sold %.4f of %s on %s (%s) at %.4f (buy_price: %.4f). Profit: %.2f",
            asset_quantity_sold,
            symbol,
            exchange_name,
            trading_mode_name,
            sell_price,
            buy_price,
            profit
        )

        # Note: The position management is now simplified as we are not tracking aggregated positions for this strategy.
        # The logic for handling `Position` objects is removed from this method.
        # If you need to track aggregated positions for other purposes, you would need to re-introduce
        # that logic separately. For the current strategy, this is sufficient.

    def print_status(self):
        if not self.positions:
            logger.info("No active positions.")
            return
        for symbol, data in self.positions.items():
            logger.info("%s: %.4f @ %.4f", symbol, data['amount'], data['buy_price'])

    def save(self):
        """No-op for compatibility — nothing to save with DB-based persistence."""
        pass

    def load(self):
        """For compatibility — reload in-memory state from the DB."""
        self._load_positions()

    def get_buy_price(self, symbol):
        position = Position.query.filter_by(symbol=symbol).first()
        return position.buy_price if position else None
