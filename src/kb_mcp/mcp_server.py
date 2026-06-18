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
    tags: list[str] | None = None
    limit: int = Field(default=10, ge=1, le=100)


class KbGetInput(BaseModel):
    id: str = Field(min_length=1)


class KbAddInput(BaseModel):
    type: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=512)
    body: str = Field(default="", max_length=1_000_000)
    tags: list[str] | None = None
    source: str | None = None


class KbLinkInput(BaseModel):
    from_id: str = Field(min_length=1)
    to_id: str = Field(min_length=1)
    rel: str = Field(default="relates-to", min_length=1, max_length=64)


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
    ) -> Any:
        """Full-text search the knowledge base.

        Args:
            query: Search query (non-empty).
            type: Restrict to a document type (optional).
            tags: Restrict to documents carrying all listed tags (AND, optional).
            limit: Max results 1..100 (default 10).

        Returns:
            List of hit dicts: {id, title, type, snippet, score}.
        """
        try:
            inp = KbSearchInput(query=query, type=type, tags=tags, limit=limit)
        except Exception as e:
            code, msg = _mcp_error(ValidationError(str(e)))
            raise RuntimeError(f"MCP error {code}: {msg}")

        logger.info(
            "kb_search query=%r type=%r tags=%r limit=%d",
            inp.query,
            inp.type,
            inp.tags,
            inp.limit,
        )
        try:
            hits = store.search(
                query=inp.query,
                type=inp.type,
                tags=inp.tags,
                limit=inp.limit,
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


__all__ = ["run", "KbSearchInput", "KbGetInput", "KbAddInput", "KbLinkInput"]


# Allow ``python -m kb_mcp.mcp_server`` to start the server directly
# (avoids Click's stdin/stdout interaction).
if __name__ == "__main__":
    run()
