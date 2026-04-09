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


# ── Formatters ─────────────────────────────────────────────────────────────

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
