"""
gen_seed — Flux Exchange API → seed.md (BTC Futures)
Fetches OHLCV, liquidations, and news from the Flux exchange HTTP API,
then writes a structured Markdown seed file.
"""

import os
import argparse
from datetime import datetime, timezone, timedelta
import csv
import json

import requests

from common import project_root, resolve_path


# ── Time helpers ───────────────────────────────────────────────────────────

def hour_bounds_ms(dt: datetime):
    """Return (start_ms, end_ms) for a UTC hour (inclusive ms)."""
    floored = dt.replace(minute=0, second=0, microsecond=0)
    start = int(floored.timestamp() * 1000)
    end = int((floored + timedelta(hours=1)).timestamp() * 1000) - 1
    return start, end


def parse_hour(hour_str: str) -> datetime:
    """Parse YYYY-MM-DDTHH or YYYY-MM-DD HH into a UTC datetime."""
    for fmt in ("%Y-%m-%dT%H", "%Y-%m-%d %H"):
        try:
            return datetime.strptime(hour_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    raise ValueError(f"Cannot parse hour: {hour_str!r}  (expected YYYY-MM-DDTHH)")


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
    Build the # OHLCV section with ## 1H, ## 4H, ## 1D subsections.
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


# ── API fetchers ───────────────────────────────────────────────────────────

def fetch_ohlcv(base_url, bucket, start_ms, end_ms):
    """
    GET /api/v1/history/ohlcv?bucket=<bucket>&start=<ms>&end=<ms>
    Returns list of item dicts with open_time_ms, open, high, low, close, volume.
    """
    resp = requests.get(
        f"{base_url}/api/v1/history/ohlcv",
        params={"bucket": bucket, "start": start_ms, "end": end_ms},
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
    _now = datetime.now(tz=timezone.utc)
    _default_hour = _now.strftime("%Y-%m-%dT%H")

    parser = argparse.ArgumentParser(description="gen_seed — Flux API → seed.md (BTC Futures)")
    parser.add_argument("--base-url", default="http://localhost:8080",
                        help="Flux exchange base URL (default: http://localhost:8080)")
    parser.add_argument("--hour", default=_default_hour,
                        help="Ending hour YYYY-MM-DDTHH in UTC (default: current hour)")
    parser.add_argument("--hours", type=int, default=72,
                        help="Hours of history to include (default: 72)")
    parser.add_argument("--agents", default=None, help="Optional agents file path")
    parser.add_argument("-o", "--output", default="seed.md",
                        help="Output path (default: seed.md at project root)")
    args = parser.parse_args()

    args.output = resolve_path(args.output)
    base = args.base_url
    end_dt = parse_hour(args.hour)
    n = args.hours

    _, end_ms = hour_bounds_ms(end_dt)
    start_dt = end_dt - timedelta(hours=n - 1)
    start_ms, _ = hour_bounds_ms(start_dt)

    print("gen_seed — Flux API → seed.md (BTC Futures)")
    print(f"  Base URL : {base}")
    print(f"  Hour     : {args.hour}  ({n} hours)")
    print(f"  Output   : {args.output}")
    print()

    # Fetch OHLCV for the full window in one call per bucket
    print(f"  OHLCV 1D ...", end=" ", flush=True)
    items_1d = fetch_ohlcv(base, "1d", start_ms, end_ms)
    print(len(items_1d))

    print(f"  OHLCV 4H ...", end=" ", flush=True)
    items_4h = fetch_ohlcv(base, "4h", start_ms, end_ms)
    print(len(items_4h))

    print(f"  OHLCV 1H ...", end=" ", flush=True)
    items_1h = fetch_ohlcv(base, "1h", start_ms, end_ms)
    print(len(items_1h))

    # Fetch liquidations (4 fixed windows relative to end hour)
    liq_windows = {"1h": 3_600_000, "4h": 14_400_000, "12h": 43_200_000, "24h": 86_400_000}
    liq_data = {}
    for label, offset_ms in liq_windows.items():
        liq_data[label] = fetch_liquidations(base, end_ms - offset_ms, end_ms)

    # Fetch news over the full N-hour window
    print(f"  News {start_dt.strftime('%Y-%m-%dT%H')} → {args.hour} ...", end=" ", flush=True)
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
