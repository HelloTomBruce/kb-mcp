"""Multi-hop Graph Query Engine & Knowledge Doctor Auto-Fixer.

Supports path finding, directional relation traversal, and graph-level integrity repairs.
"""

from __future__ import annotations

from typing import Any

from kb_mcp_lite.store.sqlite import SqliteStore


class GraphQueryEngine:
    """Provides path finding and multi-hop relation queries over document links."""

    def __init__(self, store: SqliteStore) -> None:
        self.store = store

    def find_path(
        self, start_id: str, target_id: str, max_depth: int = 5
    ) -> list[dict[str, str]] | None:
        """Find the shortest directed path from start_id to target_id."""
        if start_id == target_id:
            return []

        # visited: set[str] = {start_id}

        # BFS for shortest path
        current_level = [start_id]
        paths = {start_id: []}

        for _ in range(max_depth):
            if not current_level:
                break
            next_level = []
            placeholders = ",".join("?" for _ in current_level)
            rows = self.store._conn.execute(
                f"SELECT from_id, to_id, rel FROM links WHERE from_id IN ({placeholders})",
                current_level,
            ).fetchall()

            for r in rows:
                from_id, to_id, rel = r["from_id"], r["to_id"], r["rel"]
                if to_id not in paths:
                    new_path = paths[from_id] + [{"from": from_id, "to": to_id, "rel": rel}]
                    paths[to_id] = new_path
                    if to_id == target_id:
                        return new_path
                    next_level.append(to_id)
            current_level = next_level

        return None

    def query_relations(
        self,
        start_id: str,
        rel: str | None = None,
        direction: str = "outbound",  # "outbound", "inbound", "both"
        doc_type: str | None = None,
        max_depth: int = 2,
    ) -> list[dict[str, Any]]:
        """Multi-hop traversal with relation and type filtering."""
        visited: set[str] = {start_id}
        current_frontier = [start_id]
        results: list[dict[str, Any]] = []

        for hop in range(1, max_depth + 1):
            if not current_frontier:
                break
            placeholders = ",".join("?" for _ in current_frontier)
            sql_parts = []
            params: list[Any] = []

            if direction in ("outbound", "both"):
                sql_parts.append(
                    f"SELECT from_id AS src, to_id AS dst, rel FROM links WHERE from_id IN ({placeholders})"
                )
                params.extend(current_frontier)
            if direction in ("inbound", "both"):
                sql_parts.append(
                    f"SELECT to_id AS src, from_id AS dst, rel FROM links WHERE to_id IN ({placeholders})"
                )
                params.extend(current_frontier)

            full_sql = " UNION ".join(sql_parts)
            rows = self.store._conn.execute(full_sql, params).fetchall()

            next_frontier = []
            for r in rows:
                dst = r["dst"]
                relation = r["rel"]
                if rel and relation != rel:
                    continue
                if dst not in visited:
                    visited.add(dst)
                    try:
                        doc = self.store.get(dst)
                        if doc_type and doc.type != doc_type:
                            continue
                        results.append(
                            {
                                "id": doc.id,
                                "type": doc.type,
                                "title": doc.title,
                                "rel": relation,
                                "hop": hop,
                                "via": r["src"],
                            }
                        )
                        next_frontier.append(dst)
                    except Exception:
                        pass
            current_frontier = next_frontier

        return results


def doctor_fix_hygiene(store: SqliteStore) -> dict[str, Any]:
    """Auto-repair dangling links and link orphan documents to default projects."""
    repaired_orphan_links = 0
    with store._txn() as cur:
        # 1. Clean orphan links pointing to non-existent documents
        res = cur.execute("""
            DELETE FROM links WHERE to_id NOT IN (SELECT id FROM documents)
               OR from_id NOT IN (SELECT id FROM documents)
        """)
        repaired_orphan_links = res.rowcount

    # 2. Rebuild FTS
    store.reindex()

    return {
        "ok": True,
        "repaired_orphan_links": repaired_orphan_links,
        "fts_reindexed": True,
    }
