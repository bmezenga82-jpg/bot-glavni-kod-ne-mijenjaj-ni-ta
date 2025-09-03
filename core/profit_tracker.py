import csv
from datetime import datetime
import os
import threading
import logging
from core.extensions import db
from core.models import ProfitLog, PairProfit, TradingPair

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ProfitTracker:
    def __init__(self, log_file: str = "profit_log.csv"):
        self.log_file = log_file
        self._lock = threading.Lock()
        if not os.path.exists(self.log_file):
            with open(self.log_file, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp",
                    "symbol",
                    "buy_price",
                    "sell_price",
                    "amount",
                    "profit_usdt",
                    "exchange",
                    "trading_mode",
                ])

    def log_profit(self, symbol, buy_price, sell_price, amount, exchange: str, trading_mode: str, pair_id: int | None = None, retained_qty: float = 0.0, profit_mode: str = 'usdc'):
        profit = (sell_price - buy_price) * amount
        with self._lock, open(self.log_file, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.utcnow().isoformat(),
                symbol,
                buy_price,
                sell_price,
                amount,
                round(profit, 6),
                exchange,
                trading_mode,
            ])

        entry = ProfitLog(
            symbol=symbol,
            buy_price=buy_price,
            sell_price=sell_price,
            amount=amount,
            profit_usdt=round(profit, 6),
            exchange=exchange,
            trading_mode=trading_mode,
        )
        try:
            db.session.add(entry)
            if pair_id is not None:
                pair_profit = PairProfit.query.filter_by(pair_id=pair_id).first()
                if pair_profit is None:
                    pair = TradingPair.query.get(pair_id)
                    pair_profit = PairProfit(
                        pair_id=pair_id,
                        exchange=exchange,
                        trading_mode=trading_mode,
                    )
                    db.session.add(pair_profit)
                pair_profit.profit_usdc += profit
                if profit_mode == 'crypto':
                    pair_profit.profit_crypto += retained_qty
                pair_profit.updated_at = datetime.utcnow()
            db.session.commit()
        except Exception as e:  # pragma: no cover - skip if DB not configured
            logger.warning("DB logging skipped: %s", e)

    def get_total_profit(self):
        if self.log_file:
            if not os.path.exists(self.log_file):
                return 0.0
            with open(self.log_file, newline="") as f:
                reader = csv.DictReader(f)
                total = sum(float(row["profit_usdt"]) for row in reader)
            return round(total, 6)
        total = db.session.query(db.func.sum(ProfitLog.profit_usdt)).scalar()
        return round(total or 0.0, 6)

    def get_symbol_profit(self, symbol):
        if self.log_file:
            if not os.path.exists(self.log_file):
                return 0.0
            with open(self.log_file, newline="") as f:
                reader = csv.DictReader(f)
                total = sum(float(row["profit_usdt"]) for row in reader if row["symbol"] == symbol)
            return round(total, 6)
        total = db.session.query(db.func.sum(ProfitLog.profit_usdt)).filter_by(symbol=symbol).scalar()
        return round(total or 0.0, 6)

    def reset_profit(self, pair_id: int):
        """Reset profit totals for the given trading pair."""
        try:
            pair_profit = PairProfit.query.filter_by(pair_id=pair_id).first()
            if pair_profit:
                pair_profit.profit_usdc = 0.0
                pair_profit.profit_crypto = 0.0
                pair_profit.updated_at = datetime.utcnow()
                db.session.commit()
                return True
            return False
        except Exception as e:  # pragma: no cover - DB might be misconfigured
            logger.warning("Profit reset failed: %s", e)
            db.session.rollback()
            return False

    def get_all_pair_profits(self):
        """Return profit summary for all pairs grouped by exchange/mode."""
        try:
            profits = PairProfit.query.all()
            grouped: dict[str, list[dict]] = {}
            for p in profits:
                key = f"{p.exchange}_{p.trading_mode}"
                grouped.setdefault(key, []).append(
                    {
                        "pair_id": p.pair_id,
                        "symbol": p.pair.symbol if p.pair else "",
                        "profit_usdc": round(p.profit_usdc, 6),
                        "profit_crypto": round(p.profit_crypto, 6),
                    }
                )
            return grouped
        except Exception as e:  # pragma: no cover
            logger.warning("Fetching pair profits failed: %s", e)
            return {}

    def remove_pair_profit(self, pair_id: int) -> bool:
        """Delete profit record for a trading pair."""
        try:
            deleted = PairProfit.query.filter_by(pair_id=pair_id).delete()
            db.session.commit()
            return bool(deleted)
        except Exception as e:  # pragma: no cover
            logger.warning("Pair profit removal failed: %s", e)
            db.session.rollback()
            return False
