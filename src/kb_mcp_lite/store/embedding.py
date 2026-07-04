"""Embedding mixin for SqliteStore — vec0 operations."""

from __future__ import annotations

import logging

from kb_mcp_lite.schema import Document, NotFoundError, ValidationError


class EmbeddingMixin:
    """Mixin providing embedding / vector-similarity methods.

    Requires the host class to expose ``self._conn``, ``self._path``,
    ``self._row_to_doc_dict()``, and ``self._vec_conn_lazy()``.
    """

    # ---- embedding / similarity helpers ---------------------------------

    def similar_docs(self, doc_id: str, limit: int = 10) -> list[tuple[Document, float]]:
        """Return documents most similar to ``doc_id`` by embedding cosine distance."""
        vec_conn = self._vec_conn_lazy()
        if vec_conn is None:
            return []

        row = self._conn.execute(
            "SELECT rowid FROM documents WHERE id = ? AND deleted_at IS NULL",
            (doc_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(doc_id)

        try:
            emb_row = vec_conn.execute(
                "SELECT embedding FROM docs_vec WHERE rowid = ?",
                (row[0],),
            ).fetchone()
        except Exception:  # noqa: BLE001
            return []
        if emb_row is None:
            return []
        query_vec = emb_row[0]

        try:
            cursor = vec_conn.execute(
                """
                SELECT d.id, d.type, d.title, d.body, d.tags, d.source,
                       d.created_at, d.updated_at, d.deleted_at,
                       v.distance
                FROM docs_vec v
                JOIN documents d ON d.rowid = v.rowid
                WHERE v.embedding MATCH ?
                  AND v.rowid != ?
                  AND d.deleted_at IS NULL
                  AND k = ?
                ORDER BY v.distance
                """,
                (query_vec, row[0], limit),
            )
        except Exception:  # noqa: BLE001
            return []

        cols = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        result: list[tuple[Document, float]] = []
        for r in rows:
            d = dict(zip(cols, r))
            dist = float(d.pop("distance", 0.0))
            result.append((self._row_to_doc_dict(d), dist))
        return result

    def suggest_tags(self, doc_id: str, limit: int = 10) -> list[tuple[str, float]]:
        """Suggest tags based on similar documents' tags."""
        sim = self.similar_docs(doc_id, limit=limit * 3)
        if not sim:
            return []
        scores: dict[str, float] = {}
        for doc, dist in sim:
            weight = 1.0 - dist
            for tag in doc.tags:
                scores[tag] = scores.get(tag, 0.0) + weight
        return sorted(scores.items(), key=lambda x: -x[1])[:limit]

    def suggest_type(self, doc_id: str, limit: int = 10) -> list[tuple[str, float]]:
        """Suggest a document type based on similar docs."""
        sim = self.similar_docs(doc_id, limit=limit * 3)
        if not sim:
            return []
        scores: dict[str, float] = {}
        for doc, dist in sim:
            weight = 1.0 - dist
            scores[doc.type] = scores.get(doc.type, 0.0) + weight
        return sorted(scores.items(), key=lambda x: -x[1])[:limit]

    def find_duplicates(
        self, threshold: float = 0.15, limit: int = 50
    ) -> list[tuple[str, str, float]]:
        """Scan all documents and find near-duplicate pairs."""
        vec_conn = self._vec_conn_lazy()
        if vec_conn is None:
            return []

        doc_ids = self._conn.execute(
            "SELECT id, rowid FROM documents WHERE deleted_at IS NULL ORDER BY rowid"
        ).fetchall()

        results: list[tuple[str, str, float]] = []
        for idx, (id_a, rowid_a) in enumerate(doc_ids):
            try:
                emb_row = vec_conn.execute(
                    "SELECT embedding FROM docs_vec WHERE rowid = ?", (rowid_a,)
                ).fetchone()
            except Exception:  # noqa: BLE001
                continue
            if emb_row is None:
                continue
            query_vec = emb_row[0]
            try:
                cursor = vec_conn.execute(
                    """
                    SELECT d.id, v.distance
                    FROM docs_vec v
                    JOIN documents d ON d.rowid = v.rowid
                    WHERE v.embedding MATCH ?
                      AND v.rowid > ?
                      AND d.deleted_at IS NULL
                      AND v.distance <= ?
                      AND k = ?
                    ORDER BY v.distance
                    """,
                    (query_vec, rowid_a, threshold, limit - len(results)),
                )
            except Exception:  # noqa: BLE001
                continue
            for r in cursor.fetchall():
                id_b, dist = r[0], float(r[1])
                results.append((id_a, id_b, dist))
                if len(results) >= limit:
                    return results
        return results

    # ---- embeddings (vec0) ----------------------------------------------

    def _index_embedding(self, doc: Document) -> None:
        """Compute and store the embedding for ``doc``. Best-effort."""
        emb = getattr(self, "_embedder", None)
        if emb is None or not getattr(emb, "enabled", False):
            return
        try:
            text = f"{doc.title}\n\n{doc.body}".strip()
            vector = emb.embed(text)
        except Exception as e:  # noqa: BLE001
            logging.getLogger("kb_mcp_lite").warning("embedding failed for %s: %s", doc.id, e)
            return
        try:
            from sqlite_vec import serialize_float32
        except ImportError:
            return
        self._vec_conn = None
        vec_conn = self._vec_conn_lazy()
        if vec_conn is None:
            return
        try:
            rowid = self._conn.execute(
                "SELECT rowid FROM documents WHERE id = ?", (doc.id,)
            ).fetchone()
            if rowid is None:
                return
            vec_conn.execute("DELETE FROM docs_vec WHERE rowid = ?", (rowid[0],))
            vec_conn.execute(
                "INSERT INTO docs_vec(rowid, embedding) VALUES (?, ?)",
                (rowid[0], serialize_float32(vector)),
            )
        except Exception as e:  # noqa: BLE001
            logging.getLogger("kb_mcp_lite").debug("docs_vec write skipped for %s: %s", doc.id, e)

    def _remove_embedding(self, doc_id: str) -> None:
        vec_conn = self._vec_conn_lazy()
        if vec_conn is None:
            return
        try:
            vec_conn.execute(
                "DELETE FROM docs_vec WHERE rowid = (SELECT rowid FROM documents WHERE id = ?)",
                (doc_id,),
            )
        except Exception:  # noqa: BLE001
            pass

    def _vec_conn_lazy(self):  # type: ignore[no-untyped-def]
        """Open the vec0 side connection on first need; cache it."""
        if self._vec_conn is not None:
            return self._vec_conn if self._vec_conn is not False else None
        emb = getattr(self, "_embedder", None)
        if emb is None or not getattr(emb, "enabled", False):
            return None
        try:
            from kb_mcp_lite.store.sqlite import _make_sqlite_connection

            conn = _make_sqlite_connection(str(self.path))
        except Exception as e:  # noqa: BLE001
            logging.getLogger("kb_mcp_lite").debug("vec0 connection not available: %s", e)
            self._vec_conn = False
            return None

        dim = getattr(emb, "dim", 0) or 1536
        try:
            conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS docs_vec USING vec0("
                f"embedding float[{dim}] distance_metric=cosine)"
            )
        except Exception as e:  # noqa: BLE001
            logging.getLogger("kb_mcp_lite").debug("docs_vec table unavailable: %s", e)
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._vec_conn = False
            return None
        self._vec_conn = conn
        try:
            conn.execute("PRAGMA foreign_keys=ON")
        except Exception:  # noqa: BLE001
            pass
        self._vec_row_is_tuple = True
        return conn

    def reindex_embeddings(self, progress_callback=None) -> int:
        """Recompute embeddings for all active documents.

        Args:
            progress_callback: Optional callable(processed, total) called after each doc.
        """
        emb = getattr(self, "_embedder", None)
        if emb is None or not getattr(emb, "enabled", False):
            raise ValidationError("embedder not configured; cannot reindex")
        rows = self._conn.execute(
            "SELECT id, title, body FROM documents WHERE deleted_at IS NULL"
        ).fetchall()
        n_ok, n_fail = 0, 0
        failed_ids: list[str] = []
        total = len(rows)
        for i, r in enumerate(rows):
            doc = Document(
                id=r["id"],
                type="(unknown)",
                title=r["title"],
                body=r["body"],
            )
            self._index_embedding(doc)
            if self._count_vec(doc.id) >= 1:
                n_ok += 1
            else:
                n_fail += 1
                failed_ids.append(doc.id)
            if progress_callback:
                progress_callback(i + 1, total)
        self.last_reindex_report = {
            "succeeded": n_ok,
            "failed": n_fail,
            "failed_ids": failed_ids,
            "dim": getattr(emb, "dim", 0),
            "total": total,
        }
        return n_ok

    def _count_vec(self, doc_id: str) -> int:
        """Return 1 if ``doc_id`` has a row in ``docs_vec``, else 0."""
        vec_conn = self._vec_conn_lazy()
        if vec_conn is None:
            return 0
        try:
            r = vec_conn.execute(
                "SELECT rowid FROM docs_vec WHERE rowid = "
                "(SELECT rowid FROM documents WHERE id = ?)",
                (doc_id,),
            ).fetchone()
            return 1 if r is not None else 0
        except Exception:  # noqa: BLE001
            return 0


__all__ = ["EmbeddingMixin"]
