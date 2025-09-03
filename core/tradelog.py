from .models import TradeLog
from core.extensions import db
from datetime import datetime

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
            price=round(price, 4),
            amount=round(amount, 2),
            usdt_value=usdt_value,
            exchange=exchange,
            trading_mode=trading_mode,
        )
        db.session.add(entry)
        db.session.commit()

