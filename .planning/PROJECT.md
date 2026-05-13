# MiroFish — Crypto Prediction Engine

## Vision

Extend MiroFish from a general-purpose social simulation engine into a **crypto market prediction system**. Feed real OHLCV + sentiment data, simulate 10–5000 capital-weighted agents (whales, quants, retail), and output a probabilistic price range prediction for BTC (and other assets) over a defined time horizon.

## Core Insight

> "The closer you describe [the market], the more accurately you can predict it."

The simulation is only as good as the seed data. We need:
1. Real market data (OHLCV, news, social sentiment) as graph inputs
2. Capital-weighted agents that reflect actual market participant distribution
3. A framed prediction question, not a raw simulation

## Stack

- Backend: Python 3.11 / Flask / uv
- Frontend: Vue 3 / Vite / D3.js
- Memory: Zep Cloud (knowledge graph + temporal memory)
- Simulation: OASIS (subprocess-based multi-agent social sim)
- LLM: Any OpenAI-compatible API (default: qwen-plus via Alibaba DashScope)

## Success Definition

Given: BTC OHLCV (24h), top news headlines, social sentiment (7-day window)
Output: "BTC will trade between $X and $Y in the next 24h with Z% confidence"
Validated by: backtesting on historical data

## Current State

MiroFish works end-to-end for document-based simulations (novel chapters, news reports).
Crypto prediction requires: data pipeline, OHLCV integration, capital-weighted agents, prediction framing.
