# Price Forecast Interview — Design Spec

**Date:** 2026-04-08
**Branch:** feat/trades
**File:** `backend/scripts/run_trade.py`

---

## Summary

Replace the trade-decision interview (step 5) with a price-range forecast interview. Each agent predicts the price range for the next N hours. Output is a CSV with `name,start_timestamp,end_timestamp,range_low,range_high`.

---

## CLI Change

Add `--forecast-hours` (int, default `4`) to `run_trade.py`'s argument parser. Pass it through to `step5_interview_for_trades`.

```
python run_trade.py seed.md --forecast-hours 4
```

---

## Seed Timestamp Extraction

Add `extract_latest_timestamp(seed_text: str) -> int`.

- Parse the OHLCV table in the seed (rows like `| timestamp | open | ... |`)
- Extract the last numeric timestamp value
- Return it as Unix seconds (int)
- Fallback: `int(time.time())` if no timestamp found

---

## World Seed Context

Strip the `# Agents` section from `seed_text` before passing to the interview prompt, so agents get market context only (no other agents' profiles).

Helper: `strip_agents_section(seed_text: str) -> str` — split on `# Agents`, keep the first part.

---

## Interview Prompt

```
Here is the current market context:
{world_seed}

Based on this data and your discussions, predict the price range for the next {forecast_hours} hours.

**CRITICAL: You MUST respond with EXACTLY two numbers separated by a comma. Nothing else. No words, no explanation, no punctuation other than the comma and decimal point.**
Format: range_low,range_high
Example: 83000.5,85200.0

Any response that does not match this exact format will be discarded.
```

---

## Response Parsing

Replace `_parse_decision` / `_validate_decision` with `_parse_range(response_text: str) -> tuple[float, float] | None`.

Logic:
1. Strip whitespace
2. Split on `,` — expect exactly 2 parts
3. `float()` each part
4. Validate: `range_low > 0`, `range_high > 0`, `range_low < range_high`
5. Return `(range_low, range_high)` or `None` on any failure

No LLM re-parsing. Format is strict enough to parse directly.

---

## Fallback (Persona-Based)

Replace `_decide_from_persona` with `_forecast_from_persona(llm, agent_name, persona, world_seed, forecast_hours)`.

Same structure as before but prompts the agent (via LLM) for a price range. Uses `world_seed` (agents section stripped). Parses response with `_parse_range`.

---

## CSV Output

Fields: `name,start_timestamp,end_timestamp,range_low,range_high`

| Field | Value |
|---|---|
| `name` | Agent name |
| `start_timestamp` | Unix seconds of latest OHLCV candle from seed |
| `end_timestamp` | `start_timestamp + forecast_hours * 3600` |
| `range_low` | Lower bound of predicted price range |
| `range_high` | Upper bound of predicted price range |

Replaces the existing trade-decision CSV entirely.

---

## Functions to Remove

- `_parse_decision`
- `_validate_decision`
- `_fmt_decision`
- `_decide_from_persona`
- `write_csv` (rename/update fields)
- `count_agents_in_seed` (keep — still used for `agent_count`)

## Functions to Add / Rename

| Old | New |
|---|---|
| `_parse_decision` | `_parse_range` |
| `_validate_decision` | (removed, merged into `_parse_range`) |
| `_fmt_decision` | `_fmt_forecast` |
| `_decide_from_persona` | `_forecast_from_persona` |
| `_interview_agents` | updated in-place |
| `step5_interview_for_trades` | updated in-place (add `forecast_hours` param) |
| — | `extract_latest_timestamp` |
| — | `strip_agents_section` |

---

## No Changes

- `trade.sh` — no changes needed
- Steps 1–4 of the pipeline — unchanged
- `check_server`, `poll`, `api`, `_get_agent_profiles` — unchanged
