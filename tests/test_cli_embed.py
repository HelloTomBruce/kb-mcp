"""CLI admin surface for the async embedding queue (v0.8, 特性 #1.d).

Exercises the ``kb embed`` group and its subcommands against a store
whose embedder is disabled (``NullEmbedder``). Disabling the embedder
keeps ``kb add`` from auto-enqueueing on hosts that ship a real embedder
config, so the tests seed the ``embedding_queue`` by hand and stay
deterministic everywhere.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from kb_mcp_lite.cli import cli
from kb_mcp_lite.embedder import NullEmbedder
from kb_mcp_lite.schema import Document
from kb_mcp_lite.store.sqlite import SqliteStore

EXIT_OK = 0
EXIT_USAGE = 64


def _invoke(
    runner: CliRunner,
    store: SqliteStore,
    args: list[str],
) -> pytest.Result:
    return runner.invoke(cli, args, obj={"store": store})


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def store(tmp_path: Path) -> SqliteStore:
    db = tmp_path / "embed.db"
    s = SqliteStore(db, embedder=NullEmbedder(), auto_start_worker=False)
    yield s
    s.close()


def _seed_doc(store: SqliteStore, doc_id: str) -> str:
    """Insert a document (FK target) and return its id."""
    doc = Document(id=doc_id, type="reference", title=f"title {doc_id}", body="body")
    return store.add(doc)


def _queue_failed(store: SqliteStore, doc_id: str) -> None:
    """Enqueue + permanently fail ``doc_id`` (a job a human would retry)."""
    _seed_doc(store, doc_id)
    q = store.embedding_queue
    q.enqueue(doc_id)
    q.mark_failed(doc_id, "boom", permanent=True)


# ---------------------------------------------------------------------------
# kb embed (bare) / kb embed status
# ---------------------------------------------------------------------------


class TestEmbedStatus:
    def test_bare_summary_when_disabled(self, runner: CliRunner, store: SqliteStore) -> None:
        _seed_doc(store, "d/1")
        result = _invoke(runner, store, ["embed"])
        assert result.exit_code == EXIT_OK
        assert "embedder=disabled dim=0 indexed=0" in result.output

    def test_bare_json(self, runner: CliRunner, store: SqliteStore) -> None:
        result = _invoke(runner, store, ["embed", "--json"])
        assert result.exit_code == EXIT_OK
        payload = json.loads(result.output)
        assert payload["embedder_enabled"] is False
        assert payload["queue"] == {
            "pending": 0,
            "in_progress": 0,
            "done": 0,
            "failed": 0,
        }

    def test_status_breaks_down_queue(self, runner: CliRunner, store: SqliteStore) -> None:
        # Seed one row per non-empty state (directly, embedder disabled).
        _seed_doc(store, "d/pending")
        _seed_doc(store, "d/done")
        _seed_doc(store, "d/failed")
        q = store.embedding_queue
        q.enqueue("d/pending")
        q.enqueue("d/done")
        q.mark_done("d/done")
        q.enqueue("d/failed")
        q.mark_failed("d/failed", "boom", permanent=True)

        result = _invoke(runner, store, ["embed", "status"])
        assert result.exit_code == EXIT_OK
        assert "queue: pending=1 in_progress=0 done=1 failed=1" in result.output
        # Oldest failed row is surfaced with its error + attempt count.
        assert "oldest_failed: d/failed attempts=1 error=boom" in result.output

    def test_status_json(self, runner: CliRunner, store: SqliteStore) -> None:
        _seed_doc(store, "d/pending")
        store.embedding_queue.enqueue("d/pending")
        result = _invoke(runner, store, ["embed", "status", "--json"])
        assert result.exit_code == EXIT_OK
        payload = json.loads(result.output)
        assert payload["queue"]["pending"] == 1
        assert payload["oldest_pending"]["doc_id"] == "d/pending"  # type: ignore[index]
        assert payload["oldest_failed"] is None


# ---------------------------------------------------------------------------
# kb embed retry
# ---------------------------------------------------------------------------


class TestEmbedRetry:
    def test_retry_all_failed(self, runner: CliRunner, store: SqliteStore) -> None:
        _queue_failed(store, "d/a")
        _queue_failed(store, "d/b")
        result = _invoke(runner, store, ["embed", "retry", "--all"])
        assert result.exit_code == EXIT_OK
        assert "retried 2 job(s) (all failed)" in result.output
        counts = store.embedding_queue.count_by_state()
        assert counts["failed"] == 0
        assert counts["pending"] == 2

    def test_retry_single_doc(self, runner: CliRunner, store: SqliteStore) -> None:
        _queue_failed(store, "d/a")
        _queue_failed(store, "d/b")
        result = _invoke(runner, store, ["embed", "retry", "d/a"])
        assert result.exit_code == EXIT_OK
        assert "retried 1 job(s) for d/a" in result.output
        counts = store.embedding_queue.count_by_state()
        assert counts["failed"] == 1
        assert counts["pending"] == 1

    def test_retry_absent_doc_is_noop(self, runner: CliRunner, store: SqliteStore) -> None:
        # Doc exists but was never queued -> nothing to move.
        _seed_doc(store, "d/plain")
        result = _invoke(runner, store, ["embed", "retry", "d/plain"])
        assert result.exit_code == EXIT_OK
        assert "retried 0 job(s) for d/plain" in result.output

    def test_retry_requires_arg_or_all(self, runner: CliRunner, store: SqliteStore) -> None:
        result = _invoke(runner, store, ["embed", "retry"])
        assert result.exit_code == EXIT_USAGE
        assert "usage: kb embed retry" in result.output

    def test_retry_all_json(self, runner: CliRunner, store: SqliteStore) -> None:
        _queue_failed(store, "d/a")
        result = _invoke(runner, store, ["embed", "retry", "--all", "--json"])
        assert result.exit_code == EXIT_OK
        payload = json.loads(result.output)
        assert payload == {"ok": True, "retried": 1, "doc_id": None}

    def test_retry_single_json(self, runner: CliRunner, store: SqliteStore) -> None:
        _queue_failed(store, "d/a")
        result = _invoke(runner, store, ["embed", "retry", "d/a", "--json"])
        assert result.exit_code == EXIT_OK
        payload = json.loads(result.output)
        assert payload == {"ok": True, "retried": 1, "doc_id": "d/a"}
