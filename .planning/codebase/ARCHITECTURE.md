# MiroFish — System Architecture

## Overview

MiroFish is a social-media public-opinion simulation platform. Users upload research documents, the system extracts an ontology and builds a knowledge graph (stored in Zep), generates AI agent personas from graph entities, runs a multi-platform simulation via the OASIS framework, and finally produces an LLM-authored analysis report. Every stage is connected end-to-end without manual parameter tuning.

---

## 1. Frontend ↔ Backend Communication

The frontend is a Vue 3 SPA (Vite). All HTTP calls go to the Flask backend running on port `5001` (configurable via `VITE_API_BASE_URL`). Communication is plain JSON REST — no WebSockets, no GraphQL.

**Axios client** (`frontend/src/api/index.js`):
- Base URL defaults to `http://localhost:5001`
- 5-minute timeout (long enough for LLM calls during ontology generation)
- Retries up to 3 times with exponential back-off (`requestWithRetry`)
- Treats any response with `success: false` as an error

**API modules** mirror the three Flask blueprints:
- `frontend/src/api/graph.js` → `/api/graph/*` (project + graph lifecycle)
- `frontend/src/api/simulation.js` → `/api/simulation/*` (simulation lifecycle + interview)
- `frontend/src/api/report.js` → `/api/report/*` (report generation + chat)

**Flask app factory** (`backend/app/__init__.py`):
- CORS enabled for all `/api/*` routes
- Three blueprints registered: `graph_bp` at `/api/graph`, `simulation_bp` at `/api/simulation`, `report_bp` at `/api/report`
- `SimulationRunner.register_cleanup()` is called at startup to install SIGTERM/SIGINT/SIGHUP handlers and an `atexit` hook, ensuring all child simulation processes are killed on server shutdown

---

## 2. Frontend Page Flow

The router (`frontend/src/router/index.js`) defines six routes that follow the sequential workflow:

| Route | View | Purpose |
|---|---|---|
| `/` | `Home.vue` | Upload documents, enter simulation requirement |
| `/process/:projectId` | `MainView.vue` | Steps 1–2: build graph, set up simulation environment |
| `/simulation/:simulationId` | `SimulationView.vue` | Step 3: configure and start simulation |
| `/simulation/:simulationId/start` | `SimulationRunView.vue` | Real-time simulation monitoring |
| `/report/:reportId` | `ReportView.vue` | Step 4: view generated report |
| `/interaction/:reportId` | `InteractionView.vue` | Step 5: chat with Report Agent |

`MainView.vue` hosts a split-panel layout: the left panel shows the Zep knowledge graph (`GraphPanel`), the right panel renders step components (`Step1GraphBuild`, `Step2EnvSetup`). A header step counter tracks progress (Step 1–5 shown as `Step N/5`).

---

## 3. Simulation Pipeline: Upload → Ontology → Graph → Agents → Simulation → Report

### Step 1 — Upload & Ontology Generation

**Endpoint**: `POST /api/graph/ontology/generate` (multipart/form-data)

1. Files (PDF/MD/TXT) are saved to a per-project directory under `uploads/projects/`.
2. `FileParser.extract_text()` pulls raw text from each file.
3. `TextProcessor.preprocess_text()` cleans it.
4. `OntologyGenerator.generate()` sends all document text plus the simulation requirement to the LLM (via `LLMClient`).
5. The LLM returns a JSON ontology: exactly 10 `entity_types` (PascalCase) and N `edge_types` (UPPER_SNAKE_CASE), each with attributes and source/target constraints.
6. The ontology is persisted into `Project.ontology` (saved as `state.json` on disk). Status transitions: `CREATED` → `ONTOLOGY_GENERATED`.

**Key constraint from prompt**: entities must be real-world actors capable of speaking on social media (people, companies, organizations, media). Abstract concepts are forbidden.

### Step 2 — Graph Building (Zep)

**Endpoint**: `POST /api/graph/build` (async — returns a `task_id` immediately)

The actual work runs in a background daemon thread managed by `GraphBuilderService`:

1. **Create graph**: `client.graph.create(graph_id=f"mirofish_{uuid}")` — Zep graph ID has the `mirofish_` prefix.
2. **Set ontology**: Entity types and edge types are dynamically constructed as Pydantic subclasses of `EntityModel` / `EdgeModel` (using `type()` to create classes at runtime) and pushed to Zep via `client.graph.set_ontology()`.
3. **Chunk text**: `TextProcessor.split_text()` splits the full document text (chunk_size=500, overlap=50 by default).
4. **Batch ingest**: Chunks are wrapped in `EpisodeData(data=chunk, type="text")` and sent 3 at a time via `client.graph.add_batch()`. Episode UUIDs are collected.
5. **Wait for processing**: `_wait_for_episodes()` polls each episode via `client.graph.episode.get(uuid_=ep_uuid)` checking the `processed` attribute every 1.5 seconds (timeout 600s).
6. **Fetch result**: `get_graph_data()` paginates nodes and edges from Zep via `fetch_all_nodes()` / `fetch_all_edges()` (in `utils/zep_paging.py`).

Progress is reported via `TaskManager` (singleton, in-memory, thread-safe) at 5 → 15 → 55 → 90 → 100%. The frontend polls `GET /api/graph/task/{task_id}` to track progress.

### Step 3 — Simulation Preparation

**Endpoint**: `POST /api/simulation/prepare` (async task)

`SimulationManager.prepare_simulation()` orchestrates five sub-steps, optionally with parallelism:

1. **Read entities from Zep**: `ZepEntityReader` fetches all nodes from the graph and filters them by entity type (respecting `defined_entity_types` if provided). The result is a `FilteredEntities` object.
2. **Generate OASIS agent profiles**: `OasisProfileGenerator` converts each `EntityNode` from Zep into an `OasisAgentProfile`. The profile has fields for both Reddit format (`username`, `bio`, `karma`) and Twitter format (`friend_count`, `follower_count`, `statuses_count`). Profile generation can optionally call the LLM to enrich persona details using Zep retrieval for context. `parallel_profile_count` profiles are generated concurrently via `concurrent.futures.ThreadPoolExecutor`.
3. **Generate simulation config**: `SimulationConfigGenerator` uses a staged LLM strategy (four separate LLM calls) to produce:
   - Time configuration (total hours, minutes per round)
   - Event configuration (seed events / triggers)
   - Agent activity configs (`AgentActivityConfig`): activity level 0–1, posts/comments per hour, active hours, sentiment bias, stance, influence weight. A China-timezone activity schedule (`CHINA_TIMEZONE_CONFIG`) is baked in with peak hours at 19–22 and dead hours at 0–5.
   - Platform configuration
4. **Save files**: `simulation_config.json` and profile JSON files are written to `uploads/simulations/{simulation_id}/`.
5. **Copy preset scripts**: The three OASIS runner scripts (`run_twitter_simulation.py`, `run_reddit_simulation.py`, `run_parallel_simulation.py`) from `backend/scripts/` are made available to the simulation subprocess.

### Step 4 — Running the Simulation

**Endpoint**: `POST /api/simulation/start`

`SimulationRunner.start_simulation()` launches one of three scripts as a child subprocess:
- `run_twitter_simulation.py` (Twitter only)
- `run_reddit_simulation.py` (Reddit only)
- `run_parallel_simulation.py` (both platforms in parallel, the default)

The subprocess is started with `start_new_session=True` (Unix: creates a process group for `os.killpg` termination; Windows: uses `taskkill /T`). `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8` are set in the subprocess environment.

**Monitoring**: A daemon thread (`_monitor_simulation`) reads two JSONL log files every 2 seconds:
- `uploads/simulations/{sim_id}/twitter/actions.jsonl`
- `uploads/simulations/{sim_id}/reddit/actions.jsonl`

Each line is either an event record (`event_type: simulation_end / round_end`) or an `AgentAction` record (with `agent_id`, `action_type`, `action_args`, etc.). The monitor increments per-platform round counters and detects completion via `simulation_end` events.

**Interview feature**: While the simulation is running (or paused after completion), the backend can inject interview commands via a filesystem-based IPC (`SimulationIPC`): Flask writes command JSON files to `commands/`, the simulation script polls and writes responses to `responses/`. Interview results are also persisted in SQLite databases (`twitter_simulation.db`, `reddit_simulation.db`) in the `trace` table with `action = 'interview'`.

### Step 5 — Report Generation

**Endpoint**: `POST /api/report/generate` (async task)

`ReportAgent` uses a ReACT-style multi-step workflow with LangChain + Zep retrieval:

1. **Planning**: The agent generates a report outline (section list).
2. **Section-by-section generation**: For each section, the agent iterates through tool calls and LLM responses until the section is complete. Tools available:
   - `InsightForge`: deep hybrid retrieval with automatic sub-question decomposition
   - `PanoramaSearch`: broad retrieval including expired/invalidated edges
   - `QuickSearch`: lightweight direct graph search via `client.graph.search()`
   - `InterviewResult`: fetches saved interview responses from the SQLite databases
3. **Section persistence**: Each section is written to `uploads/reports/{report_id}/section_{N:02d}.md` incrementally, so the frontend can poll for partial content.
4. **Logging**: `ReportLogger` writes structured JSONL to `agent_log.jsonl` (one entry per action: `start`, `tool_call`, `llm_response`, `section_complete`) and plain-text to `console_log.txt`.

The frontend can stream progress via:
- `GET /api/report/{id}/progress` — current stage, percent, current section
- `GET /api/report/{id}/sections` — list of completed sections with content
- `GET /api/report/{id}/agent-log?from_line=N` — incremental structured logs
- `GET /api/report/{id}/console-log?from_line=N` — incremental plain-text logs
- `POST /api/report/chat` — chat with the Report Agent using saved `chat_history`

The "interview unlocked" flag (`interview_unlocked: true`) is set only after the report status reaches `COMPLETED` (checked via `GET /api/report/check/{simulation_id}`).

---

## 4. Zep Memory — How It Is Used

Zep is the central knowledge store. It is used in three distinct ways:

### 4a. Static Knowledge Graph (from documents)
Built in Step 2. The Zep graph stores extracted entities (nodes) and relationships (edges) with temporal metadata (`valid_at`, `invalid_at`, `expired_at`). This graph represents the real-world context extracted from the uploaded research documents.

### 4b. Agent Profile Enrichment (read-only at preparation time)
`OasisProfileGenerator` calls `ZepEntityReader` to read node summaries and attributes from the graph, feeding that context to the LLM when generating detailed agent personas for OASIS.

### 4c. Live Memory Update During Simulation (write, optional)
If `enable_graph_memory_update=True` is passed to `SimulationRunner.start_simulation()`, a `ZepGraphMemoryManager` is created. As the monitor thread reads each `AgentAction` from `actions.jsonl`, it calls `graph_updater.add_activity_from_dict()`, which converts agent actions (CREATE_POST, LIKE_POST, REPOST, etc.) into natural-language text episodes and sends them to Zep via `client.graph.add`. This means simulation outcomes (what agents posted, liked, followed) are written back into the Zep graph in real time, enriching the knowledge base with simulation events.

### 4d. Report-Time Retrieval (read)
`ZepToolsService` wraps three retrieval patterns for the Report Agent:
- `search_graph()`: calls `client.graph.search()` with a text query
- `InsightForge`: generates sub-questions from a high-level topic, runs multiple searches, and synthesizes results with an LLM
- `PanoramaSearch`: fetches all nodes and edges (paginated) for a broad overview

---

## 5. OASIS — How It Fits In

OASIS is the underlying social simulation framework. MiroFish treats it as a subprocess:

- The three runner scripts (`run_twitter_simulation.py`, `run_reddit_simulation.py`, `run_parallel_simulation.py`) are Python programs that import and run the OASIS library.
- They receive `--config simulation_config.json` as a CLI argument.
- The config contains: agent profiles (converted to OASIS format via `to_reddit_format()` / `to_twitter_format()`), time configuration, activity levels, event seeds, and platform settings.
- OASIS agents act autonomously each round (CREATE_POST, LIKE_POST, REPOST, FOLLOW, CREATE_COMMENT, etc.) and write action records to per-platform `actions.jsonl` files.
- The Flask backend never directly calls OASIS Python APIs — it only reads the JSONL output files and sends IPC commands for interviews.
- OASIS stores its internal simulation state in SQLite databases (`twitter_simulation.db`, `reddit_simulation.db`), which the backend reads directly for interview history.

---

## 6. Data Persistence Layout

All server-side state is stored on disk (no external database beyond Zep and SQLite):

```
backend/uploads/
  projects/{project_id}/
    state.json               # Project model: ontology, graph_id, status
    extracted_text.txt       # Full concatenated document text
    {uploaded files}

  simulations/{simulation_id}/
    state.json               # SimulationState: project_id, graph_id, status
    simulation_config.json   # Full OASIS config (agents, time, events, platform)
    run_state.json           # SimulationRunState: round counters, action list
    simulation.log           # Subprocess stdout/stderr
    env_status.json          # IPC environment alive status
    commands/                # IPC command files (Flask → simulation)
    responses/               # IPC response files (simulation → Flask)
    twitter/
      actions.jsonl          # Twitter agent action log
    reddit/
      actions.jsonl          # Reddit agent action log
    twitter_simulation.db    # OASIS Twitter SQLite database
    reddit_simulation.db     # OASIS Reddit SQLite database

  reports/{report_id}/
    report.json              # Report metadata + markdown_content
    section_01.md ... N.md   # Per-section markdown files
    agent_log.jsonl          # Structured ReACT step log
    console_log.txt          # Plain-text log
```

Tasks (`TaskManager`) are held only in memory (singleton, lost on restart). Projects and simulations survive restarts because state is read from disk on first access.
