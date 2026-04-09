#!/usr/bin/env bash
# trade.sh — Trade loop: run_trade (predict) → extract actual → log → repeat
# Seeds must be pre-generated in seeds/ directory
# Assumes Flask backend is already running in another terminal.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$ROOT/backend/.venv/bin/python3"
SEEDS_DIR="${2:-$ROOT/seeds}"
OUTPUT_CSV="${3:-$ROOT/price_forecast.csv}"
START_HOUR="${1:-2026-04-05T01}"
QUIET="${QUIET:-0}"
APPEND_MODE="${APPEND_MODE:-0}"
SCRIPT_START_TS=$(date +%s)

trap 'echo ""; echo "Shutting down..."; exit 0' INT TERM

if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "Error: Python venv not found at $VENV_PYTHON"
    echo "Run: cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi

# By default, always create a unique CSV per run.
# Set APPEND_MODE=1 to force writing into the exact OUTPUT_CSV path.
if [[ "$APPEND_MODE" != "1" ]]; then
    run_tag=$(date '+%Y%m%d_%H%M%S')
    if [[ "$OUTPUT_CSV" == *.csv ]]; then
        OUTPUT_CSV="${OUTPUT_CSV%.csv}_${run_tag}.csv"
    else
        OUTPUT_CSV="${OUTPUT_CSV}_${run_tag}.csv"
    fi
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
echo "Trade Loop"
echo "Started at: $(date '+%Y-%m-%d %H:%M:%S')"
echo "Start: $current_hour"
echo "Seeds dir: $SEEDS_DIR"
echo "Output CSV: $OUTPUT_CSV"
echo "=========================================="
echo ""

# Loop config: change {1..72} to desired number of iterations
for i in {1..72}; do
    iter_start_ts=$(date +%s)
    seed_file="$SEEDS_DIR/seed_${current_hour}.md"

    # Check if seed exists
    if [[ ! -f "$seed_file" ]]; then
        echo "ERROR: Seed not found: $seed_file"
        break
    fi

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] --- Iteration $i: $current_hour ---"

    # Step 1: Run MiroFish simulation + predict
    step1_start_ts=$(date +%s)
    echo "  [1/3] Running MiroFish simulation..."
    if [[ "$QUIET" == "1" ]]; then
        if ! "$VENV_PYTHON" "$ROOT/backend/scripts/run_trade.py" \
            --predict-hours 1 \
            --base-url "http://localhost:5001" \
            --rounds 10 \
            -o "$OUTPUT_CSV" \
            "$seed_file" > /dev/null 2>&1; then
            echo "  WARNING: run_trade.py failed, continuing..."
        fi
    else
        if ! "$VENV_PYTHON" "$ROOT/backend/scripts/run_trade.py" \
            --predict-hours 1 \
            --base-url "http://localhost:5001" \
            --rounds 10 \
            -o "$OUTPUT_CSV" \
            "$seed_file"; then
            echo "  WARNING: run_trade.py failed, continuing..."
        fi
    fi
    step1_elapsed=$(( $(date +%s) - step1_start_ts ))
    echo "  [1/3] Done in ${step1_elapsed}s"

    # Step 2: Extract actual prices from NEXT hour's seed
    next_hour=$(date -d "$(echo $current_hour | sed 's/T/ /') + 1 hour" +"%Y-%m-%dT%H" 2>/dev/null)
    if [[ -z "$next_hour" ]]; then
        echo "  WARNING: Could not calculate next hour, stopping"
        break
    fi

    next_seed="$SEEDS_DIR/seed_${next_hour}.md"
    if [[ ! -f "$next_seed" ]]; then
        echo "  WARNING: Next seed not found: $next_seed (end of loop)"
        break
    fi

    actual_low=$(extract_price "$next_seed" "low")
    actual_high=$(extract_price "$next_seed" "high")

    if [[ -n "$actual_low" && -n "$actual_high" ]]; then
        echo "  [2/3] Actual next candle: low=$actual_low, high=$actual_high"

        # Step 3: Update CSV with actual prices
        python3 << PYEOF
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
        print("  [3/3] Logged to CSV")
PYEOF
    else
        echo "  [2/3] WARNING: Could not extract prices from $next_seed"
    fi

    # Move to next hour
    current_hour="$next_hour"
    iter_elapsed=$(( $(date +%s) - iter_start_ts ))
    echo "  Iteration elapsed: ${iter_elapsed}s"
    echo ""
done

total_elapsed=$(( $(date +%s) - SCRIPT_START_TS ))
echo "=========================================="
echo "Finished at: $(date '+%Y-%m-%d %H:%M:%S')"
echo "Total elapsed: ${total_elapsed}s"
echo "Trade loop complete. Results: $OUTPUT_CSV"
echo "=========================================="
