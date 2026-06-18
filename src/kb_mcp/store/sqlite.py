"""SQLite implementation of the :class:`~kb_mcp.store.Store` Protocol.

Threading: a single ``SqliteStore`` instance is **not** thread-safe; use
one per thread or serialise calls. Multi-process access to the same
DB file is supported via WAL mode.

Soft delete: :meth:`delete` sets ``deleted_at``. Reads filter
``deleted_at IS NULL``. :meth:`prune` hard-deletes after a grace period.

Failure modes: every method either returns the documented value or
raises one of the documented exceptions from :mod:`kb_mcp.schema`.
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator

from kb_mcp.migrations import apply_migrations
from kb_mcp.schema import (
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

# Fields that ``update`` is allowed to mutate. Anything else raises
# ``ValidationError``. ``id``, ``type``, ``created_at``, ``updated_at``,
# and ``deleted_at`` are managed by the store and cannot be changed.
_UPDATEABLE_FIELDS = frozenset({"title", "body", "tags", "source"})


class SqliteStore:
    """SQLite-backed :class:`~kb_mcp.store.Store` implementation."""

    def __init__(self, db_path: Path | str) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        # WAL allows concurrent readers while a writer is active.
        self._conn.execute("PRAGMA journal_mode=WAL")
        # FK enforcement is per-connection; must be set every time.
        self._conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(self._conn)

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
            from kb_mcp.schema import make_id

            doc = doc.model_copy(update={"id": make_id(doc.type, doc.title)})
        elif not re.match(r"^[a-z0-9][a-z0-9/_-]*$", doc.id):
            raise ValidationError(
                f"id must match ^[a-z0-9][a-z0-9/_-]*$ (got {doc.id!r})"
            )

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
                    raise ValidationError(f"tags must be list[str] or comma string (got {type(v).__name__})")
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
        type: str | None = None,  # noqa: A002  (keep Store signature)
        tags: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
        include_deleted: bool = False,
    ) -> list[Document]:
        if limit < 1 or limit > 1000:
            raise ValidationError("limit must be in 1..1000")
        if offset < 0:
            raise ValidationError("offset must be >= 0")

        sql = "SELECT * FROM documents WHERE 1=1"
        params: list[object] = []
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
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> list[SearchHit]:
        query = (query or "").strip()
        if not query:
            raise ValidationError("query must not be empty")
        if limit < 1 or limit > 100:
            raise ValidationError("limit must be in 1..100")

        fts_q = self._escape_fts(query)
        sql = """
            SELECT d.*,
                   snippet(docs_fts, 1, '<b>', '</b>', '…', 12) AS snip,
                   bm25(docs_fts) AS score
            FROM docs_fts
            JOIN documents d ON d.rowid = docs_fts.rowid
            WHERE docs_fts MATCH ?
              AND d.deleted_at IS NULL
        """
        params: list[object] = [fts_q]
        if type:
            sql += " AND d.type = ?"
            params.append(type)
        sql += " ORDER BY score LIMIT ?"
        params.append(limit)

        try:
            rows = self._conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as e:
            raise ValidationError(f"invalid FTS query {query!r}: {e}") from e

        hits: list[SearchHit] = []
        for r in rows:
            d = dict(r)
            snippet_text = d.pop("snip", "") or ""
            score = float(d.pop("score", 0.0))
            doc = self._row_to_doc(sqlite3.Row(d)) if False else self._row_to_doc_dict(d)
            hits.append(SearchHit(doc=doc, snippet=snippet_text, score=score))

        if tags:
            wanted = set(tags)
            hits = [h for h in hits if wanted.issubset(set(h.doc.tags))]
        return hits

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
        """Wrap each whitespace-separated token in double quotes so that
        FTS5 special characters are treated literally. ``"`` is doubled."""
        tokens: list[str] = []
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
            raise ValidationError(
                f"rel must match ^[A-Za-z0-9][A-Za-z0-9_-]*$ (got {rel!r})"
            )
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
        params: list[object] = [from_id, to_id]
        if rel is not None:
            sql += " AND rel = ?"
            params.append(rel)
        cur = self._conn.execute(sql, params)
        return cur.rowcount

    def backlinks(self, doc_id: str) -> list[Link]:
        rows = self._conn.execute(
            "SELECT from_id, to_id, rel, created_at FROM links WHERE to_id = ? ORDER BY created_at",
            (doc_id,),
        ).fetchall()
        return [self._row_to_link(r) for r in rows]

    def outlinks(self, doc_id: str) -> list[Link]:
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
                            **{k: v for k, v in doc.model_dump().items()
                               if k in _UPDATEABLE_FIELDS},
                        )
                        report.updated += 1
                        continue
                self.add(doc)
                report.inserted += 1
            except (DuplicateError, ValidationError) as e:
                report.errors.append(f"{doc.id or doc.title}: {e}")
                report.skipped += 1
        return report

    def export_all(self, include_deleted: bool = False) -> list[Document]:
        sql = "SELECT * FROM documents"
        if not include_deleted:
            sql += " WHERE deleted_at IS NULL"
        sql += " ORDER BY id"
        rows = self._conn.execute(sql).fetchall()
        return [self._row_to_doc(r) for r in rows]

    # ---- maintenance ----------------------------------------------------

    def doctor(self) -> DoctorReport:
        checks: list[DoctorCheck] = []

        # 1. PRAGMA integrity_check
        row = self._conn.execute("PRAGMA integrity_check").fetchone()
        ok = bool(row) and row[0] == "ok"
        checks.append(DoctorCheck(name="integrity_check", ok=ok, detail=str(row[0]) if row else "no result"))

        # 2. FTS row count == active document count
        n_docs = self._conn.execute(
            "SELECT COUNT(*) FROM documents WHERE deleted_at IS NULL"
        ).fetchone()[0]
        n_fts = self._conn.execute("SELECT COUNT(*) FROM docs_fts").fetchone()[0]
        checks.append(
            DoctorCheck(
                name="fts_sync",
                ok=n_docs == n_fts,
                detail=f"active_docs={n_docs} fts_rows={n_fts}",
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
        cur = self._conn.execute(
            "DELETE FROM documents WHERE deleted_at IS NOT NULL AND deleted_at < ?",
            (cutoff,),
        )
        return cur.rowcount

    def reindex(self) -> None:
        """Rebuild the FTS5 index from scratch. Use after :meth:`doctor`
        reports FTS drift, or after bulk-importing outside :meth:`import_many`."""
        with self._txn() as cur:
            cur.execute("INSERT INTO docs_fts(docs_fts) VALUES('rebuild')")


__all__ = ["SqliteStore"]
