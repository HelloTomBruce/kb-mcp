"""Document CRUD + search routes for the admin UI."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from kb_mcp_lite.admin._helpers import (
    create_document,
    doc_form_data,
    doc_row,
    filtered_documents,
    flash_url,
    json_error,
    open_store,
    patch_document,
    serialize_doc,
    serialize_hit,
    split_tags,
)
from kb_mcp_lite.admin import ApiDocCreate, ApiDocUpdate
from kb_mcp_lite.admin._helpers import serialize_link
from kb_mcp_lite.schema import SearchHit


def register_doc_routes(app: FastAPI, render: Any) -> None:
    """Register document-related routes on the FastAPI app."""

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
            return JSONResponse(
                {
                    "doc": serialize_doc(doc),
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
            except Exception as exc:
                return json_error(str(exc), status_code=400)
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
            except Exception as exc:
                return json_error(str(exc), status_code=400)
            return JSONResponse({"ok": True, "doc": serialize_doc(doc)})

    @app.delete("/api/docs/{doc_id:path}")
    def api_doc_delete(doc_id: str) -> JSONResponse:
        with open_store(app) as store:
            try:
                store.delete(doc_id)
                doc = store.get(doc_id, include_deleted=True)
            except Exception as exc:
                return json_error(str(exc), status_code=400)
            return JSONResponse({"ok": True, "doc": serialize_doc(doc)})

    # ── HTML pages ─────────────────────────────────────────────────────

    @app.get("/documents", response_class=HTMLResponse)
    def documents(
        request: Request,
        q: str = "",
        type: str = "",
        tag: str = "",
        include_deleted: bool = False,
    ) -> HTMLResponse:
        with open_store(app) as store:
            docs = filtered_documents(
                store,
                q=q,
                doc_type=type,
                tag=tag,
                include_deleted=include_deleted,
            )
            rows = [doc_row(store, doc) for doc in docs]
            return render(
                request,
                "documents.html",
                {
                    "rows": rows,
                    "filters": {
                        "q": q,
                        "type": type,
                        "tag": tag,
                        "include_deleted": include_deleted,
                    },
                },
            )

    @app.get("/documents/new", response_class=HTMLResponse)
    def document_new(request: Request) -> HTMLResponse:
        empty = {
            "id": "",
            "type": "project",
            "title": "",
            "tags": "",
            "source": "",
            "body": "",
        }
        return render(
            request,
            "document_form.html",
            {
                "doc_form": empty,
                "editing": False,
                "errors": [],
                "links_out": [],
                "links_back": [],
            },
        )

    @app.get("/documents/{doc_id:path}", response_class=HTMLResponse)
    def document_detail(request: Request, doc_id: str) -> HTMLResponse:
        with open_store(app) as store:
            try:
                doc = store.get(doc_id, include_deleted=True)
            except Exception as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            return render(
                request,
                "document_form.html",
                {
                    "doc_form": doc_form_data(doc),
                    "editing": True,
                    "errors": [],
                    "links_out": store.outlinks(doc.id),
                    "links_back": store.backlinks(doc.id),
                    "doc": doc,
                    "history": store.document_history(doc.id),
                },
            )

    @app.post("/documents/{doc_id:path}/links", response_class=HTMLResponse)
    async def document_link_create(
        request: Request,
        doc_id: str,
        to_id: str = Form(...),
        rel: str = Form(default="relates-to"),
    ) -> Response:
        with open_store(app) as store:
            try:
                store.link(doc_id, to_id.strip(), rel=rel.strip() or "relates-to")
            except Exception as exc:
                doc = store.get(doc_id, include_deleted=True)
                return render(
                    request,
                    "document_form.html",
                    {
                        "doc_form": doc_form_data(doc),
                        "editing": True,
                        "errors": [str(exc)],
                        "links_out": store.outlinks(doc.id),
                        "links_back": store.backlinks(doc.id),
                        "doc": doc,
                        "history": store.document_history(doc.id),
                    },
                    status_code=400,
                )
        return RedirectResponse(
            url=flash_url(f"/documents/{doc_id}", "success", "Link created"),
            status_code=303,
        )

    @app.post("/documents/{doc_id:path}/links/delete", response_class=HTMLResponse)
    async def document_link_delete(
        doc_id: str,
        to_id: str = Form(...),
        rel: str = Form(default=""),
    ) -> RedirectResponse:
        with open_store(app) as store:
            store.unlink(doc_id, to_id.strip(), rel=rel.strip() or None)
        return RedirectResponse(
            url=flash_url(f"/documents/{doc_id}", "success", "Link removed"),
            status_code=303,
        )

    @app.post("/documents", response_class=HTMLResponse)
    async def document_create(
        request: Request,
        id: str = Form(default=""),
        type: str = Form(...),
        title: str = Form(...),
        tags: str = Form(default=""),
        source: str = Form(default=""),
        body: str = Form(default=""),
    ) -> Response:
        with open_store(app) as store:
            try:
                created = create_document(
                    store,
                    doc_id=id,
                    doc_type=type,
                    title=title,
                    tags=split_tags(tags),
                    source=source,
                    body=body,
                )
                created_id = created.id
            except Exception as exc:
                return render(
                    request,
                    "document_form.html",
                    {
                        "doc_form": {
                            "id": id,
                            "type": type,
                            "title": title,
                            "tags": tags,
                            "source": source,
                            "body": body,
                        },
                        "editing": False,
                        "errors": [str(exc)],
                        "links_out": [],
                        "links_back": [],
                        "history": [],
                    },
                    status_code=400,
                )
        return RedirectResponse(
            url=flash_url(f"/documents/{created_id}", "success", "Document created"),
            status_code=303,
        )

    @app.post("/documents/{doc_id:path}", response_class=HTMLResponse)
    async def document_update(
        request: Request,
        doc_id: str,
        title: str = Form(...),
        tags: str = Form(default=""),
        source: str = Form(default=""),
        body: str = Form(default=""),
        action: str = Form(default="save"),
    ) -> Response:
        with open_store(app) as store:
            if action == "delete":
                store.delete(doc_id)
                return RedirectResponse(
                    url=flash_url("/documents", "success", "Document deleted"),
                    status_code=303,
                )
            try:
                patch_document(
                    store,
                    doc_id,
                    title,
                    split_tags(tags),
                    source,
                    body,
                    deleted=None,
                )
            except Exception as exc:
                doc = store.get(doc_id, include_deleted=True)
                return render(
                    request,
                    "document_form.html",
                    {
                        "doc_form": {
                            "id": doc.id,
                            "type": doc.type,
                            "title": title,
                            "tags": tags,
                            "source": source,
                            "body": body,
                        },
                        "editing": True,
                        "errors": [str(exc)],
                        "links_out": store.outlinks(doc.id),
                        "links_back": store.backlinks(doc.id),
                        "doc": doc,
                        "history": store.document_history(doc.id),
                    },
                    status_code=400,
                )
        return RedirectResponse(
            url=flash_url(f"/documents/{doc_id}", "success", "Document updated"),
            status_code=303,
        )

    @app.get("/search", response_class=HTMLResponse)
    def search_lab(
        request: Request,
        query: str = "",
        type: str = "",
        tags: str = "",
        mode: str = "hybrid",
        limit: int = 10,
    ) -> HTMLResponse:
        hits: list[SearchHit] = []
        errors: list[str] = []
        if query.strip():
            with open_store(app) as store:
                try:
                    hits = store.search(
                        query=query,
                        type=type or None,
                        tags=split_tags(tags),
                        limit=limit,
                        mode=mode,
                    )
                except Exception as exc:
                    errors.append(str(exc))
        return render(
            request,
            "search.html",
            {
                "hits": hits,
                "errors": errors,
                "filters": {
                    "query": query,
                    "type": type,
                    "tags": tags,
                    "mode": mode,
                    "limit": limit,
                },
            },
        )
