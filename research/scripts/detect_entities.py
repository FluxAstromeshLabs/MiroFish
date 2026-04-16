"""
Step 1: Detect entities — upload seed docs, generate ontology, build graph.

Usage:
    python -m research.scripts.detect_entities \
        --seed-file research/data/population_v1.md \
        --simulation-requirement "Simulate market participants reacting to price and news."

Can also be imported and called from the orchestrator.
"""

import argparse
import logging
import sys

from .mirofish_client import MirofishClient, MirofishAPIError
from .run_artifacts import RunArtifacts

logger = logging.getLogger("mirofish.detect_entities")


def detect_entities(
    client: MirofishClient,
    artifacts: RunArtifacts,
    seed_files: list[str],
    simulation_requirement: str,
    project_name: str = "Research Run",
    additional_context: str = "",
    force_rebuild: bool = False,
) -> dict:
    """
    Run ontology generation + graph build. Returns dict with project_id, graph_id, ontology.

    Supports resume: skips steps if artifacts already exist (unless force_rebuild).
    """
    result = {}

    # ── Step 1a: Generate ontology ──────────────────────────
    existing_project = artifacts.read_json("project.json")
    if existing_project and not force_rebuild:
        logger.info(f"Resuming from existing project: {existing_project['project_id']}")
        project_id = existing_project["project_id"]
        ontology = artifacts.read_json("ontology.json")
    else:
        logger.info(f"Generating ontology from {len(seed_files)} seed file(s)...")
        data = client.generate_ontology(
            file_paths=seed_files,
            simulation_requirement=simulation_requirement,
            project_name=project_name,
            additional_context=additional_context,
        )
        project_id = data["project_id"]
        ontology = data.get("ontology", {})

        artifacts.write_json("project.json", {
            "project_id": project_id,
            "project_name": data.get("project_name", project_name),
            "files": data.get("files", []),
            "total_text_length": data.get("total_text_length", 0),
        })
        artifacts.write_json("ontology.json", ontology)
        artifacts.save_manifest(project_id=project_id)
        logger.info(f"Ontology generated: {len(ontology.get('entity_types', []))} entity types, "
                     f"{len(ontology.get('edge_types', []))} edge types")

    result["project_id"] = project_id
    result["ontology"] = ontology

    # ── Step 1b: Build graph ────────────────────────────────
    existing_graph = artifacts.read_json("graph.json")
    if existing_graph and existing_graph.get("graph_id") and not force_rebuild:
        logger.info(f"Resuming from existing graph: {existing_graph['graph_id']}")
        graph_id = existing_graph["graph_id"]
    else:
        logger.info("Starting graph build...")
        build_data = client.build_graph(project_id, force=force_rebuild)
        task_id = build_data.get("task_id")

        if not task_id:
            raise MirofishAPIError("Graph build did not return a task_id", response_data=build_data)

        logger.info(f"Graph build task started: {task_id}")
        task_result = client.poll_task(task_id, label="graph-build")
        graph_id = task_result.get("result", {}).get("graph_id") if isinstance(task_result.get("result"), dict) else None

        # If graph_id not in task result, try to read from project
        if not graph_id:
            # The graph build updates the project with graph_id, re-fetch it
            # Try the project list or just store what we have
            logger.warning("graph_id not found in task result, checking project...")

        artifacts.write_json("graph.json", {
            "graph_id": graph_id,
            "task_id": task_id,
            "task_result": task_result,
        })
        artifacts.save_manifest(graph_id=graph_id, graph_task_id=task_id)
        logger.info(f"Graph build complete: graph_id={graph_id}")

    result["graph_id"] = graph_id
    return result


def main():
    parser = argparse.ArgumentParser(description="Step 1: Detect entities and build graph")
    parser.add_argument("--seed-file", required=True, action="append", dest="seed_files",
                        help="Path to seed document (can repeat)")
    parser.add_argument("--simulation-requirement", required=True)
    parser.add_argument("--project-name", default="Research Run")
    parser.add_argument("--additional-context", default="")
    parser.add_argument("--base-url", default=None, help="MiroFish API base URL")
    parser.add_argument("--run-dir", required=True, help="Path to run artifacts folder")
    parser.add_argument("--force-rebuild", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    client = MirofishClient(base_url=args.base_url)
    artifacts = RunArtifacts.from_existing(args.run_dir)

    try:
        result = detect_entities(
            client=client,
            artifacts=artifacts,
            seed_files=args.seed_files,
            simulation_requirement=args.simulation_requirement,
            project_name=args.project_name,
            additional_context=args.additional_context,
            force_rebuild=args.force_rebuild,
        )
        print(f"Done. project_id={result['project_id']} graph_id={result['graph_id']}")
    except MirofishAPIError as e:
        logger.error(f"API error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
