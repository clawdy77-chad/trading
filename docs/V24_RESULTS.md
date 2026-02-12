# V24 Optimized TTFM/GxT — Results

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
| Trades | 5568 |
| Trades/Week | 13.63 |
| Win Rate | 76.1% |
| Profit Factor | 4.51 |
| Avg R:R Target | 1.46 |
| Avg R:R Achieved | 0.85 |
| Total P&L | $687,577.84 |
| Avg Win | $208.60 |
| Avg Loss | $146.91 |
| Max DD | $-1,061.85 |
| Eval Pass Rate (10d) | 27.9% |

### By Instrument

| Instrument | Trades | WR% | PF | Avg R:R | P&L |
|---|---|---|---|---|---|
| NQ | 2173 | 76.7% | 4.69 | 1.48 | $271,744.29 |
| ES | 1526 | 74.4% | 3.84 | 1.43 | $170,416.03 |
| YM | 1869 | 76.6% | 4.95 | 1.46 | $245,417.52 |

### By Fractal

| Fractal | Trades | WR% | PF | Avg R:R | P&L |
|---|---|---|---|---|---|
| F1_M30 | 2441 | 73.7% | 3.98 | 1.48 | $341,436.62 |
| F2_H1 | 1683 | 71.4% | 3.66 | 1.44 | $179,533.04 |
| F3_H4 | 1069 | 85.1% | 12.02 | 1.45 | $130,738.84 |
| F4_D1 | 375 | 86.7% | 20.01 | 1.45 | $35,869.34 |

### By Killzone

| Killzone | Trades | WR% | PF | Avg R:R | P&L |
|---|---|---|---|---|---|
| London | 2988 | 74.8% | 4.01 | 1.46 | $328,276.65 |
| NY | 2580 | 77.5% | 5.14 | 1.46 | $359,301.19 |

### By Target Type

| Target | Trades | WR% | Avg R:R |
|--------|--------|-----|---------|
| swing_high | 1409 | 80.2% | 1.43 |
| unfilled_fvg | 2543 | 74.2% | 1.46 |
| swing_low | 1616 | 75.3% | 1.48 |

## OOS (2024-2025)

| Metric | Value |
|--------|-------|
| Trades | 1539 |
| Trades/Week | 14.19 |
| Win Rate | 79.3% |
| Profit Factor | 5.69 |
| Avg R:R Target | 1.52 |
| Avg R:R Achieved | 0.98 |
| Total P&L | $221,405.80 |
| Avg Win | $220.01 |
| Avg Loss | $148.50 |
| Max DD | $-757.86 |
| Eval Pass Rate (10d) | 44.9% |

### By Instrument

| Instrument | Trades | WR% | PF | Avg R:R | P&L |
|---|---|---|---|---|---|
| NQ | 554 | 76.9% | 5.13 | 1.55 | $76,646.02 |
| ES | 403 | 80.6% | 5.34 | 1.48 | $54,194.63 |
| YM | 582 | 80.8% | 6.59 | 1.52 | $90,565.15 |

### By Fractal

| Fractal | Trades | WR% | PF | Avg R:R | P&L |
|---|---|---|---|---|---|
| F1_M30 | 638 | 76.5% | 4.84 | 1.52 | $105,828.10 |
| F2_H1 | 455 | 75.6% | 5.1 | 1.5 | $60,087.46 |
| F3_H4 | 347 | 86.7% | 11.19 | 1.54 | $46,169.02 |
| F4_D1 | 99 | 88.9% | 19.14 | 1.49 | $9,321.22 |

### By Killzone

| Killzone | Trades | WR% | PF | Avg R:R | P&L |
|---|---|---|---|---|---|
| London | 926 | 78.0% | 4.91 | 1.53 | $118,184.93 |
| NY | 613 | 81.4% | 7.06 | 1.51 | $103,220.87 |

### By Target Type

| Target | Trades | WR% | Avg R:R |
|--------|--------|-----|---------|
| unfilled_fvg | 716 | 77.8% | 1.49 |
| swing_low | 417 | 80.6% | 1.57 |
| swing_high | 406 | 80.8% | 1.52 |