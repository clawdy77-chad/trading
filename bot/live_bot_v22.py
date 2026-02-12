#!/usr/bin/env python3
"""
V22 Adaptive TTFM/GxT — Optimized Live Trading Bot
====================================================
- Parquet-backed data with incremental backfill & live updates
- Multi-fractal signal detection (F1-F4) during killzones
- DRY_RUN mode by default; real Oanda execution when disabled
- Risk: $500 green / $250 drawdown, max 3 trades/day, 30-min gap
- Logs to file, writes to trades.db, updates bot_status.json
"""

import os
import sys
import json
import time
import logging
import sqlite3
import signal as sig_mod
import numpy as np
import pandas as pd
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv

# ============================================================
# CONFIG
# ============================================================
load_dotenv('/root/.openclaw/workspace/.env')

API_KEY = os.getenv('OANDA_API_KEY', '')
ACCOUNT_ID = os.getenv('OANDA_ACCOUNT_ID', '')
BASE_URL = "https://api-fxpractice.oanda.com"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

DRY_RUN = False
MEMORY_DAYS = 30  # Keep last N days in memory

# Risk
RISK_GREEN = 500
RISK_DRAWDOWN = 250
MAX_TRADES_PER_DAY = 3
MIN_GAP_SECONDS = 1800
FLAT_HOUR, FLAT_MIN = 21, 15
ATR_PERIOD = 14
SWING_LB = 3
POLL_INTERVAL = 60

DATA_DIR = Path('/root/.openclaw/workspace/trading/data_10y')
LOG_FILE = Path('/root/.openclaw/workspace/trading/live_bot.log')
STATUS_FILE = Path('/root/.openclaw/workspace/trading/bot_status.json')
TRADES_DB = Path('/root/.openclaw/workspace/tradingjournal/trades.db')

OANDA_INSTRUMENTS = {
    'NAS100_USD': {'label': 'NQ', 'file': 'nas100_usd_m1_10y.parquet',
                   'slippage': 2.0, 'point_val': 1.0, 'buffer_mult': 0.3},
    'SPX500_USD': {'label': 'ES', 'file': 'spx500_usd_m1_10y.parquet',
                   'slippage': 0.75, 'point_val': 1.0, 'buffer_mult': 0.3},
    'US30_USD':   {'label': 'YM', 'file': 'us30_usd_m1_10y.parquet',
                   'slippage': 3.0, 'point_val': 1.0, 'buffer_mult': 0.3},
}

FRACTALS = [
    ('F1_M30', '30min', '15min', '1min',  1.0),
    ('F2_H1',  '1h',    '30min', '5min',  1.2),
    ('F3_H4',  '4h',    '1h',    '15min', 1.5),
    ('F4_D1',  '1D',    '4h',    '1h',    2.0),
]

# ============================================================
# LOGGING
# ============================================================
log = logging.getLogger("livebot")
log.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
_fh = logging.FileHandler(LOG_FILE)
_fh.setFormatter(_fmt)
_sh = logging.StreamHandler()
_sh.setFormatter(_fmt)
log.addHandler(_fh)
log.addHandler(_sh)

# ============================================================
# OANDA API
# ============================================================
_session = requests.Session()
_session.headers.update(HEADERS)


def api_get(path, params=None):
    for attempt in range(3):
        try:
            r = _session.get(f"{BASE_URL}{path}", params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == 2:
                raise
            log.warning(f"API retry {attempt+1}: {e}")
            time.sleep(2 ** attempt)


def api_post(path, data):
    for attempt in range(3):
        try:
            r = _session.post(f"{BASE_URL}{path}", json=data, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == 2:
                raise
            log.warning(f"API POST retry {attempt+1}: {e}")
            time.sleep(2 ** attempt)


def api_put(path, data=None):
    for attempt in range(3):
        try:
            r = _session.put(f"{BASE_URL}{path}", json=data or {}, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def fetch_candles_since(instrument, from_ts, granularity="M1"):
    """Fetch M1 candles from Oanda since `from_ts` (ISO string), paginating 5000 at a time.
    Returns list of dicts."""
    all_candles = []
    current_from = from_ts
    while True:
        params = {
            "granularity": granularity, "price": "M",
            "from": current_from, "count": 5000,
            "includeFirst": "false",
        }
        data = api_get(f"/v3/instruments/{instrument}/candles", params)
        candles = data.get("candles", [])
        if not candles:
            break
        for c in candles:
            if not c.get("complete", False):
                continue
            mid = c["mid"]
            all_candles.append({
                "time": c["time"],
                "open": float(mid["o"]),
                "high": float(mid["h"]),
                "low": float(mid["l"]),
                "close": float(mid["c"]),
                "volume": int(c.get("volume", 0)),
            })
        # Next page starts from last candle time
        last_time = candles[-1]["time"]
        if last_time == current_from or len(candles) < 5000:
            break
        current_from = last_time
    return all_candles


def fetch_recent_candles(instrument, granularity="M1", count=10):
    """Fetch recent complete candles."""
    params = {"granularity": granularity, "count": count, "price": "M"}
    data = api_get(f"/v3/instruments/{instrument}/candles", params)
    result = []
    for c in data.get("candles", []):
        if not c.get("complete", False):
            continue
        mid = c["mid"]
        result.append({
            "time": c["time"],
            "open": float(mid["o"]),
            "high": float(mid["h"]),
            "low": float(mid["l"]),
            "close": float(mid["c"]),
            "volume": int(c.get("volume", 0)),
        })
    return result


# ============================================================
# DATA MANAGER — parquet-backed with in-memory cache
# ============================================================
class DataManager:
    def __init__(self):
        self.data = {}  # instrument -> pd.DataFrame (indexed by time)

    def load_and_backfill(self):
        """Load parquet files, backfill gap from Oanda, trim to MEMORY_DAYS."""
        for inst, cfg in OANDA_INSTRUMENTS.items():
            pq_path = DATA_DIR / cfg['file']
            log.info(f"Loading {inst} from {pq_path}")
            df = pd.read_parquet(pq_path)
            df['time'] = pd.to_datetime(df['time'], utc=True)
            df = df.set_index('time').sort_index()
            df = df[['open', 'high', 'low', 'close', 'volume']]

            last_ts = df.index[-1]
            log.info(f"  {inst}: {len(df)} bars, last={last_ts}")

            # Backfill from Oanda
            from_iso = last_ts.strftime('%Y-%m-%dT%H:%M:%S.000000000Z')
            log.info(f"  Backfilling {inst} from {from_iso}...")
            new_candles = fetch_candles_since(inst, from_iso, "M1")
            if new_candles:
                ndf = pd.DataFrame(new_candles)
                ndf['time'] = pd.to_datetime(ndf['time'], utc=True)
                ndf = ndf.set_index('time').sort_index()
                ndf = ndf[['open', 'high', 'low', 'close', 'volume']]
                df = pd.concat([df, ndf])
                df = df[~df.index.duplicated(keep='last')].sort_index()
                log.info(f"  Backfilled {len(new_candles)} candles, total={len(df)}, last={df.index[-1]}")

                # Save updated parquet
                save_df = df.reset_index()
                save_df.to_parquet(pq_path, index=False)
                log.info(f"  Saved {pq_path}")

            # Trim to MEMORY_DAYS
            cutoff = pd.Timestamp.now(tz='UTC') - timedelta(days=MEMORY_DAYS)
            df = df[df.index >= cutoff]
            self.data[inst] = df
            log.info(f"  {inst} in memory: {len(df)} bars")

    def update_live(self):
        """Fetch recent M1 candles and append to in-memory data + parquet."""
        for inst, cfg in OANDA_INSTRUMENTS.items():
            try:
                candles = fetch_recent_candles(inst, "M1", 5)
                if not candles:
                    continue
                ndf = pd.DataFrame(candles)
                ndf['time'] = pd.to_datetime(ndf['time'], utc=True)
                ndf = ndf.set_index('time').sort_index()
                ndf = ndf[['open', 'high', 'low', 'close', 'volume']]

                df = self.data[inst]
                # Only append truly new bars
                new_mask = ~ndf.index.isin(df.index)
                if new_mask.any():
                    new_bars = ndf[new_mask]
                    self.data[inst] = pd.concat([df, new_bars]).sort_index()
                    # Append to parquet
                    pq_path = DATA_DIR / cfg['file']
                    full = pd.read_parquet(pq_path)
                    full['time'] = pd.to_datetime(full['time'], utc=True)
                    full = full.set_index('time')
                    full = pd.concat([full, new_bars])
                    full = full[~full.index.duplicated(keep='last')].sort_index()
                    full.reset_index().to_parquet(pq_path, index=False)

                    # Trim memory
                    cutoff = pd.Timestamp.now(tz='UTC') - timedelta(days=MEMORY_DAYS)
                    self.data[inst] = self.data[inst][self.data[inst].index >= cutoff]
            except Exception as e:
                log.error(f"Live update {inst}: {e}")

    def get_df(self, inst):
        return self.data.get(inst, pd.DataFrame())

    def last_timestamp(self, inst):
        df = self.data.get(inst)
        if df is not None and len(df) > 0:
            return df.index[-1].isoformat()
        return None


# ============================================================
# V22 STRATEGY — vectorized signal detection
# ============================================================
def resample_df(df, rule):
    if len(df) == 0:
        return df
    return df.resample(rule).agg(
        {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
    ).dropna()


def compute_atr(h, l, c, period=ATR_PERIOD):
    prev_c = np.empty_like(c)
    prev_c[0] = c[0]
    prev_c[1:] = c[:-1]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    tr[0] = h[0] - l[0]
    return pd.Series(tr).ewm(span=period, adjust=False).mean().values


def find_swings(h, l, lb=SWING_LB):
    n = len(h)
    sh = np.full(n, np.nan)
    sl = np.full(n, np.nan)
    win = 2 * lb + 1
    if n < win:
        return sh, sl
    from numpy.lib.stride_tricks import sliding_window_view
    h_win = sliding_window_view(h, win)
    l_win = sliding_window_view(l, win)
    sh[lb:n-lb] = np.where(h[lb:n-lb] == h_win.max(axis=1), h[lb:n-lb], np.nan)
    sl[lb:n-lb] = np.where(l[lb:n-lb] == l_win.min(axis=1), l[lb:n-lb], np.nan)
    return sh, sl


def classify_candles(df):
    h, l, o, c = df['high'].values, df['low'].values, df['open'].values, df['close'].values
    n = len(df)
    atr = compute_atr(h, l, c)
    swing_h, swing_l = find_swings(h, l)
    half_atr = 0.5 * atr
    is_small = (h - l) < half_atr
    body = c - o
    direction = np.zeros(n, dtype=np.int32)
    label_code = np.zeros(n, dtype=np.int32)
    for i in range(1, n):
        if is_small[i]:
            label_code[i] = 1
        else:
            d = 1 if body[i] > 0 else -1
            if label_code[i-1] in (2, 3) and direction[i-1] == d:
                label_code[i] = 3
            else:
                label_code[i] = 2
            direction[i] = d
    df = df.copy()
    df['atr'] = atr
    df['swing_high'] = swing_h
    df['swing_low'] = swing_l
    df['label_code'] = label_code
    df['direction'] = direction
    return df


def detect_fvgs(df):
    h, l = df['high'].values, df['low'].values
    n = len(h)
    fvgs = []
    if n < 3:
        return fvgs
    bull = np.where(l[2:] > h[:-2])[0]
    bear = np.where(h[2:] < l[:-2])[0]
    for i in bull:
        fvgs.append((i+2, l[i+2], h[i], 1))
    for i in bear:
        fvgs.append((i+2, l[i], h[i+2], -1))
    return fvgs


def build_fvg_presence(n_bars, fvg_list, lookback=5):
    has_bull = np.zeros(n_bars, dtype=bool)
    has_bear = np.zeros(n_bars, dtype=bool)
    bull_top = np.full(n_bars, np.nan)
    bull_bot = np.full(n_bars, np.nan)
    bear_top = np.full(n_bars, np.nan)
    bear_bot = np.full(n_bars, np.nan)
    for idx, top, bot, d in fvg_list:
        start, end = idx, min(idx + lookback, n_bars)
        if d == 1:
            has_bull[start:end] = True
            bull_top[idx] = top
            bull_bot[idx] = bot
        else:
            has_bear[start:end] = True
            bear_top[idx] = top
            bear_bot[idx] = bot
    for arr in [bull_top, bull_bot, bear_top, bear_bot]:
        mask = np.isnan(arr)
        idx_arr = np.where(~mask, np.arange(len(arr)), 0)
        np.maximum.accumulate(idx_arr, out=idx_arr)
        arr[:] = arr[idx_arr]
    return has_bull, has_bear, bull_top, bull_bot, bear_top, bear_bot


def detect_signals(instrument, cfg, df_m1, now_utc):
    """Run V22 multi-fractal detection. Returns list of signal dicts."""
    if len(df_m1) < 100:
        return []

    minutes_now = now_utc.hour * 60 + now_utc.minute
    in_london = 480 <= minutes_now <= 720
    in_ny = 810 <= minutes_now <= 1275
    if not (in_london or in_ny):
        return []
    kz_label = 'London' if in_london else 'NY'

    # Build all TFs from M1
    tf_rules = set()
    for _, b, s, e, _ in FRACTALS:
        tf_rules.update([b, s, e])

    tf_data = {}
    for rule in tf_rules:
        df_tf = df_m1 if rule == '1min' else resample_df(df_m1, rule)
        if len(df_tf) < ATR_PERIOD + 10:
            tf_data[rule] = (pd.DataFrame(), [])
        else:
            dc = classify_candles(df_tf)
            tf_data[rule] = (dc, detect_fvgs(dc))

    # FVG presence per entry TF
    fvg_pres = {}
    for rule in tf_rules:
        df_tf, fvg_list = tf_data[rule]
        if len(df_tf) == 0:
            fvg_pres[rule] = None
        else:
            fvg_pres[rule] = build_fvg_presence(len(df_tf), fvg_list, 5)

    # Struct FVG index for TP
    struct_fvg = {}
    for rule in tf_rules:
        _, fvg_list = tf_data[rule]
        by_bar = defaultdict(list)
        for idx, top, bot, d in fvg_list:
            by_bar[idx].append((top, bot, d))
        struct_fvg[rule] = by_bar

    signals = []

    for fname, bias_tf, struct_tf, entry_tf, conviction in FRACTALS:
        df_bias, _ = tf_data.get(bias_tf, (pd.DataFrame(), []))
        df_struct, _ = tf_data.get(struct_tf, (pd.DataFrame(), []))
        df_entry, _ = tf_data.get(entry_tf, (pd.DataFrame(), []))

        if len(df_bias) < ATR_PERIOD + 5 or len(df_struct) < ATR_PERIOD + 5 or len(df_entry) < 5:
            continue

        fp = fvg_pres.get(entry_tf)
        if fp is None:
            continue

        bi = len(df_bias) - 1
        si = len(df_struct) - 1
        ei = len(df_entry) - 1

        b_dir = int(df_bias['direction'].iloc[bi])
        b_lc = int(df_bias['label_code'].iloc[bi])
        if b_dir == 0 or b_lc < 2:
            continue

        s_dir = int(df_struct['direction'].iloc[si])
        s_lc = int(df_struct['label_code'].iloc[si])
        if s_dir != b_dir or s_lc < 2:
            continue

        has_bull, has_bear, bull_top, bull_bot, bear_top, bear_bot = fp
        if b_dir == 1 and not has_bull[ei]:
            continue
        if b_dir == -1 and not has_bear[ei]:
            continue

        direction = b_dir
        if direction == 1:
            fvg_top = bull_top[ei]
            if np.isnan(fvg_top):
                continue
            entry_price = fvg_top + cfg['slippage']
        else:
            fvg_bot = bear_bot[ei]
            if np.isnan(fvg_bot):
                continue
            entry_price = fvg_bot - cfg['slippage']

        struct_atr = df_struct['atr'].iloc[si]
        if np.isnan(struct_atr) or struct_atr <= 0:
            continue
        buffer = struct_atr * cfg['buffer_mult']

        sl_s, sl_e = max(0, si - 10), si + 1
        if direction == 1:
            sv = df_struct['swing_low'].values[sl_s:sl_e]
            vs = sv[~np.isnan(sv)]
            sl_level = vs[-1] if len(vs) > 0 else df_struct['low'].values[sl_s:sl_e].min()
            sl_price = sl_level - buffer
            sl_dist = entry_price - sl_price
        else:
            sv = df_struct['swing_high'].values[sl_s:sl_e]
            vs = sv[~np.isnan(sv)]
            sl_level = vs[-1] if len(vs) > 0 else df_struct['high'].values[sl_s:sl_e].max()
            sl_price = sl_level + buffer
            sl_dist = sl_price - entry_price

        if sl_dist <= 0.01:
            continue
        if direction == 1 and sl_price >= entry_price:
            continue
        if direction == -1 and sl_price <= entry_price:
            continue

        # TP: liquidity targets
        tp_cands = []
        sw_s, sw_e = max(0, si - 30), si + 1
        if direction == 1:
            for v in df_struct['swing_high'].values[sw_s:sw_e][~np.isnan(df_struct['swing_high'].values[sw_s:sw_e])]:
                if v > entry_price:
                    tp_cands.append((v, 'swing_high'))
        else:
            for v in df_struct['swing_low'].values[sw_s:sw_e][~np.isnan(df_struct['swing_low'].values[sw_s:sw_e])]:
                if v < entry_price:
                    tp_cands.append((v, 'swing_low'))

        sfvg = struct_fvg.get(struct_tf, {})
        for bk in range(max(0, si - 20), si):
            for ftop, fbot, fd in sfvg.get(bk, []):
                if direction == 1 and fd == -1 and fbot > entry_price:
                    tp_cands.append((fbot, 'unfilled_fvg'))
                elif direction == -1 and fd == 1 and ftop < entry_price:
                    tp_cands.append((ftop, 'unfilled_fvg'))

        if not tp_cands:
            continue
        tp_cands.sort(key=lambda x: abs(x[0] - entry_price))
        tp_price, tp_type = tp_cands[0]

        tp_dist = (tp_price - entry_price) * direction
        if tp_dist <= 0:
            continue
        rr = tp_dist / sl_dist
        if rr < 1.0:
            continue

        signals.append({
            'instrument': instrument,
            'label': cfg['label'],
            'fractal': fname,
            'killzone': kz_label,
            'direction': 'long' if direction == 1 else 'short',
            'direction_int': direction,
            'entry_price': round(entry_price, 2),
            'sl_price': round(sl_price, 2),
            'tp_price': round(tp_price, 2),
            'tp_type': tp_type,
            'sl_dist': round(sl_dist, 2),
            'rr_target': round(rr, 2),
            'conviction': conviction,
            'signal_time': now_utc.isoformat(),
        })

    return signals


# ============================================================
# TRADING STATE & RISK
# ============================================================
class TradingState:
    def __init__(self):
        self.today = None
        self.daily_trades = 0
        self.daily_pnl = 0.0
        self.signals_today = 0
        self.last_trade_ts = 0
        self.active_setups = set()
        self.d1_used = {}
        self.peak_equity = None
        self.current_equity = None
        self.positions = []

    def reset_if_new_day(self):
        today = datetime.now(timezone.utc).date()
        if self.today != today:
            self.today = today
            self.daily_trades = 0
            self.daily_pnl = 0.0
            self.signals_today = 0
            self.active_setups = set()
            self.d1_used = {}
            log.info(f"New trading day: {today}")

    def can_trade(self, now_ts):
        if self.daily_trades >= MAX_TRADES_PER_DAY:
            return False
        if now_ts - self.last_trade_ts < MIN_GAP_SECONDS:
            return False
        return True

    def record_trade(self, now_ts):
        self.daily_trades += 1
        self.last_trade_ts = now_ts

    def get_risk(self):
        if self.peak_equity and self.current_equity and self.current_equity >= self.peak_equity:
            return RISK_GREEN
        return RISK_DRAWDOWN

    def update_equity(self, equity):
        self.current_equity = equity
        if self.peak_equity is None or equity > self.peak_equity:
            self.peak_equity = equity


# ============================================================
# DB WRITER
# ============================================================
def write_trade_to_db(signal, action, risk_amount, units):
    """Write trade/signal to trades.db."""
    try:
        conn = sqlite3.connect(str(TRADES_DB))
        conn.execute(
            """INSERT INTO trades (instrument, fractal, killzone, direction,
               entry_time, entry_price, sl_price, tp_price, tp_type,
               sl_dist, rr_target, outcome, pnl_dollar, risk_amount, conviction, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (signal['instrument'], signal['fractal'], signal['killzone'],
             signal['direction'], signal['signal_time'],
             signal['entry_price'], signal['sl_price'], signal['tp_price'],
             signal['tp_type'], signal['sl_dist'], signal['rr_target'],
             'pending' if action != 'DRY_RUN' else 'dry_run',
             0.0, risk_amount, signal['conviction'],
             f"{action} units={units}")
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.error(f"DB write error: {e}")


def sync_closed_trades():
    """Check Oanda for recently closed trades and update journal DB."""
    try:
        # Get recent closed trades from Oanda
        resp = api_get(f"/v3/accounts/{ACCOUNT_ID}/trades?state=CLOSED&count=20")
        closed = resp.get("trades", [])
        if not closed:
            return

        conn = sqlite3.connect(str(TRADES_DB))
        conn.row_factory = sqlite3.Row

        for t in closed:
            oanda_id = t.get("id", "")
            instrument = t.get("instrument", "")
            close_time = t.get("closeTime", "")[:19].replace("T", "T")
            open_time = t.get("openTime", "")[:19]
            realized_pl_cad = float(t.get("realizedPL", 0))
            entry_price = float(t.get("price", 0))
            units = float(t.get("initialUnits", 0))
            close_price = float(t.get("averageClosePrice", entry_price))

            # Convert CAD to USD (approximate)
            realized_pl_usd = round(realized_pl_cad / 1.36, 2)

            # Map Oanda instrument to our names
            inst_map = {"NAS100_USD": "NQ", "SPX500_USD": "ES", "US30_USD": "YM"}
            inst_name = inst_map.get(instrument, instrument)
            direction = "long" if units > 0 else "short"
            outcome = "win" if realized_pl_cad > 0 else "loss"

            # Check if this trade is already completed in DB
            # Match by entry_time (within 2 seconds) and instrument
            existing = conn.execute(
                """SELECT id, outcome FROM trades 
                   WHERE instrument = ? AND entry_time LIKE ? 
                   AND outcome NOT IN ('pending')
                   LIMIT 1""",
                (inst_name, open_time[:16] + "%")
            ).fetchone()

            if existing and existing["outcome"] in ("win", "loss"):
                continue  # Already recorded properly

            # Find the pending trade to update
            pending = conn.execute(
                """SELECT id FROM trades 
                   WHERE instrument = ? AND entry_time LIKE ?
                   AND outcome = 'pending'
                   LIMIT 1""",
                (inst_name, open_time[:16] + "%")
            ).fetchone()

            if pending:
                # Update existing pending trade
                conn.execute(
                    """UPDATE trades SET outcome=?, pnl_dollar=?, exit_time=?, 
                       exit_price=?, notes=COALESCE(notes,'') || ? 
                       WHERE id=?""",
                    (outcome, realized_pl_usd, close_time, close_price,
                     f" | Closed: PL={realized_pl_cad:.2f} CAD",
                     pending["id"])
                )
                log.info(f"📝 Updated trade #{pending['id']}: {inst_name} {direction} → {outcome} ${realized_pl_usd}")
            elif not existing:
                # No matching trade at all — insert new completed trade
                conn.execute(
                    """INSERT INTO trades (instrument, fractal, killzone, direction,
                       entry_time, exit_time, entry_price, exit_price, sl_price, tp_price,
                       outcome, pnl_dollar, risk_amount, notes)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (inst_name, '', 'NY', direction,
                     open_time, close_time, entry_price, close_price,
                     0, 0, outcome, realized_pl_usd, 0,
                     f"Auto-synced from Oanda. PL={realized_pl_cad:.2f} CAD, units={units}")
                )
                log.info(f"📝 Synced missing trade: {inst_name} {direction} → {outcome} ${realized_pl_usd}")

        conn.commit()
        conn.close()
    except Exception as e:
        log.error(f"Trade sync error: {e}")


def write_status(state, dm):
    """Write bot_status.json."""
    try:
        status = {
            "running": True,
            "last_check": datetime.now(timezone.utc).isoformat(),
            "today_trades": state.daily_trades,
            "today_pnl": round(state.daily_pnl, 2),
            "positions": state.positions,
            "signals_today": state.signals_today,
            "data_updated_to": {
                inst: dm.last_timestamp(inst) for inst in OANDA_INSTRUMENTS
            },
            "dry_run": DRY_RUN,
        }
        STATUS_FILE.write_text(json.dumps(status, indent=2))
    except Exception as e:
        log.error(f"Status write error: {e}")


# ============================================================
# ORDER EXECUTION
# ============================================================
def place_market_order(instrument, units, sl_price, tp_price):
    data = {
        "order": {
            "type": "MARKET",
            "instrument": instrument,
            "units": str(units),
            "timeInForce": "FOK",
            "stopLossOnFill": {"price": str(round(sl_price, 1))},
            "takeProfitOnFill": {"price": str(round(tp_price, 1))},
        }
    }
    return api_post(f"/v3/accounts/{ACCOUNT_ID}/orders", data)


def get_open_trades():
    return api_get(f"/v3/accounts/{ACCOUNT_ID}/openTrades").get("trades", [])


def close_trade(trade_id):
    return api_put(f"/v3/accounts/{ACCOUNT_ID}/trades/{trade_id}/close")


def flatten_all():
    """Close all open trades."""
    try:
        trades = get_open_trades()
        for t in trades:
            log.info(f"Flattening trade {t['id']}")
            close_trade(t['id'])
    except Exception as e:
        log.error(f"Flatten error: {e}")


# ============================================================
# MAIN LOOP
# ============================================================
def run():
    log.info("=" * 60)
    log.info("  V22 Live Bot — Starting")
    log.info(f"  Mode: {'DRY RUN' if DRY_RUN else 'LIVE'}")
    log.info(f"  Instruments: {list(OANDA_INSTRUMENTS.keys())}")
    log.info("=" * 60)

    dm = DataManager()
    state = TradingState()

    # Load & backfill
    dm.load_and_backfill()

    running = True
    def stop_handler(signum, frame):
        nonlocal running
        log.info("Shutdown signal received")
        running = False
    sig_mod.signal(sig_mod.SIGTERM, stop_handler)
    sig_mod.signal(sig_mod.SIGINT, stop_handler)

    last_update = 0
    last_sync = 0

    while running:
        try:
            now = datetime.now(timezone.utc)
            now_ts = now.timestamp()
            state.reset_if_new_day()

            # Skip weekends
            if now.weekday() >= 5:
                write_status(state, dm)
                time.sleep(POLL_INTERVAL)
                continue

            # Live data update every 60s
            if now_ts - last_update >= 60:
                dm.update_live()
                last_update = now_ts

            # Sync closed trades to journal every 5 min
            if now_ts - last_sync >= 300 and not DRY_RUN:
                sync_closed_trades()
                last_sync = now_ts

            # Flat by 21:15
            if now.hour > FLAT_HOUR or (now.hour == FLAT_HOUR and now.minute >= FLAT_MIN):
                if not DRY_RUN:
                    flatten_all()
                write_status(state, dm)
                time.sleep(POLL_INTERVAL)
                continue

            # KZ check
            mins = now.hour * 60 + now.minute
            in_kz = (480 <= mins <= 720) or (810 <= mins <= 1275)
            if not in_kz:
                write_status(state, dm)
                time.sleep(POLL_INTERVAL)
                continue

            # Update equity
            if not DRY_RUN:
                try:
                    acct = api_get(f"/v3/accounts/{ACCOUNT_ID}/summary")["account"]
                    state.update_equity(float(acct.get('NAV', acct.get('balance', 0))))
                    state.positions = [
                        {"id": t["id"], "instrument": t["instrument"], "units": t["currentUnits"]}
                        for t in get_open_trades()
                    ]
                except Exception as e:
                    log.error(f"Account update: {e}")

            if not state.can_trade(now_ts):
                write_status(state, dm)
                time.sleep(POLL_INTERVAL)
                continue

            # Scan all instruments
            all_signals = []
            for inst, cfg in OANDA_INSTRUMENTS.items():
                df = dm.get_df(inst)
                if len(df) < 100:
                    continue
                sigs = detect_signals(inst, cfg, df, now)
                all_signals.extend(sigs)

            state.signals_today += len(all_signals)

            if all_signals:
                all_signals.sort(key=lambda x: -x['conviction'])

                for signal in all_signals:
                    if not state.can_trade(now_ts):
                        break

                    setup_key = f"{signal['instrument']}_{signal['fractal']}_{signal['direction']}"
                    if setup_key in state.active_setups:
                        continue

                    if signal['fractal'] == 'F4_D1':
                        d1_key = (signal['instrument'], signal['direction_int'])
                        if d1_key in state.d1_used:
                            continue
                        state.d1_used[d1_key] = True

                    risk_amount = state.get_risk()
                    units = max(1, int(risk_amount / (signal['sl_dist'] * cfg['point_val'])))
                    # Cap units by available margin (instrument margin rate ~5-12%)
                    try:
                        acct = requests.get(f"{BASE_URL}/v3/accounts/{ACCOUNT_ID}/summary",
                                          headers=HEADERS, timeout=5).json()['account']
                        margin_avail = float(acct['marginAvailable'])
                        price_now = signal['entry_price']
                        margin_per_unit = price_now * 0.15  # conservative estimate
                        max_units = max(1, int(margin_avail * 0.8 / margin_per_unit))
                        if units > max_units:
                            log.info(f"  Capping units {units} -> {max_units} (margin: ${margin_avail:.0f})")
                            units = max_units
                    except Exception as e:
                        log.warning(f"  Margin check failed: {e}")
                    if signal['direction'] == 'short':
                        units = -units

                    log.info(
                        f"{'📋' if DRY_RUN else '🔴'} SIGNAL: {signal['label']} {signal['fractal']} "
                        f"{signal['direction']} @ {signal['entry_price']} "
                        f"SL={signal['sl_price']} TP={signal['tp_price']} "
                        f"R:R={signal['rr_target']:.1f} [{signal['killzone']}] "
                        f"risk=${risk_amount} units={abs(units)}"
                    )

                    action = "DRY_RUN"
                    if not DRY_RUN:
                        try:
                            result = place_market_order(
                                signal['instrument'], units,
                                signal['sl_price'], signal['tp_price']
                            )
                            action = "EXECUTED"
                            log.info(f"Order result: {json.dumps(result)}")
                        except Exception as e:
                            log.error(f"Order failed: {e}")
                            action = "FAILED"

                    write_trade_to_db(signal, action, abs(risk_amount), abs(units))
                    state.active_setups.add(setup_key)
                    state.record_trade(now_ts)

            write_status(state, dm)

        except Exception as e:
            log.error(f"Cycle error: {e}", exc_info=True)

        time.sleep(POLL_INTERVAL)

    # Shutdown — final sync
    if not DRY_RUN:
        time.sleep(3)  # Wait for Oanda to process any final closes
        sync_closed_trades()
    write_status(state, dm)
    log.info("Bot stopped.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        if STATUS_FILE.exists():
            print(STATUS_FILE.read_text())
        else:
            print('{"running": false}')
    elif len(sys.argv) > 1 and sys.argv[1] == "backfill":
        dm = DataManager()
        dm.load_and_backfill()
        print("Backfill complete.")
    else:
        run()
