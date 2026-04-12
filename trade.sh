#!/usr/bin/env bash
# trade.sh — Run MiroFish predictions over seed files in parallel, then score results.
# Usage: ./trade.sh START_HOUR [NUM_SEEDS] [SEEDS_DIR]
# Example: ./trade.sh 2026-04-05T01 3 seeds/
# NUM_SEEDS: how many seeds to run simultaneously (default 3)
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$ROOT/backend/.venv/bin/python3"
START_HOUR="${1:-}"
NUM_SEEDS="${2:-3}"
SEEDS_DIR="${3:-$ROOT/seeds}"
SIM_ROUNDS=5

trap 'echo ""; echo "Interrupted."; exit 0' INT TERM

# Validate required argument
if [[ -z "$START_HOUR" ]]; then
    echo "Usage: ./trade.sh START_HOUR [NUM_SEEDS] [SEEDS_DIR]"
    echo "Example: ./trade.sh 2026-04-05T01 3"
    exit 1
fi

if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "Error: Python venv not found at $VENV_PYTHON"
    exit 1
fi

# Create output directories
mkdir -p "$ROOT/price_predict"
mkdir -p "$ROOT/logs"

# Generate timestamped output filename (shared across CSV and log)
TIMESTAMP=$(date +"%Y-%m-%d-%H-%M-%S")
OUTPUT_CSV="$ROOT/price_predict/$TIMESTAMP.csv"
LOG_FILE="$ROOT/logs/$TIMESTAMP.log"

# Tee all output to log file
exec > >(tee -a "$LOG_FILE") 2>&1

echo "Trade loop | start=$START_HOUR | num_seeds=$NUM_SEEDS | seeds=$SEEDS_DIR | output=$OUTPUT_CSV"
echo ""

# Collect all seed files starting from START_HOUR
current_hour="$START_HOUR"
seed_files=()

for i in $(seq 1 "$NUM_SEEDS"); do
    seed_file="$SEEDS_DIR/seed_${current_hour}.md"

    if [[ ! -f "$seed_file" ]]; then
        break
    fi

    seed_files+=("$seed_file")

    next_hour=$(date -d "${current_hour/T/ } + 1 hour" +"%Y-%m-%dT%H" 2>/dev/null)
    if [[ -z "$next_hour" ]]; then
        break
    fi

    current_hour="$next_hour"
done

if [[ ${#seed_files[@]} -eq 0 ]]; then
    echo "No seed files found starting from $START_HOUR"
    exit 1
fi

echo "Found ${#seed_files[@]} seed files"
echo ""

# Track overall metrics
script_start=$(date +%s.%N)
all_failed=false
job_index=1

# Process seeds in batches of NUM_SEEDS
for ((i = 0; i < ${#seed_files[@]}; i += NUM_SEEDS)); do
    batch_pids=()
    batch_times=()
    batch_failed=false

    # Launch up to NUM_SEEDS jobs
    for ((j = 0; j < NUM_SEEDS && i + j < ${#seed_files[@]}; j++)); do
        seed_file="${seed_files[$((i + j))]}"
        job_num=$((job_index + j))
        hour=$(basename "$seed_file" .md | sed 's/seed_//')

        # Look up actual low/high from the next candle (seed_hour + 1h, all UTC)
        actual_args=()
        read actual_low actual_high < <(
            "$VENV_PYTHON" - "$hour" "$ROOT/marketdata" <<'PYEOF'
import sys, os, csv, datetime, calendar

hour_str = sys.argv[1]   # e.g. 2026-04-05T01
marketdata_dir = sys.argv[2]

dt = datetime.datetime.strptime(hour_str, "%Y-%m-%dT%H").replace(tzinfo=datetime.timezone.utc)
next_dt = dt + datetime.timedelta(hours=1)
next_day = next_dt.strftime("%Y-%m-%d")
next_hour_ms = int(next_dt.timestamp()) * 1000
next_hour_end_ms = next_hour_ms + 3_600_000

ohlcv_file = os.path.join(marketdata_dir, next_day, "ohlcv.csv")
lo, hi = None, None
if os.path.exists(ohlcv_file):
    with open(ohlcv_file) as f:
        for row in csv.DictReader(f):
            t = int(row["T"])
            if next_hour_ms <= t < next_hour_end_ms:
                l, h = float(row["L"]), float(row["H"])
                lo = l if lo is None else min(lo, l)
                hi = h if hi is None else max(hi, h)
print(lo if lo is not None else "", hi if hi is not None else "")
PYEOF
        )
        [[ -n "$actual_low" ]] && actual_args+=(--actual-low "$actual_low")
        [[ -n "$actual_high" ]] && actual_args+=(--actual-high "$actual_high")

        echo -n "[$job_num] $hour — running prediction..."

        # Run in background, capture start time
        job_start=$(date +%s.%N)
        "$VENV_PYTHON" "$ROOT/backend/scripts/run_trade.py" \
            -o "$OUTPUT_CSV" \
            --rounds "$SIM_ROUNDS" \
            "${actual_args[@]}" \
            "$seed_file" &

        batch_pids+=($!)
        batch_times+=("$job_start:$hour:$job_num")
    done

    # Wait for all jobs in this batch and collect runtimes
    batch_runtimes=()
    for ((j = 0; j < ${#batch_pids[@]}; j++)); do
        pid=${batch_pids[$j]}
        time_info="${batch_times[$j]}"
        job_start=$(echo "$time_info" | cut -d: -f1)
        hour=$(echo "$time_info" | cut -d: -f2)
        job_num=$(echo "$time_info" | cut -d: -f3)

        if wait $pid; then
            job_end=$(date +%s.%N)
            runtime_mins=$(awk "BEGIN {printf \"%.1f\", ($job_end - $job_start) / 60}")
            batch_runtimes+=("$runtime_mins")
            echo ""
            echo "[$job_num] $hour — ✓ ($runtime_mins mins)"
        else
            batch_failed=true
            all_failed=true
            echo ""
            echo "[$job_num] $hour — ✗ (failed)"
        fi
    done

    # Calculate and report batch max runtime
    if [[ ${#batch_runtimes[@]} -gt 0 ]]; then
        batch_max=$(printf '%s\n' "${batch_runtimes[@]}" | sort -n | tail -1)
        echo ""
        echo "Batch runtime: $batch_max mins (max of parallel jobs)"
        echo ""
    fi

    job_index=$((job_index + NUM_SEEDS))
done

# Calculate total script runtime
script_end=$(date +%s.%N)
script_total_mins=$(awk "BEGIN {printf \"%.1f\", ($script_end - $script_start) / 60}")

echo "Scoring results..."
score_output=$("$VENV_PYTHON" "$ROOT/backend/scripts/calc_range_hit.py" "$OUTPUT_CSV")
echo "$score_output"

hit_rate=$(echo "$score_output" | grep '^hit_rate=' | cut -d= -f2)

# Append summary to CSV
echo "" >> "$OUTPUT_CSV"
echo "total_runtime_mins,$script_total_mins" >> "$OUTPUT_CSV"
echo "hit_rate,${hit_rate:-NA}" >> "$OUTPUT_CSV"

echo ""
echo "Total runtime: $script_total_mins mins"

if [[ "$all_failed" == true ]]; then
    exit 1
fi

exit 0
