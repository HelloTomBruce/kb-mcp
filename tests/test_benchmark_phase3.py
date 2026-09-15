"""Benchmark for Phase 3 features with 1000 documents.

Run with: pytest tests/test_benchmark_phase3.py -v -s
"""

import time

from kb_mcp_lite.link_parser import extract_body_references
from kb_mcp_lite.relations import ImpactAnalyzer, supersession_chain
from kb_mcp_lite.schema import Document
from kb_mcp_lite.store.sqlite import SqliteStore


def _make_docs(n: int) -> list[Document]:
    """Generate n test documents with cross-references."""
    docs = []
    for i in range(n):
        # Every 10th doc references the previous one via markdown link
        body = f"Document {i} body."
        if i > 0 and i % 10 == 0:
            body += f" See [doc](test/doc{i - 1})."
        if i > 2 and i % 15 == 0:
            body += f" Also `test/doc{i - 2}`."
        docs.append(Document(
            id=f"test/doc{i}",
            type="lesson" if i % 3 == 0 else "decision",
            title=f"Test Document {i}",
            body=body,
            tags=[f"tag{i % 5}"],
        ))
    return docs


def _make_links(store: SqliteStore, n: int) -> None:
    """Create a chain of influence edges for impact analysis testing."""
    for i in range(1, n):
        if i % 5 == 0:
            store.link(f"test/doc{i}", f"test/doc{i - 1}", rel="governs")
        elif i % 7 == 0:
            store.link(f"test/doc{i}", f"test/doc{i - 1}", rel="depends-on")
        elif i % 11 == 0:
            store.link(f"test/doc{i}", f"test/doc{i - 1}", rel="superseded-by")


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------


class TestBenchmarkPhase3:
    """Performance benchmarks for Phase 3 features."""

    def test_bulk_add_1000_docs(self, tmp_path):
        """Add 1000 documents and measure time."""
        store = SqliteStore(tmp_path / "bench.db")
        docs = _make_docs(1000)

        t0 = time.perf_counter()
        for doc in docs:
            store.add(doc)
        elapsed = time.perf_counter() - t0

        print(f"\n  bulk add 1000 docs: {elapsed:.3f}s ({1000 / elapsed:.0f} docs/s)")
        assert elapsed < 30, f"too slow: {elapsed:.1f}s"
        store.close()

    def test_extract_body_references_1000_docs(self, tmp_path):
        """Parse body references for 1000 documents."""
        store = SqliteStore(tmp_path / "bench_ref.db")
        docs = _make_docs(1000)
        for doc in docs:
            store.add(doc)

        # Build known_ids set
        rows = store._conn.execute("SELECT id FROM documents WHERE deleted_at IS NULL").fetchall()
        known_ids = {r["id"] for r in rows}

        t0 = time.perf_counter()
        total_refs = 0
        for doc in docs:
            refs = extract_body_references(doc.body, known_ids)
            total_refs += len(refs)
        elapsed = time.perf_counter() - t0

        print(f"\n  extract refs 1000 docs: {elapsed:.3f}s, {total_refs} refs found")
        assert elapsed < 5, f"too slow: {elapsed:.1f}s"
        store.close()

    def test_sync_body_references_1000_docs(self, tmp_path):
        """Auto-link sync for 1000 documents."""
        store = SqliteStore(tmp_path / "bench_sync.db")
        docs = _make_docs(1000)
        for doc in docs:
            store.add(doc)

        t0 = time.perf_counter()
        for doc in docs:
            store._sync_body_references(doc.id, doc.body)
        elapsed = time.perf_counter() - t0

        # Count total links created
        link_count = store._conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]
        print(f"\n  sync body refs 1000 docs: {elapsed:.3f}s, {link_count} links created")
        assert elapsed < 30, f"too slow: {elapsed:.1f}s"
        store.close()

    def test_impact_analyzer_1000_docs(self, tmp_path):
        """Impact analysis on a 1000-doc graph."""
        store = SqliteStore(tmp_path / "bench_impact.db")
        docs = _make_docs(1000)
        for doc in docs:
            store.add(doc)
        _make_links(store, 1000)

        analyzer = ImpactAnalyzer(store)
        t0 = time.perf_counter()
        result = analyzer.analyze("test/doc999", max_depth=3)
        elapsed = time.perf_counter() - t0

        print(f"\n  impact analyze (1000 docs): {elapsed:.3f}s, {len(result)} nodes reached")
        assert elapsed < 5, f"too slow: {elapsed:.1f}s"
        store.close()

    def test_supersession_chain_1000_docs(self, tmp_path):
        """Supersession chain trace on a chain of 200 decisions."""
        store = SqliteStore(tmp_path / "bench_chain.db")
        # Create 200 decisions linked by superseded-by
        for i in range(200):
            store.add(Document(
                id=f"dec/v{i}",
                type="decision",
                title=f"Decision v{i}",
                body=f"Decision version {i}",
            ))
        for i in range(1, 200):
            store.link(f"dec/v{i - 1}", f"dec/v{i}", rel="superseded-by")

        t0 = time.perf_counter()
        chain = supersession_chain(store, "dec/v0")
        elapsed = time.perf_counter() - t0

        print(f"\n  supersession chain (200 links): {elapsed:.3f}s, chain length={len(chain)}")
        assert len(chain) == 200
        assert elapsed < 2, f"too slow: {elapsed:.1f}s"
        store.close()

    def test_graph_expand_1000_docs(self, tmp_path):
        """Graph expansion on a dense 1000-doc graph."""
        store = SqliteStore(tmp_path / "bench_expand.db")
        docs = _make_docs(1000)
        for doc in docs:
            store.add(doc)
        _make_links(store, 1000)

        t0 = time.perf_counter()
        for i in range(0, 1000, 100):
            store.outgoing_links(f"test/doc{i}")
            store.incoming_links(f"test/doc{i}")
        elapsed = time.perf_counter() - t0

        print(f"\n  graph expand (10 queries on 1000 docs): {elapsed:.3f}s")
        assert elapsed < 5, f"too slow: {elapsed:.1f}s"
        store.close()
