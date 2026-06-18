"""Tests for ``kb_mcp.cli`` wired to :class:`SqliteStore` (Wave 2B).

Every test uses Click's CliRunner in-process. The store is injected via
``runner.invoke(cli, [...], obj={"store": store})`` with a temporary SQLite
database.

Exit codes follow docs/cli-reference.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from kb_mcp.cli import (
    EXIT_CONFLICT,
    EXIT_INTERNAL,
    EXIT_NOT_FOUND,
    EXIT_OK,
    EXIT_USAGE,
    EXIT_VALIDATION,
    cli,
)
from kb_mcp.schema import Document
from kb_mcp.store.sqlite import SqliteStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def store(tmp_path: Path):
    """A fresh SqliteStore backed by a temp DB."""
    db = tmp_path / "kb.db"
    s = SqliteStore(db)
    yield s
    s.close()


@pytest.fixture()
def sample_doc(store: SqliteStore) -> Document:
    """A pre-inserted document for read/link tests."""
    doc = Document(
        id="proj/test-doc",
        type="project",
        title="Test Doc",
        body="A test body with **markdown**.",
        tags=["test", "cli"],
    )
    store.add(doc)
    return doc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _invoke(
    runner: CliRunner,
    store: SqliteStore,
    args: list[str],
    input_text: str | None = None,
) -> click.testing.Result:
    return runner.invoke(cli, args, obj={"store": store}, input=input_text)


def _assert_json_ok(result: click.testing.Result) -> dict:
    assert result.exit_code == EXIT_OK, f"exit={result.exit_code}\n{result.output}"
    data = json.loads(result.output)
    assert data.get("ok") is True
    return data


def _assert_json_error(result: click.testing.Result, expected_exit: int) -> dict:
    assert result.exit_code == expected_exit, (
        f"expected exit {expected_exit}, got {result.exit_code}\n{result.output}"
    )
    data = json.loads(result.output)
    assert data.get("ok") is False
    return data


# ---------------------------------------------------------------------------
# kb init
# ---------------------------------------------------------------------------


class TestInit:
    """``kb init`` creates/touches the DB and runs doctor."""

    def test_init_happy_path(self, runner: CliRunner, store: SqliteStore) -> None:
        result = _invoke(runner, store, ["init"])
        assert result.exit_code == EXIT_OK
        assert "initialized" in result.output.lower()

    def test_init_json(self, runner: CliRunner, store: SqliteStore) -> None:
        result = _invoke(runner, store, ["init", "--json"])
        data = _assert_json_ok(result)
        assert data["force"] is False

    def test_init_force_no_confirm(self, runner: CliRunner, store: SqliteStore) -> None:
        result = _invoke(runner, store, ["init", "--force"])
        assert result.exit_code == EXIT_OK
        assert "(force)" in result.output

    def test_init_force_with_yes(self, runner: CliRunner, store: SqliteStore) -> None:
        result = _invoke(runner, store, ["init", "--force", "--yes"])
        assert result.exit_code == EXIT_OK
        assert "(force)" in result.output


# ---------------------------------------------------------------------------
# kb add
# ---------------------------------------------------------------------------


class TestAdd:
    """``kb add`` creates documents persisted to SQLite."""

    def test_add_happy_path(self, runner: CliRunner, store: SqliteStore) -> None:
        result = _invoke(
            runner, store, ["add", "--type", "project", "--title", "Hello World"]
        )
        assert result.exit_code == EXIT_OK
        assert "proj/hello-world" in result.output.strip()

    def test_add_with_body(self, runner: CliRunner, store: SqliteStore) -> None:
        result = _invoke(
            runner, store,
            ["add", "--type", "lesson", "--title", "Body Test", "--body", "Some content here."],
        )
        assert result.exit_code == EXIT_OK
        doc_id = result.output.strip()
        doc = store.get(doc_id)
        assert doc.body == "Some content here."

    def test_add_with_tags(self, runner: CliRunner, store: SqliteStore) -> None:
        result = _invoke(
            runner, store,
            ["add", "--type", "faq", "--title", "Tag Test", "--tags", "a,b,c"],
        )
        assert result.exit_code == EXIT_OK
        doc_id = result.output.strip()
        doc = store.get(doc_id)
        assert doc.tags == ["a", "b", "c"]

    def test_add_json(self, runner: CliRunner, store: SqliteStore) -> None:
        result = _invoke(
            runner, store,
            ["add", "--type", "decision", "--title", "JSON Test", "--json"],
        )
        data = _assert_json_ok(result)
        assert data["type"] == "decision"
        assert data["title"] == "JSON Test"
        assert "id" in data

    def test_add_duplicate_raises_conflict(
        self, runner: CliRunner, store: SqliteStore
    ) -> None:
        args = ["add", "--type", "project", "--title", "Dup"]
        r1 = _invoke(runner, store, args)
        assert r1.exit_code == EXIT_OK
        r2 = _invoke(runner, store, args)
        assert r2.exit_code == EXIT_CONFLICT
        assert "already exists" in r2.output

    def test_add_duplicate_json(self, runner: CliRunner, store: SqliteStore) -> None:
        args = ["add", "--type", "project", "--title", "DupJson", "--json"]
        _invoke(runner, store, args)
        r2 = _invoke(runner, store, args)
        data = _assert_json_error(r2, EXIT_CONFLICT)
        assert data["error"] == "duplicate"

    def test_add_body_from_stdin(self, runner: CliRunner, store: SqliteStore) -> None:
        result = _invoke(
            runner, store,
            ["add", "--type", "project", "--title", "Stdin Test"],
            input_text="stdin body here\n",
        )
        assert result.exit_code == EXIT_OK
        doc_id = result.output.strip().splitlines()[-1]
        doc = store.get(doc_id)
        assert doc.body == "stdin body here"

    def test_add_body_file(
        self, runner: CliRunner, store: SqliteStore, tmp_path: Path
    ) -> None:
        path = tmp_path / "body.md"
        path.write_text("file body content", encoding="utf-8")
        result = _invoke(
            runner, store,
            ["add", "--type", "project", "--title", "File Test", "--body-file", str(path)],
        )
        assert result.exit_code == EXIT_OK
        doc_id = result.output.strip()
        doc = store.get(doc_id)
        assert doc.body == "file body content"

    def test_add_body_and_body_file_mutually_exclusive(
        self, runner: CliRunner, store: SqliteStore
    ) -> None:
        result = _invoke(
            runner, store,
            [
                "add",
                "--type", "project",
                "--title", "Conflict",
                "--body", "x",
                "--body-file", "/dev/null",
            ],
        )
        assert result.exit_code == EXIT_USAGE
        assert "mutually exclusive" in result.output

    def test_add_missing_type(self, runner: CliRunner, store: SqliteStore) -> None:
        result = _invoke(runner, store, ["add", "--title", "No Type"])
        assert result.exit_code == EXIT_USAGE

    def test_add_missing_title(self, runner: CliRunner, store: SqliteStore) -> None:
        result = _invoke(runner, store, ["add", "--type", "project"])
        assert result.exit_code == EXIT_USAGE

    def test_add_body_file_not_found(
        self, runner: CliRunner, store: SqliteStore
    ) -> None:
        result = _invoke(
            runner, store,
            ["add", "--type", "project", "--title", "Missing", "--body-file", "/nonexistent/path.md"],
        )
        assert result.exit_code == EXIT_USAGE
        assert "not found" in result.output


# ---------------------------------------------------------------------------
# kb get
# ---------------------------------------------------------------------------


class TestGet:
    """``kb get`` fetches a single document by id."""

    def test_get_happy_path(
        self, runner: CliRunner, store: SqliteStore, sample_doc: Document
    ) -> None:
        result = _invoke(runner, store, ["get", sample_doc.id])
        assert result.exit_code == EXIT_OK
        assert sample_doc.title in result.output
        assert sample_doc.id in result.output
        assert sample_doc.body in result.output
    def test_get_json(
        self, runner: CliRunner, store: SqliteStore, sample_doc: Document
    ) -> None:
        """``--json`` returns the full document as JSON (not an ok wrapper)."""
        result = _invoke(runner, store, ["get", sample_doc.id, "--json"])
        assert result.exit_code == EXIT_OK, f"exit={result.exit_code}\n{result.output}"
        data = json.loads(result.output)
        assert data["id"] == sample_doc.id
        assert data["title"] == sample_doc.title
        assert data["body"] == sample_doc.body

    def test_get_not_found(self, runner: CliRunner, store: SqliteStore) -> None:
        result = _invoke(runner, store, ["get", "nonexistent-id"])
        assert result.exit_code == EXIT_NOT_FOUND
        assert "not found" in result.output

    def test_get_not_found_json(self, runner: CliRunner, store: SqliteStore) -> None:
        result = _invoke(runner, store, ["get", "nonexistent-id", "--json"])
        data = _assert_json_error(result, EXIT_NOT_FOUND)
        assert data["error"] == "not_found"


# ---------------------------------------------------------------------------
# kb search
# ---------------------------------------------------------------------------


class TestSearch:
    """``kb search`` performs FTS5 full-text search."""

    def test_search_happy_path(
        self, runner: CliRunner, store: SqliteStore, sample_doc: Document
    ) -> None:
        result = _invoke(runner, store, ["search", "Test"])
        assert result.exit_code == EXIT_OK
        assert sample_doc.id in result.output

    def test_search_no_results(self, runner: CliRunner, store: SqliteStore) -> None:
        result = _invoke(runner, store, ["search", "zzzzzz"])
        assert result.exit_code == EXIT_OK
        assert "no results" in result.output

    def test_search_json(
        self, runner: CliRunner, store: SqliteStore, sample_doc: Document
    ) -> None:
        result = _invoke(runner, store, ["search", "Test", "--json"])
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["id"] == sample_doc.id

    def test_search_by_type(
        self, runner: CliRunner, store: SqliteStore, sample_doc: Document
    ) -> None:
        store.add(Document(id="dec/other", type="decision", title="Other", body="x"))
        result = _invoke(runner, store, ["search", "Other", "--type", "decision"])
        assert result.exit_code == EXIT_OK
        assert "dec/other" in result.output
        assert sample_doc.id not in result.output

    def test_search_by_tag(
        self, runner: CliRunner, store: SqliteStore, sample_doc: Document
    ) -> None:
        result = _invoke(
            runner, store, ["search", "Test", "--tag", "test", "--tag", "cli"]
        )
        assert result.exit_code == EXIT_OK
        assert sample_doc.id in result.output

    def test_search_limit(self, runner: CliRunner, store: SqliteStore) -> None:
        for i in range(5):
            store.add(
                Document(id=f"proj/item-{i}", type="project", title=f"Item {i}", body=f"body {i}")
            )
        result = _invoke(runner, store, ["search", "body", "--limit", "2", "--json"])
        data = json.loads(result.output)
        assert len(data) == 2

    def test_search_empty_query_validation(
        self, runner: CliRunner, store: SqliteStore
    ) -> None:
        result = _invoke(runner, store, ["search", ""])
        assert result.exit_code == EXIT_VALIDATION


# ---------------------------------------------------------------------------
# kb list
# ---------------------------------------------------------------------------


class TestList:
    """``kb list`` returns documents sorted by updated_at DESC."""

    def test_list_empty(self, runner: CliRunner, store: SqliteStore) -> None:
        result = _invoke(runner, store, ["list"])
        assert result.exit_code == EXIT_OK
        assert "no documents" in result.output

    def test_list_with_docs(
        self, runner: CliRunner, store: SqliteStore, sample_doc: Document
    ) -> None:
        result = _invoke(runner, store, ["list"])
        assert result.exit_code == EXIT_OK
        assert sample_doc.id in result.output
        assert sample_doc.type in result.output
        assert sample_doc.title in result.output

    def test_list_json(
        self, runner: CliRunner, store: SqliteStore, sample_doc: Document
    ) -> None:
        result = _invoke(runner, store, ["list", "--json"])
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == sample_doc.id

    def test_list_by_type(self, runner: CliRunner, store: SqliteStore) -> None:
        store.add(Document(id="proj/a", type="project", title="A", body="x"))
        store.add(Document(id="dec/b", type="decision", title="B", body="x"))
        result = _invoke(runner, store, ["list", "--type", "decision", "--json"])
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["id"] == "dec/b"

    def test_list_by_tag(self, runner: CliRunner, store: SqliteStore) -> None:
        store.add(Document(id="proj/t1", type="project", title="T1", body="x", tags=["a"]))
        store.add(Document(id="proj/t2", type="project", title="T2", body="x", tags=["a", "b"]))
        result = _invoke(
            runner, store, ["list", "--tag", "a", "--tag", "b", "--json"]
        )
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["id"] == "proj/t2"

    def test_list_limit_offset(self, runner: CliRunner, store: SqliteStore) -> None:
        for i in range(5):
            store.add(
                Document(id=f"proj/item-{i}", type="project", title=f"Item {i}", body="x")
            )
        result = _invoke(runner, store, ["list", "--limit", "2", "--offset", "1", "--json"])
        data = json.loads(result.output)
        assert len(data) == 2

    def test_list_invalid_limit(self, runner: CliRunner, store: SqliteStore) -> None:
        result = _invoke(runner, store, ["list", "--limit", "-1"])
        assert result.exit_code == EXIT_VALIDATION


# ---------------------------------------------------------------------------
# kb link
# ---------------------------------------------------------------------------


class TestLink:
    """``kb link`` creates typed edges between documents."""

    def test_link_happy_path(
        self, runner: CliRunner, store: SqliteStore, sample_doc: Document
    ) -> None:
        store.add(Document(id="dec/target", type="decision", title="Target", body="x"))
        result = _invoke(
            runner, store, ["link", "--from", sample_doc.id, "--to", "dec/target"]
        )
        assert result.exit_code == EXIT_OK
        assert "relates-to" in result.output

    def test_link_json(
        self, runner: CliRunner, store: SqliteStore, sample_doc: Document
    ) -> None:
        store.add(Document(id="dec/target", type="decision", title="Target", body="x"))
        result = _invoke(
            runner, store, ["link", "--from", sample_doc.id, "--to", "dec/target", "--json"]
        )
        data = _assert_json_ok(result)
        assert data["from"] == sample_doc.id
        assert data["to"] == "dec/target"
        assert data["rel"] == "relates-to"

    def test_link_custom_rel(
        self, runner: CliRunner, store: SqliteStore, sample_doc: Document
    ) -> None:
        store.add(Document(id="dec/target", type="decision", title="Target", body="x"))
        result = _invoke(
            runner, store,
            ["link", "--from", sample_doc.id, "--to", "dec/target", "--rel", "depends-on"],
        )
        assert result.exit_code == EXIT_OK
        assert "depends-on" in result.output

    def test_link_not_found(self, runner: CliRunner, store: SqliteStore) -> None:
        result = _invoke(
            runner, store, ["link", "--from", "does/not-exist", "--to", "also/nope"]
        )
        assert result.exit_code == EXIT_NOT_FOUND


# ---------------------------------------------------------------------------
# kb doctor
# ---------------------------------------------------------------------------


class TestDoctor:
    """``kb doctor`` runs health checks on the DB."""

    def test_doctor_ok(self, runner: CliRunner, store: SqliteStore, sample_doc: Document) -> None:
        result = _invoke(runner, store, ["doctor"])
        assert result.exit_code == EXIT_OK
        assert "OK" in result.output

    def test_doctor_json(self, runner: CliRunner, store: SqliteStore, sample_doc: Document) -> None:
        result = _invoke(runner, store, ["doctor", "--json"])
        data = json.loads(result.output)
        assert data["ok"] is True
        assert len(data["checks"]) > 0


# ---------------------------------------------------------------------------
# Cross-invocation persistence
# ---------------------------------------------------------------------------


class TestCrossInvocation:
    """Verify that data persists across separate CliRunner invocations (simulating separate CLI calls)."""

    def test_add_then_get_different_invocation(
        self, runner: CliRunner, store: SqliteStore, tmp_path: Path
    ) -> None:
        """Add a doc in one invocation, get it in another — same store instance."""
        # First invocation: add
        r1 = _invoke(
            runner, store,
            ["add", "--type", "project", "--title", "Persist Test", "--body", "persistent body"],
        )
        assert r1.exit_code == EXIT_OK
        doc_id = r1.output.strip()

        # Second invocation: get
        r2 = _invoke(runner, store, ["get", doc_id])
        assert r2.exit_code == EXIT_OK
        assert "persistent body" in r2.output

    def test_add_then_search_different_invocation(
        self, runner: CliRunner, store: SqliteStore
    ) -> None:
        """Add a doc, then search for it in a separate invoke."""
        _invoke(
            runner, store,
            ["add", "--type", "lesson", "--title", "Search Me", "--body", "searchable content"],
        )
        result = _invoke(runner, store, ["search", "searchable", "--json"])
        assert result.exit_code == EXIT_OK
        data = json.loads(result.output)
        assert len(data) >= 1
        assert data[0]["title"] == "Search Me"

    def test_list_persists_across_invocations(
        self, runner: CliRunner, store: SqliteStore
    ) -> None:
        """Add 3 docs across 3 invocations, list all in a 4th."""
        for i in range(3):
            _invoke(
                runner, store,
                ["add", "--type", "project", "--title", f"Doc {i}"],
            )
        result = _invoke(runner, store, ["list", "--json"])
        assert result.exit_code == EXIT_OK
        data = json.loads(result.output)
        assert len(data) == 3


# ---------------------------------------------------------------------------
# kb import / export stubs
# ---------------------------------------------------------------------------


class TestImportExportStubs:
    """kb import and export are stubs that exit with code 5."""

    def test_import_not_implemented(self, runner: CliRunner, store: SqliteStore) -> None:
        result = _invoke(runner, store, ["import", "/tmp"])
        assert result.exit_code == EXIT_INTERNAL

    def test_export_not_implemented(self, runner: CliRunner, store: SqliteStore) -> None:
        result = _invoke(runner, store, ["export", "/tmp"])
        assert result.exit_code == EXIT_INTERNAL


# ---------------------------------------------------------------------------
# kb serve stub
# ---------------------------------------------------------------------------


class TestServeStub:
    """kb serve is a stub that exits with code 5."""

    def test_serve_not_implemented(self, runner: CliRunner, store: SqliteStore) -> None:
        result = _invoke(runner, store, ["serve"])
        assert result.exit_code == EXIT_INTERNAL
        assert "not yet implemented" in (result.output + result.stderr).lower()
