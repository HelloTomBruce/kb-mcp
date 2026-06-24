"""SQLite implementation of the :class:`~kb_mcp_lite.store.Store` Protocol.

Threading: a single ``SqliteStore`` instance is **not** thread-safe; use
one per thread or serialise calls. Multi-process access to the same
DB file is supported via WAL mode.

Soft delete: :meth:`delete` sets ``deleted_at``. Reads filter
``deleted_at IS NULL``. :meth:`prune` hard-deletes after a grace period.

Failure modes: every method either returns the documented value or
raises one of the documented exceptions from :mod:`kb_mcp_lite.schema`.

v0.2 (Phase D): the connection is created with the ``pysqlite3``
module when available (so ``sqlite-vec`` can load the vec0 extension).
If pysqlite3 is missing, we fall back to stdlib ``sqlite3`` — but
``docs_vec`` operations will then raise ``IntegrityError`` on first
attempt. This is a deliberate graceful-degradation: kb-mcp without
vec support still works as v0.1.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sqlite3 as _stdlib_sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Iterable, Iterator, Optional

from kb_mcp_lite.migrations import apply_migrations
from kb_mcp_lite.schema import (
    Document,
    DoctorCheck,
    DoctorReport,
    DuplicateError,
    ImportReport,
    IntegrityError,
    Link,
    NotFoundError,
    SearchHit,
    ValidationError,
)


def _make_sqlite_connection(path: str):  # type: ignore[no-untyped-def]
    """Open a sqlite3 connection that supports vec0 if possible.

    Strategy:

    1. ``pysqlite3`` if installed (ships a SQLite build with
       extension support). This is the happy path — has wheels for
       Linux and macOS (x86_64 + arm64).
    2. Stdlib ``sqlite3`` (no vec0 — semantic search disabled but
       the rest of kb-mcp keeps working).

    The ctypes-based fallback for Python 3.12 macOS arm64 was
    abandoned: that Python build strips ``sqlite3_enable_load_extension``
    from the public ABI (``-DSQLITE_OMIT_LOAD_EXTENSION``), so the
    symbol genuinely does not exist in the loaded library.
    """
    try:
        import pysqlite3 as _psql  # type: ignore[import-not-found]
        conn = _psql.connect(path, isolation_level=None)
        conn.enable_load_extension(True)
        _try_load_vec0(conn)
        return conn
    except ImportError:
        pass
    # Fallback: stdlib. vec0 won't work; the embedder becomes a
    # no-op and semantic search returns ValidationError.
    return _stdlib_sqlite3.connect(path, isolation_level=None)


def _try_load_vec0(conn) -> None:
    """Best-effort load of the vec0 SQLite extension. No-op on failure."""
    import logging
    log = logging.getLogger("kb_mcp_lite")
    try:
        import sqlite_vec  # type: ignore[import-untyped]
        sqlite_vec.load(conn)
    except Exception as e:
        log.debug("vec0 extension not loaded (%s); semantic search disabled", e)

# Fields that ``update`` is allowed to mutate. Anything else raises
# ``ValidationError``. ``id``, ``type``, ``created_at``, ``updated_at``,
# and ``deleted_at`` are managed by the store and cannot be changed.
_UPDATEABLE_FIELDS = frozenset({"title", "body", "tags", "source"})


class SqliteStore:
    """SQLite-backed :class:`~kb_mcp_lite.store.Store` implementation."""

    def __init__(
        self,
        db_path: Path | str,
        embedder: object | None = None,
    ) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Use a vanilla stdlib connection for migration; the vec0
        # connection is opened later only if we actually need to
        # write/read vectors. This keeps ``kb init`` / ``kb doctor``
        # working on any platform, even when vec0 is unavailable.
        self._conn = _stdlib_sqlite3.connect(str(self._path), isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        # WAL allows concurrent readers while a writer is active.
        self._conn.execute("PRAGMA journal_mode=WAL")
        # FK enforcement is per-connection; must be set every time.
        self._conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(self._conn)
        # Embedder is optional; lazy-make one if not supplied so existing
        # callers (``SqliteStore(path)``) keep working unchanged.
        if embedder is None:
            from kb_mcp_lite.embedder import make_embedder
            embedder = make_embedder()
        self._embedder = embedder
        # Track whether vec0 is available on this connection. Set on
        # first need (lazy). The base connection (self._conn) is plain
        # stdlib; vec0 access is routed through a side connection that
        # only opens when needed, so platforms without vec0 don't fail.
        self._vec_conn = None  # type: ignore[assignment]

    # ---- context manager + close ---------------------------------------

    def __enter__(self) -> "SqliteStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.ProgrammingError:
            pass  # already closed

    @property
    def path(self) -> Path:
        return self._path

    # ---- helpers --------------------------------------------------------

    @contextmanager
    def _txn(self) -> Iterator[sqlite3.Cursor]:
        cur = self._conn.cursor()
        cur.execute("BEGIN")
        try:
            yield cur
            cur.execute("COMMIT")
        except Exception:
            try:
                cur.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass
            raise

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        s = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(s)
        except ValueError as e:
            raise IntegrityError(f"unparseable datetime {value!r}: {e}") from e

    def _row_to_doc(self, row: sqlite3.Row) -> Document:
        d = dict(row)
        d["tags"] = json.loads(d.get("tags") or "[]")
        for k in ("created_at", "updated_at", "deleted_at"):
            if d.get(k):
                d[k] = self._parse_dt(d[k])
        return Document.model_validate(d)

    def _row_to_link(self, row: sqlite3.Row) -> Link:
        return Link(
            from_id=row["from_id"],
            to_id=row["to_id"],
            rel=row["rel"],
            created_at=self._parse_dt(row["created_at"]) or datetime.now(timezone.utc),
        )

    # ---- write ----------------------------------------------------------

    def add(self, doc: Document) -> str:
        # If the caller left id blank, generate one from type+title.
        if not doc.id:
            from kb_mcp_lite.schema import make_id

            doc = doc.model_copy(update={"id": make_id(doc.type, doc.title)})
        elif not re.match(r"^[a-z0-9][a-z0-9/_-]*$", doc.id):
            raise ValidationError(f"id must match ^[a-z0-9][a-z0-9/_-]*$ (got {doc.id!r})")

        row = doc.to_row()
        try:
            with self._txn() as cur:
                cur.execute(
                    """
                    INSERT INTO documents
                        (id, type, title, body, tags, source,
                         created_at, updated_at, deleted_at)
                    VALUES
                        (:id, :type, :title, :body, :tags, :source,
                         :created_at, :updated_at, :deleted_at)
                    """,
                    row,
                )
        except sqlite3.IntegrityError as e:
            msg = str(e)
            if "UNIQUE constraint failed: documents.id" in msg or "PRIMARY KEY" in msg:
                raise DuplicateError(doc.id) from e
            raise IntegrityError(msg) from e
        # Best-effort: write embedding if embedder is configured. Errors
        # here MUST NOT break the add (the lexical path is more
        # important), so we log and move on.
        self._index_embedding(doc)
        return doc.id

    def update(self, doc_id: str, **fields: object) -> Document:
        bad = set(fields.keys()) - _UPDATEABLE_FIELDS
        if bad:
            raise ValidationError(f"cannot update fields: {sorted(bad)}")
        if not fields:
            raise ValidationError("update requires at least one field")

        existing = self.get(doc_id, include_deleted=True)
        merged = existing.model_dump()
        for k, v in fields.items():
            if k == "tags":
                if v is None:
                    merged["tags"] = []
                elif isinstance(v, str):
                    # accept "a,b,c" comma-list form too
                    merged["tags"] = [t.strip() for t in v.split(",") if t.strip()]
                elif isinstance(v, list):
                    merged["tags"] = list(v)
                else:
                    raise ValidationError(
                        f"tags must be List[str] or comma string (got {type(v).__name__})"
                    )
            else:
                merged[k] = v
        merged["updated_at"] = datetime.now(timezone.utc)
        new_doc = Document.model_validate(merged)

        row = new_doc.to_row()
        with self._txn() as cur:
            cur.execute(
                """
                UPDATE documents SET
                    title=:title, body=:body, tags=:tags, source=:source,
                    type=:type, updated_at=:updated_at
                WHERE id=:id
                """,
                row,
            )
        # Re-embed if title or body changed (cheap heuristic; tag-only
        # changes don't really need re-embedding, but the cost is small).
        if "title" in fields or "body" in fields:
            self._index_embedding(new_doc)
        return self.get(doc_id)

    def delete(self, doc_id: str) -> None:
        """Soft-delete.

        Idempotent: deleting an already soft-deleted document is a no-op
        (no error). Deleting a never-existed document raises
        :class:`NotFoundError`.
        """
        active = self._conn.execute(
            "SELECT 1 FROM documents WHERE id = ? AND deleted_at IS NULL",
            (doc_id,),
        ).fetchone()
        if active is None:
            # Either never existed, or already soft-deleted.
            exists = self._conn.execute(
                "SELECT 1 FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()
            if exists is None:
                raise NotFoundError(doc_id)
            return  # already deleted — no-op
        now = self._now_iso()
        with self._txn() as cur:
            cur.execute(
                "UPDATE documents SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
                (now, doc_id),
            )
        # Note: we do NOT touch docs_fts / docs_fts_trgm here. FTS5
        # with ``content='documents'`` is a projection of the
        # documents table, so soft-deleted rows remain visible to
        # ``SELECT rowid FROM docs_fts``; they're excluded from
        # search results by the ``WHERE d.deleted_at IS NULL`` filter
        # in every _search_fts query. Touching the FTS table here
        # would require the FTS5 internal "delete-all-tokens" command
        # which is unreliable for external-content tables — better to
        # filter at the search layer.
        # Remove the vector too — soft-deleted docs should not surface
        # in semantic search.
        self._remove_embedding(doc_id)

    # ---- read -----------------------------------------------------------

    def get(self, doc_id: str, include_deleted: bool = False) -> Document:
        sql = "SELECT * FROM documents WHERE id = ?"
        if not include_deleted:
            sql += " AND deleted_at IS NULL"
        row = self._conn.execute(sql, (doc_id,)).fetchone()
        if row is None:
            raise NotFoundError(doc_id)
        return self._row_to_doc(row)

    def list(
        self,
        type: str | None = None,  # noqa: A002
        tags: List[str] | None = None,
        limit: int = 100,
        offset: int = 0,
        include_deleted: bool = False,
    ) -> List[Document]:
        if limit < 1 or limit > 1000:
            raise ValidationError("limit must be in 1..1000")
        if offset < 0:
            raise ValidationError("offset must be >= 0")

        sql = "SELECT * FROM documents WHERE 1=1"
        params: List[object] = []
        if not include_deleted:
            sql += " AND deleted_at IS NULL"
        if type:
            sql += " AND type = ?"
            params.append(type)
        sql += " ORDER BY updated_at DESC, id ASC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = self._conn.execute(sql, params).fetchall()
        docs = [self._row_to_doc(r) for r in rows]

        if tags:
            wanted = set(tags)
            docs = [d for d in docs if wanted.issubset(set(d.tags))]
        return docs

    def search(
        self,
        query: str,
        type: str | None = None,  # noqa: A002
        tags: List[str] | None = None,
        limit: int = 10,
        mode: str = "lexical",
    ) -> List[SearchHit]:
        """Full-text search via the backend's FTS engine.

        ``mode`` selects the scoring strategy:

        - ``"lexical"`` (default): exact-token BM25 on ``docs_fts``.
          Best for known-vocabulary queries. Lowest recall but highest
          precision; cheap.
        - ``"fuzzy"``: trigram BM25 on ``docs_fts_trgm``. Tolerates
          typos (``sqlit`` → ``sqlitte``), prefix matches, and
          separator differences (``fastech-energy`` ↔ ``fastech``).
          Slower; slightly noisier.
        - ``"hybrid"``: union of both, with exact-token hits ranked
          above trigram-only hits. Combines precision of ``lexical``
          with recall of ``fuzzy``.

        Returns ranked results with snippets. Empty query returns ``[]``.

        ``limit`` is capped at 100.

        Raises:
            ValidationError: if ``query`` is empty after stripping,
                ``limit`` is out of range, or ``mode`` is unknown.
        """
        query = (query or "").strip()
        if not query:
            raise ValidationError("query must not be empty")
        if limit < 1 or limit > 100:
            raise ValidationError("limit must be in 1..100")
        if mode not in ("lexical", "fuzzy", "semantic", "hybrid"):
            raise ValidationError(
                f"mode must be 'lexical', 'fuzzy', 'semantic', or 'hybrid' (got {mode!r})"
            )

        if mode == "lexical":
            return self._search_fts(query, type=type, tags=tags, limit=limit, table="docs_fts")
        if mode == "fuzzy":
            return self._search_fts(
                query, type=type, tags=tags, limit=limit, table="docs_fts_trgm"
            )
        if mode == "semantic":
            return self._search_semantic(query, type=type, tags=tags, limit=limit)
        # hybrid: union of exact + fuzzy + semantic
        return self._search_hybrid(query, type=type, tags=tags, limit=limit)

    def _search_fts(
        self,
        query: str,
        type: str | None,
        tags: List[str] | None,
        limit: int,
        table: str,
    ) -> List[SearchHit]:
        """Run a single FTS5 query and return SearchHit list.

        ``table`` must be either ``"docs_fts"`` (unicode61 tokenizer,
        exact) or ``"docs_fts_trgm"`` (trigram tokenizer, fuzzy).

        For ``docs_fts`` (lexical) we keep the v0.1 strict AND-of-tokens
        semantics. For ``docs_fts_trgm`` (fuzzy/hybrid) we use an
        OR-of-prefix expression so that partial tokens still hit.
        """
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

    def _search_hybrid(
        self,
        query: str,
        type: str | None,
        tags: List[str] | None,
        limit: int,
    ) -> List[SearchHit]:
        """Combine exact + trigram + semantic results, exact wins.

        Strategy:
        1. Fetch up to ``limit`` exact hits from ``docs_fts``.
        2. Fetch up to ``limit * 2`` fuzzy hits from ``docs_fts_trgm``
           that are NOT already in (1).
        3. Fetch up to ``limit * 2`` semantic hits (vec0) that are NOT
           in (1) or (2). Semantic is best-effort — embedder errors
           fall back to lexical+fuzzy only.
        4. Concatenate (exact first, then fuzzy-only, then
           semantic-only), truncate to ``limit``.
        """
        exact = self._search_fts(query, type=type, tags=tags, limit=limit, table="docs_fts")
        seen = {h.doc.id for h in exact}

        fuzzy = self._search_fts(
            query, type=type, tags=tags, limit=limit * 2, table="docs_fts_trgm"
        )
        fuzzy_only = [h for h in fuzzy if h.doc.id not in seen]
        seen.update(h.doc.id for h in fuzzy_only)

        try:
            semantic = self._search_semantic(
                query, type=type, tags=tags, limit=limit * 2
            )
        except ValidationError:
            # Embedder not configured or no vectors yet — skip silently.
            semantic = []
        semantic_only = [h for h in semantic if h.doc.id not in seen]

        return (exact + fuzzy_only + semantic_only)[:limit]

    def _search_semantic(
        self,
        query: str,
        type: str | None,
        tags: List[str] | None,
        limit: int,
    ) -> List[SearchHit]:
        """Vector similarity search via the vec0 ``docs_vec`` table.

        Requires an enabled embedder (otherwise raises
        :class:`ValidationError`). Returns ``[]`` when the KB has no
        vectors yet (cold start) or when vec0 extension is not loaded.
        """
        emb = getattr(self, "_embedder", None)
        if emb is None or not getattr(emb, "enabled", False):
            raise ValidationError(
                "semantic search requires an enabled embedder; "
                "configure auxiliary.embedding in ~/.hermes/config.yaml"
            )
        vec_conn = self._vec_conn_lazy()
        if vec_conn is None:
            raise ValidationError(
                "vec0 extension not available; semantic search disabled"
            )
        try:
            from sqlite_vec import serialize_float32
        except ImportError as e:
            raise ValidationError(
                "sqlite-vec not installed; run: pip install 'kb-mcp[vec]'"
            ) from e

        query_vec = emb.embed(query)

        # vec0 KNN query. We use the rowid from documents so we can join
        # back to the doc. vec0 does NOT accept standard ``LIMIT``; it
        # requires the special ``k = N`` predicate to bound result count.
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

        # rows come from vec_conn. May be Row (dict-like) or tuple
        # depending on row-factory compatibility with pysqlite3.
        row_is_tuple = getattr(self, "_vec_row_is_tuple", False)
        # Cache the column order for the vec0 KNN query so we can read
        # by position when rows are tuples.
        # SELECT d.*, v.distance AS vec_distance
        # d.* expands to: id, type, title, body, tags, source,
        #                 created_at, updated_at, deleted_at (9 cols)
        # plus vec_distance at index 9.
        if row_is_tuple:
            doc_col_index = 0  # id
            distance_col_index = 9
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
            # Convert cosine distance to a BM25-style "lower = better"
            # score. vec0's cosine returns 0.0 for identical vectors
            # and ~2.0 for opposite. We negate so that semantic score
            # ordering matches lexical (both ascending on
            # "more-relevant-first").
            score = -vec_distance
            snippet = (doc.body[:120] + "…") if len(doc.body) > 120 else doc.body
            hits.append(SearchHit(doc=doc, snippet=snippet, score=score))

        if tags:
            wanted: set[str] = set(tags)
            hits = [h for h in hits if wanted.issubset(set(h.doc.tags))]
        return hits[:limit]

    def _row_to_doc_dict(self, d: dict) -> Document:
        """Same as :meth:`_row_to_doc` but accepts a plain dict (used
        after we already materialised a Row via ``dict(r)``)."""
        d = dict(d)
        if "tags" in d and isinstance(d["tags"], str):
            d["tags"] = json.loads(d["tags"] or "[]")
        for k in ("created_at", "updated_at", "deleted_at"):
            if isinstance(d.get(k), str):
                d[k] = self._parse_dt(d[k])
        # 'snip' and 'score' are search-only columns; drop them.
        d.pop("snip", None)
        d.pop("score", None)
        return Document.model_validate(d)

    @staticmethod
    def _escape_fts(query: str) -> str:
        """Build an FTS5 expression tolerant to typos and word boundaries.

        For each whitespace-separated token of length ≥ 3 we emit a
        prefix pattern (``tok*``); tokens of length 1–2 are emitted
        verbatim (FTS5 trigram cannot match sub-3-char tokens). The
        tokens are joined with ``OR`` (not ``AND``) so that noisy queries
        still produce some hits.

        This is the heuristic the v0.2 fuzzy/hybrid path uses. Pure
        ``lexical`` mode uses :meth:`_escape_fts_lexical` instead.

        The original whitespace-tokenising behaviour with double-quote
        wrapping is preserved for short tokens to keep the unicode61
        path on ``docs_fts`` (hybrid mode) working as expected.
        """
        tokens: List[str] = []
        for tok in query.split():
            tok_clean = tok.strip().replace('"', '""')
            if not tok_clean:
                continue
            if len(tok_clean) >= 3:
                # FTS5 prefix match — combines with the trigram index
                # for typo tolerance and works on the unicode61 index
                # for prefix-completion.
                tokens.append(f'"{tok_clean}"*')
            else:
                tokens.append(f'"{tok_clean}"')
        return " OR ".join(tokens) if tokens else '""'

    @staticmethod
    def _escape_fts_lexical(query: str) -> str:
        """Strict AND-of-tokens FTS5 expression for ``lexical`` mode.

        Identical behaviour to the v0.1 escape: each token is wrapped in
        double quotes so that FTS5 special characters are treated
        literally. Tokens are joined with whitespace, which is FTS5's
        implicit AND.
        """
        tokens: List[str] = []
        for tok in query.split():
            tok = tok.replace('"', '""')
            if tok:
                tokens.append(f'"{tok}"')
        return " ".join(tokens) if tokens else '""'

    # ---- links ----------------------------------------------------------

    def link(self, from_id: str, to_id: str, rel: str = "relates-to") -> Link:
        rel = (rel or "").strip()
        if not rel:
            raise ValidationError("rel must be non-empty")
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]*$", rel):
            raise ValidationError(f"rel must match ^[A-Za-z0-9][A-Za-z0-9_-]*$ (got {rel!r})")
        # Verify both endpoints exist (active).
        self.get(from_id)
        self.get(to_id)

        now = self._now_iso()
        with self._txn() as cur:
            cur.execute(
                """
                INSERT OR IGNORE INTO links (from_id, to_id, rel, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (from_id, to_id, rel, now),
            )
            row = cur.execute(
                "SELECT from_id, to_id, rel, created_at FROM links WHERE from_id=? AND to_id=? AND rel=?",
                (from_id, to_id, rel),
            ).fetchone()
        assert row is not None  # just inserted
        return self._row_to_link(row)

    def unlink(
        self,
        from_id: str,
        to_id: str,
        rel: str | None = None,
    ) -> int:
        sql = "DELETE FROM links WHERE from_id = ? AND to_id = ?"
        params: List[object] = [from_id, to_id]
        if rel is not None:
            sql += " AND rel = ?"
            params.append(rel)
        cur = self._conn.execute(sql, params)
        return cur.rowcount

    def backlinks(self, doc_id: str) -> List[Link]:
        rows = self._conn.execute(
            "SELECT from_id, to_id, rel, created_at FROM links WHERE to_id = ? ORDER BY created_at",
            (doc_id,),
        ).fetchall()
        return [self._row_to_link(r) for r in rows]

    def outlinks(self, doc_id: str) -> List[Link]:
        rows = self._conn.execute(
            "SELECT from_id, to_id, rel, created_at FROM links WHERE from_id = ? ORDER BY created_at",
            (doc_id,),
        ).fetchall()
        return [self._row_to_link(r) for r in rows]

    # ---- bulk / io ------------------------------------------------------

    def import_many(self, docs: Iterable[Document]) -> ImportReport:
        report = ImportReport()
        for doc in docs:
            try:
                if doc.source:
                    row = self._conn.execute(
                        "SELECT id FROM documents WHERE source = ? AND deleted_at IS NULL",
                        (doc.source,),
                    ).fetchone()
                    if row is not None:
                        existing_id = row["id"]
                        # Update mutable fields; keep id/created_at.
                        self.update(
                            existing_id,
                            **{
                                k: v for k, v in doc.model_dump().items() if k in _UPDATEABLE_FIELDS
                            },
                        )
                        report.updated += 1
                        continue
                self.add(doc)
                report.inserted += 1
            except (DuplicateError, ValidationError) as e:
                report.errors.append(f"{doc.id or doc.title}: {e}")
                report.skipped += 1
        return report

    def export_all(self, include_deleted: bool = False) -> List[Document]:
        sql = "SELECT * FROM documents"
        if not include_deleted:
            sql += " WHERE deleted_at IS NULL"
        sql += " ORDER BY id"
        rows = self._conn.execute(sql).fetchall()
        return [self._row_to_doc(r) for r in rows]

    # ---- maintenance ----------------------------------------------------

    def doctor(self) -> DoctorReport:
        checks: List[DoctorCheck] = []

        # 1. PRAGMA integrity_check
        row = self._conn.execute("PRAGMA integrity_check").fetchone()
        ok = bool(row) and row[0] == "ok"
        checks.append(
            DoctorCheck(name="integrity_check", ok=ok, detail=str(row[0]) if row else "no result")
        )

        # 2. FTS row count == active document count.
        # FTS5 with ``content='documents'`` is a projection of the
        # documents table: ``SELECT rowid FROM docs_fts`` returns ALL
        # rows from documents, including soft-deleted ones (FTS5 has
        # no way to mark individual rows as "out of the index" when
        # the backing table is still there). Soft-deleted docs are
        # excluded from search via the ``WHERE d.deleted_at IS NULL``
        # filter in the actual search queries. For the doctor check
        # we therefore count FTS rows that correspond to active docs.
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

        # 3. No orphan links (link endpoint missing)
        n_orphans = self._conn.execute(
            """
            SELECT COUNT(*) FROM links l
            LEFT JOIN documents d ON d.id = l.to_id
            WHERE d.id IS NULL
            """
        ).fetchone()[0]
        checks.append(
            DoctorCheck(name="no_orphan_links", ok=n_orphans == 0, detail=f"{n_orphans} orphans")
        )

        # 4. All docs have non-empty type and title
        n_invalid = self._conn.execute(
            "SELECT COUNT(*) FROM documents WHERE type = '' OR title = ''"
        ).fetchone()[0]
        checks.append(
            DoctorCheck(name="valid_type_title", ok=n_invalid == 0, detail=f"{n_invalid} invalid")
        )

        return DoctorReport(ok=all(c.ok for c in checks), checks=checks)

    def prune(self, older_than: timedelta = timedelta(days=30)) -> int:
        cutoff = (datetime.now(timezone.utc) - older_than).isoformat()
        # Find doc_ids to hard-delete first so we can also clean their
        # vectors (vec0 doesn't have ON DELETE CASCADE because it's a
        # virtual table; we manage it manually here).
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
            "DELETE FROM documents WHERE deleted_at IS NOT NULL AND deleted_at < ?", (cutoff,)
        )
        return cur.rowcount

    def reindex(self) -> None:
        """Rebuild the FTS5 index from scratch. Use after :meth:`doctor`
        reports FTS drift, or after bulk-importing outside :meth:`import_many`."""
        with self._txn() as cur:
            cur.execute("INSERT INTO docs_fts(docs_fts) VALUES('rebuild')")

    # ---- embeddings (vec0) ----------------------------------------------

    def _index_embedding(self, doc: Document) -> None:
        """Compute and store the embedding for ``doc``.

        Silently no-ops when the embedder is disabled (``dim == 0``) or
        when the embedder raises. Embedding errors must never break the
        lexical CRUD path; the FTS indexes already have the document.
        """
        emb = getattr(self, "_embedder", None)
        if emb is None or not getattr(emb, "enabled", False):
            return
        try:
            text = f"{doc.title}\n\n{doc.body}".strip()
            vector = emb.embed(text)
        except Exception as e:  # noqa: BLE001 — best-effort
            import logging
            logging.getLogger("kb_mcp_lite").warning(
                "embedding failed for %s: %s", doc.id, e
            )
            return
        try:
            from sqlite_vec import serialize_float32
        except ImportError:
            return
        # Discard any cached vec connection so it gets rebuilt with
        # the embedder's actual dim. (The first embed() call may have
        # lazily probed the dim and the cached conn was built with a
        # default.)
        self._vec_conn = None
        vec_conn = self._vec_conn_lazy()
        if vec_conn is None:
            return
        try:
            vec_conn.execute(
                "INSERT OR REPLACE INTO docs_vec(rowid, embedding) "
                "VALUES ((SELECT rowid FROM documents WHERE id = ?), ?)",
                (doc.id, serialize_float32(vector)),
            )
        except Exception as e:  # noqa: BLE001
            import logging
            logging.getLogger("kb_mcp_lite").debug(
                "docs_vec write skipped for %s: %s", doc.id, e
            )

    def _remove_embedding(self, doc_id: str) -> None:
        vec_conn = self._vec_conn_lazy()
        if vec_conn is None:
            return
        try:
            vec_conn.execute(
                "DELETE FROM docs_vec WHERE rowid = "
                "(SELECT rowid FROM documents WHERE id = ?)",
                (doc_id,),
            )
        except Exception:  # noqa: BLE001
            pass

    def _vec_conn_lazy(self):
        """Open the vec0 side connection on first need; cache it.

        Returns ``None`` if vec0 cannot be loaded on this platform.
        The side connection uses the same DB file; SQLite WAL mode
        serialises writes across all open connections, so this is safe.

        The vec0 table is created with the embedder's reported dim on
        first use. If a previously-saved table has a different dim, the
        side connection will fail at INSERT/query time and this method
        will return ``None`` — call :meth:`reindex_embeddings` after
        switching models to rebuild the table.
        """
        if self._vec_conn is not None:
            return self._vec_conn if self._vec_conn is not False else None
        emb = getattr(self, "_embedder", None)
        if emb is None or not getattr(emb, "enabled", False):
            return None
        try:
            conn = _make_sqlite_connection(str(self._path))
        except Exception as e:  # noqa: BLE001
            import logging
            logging.getLogger("kb_mcp_lite").debug("vec0 connection not available: %s", e)
            self._vec_conn = False  # sentinel: tried, failed; don't retry
            return None

        # Determine the dim to use. Default 1536 (OpenAI ada / text-embedding-3
        # / most BGE-base / M3E-base models).
        dim = getattr(emb, "dim", 0) or 1536
        # Best-effort: try creating the vec0 table if it doesn't exist
        # yet (only needed if the migration 0003 was skipped).
        try:
            conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS docs_vec USING vec0("
                f"embedding float[{dim}] distance_metric=cosine)"
            )
        except Exception as e:  # noqa: BLE001
            import logging
            logging.getLogger("kb_mcp_lite").debug("docs_vec table unavailable: %s", e)
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._vec_conn = False
            return None
        self._vec_conn = conn
        # Don't copy the main conn's row factory. pysqlite3's Cursor
        # can't be wrapped by stdlib sqlite3.Row, and the embedding
        # query is small enough that we parse rows positionally in
        # _search_semantic. Set the flag so the consumer knows.
        try:
            conn.execute("PRAGMA foreign_keys=ON")
        except Exception:  # noqa: BLE001
            pass
        self._vec_row_is_tuple = True
        return conn

    def reindex_embeddings(self) -> int:
        """Recompute embeddings for all active documents.

        Returns the number of documents re-embedded. Used by
        ``kb embed --rebuild`` after switching embedding models, or to
        backfill vectors that were skipped because the embedder was
        not configured at write time.
        """
        emb = getattr(self, "_embedder", None)
        if emb is None or not getattr(emb, "enabled", False):
            raise ValidationError("embedder not configured; cannot reindex")
        rows = self._conn.execute(
            "SELECT id, title, body FROM documents WHERE deleted_at IS NULL"
        ).fetchall()
        n = 0
        for r in rows:
            self._index_embedding(
                Document(
                    id=r["id"],
                    type="(unknown)",  # not used for embedding
                    title=r["title"],
                    body=r["body"],
                )
            )
            n += 1
        return n


__all__ = ["SqliteStore"]
