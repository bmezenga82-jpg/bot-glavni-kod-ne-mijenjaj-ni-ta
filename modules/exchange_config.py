import logging
import os
# from modules.utils import load_api_keys # Old import
from modules.key_loader import load_api_keys # New import

class ExchangeConfig:
    """Utility to configure CCXT exchanges with API keys from environment vars."""

    @staticmethod
    def setup_exchange(exchange_name: str, is_testnet: bool = False, api_keys_override: dict | None = None):
        """Return a tuple of (exchange_id, params) for ``ExchangeConnector``.

        Parameters
        ----------
        exchange_name: str
            Name of the exchange.
        is_testnet: bool
            Whether to configure for testnet.
        api_keys_override: dict | None, optional
            If provided, this dictionary will be used instead of calling load_api_keys().
        """
        exchange_name = exchange_name.lower()

        keys = api_keys_override if api_keys_override is not None else load_api_keys()
        mode = "testnet" if is_testnet else "real"

        key_env = {
            "binance": {"testnet": "BINANCE_TESTNET_API_KEY", "real": "BINANCE_REAL_API_KEY"},
            "bybit": {"real": "BYBIT_REAL_API_KEY"},
            "gateio": {"real": "GATEIO_REAL_API_KEY"},
            "bitmart": {"real": "BITMART_REAL_API_KEY"},
        }

        secret_env = {
            "binance": {"testnet": "BINANCE_TESTNET_SECRET_KEY", "real": "BINANCE_REAL_SECRET_KEY"},
            "bybit": {"real": "BYBIT_REAL_SECRET_KEY"},
            "gateio": {"real": "GATEIO_REAL_SECRET_KEY"},
            "bitmart": {"real": "BITMART_REAL_SECRET_KEY"},
        }

        uid_env = {"bitmart": "BITMART_UID"}

        if exchange_name not in key_env:
            raise ValueError(f"Unsupported exchange: {exchange_name}")

        if mode not in key_env[exchange_name]:
            raise ValueError(f"Unsupported mode '{mode}' for exchange: {exchange_name}. This exchange only supports: {list(key_env[exchange_name].keys())}")

        api_key_from_file = keys.get(exchange_name, {}).get(mode, {}).get("api_key")
        api_secret_from_file = keys.get(exchange_name, {}).get(mode, {}).get("secret_key")
        uid_from_file = keys.get(exchange_name, {}).get(mode, {}).get("uid", "")

        api_key = api_key_from_file or os.getenv(key_env[exchange_name][mode])
        api_secret = api_secret_from_file or os.getenv(secret_env[exchange_name][mode])
        uid = uid_from_file or os.getenv(uid_env.get(exchange_name, ""), "")

        logger = logging.getLogger(__name__)
        if api_key_from_file:
            logger.debug("Using API key from api_keys.json for %s %s", exchange_name, mode)
        else:
            logger.debug(
                "Using API key from environment variable %s for %s %s",
                key_env[exchange_name][mode],
                exchange_name,
                mode,
            )

        if api_secret_from_file:
            logger.debug("Using API secret from api_keys.json for %s %s", exchange_name, mode)
        else:
            logger.debug(
                "Using API secret from environment variable %s for %s %s",
                secret_env[exchange_name][mode],
                exchange_name,
                mode,
            )

        uid_key = uid_env.get(exchange_name, "")
        if uid_from_file:
            logger.debug("Using UID from api_keys.json for %s %s", exchange_name, mode)
        elif uid_key:
            logger.debug(
                "Using UID from environment variable %s for %s %s",
                uid_key,
                exchange_name,
                mode,
            )

        if not api_key or not api_secret or (api_key and api_key.startswith("your_")) or (api_secret and api_secret.startswith("your_")):
            raise RuntimeError(
                f"Missing API credentials for {exchange_name} {mode}. Set the appropriate environment variables or update api_keys.json."
            )

        params = {"apiKey": api_key, "secret": api_secret, "enableRateLimit": True}

        if exchange_name == "binance" and is_testnet:
            # Remove explicit URL setting; rely on set_sandbox_mode(True) in ExchangeConnector
            # params["urls"] = {"api": "https://testnet.binance.vision/api"}
            current_options = params.setdefault('options', {})
            current_options.update({
                'defaultType': 'spot',
                'fetchCurrencies': False
            })
            params['_force_sandbox_mode'] = True # Custom flag for ExchangeConnector
            # This aims to prevent errors during load_markets if fetch_currencies causes SAPI issues.
            # fetch_balance itself might still attempt SAPI calls.

        if exchange_name == "gateio":
            # For market buy orders with quote currency amount passed as 'amount'
            current_options = params.setdefault('options', {})
            current_options.update({
                'createMarketBuyOrderRequiresPrice': False
            })

        if exchange_name == "bitmart":
            params["uid"] = uid
            params.setdefault("memo", "")

        return exchange_name, params
