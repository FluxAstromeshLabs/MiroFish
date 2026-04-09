# gen_seed API Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `backend/scripts/gen_seed.py` to fetch BTC futures market data from the Flux exchange HTTP API and output a structured tabular `seed.md`, replacing the old CSV pipeline entirely.

**Architecture:** Pure rewrite of one script file plus `agents.txt`. Three API fetchers (OHLCV, liquidations, news) feed pure formatter functions that produce Markdown tables. No LLM call. All OHLCV and news rows are sorted newest-first. A `--days N` arg controls how many days of OHLCV/news history to include.

**Tech Stack:** Python 3, `requests`, `argparse`, existing `backend/scripts/common.py` (provides `project_root`, `resolve_path`).

---

## File Map

| File | Action |
|------|--------|
| `agents.txt` | Rewrite — 15 traders + 5 KOLs, style-only descriptions |
| `backend/scripts/gen_seed.py` | Rewrite — API fetchers + formatters + main() |
| `backend/scripts/test_gen_seed.py` | Create — unit tests for time helpers and formatters |

`backend/scripts/common.py` — unchanged.

---

## Task 1: Rewrite `agents.txt`

**Files:**
- Modify: `agents.txt`

- [ ] **Step 1: Replace `agents.txt` contents**

Write the following as the complete file content:

```
- quant1: Analytical, data-driven, emotionally detached. Trusts numbers over intuition.
- quant2: Methodical and process-oriented. Uncomfortable with ambiguity, relies on repeatable systems.
- swing1: Patient, reads macro structure. Waits for conviction before committing.
- swing2: Trend-follower with a high tolerance for drawdown. Holds through noise.
- scalper1: Hyper-focused, reactive, lives in the short-term. Dislikes overnight exposure.
- scalper2: Competitive and fast-twitch. Treats every tick as an opportunity.
- whale1: Methodical and private. Moves quietly, thinks in large time horizons.
- whale2: Deliberate and patient. Rarely overreacts, hard to rattle.
- news1: Macro-aware and well-read. Connects headline dots faster than most.
- news2: Alert and always plugged in. First to react to crypto-native developments.
- degen1: Impulsive and overconfident. Thrives on volatility, hates sitting on the sidelines.
- degen2: Risk-blind and excitement-driven. Chases action more than outcomes.
- hodler1: Patient and conviction-driven. Tunes out short-term noise.
- contrarian1: Skeptical of consensus. Comfortable being the only one taking the opposite view.
- retail1: Easily influenced, reactive to price moves and social feeds.
- kol1 (KOL, 2.1M followers): Hype-driven, high-energy, large retail audience. Posts frequently and amplifies momentum.
- kol2 (KOL, 420K followers): Measured and data-heavy. Institutional-leaning audience, focuses on evidence over emotion.
- kol3 (KOL, 95K followers): Niche on-chain specialist. Small but highly technical and loyal following.
- kol4 (KOL, 1.8M followers): Macro-first thinker. Bridges TradFi and crypto, commands credibility across both.
- kol5 (KOL, 31K followers): Contrarian voice. Often goes against popular takes, niche but devoted community.
```

- [ ] **Step 2: Commit**

```bash
git add agents.txt
git commit -m "feat: expand agents to 15 traders + 5 KOLs"
```

---

## Task 2: Time helpers — test then implement

**Files:**
- Create: `backend/scripts/test_gen_seed.py`
- Create: `backend/scripts/gen_seed.py` (skeleton)

- [ ] **Step 1: Write `test_gen_seed.py` with time helper tests**

Create `backend/scripts/test_gen_seed.py`:

```python
"""Tests for gen_seed time helpers and formatters."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from gen_seed import day_bounds_ms, offset_day


def test_day_bounds_ms_start():
    start, _ = day_bounds_ms("2026-04-06")
    assert start == 1743897600000  # 2026-04-06 00:00:00 UTC in ms


def test_day_bounds_ms_end():
    _, end = day_bounds_ms("2026-04-06")
    assert end == 1743983999999  # 2026-04-06 23:59:59.999 UTC in ms


def test_day_bounds_ms_span():
    start, end = day_bounds_ms("2026-04-06")
    assert end - start == 86_400_000 - 1


def test_offset_day_negative():
    assert offset_day("2026-04-06", -2) == "2026-04-04"


def test_offset_day_positive():
    assert offset_day("2026-04-06", 1) == "2026-04-07"


def test_offset_day_zero():
    assert offset_day("2026-04-06", 0) == "2026-04-06"
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd /mnt/second_disk/Code/flux/flux-MiroFish
python -m pytest backend/scripts/test_gen_seed.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'gen_seed'`

- [ ] **Step 3: Create `gen_seed.py` skeleton with time helpers**

Write `backend/scripts/gen_seed.py`:

```python
"""
gen_seed — Flux Exchange API → seed.md (BTC Futures)
Fetches OHLCV, liquidations, and news from the Flux exchange HTTP API,
then writes a structured Markdown seed file.
"""

import os
import argparse
from datetime import datetime, timezone, timedelta

import requests

from common import project_root, resolve_path


# ── Time helpers ───────────────────────────────────────────────────────────

def day_bounds_ms(date_str):
    """Return (start_ms, end_ms) for a YYYY-MM-DD day in UTC (inclusive ms)."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start = int(dt.timestamp() * 1000)
    end = int((dt + timedelta(days=1)).timestamp() * 1000) - 1
    return start, end


def offset_day(date_str, delta):
    """Return YYYY-MM-DD string shifted by delta days (negative = earlier)."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return (dt + timedelta(days=delta)).strftime("%Y-%m-%d")
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd /mnt/second_disk/Code/flux/flux-MiroFish
python -m pytest backend/scripts/test_gen_seed.py -v 2>&1 | head -20
```

Expected:
```
PASSED test_day_bounds_ms_start
PASSED test_day_bounds_ms_end
PASSED test_day_bounds_ms_span
PASSED test_offset_day_negative
PASSED test_offset_day_positive
PASSED test_offset_day_zero
6 passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/gen_seed.py backend/scripts/test_gen_seed.py
git commit -m "feat(gen_seed): add time helpers with tests"
```

---

## Task 3: Formatters — test then implement

**Files:**
- Modify: `backend/scripts/test_gen_seed.py` (append formatter tests)
- Modify: `backend/scripts/gen_seed.py` (append formatters)

- [ ] **Step 1: Append formatter tests to `test_gen_seed.py`**

Add the following to the end of `backend/scripts/test_gen_seed.py`:

```python
from gen_seed import _fmt_dollar, format_ohlcv, format_liquidations, format_news


# ── _fmt_dollar ────────────────────────────────────────────────────────────

def test_fmt_dollar_millions():
    assert _fmt_dollar("2427609.985") == "$2.4M"


def test_fmt_dollar_thousands():
    assert _fmt_dollar("303436.72") == "$303.4K"


def test_fmt_dollar_small():
    assert _fmt_dollar("500") == "$500"


def test_fmt_dollar_zero():
    assert _fmt_dollar("0") == "$0"


def test_fmt_dollar_invalid():
    assert _fmt_dollar(None) == "N/A"


# ── format_ohlcv ───────────────────────────────────────────────────────────

OHLCV_ITEM_OLD = {
    "open_time_ms": 1743811200000,  # 2026-04-05 00:00 UTC
    "open": "82900", "high": "83600", "low": "82400", "close": "83100", "volume": "10800",
}
OHLCV_ITEM_NEW = {
    "open_time_ms": 1743897600000,  # 2026-04-06 00:00 UTC
    "open": "83100", "high": "84200", "low": "82800", "close": "83900", "volume": "11200",
}


def test_format_ohlcv_starts_with_header():
    result = format_ohlcv([OHLCV_ITEM_NEW], [], [])
    assert result.startswith("# OHLCV")


def test_format_ohlcv_1d_section():
    result = format_ohlcv([OHLCV_ITEM_NEW], [], [])
    assert "## 1D" in result
    assert "2026-04-06" in result


def test_format_ohlcv_1d_newest_first():
    result = format_ohlcv([OHLCV_ITEM_OLD, OHLCV_ITEM_NEW], [], [])
    idx_new = result.index("2026-04-06")
    idx_old = result.index("2026-04-05")
    assert idx_new < idx_old, "Newest row should appear before older row"


def test_format_ohlcv_section_order():
    result = format_ohlcv([], [], [])
    assert "## 1H" in result
    assert "## 4H" in result
    assert "## 1D" in result
    # 1H appears before 4H, 4H before 1D
    assert result.index("## 1H") < result.index("## 4H") < result.index("## 1D")


# ── format_liquidations ────────────────────────────────────────────────────

LIQ_DATA = {
    "1h":  {"total_long": "2427609.985", "total_short": "2085172.725", "count": 1, "items": []},
    "4h":  {"total_long": "9500000",     "total_short": "8200000",     "count": 5, "items": []},
    "12h": {"total_long": "28000000",    "total_short": "21000000",    "count": 18, "items": []},
    "24h": {"total_long": "55000000",    "total_short": "43000000",    "count": 32, "items": []},
}


def test_format_liquidations_header():
    result = format_liquidations(LIQ_DATA)
    assert result.startswith("# Liquidations")


def test_format_liquidations_all_windows():
    result = format_liquidations(LIQ_DATA)
    for label in ("1h", "4h", "12h", "24h"):
        assert label in result


def test_format_liquidations_values():
    result = format_liquidations(LIQ_DATA)
    assert "$2.4M" in result   # 1h long
    assert "$2.1M" in result   # 1h short


# ── format_news ────────────────────────────────────────────────────────────

NEWS_ITEMS = [
    {"timestamp_ms": 1743921000000, "content": "Fed signals pause in rate hikes"},   # 08:30
    {"timestamp_ms": 1743943200000, "content": "MicroStrategy buys 500 BTC"},        # 14:40
]


def test_format_news_header():
    result = format_news(NEWS_ITEMS)
    assert result.startswith("# News")
    assert "Time" in result


def test_format_news_newest_first():
    result = format_news(NEWS_ITEMS)
    idx_later = result.index("MicroStrategy")
    idx_earlier = result.index("Fed signals")
    assert idx_later < idx_earlier, "Newer news should appear before older news"


def test_format_news_empty():
    result = format_news([])
    assert "(no news)" in result
```

- [ ] **Step 2: Run new tests — verify they fail**

```bash
cd /mnt/second_disk/Code/flux/flux-MiroFish
python -m pytest backend/scripts/test_gen_seed.py -v -k "fmt_dollar or ohlcv or liquidations or news" 2>&1 | head -30
```

Expected: `ImportError` or `FAILED` for all new tests.

- [ ] **Step 3: Append formatters to `gen_seed.py`**

Add the following after the `offset_day` function in `backend/scripts/gen_seed.py`:

```python
# ── Formatters ─────────────────────────────────────────────────────────────

def _fmt_dollar(val):
    """Format a numeric string/float as $X.XM / $X.XK / $X."""
    try:
        v = float(val)
    except (TypeError, ValueError):
        return "N/A"
    if v >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v / 1_000:.1f}K"
    return f"${v:,.0f}"


def format_ohlcv(items_1d, items_4h, items_1h):
    """
    Build the # OHLCV section with ## 1D, ## 4H, ## 1H subsections.
    All rows sorted newest-first within each subsection.
    """
    def _hdr_1d():
        return f"{'Date':<10} | {'Open':>10} | {'High':>10} | {'Low':>10} | {'Close':>10} | {'Volume':>12}"

    def _hdr_sub():
        return f"{'Date/Time':<16} | {'Open':>10} | {'High':>10} | {'Low':>10} | {'Close':>10} | {'Volume':>12}"

    def _row_1d(item):
        dt = datetime.fromtimestamp(item["open_time_ms"] / 1000, tz=timezone.utc)
        return (
            f"{dt.strftime('%Y-%m-%d'):<10} | "
            f"{float(item['open']):>10,.2f} | "
            f"{float(item['high']):>10,.2f} | "
            f"{float(item['low']):>10,.2f} | "
            f"{float(item['close']):>10,.2f} | "
            f"{float(item['volume']):>12,.2f}"
        )

    def _row_sub(item):
        dt = datetime.fromtimestamp(item["open_time_ms"] / 1000, tz=timezone.utc)
        return (
            f"{dt.strftime('%Y-%m-%d %H:%M'):<16} | "
            f"{float(item['open']):>10,.2f} | "
            f"{float(item['high']):>10,.2f} | "
            f"{float(item['low']):>10,.2f} | "
            f"{float(item['close']):>10,.2f} | "
            f"{float(item['volume']):>12,.2f}"
        )

    def _section(label, hdr_fn, row_fn, items):
        sorted_items = sorted(items, key=lambda x: x["open_time_ms"], reverse=True)
        rows = [row_fn(i) for i in sorted_items]
        return "\n".join([f"## {label}", hdr_fn()] + rows)

    return "\n\n".join([
        "# OHLCV",
        _section("1H", _hdr_sub, _row_sub, items_1h),
        _section("4H", _hdr_sub, _row_sub, items_4h),
        _section("1D", _hdr_1d, _row_1d, items_1d),
    ])


def format_liquidations(liq_by_window):
    """
    Build the # Liquidations table.
    liq_by_window: {"1h": resp_dict, "4h": resp_dict, "12h": resp_dict, "24h": resp_dict}
    """
    header = f"{'Last':<4} | {'Long liq':>9} | {'Short liq':>10}"
    rows = []
    for label in ("1h", "4h", "12h", "24h"):
        data = liq_by_window[label]
        rows.append(
            f"{label:<4} | {_fmt_dollar(data.get('total_long', 0)):>9} | "
            f"{_fmt_dollar(data.get('total_short', 0)):>10}"
        )
    return "\n".join(["# Liquidations", header] + rows)


def format_news(items):
    """Build the # News table, newest-first."""
    header = f"{'Time':<16} | News"
    sorted_items = sorted(items, key=lambda x: x.get("timestamp_ms", 0), reverse=True)
    rows = []
    for item in sorted_items:
        dt = datetime.fromtimestamp(item["timestamp_ms"] / 1000, tz=timezone.utc)
        content = item.get("content", "").replace("\n", " ").strip()
        rows.append(f"{dt.strftime('%Y-%m-%d %H:%M'):<16} | {content}")
    if not rows:
        rows.append("(no news)")
    return "\n".join(["# News", header] + rows)
```

- [ ] **Step 4: Run all tests — verify they pass**

```bash
cd /mnt/second_disk/Code/flux/flux-MiroFish
python -m pytest backend/scripts/test_gen_seed.py -v 2>&1 | tail -25
```

Expected:
```
PASSED test_day_bounds_ms_start
PASSED test_day_bounds_ms_end
PASSED test_day_bounds_ms_span
PASSED test_offset_day_negative
PASSED test_offset_day_positive
PASSED test_offset_day_zero
PASSED test_fmt_dollar_millions
PASSED test_fmt_dollar_thousands
PASSED test_fmt_dollar_small
PASSED test_fmt_dollar_zero
PASSED test_fmt_dollar_invalid
PASSED test_format_ohlcv_starts_with_header
PASSED test_format_ohlcv_1d_section
PASSED test_format_ohlcv_1d_newest_first
PASSED test_format_ohlcv_has_4h_and_1h_sections
PASSED test_format_liquidations_header
PASSED test_format_liquidations_all_windows
PASSED test_format_liquidations_values
PASSED test_format_news_header
PASSED test_format_news_newest_first
PASSED test_format_news_empty
21 passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/gen_seed.py backend/scripts/test_gen_seed.py
git commit -m "feat(gen_seed): add formatters with tests (ohlcv, liquidations, news)"
```

---

## Task 4: API fetchers, agents loader, and main()

**Files:**
- Modify: `backend/scripts/gen_seed.py` (append fetchers + agents + main)

- [ ] **Step 1: Append fetchers and agents loader to `gen_seed.py`**

Add the following after the `format_news` function:

```python
# ── API fetchers ───────────────────────────────────────────────────────────

def fetch_ohlcv(base_url, bucket, day):
    """
    GET /api/v1/history/ohlcv?bucket=<bucket>&day=<day>&start=<ms>&end=<ms>
    Returns list of item dicts with open_time_ms, open, high, low, close, volume.
    """
    start, end = day_bounds_ms(day)
    resp = requests.get(
        f"{base_url}/api/v1/history/ohlcv",
        params={"bucket": bucket, "day": day, "start": start, "end": end},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("items", [])


def fetch_liquidations(base_url, start_ms, end_ms):
    """
    GET /api/v1/history/liquidations?start=<ms>&end=<ms>
    Returns dict with total_long, total_short, count, items.
    """
    resp = requests.get(
        f"{base_url}/api/v1/history/liquidations",
        params={"start": start_ms, "end": end_ms},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_news(base_url, start_ms, end_ms):
    """
    GET /api/v1/history/news?start=<ms>&end=<ms>
    Returns list of item dicts with timestamp_ms and content.
    """
    resp = requests.get(
        f"{base_url}/api/v1/history/news",
        params={"start": start_ms, "end": end_ms},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("items", [])


# ── Agents ─────────────────────────────────────────────────────────────────

DEFAULT_AGENTS = """\
- quant1: Analytical, data-driven, emotionally detached. Trusts numbers over intuition.
- quant2: Methodical and process-oriented. Uncomfortable with ambiguity, relies on repeatable systems.
- swing1: Patient, reads macro structure. Waits for conviction before committing.
- swing2: Trend-follower with a high tolerance for drawdown. Holds through noise.
- scalper1: Hyper-focused, reactive, lives in the short-term. Dislikes overnight exposure.
- scalper2: Competitive and fast-twitch. Treats every tick as an opportunity.
- whale1: Methodical and private. Moves quietly, thinks in large time horizons.
- whale2: Deliberate and patient. Rarely overreacts, hard to rattle.
- news1: Macro-aware and well-read. Connects headline dots faster than most.
- news2: Alert and always plugged in. First to react to crypto-native developments.
- degen1: Impulsive and overconfident. Thrives on volatility, hates sitting on the sidelines.
- degen2: Risk-blind and excitement-driven. Chases action more than outcomes.
- hodler1: Patient and conviction-driven. Tunes out short-term noise.
- contrarian1: Skeptical of consensus. Comfortable being the only one taking the opposite view.
- retail1: Easily influenced, reactive to price moves and social feeds.
- kol1 (KOL, 2.1M followers): Hype-driven, high-energy, large retail audience. Posts frequently and amplifies momentum.
- kol2 (KOL, 420K followers): Measured and data-heavy. Institutional-leaning audience, focuses on evidence over emotion.
- kol3 (KOL, 95K followers): Niche on-chain specialist. Small but highly technical and loyal following.
- kol4 (KOL, 1.8M followers): Macro-first thinker. Bridges TradFi and crypto, commands credibility across both.
- kol5 (KOL, 31K followers): Contrarian voice. Often goes against popular takes, niche but devoted community."""


def load_agents(agents_path=None):
    if agents_path and os.path.exists(agents_path):
        with open(agents_path) as f:
            return f.read().strip()
    default = os.path.join(project_root, "agents.txt")
    if os.path.exists(default):
        with open(default) as f:
            return f.read().strip()
    return DEFAULT_AGENTS


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="gen_seed — Flux API → seed.md (BTC Futures)")
    parser.add_argument("--base-url", default="http://localhost:8080",
                        help="Flux exchange base URL (default: http://localhost:8080)")
    parser.add_argument("--day", default=datetime.now(tz=timezone.utc).strftime("%Y-%m-%d"),
                        help="Ending day YYYY-MM-DD (default: today UTC)")
    parser.add_argument("--days", type=int, default=3,
                        help="Days of history to include (default: 3)")
    parser.add_argument("--agents", default=None, help="Optional agents file path")
    parser.add_argument("-o", "--output", default="seed.md",
                        help="Output path (default: seed.md at project root)")
    args = parser.parse_args()

    args.output = resolve_path(args.output)
    base = args.base_url
    day = args.day
    n = args.days

    print("gen_seed — Flux API → seed.md (BTC Futures)")
    print(f"  Base URL : {base}")
    print(f"  Day      : {day}  ({n} days)")
    print(f"  Output   : {args.output}")
    print()

    # Build day list oldest → newest
    days = [offset_day(day, -(n - 1 - i)) for i in range(n)]
    _, end_ms = day_bounds_ms(day)

    # Fetch OHLCV
    items_1d, items_4h, items_1h = [], [], []
    for d in days:
        print(f"  OHLCV 1D  {d} ...", end=" ", flush=True)
        chunk = fetch_ohlcv(base, "1d", d)
        items_1d += chunk
        print(len(chunk))

        print(f"  OHLCV 4H  {d} ...", end=" ", flush=True)
        chunk = fetch_ohlcv(base, "4h", d)
        items_4h += chunk
        print(len(chunk))

        print(f"  OHLCV 1H  {d} ...", end=" ", flush=True)
        chunk = fetch_ohlcv(base, "1h", d)
        items_1h += chunk
        print(len(chunk))

    # Fetch liquidations (4 fixed windows relative to end of --day)
    liq_windows = {"1h": 3_600_000, "4h": 14_400_000, "12h": 43_200_000, "24h": 86_400_000}
    liq_data = {}
    for label, offset_ms in liq_windows.items():
        print(f"  Liq ({label:>3}) ...", end=" ", flush=True)
        liq_data[label] = fetch_liquidations(base, end_ms - offset_ms, end_ms)
        print(liq_data[label].get("count", 0), "events")

    # Fetch news over the full N-day window
    start_ms, _ = day_bounds_ms(days[0])
    print(f"  News {days[0]} → {day} ...", end=" ", flush=True)
    news_items = fetch_news(base, start_ms, end_ms)
    print(len(news_items), "items")

    # Assemble seed
    content = "\n\n".join([
        format_ohlcv(items_1d, items_4h, items_1h),
        format_liquidations(liq_data),
        format_news(news_items),
        "# Agents Population\n" + load_agents(args.agents),
    ]) + "\n"

    with open(args.output, "w") as f:
        f.write(content)

    print(f"\nWritten: {args.output}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify all tests still pass**

```bash
cd /mnt/second_disk/Code/flux/flux-MiroFish
python -m pytest backend/scripts/test_gen_seed.py -v 2>&1 | tail -5
```

Expected: `21 passed`

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/gen_seed.py
git commit -m "feat(gen_seed): add API fetchers, agents loader, and main()"
```

---

## Task 5: Smoke test against live API

- [ ] **Step 1: Verify the API is reachable**

```bash
curl -s "http://localhost:8080/api/v1/history/ohlcv?bucket=1d&day=2026-04-06&start=1743897600000&end=1743983999999" | python3 -m json.tool | head -15
```

Expected: JSON with an `"items"` array. If you get `Connection refused`, start the Flux exchange service first.

- [ ] **Step 2: Run gen_seed for 2026-04-06, 3 days**

```bash
cd /mnt/second_disk/Code/flux/flux-MiroFish
python3 backend/scripts/gen_seed.py --day 2026-04-06 --days 3
```

Expected output (counts may vary):
```
gen_seed — Flux API → seed.md (BTC Futures)
  Base URL : http://localhost:8080
  Day      : 2026-04-06  (3 days)
  Output   : /mnt/second_disk/Code/flux/flux-MiroFish/seed.md

  OHLCV 1D  2026-04-04 ... 1
  OHLCV 4H  2026-04-04 ... 6
  OHLCV 1H  2026-04-04 ... 24
  OHLCV 1D  2026-04-05 ... 1
  OHLCV 4H  2026-04-05 ... 6
  OHLCV 1H  2026-04-05 ... 24
  OHLCV 1D  2026-04-06 ... 1
  OHLCV 4H  2026-04-06 ... 6
  OHLCV 1H  2026-04-06 ... 24
  Liq ( 1h) ... N events
  Liq ( 4h) ... N events
  Liq (12h) ... N events
  Liq (24h) ... N events
  News 2026-04-04 → 2026-04-06 ... N items

Written: /mnt/second_disk/Code/flux/flux-MiroFish/seed.md
```

- [ ] **Step 3: Spot-check seed.md structure**

```bash
head -120 /mnt/second_disk/Code/flux/flux-MiroFish/seed.md
```

Verify all of:
- `# OHLCV` present
- `## 1H` with 72 rows, newest timestamp first
- `## 4H` with 18 rows, newest timestamp first
- `## 1D` with 3 rows, newest date first (2026-04-06 before 2026-04-04)
- `# Liquidations` table with rows for 1h / 4h / 12h / 24h
- `# News` table with `Time | News` header, newest first
- `# Agents Population` with 20 lines (15 traders + 5 KOLs)

- [ ] **Step 4: Commit generated seed**

```bash
git add seed.md
git commit -m "chore: regenerate seed.md from Flux API for 2026-04-06"
```

---

## Self-Review

### Spec Coverage

| Requirement | Task |
|-------------|------|
| Call Flux API for OHLCV (1d/4h/1h) | Task 4 `fetch_ohlcv` |
| Call Flux API for liquidations (1h/4h/12h/24h) | Task 4 `fetch_liquidations` |
| Call Flux API for news | Task 4 `fetch_news` |
| `--base-url` configurable | Task 4 `main()` |
| `--day` ending day | Task 4 `main()` |
| `--days N` scales OHLCV candles | Task 4 `main()` — N×1 / N×6 / N×24 |
| OHLCV tabular format `# OHLCV ## 1D ## 4H ## 1H` | Task 3 `format_ohlcv` |
| Liquidations table `Last \| Long liq \| Short liq` | Task 3 `format_liquidations` |
| News table `Time \| News` | Task 3 `format_news` |
| Newest-first sort for OHLCV and news | Task 3 (sort by `open_time_ms` / `timestamp_ms` desc) |
| 15 traders + 5 KOLs, style-only, no bias tag | Task 1 `agents.txt`, Task 4 `DEFAULT_AGENTS` |
| KOLs with very different follower counts | Task 1 (31K / 95K / 420K / 1.8M / 2.1M) |
| Remove all CSV dependencies | Tasks 2–4 (no pandas, no CSV imports) |

### Placeholder Scan
- No TBDs, no "add validation" stubs ✓
- All functions used in `main()` defined in earlier tasks ✓
- `day_bounds_ms` and `offset_day` defined in Task 2, used in Tasks 3 and 4 ✓

### Type Consistency
- `fetch_ohlcv` → `list[dict]` → `format_ohlcv(items_1d, items_4h, items_1h)` ✓
- `fetch_liquidations` → `dict` → `format_liquidations(liq_by_window)` where each value is a `dict` ✓
- `fetch_news` → `list[dict]` → `format_news(items)` ✓
- `_fmt_dollar` called in `format_liquidations` with string values from API response ✓
