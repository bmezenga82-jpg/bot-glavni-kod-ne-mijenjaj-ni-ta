import ccxt
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

STABLECOINS = {
    'USDT','BUSD','USDC','DAI','TUSD','FDUSD','USDP','GUSD','FRAX',
    'LUSD','SUSD','HUSD','USDD','USTC','ALUSD','CUSD','UST'
}

BTC_HALVINGS = [
    1354060800,  # 2012-11-28
    1468022400,  # 2016-07-09
    1589155200,  # 2020-05-11
    1713571200,  # 2024-04-20
]

_scan_cache = {'data': None, 'ts': 0}
CACHE_TTL = 3600  # 1 hour


def _make_binance():
    return ccxt.binance({'enableRateLimit': True})


def _fetch_ohlcv(symbol, timeframe, limit):
    ex = _make_binance()
    data = ex.fetch_ohlcv(symbol, timeframe, limit=limit)
    if not data:
        raise ValueError(f"Nema podataka za {symbol}")
    df = pd.DataFrame(data, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
    df['ts'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
    df = df.drop_duplicates('ts').sort_values('ts').reset_index(drop=True)
    return df


def _rsi_series(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period - 1, min_periods=period).mean()
    rs = gain / loss.replace(0, 1e-9)
    return 100 - 100 / (1 + rs)


def _macd_series(close, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    line = ema_fast - ema_slow
    sig = line.ewm(span=signal, adjust=False).mean()
    hist = line - sig
    return line, sig, hist


def _bollinger(close, period=20, std_mult=2):
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    return sma + std_mult * std, sma, sma - std_mult * std


def _sma(close, period):
    return close.rolling(period).mean()


def _find_swing(df):
    swing_high = float(df['high'].max())
    swing_low = float(df['low'].min())
    return swing_high, swing_low


def _fib_retracement(high, low):
    d = high - low
    return {
        '0.0': high, '0.236': high - 0.236 * d, '0.382': high - 0.382 * d,
        '0.5': high - 0.5 * d, '0.618': high - 0.618 * d,
        '0.786': high - 0.786 * d, '1.0': low,
    }


def _fib_extension(high, low):
    d = high - low
    return {
        '1.0': high, '1.272': low + 1.272 * d, '1.618': low + 1.618 * d,
        '2.0': low + 2.0 * d, '2.618': low + 2.618 * d,
    }


def _support_resistance(df, n_levels=6):
    current = float(df['close'].iloc[-1])
    prices = pd.concat([df['high'], df['low']])
    bins = pd.cut(prices, bins=40)
    counts = bins.value_counts().head(15)
    levels = []
    for interval, count in counts.items():
        if hasattr(interval, 'mid'):
            price = float(interval.mid)
            if not any(abs(price - l['price']) / max(current, 1e-9) < 0.025 for l in levels):
                levels.append({
                    'price': round(price, 8),
                    'strength': int(count),
                    'type': 'support' if price < current else 'resistance',
                })
    return sorted(levels, key=lambda x: x['price'])


def _btc_correlation(df_coin):
    try:
        ex = _make_binance()
        raw = ex.fetch_ohlcv('BTC/USDT', '1d', limit=len(df_coin))
        if not raw or len(raw) < 20:
            return None
        btc_close = pd.Series([r[4] for r in raw])
        coin_close = df_coin['close'].reset_index(drop=True)
        n = min(len(btc_close), len(coin_close))
        r1 = coin_close.tail(n).pct_change().dropna()
        r2 = btc_close.tail(n).pct_change().dropna()
        n2 = min(len(r1), len(r2))
        corr = r1.tail(n2).corr(r2.tail(n2))
        return round(float(corr), 3) if not pd.isna(corr) else None
    except Exception:
        return None


def _halving_info():
    now = datetime.now(timezone.utc).timestamp()
    last = BTC_HALVINGS[-1]
    months_since = (now - last) / (30.44 * 86400)
    next_halving = last + 4 * 365.25 * 86400
    months_to_next = max(0, (next_halving - now) / (30.44 * 86400))

    if months_since < 6:
        phase = 'early_bull'; phase_hr = 'Rana akumulacija'
        outlook = 'Historijski sporo raste — dobro za DCA, vrhovi tek dolaze'
    elif months_since < 18:
        phase = 'bull'; phase_hr = 'Bull faza'
        outlook = 'Historijski najjači rast — ali oprez pri kupnji na vrhu'
    elif months_since < 30:
        phase = 'post_peak'; phase_hr = 'Post-vrh / korekcija'
        outlook = 'Historijski vrh ciklusa je prošao, moguća daljnja korekcija'
    else:
        phase = 'bear'; phase_hr = 'Bear / Akumulacija'
        outlook = 'Historijski dno ciklusa — odličan period za dugoročnu akumulaciju'

    return {
        'months_since': round(months_since, 1),
        'months_to_next': round(months_to_next, 1),
        'last_date': datetime.fromtimestamp(last, tz=timezone.utc).strftime('%Y-%m-%d'),
        'next_date': datetime.fromtimestamp(next_halving, tz=timezone.utc).strftime('%Y-%m-%d'),
        'phase': phase, 'phase_hr': phase_hr, 'outlook': outlook,
    }


def _score(rsi_d, rsi_w, vs_200ma, bb_pct):
    s = 0
    # RSI daily (20%)
    if rsi_d < 30: s += 20
    elif rsi_d < 40: s += 15
    elif rsi_d < 50: s += 10
    elif rsi_d < 60: s += 5
    # RSI weekly (30%)
    if rsi_w is not None:
        if rsi_w < 30: s += 30
        elif rsi_w < 40: s += 22
        elif rsi_w < 50: s += 14
        elif rsi_w < 60: s += 7
    # vs 200MA (30%)
    if vs_200ma < -50: s += 30
    elif vs_200ma < -30: s += 25
    elif vs_200ma < -15: s += 18
    elif vs_200ma < 0: s += 10
    elif vs_200ma < 15: s += 5
    # BB position (20%)
    if bb_pct < 15: s += 20
    elif bb_pct < 30: s += 15
    elif bb_pct < 50: s += 10
    elif bb_pct < 70: s += 5
    return min(100, s)


def _explanation(symbol, price, rsi_d, rsi_w, vs_200ma, ath_pct, fib_r, fib_e, macd_bull, btc_corr, score):
    lines = []

    # RSI daily
    if rsi_d < 30:
        lines.append(f"📉 Dnevni RSI {rsi_d:.1f} — Jako preprodan! Historijski rijetka zona, potencijalno dno ciklusa.")
    elif rsi_d < 40:
        lines.append(f"📉 Dnevni RSI {rsi_d:.1f} — Preprodan. Cijena je dosta pala, dobar entry zone za dugoročno.")
    elif rsi_d < 50:
        lines.append(f"➡️ Dnevni RSI {rsi_d:.1f} — Neutralno, blago bearish.")
    elif rsi_d < 60:
        lines.append(f"➡️ Dnevni RSI {rsi_d:.1f} — Neutralno.")
    elif rsi_d < 70:
        lines.append(f"⬆️ Dnevni RSI {rsi_d:.1f} — Lagano overbought, oprez pri kupnji.")
    else:
        lines.append(f"🔴 Dnevni RSI {rsi_d:.1f} — Jako overbought! Historijski loš timing za novi entry.")

    if rsi_w is not None:
        if rsi_w < 30:
            lines.append(f"🔑 Tjedni RSI {rsi_w:.1f} — RIJETKA ZONA. Na altcoinima ovo je historijski bio generacijsko dno.")
        elif rsi_w < 40:
            lines.append(f"✅ Tjedni RSI {rsi_w:.1f} — Odličan dugoročni entry. Historijski visok prinos od ove razine.")
        elif rsi_w < 50:
            lines.append(f"🟡 Tjedni RSI {rsi_w:.1f} — Prihvatljivo za DCA, nije idealno.")
        else:
            lines.append(f"⚠️ Tjedni RSI {rsi_w:.1f} — Povišeno. Za dugoročno, bolji entry bio bi na nižem RSI-u.")

    # 200MA
    if vs_200ma < -40:
        lines.append(f"📊 200MA: {abs(vs_200ma):.1f}% ISPOD 200-dnevnog prosjeka — duboki bear. Historijski odlična dugoročna zona.")
    elif vs_200ma < -20:
        lines.append(f"📊 200MA: {abs(vs_200ma):.1f}% ispod 200MA — slabost, ali dobar dugoročni entry.")
    elif vs_200ma < 0:
        lines.append(f"📊 200MA: {abs(vs_200ma):.1f}% ispod 200MA — blaga slabost.")
    elif vs_200ma < 20:
        lines.append(f"📊 200MA: +{vs_200ma:.1f}% iznad 200MA — bull trend, ali nije jeftino.")
    else:
        lines.append(f"📊 200MA: +{vs_200ma:.1f}% iznad 200MA — ekstenzija, visok rizik za novi entry.")

    lines.append(f"🏔️ Od vrha: cijena je {abs(ath_pct):.1f}% ispod zadnjeg vrha (ATH: ${max(fib_r.values()):.4f})")

    # Fibonacci podrška
    nearest_sup = None
    nearest_res = None
    for lvl, p in fib_r.items():
        if p < price and (nearest_sup is None or p > nearest_sup[1]):
            nearest_sup = (lvl, p)
        if p > price and (nearest_res is None or p < nearest_res[1]):
            nearest_res = (lvl, p)
    if nearest_sup:
        pct = (nearest_sup[1] / price - 1) * 100
        lines.append(f"🔵 Fib podrška: razina {nearest_sup[0]} na ${nearest_sup[1]:.4f} ({pct:.1f}% od sad)")
    if nearest_res:
        pct = (nearest_res[1] / price - 1) * 100
        lines.append(f"🟣 Fib otpor: razina {nearest_res[0]} na ${nearest_res[1]:.4f} (+{pct:.1f}% od sad)")

    # Upside targets
    targets = [(lvl, p) for lvl, p in sorted(fib_e.items(), key=lambda x: float(x[0])) if p > price]
    if targets:
        t_lines = [f"  • {lvl}× → ${p:.4f} (+{(p/price-1)*100:.0f}%)" for lvl, p in targets[:3]]
        lines.append("🎯 Potencijalni upside ciljevi (Fib ekstenzija):\n" + "\n".join(t_lines))

    # MACD
    lines.append("✅ MACD: bullish momentum." if macd_bull else "⚠️ MACD: bearish momentum, trend pada.")

    # BTC korelacija
    if btc_corr is not None:
        if btc_corr > 0.8:
            lines.append(f"🔗 BTC korelacija {btc_corr:.2f} — jako prati BTC.")
        elif btc_corr > 0.5:
            lines.append(f"🔗 BTC korelacija {btc_corr:.2f} — umjereno prati BTC.")
        else:
            lines.append(f"🔗 BTC korelacija {btc_corr:.2f} — relativno nezavisno od BTC-a.")

    # Score
    if score >= 70:
        lines.append(f"\n🟢 UKUPNO {score}/100 — Dobra zona za dugoročnu akumulaciju.")
    elif score >= 50:
        lines.append(f"\n🟡 UKUPNO {score}/100 — Neutralno. Čekaj bolji entry.")
    else:
        lines.append(f"\n🔴 UKUPNO {score}/100 — Loš timing. Moguća daljnja korekcija.")

    lines.append("\n⚠️ Samo informativno, nije financijski savjet. Bazirano na prošlim podacima.")
    return "\n".join(lines)


def _ts_series(df_ts, series):
    result = []
    for ts, val in zip(df_ts, series):
        if not pd.isna(val):
            result.append({'time': int(ts.timestamp()), 'value': round(float(val), 8)})
    return result


def analyze_long_term(symbol, view_range='1Y'):
    range_map = {'1M': 30, '3M': 90, '6M': 180, '1Y': 365, '3Y': 1095}
    tf_map = {'1M': '1d', '3M': '1d', '6M': '1d', '1Y': '1d', '3Y': '1w'}
    limit = range_map.get(view_range, 365)
    timeframe = tf_map.get(view_range, '1d')

    df = _fetch_ohlcv(symbol, timeframe, limit)
    if len(df) < 30:
        raise ValueError(f"Nedovoljno podataka ({len(df)} svijećnjaka)")

    close = df['close']
    price = float(close.iloc[-1])

    rsi_s = _rsi_series(close)
    rsi_d = float(rsi_s.iloc[-1])

    macd_l, macd_sig, macd_h = _macd_series(close)
    bb_up, bb_mid, bb_lo = _bollinger(close)
    sma50 = _sma(close, min(50, len(df) - 1))
    sma200 = _sma(close, min(200, len(df) - 1))

    sma200_val = float(sma200.iloc[-1]) if not pd.isna(sma200.iloc[-1]) else None
    vs_200ma = ((price / sma200_val) - 1) * 100 if sma200_val else 0.0

    bb_up_v = float(bb_up.iloc[-1]) if not pd.isna(bb_up.iloc[-1]) else price
    bb_lo_v = float(bb_lo.iloc[-1]) if not pd.isna(bb_lo.iloc[-1]) else price
    bb_range = bb_up_v - bb_lo_v
    bb_pct = (price - bb_lo_v) / bb_range * 100 if bb_range > 0 else 50

    ath = float(df['high'].max())
    ath_pct = ((price / ath) - 1) * 100

    swing_high, swing_low = _find_swing(df)
    fib_r = _fib_retracement(swing_high, swing_low)
    fib_e = _fib_extension(swing_high, swing_low)
    sr_levels = _support_resistance(df)

    # Weekly RSI
    rsi_w = None
    try:
        df_w = _fetch_ohlcv(symbol, '1w', 60)
        if len(df_w) >= 15:
            rsi_w = float(_rsi_series(df_w['close']).iloc[-1])
    except Exception:
        pass

    # BTC correlation (skip for BTC itself)
    btc_corr = None
    if 'BTC' not in symbol:
        btc_corr = _btc_correlation(df)

    macd_bull = float(macd_l.iloc[-1]) > float(macd_sig.iloc[-1])
    score = _score(rsi_d, rsi_w, vs_200ma, bb_pct)
    halving = _halving_info()
    explanation = _explanation(
        symbol, price, rsi_d, rsi_w, vs_200ma, ath_pct,
        fib_r, fib_e, macd_bull, btc_corr, score
    )

    candles = [
        {'time': int(row.ts.timestamp()), 'open': float(row.open),
         'high': float(row.high), 'low': float(row.low), 'close': float(row.close)}
        for row in df.itertuples()
    ]
    volume = [
        {'time': int(row.ts.timestamp()), 'value': float(row.volume),
         'color': '#26a69a' if row.close >= row.open else '#ef5350'}
        for row in df.itertuples()
    ]
    macd_hist_data = [
        {'time': int(ts.timestamp()), 'value': round(float(v), 8),
         'color': '#26a69a' if v >= 0 else '#ef5350'}
        for ts, v in zip(df['ts'], macd_h) if not pd.isna(v)
    ]

    return {
        'symbol': symbol, 'view_range': view_range, 'timeframe': timeframe,
        'current_price': price,
        'candles': candles, 'volume': volume,
        'sma50': _ts_series(df['ts'], sma50),
        'sma200': _ts_series(df['ts'], sma200),
        'bb_upper': _ts_series(df['ts'], bb_up),
        'bb_mid': _ts_series(df['ts'], bb_mid),
        'bb_lower': _ts_series(df['ts'], bb_lo),
        'rsi': _ts_series(df['ts'], rsi_s),
        'macd_line': _ts_series(df['ts'], macd_l),
        'macd_signal': _ts_series(df['ts'], macd_sig),
        'macd_hist': macd_hist_data,
        'fib_retracement': {k: round(v, 8) for k, v in fib_r.items()},
        'fib_extension': {k: round(v, 8) for k, v in fib_e.items()},
        'swing_high': round(swing_high, 8),
        'swing_low': round(swing_low, 8),
        'support_resistance': sr_levels,
        'indicators': {
            'rsi_daily': round(rsi_d, 1),
            'rsi_weekly': round(rsi_w, 1) if rsi_w else None,
            'vs_200ma': round(vs_200ma, 1),
            'ath_pct': round(ath_pct, 1),
            'ath_price': round(ath, 8),
            'btc_correlation': btc_corr,
            'score': score,
            'macd_bull': macd_bull,
            'bb_pct': round(bb_pct, 1),
        },
        'halving': halving,
        'explanation': explanation,
    }


def _scan_one(sym):
    try:
        df = _fetch_ohlcv(sym, '1d', 220)
        if len(df) < 50:
            return None
        close = df['close']
        price = float(close.iloc[-1])
        rsi_d = float(_rsi_series(close).iloc[-1])
        sma200 = _sma(close, 200)
        sma200_v = float(sma200.iloc[-1]) if not pd.isna(sma200.iloc[-1]) else None
        vs_200ma = ((price / sma200_v) - 1) * 100 if sma200_v else 0.0
        bb_up, _, bb_lo = _bollinger(close)
        bb_up_v = float(bb_up.iloc[-1]) if not pd.isna(bb_up.iloc[-1]) else price
        bb_lo_v = float(bb_lo.iloc[-1]) if not pd.isna(bb_lo.iloc[-1]) else price
        bb_range = bb_up_v - bb_lo_v
        bb_pct = (price - bb_lo_v) / bb_range * 100 if bb_range > 0 else 50
        ath = float(df['high'].max())
        ath_pct = ((price / ath) - 1) * 100
        rsi_w = None
        try:
            df_w = _fetch_ohlcv(sym, '1w', 60)
            if len(df_w) >= 15:
                rsi_w = float(_rsi_series(df_w['close']).iloc[-1])
        except Exception:
            pass
        score = _score(rsi_d, rsi_w, vs_200ma, bb_pct)
        if score >= 65:
            signal_hr = '🟢 Akumuliraj'
        elif score >= 45:
            signal_hr = '🟡 Čekaj'
        else:
            signal_hr = '🔴 Izbjegavaj'
        return {
            'symbol': sym, 'price': round(price, 6),
            'rsi_daily': round(rsi_d, 1),
            'rsi_weekly': round(rsi_w, 1) if rsi_w else None,
            'vs_200ma': round(vs_200ma, 1),
            'ath_pct': round(ath_pct, 1),
            'score': score, 'signal_hr': signal_hr,
        }
    except Exception as e:
        logger.warning(f"Scanner skip {sym}: {e}")
        return None


def scan_top_coins(top_n=40):
    global _scan_cache
    now = datetime.now(timezone.utc).timestamp()
    if _scan_cache['data'] and (now - _scan_cache['ts']) < CACHE_TTL:
        return _scan_cache['data']

    ex = _make_binance()
    tickers = ex.fetch_tickers()
    usdt = [
        (sym, t.get('quoteVolume', 0))
        for sym, t in tickers.items()
        if sym.endswith('/USDT') and t.get('quoteVolume', 0) > 0
        and sym.replace('/USDT', '') not in STABLECOINS
    ]
    usdt.sort(key=lambda x: x[1], reverse=True)
    pairs = [sym for sym, _ in usdt[:top_n]]

    results = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_scan_one, sym): sym for sym in pairs}
        for fut in as_completed(futures):
            res = fut.result()
            if res:
                results.append(res)

    results.sort(key=lambda x: x['score'], reverse=True)
    _scan_cache = {'data': results, 'ts': now}
    return results
