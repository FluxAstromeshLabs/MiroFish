---
phase: 02-pipeline
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/api/pipeline.py          # new file
  - backend/app/api/__init__.py          # register blueprint (lines 7-13)
  - backend/app/app/__init__.py          # register blueprint (lines 66-69)
autonomous: true
must_haves:
  truths:
    - Single POST /api/pipeline/run call chains graph build → poll → prepare → poll → start
    - Caller gets a task_id back immediately; polls /api/pipeline/status/<task_id> for progress
    - Pipeline reuses existing endpoints internally (does not duplicate logic)
  artifacts:
    - backend/app/api/pipeline.py with /run and /status/<task_id> routes
    - blueprint registered in api/__init__.py and app/__init__.py
  key_links:
    - pipeline.py calls graph.py:260 (/api/graph/build) then polls graph.py:530 (/api/graph/task/<task_id>)
    - then calls simulation.py:358 (/api/simulation/prepare) then polls simulation.py:638 (/api/simulation/prepare/status)
    - then calls simulation.py:1446 (/api/simulation/start)
---

<objective>
Add a /api/pipeline/run endpoint that chains the 3-step manual flow into one call.

Purpose: Enable fast iteration — one script call runs the full loop.
Output: New pipeline.py blueprint; no changes to existing endpoint logic.
</objective>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/research/PHASE-RESEARCH.md
@backend/app/api/__init__.py
@backend/app/__init__.py
</context>

<tasks>

<task type="auto">
  <name>Task 2.1: Create pipeline blueprint with /run and /status endpoints</name>
  <files>backend/app/api/pipeline.py</files>
  <action>
Create new file. The pipeline runs as a background thread and tracks its own state in a simple
in-memory dict (reuse the existing TaskManager pattern from graph.py).

```python
from flask import Blueprint, request, jsonify
from ..utils.logger import get_logger
from ..config import Config
import threading, uuid, requests, time

pipeline_bp = Blueprint('pipeline', __name__)
logger = get_logger('mirofish.pipeline')

# In-memory pipeline state (same pattern as TaskManager in graph.py)
_pipeline_tasks: dict = {}

@pipeline_bp.route('/run', methods=['POST'])
def run_pipeline():
    """
    Chain: graph build → prepare → start simulation in one call.
    Body: { "project_id": str, "simulation_id": str, "max_rounds": int (opt, default 10),
            "platform": str (opt, default "parallel"), "force": bool (opt, default false) }
    Returns: { "success": true, "pipeline_task_id": str }
    """
    data = request.get_json() or {}
    project_id = data.get('project_id')
    simulation_id = data.get('simulation_id')
    if not project_id or not simulation_id:
        return jsonify({"success": False, "error": "project_id and simulation_id are required"}), 400

    pipeline_task_id = f"pipeline_{uuid.uuid4().hex[:8]}"
    _pipeline_tasks[pipeline_task_id] = {"status": "running", "stage": "graph_build", "error": None}

    def _run():
        base = f"http://localhost:{Config.PORT if hasattr(Config, 'PORT') else 5001}"
        try:
            # Stage 1: graph build
            _pipeline_tasks[pipeline_task_id]["stage"] = "graph_build"
            r = requests.post(f"{base}/api/graph/build", json={"project_id": project_id}, timeout=30)
            task_id = r.json()["data"]["task_id"]

            # Poll graph build task (graph.py:530)
            while True:
                s = requests.get(f"{base}/api/graph/task/{task_id}", timeout=10).json()
                if s["data"]["status"] == "completed":
                    break
                if s["data"]["status"] == "failed":
                    raise Exception(f"Graph build failed: {s['data'].get('message')}")
                time.sleep(3)

            # Stage 2: prepare simulation (simulation.py:358)
            _pipeline_tasks[pipeline_task_id]["stage"] = "prepare"
            r = requests.post(f"{base}/api/simulation/prepare", json={"simulation_id": simulation_id}, timeout=30)
            prep = r.json()
            if not prep.get("success"):
                raise Exception(f"Prepare failed: {prep.get('error')}")

            # If already prepared, skip poll
            if not prep.get("data", {}).get("already_prepared"):
                prep_task_id = prep["data"]["task_id"]
                while True:
                    s = requests.get(f"{base}/api/simulation/prepare/status",
                                     json={"task_id": prep_task_id}, timeout=10).json()
                    if s["data"]["status"] == "completed":
                        break
                    if s["data"]["status"] == "failed":
                        raise Exception(f"Prepare failed: {s['data'].get('message')}")
                    time.sleep(3)

            # Stage 3: start simulation (simulation.py:1446)
            _pipeline_tasks[pipeline_task_id]["stage"] = "simulation"
            r = requests.post(f"{base}/api/simulation/start", json={
                "simulation_id": simulation_id,
                "max_rounds": data.get("max_rounds", 10),
                "platform": data.get("platform", "parallel"),
                "force": data.get("force", False),
            }, timeout=30)
            if not r.json().get("success"):
                raise Exception(f"Start failed: {r.json().get('error')}")

            _pipeline_tasks[pipeline_task_id]["status"] = "completed"
            _pipeline_tasks[pipeline_task_id]["stage"] = "done"

        except Exception as e:
            logger.error(f"Pipeline failed at stage {_pipeline_tasks[pipeline_task_id]['stage']}: {e}")
            _pipeline_tasks[pipeline_task_id]["status"] = "failed"
            _pipeline_tasks[pipeline_task_id]["error"] = str(e)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"success": True, "pipeline_task_id": pipeline_task_id})


@pipeline_bp.route('/status/<pipeline_task_id>', methods=['GET'])
def pipeline_status(pipeline_task_id):
    task = _pipeline_tasks.get(pipeline_task_id)
    if not task:
        return jsonify({"success": False, "error": "Pipeline task not found"}), 404
    return jsonify({"success": True, "data": task})
```
  </action>
  <verify>
grep -n "def run_pipeline\|def pipeline_status" backend/app/api/pipeline.py
# Expected: 2 matches
  </verify>
  <done>pipeline.py exists with /run and /status/<id> routes.</done>
</task>

<task type="auto">
  <name>Task 2.2: Register pipeline blueprint</name>
  <files>backend/app/api/__init__.py, backend/app/__init__.py</files>
  <action>
In backend/app/api/__init__.py, follow the pattern of the existing 3 blueprints (lines 7-13).
Add after the existing imports:
```python
from .pipeline import pipeline_bp
```
And add pipeline_bp to the __all__ or exports if present.

In backend/app/__init__.py, follow the registration pattern at lines 66-69:
```python
from .api import pipeline_bp
app.register_blueprint(pipeline_bp, url_prefix='/api/pipeline')
```
  </action>
  <verify>
grep -n "pipeline_bp" backend/app/api/__init__.py backend/app/__init__.py
# Expected: 1 match in each file
  </verify>
  <done>Blueprint registered; /api/pipeline/run returns 400 without body (proves route is live).</done>
</task>

</tasks>

<success_criteria>
1. POST /api/pipeline/run with valid project_id + simulation_id starts a pipeline task and returns pipeline_task_id
2. GET /api/pipeline/status/<id> returns stage: graph_build | prepare | simulation | done
3. No existing endpoints modified
</success_criteria>
