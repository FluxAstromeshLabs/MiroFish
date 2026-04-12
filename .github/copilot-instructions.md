# Project Guidelines

## Build And Test
- Prerequisites: Node.js 18+, Python 3.11+, uv.
- Install JS dependencies from repo root: npm run setup.
- Install backend Python dependencies: npm run setup:backend.
- Run full dev stack (frontend + backend): npm run dev.
- Run only backend: npm run backend.
- Run only frontend: npm run frontend.
- Build frontend: npm run build.
- Run backend script tests from repo root: source backend/.venv/bin/activate && pytest backend/scripts/test_*.py.

## Architecture
- This is a monorepo with a Vue frontend in frontend/ and a Flask backend in backend/.
- Backend entrypoint: backend/run.py. Flask app wiring and blueprint registration are in backend/app/__init__.py.
- API boundaries are split by blueprint:
  - backend/app/api/graph.py for graph and project workflows.
  - backend/app/api/simulation.py for simulation setup and execution.
  - backend/app/api/report.py for report generation and report chat.
- Business logic is in backend/app/services/. Keep route handlers thin and delegate non-trivial logic to services.
- Shared backend helpers are in backend/app/utils/ (logging, retry, llm client, parsing).
- Frontend HTTP contracts are in frontend/src/api/. Keep API schema changes synchronized with backend endpoints.

## Conventions
- Validate runtime configuration before starting backend flows. Required env vars are loaded from root .env (not backend/.env), especially LLM_API_KEY and ZEP_API_KEY.
- Preserve task/project state patterns in backend/app/models/task.py and backend/app/models/project.py (status enums + manager classes).
- Keep JSON and logs UTF-8 safe. Do not remove existing encoding safeguards in backend/run.py, backend/app/__init__.py, and backend/app/utils/logger.py.
- For transient external API failures, reuse retry helpers in backend/app/utils/retry.py instead of ad-hoc retry loops.
- For uploaded content and generated artifacts, keep paths under backend/uploads/ and maintain existing project-scoped directory layout.

## Pitfalls
- Backend startup will fail fast if required env vars are missing.
- Some scripts assume repo-root working directory semantics; run them from repo root unless the script explicitly handles cwd.
- Simulation subprocess cleanup is important; preserve cleanup hooks and termination logic in simulation manager/runner paths.

## Docs
- Project setup and runtime overview: README.md and README-EN.md.
- Prompt inventory: docs/all-prompts.md.
- Design and planning notes: docs/superpowers/specs/ and docs/superpowers/plans/.
- Container deployment details: Dockerfile and docker-compose.yml.