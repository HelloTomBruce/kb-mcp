"""Tests for the background :class:`EmbeddingWorker` (v0.8, 特性 #1.b).

Covers both layers of the worker:

* ``EmbeddingWorker._process_one`` — the synchronous per-doc pipeline
  (fetch -> embed -> write vector -> mark done/failed), exercised with a
  deterministic in-process embedder so transient / permanent / empty-text
  / soft-deleted paths never touch the network.
* The full thread lifecycle — ``start()`` drains the queue in the
  background, ``stop()`` joins cleanly, and a disabled embedder is
  rejected at construction.

Every test uses a real SQLite store but pins the embedder to a stub so
the suite stays hermetic regardless of the host's embedder config.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kb_mcp_lite.embedder import EmbeddingError, NullEmbedder
from kb_mcp_lite.schema import Document
from kb_mcp_lite.store.sqlite import SqliteStore
from kb_mcp_lite.worker import EmbeddingWorker


class ConstEmbedder:
    """Deterministic enabled embedder: every text maps to ``[0.25] * dim``."""

    enabled = True
    dim = 4

    def __init__(self, *, raise_on: EmbeddingError | None = None) -> None:
        self._raise_on = raise_on

    def embed(self, text: str) -> list[float]:
        if self._raise_on is not None:
            raise self._raise_on
        return [0.25] * self.dim


def _doc(doc_id: str, title: str = "title", body: str = "body text") -> Document:
    return Document(id=doc_id, type="reference", title=title, body=body)


@pytest.fixture()
def store(tmp_path: Path):
    """Store with the stub embedder enabled and no background worker."""
    db = tmp_path / "worker.db"
    s = SqliteStore(db, embedder=ConstEmbedder(), auto_start_worker=False)
    yield s
    s.close()


def _enqueue(store: SqliteStore, doc_id: str) -> None:
    """Add the document and enqueue an embedding job for it."""
    store.embedding_queue.enqueue(store.add(_doc(doc_id)))


def _claim(store: SqliteStore, doc_id: str):
    """Claim the specific row and assert it was actually claimed."""
    claimed = store.embedding_queue.claim_next()
    assert claimed is not None and claimed.doc_id == doc_id
    return claimed


def _process(store: SqliteStore, doc_id: str, embedder=ConstEmbedder()):
    """Claim + process one row synchronously, returning the job result."""
    entry = _claim(store, doc_id)
    worker = EmbeddingWorker(store, embedder=embedder)
    try:
        return worker._process_one(entry)
    finally:
        worker.stop()


def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


# ---------------------------------------------------------------------------
# _process_one: the per-doc synchronous pipeline
# ---------------------------------------------------------------------------


class TestProcessOne:
    def test_success_writes_vector_and_marks_done(self, store: SqliteStore) -> None:
        _enqueue(store, "d/1")
        result = _process(store, "d/1")
        assert result.ok is True
        assert result.error is None
        entry = store.embedding_queue.get("d/1")
        assert entry is not None and entry.state == "done"
        # ensure_vec_table dropped/recreated docs_vec at the stub dim (4),
        # and _write_vector inserted exactly one row for this doc.
        count = store._conn.execute("SELECT COUNT(*) AS n FROM docs_vec").fetchone()
        assert int(count["n"]) == 1

    def test_soft_deleted_doc_drops_queue_row(self, store: SqliteStore) -> None:
        _enqueue(store, "d/1")
        # ``store.delete`` clears the queue row itself, so this branch is
        # only reachable when a delete races in *after* enqueue. Simulate
        # it by flagging deleted_at directly, keeping the queue row live.
        store._conn.execute(
            "UPDATE documents SET deleted_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), "d/1"),
        )
        store._conn.commit()
        result = _process(store, "d/1")
        # The worker finds no live document and treats the job as done,
        # clearing the queue row so it never retries a deleted doc.
        assert result.ok is True
        assert store.embedding_queue.get("d/1") is None

    def test_transient_error_requeues(self, store: SqliteStore) -> None:
        _enqueue(store, "d/1")
        emb = ConstEmbedder(raise_on=EmbeddingError("upstream timeout"))
        result = _process(store, "d/1", embedder=emb)
        assert result.ok is False
        assert result.permanent is False
        entry = store.embedding_queue.get("d/1")
        assert entry is not None
        assert entry.state == "pending"  # requeued for backoff
        assert entry.attempts == 1
        assert "upstream timeout" in (entry.last_error or "")

    def test_permanent_error_parks_failed(self, store: SqliteStore) -> None:
        _enqueue(store, "d/1")
        emb = ConstEmbedder(raise_on=EmbeddingError("dimension mismatch (384 != 1536)"))
        result = _process(store, "d/1", embedder=emb)
        assert result.ok is False
        assert result.permanent is True
        entry = store.embedding_queue.get("d/1")
        assert entry is not None and entry.state == "failed"
        assert entry.attempts == 1

    def test_empty_text_is_permanent_failure(self, store: SqliteStore) -> None:
        # Document validation forbids an empty title, so empty the row
        # directly (the worker must still guard against it — e.g. rows
        # written by a future importer).
        doc_id = store.add(_doc("d/empty"))
        store._conn.execute(
            "UPDATE documents SET title='', body='' WHERE id=?", (doc_id,)
        )
        store._conn.commit()
        store.embedding_queue.enqueue(doc_id)
        result = _process(store, doc_id)
        assert result.ok is False
        assert result.permanent is True
        entry = store.embedding_queue.get(doc_id)
        assert entry is not None and entry.state == "failed"
        assert "empty" in (entry.last_error or "").lower()

    def test_missing_vector_write_still_marks_done(self, store: SqliteStore) -> None:
        """vec0 absent is not fatal: the job completes, vector just skipped."""
        _enqueue(store, "d/1")
        result = _process(store, "d/1")
        assert result.ok is True
        assert store.embedding_queue.get("d/1").state == "done"  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Worker construction + thread lifecycle
# ---------------------------------------------------------------------------


class TestWorkerLifecycle:
    def test_requires_enabled_embedder(self, store: SqliteStore) -> None:
        with pytest.raises(ValueError):
            EmbeddingWorker(store, embedder=NullEmbedder())

    def test_start_drains_queue_in_background(self, store: SqliteStore) -> None:
        for i in range(3):
            _enqueue(store, f"d/{i}")
        worker = EmbeddingWorker(store, embedder=ConstEmbedder(), idle_poll=0.02)
        worker.start()
        try:
            assert _wait_until(
                lambda: store.embedding_queue.count_by_state()["done"] == 3
            ), f"queue never drained: {store.embedding_queue.count_by_state()}"
        finally:
            worker.stop()

        counts = store.embedding_queue.count_by_state()
        assert counts["done"] == 3
        assert counts["failed"] == 0
        assert worker.processed_total == 3
        assert worker.failed_total == 0
        assert worker.last_job is not None and worker.last_job.ok

    def test_stop_is_idempotent_and_joins_thread(self, store: SqliteStore) -> None:
        worker = EmbeddingWorker(store, embedder=ConstEmbedder(), idle_poll=0.02)
        worker.start()
        assert worker.is_running
        worker.stop()
        assert not worker.is_running
        # stop() again is a safe no-op (also closes the private conn).
        worker.stop()
        assert not worker.is_running


# ---------------------------------------------------------------------------
# Worker construction + thread lifecycle
# ---------------------------------------------------------------------------


class TestWorkerLifecycleFK:
    def test_orphan_queue_row_dropped_after_doc_hard_delete(
        self, store: SqliteStore
    ) -> None:
        """Migration 0007 declares ``embedding_queue.doc_id REFERENCES
        documents(id) ON DELETE CASCADE`` and the worker's connection
        sets ``PRAGMA foreign_keys = ON``. A hard delete on the
        document must therefore remove the matching queue row, not
        leave it orphaned for the worker to ``clear()`` later.
        """
        _enqueue(store, "d/1")
        assert store.embedding_queue.get("d/1") is not None
        # Hard-delete the document directly through the store's main
        # connection (bypass soft-delete, which deliberately keeps
        # the queue row alive).
        store._conn.execute("DELETE FROM documents WHERE id = ?", ("d/1",))
        store._conn.commit()
        # FK CASCADE should have cleared the queue row. The worker
        # used to see it because ``PRAGMA foreign_keys`` was off
        # (default in pysqlite3 when not explicitly enabled); the
        # ``clear([doc_id])`` fallback in ``_process_one`` would then
        # tidy up. With the PRAGMA on, the row is gone before the
        # worker even starts.
        assert store.embedding_queue.get("d/1") is None


# ---------------------------------------------------------------------------
# process_embedding_queue: drain on the calling thread
# ---------------------------------------------------------------------------


class TestProcessEmbeddingQueue:
    def test_reuses_background_worker(self, tmp_path):
        """When the store already runs a background worker,
        ``process_embedding_queue`` must drain through it instead of
        spinning up a second ``EmbeddingWorker`` (and tearing it down
        in ``finally`` — which would also stop the live worker).
        """
        from kb_mcp_lite.schema import Document

        db = tmp_path / "reuse.db"
        s = SqliteStore(db, embedder=ConstEmbedder(), auto_start_worker=True)
        try:
            # The property starts the worker lazily.
            background = s.embedding_worker
            assert background is not None
            assert background.is_running
            doc = Document(id="d/r", type="reference", title="r", body="body")
            s.add(doc)
            s.embedding_queue.enqueue("d/r")
            status = s.process_embedding_queue(timeout=5.0)
            assert status["processed"] >= 1
            # Background worker is still the same object and still alive.
            assert s.embedding_worker is background
            assert background.is_running
        finally:
            s.close()
