import os
import json
import logging

logger = logging.getLogger(__name__)

# This set tracks modes for which a warning about default keys has already been issued.
_warned_modes = set()

def load_api_keys():
    """Load API keys from ``api_keys.json``.

    The expected structure is::

        {
            "<exchange>": {
                "testnet": {"api_key": "...", "secret_key": "..."},
                "real": {"api_key": "...", "secret_key": "..."}
            }
        }

    If an old style file is detected it will be migrated automatically.
    """

    api_keys_file = "api_keys.json"
    exchanges = ["binance", "bybit", "gateio", "bitmart"]

    def _default_for(ex):
        test_key_env = {
            "binance": "BINANCE_TESTNET_API_KEY",
        }.get(ex, "")

        test_secret_env = {
            "binance": "BINANCE_TESTNET_SECRET_KEY",
        }.get(ex, "")

        real_key_env = {
            "binance": "BINANCE_REAL_API_KEY",
            "bybit": "BYBIT_REAL_API_KEY",
            "gateio": "GATEIO_REAL_API_KEY",
            "bitmart": "BITMART_REAL_API_KEY",
        }.get(ex, "")

        real_secret_env = {
            "binance": "BINANCE_REAL_SECRET_KEY",
            "bybit": "BYBIT_REAL_SECRET_KEY",
            "gateio": "GATEIO_REAL_SECRET_KEY",
            "bitmart": "BITMART_REAL_SECRET_KEY",
        }.get(ex, "")

        uid_env = {
            "bitmart": "BITMART_UID",
        }.get(ex, "")

        data = {
            "real": {
                "api_key": os.getenv(real_key_env, "your_real_api_key"),
                "secret_key": os.getenv(real_secret_env, "your_real_secret"),
                "uid": os.getenv(uid_env, "") if uid_env else "",
            },
        }
        if ex == "binance":
            data["testnet"] = {
                "api_key": os.getenv(test_key_env, "your_testnet_api_key"),
                "secret_key": os.getenv(test_secret_env, "your_testnet_secret"),
                "uid": "",
            }
        return data

    default_keys = {ex: _default_for(ex) for ex in exchanges}

    if os.path.exists(api_keys_file):
        with open(api_keys_file, "r") as f:
            try:
                keys = json.load(f)
            except json.JSONDecodeError:
                logger.error(f"Error decoding {api_keys_file}. Using default keys structure.")
                keys = default_keys # Fallback to default structure on decode error
    else:
        keys = default_keys # Initialize with default if file doesn't exist

    # Ensure the file exists with default content if it was missing or corrupt
    if not os.path.exists(api_keys_file) or "_env_variables" not in keys: # A simple check if it's an old format or freshly made
        # This part handles migration or creation of a new file with defaults
        # Let's refine the logic for creating/migrating

        # If file existed but was corrupt and got replaced by default_keys, or if file didn't exist:
        if not os.path.exists(api_keys_file) or (os.path.exists(api_keys_file) and keys == default_keys) :
             with open(api_keys_file, "w") as f:
                json.dump(default_keys, f, indent=2)
             if not os.path.exists(api_keys_file): # only log if it was truly created
                logger.info(f"Created default {api_keys_file}. Please update with valid API keys.")
        else: # File existed and was loaded, check for migration
            # migrate old layout if necessary (original logic from utils.py)
            if "testnet" in keys or "real" in keys: # Heuristic for old top-level structure
                migrated = {ex: _default_for(ex) for ex in exchanges} # Start with fresh defaults
                # Carefully merge data from old structure
                if "binance" in migrated: # Ensure binance default structure exists
                    if "testnet" in keys and isinstance(keys["testnet"], dict):
                         migrated["binance"]["testnet"].update(keys["testnet"])
                    if "real" in keys and isinstance(keys["real"], dict):
                         migrated["binance"]["real"].update(keys["real"])

                for ex_key in keys: # Iterate over keys present in the loaded file
                    if ex_key in migrated and isinstance(keys[ex_key], dict) and "api_key" in keys[ex_key]: # Old flat structure per exchange
                        if ex_key == "binance": # if it's binance, it might be old testnet keys
                             # This part of original migration was a bit ambiguous.
                             # Assuming old flat keys for binance were for testnet if not otherwise specified.
                             # However, _default_for already sets up binance testnet/real.
                             # A direct update like this might be problematic if keys['binance'] was for 'real'.
                             # The original logic: migrated[ex]['testnet'].update(keys[ex])
                             # This seems safer if old binance keys were real:
                             # migrated[ex_key]['real'].update(keys[ex_key])
                             pass # Defaults for binance are already good, specific testnet/real handling above is better
                        elif ex_key in migrated: # For other exchanges, assume they were 'real'
                            migrated[ex_key]['real'].update(keys[ex_key])
                keys = migrated
                with open(api_keys_file, "w") as f:
                    json.dump(keys, f, indent=2)
                logger.info(f"Migrated {api_keys_file} to new multi-exchange format.")


    # Ensure every exchange and mode sub-dictionary exists to prevent KeyErrors later
    for ex_name in exchanges:
        keys.setdefault(ex_name, default_keys[ex_name])
        if ex_name == "binance":
            keys[ex_name].setdefault("testnet", default_keys[ex_name]["testnet"])
            keys[ex_name].setdefault("real", default_keys[ex_name]["real"])
        else: # For other exchanges, ensure 'real' mode structure
            keys[ex_name].setdefault("real", default_keys[ex_name]["real"])
            # Remove 'testnet' if it somehow exists for non-binance exchanges from old files
            if "testnet" in keys[ex_name] and ex_name != "binance":
                del keys[ex_name]["testnet"]


    # Warning for default/placeholder keys
    for ex_name in exchanges:
        modes_to_check = ["testnet", "real"] if ex_name == "binance" else ["real"]
        for mode in modes_to_check:
            current_keys = keys.get(ex_name, {}).get(mode, {})
            api_key = current_keys.get("api_key", "")
            secret_key = current_keys.get("secret_key", "")

            is_placeholder = (api_key.startswith("your_") or not api_key or
                              secret_key.startswith("your_") or not secret_key)

            if is_placeholder:
                # Use a more specific key for _warned_modes to avoid repeated warnings for same exchange/mode
                warning_key = f"{ex_name}_{mode}"
                if warning_key not in _warned_modes:
                    logger.warning(
                        "Using default or placeholder API keys for %s %s. "
                        "Please update %s or relevant environment variables.",
                        ex_name.capitalize(), mode, api_keys_file
                    )
                    _warned_modes.add(warning_key)
    return keys
