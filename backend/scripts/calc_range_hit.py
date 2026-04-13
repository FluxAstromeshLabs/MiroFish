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
        return None, None

    hit = actual_low >= predicted_low and actual_high <= predicted_high
    if hit:
        low_overshoot = max(0.0, actual_low - predicted_low)
        high_overshoot = max(0.0, predicted_high - actual_high)
        loss = low_overshoot + high_overshoot
    else:
        loss = None

    return hit, loss


def main():
    parser = argparse.ArgumentParser(description="Calculate range-hit metric from CSV")
    parser.add_argument("csv_file", help="Path to forecast CSV")
    args = parser.parse_args()

    if not os.path.exists(args.csv_file):
        print(f"Error: CSV file not found: {args.csv_file}")
        sys.exit(1)

    # Read raw lines to separate header, data rows, and trailing summary lines
    with open(args.csv_file, newline="", encoding="utf-8") as f:
        raw_lines = f.readlines()

    if not raw_lines:
        print("No rows found in CSV")
        sys.exit(1)

    header_line = raw_lines[0]
    fieldnames = [f.strip() for f in header_line.split(",")]

    # Separate data rows (have same column count as header) from summary lines
    data_lines = []
    summary_lines = []
    for line in raw_lines[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        cols = stripped.split(",")
        if len(cols) == len(fieldnames):
            data_lines.append(line)
        else:
            summary_lines.append(line)

    # Parse data rows
    rows = list(csv.DictReader(data_lines, fieldnames=fieldnames))

    if not rows:
        print("No data rows found in CSV")
        sys.exit(1)

    evaluated = 0
    hits = 0
    loss_values = []
    results = []

    for row in rows:
        hit, loss = evaluate_row(row)
        results.append((row, hit, loss))
        if hit is None:
            continue
        evaluated += 1
        if hit:
            hits += 1
        if loss is not None:
            loss_values.append(loss)

    avg_loss = sum(loss_values) / len(loss_values) if loss_values else None

    # Build output fieldnames: insert 'loss' after 'runtime' if present, else append
    out_fields = list(fieldnames)
    if "loss" not in out_fields:
        if "runtime" in out_fields:
            idx = out_fields.index("runtime")
            out_fields.insert(idx + 1, "loss")
        else:
            out_fields.append("loss")

    # Write updated CSV
    with open(args.csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=out_fields, extrasaction="ignore")
        writer.writeheader()
        for row, hit, loss in results:
            row["loss"] = "" if (hit is None or loss is None) else loss
            writer.writerow(row)

        # Append summary lines (only those with correct metadata format)
        f.write("\n")
        for line in summary_lines:
            cols = line.strip().split(",")
            # Only keep lines with exactly 2 columns (e.g., "key,value")
            if len(cols) == 2:
                f.write(line)
        if avg_loss is not None:
            f.write(f"avg_loss,{avg_loss:.4f}\n")
        else:
            f.write("avg_loss,\n")

    print(f"evaluated_rows={evaluated}")
    print(f"range_hits={hits}")
    if evaluated > 0:
        print(f"hit_rate={hits/evaluated:.6f}")
    else:
        print("hit_rate=NA")
    if avg_loss is not None:
        print(f"avg_loss={avg_loss:.4f}")
    else:
        print("avg_loss=NA")


if __name__ == "__main__":
    main()
