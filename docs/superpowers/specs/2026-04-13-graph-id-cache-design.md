# Graph ID Cache Design

**Date:** 2026-04-13
**Goal:** Skip steps 1 (ontology generation) and 2 (graph build) on repeated runs of the same seed file, to speed up backtesting.

---

## Problem

Each run of `run_trade.py` re-generates the ontology and rebuilds the Zep knowledge graph even when the seed content is identical. Steps 1 and 2 together can take 2–5+ minutes per seed. In a backtesting workflow where the same seeds are run many times with different `SIM_ROUNDS`, this is pure waste.

---

## Approach

Per-seed sidecar cache files. Each seed file gets its own JSON cache file in a `.cache/` subdirectory next to the seeds. The cache key is the SHA256 hash of the seed file content — not the filename — so content changes always invalidate the cache.

---

## Cache File Location

```
seeds/
  seed_2026-04-05T01.md
  seed_2026-04-05T02.md
  .cache/
    seed_2026-04-05T01.md.json
    seed_2026-04-05T02.md.json
```

The `.cache/` directory is derived from the seed file's parent directory. It should be added to `.gitignore`.

---

## Cache File Format

```json
{
  "sha256": "a3f9c2d1e4b7...",
  "project_id": "proj_abc123",
  "graph_id": "graph_xyz789",
  "cached_at": "2026-04-13T10:00:00"
}
```

---

## Cache Lookup Logic (in `run_trade.py`)

At the start of `main()`, before any pipeline steps:

1. Read seed file content → compute `sha256`
2. Derive sidecar path:
   ```python
   seed_dir = os.path.dirname(os.path.abspath(args.seed_file))
   seed_basename = os.path.basename(args.seed_file)
   cache_dir = os.path.join(seed_dir, ".cache")
   sidecar_path = os.path.join(cache_dir, seed_basename + ".json")
   ```
3. **Cache hit** — sidecar exists AND stored `sha256` matches computed hash:
   - Load `project_id` and `graph_id` from sidecar
   - Print: `[Cache] Hit — skipping steps 1 & 2`
   - Jump directly to `step3_prepare_simulation(project_id, graph_id, ...)`
4. **Cache miss** — sidecar missing or hash differs:
   - Run step 1 (`step1_generate_ontology`) → get `project_id`
   - Run step 2 (`step2_build_graph`) → get `graph_id`
   - Create `cache_dir` if needed (`os.makedirs(cache_dir, exist_ok=True)`)
   - Write sidecar JSON with `sha256`, `project_id`, `graph_id`, `cached_at`
   - Continue with step 3 as normal

---

## Concurrency

No locking needed. Each seed file owns exactly one sidecar file. When `trade.sh` runs `NUM_SEEDS` seeds in parallel, they each write to different sidecar paths — no shared state.

---

## Changes Required

- **`backend/scripts/run_trade.py`** — add cache lookup/write logic in `main()` before the pipeline steps. No new functions needed beyond a small helper. No CLI argument changes.
- **`.gitignore`** — add `seeds/.cache/` (or `**/.cache/` to cover any SEEDS_DIR).
- **No changes to `trade.sh`.**

---

## Out of Scope

- Cache expiry / TTL — not needed; content hash invalidation is sufficient
- Cache invalidation by server restart — the `project_id` and `graph_id` are persisted server-side in `ProjectManager`, so they survive restarts as long as the server's upload folder is intact
- Cache for step 3 (simulation prepare) — step 3 already handles `already_prepared` natively
