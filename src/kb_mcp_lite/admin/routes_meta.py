"""Meta routes for the admin UI — overview, links, graph, imports, settings, vault."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from kb_mcp_lite.admin._helpers import (
    json_error,
    list_links,
    open_store,
    overview_payload,
    schema_version,
    serialize_link,
)
from kb_mcp_lite.admin import ApiLinkWrite
from kb_mcp_lite.admin._helpers import serialize_doc as _serialize_doc
from kb_mcp_lite.store.sqlite import SqliteStore
from kb_mcp_lite.vault import VaultManager


def register_meta_routes(app: FastAPI, render: Any) -> None:
    """Register meta/admin routes on the FastAPI app."""

    # ── Health / Stats / Audit ─────────────────────────────────────────

    @app.get("/api/stats")
    def api_stats() -> JSONResponse:
        with open_store(app) as store:
            payload = overview_payload(store)
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

    @app.get("/api/health")
    def api_health() -> JSONResponse:
        with open_store(app) as store:
            doctor_report = store.doctor()
            return JSONResponse(
                {
                    "ok": doctor_report.ok,
                    "checks": [check.model_dump(mode="json") for check in doctor_report.checks],
                    "db_path": str(store.path),
                    "schema_version": schema_version(store),
                    "audit_log": store.audit_log(limit=50),
                }
            )

    @app.get("/api/audit")
    def api_audit(limit: int = 100) -> JSONResponse:
        with open_store(app) as store:
            return JSONResponse({"items": store.audit_log(limit=limit), "count": limit})

    @app.get("/api/links")
    def api_links() -> JSONResponse:
        with open_store(app) as store:
            links = list_links(store)
            return JSONResponse(
                {
                    "items": [serialize_link(link) for link in links],
                    "count": len(links),
                }
            )

    @app.post("/api/links")
    def api_link_create(payload: ApiLinkWrite) -> JSONResponse:
        with open_store(app) as store:
            try:
                link = store.link(
                    payload.from_id.strip(),
                    payload.to_id.strip(),
                    rel=payload.rel.strip() or "relates-to",
                )
            except Exception as exc:
                return json_error(str(exc), status_code=400)
            return JSONResponse({"ok": True, "link": serialize_link(link)}, status_code=201)

    @app.delete("/api/links")
    def api_link_delete(payload: ApiLinkWrite) -> JSONResponse:
        with open_store(app) as store:
            removed = store.unlink(
                payload.from_id.strip(),
                payload.to_id.strip(),
                rel=payload.rel.strip() or None,
            )
            return JSONResponse({"ok": True, "removed": removed})

    # ── Graph ──────────────────────────────────────────────────────────

    @app.get("/api/graph")
    def api_graph(root_id: str | None = None, depth: int = 2) -> JSONResponse:
        with open_store(app) as store:
            type_colors = {
                "project": "#1d9bf0",
                "decision": "#00ba7c",
                "lesson": "#f4212e",
                "glossary": "#ffd400",
                "person": "#7856ff",
                "faq": "#0891b2",
            }
            default_color = "#536471"
            if root_id:
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
                active_docs = store.export_all(include_deleted=False)
                links = list_links(store)
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

    @app.get("/graph", response_class=HTMLResponse)
    def graph_page(request: Request) -> HTMLResponse:
        return render(request, "graph.html")

    # ── Overview ───────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    def overview(request: Request) -> HTMLResponse:
        with open_store(app) as store:
            payload = overview_payload(store)
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

    # ── Links HTML pages ───────────────────────────────────────────────

    @app.get("/links", response_class=HTMLResponse)
    def links_page(
        request: Request,
        doc_id: str = "",
        rel: str = "",
    ) -> HTMLResponse:
        with open_store(app) as store:
            docs = store.list(limit=500)
            links = list_links(store)
            if doc_id:
                links = [link for link in links if link.from_id == doc_id or link.to_id == doc_id]
            if rel:
                links = [link for link in links if link.rel == rel]
            rel_options = sorted({link.rel for link in list_links(store)})
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
        with open_store(app) as store:
            store.link(from_id.strip(), to_id.strip(), rel=rel.strip() or "relates-to")
        return RedirectResponse(url="/links?created=1", status_code=303)

    @app.post("/links/delete", response_class=HTMLResponse)
    async def links_delete(
        from_id: str = Form(...),
        to_id: str = Form(...),
        rel: str = Form(default=""),
    ) -> RedirectResponse:
        with open_store(app) as store:
            store.unlink(from_id.strip(), to_id.strip(), rel=rel.strip() or None)
        return RedirectResponse(url="/links?deleted=1", status_code=303)

    # ── Import / Export ─────────────────────────────────────────────────

    from kb_mcp_lite.md_io import export_dir, import_dir

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
            with open_store(app) as store:
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
            with open_store(app) as store:
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

    # ── Settings ───────────────────────────────────────────────────────

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request) -> HTMLResponse:
        with open_store(app) as store:
            doctor_report = store.doctor()
            embedder = getattr(store, "_embedder", None)
            from kb_mcp_lite.config import config_path

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
                    "version": schema_version(store),
                    "audit_log": store.audit_log(limit=50),
                    "config_path": str(cfg_path),
                    "config_content": cfg_content,
                },
            )

    # ── Vault management ───────────────────────────────────────────────

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
            return json_error("vault name required", status_code=400)
        mgr = VaultManager()
        try:
            mgr.switch(name)
            new_path = str(mgr.resolve_path(name))
            app.state.store_path = new_path
            return JSONResponse({"ok": True, "current": name, "store_path": new_path})
        except Exception as e:
            return json_error(str(e), status_code=400)

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
            return json_error(str(e), status_code=500)

    @app.post("/api/vaults/commit")
    def api_vault_commit(payload: dict[str, str]) -> JSONResponse:
        message = payload.get("message", "admin commit")
        mgr = VaultManager()
        name = mgr.get_current()
        try:
            output = mgr.commit(message=message, name=name)
            return JSONResponse({"ok": True, "output": output})
        except Exception as e:
            return json_error(str(e), status_code=500)

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
            return json_error(str(e), status_code=500)
        finally:
            store.close()

    # ── Config ─────────────────────────────────────────────────────────

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
            return json_error("content is required", status_code=400)
        from kb_mcp_lite.config import config_path

        p = config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return JSONResponse({"ok": True, "path": str(p)})
