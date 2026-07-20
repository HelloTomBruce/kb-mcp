"""Maintenance mixin for SqliteStore — doctor, prune, stats, subgraph."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

from kb_mcp_lite.schema import DoctorCheck, DoctorReport


class MaintenanceMixin:
    """Mixin providing maintenance and diagnostic methods.

    Requires the host class to expose ``self._conn``, ``self._txn()``,
    and ``self._remove_embedding()``.
    """

    def doctor(self) -> DoctorReport:
        checks: List[DoctorCheck] = []

        # 1. PRAGMA integrity_check
        row = self._conn.execute("PRAGMA integrity_check").fetchone()
        ok = bool(row) and row[0] == "ok"
        checks.append(
            DoctorCheck(
                name="integrity_check",
                ok=ok,
                detail=str(row[0]) if row else "no result",
            )
        )

        # 2. FTS row count == active document count.
        n_docs = self._conn.execute(
            "SELECT COUNT(*) FROM documents WHERE deleted_at IS NULL"
        ).fetchone()[0]
        n_fts = self._conn.execute(
            "SELECT COUNT(*) FROM docs_fts d "
            "JOIN documents m ON m.rowid = d.rowid "
            "WHERE m.deleted_at IS NULL"
        ).fetchone()[0]
        checks.append(
            DoctorCheck(
                name="fts_sync",
                ok=n_docs == n_fts,
                detail=f"active_docs={n_docs} active_fts_rows={n_fts}",
            )
        )

        # 3. No orphan links
        n_orphans = self._conn.execute(
            """
            SELECT COUNT(*) FROM links l
            LEFT JOIN documents d ON d.id = l.to_id
            WHERE d.id IS NULL
            """
        ).fetchone()[0]
        checks.append(
            DoctorCheck(
                name="no_orphan_links",
                ok=n_orphans == 0,
                detail=f"{n_orphans} orphans",
            )
        )

        # 4. All docs have non-empty type and title
        n_invalid = self._conn.execute(
            "SELECT COUNT(*) FROM documents WHERE type = '' OR title = ''"
        ).fetchone()[0]
        checks.append(
            DoctorCheck(
                name="valid_type_title",
                ok=n_invalid == 0,
                detail=f"{n_invalid} invalid",
            )
        )

        # 5-7: Project-specific checks (only when projects exist and doc count > 1)
        n_projects = self._conn.execute("""
            SELECT COUNT(*) FROM documents WHERE type = 'project' AND deleted_at IS NULL
        """).fetchone()[0]
        n_total = self._conn.execute("""
            SELECT COUNT(*) FROM documents WHERE deleted_at IS NULL
        """).fetchone()[0]

        if n_total > 1 and n_projects > 0:
            # 5. No duplicate project documents (same title)
            duplicate_projects = self._conn.execute("""
                SELECT title, COUNT(*) as cnt FROM documents
                WHERE type = 'project' AND deleted_at IS NULL
                GROUP BY title HAVING cnt > 1
            """).fetchall()
            n_duplicate = len(duplicate_projects)
            detail = (
                f"{n_duplicate} duplicate projects: {', '.join(r['title'] for r in duplicate_projects)}"
                if n_duplicate
                else "no duplicates"
            )
            checks.append(
                DoctorCheck(
                    name="no_duplicate_projects",
                    ok=n_duplicate == 0,
                    detail=detail,
                )
            )

            # 6. Project documents have sufficient metadata (informational)
            empty_projects = self._conn.execute("""
                SELECT COUNT(*) FROM documents
                WHERE type = 'project' AND deleted_at IS NULL AND body = ''
            """).fetchone()[0]
            detail = (
                f"{empty_projects} project(s) with empty body"
                if empty_projects
                else "all projects have body content"
            )
            checks.append(
                DoctorCheck(
                    name="project_metadata_complete",
                    ok=True,
                    detail=detail,
                )
            )

            # 7. No orphan documents (not linked to any project)
            n_orphan_docs = self._conn.execute("""
                SELECT COUNT(DISTINCT d.id) FROM documents d
                WHERE d.deleted_at IS NULL
                  AND d.type != 'project'
                  AND NOT EXISTS (
                    SELECT 1 FROM links l
                    WHERE l.from_id = d.id AND l.to_id LIKE 'proj/%'
                       OR l.to_id = d.id AND l.from_id LIKE 'proj/%'
                  )
            """).fetchone()[0]
            detail = (
                f"{n_orphan_docs} documents not linked to any project"
                if n_orphan_docs
                else "all documents are linked to a project"
            )
            checks.append(
                DoctorCheck(
                    name="no_orphan_documents",
                    ok=n_orphan_docs == 0,
                    detail=detail,
                )
            )

        return DoctorReport(ok=all(c.ok for c in checks), checks=checks)

    def prune(self, older_than: timedelta = timedelta(days=30)) -> int:
        cutoff = (datetime.now(timezone.utc) - older_than).isoformat()
        to_delete = [
            r["id"]
            for r in self._conn.execute(
                "SELECT id FROM documents WHERE deleted_at IS NOT NULL AND deleted_at < ?",
                (cutoff,),
            ).fetchall()
        ]
        for doc_id in to_delete:
            self._remove_embedding(doc_id)
        cur = self._conn.execute(
            "DELETE FROM documents WHERE deleted_at IS NOT NULL AND deleted_at < ?",
            (cutoff,),
        )
        return cur.rowcount

    def reindex(self) -> None:
        """Rebuild the FTS5 index from scratch."""
        with self._txn() as cur:
            cur.execute("INSERT INTO docs_fts(docs_fts) VALUES('rebuild')")

    def stats(self) -> dict[str, object]:
        """Return knowledge base statistics as a flat dictionary."""
        total_docs = self._conn.execute(
            "SELECT COUNT(*) FROM documents WHERE deleted_at IS NULL"
        ).fetchone()[0]
        type_rows = self._conn.execute(
            "SELECT type, COUNT(*) AS cnt FROM documents "
            "WHERE deleted_at IS NULL GROUP BY type ORDER BY cnt DESC"
        ).fetchall()
        docs_by_type: dict[str, int] = {r["type"]: r["cnt"] for r in type_rows}
        total_links = self._conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]
        soft_deleted = self._conn.execute(
            "SELECT COUNT(*) FROM documents WHERE deleted_at IS NOT NULL"
        ).fetchone()[0]
        recent = self._conn.execute(
            "SELECT COUNT(*) FROM documents WHERE deleted_at IS NULL "
            "AND updated_at >= datetime('now', '-7 days')"
        ).fetchone()[0]
        return {
            "total_docs": total_docs,
            "docs_by_type": docs_by_type,
            "total_links": total_links,
            "soft_deleted": soft_deleted,
            "recent_changes": recent,
        }

    def subgraph(self, root_id: str, depth: int = 2) -> dict[str, object]:
        """BFS traversal returning the subgraph centred on ``root_id``."""
        visited: set[str] = {root_id}
        frontier: list[str] = [root_id]
        for _ in range(depth):
            if not frontier:
                break
            placeholders = ",".join("?" for _ in frontier)
            rows = self._conn.execute(
                f"""
                SELECT from_id, to_id FROM links
                WHERE from_id IN ({placeholders})
                   OR to_id IN ({placeholders})
                """,
                [*frontier, *frontier],
            ).fetchall()
            next_frontier: list[str] = []
            for from_id, to_id in rows:
                for doc_id in (from_id, to_id):
                    if doc_id not in visited:
                        visited.add(doc_id)
                        next_frontier.append(doc_id)
            frontier = next_frontier
        if visited:
            placeholders = ",".join("?" for _ in visited)
            edge_rows = self._conn.execute(
                f"""
                SELECT from_id, to_id, rel FROM links
                WHERE from_id IN ({placeholders})
                  AND to_id IN ({placeholders})
                ORDER BY created_at
                """,
                [*visited, *visited],
            ).fetchall()
        else:
            edge_rows = []
        return {
            "doc_ids": list(visited),
            "edges": [{"from": r["from_id"], "to": r["to_id"], "rel": r["rel"]} for r in edge_rows],
        }


__all__ = ["MaintenanceMixin"]
