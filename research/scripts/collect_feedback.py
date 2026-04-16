"""
Step 3: Collect agent feedback — interview all agents, normalize results, close env.

Usage:
    python -m research.scripts.collect_feedback \
        --run-dir research/runs/20260416_120000_btc_sim \
        --question "Will BTC sustain the current move over the next 7 days?"

Can also be imported and called from the orchestrator.
"""

import argparse
import logging
import sys

from .mirofish_client import MirofishClient, MirofishAPIError
from .run_artifacts import RunArtifacts

logger = logging.getLogger("mirofish.collect_feedback")

DEFAULT_PROMPT_TEMPLATE = (
    "Given your persona, prior timeline, and interactions in the simulation, "
    "answer this research question directly and briefly: {question}"
)


def collect_feedback(
    client: MirofishClient,
    artifacts: RunArtifacts,
    simulation_id: str,
    question: str,
    prompt_template: str = None,
    platform: str = None,
    interview_timeout: int = 180,
) -> dict:
    """
    Interview all agents with a research question, normalize output, close env.
    Returns the structured feedback data.
    """
    template = prompt_template or DEFAULT_PROMPT_TEMPLATE
    prompt = template.format(question=question)

    # ── Interview all agents ────────────────────────────────
    logger.info(f"Interviewing all agents (timeout={interview_timeout}s)...")
    logger.info(f"Question: {question}")

    raw_data = client.interview_all(
        simulation_id=simulation_id,
        prompt=prompt,
        platform=platform,
        timeout=interview_timeout,
    )
    artifacts.write_json("feedback_raw.json", raw_data)
    logger.info(f"Received {raw_data.get('interviews_count', '?')} interview responses")

    # ── Normalize into table format ─────────────────────────
    results = raw_data.get("result", {}).get("results", {})
    entities_data = artifacts.read_json("entities.json") or {}

    # Build entity lookup by name for metadata enrichment
    entity_lookup = {}
    for entity in entities_data.get("entities", []):
        name = entity.get("name", "")
        entity_lookup[name.lower()] = entity

    table = []
    for key, interview in results.items():
        row = {
            "key": key,
            "agent_id": interview.get("agent_id"),
            "platform": interview.get("platform", ""),
            "response": interview.get("response", ""),
        }
        table.append(row)

    artifacts.write_json("feedback_table.json", table)

    # ── Generate summary markdown ───────────────────────────
    lines = [
        f"# Agent Feedback Summary",
        f"",
        f"**Question:** {question}",
        f"**Total responses:** {len(table)}",
        f"**Simulation:** {simulation_id}",
        f"",
        f"---",
        f"",
    ]
    for row in table:
        platform_tag = f"[{row['platform']}]" if row['platform'] else ""
        lines.append(f"### Agent {row['agent_id']} {platform_tag}")
        lines.append(f"")
        lines.append(row["response"])
        lines.append(f"")

    artifacts.write_text("feedback_summary.md", "\n".join(lines))

    # ── Close environment ───────────────────────────────────
    logger.info("Closing simulation environment...")
    try:
        client.close_env(simulation_id)
        logger.info("Environment closed")
    except MirofishAPIError as e:
        logger.warning(f"Failed to close env (may already be closed): {e}")

    return {
        "interviews_count": len(table),
        "feedback_table": table,
    }


def main():
    parser = argparse.ArgumentParser(description="Step 3: Collect agent feedback")
    parser.add_argument("--run-dir", required=True, help="Path to run artifacts folder")
    parser.add_argument("--question", required=True, help="Research question to ask all agents")
    parser.add_argument("--platform", default=None, choices=["twitter", "reddit"],
                        help="Limit to one platform (default: both)")
    parser.add_argument("--interview-timeout", type=int, default=180)
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
    if not manifest or not manifest.get("simulation_id"):
        logger.error("manifest.json missing simulation_id. Run start_simulation first.")
        sys.exit(1)

    try:
        result = collect_feedback(
            client=client,
            artifacts=artifacts,
            simulation_id=manifest["simulation_id"],
            question=args.question,
            platform=args.platform,
            interview_timeout=args.interview_timeout,
        )
        print(f"Done. Collected {result['interviews_count']} responses.")
    except MirofishAPIError as e:
        logger.error(f"API error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
