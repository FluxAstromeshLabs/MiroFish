# gen_seed Local CSV Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `gen_seed.py` to read OHLCV and liquidation data from local `marketdata/YYYY-MM-DD/` CSV files instead of the Flux HTTP API, and support generating multiple seeds each shifted by 1 hour.

**Architecture:** Replace the three `fetch_*` API functions with two CSV readers (`read_ohlcv_csv`, `read_liq_csv`) and a `aggregate_1h` aggregator. Update formatters to produce JSON output. Add multi-seed loop in `main()` with `--count`/`--step`/`--end-hour`/`--marketdata`/`--output-dir` args.

**Tech Stack:** Python 3, stdlib only (`csv`, `json`, `datetime`, `os`, `argparse`) — drop `requests`.

---

## File Map

- **Modify:** `backend/scripts/gen_seed.py` — full rewrite of fetch layer and formatters; keep `_fmt_dollar`, `load_agents`, `parse_hour`, `hour_bounds_ms`
- **Modify:** `backend/scripts/test_gen_seed.py` — replace old formatter tests with new ones; add CSV reader and aggregator tests

---

### Task 1: CSV readers and 1H aggregator (pure functions, no I/O side effects)

**Files:**
- Modify: `backend/scripts/gen_seed.py`
- Modify: `backend/scripts/test_gen_seed.py`

- [ ] **Step 1: Write failing tests for `read_ohlcv_csv` and `read_liq_csv`**

Replace the contents of `test_gen_seed.py` with:

```python
"""Tests for gen_seed CSV readers, aggregator, and formatters."""
import sys, os, json, tempfile
sys.path.insert(0, os.path.dirname(__file__))

# ── Existing time-helper tests (keep unchanged) ────────────────────────────
from gen_seed import hour_bounds_ms, parse_hour
from datetime import datetime, timezone

def test_hour_bounds_ms():
    dt = datetime(2026, 4, 8, 12, 0, 0, tzinfo=timezone.utc)
    start, end = hour_bounds_ms(dt)
    assert start == 1744113600000
    assert end   == 1744117199999

def test_parse_hour_T():
    dt = parse_hour("2026-04-08T12")
    assert dt == datetime(2026, 4, 8, 12, tzinfo=timezone.utc)

def test_parse_hour_space():
    dt = parse_hour("2026-04-08 12")
    assert dt == datetime(2026, 4, 8, 12, tzinfo=timezone.utc)

# ── read_ohlcv_csv ─────────────────────────────────────────────────────────
from gen_seed import read_ohlcv_csv

def test_read_ohlcv_csv_basic():
    rows = "T,O,H,L,C,V\n1744113600000,69000,69500,68900,69100,5.5\n"
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
        f.write(rows)
        path = f.name
    result = read_ohlcv_csv(path)
    assert len(result) == 1
    assert result[0] == {
        "T": 1744113600000, "O": 69000.0, "H": 69500.0,
        "L": 68900.0, "C": 69100.0, "V": 5.5
    }
    os.unlink(path)

def test_read_ohlcv_csv_empty():
    rows = "T,O,H,L,C,V\n"
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
        f.write(rows)
        path = f.name
    assert read_ohlcv_csv(path) == []
    os.unlink(path)

def test_read_ohlcv_csv_missing_file():
    assert read_ohlcv_csv("/nonexistent/path.csv") == []

# ── read_liq_csv ───────────────────────────────────────────────────────────
from gen_seed import read_liq_csv

def test_read_liq_csv_basic():
    rows = "S,o,f,q,p,ap,X,l,z,T\nSELL,LIMIT,IOC,0.5,69000,69000,FILLED,0.5,0.5,1744113600000\n"
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
        f.write(rows)
        path = f.name
    result = read_liq_csv(path)
    assert len(result) == 1
    assert result[0] == {"S": "SELL", "q": 0.5, "p": 69000.0, "T": 1744113600000}
    os.unlink(path)

def test_read_liq_csv_missing_file():
    assert read_liq_csv("/nonexistent/path.csv") == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /mnt/second_disk/Code/flux/flux-MiroFish
source backend/.venv/bin/activate
pytest backend/scripts/test_gen_seed.py::test_read_ohlcv_csv_basic -v
```

Expected: `ImportError` or `FAILED` — `read_ohlcv_csv` not defined yet.

- [ ] **Step 3: Add `read_ohlcv_csv` and `read_liq_csv` to `gen_seed.py`**

In `gen_seed.py`, after the imports section, remove `import requests` and add:

```python
import csv
import json
```

Then add these two functions (replacing the `fetch_*` functions):

```python
def read_ohlcv_csv(path: str) -> list[dict]:
    """Read ohlcv.csv → list of {T, O, H, L, C, V} dicts. Returns [] if file missing."""
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            rows.append({
                "T": int(row["T"]),
                "O": float(row["O"]),
                "H": float(row["H"]),
                "L": float(row["L"]),
                "C": float(row["C"]),
                "V": float(row["V"]),
            })
    return rows


def read_liq_csv(path: str) -> list[dict]:
    """Read liq.csv → list of {S, q, p, T} dicts. Returns [] if file missing."""
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            rows.append({
                "S": row["S"],
                "q": float(row["q"]),
                "p": float(row["p"]),
                "T": int(row["T"]),
            })
    return rows
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest backend/scripts/test_gen_seed.py::test_read_ohlcv_csv_basic backend/scripts/test_gen_seed.py::test_read_ohlcv_csv_empty backend/scripts/test_gen_seed.py::test_read_ohlcv_csv_missing_file backend/scripts/test_gen_seed.py::test_read_liq_csv_basic backend/scripts/test_gen_seed.py::test_read_liq_csv_missing_file -v
```

Expected: all 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/gen_seed.py backend/scripts/test_gen_seed.py
git commit -m "feat: add read_ohlcv_csv and read_liq_csv for local CSV reading"
```

---

### Task 2: `aggregate_1h` — aggregate 1-minute candles into 1H candles

**Files:**
- Modify: `backend/scripts/gen_seed.py`
- Modify: `backend/scripts/test_gen_seed.py`

- [ ] **Step 1: Write failing tests for `aggregate_1h`**

Append to `test_gen_seed.py`:

```python
# ── aggregate_1h ───────────────────────────────────────────────────────────
from gen_seed import aggregate_1h

# 3 one-minute candles: first two in 12:00 hour, one in 13:00 hour
# T values: 2026-04-08 12:00, 12:01, 13:00 UTC
_T_1200 = 1744113600000   # 2026-04-08 12:00 UTC
_T_1201 = 1744113660000   # 2026-04-08 12:01 UTC
_T_1300 = 1744117200000   # 2026-04-08 13:00 UTC

_RAW = [
    {"T": _T_1200, "O": 69000.0, "H": 69500.0, "L": 68900.0, "C": 69100.0, "V": 1.0},
    {"T": _T_1201, "O": 69100.0, "H": 69600.0, "L": 69000.0, "C": 69200.0, "V": 2.0},
    {"T": _T_1300, "O": 69200.0, "H": 69700.0, "L": 69100.0, "C": 69300.0, "V": 3.0},
]

def test_aggregate_1h_count():
    result = aggregate_1h(_RAW)
    assert len(result) == 2

def test_aggregate_1h_open_is_first():
    result = aggregate_1h(_RAW)
    candle_1200 = next(c for c in result if c["T"] == _T_1200)
    assert candle_1200["O"] == 69000.0

def test_aggregate_1h_close_is_last():
    result = aggregate_1h(_RAW)
    candle_1200 = next(c for c in result if c["T"] == _T_1200)
    assert candle_1200["C"] == 69200.0

def test_aggregate_1h_high_is_max():
    result = aggregate_1h(_RAW)
    candle_1200 = next(c for c in result if c["T"] == _T_1200)
    assert candle_1200["H"] == 69600.0

def test_aggregate_1h_low_is_min():
    result = aggregate_1h(_RAW)
    candle_1200 = next(c for c in result if c["T"] == _T_1200)
    assert candle_1200["L"] == 68900.0

def test_aggregate_1h_volume_is_sum():
    result = aggregate_1h(_RAW)
    candle_1200 = next(c for c in result if c["T"] == _T_1200)
    assert candle_1200["V"] == 3.0

def test_aggregate_1h_empty():
    assert aggregate_1h([]) == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest backend/scripts/test_gen_seed.py::test_aggregate_1h_count -v
```

Expected: `ImportError` — `aggregate_1h` not defined yet.

- [ ] **Step 3: Add `aggregate_1h` to `gen_seed.py`**

```python
def aggregate_1h(rows: list[dict]) -> list[dict]:
    """
    Aggregate 1-minute OHLCV rows into 1H candles.
    Each row: {T (ms), O, H, L, C, V}. T of output candle = floor to hour start.
    Returns list sorted by T ascending.
    """
    buckets: dict[int, dict] = {}
    for row in sorted(rows, key=lambda r: r["T"]):
        hour_start_ms = (row["T"] // 3_600_000) * 3_600_000
        if hour_start_ms not in buckets:
            buckets[hour_start_ms] = {
                "T": hour_start_ms,
                "O": row["O"],
                "H": row["H"],
                "L": row["L"],
                "C": row["C"],
                "V": row["V"],
            }
        else:
            b = buckets[hour_start_ms]
            b["H"] = max(b["H"], row["H"])
            b["L"] = min(b["L"], row["L"])
            b["C"] = row["C"]
            b["V"] += row["V"]
    return sorted(buckets.values(), key=lambda c: c["T"])
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest backend/scripts/test_gen_seed.py -k "aggregate_1h" -v
```

Expected: all 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/gen_seed.py backend/scripts/test_gen_seed.py
git commit -m "feat: add aggregate_1h to aggregate 1-min candles into 1H buckets"
```

---

### Task 3: `load_ohlcv_window` and `load_liq_window` — load data across day directories

**Files:**
- Modify: `backend/scripts/gen_seed.py`
- Modify: `backend/scripts/test_gen_seed.py`

- [ ] **Step 1: Write failing tests**

Append to `test_gen_seed.py`:

```python
# ── load_ohlcv_window / load_liq_window ───────────────────────────────────
from gen_seed import load_ohlcv_window, load_liq_window
from datetime import datetime, timezone

def _make_marketdata(tmp_path, day_str, ohlcv_rows=None, liq_rows=None):
    """Helper: create a marketdata/YYYY-MM-DD/ dir with optional CSV files."""
    day_dir = os.path.join(tmp_path, day_str)
    os.makedirs(day_dir, exist_ok=True)
    if ohlcv_rows is not None:
        with open(os.path.join(day_dir, "ohlcv.csv"), "w") as f:
            f.write("T,O,H,L,C,V\n")
            for r in ohlcv_rows:
                f.write(",".join(str(x) for x in r) + "\n")
    if liq_rows is not None:
        with open(os.path.join(day_dir, "liq.csv"), "w") as f:
            f.write("S,o,f,q,p,ap,X,l,z,T\n")
            for r in liq_rows:
                f.write(",".join(str(x) for x in r) + "\n")
    return tmp_path

# end_dt = 2026-04-08 12:00 UTC, hours=2 → window: 10:00–12:00
_END_DT = datetime(2026, 4, 8, 12, 0, 0, tzinfo=timezone.utc)
_T_1000 = 1744106400000   # 2026-04-08 10:00 UTC
_T_1100 = 1744110000000   # 2026-04-08 11:00 UTC

def test_load_ohlcv_window_filters_by_time(tmp_path):
    _make_marketdata(str(tmp_path), "2026-04-08", ohlcv_rows=[
        [_T_1000, 69000, 69500, 68900, 69100, 1.0],   # in window
        [_T_1100, 69100, 69600, 69000, 69200, 2.0],   # in window
        [1744120800000, 69200, 69700, 69100, 69300, 3.0],  # 14:00 — out of window
    ])
    result = load_ohlcv_window(str(tmp_path), _END_DT, hours=2)
    assert len(result) == 2

def test_load_ohlcv_window_missing_dir(tmp_path):
    result = load_ohlcv_window(str(tmp_path), _END_DT, hours=2)
    assert result == []

def test_load_liq_window_sums(tmp_path):
    _make_marketdata(str(tmp_path), "2026-04-08", liq_rows=[
        ["SELL", "LIMIT", "IOC", 0.5, 69000, 69000, "FILLED", 0.5, 0.5, _T_1000],  # long liq
        ["BUY",  "LIMIT", "IOC", 1.0, 68000, 68000, "FILLED", 1.0, 1.0, _T_1100],  # short liq
    ])
    result = load_liq_window(str(tmp_path), _END_DT, hours=2)
    assert abs(result["long"]  - 0.5 * 69000) < 0.01
    assert abs(result["short"] - 1.0 * 68000) < 0.01

def test_load_liq_window_empty(tmp_path):
    result = load_liq_window(str(tmp_path), _END_DT, hours=2)
    assert result == {"long": 0.0, "short": 0.0}
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest backend/scripts/test_gen_seed.py::test_load_ohlcv_window_filters_by_time -v
```

Expected: `ImportError` — functions not defined yet.

- [ ] **Step 3: Add `load_ohlcv_window` and `load_liq_window` to `gen_seed.py`**

```python
def _days_in_window(end_dt: datetime, hours: int) -> list[str]:
    """Return list of YYYY-MM-DD strings for all calendar days (UTC) that overlap the window."""
    start_dt = end_dt - timedelta(hours=hours - 1)
    days = []
    cur = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    end_day = end_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    while cur <= end_day:
        days.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return days


def load_ohlcv_window(marketdata_dir: str, end_dt: datetime, hours: int) -> list[dict]:
    """
    Load and aggregate 1H candles from marketdata CSVs for the window
    [end_dt - hours + 1h, end_dt] (inclusive). Returns list of 1H candle dicts.
    """
    start_dt = end_dt - timedelta(hours=hours - 1)
    start_ms = int(start_dt.replace(minute=0, second=0, microsecond=0).timestamp() * 1000)
    end_ms = int(end_dt.replace(minute=0, second=0, microsecond=0).timestamp() * 1000) + 3_599_999

    raw = []
    for day in _days_in_window(end_dt, hours):
        path = os.path.join(marketdata_dir, day, "ohlcv.csv")
        for row in read_ohlcv_csv(path):
            if start_ms <= row["T"] <= end_ms:
                raw.append(row)

    return aggregate_1h(raw)


def load_liq_window(marketdata_dir: str, end_dt: datetime, hours: int) -> dict:
    """
    Sum long and short liquidations from liq CSVs over the window.
    SELL rows = long liquidations; BUY rows = short liquidations.
    Returns {"long": float, "short": float}.
    """
    start_dt = end_dt - timedelta(hours=hours - 1)
    start_ms = int(start_dt.replace(minute=0, second=0, microsecond=0).timestamp() * 1000)
    end_ms = int(end_dt.replace(minute=0, second=0, microsecond=0).timestamp() * 1000) + 3_599_999

    total_long = 0.0
    total_short = 0.0
    for day in _days_in_window(end_dt, hours):
        path = os.path.join(marketdata_dir, day, "liq.csv")
        for row in read_liq_csv(path):
            if start_ms <= row["T"] <= end_ms:
                value = row["q"] * row["p"]
                if row["S"] == "SELL":
                    total_long += value
                else:
                    total_short += value

    return {"long": total_long, "short": total_short}
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest backend/scripts/test_gen_seed.py -k "load_ohlcv_window or load_liq_window" -v
```

Expected: all 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/gen_seed.py backend/scripts/test_gen_seed.py
git commit -m "feat: add load_ohlcv_window and load_liq_window for multi-day CSV loading"
```

---

### Task 4: Update formatters to new JSON-based seed format

**Files:**
- Modify: `backend/scripts/gen_seed.py`
- Modify: `backend/scripts/test_gen_seed.py`

- [ ] **Step 1: Write failing tests for new formatters**

Append to `test_gen_seed.py`:

```python
# ── new formatters ─────────────────────────────────────────────────────────
from gen_seed import format_chart_time, format_btc_price, format_ohlcv_json, format_liquidations_json

_CANDLES = [
    {"T": 1744113600000, "O": 69000.0, "H": 69500.0, "L": 68900.0, "C": 69100.0, "V": 5.5},
    {"T": 1744117200000, "O": 69100.0, "H": 69600.0, "L": 69000.0, "C": 69200.0, "V": 3.2},
]

def test_format_chart_time():
    dt = datetime(2026, 4, 8, 12, tzinfo=timezone.utc)
    assert format_chart_time(dt) == "# Latest Chart Time\n2026-04-08 12:00"

def test_format_btc_price():
    # last candle newest-first is _CANDLES[1] after sort, close=69200
    assert format_btc_price(_CANDLES) == "# Latest BTC Price\n69200.0"

def test_format_ohlcv_json_section_header():
    result = format_ohlcv_json(_CANDLES)
    assert result.startswith("# OHLCV 1H")

def test_format_ohlcv_json_is_valid_json():
    result = format_ohlcv_json(_CANDLES)
    json_part = result[result.index("["):]
    parsed = json.loads(json_part)
    assert len(parsed) == 2

def test_format_ohlcv_json_newest_first():
    result = format_ohlcv_json(_CANDLES)
    json_part = result[result.index("["):]
    parsed = json.loads(json_part)
    assert parsed[0]["time"] == "2026-04-08 13:00"
    assert parsed[1]["time"] == "2026-04-08 12:00"

def test_format_ohlcv_json_fields():
    result = format_ohlcv_json(_CANDLES)
    json_part = result[result.index("["):]
    parsed = json.loads(json_part)
    assert set(parsed[0].keys()) == {"time", "open", "high", "low", "close", "volume"}

def test_format_liquidations_json():
    result = format_liquidations_json({"long": 3_200_000.0, "short": 1_400_000.0})
    assert result.startswith("# Liquidations")
    json_part = result[result.index("{"):]
    parsed = json.loads(json_part)
    assert parsed["long"] == 3_200_000.0
    assert parsed["short"] == 1_400_000.0
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest backend/scripts/test_gen_seed.py::test_format_chart_time -v
```

Expected: `ImportError` — new formatters not defined yet.

- [ ] **Step 3: Replace old formatters in `gen_seed.py` with new ones**

Remove `format_ohlcv`, `format_liquidations`, `format_news` and add:

```python
def format_chart_time(end_dt: datetime) -> str:
    return f"# Latest Chart Time\n{end_dt.strftime('%Y-%m-%d %H:%M')}"


def format_btc_price(candles_1h: list[dict]) -> str:
    """Latest close = close of the highest-T candle."""
    if not candles_1h:
        return "# Latest BTC Price\nN/A"
    latest = max(candles_1h, key=lambda c: c["T"])
    return f"# Latest BTC Price\n{latest['C']}"


def format_ohlcv_json(candles_1h: list[dict]) -> str:
    """Render 1H candles as JSON array, newest-first."""
    sorted_candles = sorted(candles_1h, key=lambda c: c["T"], reverse=True)
    items = []
    for c in sorted_candles:
        dt = datetime.fromtimestamp(c["T"] / 1000, tz=timezone.utc)
        items.append({
            "time": dt.strftime("%Y-%m-%d %H:%M"),
            "open": c["O"],
            "high": c["H"],
            "low": c["L"],
            "close": c["C"],
            "volume": round(c["V"], 2),
        })
    return "# OHLCV 1H\n" + json.dumps(items, indent=2)


def format_liquidations_json(liq: dict) -> str:
    """Render single-row liquidation summary as JSON."""
    return "# Liquidations\n" + json.dumps({"long": liq["long"], "short": liq["short"]})


def format_news() -> str:
    return "# News\n(no news)"
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest backend/scripts/test_gen_seed.py -k "format_" -v
```

Expected: all new formatter tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/gen_seed.py backend/scripts/test_gen_seed.py
git commit -m "feat: replace table formatters with JSON-based seed formatters"
```

---

### Task 5: Rewrite `main()` with new CLI args and multi-seed loop

**Files:**
- Modify: `backend/scripts/gen_seed.py`

- [ ] **Step 1: Replace `main()` in `gen_seed.py`**

Remove the old `main()` entirely and replace with:

```python
def main():
    _now = datetime.now(tz=timezone.utc)
    _default_hour = _now.strftime("%Y-%m-%dT%H")

    parser = argparse.ArgumentParser(description="gen_seed — marketdata CSV → seed.md (BTC Futures)")
    parser.add_argument("--end-hour", default=_default_hour,
                        help="End hour of the last seed YYYY-MM-DDTHH in UTC (default: current hour)")
    parser.add_argument("--hours", type=int, default=72,
                        help="Hours of history per seed (default: 72)")
    parser.add_argument("--count", type=int, default=1,
                        help="Number of seeds to generate, each shifted back by --step hours (default: 1)")
    parser.add_argument("--step", type=int, default=1,
                        help="Hour shift between seeds (default: 1)")
    parser.add_argument("--marketdata", default=None,
                        help="Path to marketdata directory (default: <project_root>/marketdata)")
    parser.add_argument("--agents", default=None,
                        help="Optional agents file path (default: <project_root>/agents.txt)")
    parser.add_argument("--output-dir", default=None,
                        help="Directory for output seed files (default: project root)")
    args = parser.parse_args()

    marketdata_dir = resolve_path(args.marketdata or "marketdata")
    output_dir = resolve_path(args.output_dir or ".")
    os.makedirs(output_dir, exist_ok=True)

    end_dt = parse_hour(args.end_hour)
    agents_text = load_agents(args.agents)

    # Seeds: end_dt - (count-1)*step, ..., end_dt - step, end_dt
    seed_end_times = [
        end_dt - timedelta(hours=(args.count - 1 - i) * args.step)
        for i in range(args.count)
    ]

    print(f"gen_seed — marketdata CSV → seed.md")
    print(f"  Marketdata : {marketdata_dir}")
    print(f"  Output dir : {output_dir}")
    print(f"  Seeds      : {args.count}  (step={args.step}h, window={args.hours}h each)")
    print()

    for seed_end in seed_end_times:
        label = seed_end.strftime("%Y-%m-%dT%H")
        filename = "seed.md" if args.count == 1 else f"seed_{label}.md"
        out_path = os.path.join(output_dir, filename)

        print(f"  Generating {label} ...", end=" ", flush=True)

        candles = load_ohlcv_window(marketdata_dir, seed_end, args.hours)
        liq = load_liq_window(marketdata_dir, seed_end, args.hours)

        content = "\n\n".join([
            format_chart_time(seed_end),
            format_btc_price(candles),
            format_ohlcv_json(candles),
            format_liquidations_json(liq),
            format_news(),
            "# Agents Population\n" + agents_text,
        ]) + "\n"

        with open(out_path, "w") as f:
            f.write(content)

        print(f"{len(candles)} candles → {filename}")

    print("\nDone.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run all tests to make sure nothing is broken**

```bash
pytest backend/scripts/test_gen_seed.py -v
```

Expected: all tests PASS.

- [ ] **Step 3: Smoke-test with real marketdata**

```bash
python backend/scripts/gen_seed.py \
  --end-hour 2026-04-08T14 \
  --count 3 \
  --step 1 \
  --marketdata marketdata \
  --output-dir /tmp/seeds
```

Expected output:
```
gen_seed — marketdata CSV → seed.md
  Marketdata : .../marketdata
  Output dir : /tmp/seeds
  Seeds      : 3  (step=1h, window=72h each)

  Generating 2026-04-08T12 ... 72 candles → seed_2026-04-08T12.md
  Generating 2026-04-08T13 ... 72 candles → seed_2026-04-08T13.md
  Generating 2026-04-08T14 ... 72 candles → seed_2026-04-08T14.md

Done.
```

Then inspect one file:
```bash
head -20 /tmp/seeds/seed_2026-04-08T12.md
```

Confirm: `# Latest Chart Time`, `# Latest BTC Price`, `# OHLCV 1H` with JSON array, `# Liquidations` with JSON object.

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/gen_seed.py
git commit -m "feat: rewrite main() for local CSV mode with multi-seed --count/--step support"
```

---

### Task 6: Remove stale tests and dead code

**Files:**
- Modify: `backend/scripts/test_gen_seed.py`
- Modify: `backend/scripts/gen_seed.py`

- [ ] **Step 1: Remove old tests that reference removed symbols**

In `test_gen_seed.py`, delete any remaining tests that import or call:
- `day_bounds_ms`, `offset_day` (removed from gen_seed.py)
- `format_ohlcv` (old table version with 3 args)
- `format_liquidations` (old windowed version)
- `format_news` with args

- [ ] **Step 2: Remove dead code from `gen_seed.py`**

Verify `_fmt_dollar` is no longer called anywhere in the file. If unused, delete it.
Also remove `DEFAULT_AGENTS` if `load_agents` now falls back to `agents.txt` only.

- [ ] **Step 3: Run all tests**

```bash
pytest backend/scripts/test_gen_seed.py -v
```

Expected: all tests PASS, no import errors.

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/gen_seed.py backend/scripts/test_gen_seed.py
git commit -m "chore: remove stale tests and dead code from gen_seed rewrite"
```
