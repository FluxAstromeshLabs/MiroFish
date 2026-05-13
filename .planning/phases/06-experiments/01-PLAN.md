---
phase: 06-experiments
plan: 01
type: execute
wave: 1
depends_on: [05-prediction/02-PLAN.md]
files_modified:
  - backend/experiments/run_experiment.py    # new
  - backend/experiments/analyze.py           # new
  - backend/app/services/simulation_manager.py  # add Zep graph cache (TTL 5min)
autonomous: true
must_haves:
  truths:
    - run_experiment.py runs N pipeline iterations with varying params, saves results to experiments/results.jsonl
    - analyze.py reads results.jsonl and prints which params correlate with prediction accuracy
    - Zep graph fetch is cached (TTL 5min) in simulation_manager.py:389-394 to speed up repeated prepares
  artifacts:
    - backend/experiments/run_experiment.py
    - backend/experiments/analyze.py
    - Zep cache TTL in simulation_manager.py
  key_links:
    - simulation_manager.py:389-394 — parallel profile+config generation (Zep fetch inside here)
    - run_pipeline.py: the CLI script this calls (Phase 2 Plan 02)
    - Backtester.score_candles(): backtester.py (Phase 5 Plan 02)
---

<objective>
Find what moves the prediction needle. Run controlled experiments, log results, analyze correlations.
Phuc's ask: "change agent numbers, number of news etc to see what impacts the prediction"
Output: Two scripts. One caches Zep to speed up iteration.
</objective>

<context>
@.planning/ROADMAP.md
@backend/scripts/run_pipeline.py
@backend/app/services/simulation_manager.py
</context>

<tasks>

<task type="auto">
  <name>Task 6.1: Create run_experiment.py</name>
  <files>backend/experiments/run_experiment.py</files>
  <action>
Create backend/experiments/run_experiment.py:

```python
#!/usr/bin/env python3
"""
Run parameterized MiroFish experiments and log results.

Usage:
    python backend/experiments/run_experiment.py \\
        --project-id <pid> \\
        --simulation-id <sid> \\
        --ohlcv-file data/actual.csv \\
        --agent-counts 10,25,50 \\
        --rounds 10 \\
        --asset BTC \\
        --open-price 95000
"""
import argparse, json, os, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

RESULTS_FILE = Path(__file__).parent / "results.jsonl"


def run_one(args, agent_count: int, rounds: int) -> dict:
    """Run one pipeline iteration and return result dict."""
    env = os.environ.copy()
    env["SIMULATION_AGENT_COUNT"] = str(agent_count)

    cmd = [
        sys.executable, "backend/scripts/run_pipeline.py",
        "--project-id", args.project_id,
        "--simulation-id", args.simulation_id,
        "--rounds", str(rounds),
        "--host", args.host,
    ]

    print(f"\n[experiment] agent_count={agent_count} rounds={rounds}")
    t0 = time.time()

    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    elapsed = round(time.time() - t0, 1)

    if result.returncode != 0:
        print(f"[experiment] Pipeline failed:\n{result.stderr}")
        return {
            "status": "failed",
            "error": result.stderr[-500:],
            "agent_count": agent_count,
            "rounds": rounds,
        }

    # Call backtest endpoint
    import requests
    base = args.host
    with open(args.ohlcv_file) as f:
        csv_text = f.read()

    r = requests.post(f"{base}/api/pipeline/backtest", json={
        "simulation_id": args.simulation_id,
        "csv_text": csv_text,
        "asset": args.asset,
        "open_price": args.open_price,
    }, timeout=120)
    bt = r.json()

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent_count": agent_count,
        "rounds": rounds,
        "asset": args.asset,
        "elapsed_s": elapsed,
        "status": "ok" if bt.get("success") else "backtest_failed",
    }
    if bt.get("success"):
        d = bt["data"]
        record.update({
            "prediction_low": d.get("prediction_low"),
            "prediction_high": d.get("prediction_high"),
            "pct_in_range": d.get("pct_in_range"),
            "max_deviation_pct": d.get("max_deviation_pct"),
            "direction_correct": d.get("direction_correct"),
            "grade": d.get("grade"),
            "summary": d.get("summary"),
        })
        print(f"[experiment] {d.get('summary')}")
    else:
        record["error"] = bt.get("error")

    return record


def main():
    parser = argparse.ArgumentParser(description="Run MiroFish experiments")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--simulation-id", required=True)
    parser.add_argument("--ohlcv-file", required=True)
    parser.add_argument("--agent-counts", default="10,25,50",
                        help="Comma-separated list of agent counts to test")
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--asset", default="BTC")
    parser.add_argument("--open-price", type=float, default=0.0)
    parser.add_argument("--host", default="http://localhost:5001")
    args = parser.parse_args()

    counts = [int(x.strip()) for x in args.agent_counts.split(",")]
    print(f"[experiment] Running {len(counts)} experiments: agent_counts={counts}")

    for count in counts:
        record = run_one(args, count, args.rounds)
        with open(RESULTS_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")
        print(f"[experiment] Logged to {RESULTS_FILE}")

    print(f"\n[experiment] Done. Run analyze.py to see results.")


if __name__ == "__main__":
    main()
```
  </action>
  <verify>
python3 backend/experiments/run_experiment.py --help
# Expected: shows usage with --agent-counts, --rounds, --ohlcv-file
  </verify>
  <done>run_experiment.py runs pipeline N times with varying params and logs to results.jsonl.</done>
</task>

<task type="auto">
  <name>Task 6.2: Create analyze.py</name>
  <files>backend/experiments/analyze.py</files>
  <action>
Create backend/experiments/analyze.py:

```python
#!/usr/bin/env python3
"""
Analyze experiment results from results.jsonl.
Prints a table showing which params correlate with prediction accuracy.

Usage:
    python backend/experiments/analyze.py [--file backend/experiments/results.jsonl]
"""
import argparse, json
from pathlib import Path
from collections import defaultdict

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default=str(Path(__file__).parent / "results.jsonl"))
    args = parser.parse_args()

    records = []
    with open(args.file) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    if not records:
        print("No results found.")
        return

    print(f"\n{'='*70}")
    print(f"MiroFish Experiment Results — {len(records)} runs")
    print(f"{'='*70}")
    print(f"{'Agent Count':>12} {'Rounds':>7} {'Grade':>6} {'In Range%':>10} {'Dir OK':>7} {'Time(s)':>8}")
    print(f"{'-'*70}")

    for r in records:
        if r.get("status") != "ok":
            print(f"{'':>12} {'':>7} {'FAIL':>6}  {r.get('error','')[:30]}")
            continue
        print(
            f"{r.get('agent_count','?'):>12} "
            f"{r.get('rounds','?'):>7} "
            f"{r.get('grade','?'):>6} "
            f"{r.get('pct_in_range', 0):>9.1f}% "
            f"{'Yes' if r.get('direction_correct') else 'No':>7} "
            f"{r.get('elapsed_s', 0):>8.1f}"
        )

    # Group by agent_count and compute average grade score
    print(f"\n{'='*70}")
    print("Average in-range % by agent count:")
    by_count = defaultdict(list)
    for r in records:
        if r.get("status") == "ok" and r.get("pct_in_range") is not None:
            by_count[r["agent_count"]].append(r["pct_in_range"])

    for count in sorted(by_count):
        vals = by_count[count]
        avg = sum(vals) / len(vals)
        print(f"  {count:>3} agents: {avg:>5.1f}% avg in-range ({len(vals)} run(s))")

    print()


if __name__ == "__main__":
    main()
```
  </action>
  <verify>
python3 backend/experiments/analyze.py --help
# Expected: shows --file flag
  </verify>
  <done>analyze.py reads results.jsonl and prints table of agent_count vs prediction accuracy.</done>
</task>

<task type="auto">
  <name>Task 6.3: Cache Zep graph fetch in simulation_manager.py</name>
  <files>backend/app/services/simulation_manager.py</files>
  <action>
At simulation_manager.py:389-394, the `ThreadPoolExecutor` runs `_generate_profiles()` and
`_generate_config()` concurrently. Both call Zep to fetch the graph. Add a simple TTL cache.

At the top of SimulationManager class (after `__init__` attributes), add:
```python
    # Zep graph fetch cache: {graph_id: (fetched_at_unix, data)}
    _zep_cache: dict = {}
    ZEP_CACHE_TTL = 300  # 5 minutes
```

Find the method that fetches from Zep (likely named `_fetch_graph_entities()` or similar —
search for `self.client.graph.search` or `zep_client.graph`). Wrap it:

```python
    def _fetch_graph_cached(self, graph_id: str, **kwargs):
        import time
        now = time.time()
        cached = self._zep_cache.get(graph_id)
        if cached and (now - cached[0]) < self.ZEP_CACHE_TTL:
            return cached[1]
        result = self._fetch_graph(graph_id, **kwargs)  # original fetch call
        self._zep_cache[graph_id] = (now, result)
        return result
```

Then replace calls to `_fetch_graph(graph_id)` with `_fetch_graph_cached(graph_id)`.

**Note:** If the Zep fetch is inline rather than a separate method, extract it to `_fetch_graph()`
first, then wrap. Check the actual method name at lines 389-394 before editing.
  </action>
  <verify>
grep -n "ZEP_CACHE_TTL\|_zep_cache\|_fetch_graph_cached" backend/app/services/simulation_manager.py
# Expected: ≥3 matches
  </verify>
  <done>Zep graph fetch is cached with 5-min TTL — repeated prepare calls in experiments skip the slow fetch.</done>
</task>

</tasks>

<success_criteria>
1. python3 backend/experiments/run_experiment.py --help shows all flags
2. Running 3 experiments (agent_counts=10,25,50) appends 3 records to results.jsonl
3. analyze.py prints a table sorted by agent count with avg pct_in_range per tier
4. ZEP_CACHE_TTL constant exists in simulation_manager.py
</success_criteria>
