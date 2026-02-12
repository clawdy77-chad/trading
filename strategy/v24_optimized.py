"""
V24 — Optimized TTFM/GxT Strategy (Vectorized)
================================================
Based on V22 with 4 loss-analysis optimizations:
1. Remove session_high/session_low TP types (high loss rates)
2. Cap R:R at 2.5x (tighten TP, don't skip)
3. Time-based exit at 120 minutes
4. Skip London early trades (09:00-10:00 UTC)
"""

import pandas as pd
import numpy as np
from datetime import timedelta
from pathlib import Path
import warnings, gc, time as _time, sys
warnings.filterwarnings('ignore')
def pr(s): print(s); sys.stdout.flush()

DATA_DIR = Path('/root/.openclaw/workspace/trading/data_10y')
OUTPUT_DIR = Path('/root/.openclaw/workspace/trading')

TRAIN_START = pd.Timestamp('2016-03-01', tz='UTC')
TRAIN_END   = pd.Timestamp('2023-12-31', tz='UTC')
OOS_START   = pd.Timestamp('2024-01-01', tz='UTC')
OOS_END     = pd.Timestamp('2026-01-31', tz='UTC')

RISK_PER_TRADE = 200
MAX_TRADES_PER_DAY = 3
ATR_PERIOD = 14
SWING_LB = 3

INSTRUMENTS = {
    'NQ': {'file': 'nas100_usd_m1_10y.parquet', 'slippage': 2, 'point_val': 2.0, 'buffer_mult': 0.3},
    'ES': {'file': 'spx500_usd_m1_10y.parquet', 'slippage': 0.75, 'point_val': 5.0, 'buffer_mult': 0.3},
    'YM': {'file': 'us30_usd_m1_10y.parquet', 'slippage': 3, 'point_val': 0.50, 'buffer_mult': 0.3},
}

FRACTALS = [
    ('F1_M30', '30min', '15min', '1min',  1.0),
    ('F2_H1',  '1h',    '30min', '5min',  1.2),
    ('F3_H4',  '4h',    '1h',    '15min', 1.5),
    ('F4_D1',  '1D',    '4h',    '1h',    2.0),
]


def load_data(filename):
    df = pd.read_parquet(DATA_DIR / filename)
    df['time'] = pd.to_datetime(df['time'], utc=True)
    df = df.set_index('time').sort_index()
    return df[['open', 'high', 'low', 'close', 'volume']]


def resample(df, rule):
    return df.resample(rule).agg(
        {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
    ).dropna()


def compute_atr_vec(h, l, c, period=ATR_PERIOD):
    prev_c = np.empty_like(c)
    prev_c[0] = c[0]
    prev_c[1:] = c[:-1]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    tr[0] = h[0] - l[0]
    atr = pd.Series(tr).ewm(span=period, adjust=False).mean().values
    return atr


def find_swings_vec(h, l, lb=SWING_LB):
    n = len(h)
    sh = np.full(n, np.nan)
    sl = np.full(n, np.nan)
    win = 2 * lb + 1
    if n < win:
        return sh, sl
    from numpy.lib.stride_tricks import sliding_window_view
    h_win = sliding_window_view(h, win)
    l_win = sliding_window_view(l, win)
    max_h = h_win.max(axis=1)
    min_l = l_win.min(axis=1)
    center_h = h[lb:n-lb]
    center_l = l[lb:n-lb]
    sh_mask = center_h == max_h
    sl_mask = center_l == min_l
    sh[lb:n-lb] = np.where(sh_mask, center_h, np.nan)
    sl[lb:n-lb] = np.where(sl_mask, center_l, np.nan)
    return sh, sl


def precompute_tf(df_1m, rule):
    """Return resampled df with atr/swings/labels/direction + FVG list."""
    df = resample(df_1m, rule)
    h, l, o, c = df['high'].values, df['low'].values, df['open'].values, df['close'].values
    n = len(df)

    atr = compute_atr_vec(h, l, c)
    swing_h, swing_l = find_swings_vec(h, l)

    # Vectorized C1/C2/C3 classification
    rng = h - l
    body = c - o
    half_atr = 0.5 * atr
    is_small = rng < half_atr  # C1

    # For C2/C3: displacement candles
    disp_dir = np.where(body > 0, 1, np.where(body < 0, -1, 0))
    # C1 candles have no direction for classification purposes
    # We need sequential logic for C3 (continuation of previous C2/C3)
    # Vectorize with a single pass using numba-style approach in numpy
    direction = np.zeros(n, dtype=np.int32)
    label_code = np.zeros(n, dtype=np.int32)  # 0=none, 1=C1, 2=C2, 3=C3

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

    # FVGs vectorized
    fvg_bar_idx = []  # (bar_index, top, bot, direction)
    if n >= 3:
        bull_fvg = l[2:] > h[:-2]
        bear_fvg = h[2:] < l[:-2]
        bull_idx = np.where(bull_fvg)[0]
        bear_idx = np.where(bear_fvg)[0]
        for i in bull_idx:
            fvg_bar_idx.append((i + 2, l[i + 2], h[i], 1))
        for i in bear_idx:
            fvg_bar_idx.append((i + 2, l[i], h[i + 2], -1))

    return df, fvg_bar_idx


def build_fvg_presence(n_bars, fvg_list, lookback=5):
    """Build arrays: has_bull_fvg[i], has_bear_fvg[i] = True if FVG in direction within last `lookback` bars."""
    has_bull = np.zeros(n_bars, dtype=bool)
    has_bear = np.zeros(n_bars, dtype=bool)
    bull_top = np.full(n_bars, np.nan)
    bull_bot = np.full(n_bars, np.nan)
    bear_top = np.full(n_bars, np.nan)
    bear_bot = np.full(n_bars, np.nan)

    for idx, top, bot, d in fvg_list:
        start = idx
        end = min(idx + lookback, n_bars)
        if d == 1:
            has_bull[start:end] = True
            bull_top[idx] = top
            bull_bot[idx] = bot
        else:
            has_bear[start:end] = True
            bear_top[idx] = top
            bear_bot[idx] = bot

    _ffill_inplace(bull_top)
    _ffill_inplace(bull_bot)
    _ffill_inplace(bear_top)
    _ffill_inplace(bear_bot)

    return has_bull, has_bear, bull_top, bull_bot, bear_top, bear_bot


def _ffill_inplace(arr):
    """Forward-fill NaN values in-place."""
    mask = np.isnan(arr)
    idx = np.where(~mask, np.arange(len(arr)), 0)
    np.maximum.accumulate(idx, out=idx)
    arr[:] = arr[idx]


def build_fvg_index(fvg_list, n_bars):
    """Build per-bar index of nearby FVGs for fast TP lookup.
    Returns dict: bar_idx -> list of (top, bot, direction) for FVGs within 20 bars before."""
    from collections import defaultdict
    fvg_by_bar = defaultdict(list)
    for idx, top, bot, d in fvg_list:
        fvg_by_bar[idx].append((top, bot, d))
    return fvg_by_bar


def generate_raw_signals(inst_name, inst_cfg, start, end):
    """Generate all raw candidate signals for an instrument+period. No filtering."""
    pr(f"  Loading {inst_name}...")
    t0 = _time.time()
    df_1m = load_data(inst_cfg['file'])
    warmup_start = start - timedelta(days=60)
    df_full = df_1m[(df_1m.index >= warmup_start) & (df_1m.index <= end)]
    pr(f"    Loaded {len(df_full)} bars in {_time.time()-t0:.1f}s")

    pr(f"  Precomputing timeframes...")
    t0 = _time.time()
    all_rules = set()
    for _, b, s, e, _ in FRACTALS:
        all_rules.update([b, s, e])
    tf_data = {}
    for rule in all_rules:
        tf_data[rule] = precompute_tf(df_full, rule)
    pr(f"    Done in {_time.time()-t0:.1f}s")

    m1_h = df_full['high'].values
    m1_l = df_full['low'].values
    m1_c = df_full['close'].values
    m1_times = df_full.index

    daily = resample(df_full, '1D')
    session_hl = {}
    for i in range(1, len(daily)):
        dt = daily.index[i].date()
        session_hl[dt] = (daily['high'].iloc[i-1], daily['low'].iloc[i-1])

    scan_df = resample(df_full[(df_full.index >= start) & (df_full.index <= end)], '15min')
    scan_minutes = scan_df.index.hour * 60 + scan_df.index.minute
    # London early filter: skip 09:00-10:00 UTC (hour == 9, minutes 540-599)
    kz_mask = (((scan_minutes >= 480) & (scan_minutes < 540)) | ((scan_minutes >= 600) & (scan_minutes <= 720)) | ((scan_minutes >= 810) & (scan_minutes <= 1275)))
    scan_times = scan_df.index[kz_mask]
    n_scan = len(scan_times)
    pr(f"  {n_scan} KZ scan points for {inst_name}")

    pr(f"  Building FVG presence arrays...")
    t0 = _time.time()
    fvg_data = {}
    for rule in all_rules:
        df_tf, fvg_list = tf_data[rule]
        n_bars = len(df_tf)
        fvg_data[rule] = build_fvg_presence(n_bars, fvg_list, lookback=5)
    pr(f"    Done in {_time.time()-t0:.1f}s")

    pr(f"  Vectorized signal detection...")
    t0 = _time.time()

    tf_indices = {}
    for rule in all_rules:
        df_tf, _ = tf_data[rule]
        tf_indices[rule] = df_tf.index.searchsorted(scan_times, side='right') - 1

    m1_scan_idx = m1_times.searchsorted(scan_times, side='right') - 1

    st_minutes = scan_times.hour * 60 + scan_times.minute
    kz_labels = np.where(st_minutes <= 720, 'London', 'NY')

    # Build struct FVG index
    struct_fvg_idx = {}
    for rule in all_rules:
        _, fvg_list = tf_data[rule]
        struct_fvg_idx[rule] = build_fvg_index(fvg_list, len(tf_data[rule][0]))

    raw_signals = []

    for fi, (fractal_name, bias_tf, struct_tf, entry_tf, conviction) in enumerate(FRACTALS):
        df_bias, _ = tf_data[bias_tf]
        df_struct, struct_fvgs = tf_data[struct_tf]
        df_entry, entry_fvgs = tf_data[entry_tf]

        bi = tf_indices[bias_tf]
        si = tf_indices[struct_tf]
        ei = tf_indices[entry_tf]

        valid = (bi >= ATR_PERIOD + 5) & (si >= ATR_PERIOD + 5) & (ei >= 5) & (bi >= 0) & (si >= 0) & (ei >= 0)

        bias_dir_arr = df_bias['direction'].values
        bias_lc_arr = df_bias['label_code'].values
        bi_safe = np.clip(bi, 0, len(bias_dir_arr) - 1)
        si_safe = np.clip(si, 0, len(df_struct) - 1)
        ei_safe = np.clip(ei, 0, len(df_entry) - 1)

        b_dir = bias_dir_arr[bi_safe]
        b_lc = bias_lc_arr[bi_safe]
        bias_ok = valid & (b_dir != 0) & (b_lc >= 2)

        s_dir = df_struct['direction'].values[si_safe]
        s_lc = df_struct['label_code'].values[si_safe]
        struct_ok = bias_ok & (s_dir == b_dir) & (s_lc >= 2)

        has_bull, has_bear, bull_top, bull_bot, bear_top, bear_bot = fvg_data[entry_tf]
        ei_clipped = np.clip(ei_safe, 0, len(has_bull) - 1)
        fvg_bull_ok = has_bull[ei_clipped]
        fvg_bear_ok = has_bear[ei_clipped]
        fvg_ok = struct_ok & np.where(b_dir == 1, fvg_bull_ok, fvg_bear_ok)

        signal_indices = np.where(fvg_ok)[0]

        for idx in signal_indices:
            direction = int(b_dir[idx])
            si_val = int(si_safe[idx])
            ei_val = int(ei_safe[idx])

            # Compute entry price
            _, _, e_bull_top, e_bull_bot, e_bear_top, e_bear_bot = fvg_data[entry_tf]
            if direction == 1:
                fvg_top = e_bull_top[ei_val]
                if np.isnan(fvg_top):
                    continue
                entry_price = fvg_top + inst_cfg['slippage']
            else:
                fvg_bot = e_bear_bot[ei_val]
                if np.isnan(fvg_bot):
                    continue
                entry_price = fvg_bot - inst_cfg['slippage']

            # Stop loss
            struct_atr_vals = df_struct['atr'].values
            struct_atr = struct_atr_vals[si_val]
            if np.isnan(struct_atr):
                continue
            buffer = struct_atr * inst_cfg['buffer_mult']

            sl_start_i = max(0, si_val - 10)
            sl_end_i = si_val + 1

            if direction == 1:
                swing_vals = df_struct['swing_low'].values[sl_start_i:sl_end_i]
                valid_swings = swing_vals[~np.isnan(swing_vals)]
                sl_level = valid_swings[-1] if len(valid_swings) > 0 else df_struct['low'].values[sl_start_i:sl_end_i].min()
                sl_price = sl_level - buffer
                sl_dist = entry_price - sl_price
            else:
                swing_vals = df_struct['swing_high'].values[sl_start_i:sl_end_i]
                valid_swings = swing_vals[~np.isnan(swing_vals)]
                sl_level = valid_swings[-1] if len(valid_swings) > 0 else df_struct['high'].values[sl_start_i:sl_end_i].max()
                sl_price = sl_level + buffer
                sl_dist = sl_price - entry_price

            if sl_dist <= 0:
                continue

            # Liquidity target
            tp_candidates = []
            sw_start = max(0, si_val - 30)
            sw_end = si_val + 1
            day_key = scan_times[idx].date()

            if direction == 1:
                sh_vals = df_struct['swing_high'].values[sw_start:sw_end]
                valid_sh = sh_vals[~np.isnan(sh_vals)]
                for v in valid_sh:
                    if v > entry_price:
                        tp_candidates.append((v, 'swing_high'))
            else:
                sl_cands = df_struct['swing_low'].values[sw_start:sw_end]
                valid_sl = sl_cands[~np.isnan(sl_cands)]
                for v in valid_sl:
                    if v < entry_price:
                        tp_candidates.append((v, 'swing_low'))
            sfvg = struct_fvg_idx[struct_tf]
            for bar_k in range(max(0, si_val - 20), si_val):
                for ftop, fbot, fd in sfvg.get(bar_k, []):
                    if direction == 1 and fd == -1 and fbot > entry_price:
                        tp_candidates.append((fbot, 'unfilled_fvg'))
                    elif direction == -1 and fd == 1 and ftop < entry_price:
                        tp_candidates.append((ftop, 'unfilled_fvg'))

            if not tp_candidates:
                continue

            tp_candidates.sort(key=lambda x: abs(x[0] - entry_price))
            tp_price, tp_type = tp_candidates[0]

            tp_dist = (tp_price - entry_price) * direction
            if tp_dist <= 0:
                continue

            rr = tp_dist / sl_dist
            if rr < 1.0:
                continue

            # Cap R:R at 2.5x — tighten TP, don't skip
            if rr > 2.5:
                tp_dist = sl_dist * 2.5
                tp_price = entry_price + tp_dist * direction
                rr = 2.5

            # Validate SL/TP logic (strict — no equal allowed)
            if direction == 1 and sl_price >= entry_price:
                continue
            if direction == -1 and sl_price <= entry_price:
                continue
            if sl_dist < 0.01:
                continue

            # Simulate trade on 1m data — start from NEXT bar after entry
            m1_idx = m1_scan_idx[idx] + 1
            if m1_idx < 2 or m1_idx >= len(m1_h):
                continue

            # Find session end: 21:15 UTC (16:15 ET) on entry day
            entry_ts = scan_times[idx]
            session_end = entry_ts.normalize() + pd.Timedelta(hours=21, minutes=15)
            # Find 1m bar index for session end
            session_end_idx = m1_times.searchsorted(session_end, side='right')
            end_idx_m1 = min(m1_idx + 480, len(m1_h), session_end_idx)
            if m1_idx >= end_idx_m1:
                continue

            h_slice = m1_h[m1_idx:end_idx_m1]
            l_slice = m1_l[m1_idx:end_idx_m1]

            if direction == 1:
                sl_hits = np.where(l_slice <= sl_price)[0]
                tp_hits = np.where(h_slice >= tp_price)[0]
            else:
                sl_hits = np.where(h_slice >= sl_price)[0]
                tp_hits = np.where(l_slice <= tp_price)[0]

            sl_bar = sl_hits[0] if len(sl_hits) > 0 else 999999
            tp_bar = tp_hits[0] if len(tp_hits) > 0 else 999999

            slippage_cost = inst_cfg['slippage'] * inst_cfg['point_val']

            # Time-based exit at 120 minutes
            time_exit_bar = 120

            if sl_bar == 999999 and tp_bar == 999999 or (min(sl_bar, tp_bar) > time_exit_bar):
                # Time exit at 120 bars or session end, whichever is first
                actual_exit = min(time_exit_bar, end_idx_m1 - m1_idx - 1)
                actual_exit = max(actual_exit, 0)
                exit_bar = m1_idx + actual_exit
                close_price = m1_c[exit_bar] if exit_bar < len(m1_c) else entry_price
                pnl_pts = (close_price - entry_price) * direction
                outcome = 'win' if pnl_pts > 0 else 'loss'
            elif sl_bar <= tp_bar:
                outcome = 'loss'
                exit_bar = m1_idx + sl_bar
                pnl_pts = -sl_dist
            else:
                outcome = 'win'
                exit_bar = m1_idx + tp_bar
                pnl_pts = tp_dist

            exit_time = m1_times[exit_bar] if exit_bar < len(m1_times) else scan_times[idx]
            pos_size = RISK_PER_TRADE / (sl_dist * inst_cfg['point_val'])
            pnl_dollar = pnl_pts * pos_size * inst_cfg['point_val'] - slippage_cost

            kz = kz_labels[idx]
            ts = scan_times[idx]

            # For D1 fractal dedup: track bias bar index
            bias_bar_idx = int(bi_safe[idx])

            raw_signals.append({
                'instrument': inst_name,
                'fractal': fractal_name,
                'killzone': kz,
                'direction': 'long' if direction == 1 else 'short',
                'direction_int': direction,
                'entry_time': ts,
                'exit_time': exit_time,
                'entry_price': round(entry_price, 2),
                'sl_price': round(sl_price, 2),
                'tp_price': round(tp_price, 2),
                'tp_type': tp_type,
                'sl_dist': round(sl_dist, 2),
                'rr_target': round(rr, 2),
                'outcome': outcome,
                'pnl_dollar': round(pnl_dollar, 2),
                'pnl_pts': round(pnl_pts, 2),
                'conviction': conviction,
                'bias_bar_idx': bias_bar_idx,
            })

    pr(f"    {len(raw_signals)} raw signals for {inst_name} in {_time.time()-t0:.1f}s")
    return raw_signals


def filter_signals(raw_signals):
    """Apply execution constraints in a single pass over time-sorted signals.
    
    Constraints:
    1. Max 3 trades per calendar day (global across instruments)
    2. 30-minute gap between ANY trades (global)
    3. No duplicate entries: after a trade, require NEW FVG (different entry price) 
       per instrument, and skip 30 min minimum
    4. F4 (D1) signal: once taken for a direction+instrument, mark as used until 
       the D1 bias bar index changes
    """
    if not raw_signals:
        return []

    # Sort by entry_time, then by conviction (higher first)
    raw_signals.sort(key=lambda x: (x['entry_time'], -x['conviction']))

    trades = []
    daily_trades = {}       # date -> count
    last_trade_ts = 0       # unix seconds of last trade
    # Per-instrument: last entry price and last trade time
    inst_last_entry = {}    # inst -> (entry_price, unix_ts)
    # F4 D1 dedup: (instrument, direction) -> bias_bar_idx that was used
    d1_used = {}            # (inst, dir_int) -> bias_bar_idx

    for sig in raw_signals:
        day_key = sig['entry_time'].date()
        ts_int = int(sig['entry_time'].timestamp())

        # 1. Daily limit
        if daily_trades.get(day_key, 0) >= MAX_TRADES_PER_DAY:
            continue

        # 2. Global 30-min gap
        if ts_int - last_trade_ts < 1800:
            continue

        # 3. Duplicate entry check: same instrument needs different price AND 30-min gap
        inst = sig['instrument']
        if inst in inst_last_entry:
            last_price, last_ts = inst_last_entry[inst]
            if ts_int - last_ts < 1800:
                continue
            if last_price == sig['entry_price'] and ts_int - last_ts < 7200:
                # Same entry price within 2 hours = likely same FVG, skip
                continue

        # 4. F4 D1 dedup: if this is a D1 fractal signal, check if already used
        if sig['fractal'] == 'F4_D1':
            d1_key = (inst, sig['direction_int'])
            used_bar = d1_used.get(d1_key)
            if used_bar is not None and used_bar == sig['bias_bar_idx']:
                continue  # Same D1 candle already traded
            # Mark as used
            d1_used[d1_key] = sig['bias_bar_idx']

        # Signal passes all filters — take the trade
        trades.append(sig)
        daily_trades[day_key] = daily_trades.get(day_key, 0) + 1
        last_trade_ts = ts_int
        inst_last_entry[inst] = (sig['entry_price'], ts_int)

    return trades


def compute_metrics(df, label=""):
    if len(df) == 0:
        return {'label': label, 'trades': 0, 'wins': 0, 'losses': 0, 'wr_pct': 0,
                'pf': 0, 'total_pnl': 0, 'avg_rr_target': 0, 'avg_rr_achieved': 0,
                'trades_per_week': 0, 'max_dd': 0, 'avg_win': 0, 'avg_loss': 0}

    n = len(df)
    wins = (df['outcome'] == 'win').sum()
    losses = n - wins
    wr = wins / n * 100

    avg_win = df.loc[df['outcome'] == 'win', 'pnl_dollar'].mean() if wins > 0 else 0
    avg_loss = abs(df.loc[df['outcome'] == 'loss', 'pnl_dollar'].mean()) if losses > 0 else 1
    pf = (avg_win * wins) / (avg_loss * losses) if losses > 0 else 99

    days_span = (df['entry_time'].max() - df['entry_time'].min()).days
    weeks = max(days_span / 7, 1)
    trades_per_week = n / weeks

    cumsum = df['pnl_dollar'].cumsum()
    max_dd = (cumsum - cumsum.cummax()).min()

    return {
        'label': label, 'trades': n, 'wins': int(wins), 'losses': int(losses),
        'wr_pct': round(wr, 1), 'pf': round(pf, 2),
        'total_pnl': round(df['pnl_dollar'].sum(), 2),
        'avg_rr_target': round(df['rr_target'].mean(), 2),
        'avg_rr_achieved': round(df.apply(lambda r: r['rr_target'] if r['outcome'] == 'win' else -1.0, axis=1).mean(), 2),
        'trades_per_week': round(trades_per_week, 2),
        'max_dd': round(max_dd, 2),
        'avg_win': round(avg_win, 2), 'avg_loss': round(avg_loss, 2),
    }


def eval_pass_rate(df, target_pnl=3000, max_dd_limit=-2000, window_days=10):
    """10-day rolling eval windows at $200/trade risk."""
    if len(df) < 5:
        return 0
    df_s = df.sort_values('entry_time')
    start = df_s['entry_time'].min()
    end = df_s['entry_time'].max()
    passes = attempts = 0
    current = start
    while current + timedelta(days=window_days) <= end:
        w = df_s[(df_s['entry_time'] >= current) & (df_s['entry_time'] < current + timedelta(days=window_days))]
        if len(w) > 0:
            cs = w['pnl_dollar'].cumsum()
            dd = (cs - cs.cummax()).min()
            if cs.iloc[-1] >= target_pnl and dd >= max_dd_limit:
                passes += 1
            attempts += 1
        current += timedelta(days=1)
    return round(passes / max(attempts, 1) * 100, 1)


def generate_report(all_trades, train_df, oos_df):
    lines = ["# V24 Optimized TTFM/GxT — Results\n"]
    lines.append("## Strategy Overview")
    lines.append("- Multi-fractal scanning (F1: M30→M15→M1, F2: H1→M30→M5, F3: H4→H1→M15, F4: D1→H4→H1)")
    lines.append("- Liquidity-based targets (swing H/L, session H/L, unfilled FVGs)")
    lines.append("- Adaptive SL at sweep extreme + 0.3×ATR buffer")
    lines.append(f"- Risk: ${RISK_PER_TRADE}/trade, max {MAX_TRADES_PER_DAY}/day")
    lines.append("- Killzones: London 08:00-12:00, NY 13:30-21:15 UTC")
    lines.append("- Eval: 10-day windows, $3K target, -$2K DD limit\n")

    for period_name, df in [("TRAIN (2020-2023)", train_df), ("OOS (2024-2025)", oos_df)]:
        lines.append(f"\n## {period_name}\n")
        if len(df) == 0:
            lines.append("No trades.\n")
            continue

        m = compute_metrics(df, period_name)
        ep = eval_pass_rate(df)

        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        for k, v in [('Trades', m['trades']), ('Trades/Week', m['trades_per_week']),
                      ('Win Rate', f"{m['wr_pct']}%"), ('Profit Factor', m['pf']),
                      ('Avg R:R Target', m['avg_rr_target']), ('Avg R:R Achieved', m['avg_rr_achieved']),
                      ('Total P&L', f"${m['total_pnl']:,.2f}"), ('Avg Win', f"${m['avg_win']:,.2f}"),
                      ('Avg Loss', f"${m['avg_loss']:,.2f}"), ('Max DD', f"${m['max_dd']:,.2f}"),
                      ('Eval Pass Rate (10d)', f"{ep}%")]:
            lines.append(f"| {k} | {v} |")

        for group_name, group_col, group_vals in [
            ("Instrument", "instrument", ['NQ', 'ES', 'YM']),
            ("Fractal", "fractal", ['F1_M30', 'F2_H1', 'F3_H4', 'F4_D1']),
            ("Killzone", "killzone", ['London', 'NY']),
        ]:
            lines.append(f"\n### By {group_name}\n")
            lines.append(f"| {group_name} | Trades | WR% | PF | Avg R:R | P&L |")
            lines.append("|" + "---|" * 6)
            for val in group_vals:
                sub = df[df[group_col] == val]
                if len(sub) == 0:
                    continue
                sm = compute_metrics(sub)
                lines.append(f"| {val} | {sm['trades']} | {sm['wr_pct']}% | {sm['pf']} | {sm['avg_rr_target']} | ${sm['total_pnl']:,.2f} |")

        lines.append("\n### By Target Type\n")
        lines.append("| Target | Trades | WR% | Avg R:R |")
        lines.append("|--------|--------|-----|---------|")
        for tp in df['tp_type'].unique():
            sub = df[df['tp_type'] == tp]
            sm = compute_metrics(sub)
            lines.append(f"| {tp} | {sm['trades']} | {sm['wr_pct']}% | {sm['avg_rr_target']} |")

    return '\n'.join(lines)


if __name__ == '__main__':
    t_start = _time.time()

    # Generate raw signals per period, then filter globally within each period
    for period_label, p_start, p_end in [("TRAIN", TRAIN_START, TRAIN_END), ("OOS", OOS_START, OOS_END)]:
        pr(f"\n{'='*60}")
        pr(f"  {period_label} period: {p_start.date()} to {p_end.date()}")

    all_trades = []
    for period_label, p_start, p_end in [("TRAIN", TRAIN_START, TRAIN_END), ("OOS", OOS_START, OOS_END)]:
        raw_signals = []
        for inst_name, inst_cfg in INSTRUMENTS.items():
            pr(f"\n=== {inst_name} {period_label} ===")
            raw_signals.extend(generate_raw_signals(inst_name, inst_cfg, p_start, p_end))
            gc.collect()

        pr(f"\n  Filtering {len(raw_signals)} raw signals for {period_label}...")
        filtered = filter_signals(raw_signals)
        pr(f"  {len(filtered)} trades after filtering")
        all_trades.extend(filtered)

    # Remove internal fields
    for t in all_trades:
        t.pop('direction_int', None)
        t.pop('bias_bar_idx', None)

    df_all = pd.DataFrame(all_trades)

    if len(df_all) > 0:
        df_all.to_csv(OUTPUT_DIR / 'v24_results.csv', index=False)

        train_df = df_all[(df_all['entry_time'] >= TRAIN_START) & (df_all['entry_time'] <= TRAIN_END)]
        oos_df = df_all[(df_all['entry_time'] >= OOS_START) & (df_all['entry_time'] <= OOS_END)]

        report = generate_report(df_all, train_df, oos_df)
        (OUTPUT_DIR / 'V24_RESULTS.md').write_text(report)

        pr(f"\n{'='*60}")
        pr(report)
    else:
        pr("\nNo trades found!")
        (OUTPUT_DIR / 'V24_RESULTS.md').write_text("# V24 Results\n\nNo trades found.")

    pr(f"\nTotal: {_time.time() - t_start:.0f}s")
