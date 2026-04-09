#!/usr/bin/env bash
# trade.sh — Backtest loop: gen_seed → run_trade (predict) → get actual → log → repeat
# Assumes Flask backend is already running in another terminal.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$ROOT/backend/.venv/bin/python3"
MARKETDATA_DIR="${2:-$ROOT/marketdata}"
OUTPUT_CSV="${3:-$ROOT/price_forecast.csv}"
START_HOUR="${1:-2026-04-05T01}"

trap 'echo ""; echo "Shutting down..."; exit 0' INT TERM

if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "Error: Python venv not found at $VENV_PYTHON"
    echo "Run: cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi

# Helper: extract price from seed JSON OHLCV
extract_price() {
    local seed_file=$1
    local field=$2  # "close", "open", "high", "low"
    python3 -c "
import json, re
with open('$seed_file') as f:
    text = f.read()
match = re.search(r'# OHLCV 1H\s*\[\s*\{([^}]+)\}', text)
if match:
    obj_str = '{' + match.group(1) + '}'
    obj = json.loads(obj_str)
    print(obj.get('$field', ''))
" 2>/dev/null || echo ""
}

# Parse YYYY-MM-DDTHH format into date/hour
current_hour="$START_HOUR"

echo ""
echo "=========================================="
echo "Trade Backtest Loop"
echo "Start: $current_hour"
echo "Marketdata: $MARKETDATA_DIR"
echo "Output CSV: $OUTPUT_CSV"
echo "=========================================="
echo ""

# Backtest loop
for i in {1..72}; do
    echo "--- Iteration $i: $current_hour ---"

    # Step 1: Generate seed for current hour
    seed_file="$ROOT/seeds/seed_${current_hour}.md"
    echo "  [1/4] Generating seed..."
    if ! "$VENV_PYTHON" "$ROOT/backend/scripts/gen_seed.py" \
        --end-hour "$current_hour" \
        --hours 72 \
        --marketdata "$MARKETDATA_DIR" \
        --output-dir "$ROOT/seeds" > /dev/null 2>&1; then
        echo "  ERROR: gen_seed.py failed for $current_hour"
        break
    fi

    if [[ ! -f "$seed_file" ]]; then
        echo "  ERROR: seed file not created: $seed_file"
        break
    fi

    # Step 2: Run MiroFish simulation + predict
    echo "  [2/4] Running MiroFish simulation..."
    if ! "$VENV_PYTHON" "$ROOT/backend/scripts/run_trade.py" \
        --predict-hours 1 \
        --base-url "http://localhost:5001" \
        --rounds 10 \
        -o "$OUTPUT_CSV" \
        "$seed_file" > /dev/null 2>&1; then
        echo "  WARNING: run_trade.py failed, continuing..."
    fi

    # Step 3: Extract actual prices from NEXT hour's seed
    next_hour=$(date -d "$(echo $current_hour | sed 's/T/ /') + 1 hour" +"%Y-%m-%dT%H" 2>/dev/null)
    if [[ -z "$next_hour" ]]; then
        echo "  WARNING: Could not calculate next hour, stopping"
        break
    fi

    next_seed="$ROOT/seeds/seed_${next_hour}.md"
    echo "  [3/4] Getting actual next candle prices..."
    "$VENV_PYTHON" "$ROOT/backend/scripts/gen_seed.py" \
        --end-hour "$next_hour" \
        --hours 72 \
        --marketdata "$MARKETDATA_DIR" \
        --output-dir "$ROOT/seeds" > /dev/null 2>&1

    if [[ -f "$next_seed" ]]; then
        actual_low=$(extract_price "$next_seed" "low")
        actual_high=$(extract_price "$next_seed" "high")
        echo "  [4/4] Logging: low=$actual_low, high=$actual_high"

        # Update CSV with actual prices (append new row with actuals)
        if [[ -n "$actual_low" && -n "$actual_high" ]]; then
            python3 << 'PYEOF'
import csv, os
csv_file = "$OUTPUT_CSV"
if os.path.exists(csv_file):
    with open(csv_file, 'r') as f:
        rows = list(csv.DictReader(f))
    if rows:
        last_row = rows[-1]
        last_row['actual_low'] = "$actual_low"
        last_row['actual_high'] = "$actual_high"
        with open(csv_file, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys())
            w.writeheader()
            w.writerows(rows)
PYEOF
        fi
    else
        echo "  WARNING: Next seed not found: $next_seed"
    fi

    # Step 5: Move to next hour
    current_hour="$next_hour"
    echo "  Done. Moving to $current_hour"
    echo ""

echo "=========================================="
echo "Backtest complete. Results: $OUTPUT_CSV"
echo "=========================================="
