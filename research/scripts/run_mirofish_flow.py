"""
End-to-end MiroFish research automation orchestrator.

Runs the full pipeline:
  1. detect_entities — upload seed docs, generate ontology, build graph
  2. start_simulation — create, prepare, start, wait for env
  3. collect_feedback — interview all agents, save results, close env

Usage (input folder — preferred):
    python -m research.scripts.run_mirofish_flow \
        --input-folder research/data/btc

    The folder must contain:
      - population.md   (world seed document)
      - news.txt        (news events)
      - ohlcv.txt       (price data)
      - goal.md         (research question, first line used as --question)

Usage (explicit files):
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
import hashlib
import json
import logging
import os
import sys

from .mirofish_client import MirofishClient, MirofishAPIError
from .run_artifacts import RunArtifacts
from .detect_entities import detect_entities
from .start_simulation import start_simulation
from .collect_feedback import collect_feedback

logger = logging.getLogger("mirofish.flow")

DEFAULT_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache", "graphs")


def load_input_folder(folder: str) -> dict:
    """Load population.md, news.txt, ohlcv.txt, and goal.md from a folder.

    Returns dict with keys: seed_files, question, data_files.
    """
    required = {
        "population.md": "world seed document",
        "news.txt": "news events",
        "ohlcv.txt": "price data",
        "goal.md": "research question",
    }
    for filename, desc in required.items():
        path = os.path.join(folder, filename)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Missing {desc}: {path}")

    population = os.path.join(folder, "population.md")
    news = os.path.join(folder, "news.txt")
    ohlcv = os.path.join(folder, "ohlcv.txt")
    goal_path = os.path.join(folder, "goal.md")

    with open(goal_path) as f:
        question = f.read().strip().split("\n")[0]

    return {
        "seed_files": [population, news, ohlcv],
        "question": question,
    }


def compute_data_hash(seed_files: list[str]) -> str:
    """Compute a SHA-256 hash over the contents of the given files (sorted by basename)."""
    h = hashlib.sha256()
    for path in sorted(seed_files, key=os.path.basename):
        with open(path, "rb") as f:
            h.update(f.read())
    return h.hexdigest()


def find_cached_graph(data_hash: str, cache_dir: str = None) -> dict | None:
    """Look up a cached graph result by data hash. Returns the cached dict or None."""
    cache_dir = cache_dir or DEFAULT_CACHE_DIR
    cache_file = os.path.join(cache_dir, f"{data_hash}.json")
    if os.path.isfile(cache_file):
        with open(cache_file) as f:
            cached = json.load(f)
        logger.info(f"Graph cache hit: {data_hash[:12]}...")
        return cached
    return None


def save_graph_cache(data_hash: str, graph_result: dict, cache_dir: str = None):
    """Persist a graph build result keyed by data hash."""
    cache_dir = cache_dir or DEFAULT_CACHE_DIR
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, f"{data_hash}.json")
    with open(cache_file, "w") as f:
        json.dump(graph_result, f, indent=2, ensure_ascii=False, default=str)
    logger.info(f"Graph cached: {data_hash[:12]}... -> {cache_file}")


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
    use_graph_cache: bool = True,
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
    logger.info("-" * 40)
    logger.info("STEP 1: Detect entities and build graph")
    logger.info("-" * 40)

    # Check graph cache before running the expensive build
    data_hash = compute_data_hash(seed_files)
    artifacts.write_text("data_hash.txt", data_hash)
    logger.info(f"Data hash: {data_hash[:12]}...")

    cached = None
    if use_graph_cache and not force_rebuild_graph:
        cached = find_cached_graph(data_hash)

    if cached:
        project_id = cached["project_id"]
        graph_id = cached["graph_id"]
        # Restore artifacts from cache so downstream steps can resume
        if cached.get("ontology"):
            artifacts.write_json("ontology.json", cached["ontology"])
        artifacts.write_json("project.json", {"project_id": project_id})
        artifacts.write_json("graph.json", {"graph_id": graph_id})
        artifacts.save_manifest(project_id=project_id, graph_id=graph_id)
        logger.info(f"Step 1 complete (cached): project_id={project_id}, graph_id={graph_id}")
    else:
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

        # Save to cache for future runs
        if use_graph_cache:
            save_graph_cache(data_hash, {
                "project_id": project_id,
                "graph_id": graph_id,
                "ontology": step1.get("ontology"),
            })
        logger.info(f"Step 1 complete: project_id={project_id}, graph_id={graph_id}")

    # ── Step 2: Start simulation ────────────────────────────
    logger.info("-" * 40)
    logger.info("STEP 2: Start simulation")
    logger.info("-" * 40)

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
    logger.info("-" * 40)
    logger.info("STEP 3: Collect agent feedback")
    logger.info("-" * 40)

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
    logger.info("-" * 40)
    logger.info(f"Pipeline complete. Artifacts in: {artifacts.run_dir}")
    logger.info("-" * 40)

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
    parser.add_argument("--input-folder", default=None,
                        help="Folder containing population.md, news.txt, ohlcv.txt, goal.md")
    parser.add_argument("--seed-file", action="append", dest="seed_files",
                        help="Path to seed document (can repeat). Ignored if --input-folder is set.")
    parser.add_argument("--question", default=None, help="Research question (loaded from goal.md if --input-folder)")
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
    parser.add_argument("--no-graph-cache", action="store_true",
                        help="Disable graph cache lookup/storage")

    # Connection
    parser.add_argument("--base-url", default=None, help="MiroFish API base URL")
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    # Resolve --input-folder into seed_files + question
    if args.input_folder:
        folder_data = load_input_folder(args.input_folder)
        args.seed_files = folder_data["seed_files"]
        if not args.question:
            args.question = folder_data["question"]
        if not args.simulation_requirement:
            args.simulation_requirement = args.question
        logger.info(f"Loaded input folder: {args.input_folder}")
        logger.info(f"  question: {args.question}")
        logger.info(f"  seed files: {args.seed_files}")

    # Validate inputs
    if not args.resume and not args.seed_files:
        parser.error("--seed-file or --input-folder is required (unless --resume is used)")
    if not args.question and not args.resume:
        parser.error("--question is required (or use --input-folder with goal.md)")

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
        goal_hash = hashlib.sha256(args.question.encode()).hexdigest()[:12]
        artifacts = RunArtifacts.create(slug=goal_hash, runs_dir=args.output_dir)

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
            use_graph_cache=not args.no_graph_cache,
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
