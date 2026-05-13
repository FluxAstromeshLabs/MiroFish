# MiroFish Research

Backtesting pipeline for evaluating MiroFish price range predictions against historical BTC data.

## Overview

```
OHLCV + Tweets → Seeds → Simulation → Predictions CSV → Metrics + Chart
```

Each **seed** is a snapshot of market data (candles + tweets + agent profiles) at a point in time. The pipeline runs a MiroFish simulation for each seed and records the predicted price range, then scores it against the actual next candle.

---

## Setup

### 1. Backend server

The pipeline calls the MiroFish backend at `http://localhost:5001`. Start it first:

```bash
cd backend && source .venv/bin/activate && python run.py
```

### 2. Environment

Copy the example env:

```bash
cp research/scripts/.env.example research/scripts/.env
```

---

## Data Preparation

### Fetch OHLCV candles

Aggregates 1-minute Binance data from local exchange-connectors into hourly candles:

```bash
python3 research/scripts/aggregate_ohlcv.py \
  --start-date "2026-03-28 00:00:00" \
  --end-date   "2026-04-13 23:59:59" \
  --interval 1h \
  -o research/data/ohlcv_1h.csv
```

Output columns: `T` (ms epoch), `O`, `H`, `L`, `C`, `V`

### Fetch tweets

```bash
python3 research/scripts/fetch_tweets.py \
  --start-date "2026-03-28 00:00:00" \
  --end-date   "2026-04-13 23:59:59" \
  -o research/data/tweets.csv
```

Fetches top tweets from the accounts/query configured in `.env` via twitterapi.io. Merges and deduplicates into the output CSV on each run.

### Generate seeds manually

```bash
python3 research/scripts/gen_seed.py \
  --start-date "2026-04-01 00:00:00" \
  --end-date   "2026-04-07 23:00:00" \
  --interval 1h \
  --limit 24
```

---

## Running the Backtest

```bash
python3 research/scripts/backtest_pipeline.py
```

This auto-generates seeds from `.env` config, runs simulations, scores results, and saves a report.

### Key options

| Flag | Default | Description |
|------|---------|-------------|
| `--interval` | `1h` | Candle interval(s), comma-separated (e.g. `1h` or `1h,4h`) |
| `--start-date` | `SEED_START_DATE` env | Filter seeds from this date |
| `--end-date` | `SEED_END_DATE` env | Filter seeds until this date |
| `--rounds` | `ROUNDS` env or `5` | Simulation rounds per seed |
| `--seeds-dir` | `research/data/seeds` | Pre-generated seeds directory |
| `--output` | `research/predictions/YYYY-MM-DD/TIMESTAMP.csv` | Output CSV path |

### Example with explicit dates

```bash
python3 research/scripts/backtest_pipeline.py \
  --start-date "2026-04-01 00:00:00" \
  --end-date   "2026-04-07 23:00:00" \
  --interval 1h \
  --rounds 3
```

---

## Outputs

Each run produces three files under `research/predictions/YYYY-MM-DD/`:

| File | Description |
|------|-------------|
| `TIMESTAMP.csv` | Per-candle predictions + metrics (AE, DA, e_low, e_high) |
| `TIMESTAMP.png` | Predicted vs actual candlestick chart |
| `TIMESTAMP.txt` | Human-readable report with overall and per-candle metrics |

### CSV format

```
latest_chart_time, predicted_low, predicted_high, actual_low, actual_high,
prev_mid, agent_count, simulation_rounds, runtime, ae, da, e_low, e_high

MAE,<value>
MDA,<value>
b_low,<value>
b_high,<value>
total_runtime_mins,<value>
```

### Metrics

| Metric | Description |
|--------|-------------|
| `AE` | Absolute Error: `|pred_low − act_low| + |pred_high − act_high|` |
| `MAE` | Mean AE across all evaluated candles |
| `DA` | Direction Accuracy: 1 if predicted direction matches actual, else 0 |
| `MDA` | Mean DA (requires `prev_mid`) |
| `b_low` | Mean signed relative error on the low price (%) |
| `b_high` | Mean signed relative error on the high price (%) |

---

### Regenerate report for an existing CSV

```bash
python3 research/scripts/report.py research/predictions/2026-04-25/2026-04-25-14-12-25.csv
```
