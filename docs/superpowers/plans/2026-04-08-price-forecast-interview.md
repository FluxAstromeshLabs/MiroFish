# Price Forecast Interview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the trade-decision interview in `run_trade.py` with a price-range forecast interview that outputs `name,start_timestamp,end_timestamp,range_low,range_high` to CSV.

**Architecture:** All changes are confined to `backend/scripts/run_trade.py` and a new test file `backend/scripts/test_run_trade.py`. Helper functions (`extract_latest_timestamp`, `strip_agents_section`, `_parse_range`) are pure and unit-testable. The interview/fallback logic and CSV writer are updated in-place.

**Tech Stack:** Python 3.10+, pytest, existing `LLMClient`, existing Flask API via `requests`

---

## File Map

- **Modify:** `backend/scripts/run_trade.py`
- **Create:** `backend/scripts/test_run_trade.py`

---

### Task 1: Add `strip_agents_section` helper + tests

**Files:**
- Create: `backend/scripts/test_run_trade.py`
- Modify: `backend/scripts/run_trade.py`

- [ ] **Step 1: Write the failing test**

Create `backend/scripts/test_run_trade.py`:

```python
"""Tests for run_trade helpers."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from run_trade import strip_agents_section


def test_strip_agents_section_removes_section():
    seed = "# Market Data\nprice: 80000\n\n# Agents Population\nagent1\nagent2\n"
    result = strip_agents_section(seed)
    assert "# Agents Population" not in result
    assert "agent1" not in result
    assert "# Market Data" in result
    assert "price: 80000" in result


def test_strip_agents_section_no_section():
    seed = "# Market Data\nprice: 80000\n"
    result = strip_agents_section(seed)
    assert result == seed


def test_strip_agents_section_empty():
    assert strip_agents_section("") == ""
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /mnt/second_disk/Code/flux/flux-MiroFish
backend/.venv/bin/pytest backend/scripts/test_run_trade.py::test_strip_agents_section_removes_section -v
```

Expected: `ImportError` or `AttributeError` — `strip_agents_section` not yet defined.

- [ ] **Step 3: Add `strip_agents_section` to `run_trade.py`**

In `backend/scripts/run_trade.py`, add after the `count_agents_in_seed` function (around line 50):

```python
def strip_agents_section(seed_text):
    """Remove the '# Agents Population' section and everything after it."""
    if "# Agents Population" in seed_text:
        return seed_text.split("# Agents Population", 1)[0]
    return seed_text
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
backend/.venv/bin/pytest backend/scripts/test_run_trade.py -v -k "strip_agents"
```

Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/run_trade.py backend/scripts/test_run_trade.py
git commit -m "feat: add strip_agents_section helper"
```

---

### Task 2: Add `extract_latest_timestamp` helper + tests

**Files:**
- Modify: `backend/scripts/test_run_trade.py`
- Modify: `backend/scripts/run_trade.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/scripts/test_run_trade.py`:

```python
from run_trade import extract_latest_timestamp


def test_extract_latest_timestamp_from_ohlcv_table():
    # Rows are newest-first; first data row after header is the latest candle
    seed = (
        "# OHLCV\n\n"
        "## 1H\n"
        "Date/Time        |       Open |       High |        Low |      Close |       Volume\n"
        "2026-04-06 23:00 |  68,777.00 |  68,871.90 |  68,227.50 |  68,817.90 |    10,845.19\n"
        "2026-04-06 22:00 |  68,777.00 |  68,871.90 |  68,227.50 |  68,817.90 |     5,422.78\n"
    )
    # 2026-04-06 23:00 UTC = 1775516400
    assert extract_latest_timestamp(seed) == 1775516400


def test_extract_latest_timestamp_no_table():
    import time
    seed = "# Market Data\nno timestamps here\n"
    result = extract_latest_timestamp(seed)
    assert abs(result - int(time.time())) < 5


def test_extract_latest_timestamp_single_row():
    seed = (
        "## 1H\n"
        "Date/Time        |       Open |\n"
        "2026-04-06 00:00 |  69,437.30 |\n"
    )
    # 2026-04-06 00:00 UTC = 1775433600
    assert extract_latest_timestamp(seed) == 1775433600
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
backend/.venv/bin/pytest backend/scripts/test_run_trade.py -v -k "extract_latest"
```

Expected: `ImportError` or `AttributeError`.

- [ ] **Step 3: Add `extract_latest_timestamp` to `run_trade.py`**

Add after `strip_agents_section`. Also add `import re` and `from datetime import datetime, timezone` at the top of the file alongside the existing imports.

```python
def extract_latest_timestamp(seed_text):
    """Return Unix seconds of the latest OHLCV candle in seed_text, or now() as fallback.

    The seed's 1H table lists rows newest-first in the format:
        2026-04-06 23:00 |  68,777.00 | ...
    We find the first such row after the '## 1H' header.
    """
    import re
    from datetime import datetime, timezone

    # Find the ## 1H section first
    match = re.search(
        r'## 1H\n'                          # section header
        r'Date/Time[^\n]*\n'                # column header row
        r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2})',  # first data row timestamp
        seed_text
    )
    if match:
        dt = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    return int(time.time())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
backend/.venv/bin/pytest backend/scripts/test_run_trade.py -v -k "extract_latest"
```

Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/run_trade.py backend/scripts/test_run_trade.py
git commit -m "feat: add extract_latest_timestamp helper"
```

---

### Task 3: Add `_parse_range` + `_fmt_forecast` + tests

**Files:**
- Modify: `backend/scripts/test_run_trade.py`
- Modify: `backend/scripts/run_trade.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/scripts/test_run_trade.py`:

```python
from run_trade import _parse_range, _fmt_forecast


def test_parse_range_valid():
    assert _parse_range("83000.5,85200.0") == (83000.5, 85200.0)


def test_parse_range_with_whitespace():
    assert _parse_range("  83000.5 , 85200.0  ") == (83000.5, 85200.0)


def test_parse_range_low_equals_high_invalid():
    assert _parse_range("83000.0,83000.0") is None


def test_parse_range_low_greater_than_high_invalid():
    assert _parse_range("85000.0,83000.0") is None


def test_parse_range_non_numeric_invalid():
    assert _parse_range("LONG,SHORT") is None


def test_parse_range_single_value_invalid():
    assert _parse_range("83000.5") is None


def test_parse_range_zero_invalid():
    assert _parse_range("0,85000.0") is None


def test_fmt_forecast():
    result = _fmt_forecast("Alice", 83000.5, 85200.0)
    assert "Alice" in result
    assert "83000.5" in result
    assert "85200.0" in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
backend/.venv/bin/pytest backend/scripts/test_run_trade.py -v -k "parse_range or fmt_forecast"
```

Expected: `ImportError`.

- [ ] **Step 3: Add `_parse_range` and `_fmt_forecast` to `run_trade.py`**

Replace the existing `_parse_decision`, `_validate_decision`, and `_fmt_decision` functions with:

```python
def _parse_range(response_text):
    """Parse 'range_low,range_high' from agent response. Returns (float, float) or None."""
    try:
        parts = response_text.strip().split(",")
        if len(parts) != 2:
            return None
        low = float(parts[0].strip())
        high = float(parts[1].strip())
        if low <= 0 or high <= 0 or low >= high:
            return None
        return (low, high)
    except (ValueError, AttributeError):
        return None


def _fmt_forecast(agent_name, range_low, range_high):
    """Format a price forecast as a display string."""
    return f"{agent_name}: {range_low} — {range_high}"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
backend/.venv/bin/pytest backend/scripts/test_run_trade.py -v -k "parse_range or fmt_forecast"
```

Expected: 8 PASSED

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/run_trade.py backend/scripts/test_run_trade.py
git commit -m "feat: add _parse_range and _fmt_forecast, remove trade decision parsers"
```

---

### Task 4: Update `_forecast_from_persona` (fallback)

**Files:**
- Modify: `backend/scripts/run_trade.py`

- [ ] **Step 1: Replace `_decide_from_persona` with `_forecast_from_persona`**

Remove `_decide_from_persona` entirely and replace with:

```python
def _forecast_from_persona(llm, agent_name, persona, world_seed, predict_hours):
    """Generate price range forecast directly from agent persona + market data (single LLM call)."""
    response = llm.chat(
        messages=[
            {
                "role": "system",
                "content": (
                    f"You are {agent_name}, a trader with the following profile:\n{persona}\n\n"
                    "Based on your personality and trading style, predict the price range.\n\n"
                    "**CRITICAL: You MUST respond with EXACTLY two numbers separated by a comma. "
                    "Nothing else. No words, no explanation, no punctuation other than the comma "
                    "and decimal point.**\n"
                    "Format: range_low,range_high"
                )
            },
            {
                "role": "user",
                "content": (
                    f"Market data:\n{world_seed}\n\n"
                    f"What is the price range for the next {predict_hours} hours? "
                    "Respond with ONLY two numbers separated by a comma."
                )
            }
        ],
        temperature=0.8
    )
    return _parse_range(response)
```

> **Note on `llm.chat` vs `llm.chat_json`:** The old `_decide_from_persona` used `llm.chat_json`. Since we now parse the response as a plain string (not JSON), use `llm.chat` instead. Check `app/utils/llm_client.py` — if `chat` doesn't exist, use `chat_json` and call `str()` on the result, or use whatever method returns a plain string response.

- [ ] **Step 2: Update `_fallback_persona_decisions` to use new function**

Replace the existing `_fallback_persona_decisions` function with:

```python
def _fallback_persona_decisions(llm, seed_text, id_to_profile, predict_hours):
    """Generate price range forecasts from agent personas when interview is unavailable (parallel)."""
    world_seed = strip_agents_section(seed_text)
    agent_count = len(id_to_profile)

    print(f"  Falling back to persona-based forecasts for {agent_count} agents")

    tasks = []
    for idx, (agent_id, profile) in enumerate(id_to_profile.items(), 1):
        agent_name = profile.get("name", profile.get("user_name", f"agent_{agent_id}"))
        persona = profile.get("persona", profile.get("bio", ""))
        tasks.append((idx, agent_name, persona))

    forecasts = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(_forecast_from_persona, llm, name, persona, world_seed, predict_hours): (idx, name)
            for idx, name, persona in tasks
        }
        for future in as_completed(futures):
            idx, name = futures[future]
            try:
                result = future.result()
                if result:
                    low, high = result
                    forecasts.append({"name": name, "range_low": low, "range_high": high})
                    print(f"  [{idx}/{agent_count}] {_fmt_forecast(name, low, high)}")
                else:
                    print(f"  [{idx}/{agent_count}] {name}: could not parse forecast")
            except Exception as e:
                print(f"  [{idx}/{agent_count}] {name}: error: {e}")

    return forecasts
```

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/run_trade.py
git commit -m "feat: replace _decide_from_persona with _forecast_from_persona"
```

---

### Task 5: Update `_interview_agents` for forecast

**Files:**
- Modify: `backend/scripts/run_trade.py`

- [ ] **Step 1: Replace `_interview_agents` with forecast version**

Replace the existing `_interview_agents` function with:

```python
def _interview_agents(base_url, simulation_id, seed_text, predict_hours, id_to_profile, platform, session=None):
    """Interview agents via OASIS for price range forecasts (parallel)."""
    world_seed = strip_agents_section(seed_text)
    agent_count = len(id_to_profile)

    interview_prompt = (
        "Here is the current market context:\n"
        f"{world_seed}\n\n"
        f"Based on this data and your discussions, predict the price range for the next {predict_hours} hours.\n\n"
        "**CRITICAL: You MUST respond with EXACTLY two numbers separated by a comma. "
        "Nothing else. No words, no explanation, no punctuation other than the comma and decimal point.**\n"
        "Format: range_low,range_high"
    )

    interview_timeout = max(60, agent_count * 15)
    interview_result = api("post", base_url, "/api/simulation/interview/all",
                           session=session, json={
                               "simulation_id": simulation_id,
                               "prompt": interview_prompt,
                               "platform": platform,
                               "timeout": interview_timeout
                           })

    raw_results = interview_result.get("result", {}).get("results", {})

    parse_tasks = []
    for idx, (key, interview) in enumerate(raw_results.items(), 1):
        agent_id = interview.get("agent_id")
        response_text = interview.get("response", "")
        profile = id_to_profile.get(agent_id, {})
        agent_name = profile.get("name", profile.get("user_name", f"agent_{agent_id}"))

        if not response_text:
            print(f"  [{idx}/{agent_count}] {agent_name}: (no response)")
            continue

        parse_tasks.append((idx, agent_name, response_text))

    forecasts = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(_parse_range, resp): (idx, name)
            for idx, name, resp in parse_tasks
        }
        for future in as_completed(futures):
            idx, name = futures[future]
            try:
                result = future.result()
                if result:
                    low, high = result
                    forecasts.append({"name": name, "range_low": low, "range_high": high})
                    print(f"  [{idx}/{agent_count}] {_fmt_forecast(name, low, high)}")
                else:
                    print(f"  [{idx}/{agent_count}] {name}: could not parse forecast")
            except Exception as e:
                print(f"  [{idx}/{agent_count}] {name}: parse error: {e}")

    return forecasts
```

- [ ] **Step 2: Commit**

```bash
git add backend/scripts/run_trade.py
git commit -m "feat: update _interview_agents to collect price range forecasts"
```

---

### Task 6: Update `step5_interview_for_trades` + `write_csv` + `main`

**Files:**
- Modify: `backend/scripts/run_trade.py`

- [ ] **Step 1: Update `step5_interview_for_trades`**

Replace the existing function with:

```python
def step5_interview_for_trades(base_url, simulation_id, seed_text, predict_hours, session=None):
    """Interview each agent for price range forecast, return list of forecast dicts."""
    print("[Step 5/5] Interviewing agents for price forecasts...")

    id_to_profile, platform = _get_agent_profiles(base_url, simulation_id, session=session)
    agent_count = len(id_to_profile)

    run_status = api("get", base_url, f"/api/simulation/{simulation_id}/run-status", session=session)
    env_alive = run_status.get("runner_status") not in ("stopped", "failed", "idle")

    if env_alive:
        print(f"  Found {agent_count} agents (platform: {platform}) — trying OASIS interview...")
        try:
            forecasts = _interview_agents(base_url, simulation_id, seed_text, predict_hours,
                                          id_to_profile, platform, session=session)
            if forecasts:
                return forecasts
        except Exception as e:
            print(f"  Interview failed: {e}")

    return _fallback_persona_decisions(None, seed_text, id_to_profile, predict_hours)
```

> **Note:** The fallback no longer needs `llm` for persona-based forecasts — wait, it does. Keep passing `llm` in. The signature above is wrong — fix the call: `_fallback_persona_decisions(llm, seed_text, id_to_profile, predict_hours)`. The `llm` object must be passed down from `main`. Update the function signature of `step5_interview_for_trades` to accept `llm` as well:

```python
def step5_interview_for_trades(base_url, simulation_id, llm, seed_text, predict_hours, session=None):
    """Interview each agent for price range forecast, return list of forecast dicts."""
    print("[Step 5/5] Interviewing agents for price forecasts...")

    id_to_profile, platform = _get_agent_profiles(base_url, simulation_id, session=session)
    agent_count = len(id_to_profile)

    run_status = api("get", base_url, f"/api/simulation/{simulation_id}/run-status", session=session)
    env_alive = run_status.get("runner_status") not in ("stopped", "failed", "idle")

    if env_alive:
        print(f"  Found {agent_count} agents (platform: {platform}) — trying OASIS interview...")
        try:
            forecasts = _interview_agents(base_url, simulation_id, seed_text, predict_hours,
                                          id_to_profile, platform, session=session)
            if forecasts:
                return forecasts
        except Exception as e:
            print(f"  Interview failed: {e}")

    return _fallback_persona_decisions(llm, seed_text, id_to_profile, predict_hours)
```

- [ ] **Step 2: Update `write_csv`**

Replace the existing `write_csv` function with:

```python
def write_csv(forecasts, output_path, start_timestamp, predict_hours):
    """Write price forecast decisions to CSV."""
    end_timestamp = start_timestamp + predict_hours * 3600
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "start_timestamp", "end_timestamp",
                                               "range_low", "range_high"])
        writer.writeheader()
        for row in forecasts:
            writer.writerow({
                "name": row["name"],
                "start_timestamp": start_timestamp,
                "end_timestamp": end_timestamp,
                "range_low": row["range_low"],
                "range_high": row["range_high"],
            })
```

- [ ] **Step 3: Update `main`**

In `main()`:

1. Replace `--rounds` argument block — add `--predict-hours`:

```python
parser.add_argument("--predict-hours", type=int, default=12,
                    help="Forecast horizon in hours (default: 12)")
parser.add_argument("--rounds", type=int, default=15,
                    help="Max simulation rounds (default: 15)")
```

2. Update the step 5 call and CSV write at the bottom of `main()`:

```python
forecasts = step5_interview_for_trades(args.base_url, simulation_id, llm, seed_text,
                                       args.predict_hours, session=session)

if forecasts:
    start_ts = extract_latest_timestamp(seed_text)
    write_csv(forecasts, args.output, start_ts, args.predict_hours)
    print()
    print("=" * 50)
    print(f"Output: {args.output} ({len(forecasts)} forecasts)")
else:
    print()
    print("=" * 50)
    print("Warning: No valid price forecasts were generated")
    sys.exit(1)
```

- [ ] **Step 4: Run all tests**

```bash
backend/.venv/bin/pytest backend/scripts/test_run_trade.py -v
```

Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/run_trade.py
git commit -m "feat: wire up price forecast pipeline — step5, write_csv, main"
```

---

### Task 7: Smoke test end-to-end (dry run)

**Files:** none

- [ ] **Step 1: Verify CLI help shows new flag**

```bash
backend/.venv/bin/python backend/scripts/run_trade.py --help
```

Expected output includes:
```
--predict-hours PREDICT_HOURS
                      Forecast horizon in hours (default: 12)
```

- [ ] **Step 2: Check for any remaining references to old functions**

```bash
grep -n "_parse_decision\|_validate_decision\|_fmt_decision\|_decide_from_persona\|write_csv.*direction\|\"direction\"\|\"order_type\"\|\"leverage\"" backend/scripts/run_trade.py
```

Expected: no matches.

- [ ] **Step 3: Commit if any stray references were cleaned up, otherwise skip**

```bash
git add backend/scripts/run_trade.py
git commit -m "chore: remove stray references to old trade decision fields"
```
