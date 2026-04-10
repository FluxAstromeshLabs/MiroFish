#!/usr/bin/env python3
"""Calculate range-hit metric from a forecast CSV.

Main metric:
Range hit = actual_low >= predicted_low AND actual_high <= predicted_high
"""

import argparse
import csv
import os
import sys


def parse_float(value):
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def evaluate_row(row):
    predicted_low = parse_float(row.get("predicted_low"))
    predicted_high = parse_float(row.get("predicted_high"))
    actual_low = parse_float(row.get("actual_low"))
    actual_high = parse_float(row.get("actual_high"))

    if None in (predicted_low, predicted_high, actual_low, actual_high):
        return None

    return actual_low >= predicted_low and actual_high <= predicted_high


def main():
    parser = argparse.ArgumentParser(description="Calculate range-hit metric from CSV")
    parser.add_argument("csv_file", help="Path to forecast CSV")
    args = parser.parse_args()

    if not os.path.exists(args.csv_file):
        print(f"Error: CSV file not found: {args.csv_file}")
        sys.exit(1)

    with open(args.csv_file, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print("No rows found in CSV")
        sys.exit(1)

    evaluated = 0
    hits = 0

    print("row,latest_chart_time,range_hit")
    for idx, row in enumerate(rows, start=1):
        result = evaluate_row(row)
        ts = row.get("latest_chart_time", "")

        if result is None:
            print(f"{idx},{ts},NA")
            continue

        evaluated += 1
        if result:
            hits += 1
        print(f"{idx},{ts},{int(result)}")

    print()
    print(f"evaluated_rows={evaluated}")
    print(f"range_hits={hits}")
    if evaluated > 0:
        hit_rate = hits / evaluated
        print(f"hit_rate={hit_rate:.6f}")
    else:
        print("hit_rate=NA")


if __name__ == "__main__":
    main()
