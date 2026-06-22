"""FastMCP server for kb-mcp (Wave 2A).

Exposes 4 tools over stdio transport (JSON-RPC per MCP spec):

- ``kb_search(query, type?, tags?, limit?)`` → list of search hits
- ``kb_get(id)`` → full document or error
- ``kb_add(type, title, body, tags?, source?)`` → new id or error
- ``kb_link(from_id, to_id, rel?)`` → success (idempotent)

Error codes follow architecture.md § 4.4:

| kb-mcp exception   | MCP code | Meaning          |
|--------------------|----------|------------------|
| ValidationError    | -32602   | Invalid params   |
| NotFoundError      | -32004   |                  |
| DuplicateError     | -32005   |                  |
| IntegrityError     | -32603   | Internal error   |
| Other              | -32603   | Internal error   |

Logging: structured JSON to stderr only; body content is never logged
(privacy NFR-O-2).
"""

# NOTE: We intentionally do NOT use `from __future__ import annotations` here.
# FastMCP 1.12's Tool.from_function() calls issubclass() on parameter
# annotations at runtime. PEP-563 (postponed annotations) would turn
# every annotation into a string, causing issubclass() to crash with
# "TypeError: issubclass() arg 1 must be a class".

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, List, Optional

from pydantic import BaseModel, Field

from kb_mcp.schema import (
    Document,
    DuplicateError,
    IntegrityError,
    NotFoundError,
    SearchHit,
    ValidationError,
    make_id,
)
from kb_mcp.store.sqlite import SqliteStore

# ---------------------------------------------------------------------------
# Pydantic input models (architecture.md § 4.4)
# ---------------------------------------------------------------------------


class KbSearchInput(BaseModel):
    query: str = Field(min_length=1)
    type: str | None = None
    tags: List[str] | None = None
    limit: int = Field(default=10, ge=1, le=100)
    mode: str = Field(default="hybrid", pattern="^(lexical|fuzzy|hybrid)$")


class KbGetInput(BaseModel):
    id: str = Field(min_length=1)


class KbAddInput(BaseModel):
    type: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=512)
    body: str = Field(default="", max_length=1_000_000)
    tags: List[str] | None = None
    source: str | None = None


class KbLinkInput(BaseModel):
    from_id: str = Field(min_length=1)
    to_id: str = Field(min_length=1)
    rel: str = Field(default="relates-to", min_length=1, max_length=64)


class KbListInput(BaseModel):
    type: str | None = None
    tags: List[str] | None = None
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)
    include_deleted: bool = False


class KbUpdateInput(BaseModel):
    id: str = Field(min_length=1)
    title: str | None = Field(default=None, min_length=1, max_length=512)
    body: str | None = Field(default=None, max_length=1_000_000)
    tags: List[str] | None = None
    source: str | None = None


class KbDeleteInput(BaseModel):
    id: str = Field(min_length=1)


class KbUnlinkInput(BaseModel):
    from_id: str = Field(min_length=1)
    to_id: str = Field(min_length=1)
    rel: str | None = Field(default=None, min_length=1, max_length=64)


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


def _mcp_error(exc: Exception) -> tuple[int, str]:
    """Map kb-mcp exceptions to MCP JSON-RPC error codes.

    Returns (code, message).
    """
    if isinstance(exc, ValidationError):
        return -32602, str(exc)
    if isinstance(exc, NotFoundError):
        return -32004, str(exc)
    if isinstance(exc, DuplicateError):
        return -32005, str(exc)
    if isinstance(exc, IntegrityError):
        return -32603, str(exc)
    return -32603, f"internal error: {exc}"


# ---------------------------------------------------------------------------
# Structured JSON logging to stderr
# ---------------------------------------------------------------------------


class _JsonFormatter(logging.Formatter):
    """Emit log records as single-line JSON to stderr."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _setup_logging(level: str | None = None) -> logging.Logger:
    """Configure structured JSON logging to stderr.

    Body content is never logged (privacy).
    """
    log_level = (level or os.environ.get("KB_MCP_LOG_LEVEL", "WARNING")).upper()
    logger = logging.getLogger("kb_mcp")
    logger.setLevel(getattr(logging, log_level, logging.WARNING))

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_JsonFormatter())
    logger.handlers.clear()
    logger.addHandler(handler)

    return logger


# ---------------------------------------------------------------------------
# Store factory
# ---------------------------------------------------------------------------


def _default_db_path() -> Path:
    """Return the default SQLite DB path."""
    home = os.environ.get("KB_MCP_HOME")
    if home:
        return Path(home) / "kb.db"
    return Path.home() / ".local" / "share" / "kb-mcp" / "kb.db"


def _create_store() -> SqliteStore:
    """Return a fresh :class:`SqliteStore` at the default path."""
    return SqliteStore(_default_db_path())


# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------


def _make_server() -> Any:
    """Build and return a FastMCP instance with the 4 kb tools registered."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("mcp package not installed; run: pip install mcp") from e

    mcp = FastMCP("kb-mcp")
    store = _create_store()
    logger = _setup_logging()

    # ---- kb_search --------------------------------------------------------

    @mcp.tool()
    def kb_search(
        query: str,
        type: Optional[str] = None,  # matches MCP schema in architecture.md § 4.4
        tags: Optional[List[str]] = None,
        limit: int = 10,
        mode: str = "hybrid",
    ) -> Any:
        """Full-text search the knowledge base.

        Args:
            query: Search query (non-empty).
            type: Restrict to a document type (optional).
            tags: Restrict to documents carrying all listed tags (AND, optional).
            limit: Max results 1..100 (default 10).
            mode: Scoring mode — 'lexical' (exact BM25), 'fuzzy'
                (trigram BM25, tolerates typos), or 'hybrid' (union,
                exact wins ties; default).

        Returns:
            List of hit dicts: {id, title, type, snippet, score}.
        """
        try:
            inp = KbSearchInput(query=query, type=type, tags=tags, limit=limit, mode=mode)
        except Exception as e:
            code, msg = _mcp_error(ValidationError(str(e)))
            raise RuntimeError(f"MCP error {code}: {msg}")

        logger.info(
            "kb_search query=%r type=%r tags=%r limit=%d mode=%r",
            inp.query, inp.type, inp.tags, inp.limit, inp.mode,
        )
        try:
            hits: List[SearchHit] = store.search(
                query=inp.query,
                type=inp.type,
                tags=inp.tags,
                limit=inp.limit,
                mode=inp.mode,
            )
            return {
                "hits": [
                    {
                        "id": h.doc.id,
                        "title": h.doc.title,
                        "type": h.doc.type,
                        "snippet": h.snippet,
                        "score": h.score,
                    }
                    for h in hits
                ],
                "count": len(hits),
            }
        except Exception as e:
            code, msg = _mcp_error(e)
            logger.exception("kb_search failed: %s", msg)
            raise RuntimeError(f"MCP error {code}: {msg}")

    # ---- kb_get -----------------------------------------------------------

    @mcp.tool()
    def kb_get(id: str) -> Any:
        """Fetch a document by id.

        Args:
            id: Document id (slug, e.g. "proj/kb-mcp").

        Returns:
            Full document dict (all fields).
        """
        try:
            inp = KbGetInput(id=id)
        except Exception as e:
            code, msg = _mcp_error(ValidationError(str(e)))
            raise RuntimeError(f"MCP error {code}: {msg}")

        logger.info("kb_get id=%r", inp.id)
        try:
            doc = store.get(inp.id)
            return doc.model_dump(mode="json")
        except Exception as e:
            code, msg = _mcp_error(e)
            logger.exception("kb_get failed: %s", msg)
            raise RuntimeError(f"MCP error {code}: {msg}")

    # ---- kb_add -----------------------------------------------------------

    @mcp.tool()
    def kb_add(
        type: str,  # matches MCP schema in architecture.md § 4.4
        title: str,
        body: str = "",
        tags: Optional[List[str]] = None,
        source: Optional[str] = None,
    ) -> Any:
        """Create a new document.

        Args:
            type: Document type (e.g. "project", "decision").
            title: Document title (non-empty).
            body: Markdown body (default "").
            tags: List of tag strings (optional).
            source: Origin file path (optional, enables idempotent re-import).

        Returns:
            {id: new_document_id}.
        """
        try:
            inp = KbAddInput(type=type, title=title, body=body, tags=tags, source=source)
        except Exception as e:
            code, msg = _mcp_error(ValidationError(str(e)))
            raise RuntimeError(f"MCP error {code}: {msg}")

        logger.info(
            "kb_add type=%r title=%r tags=%r source=%r",
            inp.type,
            inp.title,
            inp.tags,
            inp.source,
        )
        try:
            doc = Document(
                id=make_id(inp.type, inp.title),
                type=inp.type,
                title=inp.title,
                body=inp.body,
                tags=inp.tags or [],
                source=inp.source,
            )
            stored_id = store.add(doc)
            return {"id": stored_id}
        except Exception as e:
            code, msg = _mcp_error(e)
            logger.exception("kb_add failed: %s", msg)
            raise RuntimeError(f"MCP error {code}: {msg}")

    # ---- kb_link ----------------------------------------------------------

    @mcp.tool()
    def kb_link(
        from_id: str,
        to_id: str,
        rel: str = "relates-to",
    ) -> Any:
        """Create a typed edge between two documents.

        Args:
            from_id: Source document id.
            to_id: Target document id.
            rel: Relation type (default "relates-to").

        Returns:
            {ok: True, from_id, to_id, rel}.
        """
        try:
            inp = KbLinkInput(from_id=from_id, to_id=to_id, rel=rel)
        except Exception as e:
            code, msg = _mcp_error(ValidationError(str(e)))
            raise RuntimeError(f"MCP error {code}: {msg}")

        logger.info("kb_link from=%r to=%r rel=%r", inp.from_id, inp.to_id, inp.rel)
        try:
            link = store.link(inp.from_id, inp.to_id, rel=inp.rel)
            return {
                "ok": True,
                "from_id": link.from_id,
                "to_id": link.to_id,
                "rel": link.rel,
            }
        except Exception as e:
            code, msg = _mcp_error(e)
            logger.exception("kb_link failed: %s", msg)
            raise RuntimeError(f"MCP error {code}: {msg}")

    # ---- kb_list ----------------------------------------------------------

    @mcp.tool()
    def kb_list(
        type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0,
        include_deleted: bool = False,
    ) -> Any:
        """List documents, sorted by ``updated_at`` DESC.

        Args:
            type: Restrict to a document type (optional).
            tags: Restrict to documents carrying all listed tags (AND, optional).
            limit: Max results 1..1000 (default 100).
            offset: Skip this many results before returning (pagination).
            include_deleted: Include soft-deleted documents (default false).

        Returns:
            List of document summaries: {id, title, type, tags, updated_at}.
        """
        try:
            inp = KbListInput(type=type, tags=tags, limit=limit, offset=offset,
                              include_deleted=include_deleted)
        except Exception as e:
            code, msg = _mcp_error(ValidationError(str(e)))
            raise RuntimeError(f"MCP error {code}: {msg}")

        logger.info(
            "kb_list type=%r tags=%r limit=%d offset=%d include_deleted=%s",
            inp.type, inp.tags, inp.limit, inp.offset, inp.include_deleted,
        )
        try:
            docs = store.list(
                type=inp.type,
                tags=inp.tags,
                limit=inp.limit,
                offset=inp.offset,
                include_deleted=inp.include_deleted,
            )
            return {
                "documents": [
                    {
                        "id": d.id,
                        "type": d.type,
                        "title": d.title,
                        "tags": d.tags,
                        "updated_at": d.updated_at.isoformat(),
                    }
                    for d in docs
                ],
                "count": len(docs),
            }
        except Exception as e:
            code, msg = _mcp_error(e)
            logger.exception("kb_list failed: %s", msg)
            raise RuntimeError(f"MCP error {code}: {msg}")

    # ---- kb_update --------------------------------------------------------

    @mcp.tool()
    def kb_update(
        id: str,
        title: Optional[str] = None,
        body: Optional[str] = None,
        tags: Optional[List[str]] = None,
        source: Optional[str] = None,
    ) -> Any:
        """Patch fields on an existing document.

        Only ``title``, ``body``, ``tags``, ``source`` may be changed.
        ``id``, ``type``, ``created_at`` are immutable.

        Args:
            id: Document id to update.
            title: New title (optional).
            body: New Markdown body (optional).
            tags: New tag list (optional; empty list clears tags).
            source: New source path (optional).

        Returns:
            {ok: True, id, updated_at}.
        """
        try:
            inp = KbUpdateInput(id=id, title=title, body=body, tags=tags, source=source)
        except Exception as e:
            code, msg = _mcp_error(ValidationError(str(e)))
            raise RuntimeError(f"MCP error {code}: {msg}")

        fields: dict[str, object] = {}
        if inp.title is not None:
            fields["title"] = inp.title
        if inp.body is not None:
            fields["body"] = inp.body
        if inp.tags is not None:
            fields["tags"] = inp.tags
        if inp.source is not None:
            fields["source"] = inp.source

        if not fields:
            code, msg = _mcp_error(ValidationError("update requires at least one field"))
            raise RuntimeError(f"MCP error {code}: {msg}")

        logger.info("kb_update id=%r fields=%s", inp.id, sorted(fields.keys()))
        try:
            doc = store.update(inp.id, **fields)
            return {"ok": True, "id": doc.id, "updated_at": doc.updated_at.isoformat()}
        except Exception as e:
            code, msg = _mcp_error(e)
            logger.exception("kb_update failed: %s", msg)
            raise RuntimeError(f"MCP error {code}: {msg}")

    # ---- kb_delete --------------------------------------------------------

    @mcp.tool()
    def kb_delete(id: str) -> Any:
        """Soft-delete a document by id.

        Idempotent: deleting an already-deleted document is a no-op.
        Use ``kb doctor`` and ``kb prune`` (CLI) for hard deletion.

        Args:
            id: Document id to delete.

        Returns:
            {ok: True, id}.
        """
        try:
            inp = KbDeleteInput(id=id)
        except Exception as e:
            code, msg = _mcp_error(ValidationError(str(e)))
            raise RuntimeError(f"MCP error {code}: {msg}")

        logger.info("kb_delete id=%r", inp.id)
        try:
            store.delete(inp.id)
            return {"ok": True, "id": inp.id}
        except Exception as e:
            code, msg = _mcp_error(e)
            logger.exception("kb_delete failed: %s", msg)
            raise RuntimeError(f"MCP error {code}: {msg}")

    # ---- kb_unlink --------------------------------------------------------

    @mcp.tool()
    def kb_unlink(
        from_id: str,
        to_id: str,
        rel: Optional[str] = None,
    ) -> Any:
        """Remove typed edges between two documents.

        If ``rel`` is None, all edges between ``from_id`` and ``to_id`` are
        removed. Returns the count of edges removed.

        Args:
            from_id: Source document id.
            to_id: Target document id.
            rel: Relation type (default: remove all relations).

        Returns:
            {ok: True, removed: N, from_id, to_id, rel}.
        """
        try:
            inp = KbUnlinkInput(from_id=from_id, to_id=to_id, rel=rel)
        except Exception as e:
            code, msg = _mcp_error(ValidationError(str(e)))
            raise RuntimeError(f"MCP error {code}: {msg}")

        logger.info("kb_unlink from=%r to=%r rel=%r", inp.from_id, inp.to_id, inp.rel)
        try:
            n = store.unlink(inp.from_id, inp.to_id, rel=inp.rel)
            return {
                "ok": True,
                "removed": n,
                "from_id": inp.from_id,
                "to_id": inp.to_id,
                "rel": inp.rel,
            }
        except Exception as e:
            code, msg = _mcp_error(e)
            logger.exception("kb_unlink failed: %s", msg)
            raise RuntimeError(f"MCP error {code}: {msg}")

    return mcp


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run() -> None:
    """Start the MCP server on stdio.

    Called by ``kb serve`` CLI command.

    Uses :meth:`FastMCP.run` (sync, anyio-backed) rather than the async
    ``run_stdio_async`` + ``asyncio.run`` pair — the latter raises
    ``ValueError: I/O operation on closed file`` when stdin sees EOF
    before the asyncio loop is fully scheduled. ``anyio.run`` handles
    stdin/stdout lifecycle more gracefully under subprocess stdio.
    """
    mcp = _make_server()
    mcp.run(transport="stdio")


__all__ = ["run", "KbSearchInput", "KbGetInput", "KbAddInput", "KbLinkInput",
          "KbListInput", "KbUpdateInput", "KbDeleteInput", "KbUnlinkInput"]


# Allow ``python -m kb_mcp.mcp_server`` to start the server directly
# (avoids Click's stdin/stdout interaction).
if __name__ == "__main__":
    run()
