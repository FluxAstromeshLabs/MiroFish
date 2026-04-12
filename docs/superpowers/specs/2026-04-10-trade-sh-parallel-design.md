# trade.sh Parallel Execution Refactor — Design Specification

## Overview

Refactor `trade.sh` to execute multiple seed files in parallel (3 at a time), with simplified command-line interface. Single timestamped output CSV in `price_predict/` accumulates all results with per-seed runtime metrics. Total elapsed time reported as max of the 3 parallel job times.

## Usage

```bash
./trade.sh START_HOUR [SEEDS_DIR]

# Examples:
./trade.sh 2026-04-05T01              # Uses default seeds/ directory
./trade.sh 2026-04-05T01 /custom/dir  # Custom seeds directory
```

### Parameters
- **START_HOUR** (required): Hour to begin processing seeds (format: `YYYY-MM-DDTHH`)
- **SEEDS_DIR** (optional, default `seeds/`): Directory containing seed files

## Output Structure

### CSV File Location
`price_predict/<YYYY-MM-DD-HH-MM-SS>.csv`

The filename is generated at script start time using the current date/time.

### CSV Columns
- `latest_chart_time`: Timestamp from seed file
- `predicted_low`: Lower price prediction
- `predicted_high`: Upper price prediction
- `actual_low`: Actual low price (if provided)
- `actual_high`: Actual high price (if provided)
- `agent_count`: Number of agents in simulation
- `simulation_rounds`: Number of simulation rounds executed
- `runtime`: Individual seed runtime in minutes (float, e.g., 2.5)

### Console Output

After each batch of 3 parallel jobs completes:
```
[1] 2026-04-05T01 — running prediction... ✓ (2.5 mins)
[2] 2026-04-05T02 — running prediction... ✓ (2.3 mins)
[3] 2026-04-05T03 — running prediction... ✓ (2.4 mins)

Total runtime: 2.5 mins (max of 3 parallel)
Range hit rate: 2/3 (66.67%)
```

## Behavior

### Parallel Execution

1. Collect all seed files matching the pattern starting from `START_HOUR`
2. Launch `run_trade.py` in background for exactly 3 seeds simultaneously
3. Track start/end time for each job independently
4. Each job writes one row to the shared timestamped CSV
5. Wait for all 3 jobs to complete before processing the next batch
6. Total elapsed time = `max(job1_time, job2_time, job3_time)` for each batch

### CSV Output

- Create `price_predict/` directory if it does not exist
- Generate filename once at script start: `$(date +%Y-%m-%d-%H-%M-%S).csv`
- Pass this filename to all parallel `run_trade.py` instances via `-o` flag
- `run_trade.py` appends one row per execution (already append-mode)
- Each row must include the `runtime` field (in minutes)

### Scoring and Metrics

After all seed batches complete:
1. Run `calc_range_hit.py` once on the final CSV
2. Display hit rate (e.g., `2/3` or `66.67%`)
3. Report total runtime: the max of all parallel execution times across all batches
4. Exit with code 0 if all jobs succeed, 1 if any job fails

## Implementation Requirements

### Changes to `trade.sh`

- Simplify command-line parsing: keep `START_HOUR` and optional `SEEDS_DIR`
- Remove `--parallel` and `--rounds` flags (hardcode 3 workers, default 5 rounds)
- Add background job management to launch/wait for 3 parallel `run_trade.py` processes
- Track elapsed time for each job
- Create `price_predict/` directory
- Generate timestamped CSV filename and pass to all jobs
- After all jobs, call `calc_range_hit.py` once on the final CSV
- Print metrics to console and exit

### Changes to `run_trade.py`

- Accept runtime duration as a new column in CSV output
- Calculate elapsed time from start to end
- Include `runtime` (in minutes, as float) in the CSV row written via `write_csv()`

### No Changes Required

- `calc_range_hit.py`: Works as-is on the final CSV

## Error Handling

- If a seed file is missing, log and continue (or fail gracefully)
- If a `run_trade.py` job fails, capture error and report which seed failed
- If `calc_range_hit.py` fails, report and exit with error code
- Ensure output CSV is readable even if script is interrupted mid-execution

## Success Criteria

1. ✓ Run 3 seed files in parallel (not sequentially)
2. ✓ Simple CLI: just `START_HOUR` and optional `SEEDS_DIR`
3. ✓ Output CSV: `price_predict/<YYYY-MM-DD-HH-MM-SS>.csv` with `runtime` column
4. ✓ Total runtime = max of 3 parallel times (not sum)
5. ✓ Display per-seed runtime, total runtime, and range hit rate
6. ✓ Process multiple batches of 3 if >3 seeds exist
