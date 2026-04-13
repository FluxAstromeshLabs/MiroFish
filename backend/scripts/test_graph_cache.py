"""Tests for graph-id sidecar cache helpers."""
import json
import os
import hashlib
import tempfile
import pytest

from run_trade import _load_graph_cache, _save_graph_cache


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_load_returns_none_when_no_sidecar(tmp_path):
    sidecar = tmp_path / "seed.md.json"
    result = _load_graph_cache(str(sidecar), "abc123")
    assert result is None


def test_load_returns_none_when_hash_missing(tmp_path):
    sidecar = tmp_path / "seed.md.json"
    sidecar.write_text(json.dumps({"otherhash": {"project_id": "p1", "graph_id": "g1", "cached_at": "2026-01-01"}}))
    result = _load_graph_cache(str(sidecar), "abc123")
    assert result is None


def test_load_returns_entry_on_hit(tmp_path):
    sidecar = tmp_path / "seed.md.json"
    entry = {"project_id": "proj_abc", "graph_id": "graph_xyz", "cached_at": "2026-04-13T10:00:00"}
    sidecar.write_text(json.dumps({"abc123": entry}))
    result = _load_graph_cache(str(sidecar), "abc123")
    assert result == ("proj_abc", "graph_xyz")


def test_save_creates_new_sidecar(tmp_path):
    sidecar = tmp_path / "seed.md.json"
    _save_graph_cache(str(sidecar), "abc123", "proj_abc", "graph_xyz")
    data = json.loads(sidecar.read_text())
    assert "abc123" in data
    assert data["abc123"]["project_id"] == "proj_abc"
    assert data["abc123"]["graph_id"] == "graph_xyz"
    assert "cached_at" in data["abc123"]


def test_save_silently_skips_when_dir_missing(tmp_path):
    sidecar = tmp_path / "nonexistent_dir" / "seed.md.json"
    # Should not raise even though the directory doesn't exist
    _save_graph_cache(str(sidecar), "abc123", "proj_abc", "graph_xyz")
    assert not sidecar.exists()


def test_save_preserves_existing_entries(tmp_path):
    sidecar = tmp_path / "seed.md.json"
    existing = {"oldhash": {"project_id": "p_old", "graph_id": "g_old", "cached_at": "2026-01-01"}}
    sidecar.write_text(json.dumps(existing))
    _save_graph_cache(str(sidecar), "newhash", "p_new", "g_new")
    data = json.loads(sidecar.read_text())
    assert "oldhash" in data
    assert "newhash" in data


def test_save_overwrites_same_hash(tmp_path):
    sidecar = tmp_path / "seed.md.json"
    existing = {"abc123": {"project_id": "p_old", "graph_id": "g_old", "cached_at": "2026-01-01"}}
    sidecar.write_text(json.dumps(existing))
    _save_graph_cache(str(sidecar), "abc123", "p_new", "g_new")
    data = json.loads(sidecar.read_text())
    assert data["abc123"]["project_id"] == "p_new"


def test_load_returns_none_on_corrupt_json(tmp_path):
    sidecar = tmp_path / "seed.md.json"
    sidecar.write_text("not valid json {{{")
    result = _load_graph_cache(str(sidecar), "abc123")
    assert result is None
