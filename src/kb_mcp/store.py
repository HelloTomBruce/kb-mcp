"""Store Protocol — the interface every storage backend must implement.

This module defines the **contract** only. The concrete SQLite
implementation lives in :mod:`kb_mcp.store.sqlite`. Tests against this
Protocol are in ``tests/test_store_contract.py``.

Why a Protocol
--------------

The Store is the single integration point between kb-mcp and its data
layer. By depending on a Protocol (PEP 544 structural subtyping) instead
of a concrete class:

- the CLI, MCP server, and Markdown I/O modules can be developed and
  unit-tested against a ``StubStore`` (in-memory dict) without touching
  SQLite;
- alternative backends (Postgres, in-memory, HTTP) can be added later by
  implementing the same Protocol;
- the E2E tests in Wave 2 swap implementations to exercise both paths.

Concurrency
------------

The Protocol does **not** promise thread safety. v0.1 uses SQLite in WAL
mode with one connection per process; multi-process access (e.g. two
``kb`` CLI invocations against the same DB) is supported because SQLite
WAL serialises writers, but a single process must serialise its own
calls. The MCP server and CLI are both single-threaded; this is not a
concern for v0.1.

Soft delete
-----------

``delete()`` sets ``deleted_at`` rather than removing the row. ``get()``,
``list()``, ``search()`` all filter out soft-deleted rows. ``prune()``
hard-deletes soft-deleted rows older than a configurable grace period.
This makes ``kb import`` idempotent and recoverable.

Failure modes
-------------

Every method either:

- returns the documented value (no exception on "not found" for
  ``list`` / ``search``);
- raises one of the exceptions from :mod:`kb_mcp.schema` (``NotFoundError``,
  ``DuplicateError``, ``ValidationError``, ``IntegrityError``).

Callers MUST handle these. Callers MUST NOT catch the generic
``Exception`` to keep error semantics intact.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Iterable, Protocol, runtime_checkable

from kb_mcp.schema import (
    Document,
    DoctorReport,
    ImportReport,
    Link,
    SearchHit,
)


@runtime_checkable
class Store(Protocol):
    """The storage interface every backend must implement.

    See module docstring for thread-safety and soft-delete semantics.
    """

    # ---- write ----------------------------------------------------------

    def add(self, doc: Document) -> str:
        """Insert a new document. Returns the stored id.

        Implementations MAY auto-generate the id when ``doc.id`` is empty;
        the canonical generator is :func:`kb_mcp.schema.make_id`.

        Raises:
            DuplicateError: if a document with the same id (or, where the
                backend enforces it, same ``(type, title)``) already
                exists.
            ValidationError: if any field fails pydantic validation.
        """
        ...

    def update(self, doc_id: str, **fields: object) -> Document:
        """Patch fields on an existing document and return the updated
        instance.

        ``updated_at`` is set to the current UTC time. ``id``, ``type``,
        ``created_at`` cannot be changed via this method.

        Raises:
            NotFoundError: if ``doc_id`` does not exist.
            ValidationError: if any new field value fails validation.
        """
        ...

    def delete(self, doc_id: str) -> None:
        """Soft-delete a document. Sets ``deleted_at``.

        Idempotent: deleting an already-deleted document is a no-op.

        Raises:
            NotFoundError: if ``doc_id`` does not exist (active or deleted).
        """
        ...

    # ---- read -----------------------------------------------------------

    def get(self, doc_id: str, include_deleted: bool = False) -> Document:
        """Fetch a single document by id.

        Raises:
            NotFoundError: if the id is unknown.
        """
        ...

    def list(
        self,
        type: str | None = None,
        tags: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
        include_deleted: bool = False,
    ) -> list[Document]:
        """List documents, sorted by ``updated_at DESC``.

        ``tags`` filters to documents carrying **all** listed tags (AND).

        ``limit`` is capped at 1000 to keep callers honest. ``offset`` is
        for pagination; callers needing more should switch to
        :meth:`search`.
        """
        ...

    def search(
        self,
        query: str,
        type: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> list[SearchHit]:
        """Full-text search via the backend's FTS / equivalent engine.

        Returns ranked results with snippets. Empty query returns ``[]``.

        ``limit`` is capped at 100.

        Raises:
            ValidationError: if ``query`` is empty after stripping or
                ``limit`` is out of range.
        """
        ...

    # ---- links ----------------------------------------------------------

    def link(self, from_id: str, to_id: str, rel: str = "relates-to") -> Link:
        """Create a typed edge. Idempotent on ``(from_id, to_id, rel)``.

        Returns the canonical :class:`Link` (with ``created_at`` populated).

        Raises:
            NotFoundError: if either endpoint id does not exist.
            ValidationError: if ``rel`` is empty or contains illegal chars.
        """
        ...

    def unlink(
        self,
        from_id: str,
        to_id: str,
        rel: str | None = None,
    ) -> int:
        """Remove edges. If ``rel`` is None, all edges from
        ``(from_id, to_id)`` are removed. Returns count removed."""
        ...

    def backlinks(self, doc_id: str) -> list[Link]:
        """Return all edges pointing **to** ``doc_id`` (i.e. where
        ``to_id == doc_id``)."""
        ...

    def outlinks(self, doc_id: str) -> list[Link]:
        """Return all edges originating from ``doc_id``."""
        ...

    # ---- bulk / io ------------------------------------------------------

    def import_many(self, docs: Iterable[Document]) -> ImportReport:
        """Bulk insert/update. Backends SHOULD batch this in a single
        transaction.

        Update-by-source semantics: if a doc has ``source`` set and a
        document with that source already exists, it is updated rather
        than inserted (idempotent re-import).
        """
        ...

    def export_all(self, include_deleted: bool = False) -> list[Document]:
        """Return every document. Used by ``kb export``."""
        ...

    # ---- maintenance ----------------------------------------------------

    def doctor(self) -> DoctorReport:
        """Run health checks. Always returns a report; never raises.

        Checks include: PRAGMA integrity_check, FTS row count == documents
        row count, no orphan links, all docs have non-empty type/title."""
        ...

    def prune(self, older_than: timedelta = timedelta(days=30)) -> int:
        """Hard-delete soft-deleted documents whose ``deleted_at`` is
        older than the cutoff. Returns count removed."""
        ...

    # ---- lifecycle ------------------------------------------------------

    def close(self) -> None:
        """Release resources. Idempotent. Safe to call on error paths."""
        ...

    def __enter__(self) -> "Store": ...
    def __exit__(self, *exc: object) -> None: ...


__all__ = ["Store"]
