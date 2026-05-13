from flask import Blueprint, request, jsonify
from ..utils.logger import get_logger
from ..config import Config
import threading, uuid, requests, time, re

pipeline_bp = Blueprint('pipeline', __name__)
logger = get_logger('mirofish.pipeline')
_PORT = getattr(Config, 'PORT', 5001)

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
        base = f"http://localhost:{_PORT}"
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
                                     params={"task_id": prep_task_id}, timeout=10).json()
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


@pipeline_bp.route('/backtest', methods=['POST'])
def backtest():
    data = request.get_json() or {}
    simulation_id = data.get('simulation_id')
    actual_low = data.get('actual_low')
    actual_high = data.get('actual_high')

    if not simulation_id or actual_low is None or actual_high is None:
        return jsonify({"success": False, "error": "simulation_id, actual_low, and actual_high are required"}), 400

    base = f"http://localhost:{_PORT}"

    # Fetch agent profiles (twitter preferred, reddit fallback)
    profiles_resp = requests.get(
        f"{base}/api/simulation/{simulation_id}/profiles",
        params={"platform": "twitter"},
        timeout=30,
    )
    profiles_data = profiles_resp.json()
    if not profiles_data.get("success") or not profiles_data.get("data"):
        profiles_resp = requests.get(
            f"{base}/api/simulation/{simulation_id}/profiles",
            params={"platform": "reddit"},
            timeout=30,
        )
        profiles_data = profiles_resp.json()
        if not profiles_data.get("success"):
            logger.error(f"Failed to fetch profiles for {simulation_id}: {profiles_data.get('error')}")
            return jsonify({"success": False, "error": f"Could not fetch agent profiles: {profiles_data.get('error')}"}), 502

    id_to_profile = {int(p["agent_id"]): p for p in profiles_data.get("data", []) if p.get("agent_id") is not None}

    prompt = (
        "Based on your knowledge and the current market conditions, provide your BTC price range forecast. "
        "Reply with exactly two numbers separated by a comma: range_low,range_high (e.g. 95000,102000). "
        "No other text."
    )

    agent_count = len(id_to_profile)
    interview_timeout = max(120, agent_count * 15)

    interview_resp = requests.post(
        f"{base}/api/simulation/interview/all",
        json={"simulation_id": simulation_id, "prompt": prompt},
        timeout=interview_timeout,
    )
    interview_data = interview_resp.json()
    if not interview_data.get("success"):
        logger.error(f"Interview failed for {simulation_id}: {interview_data.get('error')}")
        return jsonify({"success": False, "error": f"Interview failed: {interview_data.get('error')}"}), 502

    raw_results = interview_data.get("data", {}).get("result", {}).get("results", {})

    _number_pattern = re.compile(r'(\d+(?:\.\d+)?)[,\s]+(\d+(?:\.\d+)?)')

    forecasts = []
    for entry in raw_results.values():
        text = entry.get("response", "") or entry.get("message", "") or ""
        match = _number_pattern.search(text)
        if match:
            low = float(match.group(1))
            high = float(match.group(2))
            if low <= 0 or high <= 0 or low >= high:
                continue
            agent_id = entry.get("agent_id")
            profile = id_to_profile.get(int(agent_id), {}) if agent_id is not None else {}
            name = profile.get("name") or profile.get("user_name") or f"agent_{agent_id}"
            forecasts.append({
                "name": name,
                "range_low": low,
                "range_high": high,
            })

    if not forecasts:
        logger.error(f"No valid forecasts parsed from interview responses for {simulation_id}")
        return jsonify({"success": False, "error": "No valid forecasts could be parsed from agent responses"}), 422

    pred_low = sum(f["range_low"] for f in forecasts) / len(forecasts)
    pred_high = sum(f["range_high"] for f in forecasts) / len(forecasts)
    actual_mid = (actual_low + actual_high) / 2
    in_range = pred_low <= actual_mid <= pred_high

    return jsonify({
        "success": True,
        "data": {
            "pred_low": pred_low,
            "pred_high": pred_high,
            "actual_mid": actual_mid,
            "in_range": in_range,
            "agent_count": len(forecasts),
            "forecasts": forecasts,
        },
    })
