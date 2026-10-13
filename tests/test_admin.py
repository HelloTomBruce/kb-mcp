"""Tests for the admin console: SPA serving plus the /api/* JSON surface.

The legacy Jinja2 SSR pages were removed; every former page-level test now
asserts against the corresponding API endpoint.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kb_mcp_lite.admin import create_app
from kb_mcp_lite.schema import Document
from kb_mcp_lite.store.sqlite import SqliteStore


def make_store(tmp_path: Path) -> SqliteStore:
    store = SqliteStore(tmp_path / "kb.db")
    store.add(
        Document(
            id="proj/sample",
            type="project",
            title="Sample Project",
            body="SQLite FTS and MCP integration",
            tags=["sqlite", "mcp"],
        )
    )
    store.add(
        Document(
            id="lesson/failure-mode",
            type="lesson",
            title="Failure mode",
            body="Agents should consult the knowledge base before editing.",
            tags=["agents"],
        )
    )
    store.link("lesson/failure-mode", "proj/sample", rel="relates-to")
    return store


def test_root_redirects_to_spa(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    client = TestClient(create_app(store=store))

    res_root = client.get("/", follow_redirects=False)
    assert res_root.status_code == 302
    assert res_root.headers["location"] == "/app"


def test_search_and_import_export_api(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    client = TestClient(create_app(store=store))

    search_response = client.get("/api/search", params={"query": "SQLite", "mode": "hybrid"})
    assert search_response.status_code == 200
    search_payload = search_response.json()
    assert search_payload["count"] >= 1
    assert any(hit["doc"]["id"] == "proj/sample" for hit in search_payload["hits"])

    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as zf:
        zf.writestr(
            "entry.md",
            "---\n"
            "type: project\n"
            "title: Imported Project\n"
            "tags: [imported]\n"
            "---\n\n"
            "Imported body.\n",
        )
    archive_buffer.seek(0)

    import_response = client.post(
        "/api/imports/upload",
        files={"archive": ("vault.zip", archive_buffer.getvalue(), "application/zip")},
        data={},
    )
    assert import_response.status_code == 200
    assert import_response.json()["ok"] is True
    # Now filename = id: the zip contains "entry.md" → id = "entry"
    assert store.get("entry").title == "Imported Project"

    export_response = client.get("/api/exports/download")
    assert export_response.status_code == 200
    assert export_response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(export_response.content)) as zf:
        assert len(zf.namelist()) >= 1


def test_admin_json_api(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    client = TestClient(create_app(store=store))

    stats_response = client.get("/api/stats")
    assert stats_response.status_code == 200
    stats_payload = stats_response.json()
    assert stats_payload["stats"]["documents"] == 2

    docs_response = client.get("/api/docs", params={"q": "SQLite"})
    assert docs_response.status_code == 200
    docs_payload = docs_response.json()
    assert docs_payload["count"] >= 1
    assert any(item["id"] == "proj/sample" for item in docs_payload["items"])

    health_response = client.get("/api/health")
    assert health_response.status_code == 200
    health_payload = health_response.json()
    assert "checks" in health_payload
    assert "audit_log" in health_payload

    links_response = client.get("/api/links")
    assert links_response.status_code == 200
    links_payload = links_response.json()
    assert links_payload["count"] == 1
    assert links_payload["items"][0]["to_id"] == "proj/sample"


def test_admin_json_write_api(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    client = TestClient(create_app(store=store))

    create_response = client.post(
        "/api/docs",
        json={
            "type": "faq",
            "title": "How do we release?",
            "tags": ["release", "ops"],
            "source": "docs/release.md",
            "body": "Run tests and verify the changelog.",
        },
    )
    assert create_response.status_code == 201
    created_payload = create_response.json()
    created_id = created_payload["doc"]["id"]
    assert created_payload["ok"] is True
    assert store.get(created_id).title == "How do we release?"

    patch_response = client.patch(
        f"/api/docs/{created_id}",
        json={
            "title": "How do we release safely?",
            "tags": ["release", "ops", "checklist"],
        },
    )
    assert patch_response.status_code == 200
    patched_payload = patch_response.json()
    assert patched_payload["doc"]["title"] == "How do we release safely?"
    assert "checklist" in patched_payload["doc"]["tags"]

    delete_response = client.request("DELETE", f"/api/docs/{created_id}")
    assert delete_response.status_code == 200
    deleted_payload = delete_response.json()
    assert deleted_payload["doc"]["deleted_at"] is not None

    detail_response = client.get(f"/api/docs/{created_id}")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert len(detail_payload["history"]) >= 3

    link_response = client.post(
        "/api/links",
        json={
            "from_id": "proj/sample",
            "to_id": "lesson/failure-mode",
            "rel": "references",
        },
    )
    assert link_response.status_code == 201
    assert any(link.rel == "references" for link in store.outlinks("proj/sample"))

    unlink_response = client.request(
        "DELETE",
        "/api/links",
        json={
            "from_id": "proj/sample",
            "to_id": "lesson/failure-mode",
            "rel": "references",
        },
    )
    assert unlink_response.status_code == 200
    assert unlink_response.json()["removed"] == 1
    assert not any(link.rel == "references" for link in store.outlinks("proj/sample"))


def test_scheduler_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = make_store(tmp_path)
    client = TestClient(create_app(store=store))

    # Status API
    status_res = client.get("/api/scheduler/status")
    assert status_res.status_code == 200
    assert "running" in status_res.json()

    # Tasks API
    tasks_res = client.get("/api/scheduler/tasks")
    assert tasks_res.status_code == 200
    assert tasks_res.json()["ok"] is True
    assert len(tasks_res.json()["tasks"]) >= 1

    # History API
    hist_res = client.get("/api/scheduler/history")
    assert hist_res.status_code == 200
    assert hist_res.json()["ok"] is True

    # Run task API
    run_res = client.post("/api/scheduler/run", json={"task_name": "auto-reindex"})
    assert run_res.status_code == 200
    assert run_res.json()["ok"] is True
    assert run_res.json()["task_name"] == "auto-reindex"


def test_embed_api(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    client = TestClient(create_app(store=store))

    # Embed status API
    status_res = client.get("/api/embed/status")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["ok"] is True
    assert "pending" in status_data
    assert "in_progress" in status_data
    assert "done" in status_data
    assert "failed" in status_data

    # Embed retry API
    retry_res = client.post("/api/embed/retry", json={})
    assert retry_res.status_code == 200
    assert retry_res.json()["ok"] is True
    assert "retried" in retry_res.json()


def test_types_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Use isolated config path in tmp_path
    monkeypatch.setenv("KB_MCP_CONFIG", str(tmp_path / "config.yaml"))

    store = make_store(tmp_path)
    client = TestClient(create_app(store=store))

    # 1. List API
    list_res = client.get("/api/types")
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert list_data["ok"] is True
    assert list_data["stats"]["builtin"] >= 9
    assert any(t["name"] == "project" for t in list_data["types"])

    # 2. Create custom type
    create_res = client.post(
        "/api/types",
        json={
            "name": "requirement",
            "label": "需求文档",
            "description": "产品功能规格与变更记录",
            "color": "#0284c7",
        },
    )
    assert create_res.status_code == 201
    assert create_res.json()["ok"] is True
    assert create_res.json()["type"]["name"] == "requirement"

    # Cannot recreate built-in or duplicate type
    dup_res = client.post(
        "/api/types",
        json={"name": "requirement", "label": "重复需求"},
    )
    assert dup_res.status_code == 409

    builtin_dup = client.post(
        "/api/types",
        json={"name": "project", "label": "项目"},
    )
    assert builtin_dup.status_code == 409

    # 3. Update custom type
    update_res = client.put(
        "/api/types/requirement",
        json={
            "label": "产品需求规格",
            "description": "需求规格说明书",
            "color": "#0369a1",
        },
    )
    assert update_res.status_code == 200
    assert update_res.json()["ok"] is True
    assert update_res.json()["type"]["label"] == "产品需求规格"

    # 4. Delete built-in type forbidden
    del_builtin_res = client.delete("/api/types/project")
    assert del_builtin_res.status_code == 400

    # 4.1 Delete custom type with active documents forbidden
    store.add(Document(id="req-1", type="requirement", title="Auth Requirement"))
    del_in_use_res = client.delete("/api/types/requirement")
    assert del_in_use_res.status_code == 400
    assert "正在使用" in del_in_use_res.json()["error"]

    # 5. Delete custom type succeeds once documents are removed
    store.delete("req-1")
    del_custom_res = client.delete("/api/types/requirement")
    assert del_custom_res.status_code == 200
    assert del_custom_res.json()["ok"] is True
    assert del_custom_res.json()["deleted"] == "requirement"


def test_type_display_labels_in_api(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    client = TestClient(create_app(store=store))

    # Types API exposes localized display labels for the SPA
    types_res = client.get("/api/types")
    assert types_res.status_code == 200
    types = {t["name"]: t for t in types_res.json()["types"]}
    assert types["project"]["label"] == "项目/规划"
    assert types["lesson"]["label"] == "经验复盘"


def test_spa_routes(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    client = TestClient(create_app(store=store))

    # Check SPA index route
    app_res = client.get("/app")
    assert app_res.status_code == 200
    assert "kb-mcp Console" in app_res.text
    assert "root" in app_res.text

    # Check SPA sub-route
    sub_res = client.get("/app/docs")
    assert sub_res.status_code == 200
    assert "kb-mcp Console" in sub_res.text


def test_graph_api(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    client = TestClient(create_app(store=store))

    # Full graph
    full_res = client.get("/api/graph")
    assert full_res.status_code == 200
    payload = full_res.json()
    assert len(payload["nodes"]) == 2
    assert len(payload["edges"]) == 1

    # Rooted subgraph
    sub_res = client.get("/api/graph", params={"root_id": "proj/sample", "depth": 1})
    assert sub_res.status_code == 200
    sub_payload = sub_res.json()
    assert any(node["id"] == "proj/sample" for node in sub_payload["nodes"])


def test_git_diff_api(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    client = TestClient(create_app(store=store))

    diff_res = client.get("/api/git/diff")
    assert diff_res.status_code == 200
    payload = diff_res.json()
    assert payload["ok"] is True
    assert "diff" in payload
    assert "pending_diffs" in payload


def test_custom_types_vault_isolation(tmp_path: Path) -> None:
    store1 = make_store(tmp_path / "vault1")
    store2 = make_store(tmp_path / "vault2")

    client1 = TestClient(create_app(store=store1))
    client2 = TestClient(create_app(store=store2))

    # Add custom type in vault1
    res1 = client1.post(
        "/api/types",
        json={"name": "v1_only", "label": "V1 Type", "color": "#112233"},
    )
    assert res1.status_code == 201

    # Check vault1 has v1_only
    list1 = client1.get("/api/types").json()
    assert any(t["name"] == "v1_only" for t in list1["types"])

    # Check vault2 DOES NOT have v1_only
    list2 = client2.get("/api/types").json()
    assert not any(t["name"] == "v1_only" for t in list2["types"])

    # Add custom type in vault2
    res2 = client2.post(
        "/api/types",
        json={"name": "v2_only", "label": "V2 Type", "color": "#445566"},
    )
    assert res2.status_code == 201

    # Check vault2 has v2_only and vault1 does not
    assert any(t["name"] == "v2_only" for t in client2.get("/api/types").json()["types"])
    assert not any(t["name"] == "v2_only" for t in client1.get("/api/types").json()["types"])
