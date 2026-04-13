# Step 3 Simulation Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cache the simulation_id from Step 3 so repeated runs on the same seed skip profile generation.

**Architecture:** Extend the existing sidecar cache (stored per seed file) to include `simulation_id` alongside `project_id` and `graph_id`. The load function returns all three IDs on hit, allowing `main()` to skip steps 1-3. Save function writes all three after step 3 completes.

**Tech Stack:** Python 3, JSON sidecar files, argparse, requests

---

## Task 1: Update `_load_graph_cache()` to Return simulation_id

**Files:**
- Modify: `backend/scripts/run_trade.py:24-36`

- [ ] **Step 1: Review current implementation**

Read [run_trade.py:24-36](backend/scripts/run_trade.py#L24-L36) to understand the current structure.

Current signature: `_load_graph_cache(sidecar_path: str, sha256: str) -> tuple | None`
Returns: `(project_id, graph_id)` or `None`

- [ ] **Step 2: Modify the function to return three values**

Replace the entire function with:

```python
def _load_graph_cache(sidecar_path: str, sha256: str):
    """Return (project_id, graph_id, simulation_id) from sidecar if sha256 key exists, else None.
    
    Returns None if the entry is incomplete (missing any required field).
    Backward compatible with old sidecars that only have project_id + graph_id.
    """
    if not os.path.exists(sidecar_path):
        return None
    try:
        with open(sidecar_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        entry = data.get(sha256)
        if entry:
            project_id = entry.get("project_id")
            graph_id = entry.get("graph_id")
            simulation_id = entry.get("simulation_id")
            # Only return if all three fields present
            if project_id and graph_id and simulation_id:
                return project_id, graph_id, simulation_id
    except (json.JSONDecodeError, KeyError):
        pass
    return None
```

- [ ] **Step 3: Commit the change**

```bash
git add backend/scripts/run_trade.py
git commit -m "feat: update _load_graph_cache to return simulation_id

Extend cache return tuple from (project_id, graph_id) to include simulation_id.
Backward compatible: old sidecars without simulation_id are treated as cache misses.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: Update `_save_graph_cache()` to Accept and Store simulation_id

**Files:**
- Modify: `backend/scripts/run_trade.py:39-57`

- [ ] **Step 1: Review current implementation**

Read [run_trade.py:39-57](backend/scripts/run_trade.py#L39-L57). Current signature takes `(sidecar_path, sha256, project_id, graph_id)`.

- [ ] **Step 2: Modify function signature and implementation**

Replace the entire function with:

```python
def _save_graph_cache(sidecar_path: str, sha256: str, project_id: str, graph_id: str, simulation_id: str) -> None:
    """Add or update sha256 entry in the sidecar dict with all three IDs, preserving all other entries."""
    data = {}
    if os.path.exists(sidecar_path):
        try:
            with open(sidecar_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            data = {}
    data[sha256] = {
        "project_id": project_id,
        "graph_id": graph_id,
        "simulation_id": simulation_id,
        "cached_at": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        with open(sidecar_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass  # cache write failure is non-fatal
```

Note: `datetime` is already imported at the top of the file (line 15).

- [ ] **Step 3: Commit the change**

```bash
git add backend/scripts/run_trade.py
git commit -m "feat: update _save_graph_cache to store simulation_id

Extend cache to store project_id, graph_id, and simulation_id together.
All fields written after Step 3 completes.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: Update `main()` to Load and Use Cached simulation_id

**Files:**
- Modify: `backend/scripts/run_trade.py:571-590`

- [ ] **Step 1: Review the current cache loading logic**

Read [run_trade.py:571-590](backend/scripts/run_trade.py#L571-L590). Current code:
- Loads cache → gets `(project_id, graph_id)` or cache miss
- If miss: run steps 1 & 2, save cache

- [ ] **Step 2: Modify cache loading to handle three return values**

Replace lines 578-587 with:

```python
    cached = _load_graph_cache(sidecar_path, seed_sha256)
    if cached:
        project_id, graph_id, simulation_id = cached
        print(f"[Cache] Hit — skipping steps 1, 2, 3 (sha256: {seed_sha256[:12]}...)")
    else:
        project_id = step1_generate_ontology(args.base_url, args.seed_file, requirement, session=session)
        graph_id = step2_build_graph(args.base_url, project_id, session=session)
        simulation_id = step3_prepare_simulation(args.base_url, project_id, graph_id,
                                                 agent_count=agent_count, session=session)
        os.makedirs(cache_dir, exist_ok=True)
        _save_graph_cache(sidecar_path, seed_sha256, project_id, graph_id, simulation_id)
        print(f"[Cache] Saved (sha256: {seed_sha256[:12]}...)")
```

The key changes:
- Unpack three values from cached tuple
- Skip steps 1 & 2 on cache hit, but still set `agent_count` (see next task)
- Save all three IDs to cache after step 3

- [ ] **Step 3: Verify agent_count is available before step 3**

Agent count must be known before we call `step3_prepare_simulation()`. Verify line 588 still exists and executes before step 3:

```python
agent_count = count_agents_in_seed(seed_text)
```

This is correct — it extracts from seed file, not from the API.

- [ ] **Step 4: Commit the change**

```bash
git add backend/scripts/run_trade.py
git commit -m "feat: skip steps 1-3 on simulation cache hit

Load cached simulation_id from sidecar. If hit, skip steps 1, 2, and 3.
If miss, run all three steps and save simulation_id to cache.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: Test the Cache Behavior with Manual Runs

**Files:**
- Test: Manual end-to-end runs

- [ ] **Step 1: Run a seed file for the first time**

```bash
cd /mnt/second_disk/Code/flux/flux-MiroFish
source backend/.venv/bin/activate
python3 backend/scripts/run_trade.py \
  -o /tmp/test_run_1.csv \
  --rounds 3 \
  seeds/seed_2026-04-05T01.md
```

Expected output should show:
- `[Step 1/5] Generating ontology...`
- `[Step 2/5] Building knowledge graph...`
- `[Step 3/5] Preparing simulation...`
- `[Cache] Saved (sha256: ...)`

Verify the sidecar file exists and contains `simulation_id`:

```bash
cat seeds/.cache/seed_2026-04-05T01.md.json | jq '.'
```

Expected: JSON with `"project_id"`, `"graph_id"`, `"simulation_id"`, `"cached_at"`

- [ ] **Step 2: Run the same seed file again**

```bash
python3 backend/scripts/run_trade.py \
  -o /tmp/test_run_2.csv \
  --rounds 3 \
  seeds/seed_2026-04-05T01.md
```

Expected output should show:
- `[Cache] Hit — skipping steps 1, 2, 3 (sha256: ...)`
- Then directly to `[Step 4/5] Running simulation...`
- Should be noticeably faster (no step 1-3 overhead)

- [ ] **Step 3: Verify CSV outputs are similar**

Both runs should have similar predicted ranges (same seed = same agents):

```bash
head -2 /tmp/test_run_1.csv
head -2 /tmp/test_run_2.csv
```

`predicted_low` and `predicted_high` should match or be very close.

- [ ] **Step 4: Delete the cached simulation_id and re-run**

Edit the sidecar to remove `simulation_id`:

```bash
cat seeds/.cache/seed_2026-04-05T01.md.json | jq 'to_entries | map(.value |= del(.simulation_id)) | from_entries' > seeds/.cache/seed_2026-04-05T01.md.json
```

Run again:

```bash
python3 backend/scripts/run_trade.py \
  -o /tmp/test_run_3.csv \
  --rounds 3 \
  seeds/seed_2026-04-05T01.md
```

Expected: Should skip steps 1-2 (graph cached) but re-run step 3, printing:
- `[Cache] Hit — ...` (for project/graph)
- Wait, the current code will return `None` because `simulation_id` is missing
- So it will re-run all three steps

Actually, the current design treats incomplete cache as a miss. This is correct per spec. The output should show:
- `[Step 1/5] Generating ontology...`
- `[Step 2/5] Building knowledge graph...`
- `[Step 3/5] Preparing simulation...`

This is fine — steps 1-2 will be fast because the backend already has the project/graph cached internally.

- [ ] **Step 5: Commit a test summary (optional)**

No code commit needed, but document the test results:

```bash
git log --oneline -3
```

Verify the three cache-related commits are present.

---

## Self-Review Checklist

**Spec coverage:**
- ✓ Cache structure (project_id + graph_id + simulation_id)
- ✓ Load function returns all three or None
- ✓ Save function stores all three
- ✓ Skip steps 1-3 on cache hit
- ✓ Backward compatibility (old sidecars treated as miss)
- ✓ Error handling (incomplete cache = miss)

**Placeholder scan:**
- ✓ No "TBD" or "TODO"
- ✓ All code is complete and shown
- ✓ All commands are exact with expected output
- ✓ No "add error handling" without implementation

**Type consistency:**
- ✓ `_load_graph_cache()` returns `(str, str, str) | None`
- ✓ `_save_graph_cache()` accepts four parameters: `sidecar_path, sha256, project_id, graph_id, simulation_id`
- ✓ `main()` unpacks three values: `project_id, graph_id, simulation_id = cached`

**Edge cases:**
- ✓ Old sidecars without `simulation_id` → treated as miss
- ✓ JSON decode errors → treated as miss
- ✓ Write errors → non-fatal (cache failure doesn't crash script)
- ✓ Missing cache directory → `os.makedirs()` creates it

---

## Execution Options

Plan complete and saved to `docs/superpowers/plans/2026-04-13-step3-simulation-cache.md`.

**Two execution approaches:**

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review your work between tasks, fast iteration with safety checkpoints.

2. **Inline Execution** — Execute all tasks in this session sequentially with checkpoints between each task.

Which approach would you prefer?
