"""
End-to-end MiroFish research automation orchestrator.

Runs the full pipeline:
  1. detect_entities — upload seed docs, generate ontology, build graph
  2. start_simulation — create, prepare, start, wait for env
  3. collect_feedback — interview all agents, save results, close env

Usage:
    python -m research.scripts.run_mirofish_flow \
        --seed-file research/data/population_v1.md \
        --question "Will BTC sustain the current move over the next 7 days?" \
        --simulation-requirement "Simulate market participants reacting to price and news."

Resume a previous run:
    python -m research.scripts.run_mirofish_flow \
        --resume research/runs/20260416_120000_btc_sim \
        --question "Will BTC sustain the current move over the next 7 days?"
"""

import argparse
import logging
import sys

from .mirofish_client import MirofishClient, MirofishAPIError
from .run_artifacts import RunArtifacts, slugify
from .detect_entities import detect_entities
from .start_simulation import start_simulation
from .collect_feedback import collect_feedback

logger = logging.getLogger("mirofish.flow")


def run_flow(
    client: MirofishClient,
    artifacts: RunArtifacts,
    seed_files: list[str],
    question: str,
    simulation_requirement: str,
    project_name: str = "Research Run",
    additional_context: str = "",
    entity_types: list[str] = None,
    platform: str = "parallel",
    max_rounds: int = None,
    force_rebuild_graph: bool = False,
    force_regenerate_simulation: bool = False,
    interview_timeout: int = 180,
):
    """Execute the full research automation pipeline."""

    # Save inputs for reproducibility
    artifacts.save_inputs(
        seed_files=seed_files,
        question=question,
        simulation_requirement=simulation_requirement,
        project_name=project_name,
        additional_context=additional_context,
        entity_types=entity_types,
        platform=platform,
        max_rounds=max_rounds,
    )

    # ── Step 1: Detect entities + build graph ───────────────
    logger.info("=" * 60)
    logger.info("STEP 1: Detect entities and build graph")
    logger.info("=" * 60)

    step1 = detect_entities(
        client=client,
        artifacts=artifacts,
        seed_files=seed_files,
        simulation_requirement=simulation_requirement,
        project_name=project_name,
        additional_context=additional_context,
        force_rebuild=force_rebuild_graph,
    )
    project_id = step1["project_id"]
    graph_id = step1["graph_id"]
    logger.info(f"Step 1 complete: project_id={project_id}, graph_id={graph_id}")

    # ── Step 2: Start simulation ────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 2: Start simulation")
    logger.info("=" * 60)

    step2 = start_simulation(
        client=client,
        artifacts=artifacts,
        project_id=project_id,
        graph_id=graph_id,
        entity_types=entity_types,
        platform=platform,
        max_rounds=max_rounds,
        force_regenerate=force_regenerate_simulation,
    )
    simulation_id = step2["simulation_id"]
    logger.info(f"Step 2 complete: simulation_id={simulation_id}")

    # ── Step 3: Collect feedback ────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 3: Collect agent feedback")
    logger.info("=" * 60)

    step3 = collect_feedback(
        client=client,
        artifacts=artifacts,
        simulation_id=simulation_id,
        question=question,
        platform=None,  # interview both platforms
        interview_timeout=interview_timeout,
    )
    logger.info(f"Step 3 complete: {step3['interviews_count']} responses collected")

    # ── Done ────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info(f"Pipeline complete. Artifacts in: {artifacts.run_dir}")
    logger.info("=" * 60)

    return {
        "project_id": project_id,
        "graph_id": graph_id,
        "simulation_id": simulation_id,
        "interviews_count": step3["interviews_count"],
        "run_dir": artifacts.run_dir,
    }


def main():
    parser = argparse.ArgumentParser(
        description="MiroFish end-to-end research automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Inputs
    parser.add_argument("--seed-file", action="append", dest="seed_files",
                        help="Path to seed document (can repeat)")
    parser.add_argument("--question", required=True, help="Research question for agent interviews")
    parser.add_argument("--simulation-requirement", default="",
                        help="Describes the simulation goal")
    parser.add_argument("--additional-context", default="")
    parser.add_argument("--project-name", default="Research Run")

    # Simulation config
    parser.add_argument("--entity-types", default=None,
                        help="Comma-separated entity types to filter")
    parser.add_argument("--platform", default="parallel",
                        choices=["twitter", "reddit", "parallel"])
    parser.add_argument("--max-rounds", type=int, default=None)
    parser.add_argument("--interview-timeout", type=int, default=180)

    # Resume / force
    parser.add_argument("--resume", default=None, metavar="RUN_DIR",
                        help="Resume from an existing run folder")
    parser.add_argument("--output-dir", default=None,
                        help="Custom output directory for runs")
    parser.add_argument("--force-rebuild-graph", action="store_true")
    parser.add_argument("--force-regenerate-simulation", action="store_true")

    # Connection
    parser.add_argument("--base-url", default=None, help="MiroFish API base URL")
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    # Validate inputs
    if not args.resume and not args.seed_files:
        parser.error("--seed-file is required (unless --resume is used)")

    # Set up artifacts
    if args.resume:
        artifacts = RunArtifacts.from_existing(args.resume)
        # Recover seed_files from saved inputs if not provided
        if not args.seed_files:
            saved = artifacts.read_json("inputs.json") or {}
            args.seed_files = saved.get("seed_files", [])
            if not args.seed_files:
                parser.error("No seed files found in resumed run or CLI args")
            if not args.simulation_requirement:
                args.simulation_requirement = saved.get("simulation_requirement", "")
    else:
        slug = slugify(args.question[:60])
        artifacts = RunArtifacts.create(slug=slug, runs_dir=args.output_dir)

    client = MirofishClient(base_url=args.base_url)
    entity_types = args.entity_types.split(",") if args.entity_types else None

    try:
        result = run_flow(
            client=client,
            artifacts=artifacts,
            seed_files=args.seed_files,
            question=args.question,
            simulation_requirement=args.simulation_requirement,
            project_name=args.project_name,
            additional_context=args.additional_context,
            entity_types=entity_types,
            platform=args.platform,
            max_rounds=args.max_rounds,
            force_rebuild_graph=args.force_rebuild_graph,
            force_regenerate_simulation=args.force_regenerate_simulation,
            interview_timeout=args.interview_timeout,
        )
        print(f"\nPipeline complete!")
        print(f"  Run dir:        {result['run_dir']}")
        print(f"  Project:        {result['project_id']}")
        print(f"  Graph:          {result['graph_id']}")
        print(f"  Simulation:     {result['simulation_id']}")
        print(f"  Responses:      {result['interviews_count']}")
    except MirofishAPIError as e:
        logger.error(f"API error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(130)


if __name__ == "__main__":
    main()
