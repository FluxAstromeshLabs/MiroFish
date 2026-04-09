# gen_seed Local CSV Rewrite — Design Spec

**Date:** 2026-04-10

## Overview

Rewrite `backend/scripts/gen_seed.py` to read from local `marketdata/YYYY-MM-DD/` CSV files instead of the Flux exchange HTTP API. Add multi-seed generation (N seeds, each shifted by 1 hour) for backtesting scenario setup.

## Seed Format

Each seed is a Markdown file with these sections:

```markdown
# Latest Chart Time
2026-04-08 12:00

# Latest BTC Price
69051.90

# OHLCV 1H
[
  {"time": "2026-04-08 12:00", "open": 68997.90, "high": 69583.00, "low": 68997.90, "close": 69051.90, "volume": 11694.37},
  ...
]

# Liquidations
{"long": 3200000.00, "short": 1400000.00}

# News
(no news)

# Agents Population
- quant1: Analytical, data-driven, emotionally detached. Trusts numbers over intuition.
...
```

- **Latest Chart Time**: seed's end hour (format `YYYY-MM-DD HH:MM`, no UTC suffix)
- **Latest BTC Price**: close price of the last 1H candle (plain float)
- **OHLCV 1H**: 72 candles ending at the seed's end hour, newest-first, JSON array
- **Liquidations**: single JSON object, total long and short liquidation value over the full window
- **News**: always `(no news)` (no news CSV available)
- **Agents Population**: read from `agents.txt` at project root

## Data Sources

`marketdata/YYYY-MM-DD/` directories, one per calendar day (UTC):

- `ohlcv.csv` — columns: `T,O,H,L,C,V` where T is Unix ms epoch (1-minute candles)
- `liq.csv` — columns: `S,o,f,q,p,ap,X,l,z,T` where S is side (BUY/SELL), q is quantity, p is price, T is Unix ms epoch

## OHLCV Processing

1. Collect all `ohlcv.csv` files from days that overlap the window `[end_hour - 72h, end_hour]`
2. Filter rows to the window by timestamp
3. Aggregate 1-minute candles into 1H candles: open=first, high=max, low=min, close=last, volume=sum
4. Take the 72 candles ending at (and including) `end_hour`, sort newest-first

## Liquidation Processing

1. Collect all `liq.csv` files from days that overlap the full 72h window
2. Filter rows to the window by timestamp T
3. Sum long liquidations: rows where `S == SELL` (long position liquidated), value = `q * p`
4. Sum short liquidations: rows where `S == BUY` (short position liquidated), value = `q * p`

## Multi-Seed Generation

CLI args:
```
--end-hour   YYYY-MM-DDTHH   End hour of the last seed (e.g. 2026-04-08T12)
--count      N               Number of seeds to generate (default: 1)
--step       hours           Hour shift between seeds (default: 1)
--marketdata PATH            Path to marketdata directory (default: marketdata/ at project root)
--agents     PATH            Optional agents file (default: agents.txt at project root)
--output-dir PATH            Directory to write seed files (default: project root)
```

For `--count 3 --end-hour 2026-04-08T14 --step 1`, generates:
- `seed_2026-04-08T12.md` (window: Apr 5 12:00 → Apr 8 12:00)
- `seed_2026-04-08T13.md` (window: Apr 5 13:00 → Apr 8 13:00)
- `seed_2026-04-08T14.md` (window: Apr 5 14:00 → Apr 8 14:00)

When `--count 1` (default), output filename is `seed.md` for backwards compatibility.

## Changes to gen_seed.py

- **Remove**: `requests` import, `fetch_ohlcv`, `fetch_liquidations`, `fetch_news`, `--base-url` arg
- **Add**: `read_ohlcv_csv`, `read_liq_csv` CSV readers; `aggregate_1h` candle aggregator; `--marketdata`, `--end-hour`, `--count`, `--step`, `--output-dir` args
- **Keep unchanged**: `_fmt_dollar`, `load_agents`, `parse_hour`, `hour_bounds_ms`, all formatters (updated signatures)
- **Update**: `format_ohlcv` → only 1H, JSON output; `format_liquidations` → single JSON row; `format_news` → always `(no news)`
