from __future__ import annotations

import os
import tempfile
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from kb_mcp_lite.md_io import export_dir, import_dir
from kb_mcp_lite.schema import Document, Link, SearchHit, ValidationError
from kb_mcp_lite.store.sqlite import SqliteStore
from kb_mcp_lite.vault import VaultManager, get_current_vault_name

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_DIR / "templates" / "admin"
STATIC_DIR = PACKAGE_DIR / "static"
DOC_TYPES = ["project", "decision", "lesson", "glossary", "person", "faq"]
SEARCH_MODES = ["lexical", "fuzzy", "semantic", "hybrid"]


class ApiDocCreate(BaseModel):
    id: str = ""
    type: str = Field(min_length=1)
    title: str = Field(min_length=1)
    tags: list[str] | None = None
    source: str | None = None
    body: str = ""


class ApiDocUpdate(BaseModel):
    title: str | None = None
    tags: list[str] | None = None
    source: str | None = None
    body: str | None = None
    deleted: bool | None = None


class ApiLinkWrite(BaseModel):
    from_id: str = Field(min_length=1)
    to_id: str = Field(min_length=1)
    rel: str = "relates-to"


def create_app(store: SqliteStore | None = None) -> FastAPI:
    app = FastAPI(title="kb-mcp admin", version="0.1")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.state.store_path = str((store or _create_default_store()).path)

    def render(
        request: Request,
        template: str,
        context: dict[str, Any] | None = None,
        *,
        status_code: int = 200,
    ) -> HTMLResponse:
        payload = {
            "request": request,
            "doc_types": DOC_TYPES,
            "search_modes": SEARCH_MODES,
            "vault_name": get_current_vault_name(),
            "flash": {
                "kind": request.query_params.get("flash", ""),
                "message": request.query_params.get("message", ""),
            },
        }
        if context:
            payload.update(context)
        return templates.TemplateResponse(
            request=request,
            name=template,
            context=payload,
            status_code=status_code,
        )

    @app.get("/api/stats")
    def api_stats() -> JSONResponse:
        with _open_store(app) as store:
            payload = _overview_payload(store)
            return JSONResponse(
                {
                    "stats": payload["stats"],
                    "type_counts": [
                        {"type": type_name, "count": count}
                        for type_name, count in payload["type_counts"]
                    ],
                    "tag_counts": [
                        {"tag": tag, "count": count} for tag, count in payload["tag_counts"]
                    ],
                    "recent_docs": [_serialize_doc(doc) for doc in payload["recent_docs"]],
                    "doctor_report": {
                        "ok": payload["doctor_report"].ok,
                        "checks": [
                            check.model_dump(mode="json")
                            for check in payload["doctor_report"].checks
                        ],
                    },
                    "embed_enabled": payload["embed_enabled"],
                    "embed_dim": payload["embed_dim"],
                }
            )

    @app.get("/api/docs")
    def api_docs(
        q: str = "",
        type: str = "",
        tag: str = "",
        include_deleted: bool = False,
    ) -> JSONResponse:
        with _open_store(app) as store:
            docs = _filtered_documents(
                store,
                q=q,
                doc_type=type,
                tag=tag,
                include_deleted=include_deleted,
            )
            return JSONResponse(
                {
                    "items": [_serialize_doc(doc) for doc in docs],
                    "count": len(docs),
                }
            )

    @app.get("/api/docs/{doc_id:path}")
    def api_doc_detail(doc_id: str) -> JSONResponse:
        with _open_store(app) as store:
            doc = store.get(doc_id, include_deleted=True)
            return JSONResponse(
                {
                    "doc": _serialize_doc(doc),
                    "outlinks": [_serialize_link(link) for link in store.outlinks(doc.id)],
                    "backlinks": [_serialize_link(link) for link in store.backlinks(doc.id)],
                    "history": store.document_history(doc.id),
                }
            )

    @app.post("/api/docs")
    def api_doc_create(payload: ApiDocCreate) -> JSONResponse:
        with _open_store(app) as store:
            try:
                created = _create_document(
                    store,
                    doc_id=payload.id,
                    doc_type=payload.type,
                    title=payload.title,
                    tags=payload.tags,
                    source=payload.source,
                    body=payload.body,
                )
            except Exception as exc:
                return _json_error(str(exc), status_code=400)
            return JSONResponse({"ok": True, "doc": _serialize_doc(created)}, status_code=201)

    @app.patch("/api/docs/{doc_id:path}")
    def api_doc_update(doc_id: str, payload: ApiDocUpdate) -> JSONResponse:
        with _open_store(app) as store:
            try:
                doc = _patch_document(
                    store,
                    doc_id,
                    payload.title,
                    payload.tags,
                    payload.source,
                    payload.body,
                    payload.deleted,
                )
            except Exception as exc:
                return _json_error(str(exc), status_code=400)
            return JSONResponse({"ok": True, "doc": _serialize_doc(doc)})

    @app.delete("/api/docs/{doc_id:path}")
    def api_doc_delete(doc_id: str) -> JSONResponse:
        with _open_store(app) as store:
            try:
                store.delete(doc_id)
                doc = store.get(doc_id, include_deleted=True)
            except Exception as exc:
                return _json_error(str(exc), status_code=400)
            return JSONResponse({"ok": True, "doc": _serialize_doc(doc)})

    @app.get("/api/search")
    def api_search(
        query: str,
        type: str = "",
        tags: str = "",
        mode: str = "hybrid",
        limit: int = 10,
    ) -> JSONResponse:
        with _open_store(app) as store:
            hits = store.search(
                query=query,
                type=type or None,
                tags=_split_tags(tags),
                limit=limit,
                mode=mode,
            )
            return JSONResponse(
                {
                    "hits": [_serialize_hit(hit) for hit in hits],
                    "count": len(hits),
                }
            )

    @app.get("/api/health")
    def api_health() -> JSONResponse:
        with _open_store(app) as store:
            doctor_report = store.doctor()
            return JSONResponse(
                {
                    "ok": doctor_report.ok,
                    "checks": [check.model_dump(mode="json") for check in doctor_report.checks],
                    "db_path": str(store.path),
                    "schema_version": _schema_version(store),
                    "audit_log": store.audit_log(limit=50),
                }
            )

    @app.get("/api/links")
    def api_links() -> JSONResponse:
        with _open_store(app) as store:
            links = _list_links(store)
            return JSONResponse(
                {
                    "items": [_serialize_link(link) for link in links],
                    "count": len(links),
                }
            )

    @app.get("/api/graph")
    def api_graph(root_id: str | None = None, depth: int = 2) -> JSONResponse:
        with _open_store(app) as store:
            type_colors = {
                "project": "#0f62fe",
                "decision": "#117a37",
                "lesson": "#b42318",
                "glossary": "#9a6700",
                "person": "#8b5cf6",
                "faq": "#0891b2",
            }
            default_color = "#62708a"

            if root_id:
                # ── BFS subgraph via store ────────────────────────────
                sub = store.subgraph(root_id, depth=depth)
                doc_ids = sub["doc_ids"]

                if doc_ids:
                    ph = ",".join("?" for _ in doc_ids)
                    doc_rows = store._conn.execute(
                        f"SELECT id, title, type FROM documents WHERE id IN ({ph}) AND deleted_at IS NULL",
                        doc_ids,
                    ).fetchall()
                else:
                    doc_rows = []

                nodes = [
                    {
                        "id": r["id"],
                        "label": r["title"],
                        "type": r["type"],
                        "color": type_colors.get(r["type"], default_color),
                        "url": f"/documents/{r['id']}",
                    }
                    for r in doc_rows
                ]
                edges = sub["edges"]
            else:
                # ── Full graph (all docs + links) ─────────────────────
                active_docs = store.export_all(include_deleted=False)
                links = _list_links(store)
                nodes = [
                    {
                        "id": doc.id,
                        "label": doc.title,
                        "type": doc.type,
                        "color": type_colors.get(doc.type, default_color),
                        "url": f"/documents/{doc.id}",
                    }
                    for doc in active_docs
                ]
                edges = [
                    {"from": link.from_id, "to": link.to_id, "label": link.rel} for link in links
                ]

            return JSONResponse({"nodes": nodes, "edges": edges})

    @app.get("/api/audit")
    def api_audit(limit: int = 100) -> JSONResponse:
        with _open_store(app) as store:
            return JSONResponse({"items": store.audit_log(limit=limit), "count": limit})

    @app.post("/api/links")
    def api_link_create(payload: ApiLinkWrite) -> JSONResponse:
        with _open_store(app) as store:
            try:
                link = store.link(
                    payload.from_id.strip(),
                    payload.to_id.strip(),
                    rel=payload.rel.strip() or "relates-to",
                )
            except Exception as exc:
                return _json_error(str(exc), status_code=400)
            return JSONResponse({"ok": True, "link": _serialize_link(link)}, status_code=201)

    @app.delete("/api/links")
    def api_link_delete(payload: ApiLinkWrite) -> JSONResponse:
        with _open_store(app) as store:
            removed = store.unlink(
                payload.from_id.strip(),
                payload.to_id.strip(),
                rel=payload.rel.strip() or None,
            )
            return JSONResponse({"ok": True, "removed": removed})

    @app.get("/", response_class=HTMLResponse)
    def overview(request: Request) -> HTMLResponse:
        with _open_store(app) as store:
            payload = _overview_payload(store)
            return render(
                request,
                "overview.html",
                {
                    "stats": payload["stats"],
                    "type_counts": payload["type_counts"],
                    "tag_counts": payload["tag_counts"],
                    "recent_docs": payload["recent_docs"],
                    "doctor_report": payload["doctor_report"],
                    "embed_enabled": payload["embed_enabled"],
                    "embed_dim": payload["embed_dim"],
                    "db_path": str(store.path),
                },
            )

    @app.get("/documents", response_class=HTMLResponse)
    def documents(
        request: Request,
        q: str = "",
        type: str = "",
        tag: str = "",
        include_deleted: bool = False,
    ) -> HTMLResponse:
        with _open_store(app) as store:
            docs = _filtered_documents(
                store,
                q=q,
                doc_type=type,
                tag=tag,
                include_deleted=include_deleted,
            )
            rows = [_doc_row(store, doc) for doc in docs]
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
        with _open_store(app) as store:
            try:
                doc = store.get(doc_id, include_deleted=True)
            except Exception as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            return render(
                request,
                "document_form.html",
                {
                    "doc_form": _doc_form_data(doc),
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
    ) -> HTMLResponse:
        with _open_store(app) as store:
            try:
                store.link(doc_id, to_id.strip(), rel=rel.strip() or "relates-to")
            except Exception as exc:
                doc = store.get(doc_id, include_deleted=True)
                return render(
                    request,
                    "document_form.html",
                    {
                        "doc_form": _doc_form_data(doc),
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
            url=_flash_url(f"/documents/{doc_id}", "success", "Link created"),
            status_code=303,
        )

    @app.post("/documents/{doc_id:path}/links/delete", response_class=HTMLResponse)
    async def document_link_delete(
        doc_id: str,
        to_id: str = Form(...),
        rel: str = Form(default=""),
    ) -> RedirectResponse:
        with _open_store(app) as store:
            store.unlink(doc_id, to_id.strip(), rel=rel.strip() or None)
        return RedirectResponse(
            url=_flash_url(f"/documents/{doc_id}", "success", "Link removed"),
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
    ) -> HTMLResponse:
        with _open_store(app) as store:
            try:
                created = _create_document(
                    store,
                    doc_id=id,
                    doc_type=type,
                    title=title,
                    tags=_split_tags(tags),
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
            url=_flash_url(f"/documents/{created_id}", "success", "Document created"),
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
    ) -> HTMLResponse:
        with _open_store(app) as store:
            if action == "delete":
                store.delete(doc_id)
                return RedirectResponse(
                    url=_flash_url("/documents", "success", "Document deleted"),
                    status_code=303,
                )
            try:
                _patch_document(
                    store,
                    doc_id,
                    title,
                    _split_tags(tags),
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
            url=_flash_url(f"/documents/{doc_id}", "success", "Document updated"),
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
            with _open_store(app) as store:
                try:
                    hits = store.search(
                        query=query,
                        type=type or None,
                        tags=_split_tags(tags),
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

    @app.get("/links", response_class=HTMLResponse)
    def links_page(
        request: Request,
        doc_id: str = "",
        rel: str = "",
    ) -> HTMLResponse:
        with _open_store(app) as store:
            docs = store.list(limit=500)
            links = _list_links(store)
            if doc_id:
                links = [link for link in links if link.from_id == doc_id or link.to_id == doc_id]
            if rel:
                links = [link for link in links if link.rel == rel]
            rel_options = sorted({link.rel for link in _list_links(store)})
            return render(
                request,
                "links.html",
                {
                    "links": links,
                    "docs": docs,
                    "rel_options": rel_options,
                    "filters": {"doc_id": doc_id, "rel": rel},
                },
            )

    @app.post("/links", response_class=HTMLResponse)
    async def links_create(
        from_id: str = Form(...),
        to_id: str = Form(...),
        rel: str = Form(default="relates-to"),
    ) -> RedirectResponse:
        with _open_store(app) as store:
            store.link(from_id.strip(), to_id.strip(), rel=rel.strip() or "relates-to")
        return RedirectResponse(url="/links?created=1", status_code=303)

    @app.post("/links/delete", response_class=HTMLResponse)
    async def links_delete(
        from_id: str = Form(...),
        to_id: str = Form(...),
        rel: str = Form(default=""),
    ) -> RedirectResponse:
        with _open_store(app) as store:
            store.unlink(from_id.strip(), to_id.strip(), rel=rel.strip() or None)
        return RedirectResponse(url="/links?deleted=1", status_code=303)

    @app.get("/imports", response_class=HTMLResponse)
    def imports_page(request: Request) -> HTMLResponse:
        return render(
            request,
            "imports.html",
            {
                "import_report": None,
                "export_report": None,
                "errors": [],
            },
        )

    @app.post("/imports", response_class=HTMLResponse)
    async def imports_run(
        request: Request,
        archive: UploadFile = File(...),
        dry_run: bool = Form(default=False),
    ) -> HTMLResponse:
        errors: list[str] = []
        import_report = None
        export_report = None
        try:
            with _open_store(app) as store:
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_path = Path(tmp)
                    payload = await archive.read()
                    zip_path = tmp_path / (archive.filename or "import.zip")
                    zip_path.write_bytes(payload)
                    import zipfile

                    with zipfile.ZipFile(zip_path) as zf:
                        zf.extractall(tmp_path / "vault")
                    import_report = import_dir(store, tmp_path / "vault", dry_run=dry_run)
        except Exception as exc:
            errors.append(str(exc))
        return render(
            request,
            "imports.html",
            {
                "import_report": import_report,
                "export_report": export_report,
                "errors": errors,
            },
            status_code=400 if errors else 200,
        )

    @app.post("/exports", response_class=HTMLResponse)
    def exports_run(request: Request) -> HTMLResponse:
        errors: list[str] = []
        import_report = None
        export_report = None
        try:
            with _open_store(app) as store:
                export_home = Path(tempfile.mkdtemp(prefix="kb-mcp-export-"))
                written = export_dir(store, export_home, force=True)
                files = sorted(
                    str(path.relative_to(export_home)) for path in export_home.rglob("*.md")
                )
                export_report = {
                    "path": str(export_home),
                    "written": written,
                    "files": files[:20],
                }
        except Exception as exc:
            errors.append(str(exc))
        return render(
            request,
            "imports.html",
            {
                "import_report": import_report,
                "export_report": export_report,
                "errors": errors,
            },
            status_code=400 if errors else 200,
        )

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request) -> HTMLResponse:
        with _open_store(app) as store:
            doctor_report = store.doctor()
            embedder = getattr(store, "_embedder", None)
            from kb_mcp_lite.config import config_path, load_config

            cfg_path = config_path()
            cfg_content = cfg_path.read_text(encoding="utf-8") if cfg_path.exists() else ""
            return render(
                request,
                "settings.html",
                {
                    "doctor_report": doctor_report,
                    "db_path": str(store.path),
                    "embedder_enabled": bool(embedder and getattr(embedder, "enabled", False)),
                    "embedder_dim": getattr(embedder, "dim", 0) if embedder else 0,
                    "kb_home": os.environ.get("KB_MCP_HOME", ""),
                    "version": _schema_version(store),
                    "audit_log": store.audit_log(limit=50),
                    "config_path": str(cfg_path),
                    "config_content": cfg_content,
                },
            )

    @app.get("/graph", response_class=HTMLResponse)
    def graph_page(request: Request) -> HTMLResponse:
        return render(request, "graph.html")

    # ---- vault management -------------------------------------------------

    @app.get("/api/vaults")
    def api_vaults() -> JSONResponse:
        mgr = VaultManager()
        vaults = mgr.list_vaults()
        current = mgr.get_current()
        return JSONResponse(
            {
                "current": current,
                "vaults": [
                    {
                        "name": v.name,
                        "description": v.description,
                        "sync_dir": v.sync_dir,
                    }
                    for v in vaults
                ],
            }
        )

    @app.post("/api/vaults/switch")
    def api_vault_switch(payload: dict[str, str]) -> JSONResponse:
        name = payload.get("name", "")
        if not name:
            return _json_error("vault name required", status_code=400)
        mgr = VaultManager()
        try:
            mgr.switch(name)
            new_path = str(mgr.resolve_path(name))
            app.state.store_path = new_path
            return JSONResponse({"ok": True, "current": name, "store_path": new_path})
        except Exception as e:
            return _json_error(str(e), status_code=400)

    @app.post("/api/vaults/import")
    def api_vault_import() -> JSONResponse:
        mgr = VaultManager()
        name = mgr.get_current()
        try:
            from kb_mcp_lite.md_io import import_dir as _import_dir

            sync_root = mgr._sync_dir(name)
            mdir = mgr.md_dir(name)
            import_target = sync_root if sync_root != mdir else mdir
            if not import_target.exists():
                return JSONResponse(
                    {"ok": False, "error": f"import target {import_target} does not exist"}
                )

            store = SqliteStore(mgr.resolve_path(name))
            try:
                report = _import_dir(store, import_target)
            finally:
                store.close()
            return JSONResponse(
                {
                    "ok": True,
                    "inserted": report.inserted,
                    "updated": report.updated,
                    "skipped": report.skipped,
                    "errors": report.errors[:10],
                }
            )
        except Exception as e:
            return _json_error(str(e), status_code=500)

    @app.post("/api/vaults/commit")
    def api_vault_commit(payload: dict[str, str]) -> JSONResponse:
        message = payload.get("message", "admin commit")
        mgr = VaultManager()
        name = mgr.get_current()
        try:
            output = mgr.commit(name, message=message)
            return JSONResponse({"ok": True, "output": output})
        except Exception as e:
            return _json_error(str(e), status_code=500)

    @app.get("/api/config")
    def api_config_get() -> JSONResponse:
        from kb_mcp_lite.config import config_path

        p = config_path()
        if not p.exists():
            return JSONResponse({"ok": False, "error": "config file not found"}, status_code=404)
        return JSONResponse({"ok": True, "path": str(p), "content": p.read_text(encoding="utf-8")})

    @app.put("/api/config")
    def api_config_put(payload: dict[str, str]) -> JSONResponse:
        content = payload.get("content", "")
        if not content:
            return _json_error("content is required", status_code=400)
        from kb_mcp_lite.config import config_path

        p = config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return JSONResponse({"ok": True, "path": str(p)})

    @app.post("/api/vaults/embed")
    def api_vault_embed() -> JSONResponse:
        mgr = VaultManager()
        name = mgr.get_current()
        store = SqliteStore(mgr.resolve_path(name))
        try:
            n = store.reindex_embeddings()
            report = getattr(store, "last_reindex_report", {}) or {}
            return JSONResponse(
                {
                    "ok": True,
                    "reindexed": n,
                    "failed": report.get("failed", 0),
                    "dim": report.get("dim", 0),
                    "total": report.get("total", 0),
                }
            )
        except Exception as e:
            return _json_error(str(e), status_code=500)
        finally:
            store.close()

    return app


def _create_default_store() -> SqliteStore:
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
def _open_store(app: FastAPI):
    store = SqliteStore(Path(app.state.store_path))
    try:
        yield store
    finally:
        store.close()


def _split_tags(raw: str) -> list[str] | None:
    values = [tag.strip() for tag in raw.split(",") if tag.strip()]
    return values or None


def _filtered_documents(
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


def _create_document(
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
        tags=tags,
        source=source.strip() if isinstance(source, str) and source.strip() else None,
        body=body,
    )
    created_id = store.add(doc)
    return store.get(created_id)


def _patch_document(
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


def _doc_row(store: SqliteStore, doc: Document) -> dict[str, Any]:
    return {
        "doc": doc,
        "outlinks": len(store.outlinks(doc.id)),
        "backlinks": len(store.backlinks(doc.id)),
    }


def _doc_form_data(doc: Document) -> dict[str, Any]:
    return {
        "id": doc.id,
        "type": doc.type,
        "title": doc.title,
        "tags": ", ".join(doc.tags),
        "source": doc.source or "",
        "body": doc.body,
    }


def _count_links(store: SqliteStore) -> int:
    return int(store._conn.execute("SELECT COUNT(*) FROM links").fetchone()[0])


def _list_links(store: SqliteStore) -> list[Link]:
    rows = store._conn.execute(
        "SELECT from_id, to_id, rel, created_at FROM links ORDER BY created_at DESC, from_id, to_id"
    ).fetchall()
    return [store._row_to_link(row) for row in rows]


def _serialize_doc(doc: Document) -> dict[str, Any]:
    payload = doc.model_dump(mode="json")
    payload["tags"] = list(doc.tags)
    return payload


def _serialize_link(link: Link) -> dict[str, Any]:
    return link.model_dump(mode="json")


def _serialize_hit(hit: SearchHit) -> dict[str, Any]:
    return {
        "doc": _serialize_doc(hit.doc),
        "snippet": hit.snippet,
        "score": hit.score,
    }


def _json_error(message: str, *, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status_code)


def _flash_url(base: str, kind: str, message: str) -> str:
    return f"{base}?{urlencode({'flash': kind, 'message': message})}"


def _overview_payload(store: SqliteStore) -> dict[str, Any]:
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
            "links": _count_links(store),
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


def _schema_version(store: SqliteStore) -> str:
    row = store._conn.execute(
        "SELECT version, name FROM schema_version ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return "unknown"
    return f"{row['version']} ({row['name']})"


def run_admin(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    store: SqliteStore | None = None,
) -> None:
    import uvicorn

    app = create_app(store=store)
    uvicorn.run(app, host=host, port=port, log_level="info")
