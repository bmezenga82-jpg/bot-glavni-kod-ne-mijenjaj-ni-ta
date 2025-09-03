from core.extensions import db
from datetime import datetime

class ProfitLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    symbol = db.Column(db.String(20), nullable=False)
    buy_price = db.Column(db.Float, nullable=False)
    sell_price = db.Column(db.Float, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    profit_usdt = db.Column(db.Float, nullable=False)
    exchange = db.Column(db.String(50), nullable=False, default='binance')
    # It's good to be explicit about nullable, even if default is set.
    # For mode, 'real' or 'testnet'
    trading_mode = db.Column(db.String(10), nullable=False, default='testnet')

class Position(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(20), nullable=False, unique=True)
    amount = db.Column(db.Float, nullable=False)
    buy_price = db.Column(db.Float, nullable=False)

class TradeLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    symbol = db.Column(db.String(20), nullable=False)
    side = db.Column(db.String(4), nullable=False)  # 'buy' or 'sell'
    price = db.Column(db.Float, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    usdt_value = db.Column(db.Float, nullable=False)
    exchange = db.Column(db.String(50), default='binance')
    trading_mode = db.Column(db.String(10), nullable=False, default='testnet')

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(20), nullable=False)
    side = db.Column(db.String(4), nullable=False)  # 'buy' or 'sell'
    price = db.Column(db.Float, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    exchange = db.Column(db.String(50), default='binance')
    filled = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(20), default='open')  # open, filled, canceled
    order_id = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class TradingPair(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(20), nullable=False)
    exchange = db.Column(db.String(50), nullable=False, default='binance')
    amount = db.Column(db.Float, nullable=False)
    buy_percentage = db.Column(db.Float, nullable=False)
    sell_percentage = db.Column(db.Float, nullable=False)
    trading_mode = db.Column(db.String(10), default='testnet')
    profit_mode = db.Column(db.String(10), nullable=False, default='usdc')

    __table_args__ = (
        db.UniqueConstraint('symbol', 'exchange', name='uix_symbol_exchange'),
    )


class PairProfit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pair_id = db.Column(db.Integer, db.ForeignKey('trading_pair.id'), nullable=False)
    exchange = db.Column(db.String(50), nullable=False, default='binance')
    trading_mode = db.Column(db.String(10), nullable=False, default='testnet')
    profit_usdc = db.Column(db.Float, nullable=False, default=0.0)
    profit_crypto = db.Column(db.Float, nullable=False, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    pair = db.relationship('TradingPair', backref=db.backref('pair_profit', uselist=False))
