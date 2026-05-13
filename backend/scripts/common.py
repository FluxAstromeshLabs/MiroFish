import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, os.path.join(project_root, "backend"))

from app.utils.llm_client import LLMClient  # noqa: E402


def resolve_path(path: str) -> str:
    """Return absolute path, resolving relative paths from project root."""
    if os.path.isabs(path):
        return path
    return os.path.join(project_root, path)
