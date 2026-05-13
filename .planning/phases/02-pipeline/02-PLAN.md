---
phase: 02-pipeline
plan: 02
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/scripts/run_pipeline.py      # new CLI script
autonomous: true
must_haves:
  truths:
    - CLI script calls /api/pipeline/run, polls /api/pipeline/status until done, prints result
    - Accepts --project-id, --simulation-id, --rounds, --ohlcv-file (for Phase 3 hookup later)
    - Can be run without the server running (fails fast with clear error)
  artifacts:
    - backend/scripts/run_pipeline.py
  key_links:
    - calls pipeline.py /run then polls /status (Plan 01 of this phase)
---

<objective>
CLI script to run the full pipeline from the terminal in one command.

Purpose: Developers can iterate without touching the frontend or Postman.
Output: backend/scripts/run_pipeline.py
</objective>

<context>
@.planning/ROADMAP.md
@.planning/phases/02-pipeline/01-PLAN.md
</context>

<tasks>

<task type="auto">
  <name>Task 2.3: Create run_pipeline.py CLI script</name>
  <files>backend/scripts/run_pipeline.py</files>
  <action>
Create backend/scripts/run_pipeline.py:

```python
#!/usr/bin/env python3
"""
Run the full MiroFish pipeline in one command.

Usage:
    python backend/scripts/run_pipeline.py \\
        --project-id <project_id> \\
        --simulation-id <sim_id> \\
        [--rounds 10] \\
        [--platform parallel] \\
        [--host http://localhost:5001]
"""
import argparse, requests, time, sys

def main():
    parser = argparse.ArgumentParser(description="Run MiroFish pipeline end-to-end")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--simulation-id", required=True)
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--platform", default="parallel")
    parser.add_argument("--host", default="http://localhost:5001")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    base = args.host

    print(f"[pipeline] Starting run — project={args.project_id} sim={args.simulation_id} rounds={args.rounds}")

    # Start pipeline
    try:
        r = requests.post(f"{base}/api/pipeline/run", json={
            "project_id": args.project_id,
            "simulation_id": args.simulation_id,
            "max_rounds": args.rounds,
            "platform": args.platform,
            "force": args.force,
        }, timeout=15)
    except requests.exceptions.ConnectionError:
        print(f"[error] Cannot connect to {base} — is the backend running?")
        sys.exit(1)

    data = r.json()
    if not data.get("success"):
        print(f"[error] {data.get('error')}")
        sys.exit(1)

    pipeline_task_id = data["pipeline_task_id"]
    print(f"[pipeline] Task started: {pipeline_task_id}")

    # Poll status
    last_stage = None
    while True:
        s = requests.get(f"{base}/api/pipeline/status/{pipeline_task_id}", timeout=10).json()
        task = s.get("data", {})
        stage = task.get("stage")
        status = task.get("status")

        if stage != last_stage:
            print(f"[pipeline] Stage: {stage}")
            last_stage = stage

        if status == "completed":
            print("[pipeline] ✓ Done")
            break
        if status == "failed":
            print(f"[pipeline] ✗ Failed at stage '{stage}': {task.get('error')}")
            sys.exit(1)

        time.sleep(3)

if __name__ == "__main__":
    main()
```
  </action>
  <verify>
python3 backend/scripts/run_pipeline.py --help
# Expected: shows usage with all args listed
  </verify>
  <done>Script exists, --help works, --host flag allows pointing at any server.</done>
</task>

</tasks>

<success_criteria>
1. python3 backend/scripts/run_pipeline.py --help prints usage
2. Running against a live server with valid IDs completes the pipeline and prints stage transitions
3. Running against a dead server prints a clear "cannot connect" error and exits 1
</success_criteria>
