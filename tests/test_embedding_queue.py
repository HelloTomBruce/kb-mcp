"""Tests for the async embedding queue (v0.8, 特性 #1 异步化嵌入).

Covers the ``embedding_queue`` table state machine
(:class:`~kb_mcp_lite.store.embedding_queue.EmbeddingQueue`) and the
store-level admin helpers that the CLI / MCP surface calls
(``SqliteStore.embedding_status`` / ``SqliteStore.retry_embedding``).

The queue is exercised against a real SQLite store (migration 0007
creates the table). The store's embedder is pinned to a ``NullEmbedder``
so ``add()`` does *not* auto-enqueue — every test drives the queue by
hand, which keeps the assertions deterministic regardless of the host's
embedder config.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kb_mcp_lite.embedder import NullEmbedder
from kb_mcp_lite.schema import Document
from kb_mcp_lite.store.sqlite import SqliteStore


def _iso(seconds_ago: float) -> str:
    """ISO-8601 timestamp ``seconds_ago`` in the past (UTC, +00:00)."""
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


def _doc(doc_id: str, body: str = "body") -> Document:
    return Document(id=doc_id, type="reference", title=f"title {doc_id}", body=body)


@pytest.fixture()
def store(tmp_path: Path):
    """SqliteStore with a disabled embedder; queue driven by hand."""
    db = tmp_path / "queue.db"
    s = SqliteStore(db, embedder=NullEmbedder(), auto_start_worker=False)
    yield s
    s.close()


def _seed(store: SqliteStore, doc_id: str) -> None:
    """Insert the document (FK target) so queue rows can reference it."""
    store.add(_doc(doc_id))


# ---------------------------------------------------------------------------
# State machine: pending -> in_progress -> done / failed
# ---------------------------------------------------------------------------


class TestStateMachine:
    def test_enqueue_creates_pending_row(self, store: SqliteStore) -> None:
        _seed(store, "d/1")
        store.embedding_queue.enqueue("d/1")
        entry = store.embedding_queue.get("d/1")
        assert entry is not None
        assert entry.state == "pending"
        assert entry.attempts == 0
        assert entry.last_error is None
        assert entry.last_attempt_at is None

    def test_claim_next_flips_to_in_progress(self, store: SqliteStore) -> None:
        _seed(store, "d/1")
        store.embedding_queue.enqueue("d/1")
        claimed = store.embedding_queue.claim_next()
        assert claimed is not None
        assert claimed.doc_id == "d/1"
        assert claimed.state == "in_progress"
        # Not claimable again while in_progress.
        assert store.embedding_queue.claim_next() is None

    def test_claim_next_is_fifo(self, store: SqliteStore) -> None:
        for i in range(3):
            _seed(store, f"d/{i}")
            store.embedding_queue.enqueue(f"d/{i}")
        q = store.embedding_queue
        assert q.claim_next().doc_id == "d/0"  # type: ignore[union-attr]
        assert q.claim_next().doc_id == "d/1"  # type: ignore[union-attr]
        assert q.claim_next().doc_id == "d/2"  # type: ignore[union-attr]

    def test_mark_done_is_terminal(self, store: SqliteStore) -> None:
        _seed(store, "d/1")
        q = store.embedding_queue
        q.enqueue("d/1")
        q.claim_next()
        q.mark_done("d/1")
        entry = q.get("d/1")
        assert entry is not None and entry.state == "done"
        assert entry.is_terminal
        assert q.claim_next() is None

    def test_transient_failure_requeues_with_attempt(self, store: SqliteStore) -> None:
        _seed(store, "d/1")
        q = store.embedding_queue
        q.enqueue("d/1")
        q.claim_next()
        q.mark_failed("d/1", "upstream timeout")
        entry = q.get("d/1")
        assert entry is not None
        assert entry.state == "pending"  # requeued, not terminal
        assert entry.attempts == 1
        assert entry.last_error == "upstream timeout"
        # Immediately back in backoff -> not claimable.
        assert q.claim_next() is None

    def test_row_becomes_claimable_after_backoff(self, store: SqliteStore) -> None:
        _seed(store, "d/1")
        q = store.embedding_queue
        q.enqueue("d/1")
        q.claim_next()
        q.mark_failed("d/1", "boom", now=_iso(120))  # 2 min ago
        # Backoff (1s) has long elapsed -> claimable again.
        claimed = q.claim_next()
        assert claimed is not None and claimed.doc_id == "d/1"

    def test_permanent_failure_parks_failed(self, store: SqliteStore) -> None:
        _seed(store, "d/1")
        q = store.embedding_queue
        q.enqueue("d/1")
        q.claim_next()
        q.mark_failed("d/1", "dimension mismatch", permanent=True)
        entry = q.get("d/1")
        assert entry is not None and entry.state == "failed"
        assert entry.is_terminal
        assert q.claim_next() is None

    def test_max_attempts_parks_failed(self, store: SqliteStore) -> None:
        _seed(store, "d/1")
        q = store.embedding_queue
        q.enqueue("d/1")
        q.claim_next()  # attempts still 0 — claim does not increment.
        # Drive max_attempts (5) transient failures back-to-back.
        # mark_failed does not require an in_progress row, so the
        # attempts counter climbs to 5 and the row parks in ``failed``.
        for _ in range(5):
            q.mark_failed("d/1", "flaky")
        entry = q.get("d/1")
        assert entry is not None and entry.state == "failed"
        assert entry.attempts == 5
        assert q.claim_next() is None

    def test_re_enqueue_resets_failure_history(self, store: SqliteStore) -> None:
        _seed(store, "d/1")
        q = store.embedding_queue
        q.enqueue("d/1")
        q.claim_next()
        q.mark_failed("d/1", "boom", permanent=True)
        assert q.get("d/1").state == "failed"  # type: ignore[union-attr]
        # Re-adding the doc should reset it to a fresh pending row.
        q.enqueue("d/1")
        entry = q.get("d/1")
        assert entry is not None
        assert entry.state == "pending"
        assert entry.attempts == 0
        assert entry.last_error is None


# ---------------------------------------------------------------------------
# Backoff starvation: fresh docs must not block behind deep-backoff rows
# ---------------------------------------------------------------------------


class TestBackoffStarvation:
    """Regression: one row that is deep in its backoff window must not
    starve every row enqueued behind it.

    Pre-fix behaviour: ``claim_next`` returned ``None`` whenever the
    head-of-queue row was in its backoff window (SQL only knew about
    the 1s floor, the Python check rejected the candidate, and there
    was no fallback). A background worker would spin in 250 ms sleeps;
    every fresh doc behind the head would never be touched.
    """

    def test_starved_row_does_not_block_fresh_ones(self, store):
        # A: enqueued first, then failed 2x so its backoff is 5s.
        _seed(store, "doc/a")
        store.embedding_queue.enqueue("doc/a", now=_iso(10))
        store.embedding_queue.claim_next()  # -> in_progress
        store.embedding_queue.mark_failed("doc/a", "transient 1", permanent=False)
        store.embedding_queue.claim_next()  # -> in_progress
        store.embedding_queue.mark_failed("doc/a", "transient 2", permanent=False)
        # B: enqueued after, last_attempt_at=NULL (freshly pending).
        _seed(store, "doc/b")
        store.embedding_queue.enqueue("doc/b", now=_iso(0))

        claimed = store.embedding_queue.claim_next()

        assert claimed is not None, "fresh doc/b must win over starved doc/a"
        assert claimed.doc_id == "doc/b"
        a = store.embedding_queue.get("doc/a")
        assert a is not None
        assert a.state == "pending"
        assert a.attempts == 2


# ---------------------------------------------------------------------------
# Admin: retry / clear / status
# ---------------------------------------------------------------------------


class TestRetryAndClear:
    def test_retry_flips_failed_to_pending(self, store: SqliteStore) -> None:
        _seed(store, "d/1")
        q = store.embedding_queue
        q.enqueue("d/1")
        q.claim_next()
        q.mark_failed("d/1", "boom", permanent=True)
        assert q.retry(["d/1"]) == 1
        entry = q.get("d/1")
        assert entry is not None
        assert entry.state == "pending"
        assert entry.attempts == 0
        assert entry.last_error is None
        assert entry.last_attempt_at is None

    def test_retry_leaves_pending_untouched(self, store: SqliteStore) -> None:
        _seed(store, "d/1")
        q = store.embedding_queue
        q.enqueue("d/1")
        assert q.retry(["d/1"]) == 0
        assert q.get("d/1").state == "pending"  # type: ignore[union-attr]

    def test_clear_removes_rows(self, store: SqliteStore) -> None:
        for i in range(2):
            _seed(store, f"d/{i}")
        q = store.embedding_queue
        q.enqueue("d/0")
        q.enqueue("d/1")
        assert q.clear(["d/0", "d/1"]) == 2
        assert q.count_by_state()["pending"] == 0

    def test_status_counts_and_oldest(self, store: SqliteStore) -> None:
        _seed(store, "d/1")
        _seed(store, "d/2")
        q = store.embedding_queue
        # d/1 -> failed, d/2 -> pending, and one done.
        q.enqueue("d/1")
        q.claim_next()
        q.mark_failed("d/1", "boom", permanent=True)
        q.enqueue("d/2")
        status = q.status()
        assert status["counts"] == {
            "pending": 1,
            "in_progress": 0,
            "done": 0,
            "failed": 1,
        }
        assert status["oldest_pending"]["doc_id"] == "d/2"  # type: ignore[index]
        assert status["oldest_failed"]["doc_id"] == "d/1"  # type: ignore[index]
        assert "attempts" in status["oldest_failed"]  # type: ignore[index]


# ---------------------------------------------------------------------------
# Store-level admin helpers used by the CLI / MCP surface
# ---------------------------------------------------------------------------


class TestStoreAdmin:
    def test_embedding_status_disabled_embedder(self, store: SqliteStore) -> None:
        payload = store.embedding_status()
        assert payload["embedder_enabled"] is False
        assert payload["dim"] == 0
        assert payload["indexed_documents"] == 0
        assert payload["queue"] == {
            "pending": 0,
            "in_progress": 0,
            "done": 0,
            "failed": 0,
        }
        assert payload["total_enqueued"] == 0
        assert payload["oldest_pending"] is None
        assert payload["oldest_failed"] is None

    def test_embedding_status_reflects_queue(self, store: SqliteStore) -> None:
        _seed(store, "d/1")
        q = store.embedding_queue
        q.enqueue("d/1")
        q.claim_next()
        q.mark_failed("d/1", "boom", permanent=True)
        payload = store.embedding_status()
        assert payload["queue"]["failed"] == 1
        assert payload["total_enqueued"] == 1
        assert payload["oldest_failed"]["doc_id"] == "d/1"  # type: ignore[index]

    def test_retry_embedding_all_failed(self, store: SqliteStore) -> None:
        for i in range(2):
            _seed(store, f"d/{i}")
            q = store.embedding_queue
            q.enqueue(f"d/{i}")
            q.claim_next()
            q.mark_failed(f"d/{i}", "boom", permanent=True)
        assert store.retry_embedding() == 2
        counts = store.embedding_queue.count_by_state()
        assert counts["failed"] == 0
        assert counts["pending"] == 2

    def test_retry_embedding_single_doc(self, store: SqliteStore) -> None:
        for i in range(2):
            _seed(store, f"d/{i}")
            q = store.embedding_queue
            q.enqueue(f"d/{i}")
            q.claim_next()
            q.mark_failed(f"d/{i}", "boom", permanent=True)
        assert store.retry_embedding(doc_id="d/0") == 1
        counts = store.embedding_queue.count_by_state()
        assert counts["failed"] == 1
        assert counts["pending"] == 1

    def test_retry_embedding_absent_doc_is_noop(self, store: SqliteStore) -> None:
        assert store.retry_embedding(doc_id="never/queued") == 0
