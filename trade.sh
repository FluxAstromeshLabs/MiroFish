#!/usr/bin/env bash
# trade.sh — Run MiroFish predictions over seed files in parallel (3 at a time), then score results.
# Usage: ./trade.sh START_HOUR [SEEDS_DIR]
# Example: ./trade.sh 2026-04-05T01 seeds/
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$ROOT/backend/.venv/bin/python3"
START_HOUR="${1:-}"
SEEDS_DIR="${2:-$ROOT/seeds}"
PARALLEL_WORKERS=3
SIM_ROUNDS=5

trap 'echo ""; echo "Interrupted."; exit 0' INT TERM

# Validate required argument
if [[ -z "$START_HOUR" ]]; then
    echo "Usage: ./trade.sh START_HOUR [SEEDS_DIR]"
    echo "Example: ./trade.sh 2026-04-05T01"
    exit 1
fi

if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "Error: Python venv not found at $VENV_PYTHON"
    exit 1
fi

# Create output directory
mkdir -p "$ROOT/price_predict"

# Generate timestamped output filename
TIMESTAMP=$(date +"%Y-%m-%d-%H-%M-%S")
OUTPUT_CSV="$ROOT/price_predict/$TIMESTAMP.csv"

echo "Trade loop | start=$START_HOUR | seeds=$SEEDS_DIR | output=$OUTPUT_CSV"
echo ""

# Collect all seed files starting from START_HOUR
current_hour="$START_HOUR"
seed_files=()

for i in {1..72}; do
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

# Process seeds in batches of PARALLEL_WORKERS
for ((i = 0; i < ${#seed_files[@]}; i += PARALLEL_WORKERS)); do
    batch_pids=()
    batch_times=()
    batch_failed=false

    # Launch up to PARALLEL_WORKERS jobs
    for ((j = 0; j < PARALLEL_WORKERS && i + j < ${#seed_files[@]}; j++)); do
        seed_file="${seed_files[$((i + j))]}"
        job_num=$((job_index + j))
        hour=$(basename "$seed_file" .md | sed 's/seed_//')

        echo -n "[$job_num] $hour — running prediction..."

        # Run in background, capture start time
        job_start=$(date +%s.%N)
        "$VENV_PYTHON" "$ROOT/backend/scripts/run_trade.py" \
            -o "$OUTPUT_CSV" \
            --rounds "$SIM_ROUNDS" \
            "$seed_file" > /dev/null 2>&1 &

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

    job_index=$((job_index + PARALLEL_WORKERS))
done

# Calculate total script runtime
script_end=$(date +%s.%N)
script_total_mins=$(awk "BEGIN {printf \"%.1f\", ($script_end - $script_start) / 60}")

echo "Scoring results..."
"$VENV_PYTHON" "$ROOT/backend/scripts/calc_range_hit.py" "$OUTPUT_CSV"

echo ""
echo "Total runtime: $script_total_mins mins"

if [[ "$all_failed" == true ]]; then
    exit 1
fi

exit 0
