"""Shared helpers for admin route modules."""

from __future__ import annotations

import os
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from kb_mcp_lite.schema import Document, Link, SearchHit, ValidationError
from kb_mcp_lite.store.sqlite import SqliteStore
from kb_mcp_lite.vault import VaultManager

DOC_TYPES = ["project", "decision", "lesson", "glossary", "person", "faq"]
SEARCH_MODES = ["lexical", "fuzzy", "semantic", "hybrid"]


def create_default_store() -> SqliteStore:
    try:
        mgr = VaultManager()
        db_path = mgr.resolve_path()
        return SqliteStore(db_path)
    except Exception:
        home = os.environ.get("KB_MCP_HOME")
        if home:
            db_path = Path(home) / "kb.db"
        else:
            db_path = Path.home() / ".local" / "share" / "kb-mcp" / "kb.db"
        return SqliteStore(db_path)


@contextmanager
def open_store(app: FastAPI):
    store = SqliteStore(Path(app.state.store_path))
    try:
        yield store
    finally:
        store.close()


def split_tags(raw: str) -> list[str] | None:
    values = [tag.strip() for tag in raw.split(",") if tag.strip()]
    return values or None


def filtered_documents(
    store: SqliteStore,
    *,
    q: str = "",
    doc_type: str = "",
    tag: str = "",
    include_deleted: bool = False,
) -> list[Document]:
    tags = [tag] if tag else None
    if q.strip():
        hits = store.search(q, type=doc_type or None, tags=tags, limit=100, mode="hybrid")
        return [hit.doc for hit in hits]
    return store.list(
        type=doc_type or None,
        tags=tags,
        limit=200,
        include_deleted=include_deleted,
    )


def create_document(
    store: SqliteStore,
    *,
    doc_id: str,
    doc_type: str,
    title: str,
    tags: list[str] | None,
    source: str | None,
    body: str,
) -> Document:
    doc = Document(
        id=(doc_id or "").strip(),
        type=doc_type.strip(),
        title=title.strip(),
        tags=tags or [],
        source=source.strip() if isinstance(source, str) and source.strip() else None,
        body=body,
    )
    created_id = store.add(doc)
    return store.get(created_id)


def patch_document(
    store: SqliteStore,
    doc_id: str,
    title: str | None,
    tags: list[str] | None,
    source: str | None,
    body: str | None,
    deleted: bool | None,
) -> Document:
    if deleted is True:
        store.delete(doc_id)
        return store.get(doc_id, include_deleted=True)
    fields: dict[str, object] = {}
    if title is not None:
        fields["title"] = title.strip()
    if tags is not None:
        fields["tags"] = tags
    if source is not None:
        fields["source"] = source.strip() or None
    if body is not None:
        fields["body"] = body
    if not fields:
        raise ValidationError("update requires at least one field")
    return store.update(doc_id, **fields)


def doc_row(store: SqliteStore, doc: Document) -> dict[str, Any]:
    return {
        "doc": doc,
        "outlinks": len(store.outlinks(doc.id)),
        "backlinks": len(store.backlinks(doc.id)),
    }


def doc_form_data(doc: Document) -> dict[str, Any]:
    return {
        "id": doc.id,
        "type": doc.type,
        "title": doc.title,
        "tags": ", ".join(doc.tags),
        "source": doc.source or "",
        "body": doc.body,
    }


def count_links(store: SqliteStore) -> int:
    return int(store._conn.execute("SELECT COUNT(*) FROM links").fetchone()[0])


def list_links(store: SqliteStore) -> list[Link]:
    rows = store._conn.execute(
        "SELECT from_id, to_id, rel, created_at FROM links ORDER BY created_at DESC, from_id, to_id"
    ).fetchall()
    return [store._row_to_link(row) for row in rows]


def serialize_doc(doc: Document) -> dict[str, Any]:
    payload = doc.model_dump(mode="json")
    payload["tags"] = list(doc.tags)
    return payload


def serialize_link(link: Link) -> dict[str, Any]:
    return link.model_dump(mode="json")


def serialize_hit(hit: SearchHit) -> dict[str, Any]:
    return {
        "doc": serialize_doc(hit.doc),
        "snippet": hit.snippet,
        "score": hit.score,
    }


def json_error(message: str, *, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status_code)


def flash_url(base: str, kind: str, message: str) -> str:
    return f"{base}?{urlencode({'flash': kind, 'message': message})}"


def overview_payload(store: SqliteStore) -> dict[str, Any]:
    all_docs = store.export_all(include_deleted=True)
    active_docs = [doc for doc in all_docs if doc.deleted_at is None]
    deleted_docs = [doc for doc in all_docs if doc.deleted_at is not None]
    tag_counts = Counter(tag for doc in active_docs for tag in doc.tags)
    type_counts = Counter(doc.type for doc in active_docs)
    doctor_report = store.doctor()
    recent_docs = sorted(active_docs, key=lambda doc: doc.updated_at, reverse=True)[:8]
    orphan_count = sum(
        1 for doc in active_docs if not store.backlinks(doc.id) and not store.outlinks(doc.id)
    )
    try:
        embedder = getattr(store, "_embedder", None)
        embed_enabled = bool(embedder and getattr(embedder, "enabled", False))
        embed_dim = getattr(embedder, "dim", 0) if embed_enabled else 0
        vec_count = (
            store._conn.execute("SELECT COUNT(*) FROM docs_vec").fetchone()[0]
            if embed_enabled
            else 0
        )
    except Exception:
        embed_enabled = False
        embed_dim = 0
        vec_count = 0
    return {
        "stats": {
            "documents": len(active_docs),
            "deleted_documents": len(deleted_docs),
            "types": len(type_counts),
            "links": count_links(store),
            "orphan_documents": orphan_count,
            "vectors": vec_count,
        },
        "type_counts": sorted(type_counts.items()),
        "tag_counts": tag_counts.most_common(12),
        "recent_docs": recent_docs,
        "doctor_report": doctor_report,
        "embed_enabled": embed_enabled,
        "embed_dim": embed_dim,
    }


def schema_version(store: SqliteStore) -> str:
    row = store._conn.execute(
        "SELECT version, name FROM schema_version ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return "unknown"
    return f"{row['version']} ({row['name']})"


__all__ = [
    "DOC_TYPES",
    "SEARCH_MODES",
    "create_default_store",
    "open_store",
    "split_tags",
    "filtered_documents",
    "create_document",
    "patch_document",
    "doc_row",
    "doc_form_data",
    "count_links",
    "list_links",
    "serialize_doc",
    "serialize_link",
    "serialize_hit",
    "json_error",
    "flash_url",
    "overview_payload",
    "schema_version",
]
