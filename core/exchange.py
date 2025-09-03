import ccxt  # type: ignore
from ccxt.base.errors import AuthenticationError
import os
import logging
import time
import re
from decimal import Decimal, ROUND_DOWN, InvalidOperation

logger = logging.getLogger(__name__)

MIN_NOTIONAL = 6.0


class ExchangeConnector:
    def __init__(self, exchange_id: str, params: dict | None = None):
        """Initialize a CCXT exchange instance.

        Parameters
        ----------
        exchange_id: str
            Name of the exchange (e.g. ``"binance"``).
        params: dict | None, optional
            Parameters to pass to the exchange constructor. This should include
            API keys, URLs for testnets, UID for Bitmart, etc., typically
            provided by `ExchangeConfig.setup_exchange`.
        """
        exchange_class = getattr(ccxt, exchange_id)
        config = {'enableRateLimit': True}

        # Default to 'spot' type for known spot exchanges if not specified in params
        spot_exchanges = {'binance', 'bybit', 'gateio', 'bitmart'}
        if exchange_id in spot_exchanges:
            current_options = params.get('options', {}) if params else {}
            if 'defaultType' not in current_options:
                config.setdefault('options', {}).update({'defaultType': 'spot'})

        if params:
            config.update(params)

        # Ensure 'apiKey' and 'secret' are in config if provided directly in params
        # or handled by ExchangeConfig.setup_exchange.
        # No need for separate api_key, secret args or env var lookups here,
        # as ExchangeConfig.setup_exchange should prepare these in `params`.

        self.exchange = exchange_class(config)
        self.exchange_id = exchange_id # Store for logging/identification

        # Apply sandbox mode if flagged by config, specifically for Binance
        if self.exchange_id == 'binance' and config.get('_force_sandbox_mode') is True:
            if hasattr(self.exchange, 'set_sandbox_mode'):
                try:
                    self.exchange.set_sandbox_mode(True)
                    logger.info(f"Binance: Sandbox mode enabled via set_sandbox_mode(True)")
                except Exception as e:
                    logger.error(f"Binance: Error calling set_sandbox_mode(True): {e}")
            else:
                logger.warning("Binance: Connector instance does not have set_sandbox_mode method, though _force_sandbox_mode was true.")

        self._balance_errors: set[str] = set()
        self._price_errors: set[str] = set()
        #logger.info(f"Initialized {self.exchange_id} connector. Options: {self.exchange.options if hasattr(self.exchange, 'options') else 'N/A'}")
        logger.info(f"Initialized {self.exchange_id} connector.")

    def _sleep_on_rate_limit(self, exc: ccxt.RateLimitExceeded) -> None:
        """Sleep for the delay recommended by ``exc`` or the exchange rate limit."""
        timeout: float | None = getattr(exc, "retry_after", None)
        if timeout is None and exc.args:
            m = re.search(r"(\d+(?:\.\d+)?)", str(exc.args[0]))
            if m:
                try:
                    timeout = float(m.group(1))
                    if timeout > 1000:
                        timeout /= 1000.0
                except ValueError:
                    timeout = None
        if timeout is None:
            timeout = getattr(self.exchange, "rateLimit", 1000) / 1000.0
        logger.warning("Rate limit exceeded, sleeping for %.2f seconds", timeout)
        time.sleep(timeout)

    def _api_call(self, func, *args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ccxt.RateLimitExceeded as e:
            self._sleep_on_rate_limit(e)
            return func(*args, **kwargs)

    def get_price(self, symbol):
        """Return the last traded price for ``symbol``."""
        try:
            ticker = self._api_call(self.exchange.fetch_ticker, symbol)
            if isinstance(ticker, dict):
                return ticker.get("last")
            return None
        except Exception as e:
            msg = str(e)
            if msg not in self._price_errors:
                logger.error("Failed to fetch price for %s: %s", symbol, e)
                self._price_errors.add(msg)
            return None

    def market_buy(self, symbol, usdt_amount):
        usdt_amount = max(usdt_amount, MIN_NOTIONAL)
        # order_response = None # Moved declaration inside try block

        # Extract quote currency and check balance
        try:
            parts = symbol.split('/')
            if len(parts) != 2:
                logger.error(f"Invalid symbol format: {symbol}. Expected format 'BASE/QUOTE'.")
                return None
            base_currency, quote_currency = parts
        except Exception as e: # Catch any other errors during split
            logger.error(f"Error processing symbol {symbol}: {e}")
            return None

        available_balance = self.get_balance(quote_currency)

        if available_balance is None:
            logger.error(f"Failed to fetch balance for {quote_currency} on {self.exchange_id}. Cannot proceed with market buy for {symbol}.")
            return None
        
        if isinstance(available_balance, str) and available_balance == "AUTH_ERROR":
            logger.error(f"Authentication error while fetching {quote_currency} balance on {self.exchange_id} for {symbol}. Cannot place order.")
            return None

        if not isinstance(available_balance, (float, int)):
            logger.error(f"Received non-numeric balance for {quote_currency} on {self.exchange_id}: {available_balance} (type: {type(available_balance)}). Cannot proceed with market buy for {symbol}.")
            return None

        if available_balance < usdt_amount:
            logger.warning(f"Insufficient {quote_currency} balance on {self.exchange_id} to buy {symbol}. Required: {usdt_amount:.2f}, Available: {available_balance:.2f}")
            return {
                'error': 'INSUFFICIENT_FUNDS',
                'symbol': symbol,
                'exchange': self.exchange_id,
                'required': usdt_amount,
                'available': available_balance
            }

        # Get current price for logging and for exchanges that need base quantity calculated
        price_before_order = self.get_price(symbol)
        order_response = None # Initialize order_response here

        try:
            # For exchanges that support buying with quote currency directly (e.g., 'notional' or 'quoteOrderQty')
            if self.exchange_id == 'bitmart':
                logger.info(f"Attempting Bitmart market buy for {symbol} with notional (quote) amount {usdt_amount}")
            
                # Load markets to ensure valid market data
                try:
                    if not self.exchange.markets:
                        self.exchange.load_markets()
                    if symbol not in self.exchange.markets:
                        self.exchange.load_markets(reload=True)
                except Exception as e:
                    logger.error(f"Failed to load markets for {symbol} on {self.exchange_id}: {e}")
                    return None
            
                # Verify market data exists
                if symbol not in self.exchange.markets:
                    logger.error(f"Market {symbol} not found on {self.exchange_id}")
                    return None
            
                # Get price precision from market info
                market = self.exchange.markets[symbol]
                price_precision_raw = market.get('info', {}).get('price_min_precision', 2)
                try:
                    price_precision = int(price_precision_raw)
                except (ValueError, TypeError):
                    logger.warning(f"Invalid price_min_precision for {symbol}: {price_precision_raw}. Using default 2.")
                    price_precision = 2
            
                # Validate notional against minimum buy amount
                min_buy_amount = float(market.get('info', {}).get('min_buy_amount', 5.0))
                if usdt_amount < min_buy_amount:
                    logger.error(f"Notional amount {usdt_amount} is below minimum buy amount {min_buy_amount} for {symbol}")
                    return None
            
                # Format notional with Decimal for precision stability
                try:
                    quant = Decimal(1) / (10 ** price_precision)
                    notional_decimal = Decimal(str(usdt_amount)).quantize(quant, rounding=ROUND_DOWN)
                    notional_str = f"{notional_decimal:.{price_precision}f}"

                    # PROPOSED ADDITION: Validate notional_str before passing to CCXT
                    if not notional_str or not isinstance(notional_str, str):
                        logger.error(
                            f"CRITICAL: Invalid notional_str generated (empty or not string): '{notional_str}' "
                            f"(type: {type(notional_str)}) for symbol {symbol}, usdt_amount {usdt_amount}. Aborting Bitmart order."
                        )
                        return None
                    try:
                        Decimal(notional_str)  # Test conversion
                    except InvalidOperation:
                        logger.error(
                            f"CRITICAL: Generated notional_str '{notional_str}' is not convertible to Decimal "
                            f"for symbol {symbol}, usdt_amount {usdt_amount}. Aborting Bitmart order.",
                            exc_info=True
                        )
                        return None

                    logger.info(
                        f"Prepared notional_str for Bitmart: '{notional_str}' (from usdt_amount: {usdt_amount}) for symbol {symbol}. "
                        f"Type: {type(notional_str)}"
                    )

                except (InvalidOperation, ValueError) as e: # This existing block catches errors during notional_decimal/notional_str generation
                    logger.error(f"Failed to format notional for {symbol}, usdt_amount {usdt_amount}: {e}", exc_info=True)
                    return None
            
                # Execute market buy order
                try:
                    order_response = self._api_call(
                        self.exchange.create_order,
                        symbol=symbol,
                        type='market',
                        side='buy',
                        amount=None,
                        price=None,
                        params={'notional': notional_str} # Use the validated notional_str
                    )
                    logger.debug(f"Order response for {symbol}: {order_response}")
                except Exception as e:
                    logger.error(f"Market buy failed for {symbol} on {self.exchange_id} with notional amount {usdt_amount}: {e}", exc_info=True)
                    return None


            elif self.exchange_id == 'gateio':
                logger.info(f"Attempting Gate.io market buy for {symbol} with quote amount {usdt_amount}")
                order_response = self._api_call(self.exchange.create_market_buy_order, symbol, usdt_amount)
            
            elif self.exchange_id == 'binance':
                # Binance supports quoteOrderQty. CCXT typically handles this if create_market_buy_order is used
                # with amount=None and 'quoteOrderQty' in params.
                # Some versions of CCXT might have create_market_buy_order_with_cost or similar,
                # but relying on params={'quoteOrderQty': usdt_amount} is generally safer for broader compatibility.
                logger.info(f"Attempting Binance market buy for {symbol} with quoteOrderQty {usdt_amount}")
                order_response = self._api_call(self.exchange.create_market_buy_order, symbol, None, params={'quoteOrderQty': usdt_amount})
            
            # Add other exchanges that support direct quote currency buys here, e.g., Bybit
            # elif self.exchange_id == 'bybit':
            #     logger.info(f"Attempting Bybit market buy for {symbol} with quote amount {usdt_amount}")
            #     # Bybit's API for market buy with quote: check CCXT documentation.
            #     # It might be through params like {'cost': usdt_amount} or a specific method.
            #     # This is a placeholder:
            #     # order_response = self._api_call(self.exchange.create_market_buy_order, symbol, None, params={'cost': usdt_amount})
            #     # If Bybit (or others) strictly require base quantity, they will fall into the 'else' block.

            else: # Default logic for other exchanges or those requiring base quantity calculation
                logger.info(f"Attempting market buy for {symbol} on {self.exchange_id} with quote amount {usdt_amount} (calculating base qty)")
                if not price_before_order or price_before_order <= 0:
                    logger.error(f"Market buy failed for {self.exchange_id} {symbol}: unable to fetch valid current price ({price_before_order}) to calculate base quantity.")
                    return None 

                base_qty_calculated = usdt_amount / price_before_order

                try:
                    if not self.exchange.markets: self.exchange.load_markets()
                    if symbol not in self.exchange.markets: self.exchange.load_markets(reload=True)

                    precision_amount_digits = 8 # Default if not found
                    if symbol in self.exchange.markets and self.exchange.markets[symbol].get('precision', {}).get('amount') is not None:
                        # CCXT's amount_to_precision takes number of decimal places or a tick size.
                        # We need the number of decimal places for amount.
                        # If precision['amount'] is like 0.001, we need to convert to number of decimal places.
                        # For simplicity, let's assume precision['amount'] gives the digits if it's an int, or we use a default.
                        # A more robust way is to use decimal_to_precision with ccxt.DECIMAL_PLACES.
                        # The existing code used amount_to_precision directly, which is fine if the value is the number of decimal places.
                        # Let's stick to amount_to_precision if the structure implies it's the number of decimal places.
                        # However, the fallback decimal_to_precision is more robust.

                        # Try to get precision.amount (usually the tick size for amount)
                        raw_precision_amount = self.exchange.markets[symbol]['precision'].get('amount')
                        if isinstance(raw_precision_amount, (int, float)): # If it's a number like 0.001 or 1e-8
                             # Convert tick size to decimal places if necessary, or use if it's already decimal places.
                             # CCXT's amount_to_precision expects the number of decimal places or the tick size.
                             # It's safer to use self.exchange.amount_to_precision as it handles both.
                            qty_to_order_str = self.exchange.amount_to_precision(symbol, base_qty_calculated)
                            qty_to_order = float(qty_to_order_str)
                        else: # Fallback if precision is not directly usable as number of decimal places
                            logger.warning(f"Precision for amount for {symbol} on {self.exchange_id} is not a direct number ({raw_precision_amount}). Using decimal_to_precision with default {precision_amount_digits} digits.")
                            qty_to_order = float(self.exchange.decimal_to_precision(base_qty_calculated, ccxt.TRUNCATE, precision_amount_digits, ccxt.DECIMAL_PLACES))

                    else: # Fallback if market or precision info is missing
                        logger.warning(f"Market or precision info for amount not found for {symbol} on {self.exchange_id}. Using decimal_to_precision with default {precision_amount_digits} digits.")
                        qty_to_order = float(self.exchange.decimal_to_precision(base_qty_calculated, ccxt.TRUNCATE, precision_amount_digits, ccxt.DECIMAL_PLACES))

                except Exception as e_precision:
                    logger.error(f"Error applying precision for {symbol} on {self.exchange_id}: {e_precision}. Using float value after basic rounding. Qty: {base_qty_calculated}", exc_info=True)
                    qty_to_order = round(base_qty_calculated, 8) # Fallback to simple rounding

                logger.info(f"Calculated base quantity {qty_to_order} for {usdt_amount} {quote_currency} on {self.exchange_id} {symbol} at price {price_before_order}")
                if qty_to_order <= 0:
                    logger.error(f"Calculated quantity {qty_to_order} is too small for {usdt_amount} {quote_currency} at price {price_before_order} for {symbol} on {self.exchange_id}")
                    return None
                order_response = self._api_call(self.exchange.create_market_buy_order, symbol, qty_to_order)

            if not order_response or 'id' not in order_response:
                logger.error(f"Market buy order failed or did not return an ID on {self.exchange_id} for {symbol}. Response: {order_response}")
                return None

            filled_amount = order_response.get('filled', 0.0)
            # Use 'price' from order if available (actual fill price for market), else fallback to price_before_order
            avg_price_filled = order_response.get('price', order_response.get('average', price_before_order))
            cost = order_response.get('cost', 0.0)
            order_id = order_response['id']

            # If filled amount is not directly available, but cost is, estimate filled if possible (for some exchanges)
            if filled_amount == 0.0 and cost > 0 and avg_price_filled is not None and avg_price_filled > 0:
                filled_amount = cost / avg_price_filled

            # If filled is still 0, but we sent quote (e.g. gate, bitmart), assume full quote amount was targeted for filling
            # and actual base filled qty will come from order status checks.
            # For immediate return, if `filled_amount` is 0 from response, it's safer to report that.
            # The `qty_to_order` was for base qty orders.

            # Log actual cost if available and numeric, otherwise use the requested usdt_amount
            if cost is not None and cost > 0:
                log_usdt_amount = cost
            else:
                log_usdt_amount = usdt_amount

            logger.info(f"Market Buy order placed/filled for {self.exchange_id} {symbol}: "
                        f"ID {order_id}, Filled {filled_amount or 'N/A'} {symbol.split('/')[0]}, "
                        f"AvgPrice {avg_price_filled if avg_price_filled else 'N/A'}, Cost {log_usdt_amount:.2f} {symbol.split('/')[1]}")

            # Determine the cost to return: use actual cost if available and positive, else usdt_amount
            # This mirrors the logic for log_usdt_amount but ensures the returned 'cost' is also handled.
            returned_cost = cost if cost is not None and cost > 0 else usdt_amount

            return {
                'order_id': order_id,
                'average': avg_price_filled if avg_price_filled and avg_price_filled > 0 else price_before_order or 0.0,  # safer fallback
                'filled': (
                    filled_amount if filled_amount is not None and filled_amount > 0 else (
                        (usdt_amount / price_before_order)
                        if price_before_order and price_before_order > 0 and self.exchange_id not in ['bitmart', 'gateio']
                        else 0.0
                    )
                ),
                'cost': returned_cost if returned_cost is not None else usdt_amount
            }


        except Exception as e:
            logger.error(f"Market buy processing failed on {self.exchange_id} for {symbol}: {e}", exc_info=True)
            return None

    def market_sell(self, symbol, qty):
        try:
            qty = round(qty, 2)
            order = self._api_call(self.exchange.create_market_sell_order, symbol, qty)
            price = self.get_price(symbol)
            logger.info("Market Sell %.2f of %s", qty, symbol)
            return {
                'order_id': order['id'],
                'average': price,
                'filled': qty
            }
        except Exception as e:
            logger.error("Market sell failed: %s", e)
            return None

    def place_limit_order(self, symbol, side, price, qty):
        try:
            try:
                price = float(self.exchange.price_to_precision(symbol, price))
            except Exception:
                price = round(price, 4)

            try:
                qty = float(self.exchange.amount_to_precision(symbol, qty))
            except Exception:
                qty = round(qty, 2)

            if side == "buy":
                order = self._api_call(self.exchange.create_limit_buy_order, symbol, qty, price)
            elif side == "sell":
                order = self._api_call(self.exchange.create_limit_sell_order, symbol, qty, price)
            else:
                raise ValueError("Invalid order side")

            logger.info("Placing %s order on %s for %.2f at %.4f", side.upper(), symbol, qty, price)
            return {
                'order_id': order['id'],
                'price': price,
                'qty': qty,
                'status': order['status']
            }
        except Exception as e:
            logger.error("Limit order failed: %s", e)
            return None

    def cancel_order(self, order_id, symbol):
        try:
            self._api_call(self.exchange.cancel_order, order_id, symbol)
            logger.info("Cancelled order %s for %s", order_id, symbol)
        except Exception as e:
            logger.error("Failed to cancel order %s for %s: %s", order_id, symbol, e)

    def cancel_all_orders(self, symbol):
        try:
            open_orders = self._api_call(self.exchange.fetch_open_orders, symbol)
            for order in open_orders:
                self.cancel_order(order['id'], symbol)
            logger.info("Cancelled all open orders for %s", symbol)
        except Exception as e:
            logger.error("Failed to cancel orders for %s: %s", symbol, e)

    def check_order_status(self, order_id, symbol):
        order_data = None
        try:
            if self.exchange_id == 'bybit':
                logger.debug(f"Bybit: Checking order status for {order_id} in symbol {symbol}")
                # Try open orders first
                open_orders = self._api_call(self.exchange.fetch_open_orders, symbol)
                for order in open_orders:
                    if order['id'] == order_id:
                        order_data = order
                        logger.debug(f"Bybit: Order {order_id} found in open orders.")
                        break

                if not order_data:
                    # Try closed orders if not found in open
                    logger.debug(f"Bybit: Order {order_id} not in open orders, checking recent closed orders for {symbol}.")
                    # Fetch a limited number of recent closed orders to avoid fetching extensive history.
                    # The limit of 50 is arbitrary; adjust as needed.
                    closed_orders = self._api_call(self.exchange.fetch_closed_orders, symbol, limit=50)
                    for order in closed_orders:
                        if order['id'] == order_id:
                            order_data = order
                            logger.debug(f"Bybit: Order {order_id} found in recent closed orders.")
                            break

                if not order_data:
                    # As a last resort, try fetchOrder, acknowledging its limitations
                    logger.warning(f"Bybit: Order {order_id} not in open or recent closed. Attempting fetchOrder for {symbol} (may fail for older orders).")
                    # Suppress CCXT's internal warning about fetchOrder limitations on Bybit
                    order_data = self._api_call(self.exchange.fetch_order, order_id, symbol, params={'acknowledged': True})
            else:
                # Default behavior for other exchanges
                order_data = self._api_call(self.exchange.fetch_order, order_id, symbol)

            if order_data:
                return {
                    'status': order_data.get('status'),
                    'filled': order_data.get('filled', 0.0),
                    'remaining': order_data.get('remaining', 0.0),
                    # Consider adding 'average' and 'cost' if available and useful here
                }
            else:
                logger.warning(f"Could not find order {order_id} for {symbol} on {self.exchange_id}.")
                return {'status': 'not_found', 'filled': 0.0, 'remaining': 0.0}

        except Exception as e:
            logger.error(f"Failed to fetch order status for {order_id} on {self.exchange_id} ({symbol}): {e}", exc_info=True)
            return {'status': 'error', 'filled': 0.0, 'remaining': 0.0}

    def get_balance(self, currency: str):
        """Return available balance for ``currency`` or ``None`` on failure."""
        try:
            # Specific handling for Binance Testnet SAPI issue
            if self.exchange_id == 'binance' and self.exchange.urls['api'] == 'https://testnet.binance.vision/api':
                try:
                    bal = self._api_call(self.exchange.fetch_balance) # type: ignore
                except ccxt.NotSupported as e:
                    logger.warning(f"Binance Testnet: fetch_balance failed likely due to SAPI limitations. Error: {e}. Returning None for {currency} balance.")
                    return None
            else:
                bal = self._api_call(self.exchange.fetch_balance) # type: ignore

            if not isinstance(bal, dict):
                logger.warning(f"Balance response is not a dict for {currency} on {self.exchange_id}: {bal}")
                return None

            # Bitmart specific parsing based on provided log structure
            if self.exchange_id == 'bitmart':
                if bal.get('info', {}).get('code') == '1000' and 'data' in bal.get('info', {}):
                    wallet = bal['info']['data'].get('wallet', [])
                    for item in wallet:
                        if item.get('id') == currency:
                            try:
                                return float(item.get('available', 0.0))
                            except (ValueError, TypeError):
                                logger.warning(f"Bitmart: 'available' balance for {currency} is not a number: {item.get('available')}.")
                                return None
                    logger.warning(f"Bitmart: Currency {currency} not found in wallet. Full wallet: {wallet}")
                    return None # Currency not found in wallet
                else: # Bitmart response structure not as expected
                    logger.warning(f"Bitmart: Unexpected response structure for balance. Full response: {bal}")
                    return None


            # Standard CCXT structure parsing (for other exchanges)
            if currency in bal:
                currency_balance_info = bal[currency]
                if isinstance(currency_balance_info, dict):
                    if 'free' in currency_balance_info and currency_balance_info['free'] is not None:
                        try:
                            return float(currency_balance_info['free'])
                        except (ValueError, TypeError):
                            logger.warning(f"'free' balance for {currency} on {self.exchange_id} is not a number: {currency_balance_info['free']}.")
                    if 'total' in currency_balance_info and currency_balance_info['total'] is not None:
                        logger.warning(f"Using 'total' balance for {currency} on {self.exchange_id} as 'free' is unavailable/invalid.")
                        try:
                            return float(currency_balance_info['total'])
                        except (ValueError, TypeError):
                            logger.warning(f"'total' balance for {currency} on {self.exchange_id} is not a number: {currency_balance_info['total']}.")
                    logger.warning(f"No valid 'free' or 'total' numeric balance found in bal['{currency}'] on {self.exchange_id}. Data: {currency_balance_info}")
                    return None
                elif isinstance(currency_balance_info, (int, float, str)):
                    try:
                        return float(currency_balance_info)
                    except ValueError:
                        logger.warning(f"Direct balance value for {currency} on {self.exchange_id} is not a number: {currency_balance_info}")
                        return None
                else:
                    logger.warning(f"bal['{currency}'] for {self.exchange_id} is neither a dict nor a direct numeric value. Type: {type(currency_balance_info)}, Value: {currency_balance_info}")
                    return None

            # Fallback for legacy structures (less common with modern CCXT)
            for balance_type_key in ("free", "total"):
                if isinstance(bal.get(balance_type_key), dict) and currency in bal[balance_type_key]:
                    val = bal[balance_type_key][currency]
                    logger.warning(f"Balance for {currency} on {self.exchange_id}: found under legacy structure bal['{balance_type_key}']['{currency}'].")
                    try:
                        return float(val)
                    except (ValueError, TypeError):
                         logger.warning(f"Legacy balance value for {currency} under '{balance_type_key}' on {self.exchange_id} is not a number: {val}")
                         return None

            logger.warning(f"Could not determine balance for {currency} on {self.exchange_id} from response: {bal}")
            return None

        except KeyError as e:
            missing_key = str(e)
            log_key = f"balance_key_missing_{self.exchange_id}_{currency}_{missing_key}"
            if log_key not in self._balance_errors:
                logger.warning(f"Balance key missing for {currency} on {self.exchange_id}: {missing_key}. Full balance response: {bal if 'bal' in locals() else 'N/A'}")
                self._balance_errors.add(log_key)
            return None
        except AuthenticationError as e:
            # Use a more specific key for _balance_errors to avoid duplicate generic messages
            msg_key = f"auth_error_{self.exchange_id}_{currency}"
            if msg_key not in self._balance_errors:
                logger.error(f"Authentication error fetching balance for {currency} on {self.exchange_id}: {e}")
                self._balance_errors.add(msg_key)
            return "AUTH_ERROR" # type: ignore
        except Exception as e:
            # Generic error message, log once per unique error message for this exchange/currency
            log_key = f"fetch_balance_error_{self.exchange_id}_{currency}_{str(e)}"
            if log_key not in self._balance_errors:
                logger.error(f"Failed to fetch balance for {currency} on {self.exchange_id}: {e}", exc_info=True)
                self._balance_errors.add(log_key)
            return None

    def fetch_my_trades(self, symbol: str | None = None, **params):
        """Return trade history for ``symbol`` using the underlying exchange."""
        try:
            return self._api_call(self.exchange.fetch_my_trades, symbol=symbol, **params)
        except Exception as e:  # pragma: no cover - thin wrapper
            logger.error("Failed to fetch trades for %s: %s", symbol or "all", e)
            return []
