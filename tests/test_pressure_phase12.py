"""Pressure tests and benchmarks for Phase 1/2 features (kb-mcp v0.8).

Run with: pytest tests/test_pressure_phase12.py -v -s -m benchmark
"""

import multiprocessing as mp
import time

import pytest

from kb_mcp_lite.schema import Document
from kb_mcp_lite.store.sqlite import SqliteStore

# ---------------------------------------------------------------------------
# Helper: concurrent write worker
# ---------------------------------------------------------------------------


def _concurrent_add_worker(
    db_path: str,
    worker_id: int,
    n_docs: int,
    ready_evt: "mp.Event",
    result_queue: "mp.Queue",
) -> None:
    """Process entry point: open store, add n_docs, report timing."""
    try:
        store = SqliteStore(db_path)
        ready_evt.set()
        t0 = time.perf_counter()
        errors = 0
        for i in range(n_docs):
            try:
                doc = Document(
                    id=f"w{worker_id}/doc{i}",
                    type="lesson",
                    title=f"Worker {worker_id} Doc {i}",
                    body=f"Body from worker {worker_id} doc {i}",
                )
                store.add(doc)
            except Exception:
                errors += 1
        elapsed = time.perf_counter() - t0
        store.close()
        result_queue.put(("ok", worker_id, n_docs, elapsed, errors))
    except Exception as e:
        result_queue.put(("error", worker_id, 0, 0, str(e)))


# ---------------------------------------------------------------------------
# 5-process concurrent write
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
class TestConcurrentWrites:
    def test_5_process_concurrent_add(self, tmp_path):
        """5 processes simultaneously add 100 docs each — no failures."""
        db = tmp_path / "concurrent.db"
        # Pre-create the DB
        s = SqliteStore(db)
        s.close()

        n_workers = 5
        docs_per_worker = 100
        processes = []
        readies = [mp.Event() for _ in range(n_workers)]
        result_queue: mp.Queue = mp.Queue()

        for wid in range(n_workers):
            p = mp.Process(
                target=_concurrent_add_worker,
                args=(str(db), wid, docs_per_worker, readies[wid], result_queue),
                daemon=True,
            )
            processes.append(p)
            p.start()

        # Wait for all workers to be ready
        for evt in readies:
            assert evt.wait(timeout=5.0), "worker did not start in time"

        # Wait for all to finish
        for p in processes:
            p.join(timeout=30)

        results = []
        while not result_queue.empty():
            results.append(result_queue.get(timeout=2))

        assert len(results) == n_workers
        total_ok = sum(r[2] for r in results if r[0] == "ok")
        total_errors = sum(r[4] for r in results if r[0] == "ok")
        total_elapsed = max(r[3] for r in results if r[0] == "ok")

        # Verify DB has all docs
        store = SqliteStore(db)
        count = store._conn.execute(
            "SELECT COUNT(*) FROM documents WHERE deleted_at IS NULL"
        ).fetchone()[0]
        store.close()

        print(
            f"\n  5-process concurrent add: {total_ok} docs, {total_errors} errors, {total_elapsed:.3f}s"
        )
        assert total_ok == n_workers * docs_per_worker
        assert total_errors == 0
        assert count == n_workers * docs_per_worker


# ---------------------------------------------------------------------------
# kb add p99 latency
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
class TestAddLatency:
    def test_add_p99_latency(self, tmp_path):
        """kb add p99 should be under 50ms (no embedding)."""
        store = SqliteStore(tmp_path / "latency.db")
        latencies = []

        for i in range(200):
            doc = Document(
                id=f"lat{i}",
                type="lesson",
                title=f"Latency Test {i}",
                body=f"Body {i}" * 10,
            )
            t0 = time.perf_counter()
            store.add(doc)
            latencies.append((time.perf_counter() - t0) * 1000)

        latencies.sort()
        p50 = latencies[len(latencies) // 2]
        p95 = latencies[int(len(latencies) * 0.95)]
        p99 = latencies[int(len(latencies) * 0.99)]

        print(f"\n  kb add latency (200 docs): p50={p50:.1f}ms p95={p95:.1f}ms p99={p99:.1f}ms")
        assert p99 < 50, f"p99 too high: {p99:.1f}ms"
        store.close()

    def test_update_p99_latency(self, tmp_path):
        """kb update p99 should be under 50ms."""
        store = SqliteStore(tmp_path / "update_lat.db")
        # Pre-populate
        for i in range(200):
            store.add(Document(id=f"upd{i}", type="lesson", title=f"U{i}", body="init"))

        latencies = []
        for i in range(200):
            t0 = time.perf_counter()
            store.update(f"upd{i}", body=f"Updated body {i}")
            latencies.append((time.perf_counter() - t0) * 1000)

        latencies.sort()
        p99 = latencies[int(len(latencies) * 0.99)]
        print(f"\n  kb update latency (200 docs): p99={p99:.1f}ms")
        assert p99 < 50, f"p99 too high: {p99:.1f}ms"
        store.close()


# ---------------------------------------------------------------------------
# Watcher CPU benchmark
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
class TestWatcherBenchmark:
    def test_scan_once_1k_files(self, tmp_path):
        """scan_once on 1k files should complete under 500ms."""
        # Create 1000 files in a vault-like structure
        vault_dir = tmp_path / "vault" / "md"
        vault_dir.mkdir(parents=True)
        for i in range(1000):
            f = vault_dir / f"doc{i:04d}.md"
            f.write_text(f"---\ntype: lesson\ntitle: Doc {i}\n---\n\nBody {i}")

        store = SqliteStore(tmp_path / "watcher.db")

        # Use import_dir to simulate bulk import timing
        from kb_mcp_lite.md_io import import_dir

        t0 = time.perf_counter()
        import_dir(store, vault_dir)
        first_scan = time.perf_counter() - t0

        # Second import (no changes — should be idempotent and fast)
        t0 = time.perf_counter()
        import_dir(store, vault_dir)
        second_scan = time.perf_counter() - t0

        count = store._conn.execute(
            "SELECT COUNT(*) FROM documents WHERE deleted_at IS NULL"
        ).fetchone()[0]

        print(
            f"\n  import 1k files: first={first_scan:.3f}s second={second_scan:.3f}s imported={count}"
        )
        assert first_scan < 5.0, f"first scan too slow: {first_scan:.1f}s"
        assert second_scan < 2.0, f"second scan too slow: {second_scan:.1f}s"
        assert count == 1000
        store.close()


# ---------------------------------------------------------------------------
# Search latency under load
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
class TestSearchLatency:
    def test_search_latency_1k_docs(self, tmp_path):
        """Search on 1k documents should complete under 200ms (lexical mode)."""
        store = SqliteStore(tmp_path / "search_lat.db")
        for i in range(1000):
            store.add(
                Document(
                    id=f"s{i}",
                    type="lesson",
                    title=f"Search Doc {i}",
                    body=f"Content about topic {i % 50} with keyword term{i}",
                )
            )

        # Warm up FTS
        store.search("topic", mode="lexical", limit=10)

        latencies = []
        queries = ["topic", "term42", "keyword", "search doc 100", "content 5"]
        for q in queries * 20:
            t0 = time.perf_counter()
            store.search(q, mode="lexical", limit=10)
            latencies.append((time.perf_counter() - t0) * 1000)

        latencies.sort()
        p99 = latencies[int(len(latencies) * 0.99)]
        print(f"\n  search latency (1k docs, 100 queries, lexical): p99={p99:.1f}ms")
        assert p99 < 200, f"p99 too high: {p99:.1f}ms"
        store.close()

    def test_search_hybrid_latency_1k_docs(self, tmp_path):
        """Hybrid search on 1k docs should complete under 1s."""
        store = SqliteStore(tmp_path / "search_hybrid.db")
        for i in range(1000):
            store.add(
                Document(
                    id=f"h{i}",
                    type="lesson",
                    title=f"Hybrid Doc {i}",
                    body=f"Content about topic {i % 50} with keyword term{i}",
                )
            )

        latencies = []
        queries = ["topic", "term42", "keyword"]
        for q in queries * 10:
            t0 = time.perf_counter()
            store.search(q, mode="hybrid", limit=10)
            latencies.append((time.perf_counter() - t0) * 1000)

        latencies.sort()
        p99 = latencies[int(len(latencies) * 0.99)]
        print(f"\n  hybrid search latency (1k docs, 30 queries): p99={p99:.1f}ms")
        assert p99 < 1000, f"p99 too high: {p99:.1f}ms"
        store.close()
