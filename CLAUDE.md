# Mirofish

Social simulation engine being extended into a **crypto market prediction system**.
Feed OHLCV + sentiment → simulate capital-weighted agents → extract price range prediction.

**Goal:** `python run_pipeline.py --backtest` prints: `Prediction: $95k–$102k | Actual: $97.2k | IN RANGE ✓`

## Current Phase

Phase 1 ✅ done (cleanup, hardcodes removed, configurable agent count/timezone).
Now on **Phase 2**: automate graph → simulate → predict → backtest into one pipeline call.
Full roadmap: `.planning/ROADMAP.md` | Requirements: `.planning/REQUIREMENTS.md`

## Tech Stack

- **Frontend**: Vue 3, Vite, Vue Router, Axios, D3
- **Backend**: Python 3.11+, Flask (sync), `uv` for deps
- **LLM**: Any OpenAI-compatible API — default is Alibaba Qwen via DashScope
- **Memory/Graph**: Zep Cloud (knowledge graph + temporal memory)
- **Simulation**: CAMEL-AI OASIS (subprocess-based multi-agent)

## Build & Run

```bash
npm run setup:all     # First-time: installs all deps (Node + Python via uv)
npm run dev           # Start backend + frontend concurrently
npm run backend       # Flask only  → http://localhost:5001
npm run frontend      # Vite only   → http://localhost:3000
docker compose up -d  # Docker deployment
```

## Conventions

**Python:**
- Logger: `logger = get_logger('mirofish.<module>')` at top of every file
- LLM calls: always go through `LLMClient` — `chat()` for text, `chat_json()` for structured output
- LLMClient has no built-in retry — wrap callers with `@retry_with_backoff` from `retry.py`
- Background tasks use `threading.Thread`, not `asyncio` — Flask is sync throughout
- API response envelope: `{"success": true, "data": {...}}` or `{"success": false, "error": "..."}`
- Dataclasses use `to_dict()` for JSON serialization (not Pydantic, even though it's installed)
- Naming: `snake_case` functions, `PascalCase` classes, `UPPER_SNAKE_CASE` constants, `_leading_underscore` private

**Vue:**
- State management: module-level `reactive()` singletons in `src/store/` — no Vuex/Pinia
- All HTTP calls through `api/index.js` axios instance — never create a new Axios instance
- Components follow 5-step workflow: Step1–Step5 map to the simulation pipeline stages

**General:**
- `.env` at project root, shared by frontend and backend
- New Flask blueprints register in `app/__init__.py:66-69` (follow existing pattern)
- OHLCV format: `T,O,H,L,C,V` — Unix millisecond timestamps, 60s candles

## 95% Confidence Rule

Do not make changes unless ≥95% confident about the impact. If uncertain:
1. State what you know and what you don't
2. Ask one focused question
3. Wait for confirmation before editing any file
