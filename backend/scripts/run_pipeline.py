#!/usr/bin/env python3
"""
Run the full MiroFish pipeline in one command.

Usage (auto-create project + sim):
    python backend/scripts/run_pipeline.py \
        --ohlcv-file research/data/btc_1h.csv \
        [--news-file path/to/news.txt] \
        [--project-name "btc-april-2026"] \
        [--rounds 10]

Usage (existing project + sim):
    python backend/scripts/run_pipeline.py \
        --project-id <project_id> \
        --simulation-id <sim_id> \
        [--rounds 10]
"""
import argparse, requests, time, sys, os, re


def _parse_range(response_text):
    if not isinstance(response_text, str):
        return None
    nums = re.findall(r'\d+(?:\.\d+)?', response_text)
    if len(nums) < 2:
        return None
    try:
        low, high = float(nums[0]), float(nums[1])
    except ValueError:
        return None
    if low <= 0 or high <= 0 or low >= high:
        return None
    return (low, high)


def _average_forecasts(forecasts):
    if not forecasts:
        return []
    lows = [float(item["range_low"]) for item in forecasts]
    highs = [float(item["range_high"]) for item in forecasts]
    avg_low = sum(lows) / len(lows)
    avg_high = sum(highs) / len(highs)
    if avg_low >= avg_high:
        avg_high = avg_low + 1e-6
    return [{"name": "consensus_avg", "range_low": avg_low, "range_high": avg_high}]


def _get_agent_profiles(base, simulation_id):
    for platform in ("twitter", "reddit"):
        resp = requests.get(f"{base}/api/simulation/{simulation_id}/profiles",
                            params={"platform": platform}, timeout=10).json()
        profiles = resp.get("data", {}).get("profiles", [])
        if profiles:
            id_to_profile = {}
            for p in profiles:
                agent_id = p.get("user_id", p.get("agent_id"))
                if agent_id is not None:
                    id_to_profile[int(agent_id)] = p
            return id_to_profile, platform
    raise RuntimeError("No agent profiles found")


def _interview_agents(base, simulation_id, id_to_profile, platform, predict_hours=1):
    agent_count = len(id_to_profile)
    interview_prompt = (
        f"Based on your discussions, predict the price range for the next {predict_hours} hours.\n\n"
        "CRITICAL: Respond with EXACTLY two numbers separated by a comma. "
        "Nothing else. Format: range_low,range_high"
    )
    interview_timeout = max(60, agent_count * 15)
    resp = requests.post(f"{base}/api/simulation/interview/all", json={
        "simulation_id": simulation_id,
        "prompt": interview_prompt,
        "platform": platform,
        "timeout": interview_timeout,
    }, timeout=interview_timeout + 30).json()

    raw_results = resp.get("data", {}).get("result", {}).get("results", {})
    forecasts = []
    for key, interview in raw_results.items():
        agent_id = interview.get("agent_id")
        response_text = interview.get("response", "")
        profile = id_to_profile.get(agent_id, {})
        agent_name = profile.get("name", profile.get("user_name", f"agent_{agent_id}"))
        result = _parse_range(response_text)
        if result:
            low, high = result
            forecasts.append({"name": agent_name, "range_low": low, "range_high": high})
            print(f"  {agent_name}: {low:,.0f} — {high:,.0f}")
        else:
            print(f"  {agent_name}: could not parse forecast")
    return forecasts


def _wait_for_env_alive(base, simulation_id, timeout=60):
    for _ in range(timeout):
        resp = requests.post(f"{base}/api/simulation/env-status",
                             json={"simulation_id": simulation_id}, timeout=10).json()
        if resp.get("data", {}).get("env_alive"):
            return True
        time.sleep(1)
    return False


def interview_for_prediction(base, simulation_id, predict_hours=1):
    print("[pipeline] Interviewing agents for price forecasts...")
    try:
        id_to_profile, platform = _get_agent_profiles(base, simulation_id)
    except RuntimeError as e:
        print(f"[pipeline] No forecasts generated: {e}")
        return []
    print(f"[pipeline] {len(id_to_profile)} agents found (platform: {platform})")

    run_status = requests.get(f"{base}/api/simulation/{simulation_id}/run-status",
                              timeout=10).json().get("data", {})
    runner_status = run_status.get("runner_status", "idle")

    if runner_status in ("completed", "running"):
        env_ready = _wait_for_env_alive(base, simulation_id)
        if env_ready:
            try:
                forecasts = _interview_agents(base, simulation_id, id_to_profile, platform, predict_hours)
                if forecasts:
                    return forecasts
            except Exception as e:
                print(f"[pipeline] Interview failed: {e}, no fallback available")
                return []

    print("[pipeline] Environment not ready for interview")
    return []


def stop_simulation(base, simulation_id):
    try:
        requests.post(f"{base}/api/simulation/stop",
                      json={"simulation_id": simulation_id}, timeout=10)
    except Exception:
        pass


def resolve_project(base, project_name, news_file, ohlcv_file):
    """Find project by name or create it. Returns project_id."""
    # Search existing projects
    resp = requests.get(f"{base}/api/graph/project/list", timeout=10).json()
    for p in resp.get("data", []):
        if p.get("name") == project_name:
            print(f"[pipeline] Reusing existing project: {p['project_id']} ({project_name})")
            return p["project_id"]

    # Create new project — upload news file or fall back to ohlcv file
    upload_path = news_file or ohlcv_file
    if not upload_path:
        print("[error] No --news-file or --ohlcv-file provided — cannot create project")
        sys.exit(1)
    if not os.path.exists(upload_path):
        print(f"[error] File not found: {upload_path}")
        sys.exit(1)

    print(f"[pipeline] Creating project '{project_name}' from {os.path.basename(upload_path)}...")
    with open(upload_path, "rb") as f:
        r = requests.post(
            f"{base}/api/graph/ontology/generate",
            data={
                "project_name": project_name,
                "simulation_requirement": "BTC crypto market simulation for price prediction",
            },
            files={"files": (os.path.basename(upload_path), f)},
            timeout=120,
        )
    result = r.json()
    if not result.get("success"):
        print(f"[error] Project creation failed: {result.get('error')}")
        sys.exit(1)

    project_id = result["data"]["project_id"]
    print(f"[pipeline] Project created: {project_id}")

    # Build graph
    print("[pipeline] Building graph...")
    r = requests.post(f"{base}/api/graph/build", json={"project_id": project_id}, timeout=30)
    task_id = r.json()["data"]["task_id"]
    while True:
        s = requests.get(f"{base}/api/graph/task/{task_id}", timeout=10).json()
        st = s["data"]["status"]
        if st == "completed":
            print("[pipeline] Graph built ✓")
            break
        if st == "failed":
            print(f"[error] Graph build failed: {s['data'].get('message')}")
            sys.exit(1)
        time.sleep(3)

    return project_id


def resolve_simulation(base, project_id):
    """Find existing simulation for project or create one. Returns simulation_id."""
    resp = requests.get(f"{base}/api/simulation/list", params={"project_id": project_id}, timeout=10).json()
    sims = resp.get("data", [])
    if sims:
        sim_id = sims[0]["simulation_id"]
        print(f"[pipeline] Reusing existing simulation: {sim_id}")
        return sim_id

    print("[pipeline] Creating simulation...")
    r = requests.post(f"{base}/api/simulation/create", json={"project_id": project_id}, timeout=30)
    result = r.json()
    if not result.get("success"):
        print(f"[error] Simulation creation failed: {result.get('error')}")
        sys.exit(1)

    sim_id = result["data"]["simulation_id"]
    print(f"[pipeline] Simulation created: {sim_id}")
    return sim_id


def main():
    from datetime import date
    parser = argparse.ArgumentParser(description="Run MiroFish pipeline end-to-end")
    parser.add_argument("--project-id", default=None)
    parser.add_argument("--simulation-id", default=None)
    parser.add_argument("--ohlcv-file", default=None)
    parser.add_argument("--news-file", default=None)
    parser.add_argument("--project-name", default=f"btc-{date.today()}")
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--platform", default="parallel")
    parser.add_argument("--host", default="http://localhost:5001")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--backtest", action="store_true")
    parser.add_argument("--actual-low", type=float, default=None)
    parser.add_argument("--actual-high", type=float, default=None)
    parser.add_argument("--predict-hours", type=int, default=1)
    args = parser.parse_args()

    base = args.host

    # Check backend is reachable
    try:
        requests.get(f"{base}/api/graph/project/list", timeout=5)
    except requests.exceptions.ConnectionError:
        print(f"[error] Cannot connect to {base} — is the backend running?")
        sys.exit(1)

    # Resolve project
    project_id = args.project_id
    if not project_id:
        project_id = resolve_project(base, args.project_name, args.news_file, args.ohlcv_file)

    # Resolve simulation
    simulation_id = args.simulation_id
    if not simulation_id:
        simulation_id = resolve_simulation(base, project_id)

    print(f"[pipeline] Starting run — project={project_id} sim={simulation_id} rounds={args.rounds}")

    if args.ohlcv_file:
        print(f"[pipeline] OHLCV file ready at {args.ohlcv_file} — will feed graph in Phase 3")

    # Start pipeline
    r = requests.post(f"{base}/api/pipeline/run", json={
        "project_id": project_id,
        "simulation_id": simulation_id,
        "max_rounds": args.rounds,
        "platform": args.platform,
        "force": args.force,
    }, timeout=15)

    data = r.json()
    if not data.get("success"):
        print(f"[error] {data.get('error')}")
        sys.exit(1)

    pipeline_task_id = data["pipeline_task_id"]
    print(f"[pipeline] Task started: {pipeline_task_id}")

    # Poll status
    last_stage = None
    while True:
        s = requests.get(f"{base}/api/pipeline/status/{pipeline_task_id}", timeout=10).json()
        task = s.get("data", {})
        stage = task.get("stage")
        status = task.get("status")

        if stage != last_stage:
            print(f"[pipeline] Stage: {stage}")
            last_stage = stage

        if status == "completed":
            print("[pipeline] ✓ Done")
            break
        if status == "failed":
            print(f"[pipeline] ✗ Failed at stage '{stage}': {task.get('error')}")
            sys.exit(1)

        time.sleep(3)

    forecasts = interview_for_prediction(base, simulation_id, args.predict_hours)
    stop_simulation(base, simulation_id)

    if forecasts:
        avg = _average_forecasts(forecasts)[0]
        pred_low = avg["range_low"]
        pred_high = avg["range_high"]

        if args.backtest and args.actual_low is not None and args.actual_high is not None:
            actual_mid = (args.actual_low + args.actual_high) / 2
            in_range = pred_low <= actual_mid <= pred_high
            result = "IN RANGE ✓" if in_range else "OUT OF RANGE ✗"
            print(f"Prediction: ${pred_low/1000:,.0f}k–${pred_high/1000:,.0f}k | Actual: ${actual_mid/1000:,.1f}k | {result}")
        else:
            print(f"Prediction: ${pred_low/1000:,.0f}k–${pred_high/1000:,.0f}k")
    else:
        print("[pipeline] No forecasts generated")


if __name__ == "__main__":
    main()
