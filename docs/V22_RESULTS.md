# V22 Adaptive TTFM/GxT — Results

## Strategy Overview
- Multi-fractal scanning (F1: M30→M15→M1, F2: H1→M30→M5, F3: H4→H1→M15, F4: D1→H4→H1)
- Liquidity-based targets (swing H/L, session H/L, unfilled FVGs)
- Adaptive SL at sweep extreme + 0.3×ATR buffer
- Risk: $200/trade, max 3/day
- Killzones: London 08:00-12:00, NY 13:30-21:15 UTC
- Eval: 10-day windows, $3K target, -$2K DD limit


## TRAIN (2020-2023)

| Metric | Value |
|--------|-------|
| Trades | 5767 |
| Trades/Week | 14.12 |
| Win Rate | 66.2% |
| Profit Factor | 2.77 |
| Avg R:R Target | 1.95 |
| Avg R:R Achieved | 0.69 |
| Total P&L | $648,533.79 |
| Avg Win | $265.49 |
| Avg Loss | $187.80 |
| Max DD | $-2,652.12 |
| Eval Pass Rate (10d) | 30.3% |

### By Instrument

| Instrument | Trades | WR% | PF | Avg R:R | P&L |
|---|---|---|---|---|---|
| NQ | 2362 | 65.3% | 2.71 | 2.14 | $263,814.48 |
| ES | 1572 | 63.7% | 2.42 | 1.79 | $152,551.55 |
| YM | 1833 | 69.6% | 3.25 | 1.85 | $232,167.76 |

### By Fractal

| Fractal | Trades | WR% | PF | Avg R:R | P&L |
|---|---|---|---|---|---|
| F1_M30 | 2726 | 64.6% | 2.66 | 2.13 | $309,759.20 |
| F2_H1 | 1828 | 61.5% | 2.22 | 1.89 | $161,577.48 |
| F3_H4 | 931 | 73.3% | 3.97 | 1.6 | $126,139.61 |
| F4_D1 | 282 | 89.0% | 13.79 | 1.81 | $51,057.50 |

### By Killzone

| Killzone | Trades | WR% | PF | Avg R:R | P&L |
|---|---|---|---|---|---|
| London | 3912 | 63.1% | 2.39 | 2.07 | $389,631.61 |
| NY | 1855 | 72.9% | 4.05 | 1.71 | $258,902.18 |

### By Target Type

| Target | Trades | WR% | Avg R:R |
|--------|--------|-----|---------|
| swing_high | 1143 | 73.0% | 1.5 |
| unfilled_fvg | 2129 | 70.4% | 1.78 |
| session_low | 649 | 46.2% | 2.92 |
| session_high | 589 | 54.0% | 2.16 |
| swing_low | 1257 | 69.1% | 2.06 |

## OOS (2024-2025)

| Metric | Value |
|--------|-------|
| Trades | 1569 |
| Trades/Week | 14.47 |
| Win Rate | 67.4% |
| Profit Factor | 4.2 |
| Avg R:R Target | 2.21 |
| Avg R:R Achieved | 1.11 |
| Total P&L | $308,839.83 |
| Avg Win | $383.14 |
| Avg Loss | $188.88 |
| Max DD | $-1,675.33 |
| Eval Pass Rate (10d) | 40.9% |

### By Instrument

| Instrument | Trades | WR% | PF | Avg R:R | P&L |
|---|---|---|---|---|---|
| NQ | 591 | 66.3% | 5.51 | 2.68 | $171,753.28 |
| ES | 396 | 66.4% | 3.01 | 1.92 | $48,804.67 |
| YM | 582 | 69.2% | 3.58 | 1.92 | $88,281.88 |

### By Fractal

| Fractal | Trades | WR% | PF | Avg R:R | P&L |
|---|---|---|---|---|---|
| F1_M30 | 714 | 66.0% | 4.95 | 2.68 | $189,930.60 |
| F2_H1 | 495 | 64.6% | 3.05 | 1.95 | $65,537.09 |
| F3_H4 | 293 | 71.3% | 3.63 | 1.64 | $40,933.24 |
| F4_D1 | 67 | 86.6% | 14.8 | 1.5 | $12,438.90 |

### By Killzone

| Killzone | Trades | WR% | PF | Avg R:R | P&L |
|---|---|---|---|---|---|
| London | 1172 | 65.1% | 4.03 | 2.35 | $242,675.27 |
| NY | 397 | 74.3% | 5.01 | 1.78 | $66,164.56 |

### By Target Type

| Target | Trades | WR% | Avg R:R |
|--------|--------|-----|---------|
| unfilled_fvg | 595 | 71.9% | 1.6 |
| swing_low | 352 | 73.3% | 1.72 |
| swing_high | 305 | 71.5% | 3.26 |
| session_high | 168 | 56.0% | 2.33 |
| session_low | 149 | 40.3% | 3.5 |