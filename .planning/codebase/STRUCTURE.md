# MiroFish — Directory Structure

```
Mirofish/
├── backend/                            # Flask Python backend
│   ├── run.py                          # Entry point: validates Config, starts Flask on port 5001 (threaded=True)
│   ├── requirements.txt                # Python dependencies (Flask, zep-cloud, openai, langchain, etc.)
│   ├── pyproject.toml                  # uv project metadata
│   ├── uv.lock                         # uv lockfile
│   │
│   ├── app/
│   │   ├── __init__.py                 # Flask app factory: CORS, blueprints, cleanup registration
│   │   ├── config.py                   # Config class: reads .env, validates ZEP_API_KEY / OPENAI_API_KEY
│   │   │
│   │   ├── api/
│   │   │   ├── __init__.py             # Blueprint definitions: graph_bp, simulation_bp, report_bp
│   │   │   ├── graph.py                # /api/graph/* — project CRUD, ontology generation, graph build, task polling
│   │   │   ├── simulation.py           # /api/simulation/* — create/prepare/start/stop/status/interview endpoints
│   │   │   └── report.py               # /api/report/* — generate, status, get, sections, chat, agent-log, console-log
│   │   │
│   │   ├── models/
│   │   │   ├── project.py              # Project dataclass + ProjectManager (disk persistence); ProjectStatus enum
│   │   │   └── task.py                 # Task dataclass + TaskManager (in-memory singleton, thread-safe); TaskStatus enum
│   │   │
│   │   ├── services/
│   │   │   ├── ontology_generator.py   # LLM-driven ontology generator: produces 10 entity types + edge types from document text
│   │   │   ├── graph_builder.py        # GraphBuilderService: creates Zep graph, sets ontology, batch-ingests text chunks, waits for episode processing
│   │   │   ├── simulation_manager.py   # SimulationManager: reads Zep entities, generates profiles, generates config, saves simulation files
│   │   │   ├── simulation_runner.py    # SimulationRunner: spawns OASIS subprocess, monitors actions.jsonl, handles stop/interview/IPC
│   │   │   ├── simulation_config_generator.py  # 4-stage LLM config generator: time, events, agent activity, platform config; China timezone schedule
│   │   │   ├── simulation_ipc.py       # Filesystem IPC client: writes commands/ reads responses/ for interview commands to running simulation
│   │   │   ├── oasis_profile_generator.py      # Converts Zep EntityNode → OasisAgentProfile (Reddit + Twitter formats); optional LLM persona enrichment
│   │   │   ├── report_agent.py         # ReACT-style report generator: plans outline, generates sections, writes section_N.md files; ReportLogger (JSONL)
│   │   │   ├── zep_tools.py            # ZepToolsService: InsightForge (deep hybrid), PanoramaSearch (broad), QuickSearch (direct) retrieval wrappers
│   │   │   ├── zep_entity_reader.py    # ZepEntityReader: reads and filters entity nodes from Zep graph; produces FilteredEntities
│   │   │   ├── zep_graph_memory_updater.py     # ZepGraphMemoryManager: streams agent actions (CREATE_POST, LIKE, REPOST…) back into Zep as episodes during simulation
│   │   │   └── text_processor.py       # TextProcessor: preprocess_text, split_text (chunking with overlap)
│   │   │
│   │   └── utils/
│   │       ├── file_parser.py          # FileParser.extract_text(): reads PDF, Markdown, and plain text files
│   │       ├── llm_client.py           # LLMClient: thin wrapper around OpenAI client; shared across all LLM callers
│   │       ├── logger.py               # setup_logger / get_logger: structured logging with named loggers
│   │       ├── retry.py                # Retry decorator / helper for transient failures
│   │       └── zep_paging.py           # fetch_all_nodes / fetch_all_edges: paginated Zep graph node/edge fetchers
│   │
│   └── scripts/
│       ├── run_twitter_simulation.py   # OASIS Twitter simulation runner script (called as subprocess)
│       ├── run_reddit_simulation.py    # OASIS Reddit simulation runner script (called as subprocess)
│       ├── run_parallel_simulation.py  # OASIS parallel (Twitter + Reddit) simulation runner script
│       ├── action_logger.py            # Shared action-logging helper used by OASIS scripts to write actions.jsonl
│       └── test_profile_format.py      # Dev utility: test/validate OASIS profile JSON format
│
├── frontend/                           # Vue 3 + Vite SPA
│   ├── package.json                    # npm config; Vite, Vue 3, Vue Router, Axios, ECharts
│   ├── src/
│   │   ├── main.js                     # App bootstrap: createApp, mount, router
│   │   ├── App.vue                     # Root component (minimal shell)
│   │   │
│   │   ├── api/
│   │   │   ├── index.js                # Axios instance (baseURL=localhost:5001, 5min timeout, retry helper)
│   │   │   ├── graph.js                # Calls to /api/graph/* (upload, build, task poll, graph data)
│   │   │   ├── simulation.js           # Calls to /api/simulation/* (create, prepare, start, stop, status, interview)
│   │   │   └── report.js               # Calls to /api/report/* (generate, sections, chat, download)
│   │   │
│   │   ├── router/
│   │   │   └── index.js                # 6 routes: Home, Process/:projectId, Simulation/:id, SimulationRun/:id, Report/:id, Interaction/:id
│   │   │
│   │   ├── store/
│   │   │   └── pendingUpload.js        # Pinia/reactive store: holds pending file upload state across navigation
│   │   │
│   │   ├── views/
│   │   │   ├── Home.vue                # Landing page: file upload dropzone + simulation requirement input
│   │   │   ├── MainView.vue            # Steps 1–2: split-panel (GraphPanel left, Step1/Step2 right); view mode switcher (graph/split/workbench)
│   │   │   ├── Process.vue             # Alternative process view (legacy or secondary path)
│   │   │   ├── SimulationView.vue      # Step 3: simulation configuration UI (agent count, platform, rounds)
│   │   │   ├── SimulationRunView.vue   # Real-time simulation monitor: round counters, action feed, per-platform status
│   │   │   ├── ReportView.vue          # Step 4: renders report sections as they arrive; download button
│   │   │   └── InteractionView.vue     # Step 5: chat UI for conversing with the Report Agent
│   │   │
│   │   └── components/
│   │       ├── GraphPanel.vue          # Force-directed graph visualization of Zep nodes/edges (ECharts or D3)
│   │       ├── HistoryDatabase.vue     # Browse past projects/simulations from local history
│   │       ├── Step1GraphBuild.vue     # UI for ontology generation progress + graph build progress bars
│   │       ├── Step2EnvSetup.vue       # UI for simulation environment preparation (entity count, profile generation progress)
│   │       ├── Step3Simulation.vue     # Simulation configuration form component
│   │       ├── Step4Report.vue         # Report streaming component (section-by-section display)
│   │       └── Step5Interaction.vue    # Agent interview / chat component
│   │
│   └── assets/
│       └── logo/                       # MiroFish logo images
│
├── research/                           # Research notes and reference materials (not deployed)
├── static/                             # Static assets served separately
├── docker-compose.yml                  # Composes frontend (Vite dev server) + backend (Flask) services
├── Dockerfile                          # Container build for backend
├── package.json                        # Root-level scripts (likely for running both services)
├── README.md                           # Project README (Chinese)
└── README-EN.md                        # Project README (English)
```

---

## Key Files Quick Reference

| File | What it does |
|---|---|
| `backend/run.py` | Single entry point; starts Flask on 0.0.0.0:5001 |
| `backend/app/__init__.py` | App factory; registers 3 blueprints + cleanup hooks |
| `backend/app/api/graph.py` | REST layer for project + graph lifecycle |
| `backend/app/api/simulation.py` | REST layer for simulation + interview |
| `backend/app/api/report.py` | REST layer for report generation + streaming + chat |
| `backend/app/services/ontology_generator.py` | LLM → structured ontology (entity/edge types) |
| `backend/app/services/graph_builder.py` | Zep graph creation, ontology push, episode batch ingest |
| `backend/app/services/simulation_manager.py` | Entity read → profile generate → config generate → file save |
| `backend/app/services/oasis_profile_generator.py` | EntityNode → OasisAgentProfile (Reddit + Twitter formats) |
| `backend/app/services/simulation_config_generator.py` | 4-stage LLM config generation with China timezone schedule |
| `backend/app/services/simulation_runner.py` | Subprocess launch, JSONL monitor, stop/interview/IPC |
| `backend/app/services/simulation_ipc.py` | Filesystem command/response IPC for live agent interviews |
| `backend/app/services/report_agent.py` | ReACT report generator; writes section files + JSONL log |
| `backend/app/services/zep_tools.py` | InsightForge / PanoramaSearch / QuickSearch retrieval tools |
| `backend/app/services/zep_entity_reader.py` | Read + filter entity nodes from Zep |
| `backend/app/services/zep_graph_memory_updater.py` | Stream agent actions back into Zep during simulation |
| `backend/app/models/project.py` | Project state machine (CREATED → ONTOLOGY_GENERATED → GRAPH_BUILDING → GRAPH_COMPLETED) |
| `backend/app/models/task.py` | Singleton in-memory task tracker for async long-running jobs |
| `backend/app/utils/zep_paging.py` | Pagination helpers for Zep node/edge fetching |
| `backend/scripts/run_parallel_simulation.py` | Main OASIS subprocess; runs Twitter + Reddit in parallel |
| `frontend/src/api/index.js` | Axios client with retry + 5-min timeout |
| `frontend/src/router/index.js` | 6-route SPA navigation matching the 5-step workflow |
| `frontend/src/views/MainView.vue` | Primary workbench: graph visualization + step panels |
