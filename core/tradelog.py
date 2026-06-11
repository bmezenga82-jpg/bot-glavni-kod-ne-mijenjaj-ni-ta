import logging
from .models import TradeLog
from core.extensions import db
from datetime import datetime

logger = logging.getLogger(__name__)

class TradeLogger:
    def log(
        self,
        symbol: str,
        side: str,
        price: float,
        amount: float,
        exchange: str = "binance",
        trading_mode: str = "testnet",
    ) -> None:
        usdt_value = round(price * amount, 2)
        entry = TradeLog(
            timestamp=datetime.utcnow(),
            symbol=symbol,
            side=side,
            price=round(price, 8),
            amount=round(amount, 8),
            usdt_value=usdt_value,
            exchange=exchange,
            trading_mode=trading_mode,
        )
        try:
            db.session.add(entry)
            db.session.commit()
        except Exception as e:
            logger.error(f"TradeLog DB write failed for {side} {symbol}: {e}")
            db.session.rollback()
