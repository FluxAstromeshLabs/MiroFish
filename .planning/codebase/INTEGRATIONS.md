# MiroFish External Integrations

Sources: `backend/app/config.py`, `backend/app/utils/llm_client.py`, `backend/app/services/zep_tools.py`, `backend/app/services/zep_graph_memory_updater.py`, `backend/app/services/oasis_profile_generator.py`, `backend/app/services/simulation_runner.py`, `.env.example`

---

## 1. LLM API (Primary)

**What it does:** Provides the language model backbone for all reasoning tasks — ontology extraction from documents, agent persona generation, sub-question decomposition (InsightForge), agent selection and question generation for interviews, report writing, and JSON-structured responses.

**Provider flexibility:** Any OpenAI-API-compatible endpoint. The `.env.example` recommends Alibaba DashScope's `qwen-plus` model, but the default in code falls back to `gpt-4o-mini` at `https://api.openai.com/v1`.

**SDK:** `openai>=1.0.0` — `openai.OpenAI(api_key=..., base_url=...)` with `client.chat.completions.create()`

**Configuration (env vars):**

| Variable | Default | Notes |
|---|---|---|
| `LLM_API_KEY` | (required) | API key for the LLM provider |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | Base URL; set to DashScope or any OpenAI-compatible endpoint |
| `LLM_MODEL_NAME` | `gpt-4o-mini` | Model identifier |

**Where used:**
- `backend/app/utils/llm_client.py` — `LLMClient` class wraps all calls; exposes `chat()` and `chat_json()` methods
- `backend/app/services/zep_tools.py` — `ZepToolsService._generate_sub_queries()`, `_select_agents_for_interview()`, `_generate_interview_questions()`, `_generate_interview_summary()`
- `backend/app/services/oasis_profile_generator.py` — generates detailed agent personas from Zep graph entities
- `backend/app/services/ontology_generator.py` — extracts entities/relationships from uploaded documents
- `backend/app/services/report_agent.py` — agentic report writing

**Notable behavior:** Strips `<think>...</think>` blocks from responses (compatibility with MiniMax M2.5 and similar models). Cleans Markdown code fences from JSON responses.

---

## 2. LLM API (Boost / Optional)

**What it does:** Optional secondary LLM endpoint for faster or cheaper calls on specific tasks. Not present in code by default — only activated when all three `LLM_BOOST_*` env vars are set.

**Configuration (env vars):**

| Variable | Notes |
|---|---|
| `LLM_BOOST_API_KEY` | API key for the boost provider |
| `LLM_BOOST_BASE_URL` | Base URL for the boost provider |
| `LLM_BOOST_MODEL_NAME` | Model name for the boost provider |

**Note from `.env.example`:** If these vars are not needed, they must be entirely absent from the `.env` file (not just empty).

---

## 3. Zep Cloud (Memory Graph)

**What it does:** Acts as the long-term, temporal knowledge graph that stores entities, relationships (edges), and facts extracted from documents and simulation events. Is central to the retrieval pipeline for report generation.

**SDK:** `zep-cloud==3.13.0` — `zep_cloud.client.Zep(api_key=...)`

**Configuration (env vars):**

| Variable | Notes |
|---|---|
| `ZEP_API_KEY` | Required. Free-tier available at https://app.getzep.com/ |

**Key API calls made:**

| Operation | Zep API | Used in |
|---|---|---|
| Graph search (hybrid semantic + BM25 + cross-encoder rerank) | `client.graph.search(graph_id, query, limit, scope, reranker="cross_encoder")` | `ZepToolsService.search_graph()` |
| Fetch all nodes (paginated) | `client.graph.node.list(graph_id, ...)` via `fetch_all_nodes()` | `ZepToolsService.get_all_nodes()` |
| Fetch all edges (paginated, incl. temporal fields) | `client.graph.edge.list(graph_id, ...)` via `fetch_all_edges()` | `ZepToolsService.get_all_edges()` |
| Fetch single node detail | `client.graph.node.get(uuid_=node_uuid)` | `ZepToolsService.get_node_detail()` |
| Add episode (write activity to graph) | `client.graph.add(graph_id, type="text", data=episode_text)` | `ZepGraphMemoryUpdater` |

**Graph data model used:**
- **Nodes** — entities with `name`, `labels` (type tags), `summary`, `attributes`
- **Edges** — relationships with `name`, `fact` text, `source_node_uuid`, `target_node_uuid`, temporal fields: `created_at`, `valid_at`, `invalid_at`, `expired_at`

**High-level retrieval tools built on top of Zep (in `zep_tools.py`):**

| Tool | Description |
|---|---|
| `InsightForge` | LLM decomposes question into sub-queries → multi-query semantic search → entity detail fetch → relationship chain building |
| `PanoramaSearch` | Fetches ALL nodes and edges; classifies facts as active vs. historical/expired |
| `QuickSearch` | Direct single-query semantic search |
| `InterviewAgents` | Reads agent profile files, LLM selects agents, calls live OASIS interview IPC, formats responses |

**Fallback:** If the Zep Cloud search API is unavailable, `ZepToolsService._local_search()` fetches all edges/nodes and does local keyword matching.

**Graph memory update during simulation:** `ZepGraphMemoryManager` (in `zep_graph_memory_updater.py`) runs a background thread that reads `actions.jsonl` entries and converts each agent action into a natural-language episode text, then writes it to Zep via `client.graph.add()`. Enabled per-simulation via `enable_graph_memory_update=True` flag on `SimulationRunner.start_simulation()`.

---

## 4. OASIS (camel-oasis Social Media Simulation)

**What it does:** Provides the multi-agent social simulation engine. Simulates LLM-powered agents interacting on Twitter-like and Reddit-like virtual platforms. Each agent is driven by an LLM and executes platform actions (posts, likes, follows, comments, etc.) each round.

**SDK:** `camel-oasis==0.2.5` (depends on `camel-ai==0.2.78`)

**Configuration (env vars):**

| Variable | Default | Notes |
|---|---|---|
| `OASIS_DEFAULT_MAX_ROUNDS` | `10` | Default max simulation rounds |

**Available platform actions (from `config.py`):**

- **Twitter:** `CREATE_POST`, `LIKE_POST`, `REPOST`, `FOLLOW`, `DO_NOTHING`, `QUOTE_POST`
- **Reddit:** `LIKE_POST`, `DISLIKE_POST`, `CREATE_POST`, `CREATE_COMMENT`, `LIKE_COMMENT`, `DISLIKE_COMMENT`, `SEARCH_POSTS`, `SEARCH_USER`, `TREND`, `REFRESH`, `DO_NOTHING`, `FOLLOW`, `MUTE`

**Execution model:**
- `SimulationRunner.start_simulation()` launches one of three scripts as a background subprocess:
  - `backend/scripts/run_twitter_simulation.py`
  - `backend/scripts/run_reddit_simulation.py`
  - `backend/scripts/run_parallel_simulation.py` (dual-platform, parallel)
- Subprocesses write JSONL action logs (`twitter/actions.jsonl`, `reddit/actions.jsonl`) and SQLite databases (`twitter_simulation.db`, `reddit_simulation.db`)
- A monitoring thread reads these logs every 2 seconds and updates in-memory + on-disk `run_state.json`

**IPC for live agent interviews:** `SimulationIPCClient` (file-based IPC in `simulation_ipc.py`) sends `interview`, `batch_interview`, and `close_env` commands to running simulation processes. Agents respond from within the live OASIS environment using their accumulated memory and persona.

**Agent profile sources:**
- `reddit_profiles.json` — preferred format (JSON array with `realname`, `username`, `bio`, `persona`, `profession`, `interested_topics`)
- `twitter_profiles.csv` — fallback format (CSV with `name`, `username`, `description`, `user_char`)

**Profile generation:** `OasisAgentProfileGenerator` reads entity nodes from the Zep graph and uses the LLM to synthesize detailed OASIS-compatible agent personas (age, gender, MBTI, country, profession, interested topics, bio, persona narrative).

---

## 5. Alibaba DashScope (Recommended LLM Provider)

**What it does:** The recommended LLM provider as documented in `.env.example`. Hosts the `qwen-plus` model accessible via an OpenAI-compatible API endpoint. No dedicated SDK — accessed through the `openai` SDK with a custom `base_url`.

**Endpoint:** `https://dashscope.aliyuncs.com/compatible-mode/v1`

**Configuration:** Set `LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1` and `LLM_MODEL_NAME=qwen-plus` in `.env`. The comment in `.env.example` notes that consumption is significant and recommends starting with fewer than 40 simulation rounds.

---

## Summary Table

| Integration | Type | Required | Config Vars | SDK/Method |
|---|---|---|---|---|
| LLM API (Primary) | AI inference | Yes | `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_NAME` | `openai>=1.0.0` |
| LLM API (Boost) | AI inference | No | `LLM_BOOST_API_KEY`, `LLM_BOOST_BASE_URL`, `LLM_BOOST_MODEL_NAME` | `openai>=1.0.0` |
| Zep Cloud | Memory/Knowledge graph | Yes | `ZEP_API_KEY` | `zep-cloud==3.13.0` |
| OASIS | Social simulation | Yes (local) | `OASIS_DEFAULT_MAX_ROUNDS` | `camel-oasis==0.2.5` |
| Alibaba DashScope | LLM provider (recommended) | No (optional provider) | via `LLM_BASE_URL` | openai SDK |
