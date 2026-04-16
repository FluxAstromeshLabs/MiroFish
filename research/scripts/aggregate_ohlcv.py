#!/usr/bin/env python3
"""Aggregate 1-minute OHLCV candles into larger timeframes.

Usage:
    python aggregate_ohlcv.py --start-date "2026-03-01 00:00:00" --end-date "2026-03-31 23:59:59" --interval 15m [-o output.csv]
    python aggregate_ohlcv.py --start-date "2026-03-01 09:30:00" --end-date "2026-03-31 16:00:00" --interval 4h -o sol_4h.csv

    python ./research/scripts/aggregate_ohlcv.py --start-date "2026-03-28 00:00:00" --end-date "2026-04-13 00:00:00" --interval 1h -o research/data/btc_1h.csv
"""

import argparse
import csv
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from calendar import monthrange


def parse_bucket(bucket: str) -> dict:
    """Parse bucket string like '15m', '4h', '1D', '1M' into components."""
    m = re.fullmatch(r"(\d+)([mhDM])", bucket)
    if not m:
        raise ValueError(f"Invalid bucket format: {bucket!r}. Use e.g. 15m, 4h, 1D, 1M")
    val, unit = int(m.group(1)), m.group(2)
    if unit == "m" and val < 1:
        raise ValueError("Bucket must be >= 1m")
    return {"value": val, "unit": unit}


def bucket_to_minutes(b: dict) -> int | None:
    """Return fixed bucket size in minutes, or None for month-based buckets."""
    if b["unit"] == "m":
        return b["value"]
    if b["unit"] == "h":
        return b["value"] * 60
    if b["unit"] == "D":
        return b["value"] * 1440
    return None  # month


def bucket_start_ms(ts_ms: int, bucket: dict) -> int:
    """Compute the bucket-start timestamp (ms) for a given candle timestamp."""
    unit, val = bucket["unit"], bucket["value"]

    if unit == "M":
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        # Floor to the start of the Nth month group
        # For 1M: floor to start of that month
        # For 3M: floor to start of quarter, etc.
        month_zero = (dt.year - 1970) * 12 + (dt.month - 1)
        floored = (month_zero // val) * val
        y, m = divmod(floored, 12)
        y += 1970
        m += 1
        return int(datetime(y, m, 1, tzinfo=timezone.utc).timestamp() * 1000)

    mins = bucket_to_minutes(bucket)
    period_ms = mins * 60_000
    return (ts_ms // period_ms) * period_ms


DATA_DIR = os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "exchange-connectors", "marketdata", "data", "binance", "btc", "formatted",
)


def load_candles(start_dt: datetime, end_dt: datetime) -> list[tuple]:
    """Load 1m candles from date-folder structure, filtered by [start_dt, end_dt]."""
    data_dir = os.path.normpath(DATA_DIR)
    d_start = start_dt.date()
    d_end = end_dt.date()
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    candles = []
    d = d_start
    while d <= d_end:
        folder = os.path.join(data_dir, d.strftime("%Y-%m-%d"))
        csv_path = os.path.join(folder, "ohlcv.csv")
        if os.path.isfile(csv_path):
            with open(csv_path, "r") as f:
                reader = csv.reader(f)
                next(reader)  # skip header
                for row in reader:
                    if len(row) < 6:
                        continue
                    t = int(row[0])
                    if t < start_ms or t > end_ms:
                        continue
                    o, h, l, c, v = (float(x) for x in row[1:6])
                    candles.append((t, o, h, l, c, v))
        d += timedelta(days=1)

    candles.sort(key=lambda x: x[0])
    return candles


def aggregate(candles: list[tuple], bucket: dict) -> list[tuple]:
    """Aggregate 1m candles into bucket-sized candles."""
    if not candles:
        return []

    result = []
    cur_key = None
    cur_o = cur_h = cur_l = cur_c = cur_v = 0.0
    cur_t = 0

    for t, o, h, l, c, v in candles:
        key = bucket_start_ms(t, bucket)
        if key != cur_key:
            if cur_key is not None:
                result.append((cur_t, cur_o, cur_h, cur_l, cur_c, cur_v))
            cur_key = key
            cur_t = key
            cur_o = o
            cur_h = h
            cur_l = l
            cur_c = c
            cur_v = v
        else:
            if h > cur_h:
                cur_h = h
            if l < cur_l:
                cur_l = l
            cur_c = c
            cur_v += v

    if cur_key is not None:
        result.append((cur_t, cur_o, cur_h, cur_l, cur_c, cur_v))

    return result


def main():
    parser = argparse.ArgumentParser(description="Aggregate 1m OHLCV into larger buckets")
    parser.add_argument("--start-date", required=True, help="Start UTC datetime (YYYY-MM-DD HH:MM:SS)")
    parser.add_argument("--end-date", required=True, help="End UTC datetime (YYYY-MM-DD HH:MM:SS)")
    parser.add_argument("--interval", required=True, help="Bucket size: e.g. 15m, 30m, 1h, 4h, 1D, 1M")
    parser.add_argument("-o", "--output", help="Output CSV path (default: stdout)")
    args = parser.parse_args()

    start_dt = datetime.strptime(args.start_date, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    end_dt = datetime.strptime(args.end_date, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    bucket = parse_bucket(args.interval)
    candles = load_candles(start_dt, end_dt)
    if not candles:
        print("No candles found in the given date range.", file=sys.stderr)
        sys.exit(1)

    agg = aggregate(candles, bucket)

    out = open(args.output, "w", newline="") if args.output else sys.stdout
    writer = csv.writer(out)
    writer.writerow(["T", "O", "H", "L", "C", "V"])
    for t, o, h, l, c, v in agg:
        writer.writerow([t, f"{o:.8f}", f"{h:.8f}", f"{l:.8f}", f"{c:.8f}", f"{v:.8f}"])

    if args.output:
        out.close()
        print(f"Wrote {len(agg)} candles to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
