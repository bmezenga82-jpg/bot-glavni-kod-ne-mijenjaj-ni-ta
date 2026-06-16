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
    profit_usdc = db.Column(db.Float, nullable=False, default=0.0)       # realized USDC profit (usdc mode only)
    profit_usdc_equiv = db.Column(db.Float, nullable=False, default=0.0) # USDC equivalent from crypto mode trades
    profit_crypto = db.Column(db.Float, nullable=False, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    pair = db.relationship('TradingPair', backref=db.backref('pair_profit', uselist=False))


class Portfolio(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    threshold_pct = db.Column(db.Float, default=5.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    holdings = db.relationship('PortfolioHolding', backref='portfolio', lazy=True, cascade='all, delete-orphan')


class PortfolioHolding(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    portfolio_id = db.Column(db.Integer, db.ForeignKey('portfolio.id'), nullable=False)
    symbol = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(100), default='')
    amount = db.Column(db.Float, nullable=False, default=0.0)
    target_pct = db.Column(db.Float, default=0.0)
    include_rebalancing = db.Column(db.Boolean, default=True)

    __table_args__ = (db.UniqueConstraint('portfolio_id', 'symbol', name='uix_portfolio_symbol'),)


class GlobalTarget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(20), nullable=False, unique=True)
    target_pct = db.Column(db.Float, default=0.0)
    include_rebalancing = db.Column(db.Boolean, default=True)


class BacktestFolder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('backtest_folder.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    children = db.relationship('BacktestFolder', backref=db.backref('parent', remote_side='BacktestFolder.id'))


class BacktestResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    symbol = db.Column(db.String(20), nullable=False)
    exchange = db.Column(db.String(50), nullable=False)
    buy_pct = db.Column(db.Float, nullable=False)
    sell_pct = db.Column(db.Float, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    total_capital = db.Column(db.Float, nullable=False)
    timeframe = db.Column(db.String(10), nullable=False, default='1h')
    start_date = db.Column(db.String(10))
    end_date = db.Column(db.String(10))
    profit_mode = db.Column(db.String(10), default='usdc')
    folder_id = db.Column(db.Integer, db.ForeignKey('backtest_folder.id'), nullable=True)
    net_profit = db.Column(db.Float)
    total_pnl = db.Column(db.Float)
    roi_pct = db.Column(db.Float)
    annualized_roi = db.Column(db.Float)
    trade_count = db.Column(db.Integer)
    open_positions = db.Column(db.Integer)
    period_days = db.Column(db.Integer)
