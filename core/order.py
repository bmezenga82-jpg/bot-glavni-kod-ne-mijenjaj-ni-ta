from .models import Order
import logging
from core.extensions import db

logger = logging.getLogger(__name__)

class OrderManager:
    def set_order(self, symbol, side, price, amount, order_id=None, status="open", exchange="binance"):
        existing = Order.query.filter_by(symbol=symbol, side=side).first()
        if existing:
            existing.price = round(price, 4)
            existing.amount = round(amount, 2)
            existing.status = status
            existing.order_id = order_id
            existing.filled = 0.0
            existing.exchange = exchange
        else:
            new_order = Order(
                symbol=symbol,
                side=side,
                price=round(price, 4),
                amount=round(amount, 2),
                exchange=exchange,
                status=status,
                order_id=order_id,
                filled=0.0
            )
            db.session.add(new_order)
        db.session.commit()

    def update_fill(self, symbol, side, filled, remaining, status):
        order = Order.query.filter_by(symbol=symbol, side=side).first()
        if order:
            order.filled = round(filled, 2)
            order.amount = round(remaining, 2)
            order.status = status
            db.session.add(order)
            db.session.commit()

    def get_orders(self):
        return Order.query.all()
    
    def get_order(self, symbol, side):
        return Order.query.filter_by(symbol=symbol, side=side).first()

    def cancel_orders(self, symbol, side=None, order_id=None):
        q = Order.query.filter_by(symbol=symbol)
        if side:
            q = q.filter_by(side=side)
        if order_id:
            q = q.filter_by(order_id=order_id)
        orders = q.all()
        for o in orders:
            db.session.delete(o)
        db.session.commit()

    def remove_order(self, symbol, side):
        order = Order.query.filter_by(symbol=symbol, side=side).first()
        if order:
            db.session.delete(order)
            db.session.commit()

    def print_orders(self):
        orders = Order.query.all()
        for o in orders:
            logger.info(
                "%s (%s) - %s @ %.4f, %s, ID: %s",
                o.symbol,
                o.exchange,
                o.side.upper(),
                o.price,
                o.status,
                o.order_id or "N/A",
            )
