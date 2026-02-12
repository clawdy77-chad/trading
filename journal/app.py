"""Trading Journal - FastAPI Backend"""
import sqlite3
import csv
import os
import json
import re
import httpx
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
import uvicorn
import pandas as pd

DB_PATH = Path(__file__).parent / "trades.db"
CSV_PATH = "/root/.openclaw/workspace/trading/v22_results.csv"
BOT_STATUS_PATH = "/root/.openclaw/workspace/trading/bot_status.json"
BOT_LOG_PATH = "/root/.openclaw/workspace/trading/live_bot.log"
ENV_PATH = "/root/.openclaw/workspace/.env"

app = FastAPI(title="Trading Journal")

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instrument TEXT,
            fractal TEXT,
            killzone TEXT,
            direction TEXT,
            entry_time TEXT,
            exit_time TEXT,
            entry_price REAL,
            exit_price REAL,
            sl_price REAL,
            tp_price REAL,
            tp_type TEXT,
            sl_dist REAL,
            rr_target REAL,
            outcome TEXT,
            pnl_dollar REAL,
            pnl_pts REAL,
            risk_amount REAL DEFAULT 200,
            conviction REAL,
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.execute("INSERT OR IGNORE INTO settings VALUES ('starting_equity', '0')")
    conn.execute("INSERT OR IGNORE INTO settings VALUES ('equity_target', '3000')")
    conn.execute("INSERT OR IGNORE INTO settings VALUES ('green_risk', '500')")
    conn.execute("INSERT OR IGNORE INTO settings VALUES ('red_risk', '250')")
    conn.execute("INSERT OR IGNORE INTO settings VALUES ('max_dd', '2000')")
    # Ensure notes column exists
    try:
        conn.execute("ALTER TABLE trades ADD COLUMN notes TEXT DEFAULT ''")
    except:
        pass
    conn.commit()
    conn.close()

def _read_oanda_key():
    try:
        with open(ENV_PATH) as f:
            for line in f:
                if line.startswith("OANDA_API_KEY="):
                    return line.strip().split("=", 1)[1]
    except:
        pass
    return None

def import_csv(filepath):
    conn = get_db()
    count = 0
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            conn.execute("""
                INSERT INTO trades (instrument, fractal, killzone, direction, entry_time, exit_time,
                    entry_price, sl_price, tp_price, tp_type, sl_dist, rr_target, outcome,
                    pnl_dollar, pnl_pts, conviction, exit_price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row['instrument'], row['fractal'], row['killzone'], row['direction'],
                row['entry_time'], row['exit_time'],
                float(row['entry_price']), float(row['sl_price']), float(row['tp_price']),
                row['tp_type'], float(row['sl_dist']), float(row['rr_target']),
                row['outcome'], float(row['pnl_dollar']), float(row['pnl_pts']),
                float(row.get('conviction', 1.0)),
                float(row['tp_price']) if row['outcome'] == 'win' else float(row['sl_price'])
            ))
            count += 1
    conn.commit()
    conn.close()
    return count

# --- Helper: filtered stats ---
def _get_trades_filtered(date_from=None, date_to=None):
    conn = get_db()
    where = []
    params = []
    if date_from:
        where.append("entry_time >= ?")
        params.append(date_from)
    if date_to:
        where.append("entry_time < ?")
        params.append(date_to)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    trades = conn.execute(f"SELECT * FROM trades {where_sql} ORDER BY entry_time", params).fetchall()
    conn.close()
    return [dict(t) for t in trades]

# --- API Routes ---

@app.get("/api/stats")
def get_stats(period: str = ""):
    now = date.today()
    date_from = None
    if period == "today":
        date_from = now.isoformat()
    elif period == "week":
        date_from = (now - timedelta(days=now.weekday())).isoformat()
    elif period == "month":
        date_from = now.replace(day=1).isoformat()

    trades = _get_trades_filtered(date_from=date_from)
    if not trades:
        return {"total": 0}

    wins = [t for t in trades if t['outcome'] == 'win']
    losses = [t for t in trades if t['outcome'] == 'loss']

    total = len(trades)
    win_count = len(wins)
    win_rate = win_count / total * 100 if total else 0

    gross_wins = sum(t['pnl_dollar'] for t in wins)
    gross_losses = abs(sum(t['pnl_dollar'] for t in losses))
    profit_factor = gross_wins / gross_losses if gross_losses else 0
    avg_win = gross_wins / win_count if win_count else 0
    avg_loss = gross_losses / len(losses) if losses else 0

    cumulative = []
    running = 0
    peak = 0
    max_dd = 0
    for t in trades:
        running += t['pnl_dollar']
        cumulative.append(running)
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd:
            max_dd = dd

    rolling_wr = []
    for i in range(len(trades)):
        window = trades[max(0, i-19):i+1]
        w = sum(1 for t in window if t['outcome'] == 'win')
        rolling_wr.append(w / len(window) * 100)

    streak = 0
    streak_type = trades[-1]['outcome'] if trades else ''
    for t in reversed(trades):
        if t['outcome'] == streak_type:
            streak += 1
        else:
            break

    today_str = date.today().isoformat()
    week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    month_start = date.today().replace(day=1).isoformat()

    trades_today = sum(1 for t in trades if t['entry_time'][:10] == today_str)
    trades_week = sum(1 for t in trades if t['entry_time'][:10] >= week_start)
    trades_month = sum(1 for t in trades if t['entry_time'][:10] >= month_start)

    eq_labels = [t['entry_time'][:10] for t in trades]

    return {
        "total": total,
        "wins": win_count,
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "profit_factor": round(profit_factor, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "max_drawdown": round(max_dd, 2),
        "total_pnl": round(running, 2),
        "current_streak": streak,
        "streak_type": streak_type,
        "trades_today": trades_today,
        "trades_week": trades_week,
        "trades_month": trades_month,
        "equity_curve": cumulative,
        "equity_labels": eq_labels,
        "rolling_wr": rolling_wr,
        "peak_equity": round(peak, 2),
    }

@app.get("/api/stats/filtered")
def get_stats_filtered(date_from: str = "", date_to: str = "", direction: str = ""):
    import math
    conn = get_db()
    where = []
    params = []
    if date_from:
        where.append("entry_time >= ?")
        params.append(date_from)
    if date_to:
        where.append("entry_time < ?")
        params.append(date_to)
    if direction and direction.lower() in ('long', 'short'):
        where.append("direction = ?")
        params.append(direction.lower())
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    trades = [dict(t) for t in conn.execute(
        f"SELECT * FROM trades {where_sql} ORDER BY entry_time", params
    ).fetchall()]
    conn.close()

    if not trades:
        return {"total": 0}

    wins = [t for t in trades if t['outcome'] == 'win']
    losses = [t for t in trades if t['outcome'] == 'loss']
    total = len(trades)
    win_count = len(wins)
    win_rate = win_count / total * 100 if total else 0

    pnls = [t['pnl_dollar'] for t in trades]
    gross_wins = sum(t['pnl_dollar'] for t in wins)
    gross_losses = abs(sum(t['pnl_dollar'] for t in losses))
    profit_factor = gross_wins / gross_losses if gross_losses else 0
    avg_win = gross_wins / win_count if win_count else 0
    avg_loss = gross_losses / len(losses) if losses else 0
    net_profit = sum(pnls)
    avg_trade = net_profit / total if total else 0

    # Equity curve, peak, max DD
    cumulative = []
    running = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        running += t['pnl_dollar']
        cumulative.append(round(running, 2))
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd:
            max_dd = dd

    eq_labels = [t['entry_time'][:10] for t in trades]

    # Recovery factor
    recovery_factor = net_profit / max_dd if max_dd > 0 else 0

    # SQN = sqrt(n) * avg / std
    import statistics
    std_pnl = statistics.stdev(pnls) if len(pnls) > 1 else 0
    sqn = (math.sqrt(total) * avg_trade / std_pnl) if std_pnl > 0 else 0

    # Sharpe ratio (daily returns, annualized)
    daily_pnl = {}
    for t in trades:
        d = t['entry_time'][:10]
        daily_pnl[d] = daily_pnl.get(d, 0) + t['pnl_dollar']
    daily_returns = list(daily_pnl.values())
    trading_days = len(daily_returns)
    if trading_days > 1:
        dr_mean = statistics.mean(daily_returns)
        dr_std = statistics.stdev(daily_returns)
        sharpe = (dr_mean / dr_std * math.sqrt(252)) if dr_std > 0 else 0
    else:
        sharpe = 0

    # Stagnation: max calendar days between equity highs
    stagnation = 0
    eq_peak = 0
    last_high_date = trades[0]['entry_time'][:10] if trades else ''
    running2 = 0.0
    for t in trades:
        running2 += t['pnl_dollar']
        if running2 > eq_peak:
            eq_peak = running2
            cur_date = t['entry_time'][:10]
            if last_high_date:
                try:
                    d1 = datetime.strptime(last_high_date, '%Y-%m-%d')
                    d2 = datetime.strptime(cur_date, '%Y-%m-%d')
                    gap = (d2 - d1).days
                    if gap > stagnation:
                        stagnation = gap
                except:
                    pass
            last_high_date = cur_date
    # Also check from last high to last trade
    if last_high_date and trades:
        try:
            d1 = datetime.strptime(last_high_date, '%Y-%m-%d')
            d2 = datetime.strptime(trades[-1]['entry_time'][:10], '%Y-%m-%d')
            gap = (d2 - d1).days
            if gap > stagnation:
                stagnation = gap
        except:
            pass

    # P-value (t-test: is mean PnL significantly > 0?)
    p_value = 1.0
    if total > 2 and std_pnl > 0:
        t_stat = avg_trade / (std_pnl / math.sqrt(total))
        # Approximate p-value using normal distribution for large n
        # For small n this is rough but good enough
        p_value = 0.5 * math.erfc(t_stat / math.sqrt(2))

    # Rolling WR
    rolling_wr = []
    for i in range(len(trades)):
        window = trades[max(0, i-19):i+1]
        w = sum(1 for t in window if t['outcome'] == 'win')
        rolling_wr.append(round(w / len(window) * 100, 1))

    # Streak
    streak = 0
    streak_type = trades[-1]['outcome'] if trades else ''
    for t in reversed(trades):
        if t['outcome'] == streak_type:
            streak += 1
        else:
            break

    return {
        "total": total,
        "wins": win_count,
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "profit_factor": round(profit_factor, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "net_profit": round(net_profit, 2),
        "avg_trade": round(avg_trade, 2),
        "max_drawdown": round(max_dd, 2),
        "peak_equity": round(peak, 2),
        "recovery_factor": round(recovery_factor, 2),
        "sqn": round(sqn, 2),
        "sharpe": round(sharpe, 2),
        "stagnation_days": stagnation,
        "p_value": round(p_value, 4),
        "trading_days": trading_days,
        "equity_curve": cumulative,
        "equity_labels": eq_labels,
        "rolling_wr": rolling_wr,
        "current_streak": streak,
        "streak_type": streak_type,
    }

@app.get("/api/bot/status")
def get_bot_status():
    try:
        with open(BOT_STATUS_PATH) as f:
            data = json.load(f)
        return data
    except Exception as e:
        return {"running": False, "error": str(e)}

@app.get("/api/account")
async def get_account():
    key = _read_oanda_key()
    if not key:
        raise HTTPException(500, "OANDA_API_KEY not found in .env")
    account_id = os.getenv('OANDA_ACCOUNT_ID', '')
    url = f"https://api-fxpractice.oanda.com/v3/accounts/{account_id}/summary"
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, headers={"Authorization": f"Bearer {key}"})
            r.raise_for_status()
            acc = r.json().get("account", {})
            return {
                "balance": float(acc.get("balance", 0)),
                "equity": float(acc.get("NAV", 0)),
                "unrealized_pnl": float(acc.get("unrealizedPL", 0)),
                "margin_used": float(acc.get("marginUsed", 0)),
                "open_trade_count": int(acc.get("openTradeCount", 0)),
                "currency": acc.get("currency", "USD"),
            }
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/api/signals/recent")
def get_recent_signals():
    signals = []
    try:
        with open(BOT_LOG_PATH) as f:
            lines = f.readlines()
        signal_lines = [l for l in lines if "SIGNAL:" in l][-20:]
        for line in reversed(signal_lines):
            # Parse: 2026-02-12 14:33:43,966 [INFO] 🔴 SIGNAL: ES F3_H4 long @ 6969.95 SL=6954.87 TP=6996.7 R:R=1.8 [NY] risk=$500 units=33
            m = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*SIGNAL:\s+(\S+)\s+(\S+)\s+(\S+)\s+@\s+([\d.]+)\s+SL=([\d.]+)\s+TP=([\d.]+)\s+R:R=([\d.]+)\s+\[(\S+)\]', line)
            if m:
                signals.append({
                    "timestamp": m.group(1),
                    "instrument": m.group(2),
                    "fractal": m.group(3),
                    "direction": m.group(4),
                    "entry": float(m.group(5)),
                    "sl": float(m.group(6)),
                    "tp": float(m.group(7)),
                    "rr": float(m.group(8)),
                    "killzone": m.group(9),
                })
    except Exception as e:
        pass
    return {"signals": signals}

@app.get("/api/analysis/hourly_wr")
def get_hourly_wr():
    conn = get_db()
    trades = [dict(t) for t in conn.execute("SELECT * FROM trades").fetchall()]
    conn.close()
    hours = {}
    for h in range(24):
        hours[h] = {"wins": 0, "total": 0}
    for t in trades:
        try:
            dt = datetime.fromisoformat(t['entry_time'].replace('+00:00', ''))
            h = dt.hour
            hours[h]["total"] += 1
            if t['outcome'] == 'win':
                hours[h]["wins"] += 1
        except:
            pass
    result = []
    for h in range(24):
        d = hours[h]
        wr = (d["wins"] / d["total"] * 100) if d["total"] else 0
        result.append({"hour": h, "win_rate": round(wr, 1), "total": d["total"], "wins": d["wins"]})
    return {"hours": result}

@app.get("/api/analysis/fractal")
def get_fractal_analysis():
    conn = get_db()
    trades = [dict(t) for t in conn.execute("SELECT * FROM trades").fetchall()]
    conn.close()
    groups = {}
    for t in trades:
        f = t.get('fractal', '') or 'Unknown'
        if f not in groups:
            groups[f] = []
        groups[f].append(t)
    result = []
    for name, gtrades in sorted(groups.items()):
        wins = sum(1 for t in gtrades if t['outcome'] == 'win')
        total = len(gtrades)
        pnl = sum(t['pnl_dollar'] for t in gtrades)
        gross_w = sum(t['pnl_dollar'] for t in gtrades if t['outcome'] == 'win')
        gross_l = abs(sum(t['pnl_dollar'] for t in gtrades if t['outcome'] == 'loss'))
        pf = gross_w / gross_l if gross_l else 0
        result.append({
            "name": name,
            "total": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": round(wins / total * 100, 1) if total else 0,
            "pnl": round(pnl, 2),
            "profit_factor": round(pf, 2),
            "avg_pnl": round(pnl / total, 2) if total else 0,
        })
    return {"groups": result}

@app.get("/api/streaks")
def get_streaks():
    conn = get_db()
    trades = [dict(t) for t in conn.execute("SELECT outcome FROM trades ORDER BY entry_time").fetchall()]
    conn.close()
    if not trades:
        return {"current": 0, "current_type": "", "best_win": 0, "worst_loss": 0}

    # Current streak
    current = 1
    current_type = trades[-1]['outcome']
    for i in range(len(trades)-2, -1, -1):
        if trades[i]['outcome'] == current_type:
            current += 1
        else:
            break

    # Best/worst ever
    best_win = 0
    worst_loss = 0
    streak = 1
    for i in range(1, len(trades)):
        if trades[i]['outcome'] == trades[i-1]['outcome']:
            streak += 1
        else:
            if trades[i-1]['outcome'] == 'win' and streak > best_win:
                best_win = streak
            elif trades[i-1]['outcome'] == 'loss' and streak > worst_loss:
                worst_loss = streak
            streak = 1
    # Final streak
    if trades[-1]['outcome'] == 'win' and streak > best_win:
        best_win = streak
    elif trades[-1]['outcome'] == 'loss' and streak > worst_loss:
        worst_loss = streak

    return {"current": current, "current_type": current_type, "best_win": best_win, "worst_loss": worst_loss}

@app.get("/api/eval")
def get_eval(start_date: str = ""):
    target = 3000
    max_dd = 2000
    risk = 500
    trades = _get_trades_filtered(date_from=start_date if start_date else None)
    if not trades:
        return {"status": "no_trades", "total_pnl": 0, "peak": 0, "drawdown": 0, "days": 0, "trades": 0, "target": target, "max_dd": max_dd, "risk": risk}

    cumulative = 0
    peak = 0
    max_dd_actual = 0
    eod_pnls = {}
    failed = False
    fail_reason = ""

    for t in trades:
        cumulative += t['pnl_dollar']
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd_actual:
            max_dd_actual = dd
        day = t['entry_time'][:10]
        eod_pnls[day] = cumulative

    # Check EOD trailing DD
    eod_peak = 0
    for day in sorted(eod_pnls.keys()):
        eod_val = eod_pnls[day]
        if eod_val > eod_peak:
            eod_peak = eod_val
        eod_dd = eod_peak - eod_val
        if eod_dd > max_dd:
            failed = True
            fail_reason = f"EOD DD exceeded on {day}: ${eod_dd:.0f} > ${max_dd}"
            break

    passed = cumulative >= target and not failed
    status = "pass" if passed else ("fail" if failed else "in_progress")

    days_trading = len(eod_pnls)
    return {
        "status": status,
        "fail_reason": fail_reason,
        "total_pnl": round(cumulative, 2),
        "peak": round(peak, 2),
        "drawdown": round(max_dd_actual, 2),
        "eod_drawdown": round(peak - cumulative, 2),
        "days": days_trading,
        "trades": len(trades),
        "target": target,
        "max_dd": max_dd,
        "risk": risk,
        "progress_pct": round(min(100, max(0, cumulative / target * 100)), 1),
        "dd_pct": round(min(100, max(0, (peak - cumulative) / max_dd * 100)), 1),
    }

@app.get("/api/analysis/edge_decay")
def get_edge_decay():
    conn = get_db()
    trades = [dict(t) for t in conn.execute("SELECT outcome FROM trades ORDER BY entry_time").fetchall()]
    conn.close()
    if len(trades) < 50:
        return {"rolling": [], "overall_wr": 0}
    overall_wr = sum(1 for t in trades if t['outcome'] == 'win') / len(trades) * 100
    rolling = []
    for i in range(49, len(trades)):
        window = trades[i-49:i+1]
        wr = sum(1 for t in window if t['outcome'] == 'win') / 50 * 100
        rolling.append(round(wr, 1))
    return {"rolling": rolling, "overall_wr": round(overall_wr, 1)}

class SettingsUpdate(BaseModel):
    green_risk: Optional[float] = None
    red_risk: Optional[float] = None
    max_dd: Optional[float] = None
    target: Optional[float] = None

@app.get("/api/settings")
def get_settings():
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return {r['key']: r['value'] for r in rows}

@app.post("/api/settings")
def update_settings(body: SettingsUpdate):
    conn = get_db()
    mapping = {
        'green_risk': body.green_risk,
        'red_risk': body.red_risk,
        'max_dd': body.max_dd,
        'equity_target': body.target,
    }
    for key, val in mapping.items():
        if val is not None:
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(val)))
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.get("/api/stats/daily")
def get_daily_stats():
    conn = get_db()
    trades = [dict(t) for t in conn.execute("SELECT * FROM trades ORDER BY entry_time").fetchall()]
    conn.close()
    days = {}
    for t in trades:
        d = t['entry_time'][:10]
        if d not in days:
            days[d] = 0
        days[d] += t['pnl_dollar']
    result = [{"date": d, "pnl": round(p, 2)} for d, p in sorted(days.items())]
    return {"daily": result}

@app.get("/api/eval/monte_carlo")
def get_monte_carlo_stats():
    conn = get_db()
    trades = [dict(t) for t in conn.execute("SELECT pnl_dollar FROM trades ORDER BY entry_time").fetchall()]
    conn.close()
    if not trades:
        return {"pnls": [], "mean": 0, "std": 0, "count": 0}
    pnls = [t['pnl_dollar'] for t in trades]
    import numpy as np
    arr = np.array(pnls)
    percentiles = {str(p): round(float(np.percentile(arr, p)), 2) for p in [5, 25, 50, 75, 95]}
    return {
        "pnls": pnls,
        "mean": round(float(arr.mean()), 2),
        "std": round(float(arr.std()), 2),
        "count": len(pnls),
        "percentiles": percentiles,
    }

class NoteUpdate(BaseModel):
    note: str

@app.put("/api/trade/{trade_id}/note")
def update_trade_note(trade_id: int, body: NoteUpdate):
    conn = get_db()
    row = conn.execute("SELECT id FROM trades WHERE id = ?", (trade_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Trade not found")
    conn.execute("UPDATE trades SET notes = ? WHERE id = ?", (body.note, trade_id))
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.get("/api/trades")
def get_trades(page: int = 1, limit: int = 50, instrument: str = "", outcome: str = ""):
    conn = get_db()
    where = []
    params = []
    if instrument:
        where.append("instrument = ?")
        params.append(instrument)
    if outcome:
        where.append("outcome = ?")
        params.append(outcome)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    total = conn.execute(f"SELECT COUNT(*) FROM trades {where_sql}", params).fetchone()[0]
    offset = (page - 1) * limit
    rows = conn.execute(
        f"SELECT * FROM trades {where_sql} ORDER BY entry_time DESC LIMIT ? OFFSET ?",
        params + [limit, offset]
    ).fetchall()
    conn.close()
    return {"trades": [dict(r) for r in rows], "total": total, "page": page, "pages": (total + limit - 1) // limit}

@app.get("/api/analysis/{dimension}")
def get_analysis(dimension: str):
    conn = get_db()
    trades = [dict(t) for t in conn.execute("SELECT * FROM trades ORDER BY entry_time").fetchall()]
    conn.close()

    if not trades:
        return {"groups": []}

    def group_key(t):
        if dimension == "instrument":
            return t['instrument']
        elif dimension == "fractal":
            return t['fractal']
        elif dimension == "killzone":
            return t['killzone']
        elif dimension == "day_of_week":
            try:
                dt = datetime.fromisoformat(t['entry_time'].replace('+00:00', ''))
                return dt.strftime('%A')
            except:
                return 'Unknown'
        elif dimension == "hour":
            try:
                dt = datetime.fromisoformat(t['entry_time'].replace('+00:00', ''))
                return f"{dt.hour:02d}:00"
            except:
                return 'Unknown'
        elif dimension == "tp_type":
            return t['tp_type']
        elif dimension == "direction":
            return t['direction']
        return 'all'

    groups = {}
    for t in trades:
        k = group_key(t)
        if k not in groups:
            groups[k] = []
        groups[k].append(t)

    result = []
    for name, gtrades in sorted(groups.items()):
        wins = sum(1 for t in gtrades if t['outcome'] == 'win')
        total = len(gtrades)
        pnl = sum(t['pnl_dollar'] for t in gtrades)
        gross_w = sum(t['pnl_dollar'] for t in gtrades if t['outcome'] == 'win')
        gross_l = abs(sum(t['pnl_dollar'] for t in gtrades if t['outcome'] == 'loss'))
        pf = gross_w / gross_l if gross_l else 0
        result.append({
            "name": name,
            "total": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": round(wins / total * 100, 1) if total else 0,
            "pnl": round(pnl, 2),
            "profit_factor": round(pf, 2),
            "avg_pnl": round(pnl / total, 2) if total else 0,
        })

    return {"groups": result}

@app.get("/api/calendar/{year}/{month}")
def get_calendar(year: int, month: int):
    conn = get_db()
    start = f"{year}-{month:02d}-01"
    if month == 12:
        end = f"{year+1}-01-01"
    else:
        end = f"{year}-{month+1:02d}-01"

    rows = conn.execute(
        "SELECT * FROM trades WHERE entry_time >= ? AND entry_time < ? ORDER BY entry_time",
        (start, end)
    ).fetchall()
    conn.close()

    days = {}
    for r in rows:
        d = dict(r)
        day = d['entry_time'][:10]
        if day not in days:
            days[day] = {"date": day, "pnl": 0, "trades": 0, "wins": 0}
        days[day]['pnl'] += d['pnl_dollar']
        days[day]['trades'] += 1
        if d['outcome'] == 'win':
            days[day]['wins'] += 1

    for d in days.values():
        d['pnl'] = round(d['pnl'], 2)

    return {"days": days}

@app.get("/api/calendar/day/{day}")
def get_day_trades(day: str):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM trades WHERE entry_time LIKE ? ORDER BY entry_time",
        (f"{day}%",)
    ).fetchall()
    conn.close()
    return {"trades": [dict(r) for r in rows]}

@app.get("/api/heatmap")
def get_heatmap():
    conn = get_db()
    trades = [dict(t) for t in conn.execute("SELECT * FROM trades").fetchall()]
    conn.close()

    heatmap = [[0]*24 for _ in range(7)]
    counts = [[0]*24 for _ in range(7)]
    for t in trades:
        try:
            dt = datetime.fromisoformat(t['entry_time'].replace('+00:00', ''))
            dow = dt.weekday()
            hour = dt.hour
            heatmap[dow][hour] += t['pnl_dollar']
            counts[dow][hour] += 1
        except:
            pass

    return {"pnl": heatmap, "counts": counts}

@app.get("/api/best_worst_days")
def best_worst_days():
    conn = get_db()
    trades = [dict(t) for t in conn.execute("SELECT * FROM trades ORDER BY entry_time").fetchall()]
    conn.close()

    days = {}
    for t in trades:
        d = t['entry_time'][:10]
        days[d] = days.get(d, 0) + t['pnl_dollar']

    sorted_days = sorted(days.items(), key=lambda x: x[1])
    worst = [{"date": d, "pnl": round(p, 2)} for d, p in sorted_days[:10]]
    best = [{"date": d, "pnl": round(p, 2)} for d, p in reversed(sorted_days[-10:])]
    return {"best": best, "worst": worst}

class TradeCreate(BaseModel):
    instrument: str
    fractal: str = ""
    killzone: str = ""
    direction: str
    entry_time: str
    exit_time: str = ""
    entry_price: float
    exit_price: float = 0
    sl_price: float = 0
    tp_price: float = 0
    tp_type: str = ""
    sl_dist: float = 0
    rr_target: float = 0
    outcome: str = ""
    pnl_dollar: float = 0
    pnl_pts: float = 0
    risk_amount: float = 200
    conviction: float = 1.0
    notes: str = ""

@app.post("/api/trades")
def create_trade(trade: TradeCreate):
    conn = get_db()
    conn.execute("""
        INSERT INTO trades (instrument, fractal, killzone, direction, entry_time, exit_time,
            entry_price, exit_price, sl_price, tp_price, tp_type, sl_dist, rr_target,
            outcome, pnl_dollar, pnl_pts, risk_amount, conviction, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (trade.instrument, trade.fractal, trade.killzone, trade.direction,
          trade.entry_time, trade.exit_time, trade.entry_price, trade.exit_price,
          trade.sl_price, trade.tp_price, trade.tp_type, trade.sl_dist, trade.rr_target,
          trade.outcome, trade.pnl_dollar, trade.pnl_pts, trade.risk_amount,
          trade.conviction, trade.notes))
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.post("/api/import")
async def import_csv_upload(file: UploadFile = File(...)):
    content = await file.read()
    tmp = "/tmp/import_trades.csv"
    with open(tmp, 'wb') as f:
        f.write(content)
    try:
        count = import_csv(tmp)
        return {"imported": count}
    except Exception as e:
        raise HTTPException(400, str(e))

@app.delete("/api/trades/{trade_id}")
def delete_trade(trade_id: int):
    conn = get_db()
    conn.execute("DELETE FROM trades WHERE id = ?", (trade_id,))
    conn.commit()
    conn.close()
    return {"status": "ok"}

import pyarrow.parquet as pq

PARQUET_DIR = Path("/root/.openclaw/workspace/trading/data_10y")
INSTRUMENT_MAP = {
    "NQ": "nas100_usd_m1_10y.parquet",
    "NAS100": "nas100_usd_m1_10y.parquet",
    "ES": "spx500_usd_m1_10y.parquet",
    "SPX500": "spx500_usd_m1_10y.parquet",
    "YM": "us30_usd_m1_10y.parquet",
    "US30": "us30_usd_m1_10y.parquet",
}

def _load_candles(instrument: str, start: pd.Timestamp, end: pd.Timestamp):
    fname = INSTRUMENT_MAP.get(instrument.upper())
    if not fname:
        return None
    path = PARQUET_DIR / fname
    if not path.exists():
        return None
    import pyarrow.compute as pc
    import pyarrow as pa
    filters = [
        ("time", ">=", start.to_pydatetime()),
        ("time", "<=", end.to_pydatetime()),
    ]
    table = pq.read_table(str(path), filters=filters)
    df = table.to_pandas()
    df = df.sort_values("time").reset_index(drop=True)
    return df

@app.get("/api/trade/{trade_id}/candles")
def get_trade_candles(trade_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Trade not found")
    trade = dict(row)

    entry_dt = pd.Timestamp(trade["entry_time"])
    exit_dt = pd.Timestamp(trade["exit_time"]) if trade["exit_time"] else entry_dt + pd.Timedelta(hours=1)

    if entry_dt.tzinfo is None:
        entry_dt = entry_dt.tz_localize("UTC")
    if exit_dt.tzinfo is None:
        exit_dt = exit_dt.tz_localize("UTC")

    start = entry_dt - pd.Timedelta(minutes=60)
    end = exit_dt + pd.Timedelta(minutes=30)

    candles = _load_candles(trade["instrument"], start, end)
    if candles is None or candles.empty:
        raise HTTPException(404, f"No candle data for {trade['instrument']}")

    candle_list = []
    for _, c in candles.iterrows():
        candle_list.append({
            "time": int(c["time"].timestamp()),
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
        })

    return {
        "candles": candle_list,
        "trade": {
            "id": trade["id"],
            "instrument": trade["instrument"],
            "direction": trade["direction"],
            "entry_time": int(entry_dt.timestamp()),
            "exit_time": int(exit_dt.timestamp()),
            "entry_price": trade["entry_price"],
            "exit_price": trade["exit_price"],
            "sl_price": trade["sl_price"],
            "tp_price": trade["tp_price"],
            "outcome": trade["outcome"],
            "pnl_dollar": trade["pnl_dollar"],
            "pnl_pts": trade["pnl_pts"],
            "rr_target": trade["rr_target"],
        }
    }

@app.get("/api/trades/all")
def get_all_trades_simple():
    conn = get_db()
    rows = conn.execute("SELECT id, instrument, direction, entry_time, outcome, pnl_dollar FROM trades ORDER BY entry_time DESC").fetchall()
    conn.close()
    return {"trades": [dict(r) for r in rows]}

# Serve frontend
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

@app.get("/")
def index():
    return HTMLResponse(open(str(Path(__file__).parent / "static" / "index.html")).read())

@app.on_event("startup")
def startup():
    init_db()
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    conn.close()
    if count == 0 and os.path.exists(CSV_PATH):
        print(f"Importing backtest data from {CSV_PATH}...")
        n = import_csv(CSV_PATH)
        print(f"Imported {n} trades")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
