"""Search mixin for SqliteStore — FTS5 + vec0 search operations."""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING, Any, List

from kb_mcp_lite.schema import Document, SearchHit, ValidationError


class SearchMixin:
    """Mixin providing search methods.

    Requires the host class to expose ``self._conn``, ``self._parse_dt()``,
    ``self._vec_conn_lazy()``, and ``self.get()``.
    """

    if TYPE_CHECKING:
        import sqlite3

        _conn: sqlite3.Connection
        _vec_row_is_tuple: bool

        def _parse_dt(self, value: str | None) -> object: ...
        def _vec_conn_lazy(self) -> Any: ...
        def get(self, doc_id: str, include_deleted: bool = False) -> Document: ...

    def search(
        self,
        query: str,
        type: str | None = None,  # noqa: A002
        tags: List[str] | None = None,
        limit: int = 10,
        mode: str = "lexical",
        rrf_k: int = 60,
    ) -> List[SearchHit]:
        """Full-text search via the backend's FTS engine.

        ``mode`` selects the scoring strategy:

        - ``"lexical"`` (default): exact-token BM25 on ``docs_fts``.
        - ``"fuzzy"``: trigram BM25 on ``docs_fts_trgm``.
        - ``"semantic"``: vector similarity via ``docs_vec``.
        - ``"hybrid"`` / ``"rrf"``: reciprocal-rank fusion of all three.

        ``limit`` is capped at 100. ``rrf_k`` sets the RRF constant (default 60).
        """
        query = (query or "").strip()
        if not query:
            raise ValidationError("query must not be empty")
        if limit < 1 or limit > 100:
            raise ValidationError("limit must be in 1..100")
        if mode not in ("lexical", "fuzzy", "semantic", "hybrid", "rrf"):
            raise ValidationError(
                f"mode must be one of 'lexical', 'fuzzy', 'semantic', "
                f"'hybrid', or 'rrf' (got {mode!r})"
            )

        if mode == "lexical":
            return self._search_fts(query, type=type, tags=tags, limit=limit, table="docs_fts")
        if mode == "fuzzy":
            return self._search_fts(query, type=type, tags=tags, limit=limit, table="docs_fts_trgm")
        if mode == "semantic":
            return self._search_semantic(query, type=type, tags=tags, limit=limit)
        return self._search_rrf(query, type=type, tags=tags, limit=limit, k=rrf_k)

    def _search_fts(
        self,
        query: str,
        type: str | None,
        tags: List[str] | None,
        limit: int,
        table: str,
    ) -> List[SearchHit]:
        """Run a single FTS5 query and return SearchHit list."""
        if table == "docs_fts_trgm":
            fts_q = self._escape_fts(query)
        else:
            fts_q = self._escape_fts_lexical(query)
        sql = f"""
            SELECT d.*,
                   snippet({table}, 1, '<b>', '</b>', '…', 12) AS snip,
                   bm25({table}) AS score
            FROM {table}
            JOIN documents d ON d.rowid = {table}.rowid
            WHERE {table} MATCH ?
              AND d.deleted_at IS NULL
        """
        params: List[object] = [fts_q]
        if type:
            sql += " AND d.type = ?"
            params.append(type)
        sql += " ORDER BY score LIMIT ?"
        params.append(limit)

        try:
            rows = self._conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as e:
            raise ValidationError(f"invalid FTS query {query!r}: {e}") from e

        hits: List[SearchHit] = []
        for r in rows:
            d = dict(r)
            snippet_text = d.pop("snip", "") or ""
            score = float(d.pop("score", 0.0))
            doc = self._row_to_doc_dict(d)
            hits.append(SearchHit(doc=doc, snippet=snippet_text, score=score))

        if tags:
            wanted: set[str] = set(tags)
            hits = [h for h in hits if wanted.issubset(set(h.doc.tags))]
        return hits

    def _search_rrf(
        self,
        query: str,
        type: str | None,
        tags: List[str] | None,
        limit: int,
        k: int = 60,
    ) -> List[SearchHit]:
        """Reciprocal-rank fusion of lexical + fuzzy + semantic results."""
        fetch_n = limit * 3
        lexical = self._search_fts(query, type=type, tags=tags, limit=fetch_n, table="docs_fts")
        fuzzy = self._search_fts(query, type=type, tags=tags, limit=fetch_n, table="docs_fts_trgm")
        try:
            semantic = self._search_semantic(query, type=type, tags=tags, limit=fetch_n)
        except Exception:
            semantic = []

        rrf_scores: dict[str, tuple[float, str, Document]] = {}
        for rank_1based, hit in enumerate(lexical, start=1):
            contrib = 1.0 / (k + rank_1based)
            cur_score, _, _ = rrf_scores.get(hit.doc.id, (0.0, "", hit.doc))
            rrf_scores[hit.doc.id] = (cur_score + contrib, hit.snippet, hit.doc)
        for rank_1based, hit in enumerate(fuzzy, start=1):
            contrib = 1.0 / (k + rank_1based)
            cur_score, cur_snip, doc = rrf_scores.get(hit.doc.id, (0.0, "", hit.doc))
            snippet = cur_snip or hit.snippet
            rrf_scores[hit.doc.id] = (cur_score + contrib, snippet, doc)
        for rank_1based, hit in enumerate(semantic, start=1):
            contrib = 1.0 / (k + rank_1based)
            cur_score, cur_snip, doc = rrf_scores.get(hit.doc.id, (0.0, "", hit.doc))
            snippet = cur_snip or hit.snippet
            rrf_scores[hit.doc.id] = (cur_score + contrib, snippet, doc)

        sorted_ids = sorted(rrf_scores.keys(), key=lambda i: -rrf_scores[i][0])
        hits: list[SearchHit] = []
        for doc_id in sorted_ids:
            score, snippet, doc = rrf_scores[doc_id]
            hits.append(SearchHit(doc=doc, snippet=snippet, score=round(score, 6)))
        if tags:
            wanted: set[str] = set(tags)
            hits = [h for h in hits if wanted.issubset(set(h.doc.tags))]
        return hits[:limit]

    def _search_semantic(
        self,
        query: str,
        type: str | None,
        tags: List[str] | None,
        limit: int,
    ) -> List[SearchHit]:
        """Vector similarity search via the vec0 ``docs_vec`` table."""
        emb = getattr(self, "_embedder", None)
        if emb is None or not getattr(emb, "enabled", False):
            raise ValidationError("semantic search requires an enabled embedder")
        vec_conn = self._vec_conn_lazy()
        if vec_conn is None:
            raise ValidationError("vec0 extension not available; semantic search disabled")
        try:
            from sqlite_vec import serialize_float32
        except ImportError as e:
            raise ValidationError("sqlite-vec not installed; run: pip install 'kb-mcp[vec]'") from e

        query_vec = emb.embed(query)
        sql = """
            SELECT d.*, v.distance AS vec_distance
            FROM docs_vec v
            JOIN documents d ON d.rowid = v.rowid
            WHERE v.embedding MATCH ?
              AND k = ?
              AND d.deleted_at IS NULL
        """
        params: List[object] = [serialize_float32(query_vec), limit * 4]
        if type:
            sql += " AND d.type = ?"
            params.append(type)
        sql += " ORDER BY v.distance"

        try:
            rows = vec_conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as e:
            raise ValidationError(f"vec0 query failed: {e}") from e

        row_is_tuple = getattr(self, "_vec_row_is_tuple", False)
        if row_is_tuple:
            doc_col_index: int | None = 0
            distance_col_index: int | str | None = 9
        else:
            doc_col_index = None
            distance_col_index = "vec_distance"

        hits: List[SearchHit] = []
        for r in rows:
            if row_is_tuple:
                doc = self.get(r[doc_col_index])
                vec_distance = float(r[distance_col_index] or 0.0)
            else:
                d = dict(r)
                vec_distance = float(d.pop("vec_distance", 0.0) or 0.0)
                doc = self._row_to_doc_dict(d)
            score = -vec_distance
            snippet = (doc.body[:120] + "…") if len(doc.body) > 120 else doc.body
            hits.append(SearchHit(doc=doc, snippet=snippet, score=score))

        if tags:
            wanted: set[str] = set(tags)
            hits = [h for h in hits if wanted.issubset(set(h.doc.tags))]
        return hits[:limit]

    def _row_to_doc_dict(self, d: dict) -> Document:
        """Convert a plain dict to a Document (after we already materialised a Row)."""
        d = dict(d)
        if "tags" in d and isinstance(d["tags"], str):
            d["tags"] = json.loads(d["tags"] or "[]")
        for k in ("created_at", "updated_at", "deleted_at"):
            if isinstance(d.get(k), str):
                d[k] = self._parse_dt(d[k])
        d.pop("snip", None)
        d.pop("score", None)
        return Document.model_construct(**d)

    @staticmethod
    def _escape_fts(query: str) -> str:
        """Build an FTS5 expression tolerant to typos and word boundaries."""
        tokens: List[str] = []
        for tok in query.split():
            tok_clean = tok.strip().replace('"', '""')
            if not tok_clean:
                continue
            if len(tok_clean) >= 3:
                tokens.append(f'"{tok_clean}"*')
            else:
                tokens.append(f'"{tok_clean}"')
        return " OR ".join(tokens) if tokens else '""'

    @staticmethod
    def _escape_fts_lexical(query: str) -> str:
        """Strict AND-of-tokens FTS5 expression for lexical mode."""
        return " AND ".join(f'"{t.strip()}"' for t in query.split() if t.strip()) or '""'


__all__ = ["SearchMixin"]
