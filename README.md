# Trading System

Automated prop firm trading system for US index futures (NQ, ES, YM).

## Structure
- **`strategy/`** — V24 Optimized backtest strategy (79.3% WR, PF 5.69)
- **`bot/`** — Live Oanda trading bot
- **`journal/`** — Trading journal dashboard (FastAPI + Chart.js)
- **`docs/`** — Research, lessons, trade log, backtest results

## Quick Start

### Run Backtest
```bash
cd strategy
python v24_optimized.py  # requires data_10y/ with M1 parquet files
```

### Start Journal
```bash
cd journal
pip install -r requirements.txt
python app.py  # runs on port 8080
```

### Start Live Bot
```bash
cd bot
cp ../.env.example ../.env  # fill in your keys
pip install -r requirements.txt
python live_bot_v22.py
```

## V24 Performance (OOS 2024-2026)
| Metric | Value |
|--------|-------|
| Win Rate | 79.3% |
| Profit Factor | 5.69 |
| Trades/Week | 14.2 |
| Max Drawdown | -$758 |
| Sharpe | 2.18 |
| Monte Carlo 10-day pass | 93.0% |
