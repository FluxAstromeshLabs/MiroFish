"""
MiroFish Price Forecast Pipeline
Automates: seed.md → Ontology → Graph → Simulation → Interview → price_forecast.csv
"""

import os
import sys
import csv
import time
import re
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests

from common import project_root, resolve_path, LLMClient


# ============== Helpers ==============

def poll(check_fn, interval=3, max_wait=600):
    """Poll check_fn() until it returns a truthy result or timeout."""
    start = time.time()
    while time.time() - start < max_wait:
        result = check_fn()
        if result:
            return result
        time.sleep(interval)
    raise TimeoutError(f"Polling timed out after {max_wait}s")


def api(method, base_url, path, session=None, **kwargs):
    """Make an API call and return parsed response. Raises on failure."""
    http = session or requests
    url = f"{base_url}{path}"
    resp = getattr(http, method)(url, **kwargs)
    data = resp.json()
    if not data.get("success"):
        error = data.get("error") or data.get("message") or str(data)
        raise RuntimeError(f"API error ({path}): {error}")
    return data.get("data", {})


def count_agents_in_seed(seed_text):
    """Count agent entries in the # Agents section of seed.md."""
    if "# Agents" in seed_text:
        agents_section = seed_text.split("# Agents", 1)[1]
    else:
        agents_section = seed_text
    lines = [l for l in agents_section.strip().splitlines() if l.strip()]
    return max(len(lines), 6)


def strip_agents_section(seed_text):
    """Remove the '# Agents Population' section and everything after it."""
    if "# Agents Population" in seed_text:
        return seed_text.split("# Agents Population", 1)[0]
    return seed_text


def extract_latest_timestamp(seed_text):
    """Return Unix seconds of the latest OHLCV candle in seed_text, or now() as fallback.

    The seed's 1H table lists rows newest-first in the format:
        2026-04-06 23:00 |  68,777.00 | ...
    We find the first data row after the '## 1H' header.
    """
    match = re.search(
        r'## 1H\n'
        r'Date/Time[^\n]*\n'
        r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2})',
        seed_text
    )
    if match:
        dt = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    return int(time.time())


# ============== Pipeline Steps ==============

def check_server(base_url, session=None):
    """Check if Flask server is reachable."""
    http = session or requests
    try:
        http.get(f"{base_url}/api/graph/tasks", timeout=5)
        return True
    except requests.ConnectionError:
        return False


def step1_generate_ontology(base_url, seed_path, requirement, session=None):
    """Upload seed file and generate ontology."""
    print("[Step 1/5] Generating ontology...", end="", flush=True)

    filename = os.path.basename(seed_path)
    with open(seed_path, "rb") as f:
        files = {"files": (filename, f)}
        form_data = {"simulation_requirement": requirement}
        result = api("post", base_url, "/api/graph/ontology/generate",
                     session=session, files=files, data=form_data)

    project_id = result["project_id"]
    entity_count = len(result.get("ontology", {}).get("entity_types", []))
    print(f"  ✓ {project_id} ({entity_count} entity types)")
    return project_id


def step2_build_graph(base_url, project_id, session=None):
    """Build Zep knowledge graph and wait for completion."""
    print("[Step 2/5] Building knowledge graph...", end="", flush=True)
    t0 = time.time()

    result = api("post", base_url, "/api/graph/build",
                 session=session, json={"project_id": project_id})
    task_id = result["task_id"]

    def check():
        task = api("get", base_url, f"/api/graph/task/{task_id}", session=session)
        status = task.get("status")
        if status == "completed":
            return task
        if status == "failed":
            raise RuntimeError(f"Graph build failed: {task.get('error')}")
        return None

    task = poll(check, interval=1, max_wait=300)
    graph_id = task.get("result", {}).get("graph_id")
    elapsed = int(time.time() - t0)
    print(f"  ✓ {graph_id} ({elapsed}s)")
    return graph_id


def step3_prepare_simulation(base_url, project_id, graph_id, agent_count=20, session=None):
    """Create simulation and prepare (profiles + config)."""
    print("[Step 3/5] Preparing simulation...", end="", flush=True)
    t0 = time.time()

    # Create
    result = api("post", base_url, "/api/simulation/create",
                 session=session, json={"project_id": project_id, "graph_id": graph_id})
    simulation_id = result["simulation_id"]

    # Prepare — parallel_profile_count = agent_count so all profiles generate in one batch
    result = api("post", base_url, "/api/simulation/prepare",
                 session=session, json={"simulation_id": simulation_id, "parallel_profile_count": agent_count})

    if result.get("already_prepared"):
        agents_count = result.get("prepare_info", {}).get("profiles_count", "?")
        elapsed = int(time.time() - t0)
        print(f"  ✓ {simulation_id} | {agents_count} agents (already prepared, {elapsed}s)")
        return simulation_id

    task_id = result.get("task_id")

    def check():
        status_data = api("post", base_url, "/api/simulation/prepare/status",
                          session=session, json={"task_id": task_id, "simulation_id": simulation_id})
        if status_data.get("already_prepared"):
            return status_data
        status = status_data.get("status")
        if status == "completed":
            return status_data
        if status == "failed":
            raise RuntimeError(f"Preparation failed: {status_data.get('error')}")
        progress = status_data.get("progress", 0)
        print(f"\r[Step 3/5] Preparing simulation... {progress}%", end="", flush=True)
        return None

    status_data = poll(check, interval=5, max_wait=600)
    elapsed = int(time.time() - t0)
    agents_count = status_data.get("prepare_info", {}).get("profiles_count",
                   status_data.get("result", {}).get("agents_count", "?"))
    print(f"\r[Step 3/5] Preparing simulation...  ✓ {simulation_id} | {agents_count} agents ({elapsed}s)")
    return simulation_id


def step4_run_simulation(base_url, simulation_id, max_rounds=10, session=None):
    """Start OASIS simulation and wait for completion."""
    print("[Step 4/5] Running simulation...", end="", flush=True)
    t0 = time.time()

    api("post", base_url, "/api/simulation/start",
        session=session, json={"simulation_id": simulation_id, "platform": "parallel", "max_rounds": max_rounds})

    def check():
        status = api("get", base_url, f"/api/simulation/{simulation_id}/run-status", session=session)
        runner = status.get("runner_status", "idle")
        if runner == "completed":
            return status
        if runner in ("failed", "stopped"):
            raise RuntimeError(f"Simulation {runner}: {status.get('error', '')}")
        current = status.get("current_round", 0)
        total = status.get("total_rounds", "?")
        actions = status.get("total_actions_count", 0)
        print(f"\r[Step 4/5] Running simulation... round {current}/{total}, {actions} actions",
              end="", flush=True)
        return None

    max_wait = max(600, max_rounds * 60)
    status = poll(check, interval=2, max_wait=max_wait)
    elapsed = int(time.time() - t0)
    total_rounds = status.get("total_rounds", "?")
    total_actions = status.get("total_actions_count", 0)
    print(f"\r[Step 4/5] Running simulation...  ✓ {total_rounds} rounds, {total_actions} actions ({elapsed}s)")
    return simulation_id


# ============== Interview & Decision Parsing ==============

def _parse_range(response_text):
    """Parse two floats from agent response. Returns (float, float) or None.

    Uses regex extraction so the response can contain extra words/punctuation
    (e.g. 'The range is 83000.5,85200.0' or '83000.5 to 85200.0').
    Validates: both values > 0, low < high.
    """
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


def _fmt_forecast(agent_name, range_low, range_high):
    """Format a price forecast as a display string."""
    return f"{agent_name}: {range_low} — {range_high}"


def _forecast_from_persona(llm, agent_name, persona, world_seed, predict_hours):
    """Generate price range forecast directly from agent persona + market data (single LLM call).
    llm.chat() returns a plain string — we parse it directly with _parse_range.
    """
    response = llm.chat(
        messages=[
            {
                "role": "system",
                "content": (
                    f"You are {agent_name}, a trader with the following profile:\n{persona}\n\n"
                    "Based on your personality and trading style, predict the price range.\n\n"
                    "**CRITICAL: You MUST respond with EXACTLY two numbers separated by a comma. "
                    "Nothing else. No words, no explanation, no punctuation other than the comma "
                    "and decimal point.**\n"
                    "Format: range_low,range_high"
                )
            },
            {
                "role": "user",
                "content": (
                    f"Market data:\n{world_seed}\n\n"
                    f"What is the price range for the next {predict_hours} hours? "
                    "Respond with ONLY two numbers separated by a comma."
                )
            }
        ],
        temperature=0.8
    )
    return _parse_range(response)


def _get_agent_profiles(base_url, simulation_id, session=None):
    """Fetch agent profiles, trying twitter then reddit. Returns (id_to_profile, platform)."""
    for platform in ("twitter", "reddit"):
        profiles_data = api("get", base_url,
                            f"/api/simulation/{simulation_id}/profiles?platform={platform}",
                            session=session)
        profiles = profiles_data.get("profiles", [])
        if profiles:
            id_to_profile = {}
            for p in profiles:
                agent_id = p.get("user_id", p.get("agent_id"))
                if agent_id is not None:
                    id_to_profile[int(agent_id)] = p
            return id_to_profile, platform

    raise RuntimeError("No agent profiles found")


def _interview_agents(base_url, simulation_id, seed_text, predict_hours, id_to_profile, platform, session=None):
    """Interview agents via OASIS for price range forecasts (parallel)."""
    world_seed = strip_agents_section(seed_text)
    agent_count = len(id_to_profile)

    interview_prompt = (
        "Here is the current market context:\n"
        f"{world_seed}\n\n"
        f"Based on this data and your discussions, predict the price range for the next {predict_hours} hours.\n\n"
        "**CRITICAL: You MUST respond with EXACTLY two numbers separated by a comma. "
        "Nothing else. No words, no explanation, no punctuation other than the comma and decimal point.**\n"
        "Format: range_low,range_high"
    )

    interview_timeout = max(60, agent_count * 15)
    interview_result = api("post", base_url, "/api/simulation/interview/all",
                           session=session, json={
                               "simulation_id": simulation_id,
                               "prompt": interview_prompt,
                               "platform": platform,
                               "timeout": interview_timeout
                           })

    raw_results = interview_result.get("result", {}).get("results", {})

    parse_tasks = []
    for idx, (key, interview) in enumerate(raw_results.items(), 1):
        agent_id = interview.get("agent_id")
        response_text = interview.get("response", "")
        profile = id_to_profile.get(agent_id, {})
        agent_name = profile.get("name", profile.get("user_name", f"agent_{agent_id}"))

        if not response_text:
            print(f"  [{idx}/{agent_count}] {agent_name}: (no response)")
            continue

        parse_tasks.append((idx, agent_name, response_text))

    forecasts = []
    for idx, name, resp in parse_tasks:
        result = _parse_range(resp)
        if result:
            low, high = result
            forecasts.append({"name": name, "range_low": low, "range_high": high})
            print(f"  [{idx}/{agent_count}] {_fmt_forecast(name, low, high)}")
        else:
            print(f"  [{idx}/{agent_count}] {name}: could not parse forecast")

    return forecasts


def _fallback_persona_decisions(llm, seed_text, id_to_profile, predict_hours):
    """Generate price range forecasts from agent personas when interview is unavailable (parallel)."""
    world_seed = strip_agents_section(seed_text)
    agent_count = len(id_to_profile)

    print(f"  Falling back to persona-based forecasts for {agent_count} agents")

    tasks = []
    for idx, (agent_id, profile) in enumerate(id_to_profile.items(), 1):
        agent_name = profile.get("name", profile.get("user_name", f"agent_{agent_id}"))
        persona = profile.get("persona", profile.get("bio", ""))
        tasks.append((idx, agent_name, persona))

    forecasts = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(_forecast_from_persona, llm, name, persona, world_seed, predict_hours): (idx, name)
            for idx, name, persona in tasks
        }
        for future in as_completed(futures):
            idx, name = futures[future]
            try:
                result = future.result()
                if result:
                    low, high = result
                    forecasts.append({"name": name, "range_low": low, "range_high": high})
                    print(f"  [{idx}/{agent_count}] {_fmt_forecast(name, low, high)}")
                else:
                    print(f"  [{idx}/{agent_count}] {name}: could not parse forecast")
            except Exception as e:
                print(f"  [{idx}/{agent_count}] {name}: error: {e}")

    return forecasts


def step5_interview_for_trades(base_url, simulation_id, llm, seed_text, predict_hours, session=None):
    """Interview each agent for price range forecast, return list of forecast dicts."""
    print("[Step 5/5] Interviewing agents for price forecasts...")

    id_to_profile, platform = _get_agent_profiles(base_url, simulation_id, session=session)
    agent_count = len(id_to_profile)

    run_status = api("get", base_url, f"/api/simulation/{simulation_id}/run-status", session=session)
    env_alive = run_status.get("runner_status") not in ("stopped", "failed", "idle")

    if env_alive:
        print(f"  Found {agent_count} agents (platform: {platform}) — trying OASIS interview...")
        try:
            forecasts = _interview_agents(base_url, simulation_id, seed_text, predict_hours,
                                          id_to_profile, platform, session=session)
            if forecasts:
                return forecasts
        except Exception as e:
            print(f"  Interview failed: {e}")

    return _fallback_persona_decisions(llm, seed_text, id_to_profile, predict_hours)


# ============== CSV Output ==============

def write_csv(forecasts, output_path, start_timestamp, predict_hours):
    """Write price forecast decisions to CSV."""
    end_timestamp = start_timestamp + predict_hours * 3600
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "start_timestamp", "end_timestamp",
                                               "range_low", "range_high"])
        writer.writeheader()
        for row in forecasts:
            writer.writerow({
                "name": row["name"],
                "start_timestamp": start_timestamp,
                "end_timestamp": end_timestamp,
                "range_low": row["range_low"],
                "range_high": row["range_high"],
            })


# ============== Main ==============

def main():
    parser = argparse.ArgumentParser(description="MiroFish Price Forecast Pipeline")
    parser.add_argument("seed_file", help="Path to seed file (md/txt)")
    default_output = os.path.join(project_root, '..', 'rust-connectors', 'price_forecast.csv')
    parser.add_argument("-o", "--output", default=default_output,
                        help="Output CSV path (default: ../rust-connectors/price_forecast.csv)")
    parser.add_argument("-r", "--requirement", default=None,
                        help="Simulation requirement (default: uses seed file content)")
    parser.add_argument("--base-url", default="http://localhost:5001",
                        help="Flask server URL (default: http://localhost:5001)")
    parser.add_argument("--rounds", type=int, default=15,
                        help="Max simulation rounds (default: 15)")
    parser.add_argument("--predict-hours", type=int, default=12,
                        help="Forecast horizon in hours (default: 12)")
    args = parser.parse_args()

    args.output = resolve_path(args.output)

    if not os.path.exists(args.seed_file):
        print(f"Error: seed file not found: {args.seed_file}")
        sys.exit(1)

    with open(args.seed_file, "r", encoding="utf-8") as f:
        seed_text = f.read()

    requirement = args.requirement or seed_text

    print("MiroFish Trade Pipeline")
    print("=" * 50)

    session = requests.Session()

    if not check_server(args.base_url, session=session):
        print(f"Error: Cannot connect to server at {args.base_url}")
        print("Start the server first: cd backend && python run.py")
        sys.exit(1)
    print(f"Server: {args.base_url} ✓")
    print()

    llm = LLMClient()

    # Run pipeline
    project_id = step1_generate_ontology(args.base_url, args.seed_file, requirement, session=session)
    graph_id = step2_build_graph(args.base_url, project_id, session=session)
    agent_count = count_agents_in_seed(seed_text)
    simulation_id = step3_prepare_simulation(args.base_url, project_id, graph_id,
                                             agent_count=agent_count, session=session)
    step4_run_simulation(args.base_url, simulation_id, max_rounds=args.rounds, session=session)
    forecasts = step5_interview_for_trades(args.base_url, simulation_id, llm, seed_text,
                                           args.predict_hours, session=session)

    if forecasts:
        start_ts = extract_latest_timestamp(seed_text)
        write_csv(forecasts, args.output, start_ts, args.predict_hours)
        print()
        print("=" * 50)
        print(f"Output: {args.output} ({len(forecasts)} forecasts)")
    else:
        print()
        print("=" * 50)
        print("Warning: No valid price forecasts were generated")
        sys.exit(1)


if __name__ == "__main__":
    main()
