"""SQLite storage implementation."""
from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple, TypeVar, Iterator

from kb_mcp_lite.schema import (
    Document,
    Link,
    SearchHit,
    DoctorReport,
    ImportReport,
    NotFoundError,
    DuplicateError,
    ValidationError,
)
from kb_mcp_lite.store.maintenance import MaintenanceMixin
from kb_mcp_lite.store.search import SearchMixin
from kb_mcp_lite.store.versioning import VersioningMixin
from kb_mcp_lite.store.embedding import EmbeddingMixin


T = TypeVar("T")


def _sqlite_row_factory(cursor: sqlite3.Cursor, row: Tuple[Any, ...]) -> sqlite3.Row:
    return sqlite3.Row(cursor, row)


def _make_sqlite_connection(db_path: str) -> sqlite3.Connection:
    """Open a sqlite3 connection that supports vec0 if possible."""
    try:
        import pysqlite3 as _psql
        conn = _psql.connect(db_path, isolation_level=None)
        conn.enable_load_extension(True)
        _try_load_vec0(conn)
        return conn
    except ImportError:
        pass
    try:
        import sqlite_vec
        conn = sqlite3.connect(db_path)
        sqlite_vec.load(conn)
        return conn
    except ImportError:
        pass
    return sqlite3.connect(db_path)


def _try_load_vec0(conn: sqlite3.Connection) -> None:
    """Best-effort load of vec0 extension."""
    import logging
    try:
        import sqlite_vec
        sqlite_vec.load(conn)
    except Exception as e:
        logging.getLogger("kb_mcp_lite").debug("vec0 not loaded: %s", e)


class SqliteStore(MaintenanceMixin, SearchMixin, VersioningMixin, EmbeddingMixin):
    """SQLite-based storage implementation.
    
    Combines functionality from multiple mixins:
    - MaintenanceMixin: Health checks, stats, pruning, reindexing
    - SearchMixin: Full-text and semantic search
    - VersioningMixin: Document version history, diff, restore
    - EmbeddingMixin: Vector storage and semantic search support
    """

    def __init__(self, db_path: str, embedder: Any | None = None) -> None:
        self.db_path = db_path
        self._conn = self._open_connection()
        self._vec_conn = None
        self._init_db()
        if embedder is None:
            from kb_mcp_lite.embedder import make_embedder
            embedder = make_embedder()
        self._embedder = embedder

    def _open_connection(self) -> sqlite3.Connection:
        """Open a connection to the SQLite database."""
        dir_path = os.path.dirname(self.db_path)
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)
        
        conn = sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = _sqlite_row_factory
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA temp_store = MEMORY")
        return conn

    def _init_db(self) -> None:
        """Initialize database schema and run migrations."""
        from kb_mcp_lite.migrations import apply_migrations
        apply_migrations(self._conn)
        self._conn.commit()

    @property
    def path(self):
        """Return the path to the database file (compatibility alias for db_path)."""
        return self.db_path

    def init(self) -> None:
        """Initialize a new empty knowledge base."""
        # Already handled by migrations
        pass

    def close(self) -> None:
        """Close the database connection."""
        try:
            self._conn.close()
        except (sqlite3.ProgrammingError, Exception):
            pass

    def __enter__(self) -> "SqliteStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def _txn(self) -> Iterator[sqlite3.Cursor]:
        """Start a transaction and yield a cursor. Commits on success, rolls back on error."""
        cur = self._conn.cursor()
        try:
            yield cur
            self._conn.commit()
        except Exception:
            try:
                self._conn.rollback()
            except sqlite3.OperationalError:
                pass
            raise
        finally:
            cur.close()

    def _row_to_doc(self, row: Dict[str, Any]) -> Document:
        """Convert a database row to a Document object."""
        return Document.from_row(row)

    @staticmethod
    def _row_to_link(row: Dict[str, Any]) -> Link:
        """Convert a database row to a Link object."""
        return Link(**row)

    @staticmethod
    def _now_iso() -> str:
        """Return the current UTC time as an ISO-8601 string."""
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        """Parse an ISO-8601 string to datetime, or return None."""
        if not value:
            return None
        s = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None

    # ---- read operations ------------------------------------------------------

    def get(self, doc_id: str, include_deleted: bool = False) -> Document:
        """Get a document by ID.
        
        Raises NotFoundError if the document doesn't exist.
        """
        sql = "SELECT * FROM documents WHERE id = ?"
        params: List[Any] = [doc_id]
        if not include_deleted:
            sql += " AND deleted_at IS NULL"
        
        row = self._conn.execute(sql, params).fetchone()
        if not row:
            # Try resolving alias via doc_aliases table
            alias_row = self._conn.execute(
                "SELECT doc_id FROM doc_aliases WHERE alias = ?", (doc_id,)
            ).fetchone()
            if alias_row:
                resolved = alias_row["doc_id"]
                return self.get(resolved, include_deleted=include_deleted)
            raise NotFoundError(doc_id)
        
        doc = self._row_to_doc(row)
        # Fetch aliases from doc_aliases
        aliases_rows = self._conn.execute(
            "SELECT alias FROM doc_aliases WHERE doc_id = ?", (doc.id,)
        ).fetchall()
        doc.aliases = [r["alias"] for r in aliases_rows]
        return doc

    def list(
        self,
        type: str | None = None,
        tags: List[str] | None = None,
        link_to: str | None = None,
        link_from: str | None = None,
        limit: int = 100,
        offset: int = 0,
        include_deleted: bool = False,
    ) -> List[Document]:
        """List documents with optional filtering.
        
        Args:
            type: Filter by document type
            tags: Filter by tags (all tags must be present)
            link_to: Filter documents that link to the given document ID
            link_from: Filter documents that are linked from the given document ID
            limit: Maximum number of results to return (1-1000)
            offset: Number of results to skip for pagination
            include_deleted: Include soft-deleted documents in results
        """
        if limit < 1 or limit > 1000:
            raise ValidationError("limit must be in 1..1000")
        if offset < 0:
            raise ValidationError("offset must be >= 0")
        
        sql_parts = ["SELECT DISTINCT d.* FROM documents d"]
        params: List[object] = []
        joins = []
        conditions = ["1=1"]
        
        if not include_deleted:
            conditions.append("d.deleted_at IS NULL")
        
        if type:
            conditions.append("d.type = ?")
            params.append(type)
        
        if link_to:
            joins.append("LEFT JOIN links l_to ON l_to.from_id = d.id")
            conditions.append("l_to.to_id = ?")
            params.append(link_to)
        
        if link_from:
            joins.append("LEFT JOIN links l_from ON l_from.to_id = d.id")
            conditions.append("l_from.from_id = ?")
            params.append(link_from)
        
        if joins:
            sql_parts.extend(joins)
        
        sql_parts.append("WHERE " + " AND ".join(conditions))
        sql_parts.append("ORDER BY d.updated_at DESC, d.id ASC LIMIT ? OFFSET ?")
        params.extend([limit, offset])
        
        sql = " ".join(sql_parts)
        rows = self._conn.execute(sql, params).fetchall()
        docs = [self._row_to_doc(r) for r in rows]
        
        if tags:
            wanted = set(tags)
            docs = [d for d in docs if wanted.issubset(set(d.tags))]
        
        return docs

    # ---- write operations ------------------------------------------------------

    def add(self, doc: Document) -> str:
        """Add a new document.
        
        Returns the generated document ID.
        Raises DuplicateError if a document with the same (type, title) already exists.
        Raises ValidationError if the ID format is invalid.
        """
        # Generate ID if not provided
        if not doc.id:
            doc.id = make_id(doc.type, doc.title)
        elif not re.match(r"^[a-z0-9][a-z0-9/_-]*$", doc.id):
            raise ValidationError(f"id must match ^[a-z0-9][a-z0-9/_-]*$ (got {doc.id!r})")
        
        # Check for duplicate
        try:
            existing = self.get(doc.id, include_deleted=True)
            raise DuplicateError(doc.id, existing.id)
        except NotFoundError:
            pass

        now = datetime.now(timezone.utc)
        doc.created_at = now
        doc.updated_at = now

        with self._txn() as cur:
            cur.execute(
                """
                INSERT INTO documents (
                    id, type, title, body, tags, source, created_at, updated_at, deleted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc.id,
                    doc.type,
                    doc.title,
                    doc.body,
                    json.dumps(doc.tags, ensure_ascii=False),
                    doc.source,
                    doc.created_at.isoformat(),
                    doc.updated_at.isoformat(),
                    doc.deleted_at.isoformat() if doc.deleted_at else None,
                ),
            )
            # Add to FTS index
            cur.execute(
                """
                INSERT INTO docs_fts (rowid, title, body)
                VALUES (last_insert_rowid(), ?, ?)
                """,
                (doc.title, doc.body),
            )
            # Create version entry
            self._record_doc_version(cur, doc, action="create")
            self._record_audit(
                cur,
                entity_type="document",
                entity_id=doc.id,
                action="create",
                detail={"title": doc.title, "type": doc.type},
            )
            # Insert aliases
            if doc.aliases:
                now_str = now.isoformat()
                for alias in doc.aliases:
                    cur.execute(
                        """
                        INSERT INTO doc_aliases (alias, doc_id, created_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT (alias) DO NOTHING
                        """,
                        (alias, doc.id, now_str),
                    )

        self._index_embedding(doc)
        return doc.id

    def update(self, doc_id: str, **kwargs: Any) -> Document:
        """Update fields on an existing document.
        
        Supported fields: title, body, tags, source, aliases.
        Raises NotFoundError if the document doesn't exist.
        Raises ValidationError if disallowed fields are passed or no fields given.
        """
        doc = self.get(doc_id)
        allowed_fields = {"title", "body", "tags", "source", "aliases"}
        bad = set(kwargs.keys()) - allowed_fields
        if bad:
            raise ValidationError(f"cannot update fields: {sorted(bad)}")
        if not kwargs:
            raise ValidationError("update requires at least one field")
        updates = {k: v for k, v in kwargs.items() if k in allowed_fields}

        # Update fields
        for k, v in updates.items():
            if k == "tags":
                if isinstance(v, str):
                    doc.tags = [t.strip() for t in v.split(",") if t.strip()]
                else:
                    doc.tags = list(v)
            else:
                setattr(doc, k, v)

        doc.updated_at = datetime.now(timezone.utc)

        with self._txn() as cur:
            cur.execute(
                """
                UPDATE documents
                SET title = ?, body = ?, tags = ?, source = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    doc.title,
                    doc.body,
                    json.dumps(doc.tags, ensure_ascii=False),
                    doc.source,
                    doc.updated_at.isoformat(),
                    doc.id,
                ),
            )
            # Update FTS index
            cur.execute(
                """
                UPDATE docs_fts
                SET title = ?, body = ?
                WHERE rowid = (SELECT rowid FROM documents WHERE id = ?)
                """,
                (doc.title, doc.body, doc.id),
            )
            # Create version entry
            self._record_doc_version(cur, doc, action="update")
            self._record_audit(
                cur,
                entity_type="document",
                entity_id=doc_id,
                action="update",
                detail={"fields": sorted(kwargs.keys())},
            )
            # Update aliases if provided
            if "aliases" in kwargs:
                cur.execute("DELETE FROM doc_aliases WHERE doc_id = ?", (doc.id,))
                if doc.aliases:
                    now_str = datetime.now(timezone.utc).isoformat()
                    for alias in doc.aliases:
                        cur.execute(
                            """
                            INSERT INTO doc_aliases (alias, doc_id, created_at)
                            VALUES (?, ?, ?)
                            ON CONFLICT (alias) DO NOTHING
                            """,
                            (alias, doc.id, now_str),
                        )

        self._index_embedding(doc)
        return doc

    def update_source(self, doc_id: str, source: str | None) -> None:
        """Update only the ``source`` field of a document.

        Unlike :meth:`update`, this does not bump ``updated_at`` and does
        not record a version or audit entry — it exists for the export
        write-back path (see :func:`kb_mcp_lite.md_io.export_dir`), where
        refreshing ``updated_at`` would leave the document newer than the
        file just written and defeat incremental export.

        Raises NotFoundError if the document doesn't exist.
        """
        with self._txn() as cur:
            cur.execute(
                "UPDATE documents SET source = ? WHERE id = ?",
                (source, doc_id),
            )
            if cur.rowcount == 0:
                raise NotFoundError(doc_id)

    def delete(self, doc_id: str) -> None:
        """Soft-delete a document.
        
        Raises NotFoundError if the document doesn't exist.
        Idempotent: deleting an already-deleted doc is a no-op.
        """
        # Check if the document exists and is not already deleted
        try:
            doc = self.get(doc_id)
        except NotFoundError:
            # Check if it exists but is already deleted (idempotent)
            existing = self._conn.execute(
                "SELECT deleted_at FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()
            if existing and existing["deleted_at"] is not None:
                return  # already deleted, no-op
            raise
        
        now = datetime.now(timezone.utc)
        with self._txn() as cur:
            cur.execute(
                "UPDATE documents SET deleted_at = ?, updated_at = ? WHERE id = ?",
                (now.isoformat(), now.isoformat(), doc_id),
            )
            # Create version entry
            self._record_doc_version(cur, doc, action="delete")
            self._record_audit(
                cur,
                entity_type="document",
                entity_id=doc_id,
                action="delete",
                detail={"title": doc.title, "type": doc.type},
            )

        self._remove_embedding(doc_id)

    def restore_deleted(self, doc_id: str) -> Document:
        """Restore a soft-deleted document.
        
        Raises NotFoundError if the document doesn't exist or is not deleted.
        """
        doc = self.get(doc_id, include_deleted=True)
        if not doc.deleted_at:
            raise ValidationError(f"Document {doc_id} is not deleted")
        
        now = datetime.now(timezone.utc)
        doc.deleted_at = None
        doc.updated_at = now

        with self._txn() as cur:
            cur.execute(
                "UPDATE documents SET deleted_at = NULL, updated_at = ? WHERE id = ?",
                (now.isoformat(), doc_id),
            )
            # Create version entry
            self._record_doc_version(cur, doc, action="restore")

        self._index_embedding(doc)
        return doc

    # ---- link operations ------------------------------------------------------

    def link(self, from_id: str, to_id: str, rel: str = "relates-to") -> Link:
        """Create a typed link between two documents.
        
        Raises NotFoundError if either document doesn't exist.
        Raises ValidationError if rel is empty or invalid.
        Returns the created (or existing) Link.
        """
        rel = (rel or "").strip()
        if not rel:
            raise ValidationError("rel must be non-empty")
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]*$", rel):
            raise ValidationError(f"rel must match ^[A-Za-z0-9][A-Za-z0-9_-]*$ (got {rel!r})")
        # Check both documents exist and resolve aliases
        from_doc = self.get(from_id)
        to_doc = self.get(to_id)
        real_from_id = from_doc.id
        real_to_id = to_doc.id

        now = datetime.now(timezone.utc)
        with self._txn() as cur:
            cur.execute(
                """
                INSERT INTO links (from_id, to_id, rel, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (from_id, to_id, rel) DO NOTHING
                """,
                (real_from_id, real_to_id, rel, now.isoformat()),
            )
            # Retrieve the link (either just inserted or existing)
            row = cur.execute(
                "SELECT * FROM links WHERE from_id=? AND to_id=? AND rel=?",
                (real_from_id, real_to_id, rel),
            ).fetchone()
            self._record_audit(
                cur,
                entity_type="link",
                entity_id=f"{from_id}|{to_id}|{rel}",
                action="create",
                detail={"from_id": from_id, "to_id": to_id, "rel": rel},
            )
            
        assert row is not None
        return Link(**row)

    def unlink(self, from_id: str, to_id: str, rel: str | None = None) -> int:
        """Remove a link between two documents.
        
        If rel is specified, only remove links with that relation type.
        Returns the number of removed links.
        """
        with self._txn() as cur:
            if rel:
                cur.execute(
                    "DELETE FROM links WHERE from_id = ? AND to_id = ? AND rel = ?",
                    (from_id, to_id, rel),
                )
            else:
                cur.execute(
                    "DELETE FROM links WHERE from_id = ? AND to_id = ?",
                    (from_id, to_id),
                )
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

    def outgoing_links(self, doc_id: str) -> List[Link]:
        """Get all outgoing links from a document."""
        rows = self._conn.execute(
            "SELECT * FROM links WHERE from_id = ? ORDER BY created_at DESC",
            (doc_id,),
        ).fetchall()
        return [Link(**row) for row in rows]

    def incoming_links(self, doc_id: str) -> List[Link]:
        """Get all incoming links to a document."""
        rows = self._conn.execute(
            "SELECT * FROM links WHERE to_id = ? ORDER BY created_at DESC",
            (doc_id,),
        ).fetchall()
        return [Link(**row) for row in rows]

    # ---- compatibility aliases (backlinks / outlinks) -------------------------

    def backlinks(self, doc_id: str) -> List[Link]:
        """Alias for :meth:`incoming_links`."""
        return self.incoming_links(doc_id)

    def outlinks(self, doc_id: str) -> List[Link]:
        """Alias for :meth:`outgoing_links`."""
        return self.outgoing_links(doc_id)

    # ---- bulk / io ------------------------------------------------------------

    def import_many(self, docs: Iterable[Document]) -> ImportReport:
        """Bulk-import documents. Uses source-based idempotent upsert.
        
        When a document has a ``source`` field, a matching document
        (same source, not deleted) is updated instead of inserted.
        """
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
                            **{k: v for k, v in doc.model_dump().items() if k in {"title", "body", "tags", "source", "aliases"}},
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
        """Export all documents, optionally including soft-deleted ones."""
        sql = "SELECT * FROM documents"
        if not include_deleted:
            sql += " WHERE deleted_at IS NULL"
        sql += " ORDER BY id"
        rows = self._conn.execute(sql).fetchall()
        return [self._row_to_doc(r) for r in rows]


# Import make_id at the end to avoid circular import
from kb_mcp_lite.schema import make_id

__all__ = ["SqliteStore"]
