# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Database setup (first time or after model changes)
flask db migrate -m "description"
flask db upgrade

# Run the app (local dev)
python app.py

# Production (Azure / gunicorn)
gunicorn --worker-class eventlet -w 1 app:app --bind=0.0.0.0:$PORT

# Run backtest directly (without web UI)
python run_backtest.py
```

## Architecture

### App startup
`app.py` → `factory.create_app()` → initialises Flask extensions (SQLAlchemy, Flask-Migrate, SocketIO, Flask-Login, Bcrypt) → registers all routes via `core/routes.py:register_routes()`. The app reads config from `settings.yaml` (generated at runtime from DB state) or falls back to `config.yaml`.

### Trading loop
`modules/bot_control.py:BotManager` manages one daemon thread per trading pair. Each thread runs `main.py:trade_loop()`. The loop executes the cyclic grid strategy:
1. Market buy to start cycle
2. Place limit sell at `+sell_pct%` and limit buy at `-buy_pct%`
3. When sell fills → cancel buy → restart
4. When buy fills → add new position lot, place new sell + lower buy

`buy_percentage` is always stored as a **negative** number in the DB and `settings.yaml` (e.g. `-1.0` = 1% below). `main.py` always calls `abs()` on it before use.

### Exchange layer
`core/exchange.py:ExchangeConnector` wraps CCXT. Each exchange has quirks handled here:
- **Binance**: `quoteOrderQty` param for market buys, `set_sandbox_mode(True)` for testnet
- **Gate.io**: `create_market_buy_order` with quote amount directly
- **Bitmart**: `notional` param with Decimal-formatted string; parses balance from `info.data.wallet`
- **Bybit**: order status checks must fall back through open→closed→fetchOrder due to API limitations

`modules/exchange_config.py:ExchangeConfig.setup_exchange()` produces the `(exchange_id, params)` tuple that `ExchangeConnector` expects.

### Data flow for the dashboard
`/api/data` → `modules/data.py:get_data()` → uses `ThreadPoolExecutor` to fetch balances/P&L concurrently across exchanges → returns JSON polled by the frontend. Live prices are pushed via SocketIO from a background thread (`factory.py:stream_prices`) that runs only while clients are connected.

### Database models (`core/models.py`)
- `TradingPair` – configured pairs with exchange, amounts, percentages, profit mode
- `ProfitLog` – completed sell trades with profit per cycle
- `TradeLog` – raw buy/sell events
- `Order` – open order tracking (mirrors `core/order.py` in-memory state)
- `PairProfit` – cumulative profit per pair (also tracked in-memory by `core/profit_tracker.py`)
- `Position` – currently held base-asset positions

### Profit modes
Each pair has a `profit_mode`:
- `usdc` – sell entire position, all profit in USDC
- `crypto` – sell only enough to recover the USDC cost; keep the rest as base asset

### Backtest (`core/backtester.py`)
`_simulate_grid()` is the core simulation. It uses candle `high`/`low` (not close) to detect limit order fills and mirrors the actual `trade_loop` logic. `buy_pct` and `sell_pct` are passed as **positive** values; signs are applied internally. Default timeframe is `1h`. OHLCV is fetched in 1000-candle batches to cover the full requested range.

### Configuration
`settings.yaml` is the live config file (auto-generated from DB via `modules/settings.py:save_settings_yaml()`). `config.yaml` is the static fallback/seed. API credentials are read from `api_keys.json` or environment variables (see README for variable names). Only Binance supports testnet; other exchanges always use real mode.

### Frontend JS
`static/js/scripts.js` is the entry point; it conditionally imports and wires up modules from `static/js/modules/`. Bot start/stop calls `POST /api/control` with `{action, pair_id}`. Price updates are received over SocketIO `price_update` events.
