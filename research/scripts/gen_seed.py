"""
gen_seed — Generate seed (.md) + label (.json) pairs from OHLCV and tweet data.

Usage:
        python3 research/scripts/gen_seed.py --start-date "2026-04-02 00:00:00" --end-date "2026-04-07 23:00:00" --limit 24 --interval 1h
        python3 research/scripts/gen_seed.py --start-date "2026-04-02 00:00:00" --end-date "2026-04-07 23:00:00" --limit 48 --interval 30m

Outputs per candle t:
    research/data/seeds/YYYY-MM-DD/.../*.md   — candles up to t + tweets
    research/data/seeds/YYYY-MM-DD/.../*-label.json — t+1 candle (the label)
"""

import argparse
import csv
import json
import os
import re
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from common import project_root

load_dotenv()


def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_agents(agents_path=None) -> list[dict]:
    if agents_path and os.path.exists(agents_path):
        with open(agents_path, encoding="utf-8") as f:
            return json.load(f)
    default = os.path.join(project_root, "research", "data", "agents.json")
    legacy_default = os.path.join(project_root, "research", "agents.json")
    if os.path.exists(default):
        with open(default, encoding="utf-8") as f:
            return json.load(f)
    if os.path.exists(legacy_default):
        with open(legacy_default, encoding="utf-8") as f:
            return json.load(f)
    return []


def parse_interval(interval: str) -> tuple[timedelta, str]:
    """Parse '1h', '30m', '2h', '1d' → (timedelta, suffix_for_filename)."""
    import re
    m = re.fullmatch(r"(\d+)([dhm])", interval.strip().lower())
    if not m:
        raise ValueError(f"Invalid interval '{interval}'. Use e.g. 1h, 30m, 1d, 2h")
    n, unit = int(m.group(1)), m.group(2)
    if unit == "h":
        return timedelta(hours=n), interval
    elif unit == "d":
        return timedelta(days=n), interval
    elif unit == "m":
        return timedelta(minutes=n), interval
    raise ValueError(f"Unknown unit '{unit}'")


def parse_dt(raw: str) -> datetime:
    """Parse datetime from either YYYY-MM-DD HH:MM:SS or YYYY-MM-DD-HH-MM."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d-%H-%M"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Invalid datetime '{raw}'. Use YYYY-MM-DD HH:MM:SS")


def floor_to_interval(dt: datetime, delta: timedelta) -> datetime:
    """Floor dt down to the nearest delta boundary in UTC."""
    seconds = int(delta.total_seconds())
    floored = int(dt.timestamp()) // seconds * seconds
    return datetime.fromtimestamp(floored, tz=timezone.utc)


def interval_to_minutes(interval: str) -> int:
    m = re.fullmatch(r"(\d+)([mhd])", interval.strip().lower())
    if not m:
        raise ValueError(f"Invalid interval '{interval}'. Use e.g. 1h, 30m, 1d")
    n, unit = int(m.group(1)), m.group(2)
    if unit == "m":
        return n
    if unit == "h":
        return n * 60
    return n * 1440


def default_ohlcv_path(interval: str) -> str:
    interval_key = interval.strip().lower()
    candidates = [
        os.path.join(project_root, "research", "data", f"ohlcv_{interval_key}.csv"),
        os.path.join(project_root, "research", "data", f"btc_{interval_key}.csv"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]


def load_ohlcv_csv(path: str, interval: str) -> dict[str, dict]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"OHLCV CSV not found: {path}")

    expected_step = interval_to_minutes(interval)
    candle_map: dict[str, dict] = {}
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row:
                continue
            t_raw = row.get("T")
            if not t_raw:
                continue
            try:
                ts = int(t_raw)
            except ValueError:
                continue

            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            key = dt.strftime("%Y-%m-%d %H:%M")
            candle_map[key] = {
                "time": key,
                "open": float(row.get("O", 0) or 0),
                "high": float(row.get("H", 0) or 0),
                "low": float(row.get("L", 0) or 0),
                "close": float(row.get("C", 0) or 0),
                "volume": float(row.get("V", 0) or 0),
                "interval": f"{expected_step}m",
            }
    return candle_map


def load_tweets_csv(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []

    tweets: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row:
                continue
            created_at = (row.get("timestamp") or "").strip()
            text = (row.get("tweet") or "").strip()
            if not created_at or not text:
                continue
            tweets.append({"createdAt": created_at, "text": text})
    return tweets


def format_ohlcv(candles: list[dict], interval: str) -> str:
    items = [json.dumps(c, separators=(',', ': ')) for c in candles]
    return f"# OHLCV {interval.upper()}\n[\n  " + ",\n  ".join(items) + "\n]"


def format_tweets(tweets: list[dict], up_to: datetime, tweet_limit: int) -> str:
    cutoff = up_to.strftime("%Y-%m-%dT%H:%M")
    filtered = [t for t in tweets if t.get("createdAt", "") <= cutoff]
    filtered = sorted(filtered, key=lambda t: t.get("createdAt", ""), reverse=True)[:tweet_limit]
    filtered = sorted(filtered, key=lambda t: t.get("createdAt", ""))
    items = [
        {"tweet": t["text"], "createdAt": t.get("createdAt", "")}
        for t in filtered
    ]
    return "# X Tweets\n" + json.dumps(items, ensure_ascii=False, indent=2)


def format_agents(agents: list[dict]) -> str:
    return "# Agents Population\n" + json.dumps(agents, ensure_ascii=False, indent=2)


def generate(
    start_date: str,
    end_date: str,
    interval: str = "1h",
    limit: int = 24,
    agents_path: str = None,
    output_dir: str = None,
    ohlcv_file: str = None,
    tweets_file: str = None,
    tweet_limit: int = 5,
    agents_limit: int = 0,
    roll_step: str = None,
) -> int:
    """Generate seed/label pairs. Returns count of pairs written."""
    start_dt = parse_dt(start_date)
    end_dt = parse_dt(end_date)
    delta, interval_label = parse_interval(interval)
    step_delta = parse_interval(roll_step)[0] if roll_step else delta

    out_dir = os.path.join(project_root, output_dir or os.path.join("research", "data", "seeds"))
    os.makedirs(out_dir, exist_ok=True)

    ohlcv_path = os.path.join(project_root, ohlcv_file) if ohlcv_file else default_ohlcv_path(interval_label)
    tweets_path = os.path.join(project_root, tweets_file) if tweets_file else os.path.join(project_root, "research", "data", "tweets.csv")

    agents = load_agents(agents_path)
    if agents_limit > 0:
        agents = agents[:agents_limit]

    candle_map = load_ohlcv_csv(ohlcv_path, interval_label)
    all_tweets = load_tweets_csv(tweets_path)

    count = 0

    cur = start_dt
    while cur <= end_dt:
        latest_dt = floor_to_interval(cur, step_delta)
        time_str = latest_dt.strftime("%Y-%m-%d %H:%M")
        t1_str = (latest_dt + step_delta).strftime("%Y-%m-%d %H:%M")

        if time_str not in candle_map or t1_str not in candle_map:
            cur += step_delta
            continue

        # Keep candle interval spacing (e.g. 4h) while rolling seed timestamps (e.g. 1h).
        needed_times = [
            (latest_dt - delta * i).strftime("%Y-%m-%d %H:%M")
            for i in range(limit - 1, -1, -1)
        ]
        if any(t not in candle_map for t in needed_times):
            cur += step_delta
            continue

        window = [candle_map[t] for t in needed_times]
        day_tweets = all_tweets

        agent_count = len(agents)
        day_dir = os.path.join(out_dir, cur.strftime("%Y-%m-%d"))
        os.makedirs(day_dir, exist_ok=True)
        fname_base = f"{cur.strftime('%Y-%m-%d-%H-%M')}-{interval_label}-{limit}-{tweet_limit}-{agent_count}"
        seed_path = os.path.join(day_dir, f"{fname_base}.md")
        label_path = os.path.join(day_dir, f"{cur.strftime('%Y-%m-%d-%H-%M')}-{interval_label}-label.json")

        seed_content = "\n\n".join([
            format_agents(agents),
            f"# Latest Chart Time\n{cur.strftime('%Y-%m-%d %H:%M')}",
            f"# Latest BTC Price\n{candle_map[time_str]['close']}",
            format_ohlcv(window, interval_label),
            format_tweets(day_tweets, cur, tweet_limit),
        ]) + "\n"

        with open(seed_path, "w", encoding="utf-8") as f:
            f.write(seed_content)

        with open(label_path, "w", encoding="utf-8") as f:
            json.dump(candle_map[t1_str], f, ensure_ascii=False, indent=2)

        count += 1
        cur += step_delta

    print(f"Generated {count} seed/label pairs → {out_dir}")
    return count


def main():
    parser = argparse.ArgumentParser(description="Generate seed/label pairs from OHLCV + tweets")
    parser.add_argument("--start-date", default=os.getenv("SEED_START_DATE"), help="Start candle time YYYY-MM-DD HH:MM:SS")
    parser.add_argument("--end-date", default=os.getenv("SEED_END_DATE"), help="End candle time YYYY-MM-DD HH:MM:SS")
    parser.add_argument("--limit", type=int, default=int(os.getenv("LIMIT", "24")), help="Candles per seed window")
    parser.add_argument("--interval", default=os.getenv("INTERVAL", "1h"), help="Candle interval e.g. 1h, 30m, 1d, 2h")
    parser.add_argument("--roll-step", default=None,
                        help="Seed rolling step e.g. 1h. Default follows --interval")
    parser.add_argument(
        "--agents",
        default=os.path.join("research", "data", "agents.json"),
        help="Path to agents JSON (default: research/data/agents.json)",
    )
    parser.add_argument("--ohlcv-file", default=None, help="OHLCV CSV path (default: research/data/ohlcv_{interval}.csv)")
    parser.add_argument("--tweets-file", default=None, help="Tweets CSV path (default: research/data/tweets.csv)")
    parser.add_argument("-o", "--output", dest="output_dir", default=os.path.join("research", "data", "seeds"), help="Output directory (default: research/data/seeds)")
    args = parser.parse_args()

    if not args.start_date or not args.end_date:
        raise ValueError("--start-date and --end-date (or env vars) are required")

    generate(
        start_date=args.start_date,
        end_date=args.end_date,
        interval=args.interval,
        limit=args.limit,
        agents_path=args.agents,
        ohlcv_file=args.ohlcv_file,
        tweets_file=args.tweets_file,
        output_dir=args.output_dir,
        tweet_limit=int(os.getenv("TWEET_LIMIT", "5")),
        agents_limit=int(os.getenv("AGENTS", "0")),
        roll_step=args.roll_step,
    )


if __name__ == "__main__":
    main()
