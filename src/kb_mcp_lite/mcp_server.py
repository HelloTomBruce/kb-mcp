"""FastMCP server for kb-mcp.

Exposes tools, Resources, and Prompts over stdio transport:

**Tools (12):** kb_search, kb_get, kb_add, kb_link, kb_list, kb_update,
kb_delete, kb_unlink, kb_history, kb_restore, kb_diff, kb_restore_deleted

**Resources (4):** kb://doc/{type}/{slug}, kb://links/{type}/{slug},
kb://types, kb://stats

**Prompts (2):** new-doc(type), link-analysis(id)

Error codes:

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
from typing import Any, List, Optional

from pydantic import BaseModel, Field

from kb_mcp_lite.schema import (
    Document,
    DuplicateError,
    IntegrityError,
    NotFoundError,
    SearchHit,
    ValidationError,
    make_id,
)
from kb_mcp_lite.store.sqlite import SqliteStore
from kb_mcp_lite.vault import VaultManager

# ---------------------------------------------------------------------------
# Pydantic input models (architecture.md § 4.4)
# ---------------------------------------------------------------------------


class KbSearchInput(BaseModel):
    query: str = Field(min_length=1)
    type: str | None = None
    tags: List[str] | None = None
    limit: int = Field(default=10, ge=1, le=100)
    mode: str = Field(default="hybrid", pattern="^(lexical|fuzzy|hybrid|rrf)$")
    rrf_k: int = Field(default=60, ge=1, le=200)


class KbGetInput(BaseModel):
    id: str = Field(min_length=1)


class KbAddInput(BaseModel):
    type: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=512)
    body: str = Field(default="", max_length=1_000_000)
    tags: List[str] | None = None
    aliases: List[str] | None = None
    source: str | None = None
    id: str | None = Field(default=None, min_length=1, max_length=512)


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
    aliases: List[str] | None = None
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
    logger = logging.getLogger("kb_mcp_lite")
    logger.setLevel(getattr(logging, log_level, logging.WARNING))

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_JsonFormatter())
    logger.handlers.clear()
    logger.addHandler(handler)

    return logger


# ---------------------------------------------------------------------------
# Store factory
# ---------------------------------------------------------------------------


def _create_store(vault: str | None = None) -> SqliteStore:
    """Return a :class:`SqliteStore` for the given (or current) vault.

    The DB path is resolved via :class:`VaultManager`.
    """
    mgr = VaultManager()
    db_path = mgr.resolve_path(vault)
    return SqliteStore(db_path)


# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------


def _make_server(vault: str | None = None) -> Any:
    """Build and return a FastMCP instance with kb tools registered.

    Args:
        vault: Optional vault name. Defaults to the current active vault.
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("mcp package not installed; run: pip install mcp") from e

    mcp = FastMCP("kb-mcp")
    store = _create_store(vault)
    logger = _setup_logging()

    # ---- kb_search --------------------------------------------------------

    @mcp.tool()
    def kb_search(
        query: str,
        type: Optional[str] = None,  # matches MCP schema in architecture.md § 4.4
        tags: Optional[List[str]] = None,
        limit: int = 10,
        mode: str = "hybrid",
        rrf_k: int = 60,
    ) -> Any:
        """Full-text search the knowledge base.

        Args:
            query: Search query (non-empty).
            type: Restrict to a document type (optional).
            tags: Restrict to documents carrying all listed tags (AND, optional).
            limit: Max results 1..100 (default 10).
            mode: Scoring mode — 'lexical' (exact BM25), 'fuzzy'
                (trigram BM25, tolerates typos), 'hybrid' (default,
                reciprocal-rank fusion of lexical+fuzzy+semantic),
                'rrf' (same as hybrid), or 'semantic' (vectors).
            rrf_k: RRF constant (default 60). Lower = more weight on
                top ranks. Only used in hybrid/rrf mode.

        Returns:
            List of hit dicts: {id, title, type, snippet, score}.
        """
        try:
            inp = KbSearchInput(
                query=query,
                type=type,
                tags=tags,
                limit=limit,
                mode=mode,
                rrf_k=rrf_k,
            )
        except Exception as e:
            code, msg = _mcp_error(ValidationError(str(e)))
            raise RuntimeError(f"MCP error {code}: {msg}")

        logger.info(
            "kb_search query=%r type=%r tags=%r limit=%d mode=%r rrf_k=%d",
            inp.query,
            inp.type,
            inp.tags,
            inp.limit,
            inp.mode,
            inp.rrf_k,
        )
        try:
            hits: List[SearchHit] = store.search(
                query=inp.query,
                type=inp.type,
                tags=inp.tags,
                limit=inp.limit,
                mode=inp.mode,
                rrf_k=inp.rrf_k,
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
        aliases: Optional[List[str]] = None,
        source: Optional[str] = None,
        id: Optional[str] = None,
    ) -> Any:
        """Create a new document.

        Args:
            type: Document type (e.g. "project", "decision").
            title: Document title (non-empty).
            body: Markdown body (default "").
            tags: List of tag strings (optional).
            aliases: Alternative IDs for this document (optional).
            source: Origin file path (optional, enables idempotent re-import).
            id: Explicit document id (e.g. "reference/foo/bar"). When omitted,
                the server auto-generates one from ``type`` and ``title``. Pass
                this when the caller has a stable hierarchical id (multi-doc
                imports, micro-app docs splits, etc.).

        Returns:
            {id: new_document_id}.
        """
        try:
            inp = KbAddInput(
                type=type, title=title, body=body, tags=tags, aliases=aliases, source=source, id=id
            )
        except Exception as e:
            code, msg = _mcp_error(ValidationError(str(e)))
            raise RuntimeError(f"MCP error {code}: {msg}")

        logger.info(
            "kb_add type=%r title=%r tags=%r aliases=%r source=%r id=%r",
            inp.type,
            inp.title,
            inp.tags,
            inp.aliases,
            inp.source,
            inp.id,
        )
        try:
            doc_id = inp.id or make_id(inp.type, inp.title)
            doc = Document(
                id=doc_id,
                type=inp.type,
                title=inp.title,
                body=inp.body,
                tags=inp.tags or [],
                aliases=inp.aliases or [],
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
            inp = KbListInput(
                type=type, tags=tags, limit=limit, offset=offset, include_deleted=include_deleted
            )
        except Exception as e:
            code, msg = _mcp_error(ValidationError(str(e)))
            raise RuntimeError(f"MCP error {code}: {msg}")

        logger.info(
            "kb_list type=%r tags=%r limit=%d offset=%d include_deleted=%s",
            inp.type,
            inp.tags,
            inp.limit,
            inp.offset,
            inp.include_deleted,
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
        aliases: Optional[List[str]] = None,
        source: Optional[str] = None,
    ) -> Any:
        """Patch fields on an existing document.

        Only ``title``, ``body``, ``tags``, ``aliases``, ``source`` may be
        changed. ``id``, ``type``, ``created_at`` are immutable.

        Args:
            id: Document id to update.
            title: New title (optional).
            body: New Markdown body (optional).
            tags: New tag list (optional; empty list clears tags).
            aliases: New alias list (optional; empty list clears aliases).
            source: New source path (optional).

        Returns:
            {ok: True, id, updated_at}.
        """
        try:
            inp = KbUpdateInput(
                id=id, title=title, body=body, tags=tags, aliases=aliases, source=source
            )
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
        if inp.aliases is not None:
            fields["aliases"] = inp.aliases
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

    # ---- kb_history -------------------------------------------------------

    class KbHistoryInput(BaseModel):
        id: str = Field(min_length=1)
        limit: int = Field(default=50, ge=1, le=500)

    @mcp.tool()
    def kb_history(id: str, limit: int = 50) -> Any:
        """View the version history of a document.

        Args:
            id: Document id.
            limit: Max versions to return (default 50, max 500).

        Returns:
            List of version entries: {version_id, action, created_at, ...}.
        """
        try:
            inp = KbHistoryInput(id=id, limit=limit)
        except Exception as e:
            code, msg = _mcp_error(ValidationError(str(e)))
            raise RuntimeError(f"MCP error {code}: {msg}")

        logger.info("kb_history id=%r limit=%d", inp.id, inp.limit)
        try:
            history = store.document_history(inp.id, limit=inp.limit)
            return {"history": history, "count": len(history)}
        except Exception as e:
            code, msg = _mcp_error(e)
            logger.exception("kb_history failed: %s", msg)
            raise RuntimeError(f"MCP error {code}: {msg}")

    # ---- kb_restore -------------------------------------------------------

    class KbRestoreInput(BaseModel):
        id: str = Field(min_length=1)
        version: int | None = None

    @mcp.tool()
    def kb_restore(id: str, version: Optional[int] = None) -> Any:
        """Restore a document to a previous version.

        Args:
            id: Document id.
            version: Version id to restore to (default: most recent).

        Returns:
            {ok: True, id, version, restored_at}.
        """
        try:
            inp = KbRestoreInput(id=id, version=version)
        except Exception as e:
            code, msg = _mcp_error(ValidationError(str(e)))
            raise RuntimeError(f"MCP error {code}: {msg}")

        logger.info("kb_restore id=%r version=%r", inp.id, inp.version)
        try:
            doc = store.restore(inp.id, version_id=inp.version)
            return {
                "ok": True,
                "id": doc.id,
                "version": inp.version,
                "restored_at": doc.updated_at.isoformat(),
            }
        except Exception as e:
            code, msg = _mcp_error(e)
            logger.exception("kb_restore failed: %s", msg)
            raise RuntimeError(f"MCP error {code}: {msg}")

    # ---- kb_diff ----------------------------------------------------------

    class KbDiffInput(BaseModel):
        id: str = Field(min_length=1)
        version_a: int
        version_b: int

    @mcp.tool()
    def kb_diff(id: str, version_a: int, version_b: int) -> Any:
        """Compare two document versions and return field-level differences.

        Args:
            id: Document id.
            version_a: First version id.
            version_b: Second version id.

        Returns:
            {added, removed, changed} describing the diff from A to B.
        """
        try:
            inp = KbDiffInput(id=id, version_a=version_a, version_b=version_b)
        except Exception as e:
            code, msg = _mcp_error(ValidationError(str(e)))
            raise RuntimeError(f"MCP error {code}: {msg}")

        logger.info("kb_diff id=%r a=%d b=%d", inp.id, inp.version_a, inp.version_b)
        try:
            result = store.diff(inp.id, inp.version_a, inp.version_b)
            return result
        except Exception as e:
            code, msg = _mcp_error(e)
            logger.exception("kb_diff failed: %s", msg)
            raise RuntimeError(f"MCP error {code}: {msg}")

    # ---- kb_restore_deleted -----------------------------------------------

    @mcp.tool()
    def kb_restore_deleted(id: str) -> Any:
        """Restore a soft-deleted document.

        Args:
            id: Document id.

        Returns:
            {ok: True, id, restored_at}.
        """
        try:
            inp = KbRestoreInput(id=id)
        except Exception as e:
            code, msg = _mcp_error(ValidationError(str(e)))
            raise RuntimeError(f"MCP error {code}: {msg}")

        logger.info("kb_restore_deleted id=%r", inp.id)
        try:
            doc = store.restore_deleted(inp.id)
            return {
                "ok": True,
                "id": doc.id,
                "restored_at": doc.updated_at.isoformat(),
            }
        except Exception as e:
            code, msg = _mcp_error(e)
            logger.exception("kb_restore_deleted failed: %s", msg)
            raise RuntimeError(f"MCP error {code}: {msg}")

    # ---- Resources -------------------------------------------------------

    @mcp.resource(
        "kb://doc/{type}/{slug}",
        name="doc",
        description="Full document by id (JSON); type=prefix (e.g. proj), slug=rest of id",
        mime_type="application/json",
    )
    def kb_resource_doc(type: str, slug: str) -> str:
        """Return the full document as JSON.

        Args:
            type: Document type prefix (e.g. "proj", "dec", "lesson").
            slug: Remainder of the document id after the ``/``.

        Returns:
            JSON string of the full document.
        """
        doc_id = f"{type}/{slug}"
        logger.info("resource kb://doc/%s", doc_id)
        try:
            doc = store.get(doc_id)
            return json.dumps(doc.model_dump(mode="json"), ensure_ascii=False)
        except NotFoundError:
            return json.dumps({"error": "not_found", "id": doc_id})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.resource(
        "kb://links/{type}/{slug}",
        name="links",
        description="Backlinks and outlinks for a document (JSON)",
        mime_type="application/json",
    )
    def kb_resource_links(type: str, slug: str) -> str:
        """Return the links (inbound + outbound) for a document.

        Args:
            type: Document type prefix (e.g. "proj").
            slug: Remainder of the document id.

        Returns:
            JSON object with backlinks and outlinks arrays.
        """
        doc_id = f"{type}/{slug}"
        logger.info("resource kb://links/%s", doc_id)
        try:
            backlinks = store.backlinks(doc_id)
            outlinks = store.outlinks(doc_id)
            return json.dumps(
                {
                    "doc_id": doc_id,
                    "backlinks": [{"from_id": lnk.from_id, "rel": lnk.rel} for lnk in backlinks],
                    "outlinks": [{"to_id": lnk.to_id, "rel": lnk.rel} for lnk in outlinks],
                },
                ensure_ascii=False,
            )
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.resource(
        "kb://types",
        name="types",
        description="Registered document types with their JSON field schemas",
        mime_type="application/json",
    )
    def kb_resource_types() -> str:
        """Return the list of registered document types and their pydantic field
        schemas.

        Returns:
            JSON object: ``{types: [{name, description, fields: [...]}], count: N}``.
        """
        logger.info("resource kb://types")
        try:
            from kb_mcp_lite.schema import default_registry

            types_info = []
            for name in default_registry.known_types():
                model = default_registry.model_for(name)
                fields = []
                for fname, finfo in model.model_fields.items():
                    fields.append(
                        {
                            "name": fname,
                            "type": str(finfo.annotation),
                            "required": finfo.is_required(),
                            "default": repr(finfo.default) if finfo.default is not None else None,
                        }
                    )
                types_info.append(
                    {
                        "name": name,
                        "description": (model.__doc__ or "").strip(),
                        "fields": fields,
                    }
                )
            return json.dumps(
                {"types": types_info, "count": len(types_info)},
                ensure_ascii=False,
            )
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.resource(
        "kb://stats",
        name="stats",
        description="Knowledge base statistics (document counts, links, recent changes)",
        mime_type="application/json",
    )
    def kb_resource_stats() -> str:
        """Return knowledge base statistics.

        Returns:
            JSON string of stats dict.
        """
        logger.info("resource kb://stats")
        try:
            stats = store.stats()
            return json.dumps(stats, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.resource(
        "kb://graph/{type}/{slug}",
        name="graph",
        description="Subgraph centred on a document (depth 2); JSON with nodes and edges",
        mime_type="application/json",
    )
    def kb_resource_graph(type: str, slug: str) -> str:
        """Return the subgraph (depth 2) centred on a document.

        Args:
            type: Document type prefix (e.g. "proj").
            slug: Remainder of the document id.

        Returns:
            JSON string with node ids and edges.
        """
        doc_id = f"{type}/{slug}"
        logger.info("resource kb://graph/%s", doc_id)
        try:
            sub = store.subgraph(doc_id, depth=2)
            return json.dumps(sub, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.resource(
        "kb://graph/{type}/{slug}/{depth}",
        name="graph-depth",
        description="Subgraph centred on a document at a given depth; JSON with nodes and edges",
        mime_type="application/json",
    )
    def kb_resource_graph_depth(type: str, slug: str, depth: str) -> str:
        """Return the subgraph at a custom depth centred on a document.

        Args:
            type: Document type prefix (e.g. "proj").
            slug: Remainder of the document id.
            depth: Traversal depth (1, 2, 3, …).

        Returns:
            JSON string with node ids and edges.
        """
        doc_id = f"{type}/{slug}"
        logger.info("resource kb://graph/%s depth=%s", doc_id, depth)
        try:
            n = int(depth)
            if n < 1 or n > 8:
                return json.dumps({"error": f"depth must be 1..8 (got {depth})"})
            sub = store.subgraph(doc_id, depth=n)
            return json.dumps(sub, ensure_ascii=False)
        except ValueError:
            return json.dumps({"error": f"invalid depth {depth!r}"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    # ---- Prompts ---------------------------------------------------------

    @mcp.prompt(
        name="new-doc",
        title="New Document",
        description="Create a new document with a type-specific Markdown template.",
    )
    def kb_prompt_new_doc(type: str = "decision") -> str:
        """Return a Markdown skeleton for a given document type.

        Args:
            type: Document type — project, decision, lesson, glossary, person, faq.

        Returns:
            A fill-in-the-blank Markdown template.
        """
        templates = {
            "project": (
                "# {title}\n\n"
                "## Purpose\n\n"
                "(What does this project do? Why does it exist?)\n\n"
                "## Stack\n\n"
                "- Language:\n- Framework:\n- Database:\n- Infrastructure:\n\n"
                "## Status\n\n"
                "(active / maintenance / archived)\n\n"
                "## Owners\n\n"
                "(who maintains this)\n\n"
                "## Links\n\n"
                "- Related docs: \n"
            ),
            "decision": (
                "# {title}\n\n"
                "## Context\n\n"
                "(What prompted this decision? What problem does it solve?)\n\n"
                "## Options Considered\n\n"
                "- Option A: \n- Option B: \n\n"
                "## Decision\n\n"
                "(Chosen option and why)\n\n"
                "## Consequences\n\n"
                "(What does this decision affect? Any follow-up work?)\n\n"
            ),
            "lesson": (
                "# {title}\n\n"
                "## What Happened\n\n"
                "(Description of the situation)\n\n"
                "## Root Cause\n\n"
                "(Why did it happen?)\n\n"
                "## Resolution\n\n"
                "(How was it fixed or mitigated?)\n\n"
                "## Prevention\n\n"
                "(How to avoid this in the future)\n\n"
            ),
            "glossary": (
                "# {title}\n\n"
                "## Definition\n\n"
                "(One-sentence definition of the term)\n\n"
                "## Details\n\n"
                "(Elaboration, examples, or context)\n\n"
                "## Related Terms\n\n"
                "- \n\n"
            ),
            "person": (
                "# {title}\n\n"
                "## Role\n\n"
                "(Title / responsibility)\n\n"
                "## Expertise\n\n"
                "- \n\n"
                "## Projects\n\n"
                "- \n\n"
            ),
            "faq": (
                "# {title}\n\n"
                "## Answer\n\n"
                "(Concise answer to the question)\n\n"
                "## References\n\n"
                "- \n\n"
            ),
        }
        skeleton = templates.get(type, templates["decision"])
        return (
            f"You are adding a **{type}** document to the knowledge base.\n\n"
            "Fill in this template:\n\n"
            f"{skeleton}\n\n"
            "After filling, call kb_add with type, title, body, and optional tags."
        )

    @mcp.prompt(
        name="link-analysis",
        title="Link Analysis",
        description="Analyse a document's link graph and suggest missing connections.",
    )
    def kb_prompt_link_analysis(id: str) -> str:
        """Analyse the link graph around a document and suggest missing links.

        Args:
            id: Document id to analyse (e.g. "proj/kb-mcp").

        Returns:
            A multi-step analysis workflow the agent can execute.
        """
        return (
            f"Analyse the link graph for document **{id}**.\n\n"
            "1. **Read the document** — call kb_get to fetch the full body.\n"
            "2. **Check backlinks** — use the kb://links/ resource to see "
            "which documents link to this one.\n"
            "3. **Check outlinks** — same resource; does this document "
            "reference other documents by id?\n"
            "4. **Search for related docs** — use kb_search with key terms "
            "from the body to find documents that should be linked but aren't.\n"
            "5. **Suggest new links** — call kb_link(from_id, to_id, "
            "rel='relates-to') for each missing connection.\n\n"
            "Consider especially:\n"
            "- Decisions that mention this context but aren't linked to it\n"
            "- Lessons learned that reference the same component\n"
            "- FAQ entries whose answer involves this document\n"
            "- Person documents listing this under their projects\n\n"
            "When done, summarise how many links were added."
        )

    return mcp


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run(vault: str | None = None) -> None:
    """Start the MCP server on stdio.

    Args:
        vault: Optional vault name. Defaults to the current active vault.

    Called by ``kb serve`` CLI command.

    Uses :meth:`FastMCP.run` (sync, anyio-backed) rather than the async
    ``run_stdio_async`` + ``asyncio.run`` pair — the latter raises
    ``ValueError: I/O operation on closed file`` when stdin sees EOF
    before the asyncio loop is fully scheduled. ``anyio.run`` handles
    stdin/stdout lifecycle more gracefully under subprocess stdio.
    """
    mcp = _make_server(vault)
    mcp.run(transport="stdio")


__all__ = [
    "run",
    "KbSearchInput",
    "KbGetInput",
    "KbAddInput",
    "KbLinkInput",
    "KbListInput",
    "KbUpdateInput",
    "KbDeleteInput",
    "KbUnlinkInput",
]


# Allow ``python -m kb_mcp_lite.mcp_server`` to start the server directly
# (avoids Click's stdin/stdout interaction).
if __name__ == "__main__":
    run()
