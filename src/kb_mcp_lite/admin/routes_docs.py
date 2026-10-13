"""Document CRUD + search API routes for the admin UI."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from kb_mcp_lite.admin import ApiDocCreate, ApiDocUpdate
from kb_mcp_lite.admin._helpers import (
    create_document,
    filtered_documents,
    json_error,
    open_store,
    patch_document,
    serialize_doc,
    serialize_hit,
    serialize_link,
    split_tags,
)
from kb_mcp_lite.schema import (
    DuplicateError,
    IntegrityError,
    NotFoundError,
    ValidationError,
)


def register_doc_routes(app: FastAPI) -> None:
    """Register document-related API routes on the FastAPI app."""

    # ── API routes ─────────────────────────────────────────────────────

    @app.get("/api/docs")
    def api_docs(
        q: str = "",
        type: str = "",
        tag: str = "",
        include_deleted: bool = False,
    ) -> JSONResponse:
        with open_store(app) as store:
            docs = filtered_documents(
                store,
                q=q,
                doc_type=type,
                tag=tag,
                include_deleted=include_deleted,
            )
            return JSONResponse(
                {
                    "items": [serialize_doc(doc) for doc in docs],
                    "count": len(docs),
                }
            )

    @app.get("/api/docs/{doc_id:path}")
    def api_doc_detail(doc_id: str) -> JSONResponse:
        with open_store(app) as store:
            doc = store.get(doc_id, include_deleted=True)
            doc_data = serialize_doc(doc)
            sections = doc.extract_sections()
            return JSONResponse(
                {
                    "doc": doc_data,
                    "sections": sections,
                    "section_headings": [s for s in sections.keys() if s],
                    "outlinks": [serialize_link(link) for link in store.outlinks(doc.id)],
                    "backlinks": [serialize_link(link) for link in store.backlinks(doc.id)],
                    "history": store.document_history(doc.id),
                }
            )

    @app.get("/api/search")
    def api_search(
        query: str,
        type: str = "",
        tags: str = "",
        mode: str = "hybrid",
        limit: int = 10,
    ) -> JSONResponse:
        with open_store(app) as store:
            hits = store.search(
                query=query,
                type=type or None,
                tags=split_tags(tags),
                limit=limit,
                mode=mode,
            )
            return JSONResponse(
                {
                    "hits": [serialize_hit(hit) for hit in hits],
                    "count": len(hits),
                }
            )

    # ── Document CRUD API ──────────────────────────────────────────────

    @app.post("/api/docs")
    def api_doc_create(payload: ApiDocCreate) -> JSONResponse:
        with open_store(app) as store:
            try:
                created = create_document(
                    store,
                    doc_id=payload.id,
                    doc_type=payload.type,
                    title=payload.title,
                    tags=payload.tags,
                    source=payload.source,
                    body=payload.body,
                )
            except (ValidationError, DuplicateError) as exc:
                return json_error(str(exc), status_code=400)
            except (NotFoundError, IntegrityError) as exc:
                return json_error(str(exc), status_code=500)
            return JSONResponse({"ok": True, "doc": serialize_doc(created)}, status_code=201)

    @app.patch("/api/docs/{doc_id:path}")
    def api_doc_update(doc_id: str, payload: ApiDocUpdate) -> JSONResponse:
        with open_store(app) as store:
            try:
                doc = patch_document(
                    store,
                    doc_id,
                    payload.title,
                    payload.tags,
                    payload.source,
                    payload.body,
                    payload.deleted,
                )
            except NotFoundError as exc:
                return json_error(str(exc), status_code=404)
            except ValidationError as exc:
                return json_error(str(exc), status_code=400)
            except IntegrityError as exc:
                return json_error(str(exc), status_code=500)
            return JSONResponse({"ok": True, "doc": serialize_doc(doc)})

    @app.delete("/api/docs/{doc_id:path}")
    def api_doc_delete(doc_id: str) -> JSONResponse:
        with open_store(app) as store:
            try:
                store.delete(doc_id)
                doc = store.get(doc_id, include_deleted=True)
            except NotFoundError as exc:
                return json_error(str(exc), status_code=404)
            except IntegrityError as exc:
                return json_error(str(exc), status_code=500)
            return JSONResponse({"ok": True, "doc": serialize_doc(doc)})
