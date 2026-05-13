# MiroFish Technology Stack

Sources: `package.json`, `frontend/package.json`, `backend/requirements.txt`, `backend/pyproject.toml`, `docker-compose.yml`, `backend/app/config.py`, `backend/app/utils/llm_client.py`

---

## Frontend

| Technology | Version | Role |
|---|---|---|
| Vue 3 | ^3.5.24 | UI framework |
| Vue Router | ^4.6.3 | Client-side routing |
| Vite | ^7.2.4 | Build tool and dev server (`vite --host`) |
| @vitejs/plugin-vue | ^6.0.1 | Vue SFC support in Vite |
| Axios | ^1.13.2 | HTTP client for API calls to backend |
| D3.js | ^7.9.0 | Data visualization (graph rendering) |

**Language:** JavaScript (ESM, `"type": "module"`)
**Node requirement:** `>=18.0.0`
**Dev server port:** 3000 (exposed in Docker)

---

## Backend

### Runtime & Framework

| Technology | Version | Role |
|---|---|---|
| Python | >=3.11 | Runtime language |
| Flask | >=3.0.0 | REST API web framework |
| flask-cors | >=6.0.0 | Cross-origin request handling |
| uv | (via `uv sync` / `uv run`) | Python package manager and runner |
| hatchling | (build-system) | Python package build backend |

**Backend port:** 5001 (exposed in Docker)
**Entry point:** `backend/run.py` via `uv run python run.py`

### LLM / AI Client

| Technology | Version | Role |
|---|---|---|
| openai | >=1.0.0 | OpenAI-compatible SDK used as unified LLM client |

The `LLMClient` wrapper (`backend/app/utils/llm_client.py`) instantiates `openai.OpenAI` with a configurable `base_url`, allowing any OpenAI-API-compatible provider to be substituted (OpenAI, Alibaba Qwen via DashScope, MiniMax, etc.).

### Simulation Framework

| Technology | Version | Role |
|---|---|---|
| camel-oasis | 0.2.5 | OASIS social-media simulation (dual-platform: Twitter + Reddit) |
| camel-ai | 0.2.78 | Multi-agent AI library (dependency of camel-oasis) |

OASIS simulations run as background subprocesses launched by `SimulationRunner`. Platform scripts (`run_twitter_simulation.py`, `run_reddit_simulation.py`, `run_parallel_simulation.py`) live in `backend/scripts/`. Each simulation writes per-platform `actions.jsonl` logs and SQLite databases (`twitter_simulation.db`, `reddit_simulation.db`).

### Memory / Graph

| Technology | Version | Role |
|---|---|---|
| zep-cloud | 3.13.0 | Temporal knowledge graph as agent memory store |

Zep is used via `zep_cloud.client.Zep`. The `ZepToolsService` class wraps graph search, node/edge reads, and agent interview flows. The `ZepGraphMemoryManager` streams live simulation actions into Zep graphs using episode text.

### File Processing

| Technology | Version | Role |
|---|---|---|
| PyMuPDF | >=1.24.0 | PDF parsing and text extraction |
| charset-normalizer | >=3.0.0 | Encoding detection for non-UTF-8 text files |
| chardet | >=5.0.0 | Secondary encoding detection library |

### Utilities

| Technology | Version | Role |
|---|---|---|
| pydantic | >=2.0.0 | Data validation and settings models |
| python-dotenv | >=1.0.0 | `.env` file loading at startup |

**Config loading:** `backend/app/config.py` loads from `{project_root}/.env` with override. Falls back to process environment if `.env` is absent.

### Development / Testing

| Technology | Version | Role |
|---|---|---|
| pytest | >=8.0.0 | Test runner |
| pytest-asyncio | >=0.23.0 | Async test support |
| pipreqs | >=0.5.0 | Requirements generation helper |
| concurrently | ^9.1.2 | Root-level dev runner (launches backend + frontend together) |

---

## Infrastructure

| Technology | Details | Role |
|---|---|---|
| Docker | `ghcr.io/666ghj/mirofish:latest` | Container image for production deployment |
| docker-compose | Single-service `mirofish` | Orchestrates container with port mapping and volume mount |
| Volumes | `./backend/uploads:/app/backend/uploads` | Persists uploaded files and simulation artifacts |
| Ports | 3000 (frontend), 5001 (backend) | Both exposed from container |
| Restart policy | `unless-stopped` | Auto-restart on crash |

**Alternative mirror image:** `ghcr.nju.edu.cn/666ghj/mirofish:latest` (NJU mirror for China)

**File storage layout (local, not a hosted DB):**
- `backend/uploads/` — uploaded source documents (PDF, MD, TXT)
- `backend/uploads/simulations/{simulation_id}/` — per-simulation artifacts:
  - `simulation_config.json`, `run_state.json`
  - `twitter/actions.jsonl`, `reddit/actions.jsonl`
  - `twitter_simulation.db`, `reddit_simulation.db` (SQLite)
  - `twitter_profiles.csv`, `reddit_profiles.json`
  - `simulation.log`

**IPC mechanism:** File-based IPC (`SimulationIPCClient`) for sending interview/close commands to running simulation subprocesses.

---

## AI/ML

| Component | Technology | Notes |
|---|---|---|
| LLM inference | OpenAI SDK (`openai>=1.0.0`) pointing to configurable endpoint | Default model `gpt-4o-mini`; `.env.example` recommends `qwen-plus` via Alibaba DashScope |
| Optional boost LLM | Second `LLMClient` instance | Configured via `LLM_BOOST_*` env vars for faster/cheaper calls |
| Social simulation | camel-oasis 0.2.5 + camel-ai 0.2.78 | Multi-agent Twitter + Reddit simulation |
| Knowledge graph | zep-cloud 3.13.0 | Temporal graph memory; stores entities, relationships, and simulation facts |
| Graph search | Zep hybrid search (semantic + BM25 + cross-encoder reranking) | Falls back to local keyword matching if Zep Cloud search API unavailable |
| Agent profiling | `OasisAgentProfileGenerator` | Reads Zep graph nodes, uses LLM to generate detailed OASIS agent personas |
| Ontology generation | `OntologyGenerator` service | LLM-driven extraction of entities/relationships from uploaded documents |
| Report generation | `ReportAgent` service | Agentic report writer using tool calls into Zep (`InsightForge`, `PanoramaSearch`, `QuickSearch`, `InterviewAgents`) |
| PDF parsing | PyMuPDF >=1.24.0 | Extracts text from uploaded PDFs for knowledge ingestion |
| Graph visualization | D3.js ^7.9.0 (frontend) | Renders the Zep knowledge graph in the browser |
