# MiroFish Phase Research — Exact File:Line References

## Phase 2 — Pipeline Automation

### 1. `/api/graph/build` endpoint
- **Defined**: `backend/app/api/graph.py:260` — `@graph_bp.route('/build', methods=['POST'])`
- **Returns success (task started)**: `graph.py:511-518` — returns `{"success": True, "data": {"project_id", "task_id", "message": "Graph build task started..."}}`
- **Background task marks COMPLETED**: `graph.py:477-489` — `task_manager.update_task(task_id, status=TaskStatus.COMPLETED, ...)`
- **Blueprint registered**: `backend/app/__init__.py:67` — `app.register_blueprint(graph_bp, url_prefix='/api/graph')`

### 2. `/api/simulation/prepare` endpoint
- **Defined**: `backend/app/api/simulation.py:358` — `@simulation_bp.route('/prepare', methods=['POST'])`
- **Parameters (JSON body)**:
  - `simulation_id` (required)
  - `entity_types` (optional list)
  - `use_llm_for_profiles` (optional bool, default true)
  - `parallel_profile_count` (optional int, default 5)
  - `force_regenerate` (optional bool, default false)
- **Returns task_id immediately**: `simulation.py:489-497` — creates async task, returns `task_id`
- **Short-circuits if already prepared**: `simulation.py:428-443` — returns `already_prepared: true` immediately

### 3. `/api/simulation/start` endpoint
- **Defined**: `backend/app/api/simulation.py:1446` — `@simulation_bp.route('/start', methods=['POST'])`
- **Parameters (JSON body)**: `simulation_id` (required), `platform` (twitter/reddit/parallel, default parallel), `max_rounds` (optional int), `enable_graph_memory_update` (optional bool), `force` (optional bool)
- **Calls runner**: `simulation.py:1599-1605` — `SimulationRunner.start_simulation(...)`
- **Returns success**: `simulation.py:1619-1622`

### 4. Task/polling mechanism
- **Task poll endpoint**: `backend/app/api/graph.py:530` — `GET /api/graph/task/<task_id>`
- **Prepare status poll**: `backend/app/api/simulation.py:638` — `GET /api/simulation/prepare/status`
- **Graph build uses `TaskManager`**: graph.py background thread calls `task_manager.update_task(task_id, status=..., progress=0-100, message=...)` at each stage
- **Prepare uses same `TaskManager`**: simulation.py `run_prepare()` thread at line `504` updates task with `progress_detail` dict including `current_stage`, `stage_index`, `total_stages`, `current_item`, `total_items`

### 5. State transitions (`state.status`)
| Step | Status Value |
|------|-------------|
| Simulation created | `created` |
| `/prepare` called | `preparing` |
| Preparation done | `ready` |
| `/start` called | `running` |
| Stopped manually | `stopped` |
| Finished naturally | `completed` |
| Error | `failed` |
- **Defined**: `backend/app/services/simulation_manager.py:24-33` — `SimulationStatus` enum
- **Project status** (graph build): `CREATED → ONTOLOGY_GENERATED → GRAPH_BUILDING → GRAPH_COMPLETED / FAILED`
  - Defined: `backend/app/models/project.py` (referenced; transitions at `graph.py:370`, `graph.py:469`, `graph.py:496`)

### 6. `simulation_manager.py` key methods
- **`create_simulation()`**: `simulation_manager.py:193` — creates SimulationState, saves to `uploads/simulations/<sim_id>/state.json`
- **`prepare_simulation()`**: `simulation_manager.py:229` — orchestrates full prep pipeline (read entities → generate profiles + config in parallel → save files → set `status=READY`)
- **`_save_simulation_state()`**: `simulation_manager.py:144` — persists state dict to `state.json`
- **`_load_simulation_state()`**: `simulation_manager.py:156` — loads from disk with in-memory cache
- **`get_simulation()`**: `simulation_manager.py:443` — public accessor calling `_load_simulation_state`
- **Parallel profile+config generation**: `simulation_manager.py:389-394` — `ThreadPoolExecutor(max_workers=2)` runs `_generate_profiles()` and `_generate_config()` concurrently

---

## Phase 3 — OHLCV Data Bridge

### 1. `GraphBuilderService` episode ingestion into Zep
- **Method**: `add_text_batches()` — `backend/app/services/graph_builder.py:288`
- **Sends episodes**: `graph_builder.py:312-315` — builds `[EpisodeData(data=chunk, type="text") for chunk in batch_chunks]` then calls `self.client.graph.add_batch(graph_id=graph_id, episodes=episodes)`
- **Called from**: `graph_builder.py:436` (in `build_task` thread in `graph.py`)

### 2. `EpisodeData` format
- **Import**: `graph_builder.py:15` — `from zep_cloud import EpisodeData, EntityEdgeSourceTarget`
- **Usage**: `graph_builder.py:313` — `EpisodeData(data=chunk, type="text")` where `chunk` is a plain text string from `TextProcessor.split_text()`

### 3. `text_processor.py` chunking
- **Method**: `backend/app/services/text_processor.py:18` — `split_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]`
- **Input format**: plain preprocessed text string; delegates to `split_text_into_chunks()` from `backend/app/utils/file_parser.py`
- **Preprocessing**: `text_processor.py:37` — `preprocess_text()` normalizes line breaks and strips whitespace

### 4. OHLCV CSV format
- **File**: `/Users/nathannguyen/Documents/exchange-connectors/marketdata/data/binance/sol/formatted/2026-03-15/ohlcv.csv`
- **Header**: `T,O,H,L,C,V`
- **Sample row**: `1773532980000,87.84000000,87.90000000,87.84000000,87.86000000,8480.76000000`
- **T** = Unix timestamp ms, **O** = Open, **H** = High, **L** = Low, **C** = Close, **V** = Volume (all float strings with 8 decimal places)
- **Interval**: 60-second candles (timestamps differ by 60000 ms)

### 5. Where to add new API endpoints
- **Blueprint registration**: `backend/app/__init__.py:66-69` — the 3 blueprints (`graph_bp`, `simulation_bp`, `report_bp`) are imported from `backend/app/api/__init__.py` and registered with URL prefixes
- **Blueprint definition**: `backend/app/api/__init__.py:7-13` — `graph_bp`, `simulation_bp`, `report_bp` created; route modules imported
- **Pattern**: Add new routes to an existing blueprint file (e.g. `graph.py` for graph-related, `simulation.py` for sim-related) OR create a new blueprint following the pattern in `api/__init__.py` lines 7-13 and register it in `app/__init__.py` lines 66-69
- **Recommended location for OHLCV bridge**: add new file `backend/app/api/ohlcv.py` + `ohlcv_bp = Blueprint('ohlcv', __name__)` in `api/__init__.py`, registered at `app/__init__.py` with `url_prefix='/api/ohlcv'`

---

## Phase 4 — Capital-Weighted Agents

### 1. Agent profile creation
- **Primary method**: `OasisProfileGenerator.generate_profile_from_entity()` — `backend/app/services/oasis_profile_generator.py:211`
- **Batch method**: `generate_profiles_from_entities()` — `oasis_profile_generator.py:856` — iterates entities, calls `generate_profile_from_entity()` with LLM or rule-based path
- **Returns**: `OasisAgentProfile` dataclass — `oasis_profile_generator.py:29`

### 2. `karma` and `follower_count` set
- **Dataclass defaults**: `oasis_profile_generator.py:39` — `karma: int = 1000`; `oasis_profile_generator.py:43` — `follower_count: int = 150`
- **Set from LLM output**: `oasis_profile_generator.py:261` — `karma=profile_data.get("karma", random.randint(500, 5000))`
- **Set from LLM output**: `oasis_profile_generator.py:263` — `follower_count=profile_data.get("follower_count", random.randint(100, 1000))`
- **Serialized to Reddit JSON**: `oasis_profile_generator.py:68` — `"karma": self.karma`
- **Serialized to Twitter CSV**: `oasis_profile_generator.py:97` — `"follower_count": self.follower_count`

### 3. `influence_weight` in agent configs
- **Dataclass field**: `backend/app/services/simulation_config_generator.py:80` — `influence_weight: float = 1.0` in `AgentActivityConfig`
- **Rule-based assignment by entity type**:
  - University/GovAgency/NGO: `simulation_config_generator.py:937` — `"influence_weight": 3.0`
  - MediaOutlet: `simulation_config_generator.py:950` — `"influence_weight": 2.5`
  - Professor/Expert/Official: `simulation_config_generator.py:963` — `"influence_weight": 2.0`
  - Student: `simulation_config_generator.py:976` — `"influence_weight": 0.8`
  - Default: `simulation_config_generator.py:989,1002` — `"influence_weight": 1.0`
- **LLM path**: `simulation_config_generator.py:878` — LLM prompt instructs `"influence_weight": <influence weight>`
- **Parsed back**: `simulation_config_generator.py:916` — `influence_weight=cfg.get("influence_weight", 1.0)`
- **Sorted by influence**: `simulation_config_generator.py:812` — `sorted(agent_configs, key=lambda a: a.influence_weight, reverse=True)`

### 4. Final agent config structure (JSON serialization)
- **`SimulationParameters.to_dict()`**: `simulation_config_generator.py:176` — top-level keys: `simulation_id`, `project_id`, `graph_id`, `simulation_requirement`, `time_config`, `agent_configs`, `event_config`, `twitter_config`, `reddit_config`, `llm_model`, `llm_base_url`, `generated_at`, `generation_reasoning`
- **`agent_configs` item** (from `AgentActivityConfig` via `asdict()`): `simulation_config_generator.py:185` — includes `activity_level`, `posts_per_hour`, `comments_per_hour`, `active_hours`, `response_delay_min`, `response_delay_max`, `sentiment_bias`, `stance`, `influence_weight`
- **Saved to**: `backend/uploads/simulations/<sim_id>/simulation_config.json` — `simulation_manager.py:407-409`

---

## Phase 5 — Prediction + Backtest

### 1. Where `actions.jsonl` is read/parsed
- **Method**: `SimulationRunner.get_all_actions()` — `backend/app/services/simulation_runner.py:889`
- **Per-platform files**: `simulation_runner.py:912` — reads `uploads/simulations/<sim_id>/twitter/actions.jsonl`; `simulation_runner.py:923` — reads `uploads/simulations/<sim_id>/reddit/actions.jsonl`
- **Fallback**: `simulation_runner.py:935` — falls back to `uploads/simulations/<sim_id>/actions.jsonl` (legacy format)
- **Low-level parse**: `simulation_runner.py:843-884` — `_read_actions_from_file()`: reads JSONL line-by-line, skips `event_type` records, creates `AgentAction` objects with fields `round_num`, `timestamp`, `platform`, `agent_id`, `agent_name`, `action_type`, `action_args`, `result`, `success`

### 2. Where `report_agent.py` / `ReportAgent` is triggered
- **API endpoint**: `backend/app/api/report.py:24` — `POST /api/report/generate`
- **ReportAgent instantiated**: `report.py:134` — `agent = ReportAgent(graph_id=..., simulation_id=..., simulation_requirement=...)`
- **`generate_report()` called**: `report.py:149` — inside a background thread started at `report.py` around line 120
- **Second trigger point**: `report.py:540` — another `ReportAgent` instantiation for chat/interview continuation

### 3. ReportAgent tools (with line numbers)
- **`_define_tools()`**: `backend/app/services/report_agent.py:917`
- **`insight_forge`**: `report_agent.py:920` — deep multi-angle retrieval from Zep graph
- **`panorama_search`**: `report_agent.py:928` — full-view retrieval including expired/historical facts
- **`quick_search`**: `report_agent.py:936` — fast single-query search with `limit` param
- **`interview_agents`**: `report_agent.py:944` — interview up to N simulation agents (default 5, max 10)
- **Tool execution dispatch**: `report_agent.py:954` — `_execute_tool()`

### 4. Where simulation results are stored after completion
- **`run_state.json`**: `uploads/simulations/<sim_id>/run_state.json` — runner state including `runner_status`, `completed_at`, `twitter_completed`, `reddit_completed`; written by `simulation_runner.py:300-302`
- **`actions.jsonl`**: `uploads/simulations/<sim_id>/twitter/actions.jsonl` and `reddit/actions.jsonl` — live-written during simulation
- **`simulation.log`**: `uploads/simulations/<sim_id>/simulation.log` — subprocess stdout/stderr
- **SQLite DBs**: `uploads/simulations/<sim_id>/twitter_simulation.db` and `reddit_simulation.db` — posts/comments accessed via `simulation.py:2004`
- **Reports**: `uploads/reports/<report_id>/` — markdown, outline, sections, `agent_log.jsonl`, `console_log.txt`; `ReportManager._get_report_folder()` at `report_agent.py:1909`
- **Completion marked**: `simulation_runner.py:523-524` — `state.runner_status = RunnerStatus.COMPLETED; state.completed_at = datetime.now().isoformat()`
