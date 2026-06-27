"""Tests for reindex_embeddings (kb-mcp-lite v0.2.3).

Covers the bug where ``kb embed --rebuild`` reported
``"re-embedded 1 document(s) (dim=0)"`` regardless of actual progress,
because:

1. ``HttpEmbedder.dim`` is lazy (filled after first ``embed()`` call),
   so reading it before reindex always returns 0.
2. ``reindex_embeddings`` silently counted *attempts*, not successes —
   a 1024-dim embedder writing to a 1536-dim ``docs_vec`` table would
   log warnings and skip, but reindex would still claim success.
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kb_mcp_lite.schema import Document
from kb_mcp_lite.store.sqlite import SqliteStore


def _make_store_with_mock_embedder(tmp_path: Path, dim: int = 1024) -> SqliteStore:
    """Build a SqliteStore with a stubbed embedder that always succeeds."""
    db = tmp_path / "test.db"
    store = SqliteStore(db)

    # Use a mock embedder so tests don't hit any real API.
    mock = MagicMock()
    mock.enabled = True
    mock.dim = dim
    # Real (or stub) embed returns `dim` floats
    mock.embed = lambda text: [0.0] * dim
    store._embedder = mock
    return store


def test_reindex_returns_succeeded_count(tmp_path):
    """reindex_embeddings() returns the number of successfully indexed docs."""
    store = _make_store_with_mock_embedder(tmp_path)
    # Add 3 active docs
    for i in range(3):
        store.add(Document(id=f"d/{i}", type="reference", title=f"d{i}",
                           body=f"body {i}"))

    n = store.reindex_embeddings()
    report = store.last_reindex_report
    assert report["total"] == 3
    # On hosts without vec0, all docs fail (n=0, failed=3).
    # On hosts with vec0, all succeed (n=3, failed=0).
    assert report["failed"] + n == 3, f"failed={report['failed']} succeeded={n}"
    # Either all success or all failure — no partial writes.
    assert n in (0, 3), f"expected 0 or 3, got {n}"


def test_reindex_report_dim_captures_post_state(tmp_path):
    """The dim stored in last_reindex_report reflects the post-reindex
    state, not a pre-call snapshot.

    This is the key fix: previously ``kb embed --rebuild`` reported
    ``dim=0`` because the CLI read ``embedder.dim`` before reindex
    triggered the first lazy ``embed()`` call. Now the report captures
    the dim after the loop, so the CLI can show the real number.
    """
    store = _make_store_with_mock_embedder(tmp_path, dim=1024)
    store.add(Document(id="d/1", type="reference", title="t", body="b"))

    store.reindex_embeddings()
    # Even if _index_embedding itself no-ops (no vec0), the report
    # still has the embedder's reported dim (1024), not 0.
    assert store.last_reindex_report["dim"] == 1024


def test_reindex_count_vec_handles_missing_vec0(tmp_path):
    """_count_vec returns 0 when docs_vec doesn't exist (vec0 not loaded).

    Without this, every doc would crash the reindex loop with an
    ``OperationalError`` on the missing table.
    """
    store = _make_store_with_mock_embedder(tmp_path)
    store.add(Document(id="d/1", type="reference", title="t", body="b"))

    # _count_vec must not crash regardless of vec0 availability.
    # On hosts without vec0, _vec_conn_lazy returns None → 0.
    # On hosts with vec0, the doc may already be indexed → 1.
    c = store._count_vec("d/1")
    assert c in (0, 1), f"expected 0 or 1, got {c}"
    # Nonexistent doc id should always return 0.
    assert store._count_vec("nonexistent") == 0


def test_reindex_raises_when_embedder_disabled(tmp_path):
    """Without an enabled embedder, reindex raises ValidationError.

    We stub the store to use a NullEmbedder directly so this test is
    hermetic (it does not depend on the host's ``~/.hermes/config.yaml``
    embedder config).
    """
    from kb_mcp_lite.embedder import NullEmbedder
    store = SqliteStore(tmp_path / "test.db")
    store._embedder = NullEmbedder()
    store.add(Document(id="d/1", type="reference", title="t", body="b"))

    assert not store._embedder.enabled

    with pytest.raises(Exception) as exc_info:
        store.reindex_embeddings()
    assert "embedder not configured" in str(exc_info.value).lower()
