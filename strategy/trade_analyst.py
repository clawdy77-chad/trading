#!/usr/bin/env python3
"""Trade Analyst — analyzes journal DB trades and produces actionable insights."""

import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys

DB_PATH = "/root/.openclaw/workspace/tradingjournal/trades.db"

def load_trades(live_only=False, days=None):
    db = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM trades", db)
    df['entry_time'] = pd.to_datetime(df['entry_time'], format='mixed', utc=True)
    df['exit_time'] = pd.to_datetime(df['exit_time'], format='mixed', utc=True)
    if live_only:
        df = df[df.entry_time >= '2026-02-12']
    if days:
        cutoff = datetime.now().astimezone() - timedelta(days=days)
        df = df[df.entry_time >= cutoff]
    db.close()
    return df

def win_rate(df):
    if len(df) == 0: return 0.0
    return (df.outcome == 'win').sum() / len(df) * 100

def profit_factor(df):
    wins = df[df.pnl_dollar > 0].pnl_dollar.sum()
    losses = abs(df[df.pnl_dollar < 0].pnl_dollar.sum())
    if losses == 0: return float('inf') if wins > 0 else 0.0
    return wins / losses

def analyze_full(df, label="All Trades"):
    """Full breakdown analysis."""
    lines = []
    lines.append(f"📊 **{label}** ({len(df)} trades)")
    lines.append(f"━━━━━━━━━━━━━━━━━━━━")
    
    total_pnl = df.pnl_dollar.sum()
    wr = win_rate(df)
    pf = profit_factor(df)
    wins = (df.outcome == 'win').sum()
    losses = (df.outcome == 'loss').sum()
    
    lines.append(f"**Overall**: {wr:.1f}% WR | PF {pf:.2f} | {wins}W/{losses}L")
    lines.append(f"**P&L**: ${total_pnl:,.0f} | Avg win ${df[df.pnl_dollar>0].pnl_dollar.mean():.0f} | Avg loss ${df[df.pnl_dollar<0].pnl_dollar.mean():.0f}")
    
    # Max drawdown
    cum = df.sort_values('entry_time').pnl_dollar.cumsum()
    peak = cum.cummax()
    dd = (cum - peak).min()
    lines.append(f"**Max DD**: ${dd:,.0f}")
    
    # By instrument
    lines.append(f"\n🏷 **By Instrument**:")
    for inst in sorted(df.instrument.unique()):
        sub = df[df.instrument == inst]
        lines.append(f"  {inst}: {win_rate(sub):.1f}% WR, PF {profit_factor(sub):.2f}, {len(sub)} trades, ${sub.pnl_dollar.sum():,.0f}")
    
    # By fractal
    lines.append(f"\n🔬 **By Fractal**:")
    for frac in ['F1_M30', 'F2_H1', 'F3_H4', 'F4_D1']:
        sub = df[df.fractal == frac]
        if len(sub) == 0: continue
        lines.append(f"  {frac}: {win_rate(sub):.1f}% WR, PF {profit_factor(sub):.2f}, {len(sub)} trades")
    
    # By killzone
    lines.append(f"\n⏰ **By Killzone**:")
    for kz in ['London', 'NY']:
        sub = df[df.killzone == kz]
        if len(sub) == 0: continue
        lines.append(f"  {kz}: {win_rate(sub):.1f}% WR, PF {profit_factor(sub):.2f}, {len(sub)} trades")
    
    # By direction
    lines.append(f"\n↕️ **By Direction**:")
    for d in ['long', 'short']:
        sub = df[df.direction == d]
        if len(sub) == 0: continue
        lines.append(f"  {d.title()}: {win_rate(sub):.1f}% WR, PF {profit_factor(sub):.2f}, {len(sub)} trades")
    
    # By TP type
    if 'tp_type' in df.columns and df.tp_type.notna().any():
        lines.append(f"\n🎯 **By TP Type**:")
        for tp in df.tp_type.dropna().unique():
            sub = df[df.tp_type == tp]
            lines.append(f"  {tp}: {win_rate(sub):.1f}% WR, PF {profit_factor(sub):.2f}, {len(sub)} trades")
    
    # R:R analysis
    if 'rr_target' in df.columns and df.rr_target.notna().any():
        lines.append(f"\n📐 **R:R Analysis**:")
        rr = df[df.rr_target.notna()]
        bins = [(0, 1.5, "< 1.5"), (1.5, 2.5, "1.5-2.5"), (2.5, 100, "> 2.5")]
        for lo, hi, label in bins:
            sub = rr[(rr.rr_target >= lo) & (rr.rr_target < hi)]
            if len(sub) == 0: continue
            lines.append(f"  R:R {label}: {win_rate(sub):.1f}% WR, PF {profit_factor(sub):.2f}, {len(sub)} trades")
    
    # Worst setups (fractal + killzone + direction combos with <50% WR and 10+ trades)
    lines.append(f"\n🚨 **Worst Setups** (WR < 55%, 10+ trades):")
    found_bad = False
    for frac in df.fractal.unique():
        for kz in df.killzone.unique():
            for d in df.direction.unique():
                sub = df[(df.fractal == frac) & (df.killzone == kz) & (df.direction == d)]
                if len(sub) >= 10 and win_rate(sub) < 55:
                    found_bad = True
                    lines.append(f"  ⚠️ {frac} {kz} {d}: {win_rate(sub):.1f}% WR, {len(sub)} trades, ${sub.pnl_dollar.sum():,.0f}")
    if not found_bad:
        lines.append(f"  ✅ None — all combos above 55% WR")
    
    # Best setups
    lines.append(f"\n🌟 **Best Setups** (WR > 75%, 10+ trades):")
    found_good = False
    for frac in df.fractal.unique():
        for kz in df.killzone.unique():
            for d in df.direction.unique():
                sub = df[(df.fractal == frac) & (df.killzone == kz) & (df.direction == d)]
                if len(sub) >= 10 and win_rate(sub) > 75:
                    found_good = True
                    lines.append(f"  🔥 {frac} {kz} {d}: {win_rate(sub):.1f}% WR, {len(sub)} trades, ${sub.pnl_dollar.sum():,.0f}")
    if not found_good:
        lines.append(f"  None above 75%")
    
    # Streak analysis
    outcomes = df.sort_values('entry_time').outcome.values
    max_win_streak = max_loss_streak = cur_win = cur_loss = 0
    for o in outcomes:
        if o == 'win':
            cur_win += 1; cur_loss = 0
            max_win_streak = max(max_win_streak, cur_win)
        else:
            cur_loss += 1; cur_win = 0
            max_loss_streak = max(max_loss_streak, cur_loss)
    lines.append(f"\n🔥 **Streaks**: Max win {max_win_streak} | Max loss {max_loss_streak}")
    
    # Conviction analysis
    if 'conviction' in df.columns and df.conviction.notna().any():
        lines.append(f"\n💪 **Conviction Analysis**:")
        conv = df[df.conviction.notna()]
        for c in sorted(conv.conviction.unique()):
            sub = conv[conv.conviction == c]
            if len(sub) >= 5:
                lines.append(f"  Conv {c}: {win_rate(sub):.1f}% WR, {len(sub)} trades")
    
    return "\n".join(lines)

def analyze_recent_live(df):
    """Analyze only live trades with specific trade-by-trade review."""
    if len(df) == 0:
        return "📊 **Live Trades**: No live trades yet."
    
    lines = []
    lines.append(f"📊 **Live Trade Review** ({len(df)} trades)")
    lines.append(f"━━━━━━━━━━━━━━━━━━━━")
    
    for _, t in df.sort_values('entry_time').iterrows():
        emoji = "✅" if t.outcome == 'win' else "❌"
        hold = ""
        if pd.notna(t.exit_time) and pd.notna(t.entry_time):
            dur = (t.exit_time - t.entry_time).total_seconds() / 60
            hold = f", {dur:.0f}min hold"
        
        lines.append(f"\n{emoji} **{t.instrument} {t.direction.upper()}** @ {t.entry_price}")
        lines.append(f"   {t.fractal} | {t.killzone} | ${t.pnl_dollar:+.0f}{hold}")
        
        # Trade-specific notes
        issues = []
        if t.outcome == 'loss':
            if t.sl_dist and t.rr_target and t.rr_target < 1.2:
                issues.append("Low R:R target (<1.2)")
            # Check if entry was near session extremes (rough heuristic)
            if t.direction == 'long' and t.sl_price and t.entry_price:
                risk = t.entry_price - t.sl_price
                move_against = t.entry_price - t.exit_price
                if risk > 0 and move_against / risk > 0.9:
                    issues.append("Stopped out — price went straight against")
        
        if issues:
            for issue in issues:
                lines.append(f"   ⚠️ {issue}")
    
    total = df.pnl_dollar.sum()
    lines.append(f"\n**Total Live P&L**: ${total:+,.0f}")
    return "\n".join(lines)

def key_insights(df):
    """Generate actionable insights."""
    lines = ["💡 **Key Insights & Recommendations**:", "━━━━━━━━━━━━━━━━━━━━"]
    
    # Compare killzones
    lon = df[df.killzone == 'London']
    ny = df[df.killzone == 'NY']
    if len(lon) > 0 and len(ny) > 0:
        lon_wr = win_rate(lon)
        ny_wr = win_rate(ny)
        if ny_wr > lon_wr + 5:
            lines.append(f"📍 NY session significantly stronger ({ny_wr:.1f}% vs {lon_wr:.1f}%). Consider heavier sizing in NY.")
        elif lon_wr > ny_wr + 5:
            lines.append(f"📍 London session stronger ({lon_wr:.1f}% vs {ny_wr:.1f}%). Consider heavier sizing in London.")
    
    # Best fractal
    best_frac = None
    best_wr = 0
    for frac in df.fractal.unique():
        sub = df[df.fractal == frac]
        if len(sub) >= 20 and win_rate(sub) > best_wr:
            best_wr = win_rate(sub)
            best_frac = frac
    if best_frac:
        lines.append(f"🔬 Best fractal: {best_frac} ({best_wr:.1f}% WR). Consider higher conviction sizing.")
    
    # Direction bias
    longs = df[df.direction == 'long']
    shorts = df[df.direction == 'short']
    if len(longs) > 0 and len(shorts) > 0:
        if win_rate(longs) > win_rate(shorts) + 5:
            lines.append(f"↕️ Longs outperform ({win_rate(longs):.1f}% vs {win_rate(shorts):.1f}%). Short setups need extra confirmation.")
        elif win_rate(shorts) > win_rate(longs) + 5:
            lines.append(f"↕️ Shorts outperform ({win_rate(shorts):.1f}% vs {win_rate(longs):.1f}%). Long setups need extra confirmation.")
    
    # TP type effectiveness
    if df.tp_type.notna().any():
        best_tp = None
        best_tp_pf = 0
        for tp in df.tp_type.dropna().unique():
            sub = df[df.tp_type == tp]
            if len(sub) >= 20:
                pf = profit_factor(sub)
                if pf > best_tp_pf:
                    best_tp_pf = pf
                    best_tp = tp
        if best_tp:
            lines.append(f"🎯 Most profitable TP: {best_tp} (PF {best_tp_pf:.2f})")
    
    # Avg R:R achieved on wins vs target
    wins = df[(df.outcome == 'win') & df.rr_target.notna() & df.pnl_dollar.notna() & df.risk_amount.notna() & (df.risk_amount > 0)]
    if len(wins) > 0:
        achieved_rr = (wins.pnl_dollar / wins.risk_amount).mean()
        target_rr = wins.rr_target.mean()
        lines.append(f"📐 Avg R:R achieved on wins: {achieved_rr:.2f}x (target was {target_rr:.2f}x)")
    
    return "\n".join(lines)

def full_report(mode="all", days=None):
    """Generate complete analyst report."""
    df = load_trades(days=days)
    
    parts = []
    
    if mode in ("all", "backtest"):
        bt = df[df.entry_time < '2026-02-12']
        if len(bt) > 0:
            parts.append(analyze_full(bt, "Backtest (10yr v22)"))
    
    if mode in ("all", "live"):
        live = df[df.entry_time >= '2026-02-12']
        parts.append(analyze_recent_live(live))
    
    parts.append(key_insights(df))
    
    return "\n\n".join(parts)

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    days = int(sys.argv[2]) if len(sys.argv) > 2 else None
    print(full_report(mode, days))
