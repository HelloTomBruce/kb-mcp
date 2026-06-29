"""SQLite implementation of the :class:`~kb_mcp_lite.store.Store` Protocol.

Threading: a single ``SqliteStore`` instance is **not** thread-safe; use
one per thread or serialise calls. Multi-process access to the same
DB file is supported via WAL mode.

Soft delete: :meth:`delete` sets ``deleted_at``. Reads filter
``deleted_at IS NULL``. :meth:`prune` hard-deletes after a grace period.

Failure modes: every method either returns the documented value or
raises one of the documented exceptions from :mod:`kb_mcp_lite.schema`.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sqlite3 as _stdlib_sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, List

from kb_mcp_lite.migrations import apply_migrations
from kb_mcp_lite.schema import (
    Document,
    DuplicateError,
    ImportReport,
    IntegrityError,
    Link,
    NotFoundError,
    ValidationError,
)
from kb_mcp_lite.store.search import SearchMixin
from kb_mcp_lite.store.versioning import VersioningMixin
from kb_mcp_lite.store.embedding import EmbeddingMixin
from kb_mcp_lite.store.maintenance import MaintenanceMixin


def _make_sqlite_connection(path: str):
    """Open a sqlite3 connection that supports vec0 if possible."""
    try:
        import pysqlite3 as _psql

        conn = _psql.connect(path, isolation_level=None)
        conn.enable_load_extension(True)
        _try_load_vec0(conn)
        return conn
    except ImportError:
        pass
    return _stdlib_sqlite3.connect(path, isolation_level=None)


def _try_load_vec0(conn) -> None:
    """Best-effort load of the vec0 SQLite extension. No-op on failure."""
    import logging

    log = logging.getLogger("kb_mcp_lite")
    try:
        import sqlite_vec

        sqlite_vec.load(conn)
    except Exception as e:
        log.debug("vec0 extension not loaded (%s); semantic search disabled", e)


_UPDATEABLE_FIELDS = frozenset({"title", "body", "tags", "source", "aliases"})
_DEFAULT_ACTOR = "admin"


class SqliteStore(SearchMixin, VersioningMixin, EmbeddingMixin, MaintenanceMixin):
    """SQLite-backed :class:`~kb_mcp_lite.store.Store` implementation."""

    def __init__(
        self,
        db_path: Path | str,
        embedder: object | None = None,
    ) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = _stdlib_sqlite3.connect(str(self._path), isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(self._conn)
        if embedder is None:
            from kb_mcp_lite.embedder import make_embedder

            embedder = make_embedder()
        self._embedder = embedder
        self._vec_conn = None

    # ---- context manager + close ---------------------------------------

    def __enter__(self) -> "SqliteStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.ProgrammingError:
            pass

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
        return Document.model_construct(**d)

    def _row_to_link(self, row: sqlite3.Row) -> Link:
        return Link(
            from_id=row["from_id"],
            to_id=row["to_id"],
            rel=row["rel"],
            created_at=self._parse_dt(row["created_at"]) or datetime.now(timezone.utc),
        )

    # ---- aliases --------------------------------------------------------

    def _write_aliases(self, doc_id: str, aliases: list[str]) -> None:
        self._conn.execute("DELETE FROM doc_aliases WHERE doc_id = ?", (doc_id,))
        if not aliases:
            return
        now = self._now_iso()
        for alias in aliases:
            if not alias:
                continue
            try:
                self._conn.execute(
                    "INSERT INTO doc_aliases (alias, doc_id, created_at) VALUES (?, ?, ?)",
                    (alias, doc_id, now),
                )
            except sqlite3.IntegrityError:
                continue

    def _read_aliases(self, doc_id: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT alias FROM doc_aliases WHERE doc_id = ? ORDER BY alias",
            (doc_id,),
        ).fetchall()
        return [r["alias"] for r in rows]

    def resolve_alias(self, alias: str) -> str | None:
        row = self._conn.execute(
            "SELECT doc_id FROM doc_aliases WHERE alias = ?", (alias,)
        ).fetchone()
        return row["doc_id"] if row else None

    # ---- read -----------------------------------------------------------

    def get(self, doc_id: str, include_deleted: bool = False) -> Document:
        """Fetch a document by id. Also resolves aliases."""
        sql = "SELECT * FROM documents WHERE id = ?"
        if not include_deleted:
            sql += " AND deleted_at IS NULL"
        row = self._conn.execute(sql, (doc_id,)).fetchone()
        if row is None:
            resolved = self.resolve_alias(doc_id)
            if resolved:
                return self.get(resolved, include_deleted=include_deleted)
            raise NotFoundError(doc_id)
        return self._row_to_doc(row)

    def list(
        self,
        type: str | None = None,
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

    # ---- write ----------------------------------------------------------

    def add(self, doc: Document) -> str:
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
                self._record_doc_version(cur, doc, action="create")
                self._record_audit(
                    cur,
                    entity_type="document",
                    entity_id=doc.id,
                    action="create",
                    detail={"title": doc.title, "type": doc.type},
                )
        except sqlite3.IntegrityError as e:
            msg = str(e)
            if "UNIQUE constraint failed: documents.id" in msg or "PRIMARY KEY" in msg:
                raise DuplicateError(doc.id) from e
            raise IntegrityError(msg) from e
        self._write_aliases(doc.id, doc.aliases)
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
            self._record_doc_version(cur, new_doc, action="update")
            self._record_audit(
                cur,
                entity_type="document",
                entity_id=doc_id,
                action="update",
                detail={"fields": sorted(fields.keys())},
            )
        if "aliases" in fields:
            self._write_aliases(doc_id, fields["aliases"])
        if "title" in fields or "body" in fields:
            self._index_embedding(new_doc)
        return self.get(doc_id)

    def delete(self, doc_id: str) -> None:
        active = self._conn.execute(
            "SELECT 1 FROM documents WHERE id = ? AND deleted_at IS NULL",
            (doc_id,),
        ).fetchone()
        if active is None:
            exists = self._conn.execute(
                "SELECT 1 FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()
            if exists is None:
                raise NotFoundError(doc_id)
            return
        now = self._now_iso()
        doc = self.get(doc_id, include_deleted=True)
        deleted_doc = doc.model_copy(update={"deleted_at": self._parse_dt(now)})
        with self._txn() as cur:
            cur.execute(
                "UPDATE documents SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
                (now, doc_id),
            )
            self._record_doc_version(cur, deleted_doc, action="delete")
            self._record_audit(
                cur,
                entity_type="document",
                entity_id=doc_id,
                action="delete",
                detail={"title": doc.title, "type": doc.type},
            )
        self._remove_embedding(doc_id)

    # ---- links ----------------------------------------------------------

    def link(self, from_id: str, to_id: str, rel: str = "relates-to") -> Link:
        rel = (rel or "").strip()
        if not rel:
            raise ValidationError("rel must be non-empty")
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]*$", rel):
            raise ValidationError(f"rel must match ^[A-Za-z0-9][A-Za-z0-9_-]*$ (got {rel!r})")
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
            self._record_audit(
                cur,
                entity_type="link",
                entity_id=f"{from_id}|{to_id}|{rel}",
                action="create",
                detail={"from_id": from_id, "to_id": to_id, "rel": rel},
            )
        assert row is not None
        return self._row_to_link(row)

    def unlink(self, from_id: str, to_id: str, rel: str | None = None) -> int:
        sql = "DELETE FROM links WHERE from_id = ? AND to_id = ?"
        params: List[object] = [from_id, to_id]
        if rel is not None:
            sql += " AND rel = ?"
            params.append(rel)
        with self._txn() as cur:
            cur.execute(sql, params)
            removed = cur.rowcount
            if removed:
                self._record_audit(
                    cur,
                    entity_type="link",
                    entity_id=f"{from_id}|{to_id}|{rel or '*'}",
                    action="delete",
                    detail={"from_id": from_id, "to_id": to_id, "rel": rel},
                )
            return removed

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
                        self.update(
                            row["id"],
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


__all__ = ["SqliteStore"]
