"""
Step 2: Start simulation — fetch entities, create, prepare, start, wait for env.

Usage:
    python -m research.scripts.start_simulation \
        --run-dir research/runs/20260416_120000_btc_sim

Can also be imported and called from the orchestrator.
"""

import argparse
import logging
import sys

from .mirofish_client import MirofishClient, MirofishAPIError
from .run_artifacts import RunArtifacts

logger = logging.getLogger("mirofish.start_simulation")


def start_simulation(
    client: MirofishClient,
    artifacts: RunArtifacts,
    project_id: str,
    graph_id: str,
    entity_types: list[str] = None,
    platform: str = "parallel",
    max_rounds: int = None,
    enable_graph_memory_update: bool = False,
    force_regenerate: bool = False,
) -> dict:
    """
    Create, prepare, and start a simulation. Returns dict with simulation_id.

    Supports resume: skips completed steps based on existing artifacts.
    """
    result = {}

    # ── Fetch entities ──────────────────────────────────────
    if not artifacts.has("entities.json") or force_regenerate:
        logger.info(f"Fetching entities from graph {graph_id}...")
        entities_data = client.get_entities(graph_id)
        artifacts.write_json("entities.json", entities_data)
        logger.info(f"Fetched {entities_data.get('total_count', '?')} entities")
    else:
        entities_data = artifacts.read_json("entities.json")
        logger.info("Resuming with existing entities.json")

    result["entities"] = entities_data

    # ── Create simulation ───────────────────────────────────
    existing_sim = artifacts.read_json("simulation.json")
    if existing_sim and existing_sim.get("simulation_id") and not force_regenerate:
        simulation_id = existing_sim["simulation_id"]
        logger.info(f"Resuming from existing simulation: {simulation_id}")
    else:
        logger.info("Creating simulation...")
        create_data = client.create_simulation(
            project_id=project_id,
            graph_id=graph_id,
        )
        simulation_id = create_data["simulation_id"]
        artifacts.write_json("simulation.json", create_data)
        artifacts.save_manifest(simulation_id=simulation_id)
        logger.info(f"Simulation created: {simulation_id}")

    result["simulation_id"] = simulation_id

    # ── Prepare simulation ──────────────────────────────────
    existing_prepare = artifacts.read_json("prepare_task.json")
    already_prepared = existing_prepare and existing_prepare.get("status") in ("ready", "completed")

    if already_prepared and not force_regenerate:
        logger.info("Simulation already prepared, skipping prepare step")
    else:
        logger.info("Preparing simulation...")
        prepare_kwargs = {}
        if entity_types:
            prepare_kwargs["entity_types"] = entity_types
        if force_regenerate:
            prepare_kwargs["force_regenerate"] = True

        prepare_data = client.prepare_simulation(simulation_id, **prepare_kwargs)

        if prepare_data.get("already_prepared") and not force_regenerate:
            logger.info("Backend reports simulation already prepared")
            artifacts.write_json("prepare_task.json", {"status": "ready", **prepare_data})
        else:
            task_id = prepare_data.get("task_id")
            if task_id:
                logger.info(f"Prepare task started: {task_id}")
                prepare_result = client.poll_prepare_status(
                    simulation_id=simulation_id,
                    task_id=task_id,
                )
                artifacts.write_json("prepare_task.json", prepare_result)
            else:
                artifacts.write_json("prepare_task.json", {"status": "ready", **prepare_data})

    # ── Start simulation ────────────────────────────────────
    logger.info(f"Starting simulation (platform={platform})...")
    start_kwargs = {"platform": platform}
    if max_rounds is not None:
        start_kwargs["max_rounds"] = max_rounds
    if enable_graph_memory_update:
        start_kwargs["enable_graph_memory_update"] = True

    start_data = client.start_simulation(simulation_id, **start_kwargs)
    logger.info(f"Simulation started: pid={start_data.get('process_pid')}")

    # ── Wait for simulation rounds to complete ──────────────
    logger.info("Waiting for simulation rounds to complete...")
    run_status = client.poll_run_status(simulation_id, interval=10, timeout=1800)
    artifacts.write_json("discussion_status.json", run_status)
    logger.info(f"Simulation rounds complete: status={run_status.get('runner_status')}")

    # ── Verify env is alive for interviews ──────────────────
    logger.info("Verifying env is alive for interviews...")
    env_status = client.poll_env_alive(simulation_id, interval=5, timeout=60)
    logger.info("Environment is alive and ready for interviews")

    result["run_status"] = run_status
    result["env_status"] = env_status
    return result


def main():
    parser = argparse.ArgumentParser(description="Step 2: Start simulation")
    parser.add_argument("--run-dir", required=True, help="Path to run artifacts folder")
    parser.add_argument("--entity-types", default=None, help="Comma-separated entity types to filter")
    parser.add_argument("--platform", default="parallel", choices=["twitter", "reddit", "parallel"])
    parser.add_argument("--max-rounds", type=int, default=None)
    parser.add_argument("--enable-graph-memory-update", action="store_true")
    parser.add_argument("--force-regenerate", action="store_true")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    client = MirofishClient(base_url=args.base_url)
    artifacts = RunArtifacts.from_existing(args.run_dir)

    manifest = artifacts.read_json("manifest.json")
    if not manifest or not manifest.get("project_id") or not manifest.get("graph_id"):
        logger.error("manifest.json missing project_id or graph_id. Run detect_entities first.")
        sys.exit(1)

    entity_types = args.entity_types.split(",") if args.entity_types else None

    try:
        result = start_simulation(
            client=client,
            artifacts=artifacts,
            project_id=manifest["project_id"],
            graph_id=manifest["graph_id"],
            entity_types=entity_types,
            platform=args.platform,
            max_rounds=args.max_rounds,
            enable_graph_memory_update=args.enable_graph_memory_update,
            force_regenerate=args.force_regenerate,
        )
        print(f"Done. simulation_id={result['simulation_id']}")
    except MirofishAPIError as e:
        logger.error(f"API error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
