---
name: Step 3 Simulation Cache Design
description: Extend graph-id cache to include simulation_id, skipping Step 3 (profile prep) on seed cache hits
type: design
---

# Step 3 Simulation Cache Design

## Problem

Step 3 (`step3_prepare_simulation`) generates agent profiles for the simulation, which is time-consuming. Currently, only Steps 1 & 2 are cached. Running the same seed multiple times re-generates profiles needlessly.

## Solution

Extend the existing sidecar cache to store `simulation_id` alongside `project_id` and `graph_id`. On cache hit, skip steps 1, 2, and 3 — jump directly to Step 4 (run simulation).

## Cache Structure

**Current format (Steps 1 & 2 only):**
```json
{
  "sha256_of_seed_content": {
    "project_id": "proj_123",
    "graph_id": "graph_456",
    "cached_at": "2026-04-13T10:30:00"
  }
}
```

**New format (Steps 1, 2, 3):**
```json
{
  "sha256_of_seed_content": {
    "project_id": "proj_123",
    "graph_id": "graph_456",
    "simulation_id": "sim_789",
    "cached_at": "2026-04-13T10:30:00"
  }
}
```

## Implementation Details

### `_load_graph_cache(sidecar_path, sha256)` Changes

**Current behavior:**
- Returns `(project_id, graph_id)` if entry exists, else `None`

**New behavior:**
- Returns `(project_id, graph_id, simulation_id)` if entry exists and all three fields are present
- Returns `None` if entry missing or incomplete (backward compatible with old sidecars)

### `_save_graph_cache(sidecar_path, sha256, project_id, graph_id, simulation_id)` Changes

**Current behavior:**
- Saves `project_id` + `graph_id` + `cached_at` timestamp

**New behavior:**
- Saves `project_id` + `graph_id` + `simulation_id` + `cached_at` timestamp
- Preserves all other entries in the sidecar

### `main()` Execution Flow

```
1. Compute seed_sha256 = hash(seed_text)
2. Load cache:
   - If (project_id, graph_id, simulation_id) found:
     - Print "[Cache] Hit — skipping steps 1, 2, 3"
     - Skip to Step 4 (run simulation)
   - Else:
     - Run Step 1 (generate ontology)
     - Run Step 2 (build graph)
     - Run Step 3 (prepare simulation)
     - Save cache with all three IDs
3. Run Step 4 (run simulation)
4. Run Step 5 (interview agents)
```

## Backward Compatibility

- Old sidecar files containing only `project_id` + `graph_id` (no `simulation_id`) are treated as cache misses
- After Step 3 completes, they are rewritten with the new format
- No manual migration required

## Error Handling

**If Step 3 fails after steps 1-2 succeed:**
- The cache entry may be incomplete (`simulation_id` missing or null)
- On next run, the cache check returns `None` (incomplete entry triggers miss)
- Steps 1-2 are skipped (already in sidecar), but Step 3 re-runs
- After Step 3 succeeds, cache is updated with new `simulation_id`

**If manual cache invalidation is needed:**
- User deletes the sidecar file at `seeds/.cache/seed_YYYY-MM-DDTHH.md.json`
- All three steps re-run on next execution

## Testing

1. Run a seed multiple times → verify Step 3 is skipped on subsequent runs
2. Modify seed content → verify cache miss and full re-run
3. Delete cached `simulation_id` → verify Step 3 re-runs but steps 1-2 are skipped
4. Run old sidecar (without `simulation_id` field) → verify graceful upgrade to new format

## Performance Impact

- **First run:** Same as before (all 5 steps)
- **Subsequent runs (same seed):** Steps 1-3 skipped, ~60-70% faster (steps 4-5 still run)

## Future Considerations

- Consider adding a TTL (time-to-live) on cached `simulation_id` if profiles need periodic refresh
- Consider checksum validation on seed file to detect edits more reliably
