from __future__ import annotations

import io
import zipfile
from pathlib import Path

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


def test_overview_renders(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    client = TestClient(create_app(store=store))

    response = client.get("/")

    assert response.status_code == 200
    assert "Active docs" in response.text
    assert "Sample Project" in response.text


def test_document_create_and_update(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    client = TestClient(create_app(store=store))

    create_response = client.post(
        "/documents",
        data={
            "id": "",
            "type": "faq",
            "title": "How do we ship?",
            "tags": "release, process",
            "source": "",
            "body": "Run tests first.",
        },
        follow_redirects=False,
    )

    assert create_response.status_code == 303
    created_id = "faq/how-do-we-ship"
    assert store.get(created_id).title == "How do we ship?"

    update_response = client.post(
        f"/documents/{created_id}",
        data={
            "title": "How do we ship safely?",
            "tags": "release,process",
            "source": "docs/release.md",
            "body": "Run tests and verify migrations.",
            "action": "save",
        },
        follow_redirects=False,
    )

    assert update_response.status_code == 303
    updated_doc = store.get(created_id)
    assert updated_doc.title == "How do we ship safely?"
    assert updated_doc.source == "docs/release.md"


def test_search_lab_and_import_export(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    client = TestClient(create_app(store=store))

    search_response = client.get("/search", params={"query": "SQLite", "mode": "hybrid"})
    assert search_response.status_code == 200
    assert "Sample Project" in search_response.text

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
        "/imports",
        files={"archive": ("vault.zip", archive_buffer.getvalue(), "application/zip")},
        data={},
    )
    assert import_response.status_code == 200
    assert "Imported Project" not in import_response.text
    assert store.get("proj/imported-project").title == "Imported Project"

    export_response = client.post("/exports")
    assert export_response.status_code == 200
    assert "Written" in export_response.text


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


def test_links_page_and_link_mutation(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    client = TestClient(create_app(store=store))

    page_response = client.get("/links")
    assert page_response.status_code == 200
    assert "Relationships" in page_response.text

    create_response = client.post(
        "/links",
        data={
            "from_id": "proj/sample",
            "to_id": "lesson/failure-mode",
            "rel": "references",
        },
        follow_redirects=False,
    )
    assert create_response.status_code == 303
    assert any(link.rel == "references" for link in store.outlinks("proj/sample"))

    delete_response = client.post(
        "/links/delete",
        data={
            "from_id": "proj/sample",
            "to_id": "lesson/failure-mode",
            "rel": "references",
        },
        follow_redirects=False,
    )
    assert delete_response.status_code == 303
    assert not any(link.rel == "references" for link in store.outlinks("proj/sample"))


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


def test_flash_feedback_and_history_render(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    client = TestClient(create_app(store=store))

    create_response = client.post(
        "/documents",
        data={
            "id": "",
            "type": "faq",
            "title": "Flash doc",
            "tags": "ui",
            "source": "",
            "body": "hello",
        },
        follow_redirects=True,
    )
    assert create_response.status_code == 200
    assert "Document created" in create_response.text
    assert "Version history" in create_response.text
