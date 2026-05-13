# Requirements

## R-01: Automated Pipeline
The upload → ontology → graph → simulation flow must be chainable in a single API call or trigger.
Currently: fully manual 3-step API sequence. No chaining exists.

## R-02: Configurable Agent Count
Agent count must be explicitly configurable (e.g., 10 for initial tests, 1000+ for production).
Currently: opaquely derived from Zep entity extraction. AGENTS_PER_BATCH=15 is misleading.

## R-03: OHLCV Data Ingestion
System must accept OHLCV data (timestamp, open, high, low, close, volume) and convert it into Zep knowledge graph episodes.
Currently: no endpoint, no data model, no integration point anywhere.

## R-04: Sentiment Data Ingestion
System must accept 7-day social sentiment data (posts, headlines) as graph input.
Currently: only supported via document upload (PDF/text). No structured sentiment pipeline.

## R-05: Capital-Weighted Agent Influence
Agents must be typed by capital tier: whale (100x capital, low count), quant (10x, low count), retail (1x, high count).
Influence in simulation must reflect capital weight, not just role type.
Currently: influence is role-type-only (university=3.0, student=0.8). No capital concept.

## R-06: Prediction Framing
Simulation must output a structured prediction: price range + confidence, not raw social posts.
Question format: "Based on provided market context, what price range do you expect BTC to trade in the next 24h?"
Currently: output is social simulation events; no structured prediction extraction.

## R-07: Zep Caching
Zep graph fetches must be cached within a session. Currently fetched twice per prepare call, and per-entity searches run on every profile generation.
Currently: zero caching at any layer.

## R-08: Skip Redundant Persona Generation
Persona generation must be skipped if entity profiles haven't changed (content-hash check).
Currently: regenerates all personas on every non-skip run.

## R-09: Fix Hardcoded Values
- `REF-2024-X92` fallback in Vue frontend (Step5Interaction.vue line 12)
- Chinese gender normalization strings in `_normalize_gender` (dead code)
- Beijing timezone hardcoded in simulation config
- Mixed Chinese/English in API docstrings and log strings
- Concatenation bug at simulation.py line 460
- Platform weights (Twitter/Reddit) hardcoded as magic numbers

## R-10: Local Zep DB Option
ZEP processing is slow on cloud. Support local Zep DB for faster simulation + development.
Currently: cloud-only.
