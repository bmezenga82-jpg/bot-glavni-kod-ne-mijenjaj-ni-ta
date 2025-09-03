# 🪙 CryptoBot

A Flask-based cryptocurrency trading assistant with real-time price updates, authentication, and portfolio tracking.

---

## 🚀 Features

- User authentication (Flask-Login)
- Real-time price updates via WebSockets (Flask-SocketIO)
- Portfolio tracking with profit logging
- SQLAlchemy ORM and Flask-Migrate
- REST API endpoints

---

## 📦 Requirements

- Python 3.9+
- `pip`
- A virtual environment (recommended)

---

## 🔧 Setup Instructions

### 1. Clone the Repository

```bash
git clone git@github.com:betaways01/CryptoBot.git
cd cryptobot
```

### 2. Create and Activate a Virtual Environment

```bash
python -m venv venv
source venv/bin/activate      # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure API Keys

Provide API credentials either through environment variables or by copying
`api_keys.example.json` to `api_keys.json` and filling in your details. The
application will raise an error if any required key is missing.

For Binance use `BINANCE_TESTNET_API_KEY`, `BINANCE_TESTNET_SECRET_KEY`,
`BINANCE_REAL_API_KEY` and `BINANCE_REAL_SECRET_KEY`.

For Bybit, Gate.io and Bitmart provide real API keys only:
`BYBIT_REAL_API_KEY`/`BYBIT_REAL_SECRET_KEY`,
`GATEIO_REAL_API_KEY`/`GATEIO_REAL_SECRET_KEY`,
`BITMART_REAL_API_KEY`/`BITMART_REAL_SECRET_KEY`.
Bitmart also requires a `BITMART_UID` value which can be supplied via the
environment variable of the same name or inside the `uid` field of
`api_keys.json`.

Recognized environment variables:

- `BINANCE_TESTNET_API_KEY` / `BINANCE_TESTNET_SECRET_KEY`
- `BINANCE_REAL_API_KEY` / `BINANCE_REAL_SECRET_KEY`
- `BYBIT_REAL_API_KEY` / `BYBIT_REAL_SECRET_KEY`
- `GATEIO_REAL_API_KEY` / `GATEIO_REAL_SECRET_KEY`
- `BITMART_REAL_API_KEY` / `BITMART_REAL_SECRET_KEY`
- `BITMART_UID`

Only Binance supports testnet mode; other exchanges always operate in real
trading. The bot supports Binance, Bybit, Gate.io and Bitmart. Make sure to set
the relevant credentials before running the application.

Use the `/api/exchange_pairs` endpoint (for example `/api/exchange_pairs?exchange=binance`) to discover
which symbols are available on a particular exchange. You can also browse pairs via the **Settings** page.
Unsupported pairs will result in "Symbol not found" warnings and missing price data.

### 5. Initialize the Database

```bash
flask db migrate -m "Your message"
flask db upgrade
```

### Database Settings

You can tune SQLAlchemy's connection pool in `config.yaml`:

```yaml
database:
  engine: sqlite
  path: sqlite:///mydatabase.db
  pool_size: 20     # default is 5
  max_overflow: 40  # default is 10
```

If you run many pairs simultaneously, consider increasing these values but stay within your database's limits.

### 6. Run the App

```bash
python app.py  # or flask run
```

Once you open the web interface and log in, the server will start streaming
real-time prices to any connected clients.


