# Roadmap

## Phase 1 — Cleanup & Hardcoded Fixes ✅ DONE
**Goal:** Codebase is clean, configurable, and in English.
- Removed dead Chinese code, hardcoded Beijing timezone, REF-2024-X92 fallback, concat bug
- Made SIMULATION_AGENT_COUNT, SIMULATION_TIMEZONE, platform weights all env-var configurable
- Translated all Chinese strings in simulation.py and .env.example

---

## Phase 2 — Pipeline Automation
**Goal:** Single script call runs the full loop: graph → simulate → predict → backtest.
**Why:** Iteration speed. Can't tune the system if each run requires 3 manual API calls.

Tasks:
- 2.1: Add `POST /api/pipeline/run` endpoint — chains graph build (graph.py:260) → poll task (graph.py:530) → prepare (simulation.py:358) → poll prepare (simulation.py:638) → start (simulation.py:1446)
- 2.2: Add pipeline status SSE stream so caller can track progress across all stages
- 2.3: Add `POST /api/pipeline/backtest` — given a simulation_id and actual OHLCV CSV, scores the prediction against real price data
- 2.4: Add `run_pipeline.py` CLI script in `backend/scripts/` — calls the pipeline API end-to-end, prints results

**Key files:** `graph.py:260,477,511,530` | `simulation.py:358,428,638,1446,1599` | `simulation_manager.py:24-33,193,229`

**Success:** `python run_pipeline.py --project-id X --rounds 5` completes one full loop and prints a prediction.

---

## Phase 3 — OHLCV + Sentiment Data Bridge
**Goal:** OHLCV candles and sentiment posts feed into the Zep knowledge graph as episodes.
**Why:** Right now agents know nothing about markets. This gives them real data to reason about.

Tasks:
- 3.1: Add `backend/app/api/ohlcv.py` with `POST /api/ohlcv/ingest` — reads OHLCV CSV (T,O,H,L,C,V format), converts candles to narrative text episodes, calls `GraphBuilderService.add_text_batches()` (graph_builder.py:288)
- 3.2: Add `OHLCVProcessor` service in `backend/app/services/ohlcv_processor.py` — converts price candles into human-readable text: "BTC moved +3.2% from $95,000 to $98,040 with 2.1x average volume between 14:00-15:00 UTC"
- 3.3: Add `POST /api/ohlcv/sentiment` — accepts array of `{timestamp, text, source}`, converts to Zep episodes via same `add_text_batches()` path
- 3.4: Register blueprint in `app/__init__.py:66-69` (follow pattern of existing 3 blueprints)
- 3.5: Wire into pipeline — Phase 2's `run_pipeline.py` accepts `--ohlcv-file` and `--sentiment-file` args

**Key files:** `graph_builder.py:288,312-315` | `app/__init__.py:66-69` | `api/__init__.py:7-13` | OHLCV format: `T,O,H,L,C,V` Unix ms timestamps, 60s candles

**Success:** Feed 24h BTC OHLCV → Zep graph contains price movement entities agents can reference.

---

## Phase 4 — Capital-Weighted Agents
**Goal:** Agents reflect real market structure — whales move markets, retail follows.
**Why:** Equal-weight agents produce meaningless consensus. Capital weighting makes simulation realistic.

Tiers:
- WHALE: 1-5% of agents, 100x capital, high follower_count (50k-500k), high karma (10k-100k), influence_weight 8.0-10.0
- QUANT: 5-15% of agents, 10x capital, follower_count (5k-50k), karma (2k-10k), influence_weight 4.0-6.0
- RETAIL: 80-90% of agents, 1x capital, follower_count (10-500), karma (10-500), influence_weight 0.5-1.5

Tasks:
- 4.1: Add `AGENT_TIER` enum and `WHALE_PCT`, `QUANT_PCT` env vars to `config.py`
- 4.2: Extend `OasisProfileGenerator.generate_profile_from_entity()` (oasis_profile_generator.py:211) — assign tier based on entity type, set `karma` (line 261) and `follower_count` (line 263) from tier ranges instead of random
- 4.3: Extend `SimulationConfigGenerator._generate_agent_config_by_rule()` — add WHALE/QUANT/RETAIL cases to influence_weight assignment (currently lines 937-1002), map tier → influence_weight
- 4.4: Add `capital_tier` field to `AgentActivityConfig` dataclass (simulation_config_generator.py:80) and include in `SimulationParameters.to_dict()` (line 176)
- 4.5: Update LLM prompts in `_generate_agent_configs_batch()` (simulation_config_generator.py:878) to instruct whale/quant/retail behavior differences

**Key files:** `oasis_profile_generator.py:211,261,263` | `simulation_config_generator.py:80,176,812,878,937-1002`

**Success:** 10-agent sim has 1 whale (influence 9.0), 1 quant (5.0), 8 retail (1.0). Whale opinion demonstrably shifts retail sentiment in output.

---

## Phase 5 — Prediction Output + Backtest
**Goal:** Simulation outputs a structured price prediction. Backtest scores it against real data.

Tasks:
- 5.1: Add `PredictionExtractor` service in `backend/app/services/prediction_extractor.py` — reads `actions.jsonl` via `SimulationRunner.get_all_actions()` (simulation_runner.py:889), uses LLM to extract consensus price range from agent posts/opinions
- 5.2: Add `price_prediction` tool to `ReportAgent._define_tools()` (report_agent.py:917) — calls `PredictionExtractor`, returns `{low, high, confidence, reasoning}`
- 5.3: Add `POST /api/report/predict` endpoint — returns structured prediction JSON: `{asset, horizon_hours, low, high, confidence, dissenting_views, agent_consensus}`
- 5.4: Add `Backtester` in `backend/app/services/backtester.py` — given prediction `{low, high}` and actual OHLCV CSV, scores accuracy (% time price stayed in range, max deviation, direction correct)
- 5.5: Add `POST /api/pipeline/backtest` (from Phase 2.3) — runs prediction then scores against actual data
- 5.6: Add backtest result display in CLI script from Phase 2.4

**Key files:** `simulation_runner.py:889,912,923` | `report_agent.py:917,920,928,936,944,954` | `report.py:24,134,149`

**Success:** `python run_pipeline.py --backtest` prints: `Prediction: $95k-$102k | Actual: $97.2k | Result: IN RANGE ✓`

---

## Phase 6 — Experimentation & Tuning
**Goal:** Find what actually moves the prediction needle. Run controlled experiments.
**Why (from Phuc):** "Change agent numbers, number of news etc to see what impacts the prediction"

Tasks:
- 6.1: Add `experiments/` directory with `run_experiment.py` — parameterized runner (agent_count, news_window_days, rounds, whale_pct)
- 6.2: Add experiment result logging — each run saves `{params, prediction, backtest_score}` to `experiments/results.jsonl`
- 6.3: Add `experiments/analyze.py` — reads results.jsonl, prints which params correlate with prediction accuracy
- 6.4: Local Zep option (`ZEP_LOCAL=true`) — docker-compose service for faster iteration
- 6.5: Cache Zep graph fetch in `simulation_manager.py` (TTL: 5min) — currently fetched twice per prepare (lines 389-394)

**Success:** Run 10 experiments varying agent count 10→50→100, produce a table showing which setting was most accurate.

---

## Execution Order
1 ✅ → 2 → 3 → 4 → 5 → 6

Critical path for demo: **3 + 4 + 5** (data in → agents weighted → prediction out)
Phase 2 unblocks iteration speed — do it first so every subsequent phase can be tested quickly.
