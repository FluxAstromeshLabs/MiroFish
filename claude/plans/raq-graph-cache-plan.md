# RAQ Graph Cache Plan

## Goal

Avoid rebuilding the RAQ graph when `research/scripts/run_mirofish_flow.py` is run again with the same effective graph-building inputs.

## Current State

- `run_mirofish_flow.py` calls `detect_entities()` for step 1.
- `detect_entities()` already supports resume within the same run directory by reusing `project.json`, `ontology.json`, and `graph.json`.
- This does not help across separate runs with identical inputs, because the state is scoped to a single run folder.

## Plan

1. Define a deterministic cache key for graph inputs.

- Hash the normalized contents of all `seed_files`.
- Include `simulation_requirement`.
- Include `additional_context`.
- Include graph-build parameters that affect the result, such as `chunk_size` and `chunk_overlap`, if those are configurable.
- Include a manual cache schema version so invalidation is explicit when behavior changes.

2. Add a shared graph cache index outside per-run artifacts.

- Create a shared cache store such as `research/cache/graph_cache_index.json` or `research/runs/graph_cache_index.json`.
- Do not rely on per-run artifacts for this, because those only work with `--resume` on the same run.

3. Cache both `project_id` and `graph_id`.

- `start_simulation()` requires both.
- Reusing only `graph_id` is weaker because simulation creation is project-scoped and the backend still expects a project context.

4. Put cache lookup at the start of `detect_entities()`.

- Before calling `generate_ontology()` or `build_graph()`, compute the cache key and look it up in the shared cache.
- If a valid cache entry exists and `force_rebuild` is false:
  - write cached values into this run’s `project.json`
  - write cached values into this run’s `ontology.json`
  - write cached values into this run’s `graph.json`
  - update `manifest.json`
  - skip ontology generation and graph rebuild entirely

5. Validate cached entries before reuse.

- Confirm the cache entry has the required fields: `project_id`, `graph_id`, and `ontology`.
- Prefer a lightweight backend validation step:
  - verify the project still exists
  - verify the graph still exists
- If validation fails, remove or ignore the cache entry and rebuild.

6. Populate the cache only after a successful build.

- After ontology generation and graph build complete successfully, store:
  - `cache_key`
  - `project_id`
  - `graph_id`
  - `ontology`
  - input metadata
  - timestamps
- Do not cache partial or failed state.

7. Add explicit CLI controls.

- Keep `--force-rebuild-graph` as the hard bypass.
- Add an optional `--no-graph-cache` flag for debugging or one-off runs.

8. Make invalidation explicit.

- Add a `GRAPH_CACHE_VERSION` constant in the script layer.
- Bump it when ontology generation logic, graph chunking, or backend graph semantics change.

9. Record cache provenance in run artifacts.

- On a cache hit, save metadata such as:
  - `cache_hit: true`
  - `cache_key`
  - `cache_source_graph_id`
  - `cache_source_project_id`
- This should go into `graph.json` and/or `manifest.json` so later debugging is straightforward.

10. Optional follow-up: cache fetched entities by `graph_id`.

- If the graph is reused, `start_simulation()` can also reuse `entities.json` for the same `graph_id`.
- This is not the main win, but it avoids an extra backend call.

## Files Likely To Change

- `research/scripts/run_mirofish_flow.py`
- `research/scripts/detect_entities.py`
- `research/scripts/run_artifacts.py`
- possibly a new helper such as `research/scripts/graph_cache.py`

## Recommended Implementation Order

1. Add cache key computation and shared cache read/write helper.
2. Add cache lookup and validation to `detect_entities()`.
3. Save cache hit metadata into per-run artifacts.
4. Add CLI flag(s) in `run_mirofish_flow.py`.
5. Optionally extend reuse to `entities.json`.
