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
