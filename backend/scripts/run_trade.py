"""
MiroFish Trade Decision Pipeline
Automates: seed.md → Ontology → Graph → Simulation → Interview → trade_decision.csv
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

def _parse_decision(llm, agent_name, response_text, seed_text):
    """Parse a free-text trade response into a structured decision dict. Returns None on failure."""
    parsed = llm.chat_json(
        messages=[
            {
                "role": "system",
                "content": (
                    "Extract the trade decision from the trader's response. "
                    "The market context is:\n"
                    f"{seed_text}\n\n"
                    "Return JSON with exactly these fields:\n"
                    '- direction: "LONG" or "SHORT"\n'
                    '- order_type: "LIMIT" or "MARKET"\n'
                    "- price: number (only for LIMIT orders, null for MARKET; must be near current market price)\n"
                    "- size: number (position size, must be realistic)\n"
                    "- leverage: integer (1-100)\n\n"
                    "If the response is vague, infer the most likely decision based on "
                    "their personality and the market data."
                )
            },
            {
                "role": "user",
                "content": f"Trader response:\n{response_text}"
            }
        ],
        temperature=0.1
    )

    return _validate_decision(parsed, agent_name)


def _validate_decision(parsed, agent_name):
    """Validate and normalize a parsed decision dict. Returns None on invalid data."""
    direction = str(parsed.get("direction", "")).upper()
    order_type = str(parsed.get("order_type", "")).upper()

    if direction not in ("LONG", "SHORT"):
        return None

    if order_type not in ("LIMIT", "MARKET"):
        order_type = "MARKET"

    price = parsed.get("price")
    if order_type == "MARKET":
        price = ""
    elif price is not None:
        try:
            price = float(price)
        except (TypeError, ValueError):
            price = ""

    try:
        size = float(parsed.get("size", 0))
        if size <= 0:
            return None
    except (TypeError, ValueError):
        return None

    try:
        leverage = int(parsed.get("leverage", 1))
        leverage = max(1, min(100, leverage))
    except (TypeError, ValueError):
        leverage = 1

    return {
        "name": agent_name,
        "direction": direction,
        "order_type": order_type,
        "price": price,
        "size": size,
        "leverage": leverage,
    }


def _fmt_decision(agent_name, decision):
    """Format a trade decision as a display string."""
    price_str = f"${decision['price']}" if decision['price'] != "" else "MARKET"
    return (f"{agent_name}: {decision['direction']:<5} "
            f"{decision['order_type']:<6} {price_str:<12} size={decision['size']}  {decision['leverage']}x")


def _decide_from_persona(llm, agent_name, persona, seed_text):
    """Generate trade decision directly from agent persona + market data (single LLM call)."""
    parsed = llm.chat_json(
        messages=[
            {
                "role": "system",
                "content": (
                    f"You are {agent_name}, a trader with the following profile:\n{persona}\n\n"
                    "Based on your personality and trading style, decide on a futures trade.\n\n"
                    "Return JSON with exactly these fields:\n"
                    '- direction: "LONG" or "SHORT"\n'
                    '- order_type: "LIMIT" or "MARKET"\n'
                    "- price: number (only for LIMIT orders, null for MARKET; must be near current market price)\n"
                    "- size: number (position size, must be realistic)\n"
                    "- leverage: integer (1-100)"
                )
            },
            {
                "role": "user",
                "content": (
                    f"Market data:\n{seed_text}\n\n"
                    "What is your trade decision? Return only JSON."
                )
            }
        ],
        temperature=0.8
    )
    return _validate_decision(parsed, agent_name)


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


def _interview_agents(base_url, simulation_id, llm, seed_text, id_to_profile, platform, session=None):
    """Interview agents via OASIS and parse responses into decisions (parallel)."""
    agent_count = len(id_to_profile)

    interview_prompt = (
        "Here is the current market data:\n"
        f"{seed_text}\n\n"
        "Based on this market data and your discussions with other traders, "
        "what is your trade decision? You MUST specify:\n"
        "1. Direction: LONG or SHORT\n"
        "2. Order type: LIMIT or MARKET\n"
        "3. If LIMIT, what exact price? (must be near current market price)\n"
        "4. Position size (be realistic)\n"
        "5. Leverage (1x-100x)\n\n"
        "Be specific with numbers. Give only ONE trade decision."
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

    # Collect valid responses for parallel parsing
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

    # Parse decisions in parallel
    decisions = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(_parse_decision, llm, name, resp, seed_text): (idx, name)
            for idx, name, resp in parse_tasks
        }
        for future in as_completed(futures):
            idx, name = futures[future]
            try:
                decision = future.result()
                if decision:
                    decisions.append(decision)
                    print(f"  [{idx}/{agent_count}] {_fmt_decision(name, decision)}")
                else:
                    print(f"  [{idx}/{agent_count}] {name}: could not parse decision")
            except Exception as e:
                print(f"  [{idx}/{agent_count}] {name}: parse error: {e}")

    return decisions


def _fallback_persona_decisions(llm, seed_text, id_to_profile):
    """Generate trade decisions from agent personas when interview is unavailable (parallel)."""
    agent_count = len(id_to_profile)

    print(f"  Falling back to persona-based decisions for {agent_count} agents")

    # Build task list
    tasks = []
    for idx, (agent_id, profile) in enumerate(id_to_profile.items(), 1):
        agent_name = profile.get("name", profile.get("user_name", f"agent_{agent_id}"))
        persona = profile.get("persona", profile.get("bio", ""))
        tasks.append((idx, agent_name, persona))

    # Run in parallel
    decisions = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(_decide_from_persona, llm, name, persona, seed_text): (idx, name)
            for idx, name, persona in tasks
        }
        for future in as_completed(futures):
            idx, name = futures[future]
            try:
                decision = future.result()
                if decision:
                    decisions.append(decision)
                    print(f"  [{idx}/{agent_count}] {_fmt_decision(name, decision)}")
                else:
                    print(f"  [{idx}/{agent_count}] {name}: could not parse decision")
            except Exception as e:
                print(f"  [{idx}/{agent_count}] {name}: error: {e}")

    return decisions


def step5_interview_for_trades(base_url, simulation_id, llm, seed_text, session=None):
    """Interview each agent for trade decisions, parse into structured data."""
    print("[Step 5/5] Interviewing agents for trade decisions...")

    id_to_profile, platform = _get_agent_profiles(base_url, simulation_id, session=session)
    agent_count = len(id_to_profile)

    # Check if simulation env is still alive for interview
    run_status = api("get", base_url, f"/api/simulation/{simulation_id}/run-status", session=session)
    env_alive = run_status.get("runner_status") not in ("stopped", "failed", "idle")

    if env_alive:
        print(f"  Found {agent_count} agents (platform: {platform}) — trying OASIS interview...")
        try:
            decisions = _interview_agents(base_url, simulation_id, llm, seed_text,
                                          id_to_profile, platform, session=session)
            if decisions:
                return decisions
        except Exception as e:
            print(f"  Interview failed: {e}")

    return _fallback_persona_decisions(llm, seed_text, id_to_profile)


# ============== CSV Output ==============

def write_csv(decisions, output_path):
    """Write trade decisions to CSV."""
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "direction", "order_type",
                                                "price", "size", "leverage"])
        writer.writeheader()
        writer.writerows(decisions)


# ============== Main ==============

def main():
    parser = argparse.ArgumentParser(description="MiroFish Trade Decision Pipeline")
    parser.add_argument("seed_file", help="Path to seed file (md/txt)")
    default_output = os.path.join(project_root, '..', 'rust-connectors', 'trade_decision.csv')
    parser.add_argument("-o", "--output", default=default_output,
                        help="Output CSV path (default: ../rust-connectors/trade_decision.csv)")
    parser.add_argument("-r", "--requirement", default=None,
                        help="Simulation requirement (default: uses seed file content)")
    parser.add_argument("--base-url", default="http://localhost:5001",
                        help="Flask server URL (default: http://localhost:5001)")
    parser.add_argument("--rounds", type=int, default=15,
                        help="Max simulation rounds (default: 15)")
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
    decisions = step5_interview_for_trades(args.base_url, simulation_id, llm, seed_text, session=session)

    if decisions:
        write_csv(decisions, args.output)
        print()
        print("=" * 50)
        print(f"Output: {args.output} ({len(decisions)} decisions)")
    else:
        print()
        print("=" * 50)
        print("Warning: No valid trade decisions were generated")
        sys.exit(1)


if __name__ == "__main__":
    main()
