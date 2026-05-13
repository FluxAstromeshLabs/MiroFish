# MiroFish Codebase Concerns, Bugs & Technical Debt

Generated: 2026-05-09  
Scope: backend services, API routes, frontend Step 5  

---

## TODO Mapping

| # | TODO Item | Concern IDs |
|---|-----------|-------------|
| 1 | Automate upload → graph → simulation flow | C-01 |
| 2 | Why 14 agents? Make configurable | C-02 |
| 3 | Agent identity language hardcoded in Chinese → verify fix | C-03 |
| 4 | Hardcoded values in chat | C-04 |
| 5 | Zep processing is slow, needs caching | C-05, C-06 |
| 6 | OHLCV data not in simulation graph | C-07 |
| 7 | Redundant persona generation every run | C-08 |
| 8 | Capital-weighted agent influence (whale vs retail) | C-09 |

---

## C-01 — No end-to-end automation: upload → graph → simulation

**Severity: HIGH**

**Files:**
- `/Users/nathannguyen/Mirofish/backend/app/api/graph.py` lines 121–256 (`generate_ontology`), 260–518 (`build_graph`)
- `/Users/nathannguyen/Mirofish/backend/app/api/simulation.py` lines 164–236 (`create_simulation`), 358–616 (`prepare_simulation`)

**Description:**  
The three-stage pipeline (upload/ontology → graph build → simulation prepare) requires three separate, manually triggered API calls. After `build_graph` completes and fires a task-complete callback, there is no code that automatically creates and prepares a simulation. The user or frontend must explicitly call `/api/simulation/create` and then `/api/simulation/prepare`. The graph build task callback (`build_task` in `graph.py` line 375) simply marks the project `GRAPH_COMPLETED` and exits — it does not chain into simulation creation.

**Suggested Fix:**  
Add an optional `auto_simulate: true` flag to the `/api/graph/build` request body. When set, the `build_task` function (after line 488 in `graph.py`) should call `SimulationManager().create_simulation(...)` and immediately enqueue `prepare_simulation(...)` in a new background thread, passing the project's `simulation_requirement` and graph ID. The simulation ID can be returned in the original `/api/graph/build` response so the frontend can start polling.

---

## C-02 — Why 14 agents? Agent count is not configurable and the source is indirect

**Severity: HIGH**

**Files:**
- `/Users/nathannguyen/Mirofish/backend/app/services/simulation_config_generator.py` lines 213–216
- `/Users/nathannguyen/Mirofish/backend/app/services/ontology_generator.py` lines 76–82, 247–253

**Description:**  
There is no hardcoded "14 agents" constant. The agent count derives entirely from the number of entities returned by Zep after graph construction. The ontology system prompt (`ontology_generator.py` line 76) mandates **exactly 10 entity types** (8 specific + 2 fallback). Zep then extracts entities into those buckets. For a typical single-document scenario the graph produces roughly 10–20 entities total, with the most common result being ~14. However, the number is completely opaque to the user — nowhere in the UI or API can a user request "generate N agents" or cap/expand the pool. The `AGENTS_PER_BATCH = 15` constant in `simulation_config_generator.py` line 216 is a batching parameter, not an agent count cap, but its name can mislead.

**Suggested Fix:**
1. Expose a `max_agents` / `min_agents` parameter in the `/api/simulation/prepare` request body.
2. In `ZepEntityReader.filter_defined_entities()`, apply the cap after filtering.
3. Rename `AGENTS_PER_BATCH` to `LLM_BATCH_SIZE` to eliminate confusion.
4. In the ontology prompt (`ontology_generator.py` line 76), note that entity-type count controls agent diversity, not raw agent count, so these are orthogonal knobs.

---

## C-03 — Agent persona language: was Chinese, now English in prompts but Chinese fallback values remain in code

**Severity: MEDIUM**

**Files:**
- `/Users/nathannguyen/Mirofish/backend/app/services/oasis_profile_generator.py`
  - Line 679: system prompt says `"Use English."`
  - Lines 695–729: individual persona prompt says `"Use English for the content"`
  - Lines 742–777: group persona prompt says `"Use English for the content"`
  - Lines 1134–1138: `_normalize_gender` contains Unicode escapes `男` (男), `女` (女), `机构` (机构), `其他` (其他) — these are Chinese gender strings used as normalization keys, meaning the LLM was previously generating Chinese gender strings and this mapping was added as a band-aid

**Description:**  
The prompts now explicitly request English output. However, the `_normalize_gender` method still maps Chinese gender terms (`男`, `女`, `机构`, `其他`) into valid OASIS values. This is dead code if the LLM outputs English, but it reveals the prior state. More importantly, the system-prompt comment on line 603 (`simulation_config_generator.py`) still says `"The time configuration should follow typical China daily routines"` — this is a real functional bias baked into the LLM prompts, not just a cosmetic label. All time config prompts default to Beijing-time schedules regardless of the target scenario.

**Suggested Fix:**
1. Delete the Chinese-to-English mappings in `_normalize_gender` (lines 1135–1138) since the LLM now generates English. Add a catch-all that logs a warning for unexpected values instead.
2. Make the time-zone persona parameterizable: accept a `timezone` or `locale` field in the simulation request and pass it into the `_generate_time_config` and `_generate_agent_configs_batch` prompts so non-Chinese scenarios generate culturally appropriate schedules.

---

## C-04 — Hardcoded values in chat / UI

**Severity: LOW**

**Files:**
- `/Users/nathannguyen/Mirofish/frontend/src/components/Step5Interaction.vue` line 12
- `/Users/nathannguyen/Mirofish/backend/app/api/simulation.py` lines 684–735 (mixed Chinese/English comments in the same function, e.g. lines 362–370, 425, 429, 433, 456, 460, 463, 470–487, 499, 532)
- `/Users/nathannguyen/Mirofish/backend/app/services/simulation_config_generator.py` lines 357–360, 363–374 (platform config values hardcoded: `recency_weight=0.4`, `popularity_weight=0.3`, `relevance_weight=0.3`, `viral_threshold=10`, `echo_chamber_strength=0.5`)

**Description:**
1. **Vue component line 12**: `'REF-2024-X92'` is a hardcoded fallback report ID displayed to the user when `reportId` prop is null. It is a stale placeholder string and will appear in production if the prop is ever missing.
2. **Platform config constants** (`simulation_config_generator.py` lines 357–374): `PlatformConfig` values for Twitter and Reddit are hardcoded inline rather than being LLM-generated or user-configurable. There is a comment saying platform config generation is the "final step" but the implementation just returns fixed magic numbers.
3. **Mixed-language comments in `simulation.py`**: The `/prepare` endpoint docstring (lines 362–400) is half-English, half-Chinese. Error messages also mix languages (e.g. line 460: `"项目Missing simulation requirement description"`). This is a maintenance hazard.

**Suggested Fix:**
1. Replace `'REF-2024-X92'` with an empty string or `'—'` and hide the span when no ID is available.
2. Move `PlatformConfig` defaults into a config dict in `Config` so they can be overridden per deployment or per-simulation.
3. Standardize all API comments and error strings to English.

---

## C-05 — Zep graph fetch is slow: no caching, full re-fetch every prepare call

**Severity: HIGH**

**Files:**
- `/Users/nathannguyen/Mirofish/backend/app/services/zep_entity_reader.py` lines 127–152 (`get_all_nodes`), 154–180 (`get_all_edges`)
- `/Users/nathannguyen/Mirofish/backend/app/api/simulation.py` lines 471–487 (synchronous pre-fetch of entities before the async task)
- `/Users/nathannguyen/Mirofish/backend/app/services/simulation_manager.py` lines 275–291 (re-reads all nodes/edges again inside `prepare_simulation`)

**Description:**  
Every call to `/api/simulation/prepare` triggers two full graph fetches:
1. A synchronous fetch at `simulation.py` line 471–486 (without edge enrichment, for quick entity count display).
2. A second full fetch with edge enrichment inside `prepare_simulation()` → `ZepEntityReader.filter_defined_entities()` at `simulation_manager.py` line 280.

For large graphs each call to `get_all_nodes` and `get_all_edges` pages through the entire Zep graph with no pagination size control and no local cache. For a graph with hundreds of nodes and edges this can take 30–120 seconds. There is zero caching at any layer (no Redis, no in-memory TTL cache, no file-based cache). The `_simulations` dict in `SimulationManager.__init__` (line 136) only caches `SimulationState` objects, not Zep graph data.

**Suggested Fix:**
1. After `build_graph` completes (in `graph.py` task callback), serialize the filtered entity list to a file (`entities_cache.json`) in the simulation directory. `prepare_simulation` reads from this file instead of re-fetching Zep.
2. Add a TTL-based in-memory cache keyed by `graph_id` in `ZepEntityReader` using `functools.lru_cache` or a simple dict with timestamps.
3. Eliminate the redundant synchronous pre-fetch in `simulation.py` by reading the cached entity count from the project state.

---

## C-06 — Per-entity Zep hybrid search during profile generation is a major bottleneck

**Severity: HIGH**

**Files:**
- `/Users/nathannguyen/Mirofish/backend/app/services/oasis_profile_generator.py` lines 285–414 (`_search_zep_for_entity`)
- `/Users/nathannguyen/Mirofish/backend/app/services/oasis_profile_generator.py` line 478 (called from `_build_entity_context` for every entity)
- `/Users/nathannguyen/Mirofish/backend/app/services/oasis_profile_generator.py` lines 329–366 (edge search: limit=30, nodes search: limit=20, each with up to 3 retries and exponential backoff of 2s/4s/8s)

**Description:**  
For every entity, `generate_profile_from_entity` calls `_build_entity_context`, which calls `_search_zep_for_entity`. That function fires two parallel Zep search queries (edges + nodes) per entity with a 30-second timeout each and up to 3 retries with exponential backoff. For 14 agents with `parallel_count=5`, at steady state 5 of these are running simultaneously, each potentially making 6 Zep API calls (2 searches × 3 retries). In the worst case, persona generation alone can block for 5–10 minutes.

There is no result caching: if the same entity is processed again (e.g., on `force_regenerate`), all Zep searches repeat from scratch.

**Suggested Fix:**
1. Save the Zep search results for each entity to a sidecar file (e.g., `entity_context_cache/{uuid}.json`) during the first `prepare_simulation`. Subsequent runs read from the cache file.
2. Make the Zep hybrid search optional via a `enrich_with_zep_search` flag that defaults to `False` for subsequent runs.
3. Reduce the retry backoff aggressiveness: the current `delay *= 2` starting from 2s means a single entity can stall persona generation for 14 seconds before giving up. Change to max 1 retry with a 1s delay, or set `max_retries=2`.

---

## C-07 — OHLCV / market data has no integration point anywhere in the simulation pipeline

**Severity: HIGH**

**Files:**
- `/Users/nathannguyen/Mirofish/backend/app/services/simulation_config_generator.py` lines 113–127 (`EventConfig`), lines 660–739 (`_generate_event_config`)
- `/Users/nathannguyen/Mirofish/backend/app/services/simulation_manager.py` lines 229–441 (`prepare_simulation`)
- `/Users/nathannguyen/Mirofish/backend/app/api/graph.py` (no OHLCV endpoint)

**Description:**  
There is no OHLCV ingestion endpoint, no OHLCV data model, and no passage of price/volume data into the graph builder, entity reader, simulation config generator, or the OASIS simulation scripts. The `EventConfig` dataclass has `hot_topics`, `initial_posts`, and `scheduled_events`, but none of these are seeded from market data. The `_generate_event_config` LLM prompt (lines 690–717) only uses the simulation requirement and entity context — real price action cannot inform agent stances or event timing.

**Suggested Fix:**
1. Add a new `/api/graph/ingest-ohlcv` endpoint that accepts a CSV/JSON of `{timestamp, open, high, low, close, volume}` data.
2. Convert significant price events (large drops, volume spikes) into Zep graph episodes via `client.graph.add(type="text", data="On DATE, TICKER fell 8% on VOLUME volume, reaching CLOSE")`. This makes price action queryable from the graph during entity search.
3. In `_generate_event_config`, optionally accept a `market_events` parameter (a list of `{date, event_description}` tuples derived from OHLCV anomalies) and include them in the LLM prompt so initial posts and narrative direction reflect real price triggers.
4. In `AgentActivityConfig`, add a `capital_exposure` field that can be populated from OHLCV + entity data, which feeds into concern C-09 below.

---

## C-08 — Redundant persona generation on every non-cached run; no profile reuse

**Severity: MEDIUM**

**Files:**
- `/Users/nathannguyen/Mirofish/backend/app/api/simulation.py` lines 424–443 (`force_regenerate` check)
- `/Users/nathannguyen/Mirofish/backend/app/services/simulation_manager.py` lines 316–365 (`_generate_profiles` closure)
- `/Users/nathannguyen/Mirofish/backend/app/services/oasis_profile_generator.py` lines 924–952 (`generate_single_profile`)

**Description:**  
The `_check_simulation_prepared` guard at `simulation.py` lines 428–443 correctly skips re-generation if `state.json` shows `config_generated=True` and the profile files exist. However, this check only applies at the top-level `/prepare` endpoint. The internal `_generate_profiles` closure inside `prepare_simulation` (`simulation_manager.py` line 316) always calls `OasisProfileGenerator.generate_profiles_from_entities`, which calls the LLM once per entity. There is no entity-level check: if even one entity's file is missing, the entire batch regenerates. Additionally, when `force_regenerate=True`, all profiles are regenerated even for entities whose summaries have not changed since the last run — there is no content-hash comparison.

**Suggested Fix:**
1. Save each generated profile alongside a hash of the input (`entity.summary + entity.attributes`) to a sidecar file (`profiles/{uuid}.hash`).
2. In `generate_profiles_from_entities`, check the hash before calling the LLM. If the hash matches, deserialize the cached profile JSON and skip the LLM call.
3. This can reduce a 14-agent prepare from ~14 LLM calls + ~28 Zep searches to 0 LLM calls on unchanged entities.

---

## C-09 — Influence weight is role-based only; no capital-weighted (whale vs retail) differentiation

**Severity: MEDIUM**

**Files:**
- `/Users/nathannguyen/Mirofish/backend/app/services/simulation_config_generator.py` lines 920–1001 (`_generate_agent_config_by_rule`)
- `/Users/nathannguyen/Mirofish/backend/app/services/oasis_profile_generator.py` lines 39–44 (`OasisAgentProfile` dataclass: `karma`, `follower_count`)

**Description:**  
`influence_weight` is assigned purely by entity type (e.g., university=3.0, student=0.8). There is no mechanism to differentiate between agents of the same type based on capital size, holdings, or trading volume. A large institutional investor and a small retail fund would both receive `influence_weight=3.0` if they're both classified as `Organization`. The `karma` and `follower_count` fields in `OasisAgentProfile` are randomly generated (`random.randint(500, 5000)` at line 261) and have no relationship to real-world capital or influence metrics.

Furthermore, there is no concept of "whale" or "retail" entity type in the ontology system prompt (`ontology_generator.py`). The ontology is designed for social-media public-opinion simulation and treats all participants as social actors without financial weighting.

**Suggested Fix:**
1. Add a `capital_tier` field to `AgentActivityConfig` (e.g., `"whale"`, `"institutional"`, `"retail"`).
2. When OHLCV/market data is available (see C-07), derive `capital_tier` from position size or AUM data in the entity attributes.
3. In `_generate_agent_config_by_rule`, apply a `capital_multiplier` to `influence_weight`: whale entities get `influence_weight *= 5`, retail entities get `influence_weight *= 0.5`.
4. Pass `capital_tier` into the LLM persona prompt so agents generate posts with vocabulary and concerns that match their financial weight class.
5. Map `karma` and `follower_count` to the capital tier: whales get high karma (10,000+), retail gets low karma (100–500).

---

## Additional Concerns (not in the original TODO list)

### C-10 — Mixed Chinese/English in production API comments and error strings

**Severity: LOW**

**Files:**
- `/Users/nathannguyen/Mirofish/backend/app/api/simulation.py` lines 362–400 (docstring), 425, 429, 433, 456, 460, 470, 484, 499, 532

**Description:**  
The `/prepare` endpoint contains a mixed-language docstring (partially Chinese, partially English) and inline Chinese log strings (`"开始处理 /prepare 请求"`, `"检查Simulation"`, `"已准备完成，跳过重复生成"`). These appear in production logs and make debugging harder for non-Chinese speakers. The error at line 460 is a clear bug: `"项目Missing simulation requirement description"` — a Chinese prefix was accidentally concatenated to an English message.

**Suggested Fix:** Standardize all comments, docstrings, and log strings to English. Fix the concatenation bug at line 460.

---

### C-11 — `get_timeline` and `get_agent_stats` load up to 10,000 actions into memory without streaming

**Severity: MEDIUM**

**Files:**
- `/Users/nathannguyen/Mirofish/backend/app/services/simulation_runner.py` lines 984–1052 (`get_timeline`), 1055–1095 (`get_agent_stats`)

**Description:**  
Both methods call `cls.get_actions(simulation_id, limit=10000)`, loading all simulation actions into a Python list before processing them. For long simulations this can consume hundreds of MB of memory. There is no streaming or generator-based aggregation.

**Suggested Fix:** Replace with a streaming JSONL reader that aggregates round/agent statistics incrementally without loading all records into memory at once.

---

### C-12 — `_normalize_gender` still contains dead Chinese-string normalization code

**Severity: LOW**

**Files:**
- `/Users/nathannguyen/Mirofish/backend/app/services/oasis_profile_generator.py` lines 1134–1138

**Description:**  
The `_normalize_gender` method maps Chinese gender strings (`男`=男, `女`=女, `机构`=机构, `其他`=其他) to OASIS values. Since the LLM prompts now require English output, these entries are dead code. They are also misleading because they imply the system still handles Chinese LLM output silently.

**Suggested Fix:** Remove the Chinese entries. If an unexpected value arrives, log a warning and return `"other"`.

---

### C-13 — Platform config (Twitter/Reddit weights) is hardcoded, not LLM-generated

**Severity: LOW**

**Files:**
- `/Users/nathannguyen/Mirofish/backend/app/services/simulation_config_generator.py` lines 352–374

**Description:**  
The docstring for `generate_config` says platform configuration is "generated" as a final step, but the implementation simply creates `PlatformConfig` objects with fixed magic numbers (`recency_weight=0.4`, `viral_threshold=10`, `echo_chamber_strength=0.5` etc.). These values are never adjusted by the LLM based on the scenario. A breaking-news scenario and a slow-burn political scandal should arguably have very different viral thresholds and echo-chamber strengths.

**Suggested Fix:** Move these values into a `Config` class dict or expose them as API parameters. Optionally ask the LLM to suggest platform config values in the same prompt that generates event config.

---

### C-14 — `get_entity_with_context` re-fetches ALL nodes to build a node map for a single entity lookup

**Severity: MEDIUM**

**Files:**
- `/Users/nathannguyen/Mirofish/backend/app/services/zep_entity_reader.py` lines 333–411 (`get_entity_with_context`)

**Description:**  
`get_entity_with_context` calls `self.get_all_nodes(graph_id)` (lines 362–363) to build a `node_map` just to resolve related-node names. For a graph with 500+ nodes, this is an O(N) page-through of the entire graph to look up a handful of adjacent node names for a single entity. This method is called from the `/api/simulation/entities/<graph_id>/<entity_uuid>` endpoint and from the Zep entity reader's edge enrichment path.

**Suggested Fix:** Either (a) cache the full node map per `graph_id` with a TTL (see C-05), or (b) fetch related nodes individually using their UUIDs via `self.client.graph.node.get(uuid_=related_uuid)`, which avoids loading the entire graph.
