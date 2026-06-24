from __future__ import annotations

import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from kb_mcp_lite.md_io import export_dir, import_dir
from kb_mcp_lite.schema import Document, SearchHit, ValidationError
from kb_mcp_lite.store.sqlite import SqliteStore

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"
DOC_TYPES = ["project", "decision", "lesson", "glossary", "person", "faq"]
SEARCH_MODES = ["lexical", "fuzzy", "semantic", "hybrid"]


def create_app(store: SqliteStore | None = None) -> FastAPI:
    app = FastAPI(title="kb-mcp admin", version="0.1")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.state.store = store or _create_default_store()

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
        }
        if context:
            payload.update(context)
        return templates.TemplateResponse(
            request=request,
            name=template,
            context=payload,
            status_code=status_code,
        )

    @app.get("/", response_class=HTMLResponse)
    def overview(request: Request) -> HTMLResponse:
        store = app.state.store
        docs = store.list(limit=1000)
        all_docs = store.export_all(include_deleted=True)
        active_docs = [doc for doc in all_docs if doc.deleted_at is None]
        deleted_docs = [doc for doc in all_docs if doc.deleted_at is not None]
        tag_counts = Counter(tag for doc in active_docs for tag in doc.tags)
        type_counts = Counter(doc.type for doc in active_docs)
        doctor_report = store.doctor()

        recent_docs = sorted(
            active_docs,
            key=lambda doc: doc.updated_at,
            reverse=True,
        )[:8]
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

        stats = {
            "documents": len(active_docs),
            "deleted_documents": len(deleted_docs),
            "types": len(type_counts),
            "links": _count_links(store),
            "orphan_documents": orphan_count,
            "vectors": vec_count,
        }
        return render(
            request,
            "overview.html",
            {
                "stats": stats,
                "type_counts": sorted(type_counts.items()),
                "tag_counts": tag_counts.most_common(12),
                "recent_docs": recent_docs,
                "doctor_report": doctor_report,
                "embed_enabled": embed_enabled,
                "embed_dim": embed_dim,
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
        store = app.state.store
        tags = [tag] if tag else None
        if q.strip():
            hits = store.search(q, type=type or None, tags=tags, limit=100, mode="hybrid")
            docs = [hit.doc for hit in hits]
        else:
            docs = store.list(
                type=type or None,
                tags=tags,
                limit=200,
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
        store = app.state.store
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
            },
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
        store = app.state.store
        try:
            doc = Document(
                id=id.strip(),
                type=type.strip(),
                title=title.strip(),
                tags=_split_tags(tags),
                source=source.strip() or None,
                body=body,
            )
            created_id = store.add(doc)
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
                },
                status_code=400,
            )
        return RedirectResponse(
            url=f"/documents/{created_id}?saved=1",
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
        store = app.state.store
        if action == "delete":
            store.delete(doc_id)
            return RedirectResponse(url="/documents?deleted=1", status_code=303)
        try:
            store.update(
                doc_id,
                title=title.strip(),
                tags=_split_tags(tags),
                source=source.strip() or None,
                body=body,
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
                },
                status_code=400,
            )
        return RedirectResponse(url=f"/documents/{doc_id}?saved=1", status_code=303)

    @app.get("/search", response_class=HTMLResponse)
    def search_lab(
        request: Request,
        query: str = "",
        type: str = "",
        tags: str = "",
        mode: str = "hybrid",
        limit: int = 10,
    ) -> HTMLResponse:
        store = app.state.store
        hits: list[SearchHit] = []
        errors: list[str] = []
        if query.strip():
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
        store = app.state.store
        errors: list[str] = []
        import_report = None
        export_report = None
        try:
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
        store = app.state.store
        errors: list[str] = []
        import_report = None
        export_report = None
        try:
            export_home = Path(tempfile.mkdtemp(prefix="kb-mcp-export-"))
            written = export_dir(store, export_home, force=True)
            files = sorted(str(path.relative_to(export_home)) for path in export_home.rglob("*.md"))
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
        store = app.state.store
        doctor_report = store.doctor()
        embedder = getattr(store, "_embedder", None)
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
            },
        )

    return app


def _create_default_store() -> SqliteStore:
    home = os.environ.get("KB_MCP_HOME")
    if home:
        db_path = Path(home) / "kb.db"
    else:
        db_path = Path.home() / ".local" / "share" / "kb-mcp" / "kb.db"
    return SqliteStore(db_path)


def _split_tags(raw: str) -> list[str] | None:
    values = [tag.strip() for tag in raw.split(",") if tag.strip()]
    return values or None


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
