"""FastAPI admin console for kb-mcp."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from kb_mcp_lite.admin._helpers import (
    DOC_TYPES,
    SEARCH_MODES,
    create_default_store,
    schema_version,
)
from kb_mcp_lite.store.sqlite import SqliteStore
from kb_mcp_lite.vault import get_current_vault_name

_THIS_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = _THIS_DIR.parent  # kb_mcp_lite/
TEMPLATES_DIR = PACKAGE_DIR / "templates" / "admin"
STATIC_DIR = PACKAGE_DIR / "static"


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

    app.state.store_path = str((store or create_default_store()).path)

    def render(
        request: Any,
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

    from kb_mcp_lite.admin.routes_docs import register_doc_routes
    from kb_mcp_lite.admin.routes_meta import register_meta_routes

    register_doc_routes(app, render)
    register_meta_routes(app, render)

    return app


def run_admin(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    store: SqliteStore | None = None,
) -> None:
    import uvicorn

    app = create_app(store=store)
    uvicorn.run(app, host=host, port=port, log_level="info")
