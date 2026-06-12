import ccxt
import pandas as pd
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

EXCHANGE_ID_MAP = {
    'binance': 'binance',
    'gate.io': 'gateio',
    'gateio': 'gateio',
    'bitmart': 'bitmart',
    'bybit': 'bybit',
    'kucoin': 'kucoin',
    'okx': 'okx',
}

def _make_exchange(exchange_name):
    ex_id = EXCHANGE_ID_MAP.get(exchange_name.lower(), exchange_name.lower())
    ex_class = getattr(ccxt, ex_id, None)
    if ex_class is None:
        raise ValueError(f"CCXT ne poznaje exchange: {ex_id}")
    return ex_class({'enableRateLimit': True})

def _fetch_ohlcv(exchange_name, symbol, timeframe='1h', limit=None):
    if limit is None:
        limit = 120 if timeframe in ('1w', '1M') else 220
    ex = _make_exchange(exchange_name)
    data = ex.fetch_ohlcv(symbol, timeframe, limit=limit)
    if not data:
        raise ValueError("Exchange nije vratio podatke")
    df = pd.DataFrame(data, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
    df['ts'] = pd.to_datetime(df['ts'], unit='ms')
    return df

def _rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period - 1, min_periods=period).mean()
    rs = gain / loss.replace(0, 1e-9)
    return (100 - 100 / (1 + rs)).iloc[-1]

def _ema(close, period):
    return close.ewm(span=period, adjust=False).mean()

def _atr_pct(high, low, close, period=14):
    prev_close = close.shift()
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr = tr.ewm(com=period - 1, min_periods=period).mean().iloc[-1]
    price = close.iloc[-1]
    return (atr / price * 100) if price else 0

def _bollinger_pct(close, period=20):
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = (sma + 2 * std).iloc[-1]
    lower = (sma - 2 * std).iloc[-1]
    price = close.iloc[-1]
    band_width = upper - lower
    if band_width == 0:
        return 0.5
    return max(0.0, min(1.0, (price - lower) / band_width))

def _score(rsi, trend_pct, atr_pct, bb_pct):
    # RSI — niži bolji za entry
    if rsi < 30:      rsi_s = 90
    elif rsi < 45:    rsi_s = 75
    elif rsi < 55:    rsi_s = 60
    elif rsi < 70:    rsi_s = 40
    else:             rsi_s = 20

    # Trend strength — sideways je idealan za grid
    if trend_pct < 1.5:   trend_s = 90
    elif trend_pct < 3:   trend_s = 75
    elif trend_pct < 6:   trend_s = 55
    elif trend_pct < 10:  trend_s = 35
    else:                 trend_s = 20

    # Volatilnost — viša = više grid okidanja
    if atr_pct > 3:      vol_s = 90
    elif atr_pct > 2:    vol_s = 75
    elif atr_pct > 1:    vol_s = 60
    elif atr_pct > 0.5:  vol_s = 40
    else:                vol_s = 20

    # BB pozicija — bliže donjoj granici = bolji entry
    if bb_pct < 0.2:    bb_s = 90
    elif bb_pct < 0.4:  bb_s = 72
    elif bb_pct < 0.6:  bb_s = 50
    elif bb_pct < 0.8:  bb_s = 32
    else:               bb_s = 18

    total = rsi_s * 0.25 + trend_s * 0.30 + vol_s * 0.30 + bb_s * 0.15
    total = round(total)

    if total >= 68:   label = 'Dobar'
    elif total >= 50: label = 'Neutralan'
    else:             label = 'Loš'

    return total, label

def _trend_label(ema50_last, ema200_last, ema50_slope):
    diff_pct = (ema50_last - ema200_last) / ema200_last * 100 if ema200_last else 0
    if abs(diff_pct) < 2 and abs(ema50_slope) < 0.05:
        return 'Sideways', abs(diff_pct)
    elif diff_pct > 0:
        return 'Uptrend', abs(diff_pct)
    else:
        return 'Downtrend', abs(diff_pct)

def analyze_pair(pair_info):
    symbol = pair_info['symbol']
    exchange = pair_info['exchange']
    timeframe = pair_info.get('timeframe', '1h')
    try:
        df = _fetch_ohlcv(exchange, symbol, timeframe=timeframe)
        if len(df) < 50:
            return {**pair_info, 'error': 'Nedovoljno podataka'}

        close = df['close']
        high = df['high']
        low = df['low']

        rsi = round(_rsi(close), 1)
        ema50 = _ema(close, 50)
        ema200 = _ema(close, 200)
        ema50_slope = (ema50.iloc[-1] - ema50.iloc[-6]) / ema50.iloc[-6] * 100
        trend_label, trend_strength = _trend_label(ema50.iloc[-1], ema200.iloc[-1], ema50_slope)
        atr = round(_atr_pct(high, low, close), 2)
        bb_pct = round(_bollinger_pct(close), 2)
        price = round(close.iloc[-1], 6)
        score, score_label = _score(rsi, trend_strength, atr, bb_pct)

        return {
            'symbol': symbol,
            'exchange': exchange,
            'price': price,
            'rsi': rsi,
            'trend': trend_label,
            'trend_strength': round(trend_strength, 2),
            'atr_pct': atr,
            'bb_pct': round(bb_pct * 100, 1),
            'score': score,
            'score_label': score_label,
            'error': None,
        }
    except Exception as e:
        logger.warning(f"analyze_pair {symbol}/{exchange}: {e}")
        return {**pair_info, 'error': str(e), 'price': None, 'rsi': None,
                'trend': None, 'atr_pct': None, 'bb_pct': None, 'score': 0, 'score_label': 'Greška'}

def _dca_score(rsi_daily, rsi_weekly, vs_ma200, dist_from_high):
    # Weekly RSI — ključni signal za dugoročni entry
    if rsi_weekly < 30:    wrsi_s = 95
    elif rsi_weekly < 40:  wrsi_s = 80
    elif rsi_weekly < 50:  wrsi_s = 65
    elif rsi_weekly < 60:  wrsi_s = 45
    else:                  wrsi_s = 25

    # Price vs 200-day MA — ispod MA = bear territorij
    if vs_ma200 < -40:    ma_s = 92
    elif vs_ma200 < -25:  ma_s = 80
    elif vs_ma200 < -10:  ma_s = 65
    elif vs_ma200 < 0:    ma_s = 52
    elif vs_ma200 < 15:   ma_s = 38
    else:                 ma_s = 20

    # Daily RSI
    if rsi_daily < 25:    drsi_s = 90
    elif rsi_daily < 35:  drsi_s = 75
    elif rsi_daily < 45:  drsi_s = 62
    elif rsi_daily < 55:  drsi_s = 48
    elif rsi_daily < 65:  drsi_s = 35
    else:                 drsi_s = 20

    # Udaljenost od 52-tjednog vrha
    if dist_from_high < -70:   high_s = 90
    elif dist_from_high < -50: high_s = 78
    elif dist_from_high < -35: high_s = 65
    elif dist_from_high < -20: high_s = 50
    elif dist_from_high < -10: high_s = 35
    else:                      high_s = 20

    total = round(wrsi_s * 0.35 + ma_s * 0.30 + drsi_s * 0.20 + high_s * 0.15)

    if total >= 68:   label = 'Akumuliraj'
    elif total >= 50: label = 'Čekaj'
    else:             label = 'Preskupo'

    return total, label

def analyze_dca_pair(pair_info):
    symbol = pair_info['symbol']
    exchange = pair_info['exchange']
    try:
        df = _fetch_ohlcv(exchange, symbol, timeframe='1d', limit=500)
        if len(df) < 50:
            return {**pair_info, 'error': 'Nedovoljno podataka'}

        close = df['close']
        high_col = df['high']
        price = round(close.iloc[-1], 6)

        # Daily RSI
        rsi_daily = round(_rsi(close), 1)

        # Weekly RSI — resample na tjedne
        df_w = df.set_index('ts').resample('W').agg({'close': 'last'}).dropna()
        rsi_weekly = round(_rsi(df_w['close']), 1) if len(df_w) >= 14 else rsi_daily

        # Price vs 200-day SMA
        ma200 = close.rolling(200).mean().iloc[-1]
        vs_ma200 = round((price - ma200) / ma200 * 100, 1) if ma200 and not pd.isna(ma200) else 0

        # Udaljenost od 52-tjednog vrha (365 dana)
        cutoff = df['ts'].max() - pd.Timedelta(days=365)
        last_year = df[df['ts'] >= cutoff]
        high_52w = last_year['high'].max() if not last_year.empty else price
        dist_from_high = round((price - high_52w) / high_52w * 100, 1) if high_52w else 0

        score, score_label = _dca_score(rsi_daily, rsi_weekly, vs_ma200, dist_from_high)

        recommended = 'crypto' if score >= 68 else ('usdc' if score < 50 else None)

        return {
            'symbol': symbol,
            'exchange': exchange,
            'pair_id': pair_info.get('pair_id'),
            'profit_mode': pair_info.get('profit_mode', 'usdc'),
            'price': price,
            'rsi_daily': rsi_daily,
            'rsi_weekly': rsi_weekly,
            'vs_ma200': vs_ma200,
            'dist_from_high': dist_from_high,
            'score': score,
            'score_label': score_label,
            'recommended_mode': recommended,
            'error': None,
        }
    except Exception as e:
        logger.warning(f"analyze_dca_pair {symbol}/{exchange}: {e}")
        return {**pair_info, 'error': str(e), 'price': None, 'rsi_daily': None,
                'rsi_weekly': None, 'vs_ma200': None, 'dist_from_high': None,
                'score': 0, 'score_label': 'Greška', 'recommended_mode': None}

def analyze_dca_all(pairs, max_workers=4):
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(analyze_dca_pair, p): p for p in pairs}
        for fut in as_completed(futures):
            results.append(fut.result())
    results.sort(key=lambda r: r.get('score', 0), reverse=True)
    return results

def analyze_all(pairs, timeframe='1h', max_workers=4):
    enriched = [{**p, 'timeframe': timeframe} for p in pairs]
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(analyze_pair, p): p for p in enriched}
        for fut in as_completed(futures):
            results.append(fut.result())
    results.sort(key=lambda r: r.get('score', 0), reverse=True)
    return results
