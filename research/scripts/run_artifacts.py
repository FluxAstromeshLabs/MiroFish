"""
Run artifact management — creates run folders and writes structured artifacts.
"""

import json
import os
import re
import logging
from datetime import datetime

logger = logging.getLogger("mirofish.artifacts")

DEFAULT_RUNS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "runs")


def slugify(text: str, max_len: int = 40) -> str:
    """Turn text into a filesystem-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = text.strip("_")
    return text[:max_len]


class RunArtifacts:
    """Manages a single run folder under research/runs/."""

    def __init__(self, run_dir: str):
        self.run_dir = run_dir
        os.makedirs(run_dir, exist_ok=True)

    @classmethod
    def create(cls, slug: str = "run", runs_dir: str = None) -> "RunArtifacts":
        """Create a new run folder with timestamp prefix."""
        base = runs_dir or DEFAULT_RUNS_DIR
        os.makedirs(base, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_name = f"{ts}_{slugify(slug)}"
        run_dir = os.path.join(base, folder_name)
        os.makedirs(run_dir, exist_ok=True)
        logger.info(f"Created run folder: {run_dir}")
        return cls(run_dir)

    @classmethod
    def from_existing(cls, run_dir: str) -> "RunArtifacts":
        """Resume from an existing run folder."""
        if not os.path.isdir(run_dir):
            raise FileNotFoundError(f"Run folder not found: {run_dir}")
        return cls(run_dir)

    def path(self, filename: str) -> str:
        return os.path.join(self.run_dir, filename)

    def write_json(self, filename: str, data) -> str:
        """Write data as JSON. Returns the file path."""
        filepath = self.path(filename)
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        logger.info(f"Wrote {filename}")
        return filepath

    def read_json(self, filename: str):
        """Read a JSON artifact, or return None if missing."""
        filepath = self.path(filename)
        if not os.path.exists(filepath):
            return None
        with open(filepath) as f:
            return json.load(f)

    def write_text(self, filename: str, text: str) -> str:
        filepath = self.path(filename)
        with open(filepath, "w") as f:
            f.write(text)
        logger.info(f"Wrote {filename}")
        return filepath

    def has(self, filename: str) -> bool:
        return os.path.exists(self.path(filename))

    def save_manifest(self, **ids):
        """Save/update manifest.json with canonical IDs and timestamps."""
        manifest = self.read_json("manifest.json") or {}
        manifest.update(ids)
        manifest["updated_at"] = datetime.now().isoformat()
        if "created_at" not in manifest:
            manifest["created_at"] = manifest["updated_at"]
        self.write_json("manifest.json", manifest)

    def save_inputs(self, **inputs):
        """Save CLI args and resolved config."""
        self.write_json("inputs.json", inputs)
