# gen_seed API Rewrite — Design Spec

## Context

`gen_seed.py` currently reads local CSV files (bbo, trade, liq, oi) to produce a `seed.md` used as market context for the BTC futures simulation. The goal is to replace the CSV pipeline with live HTTP calls to the Flux exchange API, produce a structured tabular seed format, and expand the agents list to 20 participants (15 traders + 5 KOLs) with style-only descriptions.

---

## CLI

```
python3 backend/scripts/gen_seed.py \
  --day 2026-04-06 \
  --days 3 \
  --base-url http://localhost:8080 \
  --agents agents.txt \
  -o seed.md
```

| Arg | Default | Description |
|-----|---------|-------------|
| `--day` | today (UTC) | Ending day `YYYY-MM-DD` |
| `--days` | `3` | Number of days of history to include |
| `--base-url` | `http://localhost:8080` | Flux exchange API base URL |
| `--agents` | `agents.txt` at project root | Optional agents file override |
| `-o` | `seed.md` at project root | Output path |

---

## API Calls

### OHLCV
```
GET /api/v1/history/ohlcv?bucket=<bucket>&day=<YYYY-MM-DD>&start=<ms>&end=<ms>
```
Called once per (day × bucket). For `--days 3`, that is 9 calls total (3 days × 1d/4h/1h).  
Items are concatenated in chronological order across days.

**Response shape:**
```json
{
  "items": [
    { "open_time_ms": 1743897600000, "open": "83000", "high": "84500", "low": "82100", "close": "83800", "volume": "12000" }
  ]
}
```

### Liquidations
```
GET /api/v1/history/liquidations?start=<ms>&end=<ms>
```
4 calls, each with `end_ms = end of --day`, and `start_ms = end_ms - window`:

| Window | start_ms offset |
|--------|----------------|
| 1h  | -3,600,000 ms |
| 4h  | -14,400,000 ms |
| 12h | -43,200,000 ms |
| 24h | -86,400,000 ms |

**Response shape:**
```json
{
  "total_long": "2427609.985",
  "total_short": "2085172.725",
  "items": [
    { "side": "buy", "avg_price": "84.77", "cum_filled_qty": "0.20", "trade_time_ms": 1743900000000 }
  ]
}
```
(`side: "buy"` = long liquidation, `side: "sell"` = short liquidation)

### News
```
GET /api/v1/history/news?start=<ms>&end=<ms>
```
1 call covering the full N-day window.

**Response shape:**
```json
{
  "items": [
    { "timestamp_ms": 1743921000000, "content": "Fed signals pause in rate hikes" }
  ]
}
```

---

## Seed Output Format

```markdown
# OHLCV

## 1D
Date       | Open      | High      | Low       | Close     | Volume
2026-04-06 | 83,100.00 | 84,200.00 | 82,800.00 | 83,900.00 | 11,200.00
2026-04-05 | 82,900.00 | 83,600.00 | 82,400.00 | 83,100.00 | 10,800.00
2026-04-04 | 83,000.00 | 84,500.00 | 82,100.00 | 83,800.00 | 12,000.00

## 4H
Date/Time         | Open      | High      | Low       | Close     | Volume
2026-04-06 20:00  | 83,500.00 | 83,900.00 | 83,200.00 | 83,700.00 |  1,900.00
...  (18 rows for --days 3, newest first)

## 1H
Date/Time         | Open      | High      | Low       | Close     | Volume
2026-04-06 23:00  | 83,700.00 | 83,900.00 | 83,500.00 | 83,800.00 |    420.00
...  (72 rows for --days 3, newest first)

# Liquidations
Last | Long liq | Short liq
1h   | $2.4M    | $2.1M
4h   | $9.6M    | $8.3M
12h  | $28.0M   | $21.0M
24h  | $55.0M   | $43.0M

# News
Time             | News
2026-04-06 14:00 | MicroStrategy buys 500 BTC
2026-04-06 08:30 | Fed signals pause in rate hikes

# Agents Population
- quant1: ...
```

---

## Agents

### Traders (15)

| Name | Style |
|------|-------|
| quant1 | Analytical, data-driven, emotionally detached. Trusts numbers over intuition. |
| quant2 | Methodical and process-oriented. Uncomfortable with ambiguity, relies on repeatable systems. |
| swing1 | Patient, reads macro structure. Waits for conviction before committing. |
| swing2 | Trend-follower with a high tolerance for drawdown. Holds through noise. |
| scalper1 | Hyper-focused, reactive, lives in the short-term. Dislikes overnight exposure. |
| scalper2 | Competitive and fast-twitch. Treats every tick as an opportunity. |
| whale1 | Methodical and private. Moves quietly, thinks in large time horizons. |
| whale2 | Deliberate and patient. Rarely overreacts, hard to rattle. |
| news1 | Macro-aware and well-read. Connects headline dots faster than most. |
| news2 | Alert and always plugged in. First to react to crypto-native developments. |
| degen1 | Impulsive and overconfident. Thrives on volatility, hates sitting on the sidelines. |
| degen2 | Risk-blind and excitement-driven. Chases action more than outcomes. |
| hodler1 | Patient and conviction-driven. Tunes out short-term noise. |
| contrarian1 | Skeptical of consensus. Comfortable being the only one taking the opposite view. |
| retail1 | Easily influenced, reactive to price moves and social feeds. |

### KOLs (5)

| Name | Followers | Style |
|------|-----------|-------|
| kol1 | 2.1M | Hype-driven, high-energy, large retail audience. Posts frequently and amplifies momentum. |
| kol2 | 420K | Measured and data-heavy. Institutional-leaning audience, focuses on evidence over emotion. |
| kol3 | 95K | Niche on-chain specialist. Small but highly technical and loyal following. |
| kol4 | 1.8M | Macro-first thinker. Bridges TradFi and crypto, commands credibility across both. |
| kol5 | 31K | Contrarian voice. Often goes against popular takes, niche but devoted community. |

---

## File Changes

| File | Action |
|------|--------|
| `backend/scripts/gen_seed.py` | **Rewrite** — replace CSV pipeline with API fetchers + tabular formatters |
| `agents.txt` | **Rewrite** — 15 traders + 5 KOLs with style descriptions |

`backend/scripts/common.py` — no changes needed (path/env bootstrap is reused as-is).

---

## Verification

```bash
# 1. Confirm API is reachable
curl -s "http://localhost:8080/api/v1/history/ohlcv?bucket=1d&day=2026-04-06&start=1743897600000&end=1743983999000"

# 2. Generate seed for 3 days ending 2026-04-06
cd /mnt/second_disk/Code/flux/flux-MiroFish
python3 backend/scripts/gen_seed.py --day 2026-04-06 --days 3

# 3. Inspect output
head -100 seed.md
```

Expected checks:
- `# OHLCV` with `## 1D` (3 rows), `## 4H` (18 rows), `## 1H` (72 rows)
- `# Liquidations` table with 4 rows (1h/4h/12h/24h)
- `# News` table with timestamped entries
- `# Agents Population` with 20 entries (15 traders + 5 KOLs)
