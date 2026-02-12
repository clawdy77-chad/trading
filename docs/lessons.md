# Lessons Learned

## Strategy
1. **Look-ahead bias kills** — v1-v6 assumed instant fills. Real WR: ~37%, not 69%.
2. **Worst-case fills mandatory** — Bull: top of FVG. Bear: bottom.
3. **Session H/L targets lose** — 55%/46% loss rates. Removed in v24.
4. **Cap R:R at 2.5x** — Above that, WR drops to 41.5%.
5. **120-min time exit** — Losers hold 188min avg. Cut them.
6. **Skip London 09:00** — 38.8% loss rate.
7. **Don't stack filters** — v9 proved it kills volume.
8. **PO3 matters** — Buy below open, don't chase.
9. **Adaptive > fixed timeframes** — 4 fractals simultaneously.
10. **Liquidity targets > fixed R:R** — Swing H/L, unfilled FVGs.
11. **NY > London** — 73.1% vs 63.6% WR.
12. **F4 (D1) is best** — 88.5% WR but rare.
13. **Indices only** — Forex doesn't fire.

## Live
1. Don't enter at 76% of session range without PO3 dip.
2. Oanda CFDs: point_val = 1.0, account in CAD.
3. Bot must sync closed trades to journal DB.
4. Always check margin before placing orders.
