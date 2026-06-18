"""Tests for kb_mcp.cli with StubStore (Wave 1C).

Every test uses Click's CliRunner in-process (no subprocess, no mocks).
The store is injected via ``runner.invoke(..., obj={"store": store})``.

Exit codes follow docs/cli-reference.md:

====  =================================================================
0    Success
2    Validation error
3    Not found
4    Conflict (duplicate)
5    Internal error (DB / I/O)  -  also used for "not implemented" stubs
64   Usage error
====  =================================================================
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

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
from kb_mcp.schema import Document, DuplicateError, NotFoundError, ValidationError
from kb_mcp.stub_store import StubStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def runner() -> CliRunner:
    """A fresh CliRunner."""
    return CliRunner()


@pytest.fixture()
def store() -> Iterator[StubStore]:
    """A fresh StubStore."""
    s = StubStore()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def sample_doc(store: StubStore) -> Document:
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
    store: StubStore,
    args: list[str],
    input_text: str | None = None,
) -> click.testing.Result:
    """Invoke the CLI with a injected StubStore."""
    return runner.invoke(cli, args, obj={"store": store}, input=input_text)


def _assert_json_ok(result: click.testing.Result) -> dict:
    """Assert the result exited 0 and parsed JSON has ok=True."""
    assert result.exit_code == EXIT_OK, f"exit={result.exit_code}\n{result.output}"
    data = json.loads(result.output)
    assert data.get("ok") is True
    return data


def _assert_json_error(
    result: click.testing.Result, expected_exit: int
) -> dict:
    """Assert the result exited with expected code and parsed JSON has ok=False."""
    assert (
        result.exit_code == expected_exit
    ), f"expected exit {expected_exit}, got {result.exit_code}\n{result.output}"
    data = json.loads(result.output)
    assert data.get("ok") is False
    return data


# ---------------------------------------------------------------------------
# kb init
# ---------------------------------------------------------------------------


class TestInit:
    """"kb init`` is a no-op with StubStore but accepts all flags."""

    def test_init_happy_path(self, runner: CliRunner, store: StubStore) -> None:
        """Default init succeeds and prints a confirmation."""
        result = _invoke(runner, store, ["init"])
        assert result.exit_code == EXIT_OK
        assert "initialized" in result.output

    def test_init_json(self, runner: CliRunner, store: StubStore) -> None:
        """--json`` produces valid JSON with ok=True."""
        result = _invoke(runner, store, ["init", "--json"])
        data = _assert_json_ok(result)
        assert data["force"] is False

    def test_init_force_no_confirm_in_runner(
        self, runner: CliRunner, store: StubStore
    ) -> None:
        """"--force`` without ``--yes`` in CliRunner skips the interactive
        prompt (stdin is not a tty) and succeeds."""
        result = _invoke(runner, store, ["init", "--force"])
        assert result.exit_code == EXIT_OK
        assert "(force)" in result.output

    def test_init_force_with_yes(self, runner: CliRunner, store: StubStore) -> None:
        """"--force --yes`` succeeds without prompting."""
        result = _invoke(runner, store, ["init", "--force", "--yes"])
        assert result.exit_code == EXIT_OK
        assert "(force)" in result.output


# ---------------------------------------------------------------------------
# kb add
# ---------------------------------------------------------------------------


class TestAdd:
    """"kb add`` creates documents and returns the generated id."""

    def test_add_happy_path(self, runner: CliRunner, store: StubStore) -> None:
        """Minimal add prints the generated id."""
        result = _invoke(
            runner,
            store,
            ["add", "--type", "project", "--title", "Hello World"],
        )
        assert result.exit_code == EXIT_OK
        assert result.output.strip() == "proj/hello-world"

    def test_add_with_body(self, runner: CliRunner, store: StubStore) -> None:
        """"--body`` is stored and reflected in get."""
        result = _invoke(
            runner,
            store,
            [
                "add",
                "--type",
                "lesson",
                "--title",
                "Body Test",
                "--body",
                "Some content here.",
            ],
        )
        assert result.exit_code == EXIT_OK
        doc_id = result.output.strip()
        doc = store.get(doc_id)
        assert doc.body == "Some content here."

    def test_add_with_tags(self, runner: CliRunner, store: StubStore) -> None:
        """"--tags`` comma list is parsed."""
        result = _invoke(
            runner,
            store,
            [
                "add",
                "--type",
                "faq",
                "--title",
                "Tag Test",
                "--tags",
                "a,b,c",
            ],
        )
        assert result.exit_code == EXIT_OK
        doc_id = result.output.strip()
        doc = store.get(doc_id)
        assert doc.tags == ["a", "b", "c"]

    def test_add_with_source(self, runner: CliRunner, store: StubStore) -> None:
        """"--source`` enables idempotent re-import."""
        result = _invoke(
            runner,
            store,
            [
                "add",
                "--type",
                "project",
                "--title",
                "Source Test",
                "--source",
                "src/x.md",
            ],
        )
        assert result.exit_code == EXIT_OK

    def test_add_json(self, runner: CliRunner, store: StubStore) -> None:
        """"--json`` returns structured output."""
        result = _invoke(
            runner,
            store,
            [
                "add",
                "--type",
                "decision",
                "--title",
                "JSON Test",
                "--json",
            ],
        )
        data = _assert_json_ok(result)
        assert data["type"] == "decision"
        assert data["title"] == "JSON Test"
        assert "id" in data

    def test_add_duplicate_raises_conflict(
        self, runner: CliRunner, store: StubStore
    ) -> None:
        """Adding the same (type, title) twice exits 4."""
        args = ["add", "--type", "project", "--title", "Dup"]
        r1 = _invoke(runner, store, args)
        assert r1.exit_code == EXIT_OK
        r2 = _invoke(runner, store, args)
        assert r2.exit_code == EXIT_CONFLICT
        assert "already exists" in r2.output

    def test_add_duplicate_json(self, runner: CliRunner, store: StubStore) -> None:
        """Duplicate with ``--json`` returns machine-readable error."""
        args = ["add", "--type", "project", "--title", "DupJson", "--json"]
        _invoke(runner, store, args)
        r2 = _invoke(runner, store, args)
        data = _assert_json_error(r2, EXIT_CONFLICT)
        assert data["error"] == "duplicate"

    def test_add_body_from_stdin(self, runner: CliRunner, store: StubStore) -> None:
        """When neither ``--body`` nor ``--body-file`` is given, stdin is read."""
        result = _invoke(
            runner,
            store,
            ["add", "--type", "project", "--title", "Stdin Test"],
            input_text="stdin body here\n",
        )
        assert result.exit_code == EXIT_OK
        doc_id = result.output.strip().splitlines()[-1]
        doc = store.get(doc_id)
        assert doc.body == "stdin body here"

    def test_add_body_file(self, runner: CliRunner, store: StubStore, tmp_path: Path) -> None:
        """"--body-file`` reads UTF-8 content."""
        path = tmp_path / "body.md"
        path.write_text("file body content", encoding="utf-8")
        result = _invoke(
            runner,
            store,
            [
                "add",
                "--type",
                "project",
                "--title",
                "File Test",
                "--body-file",
                str(path),
            ],
        )
        assert result.exit_code == EXIT_OK
        doc_id = result.output.strip()
        doc = store.get(doc_id)
        assert doc.body == "file body content"

    def test_add_body_and_body_file_mutually_exclusive(
        self, runner: CliRunner, store: StubStore
    ) -> None:
        """Supplying both ``--body`` and ``--body-file`` exits 64 (usage error)."""
        result = _invoke(
            runner,
            store,
            [
                "add",
                "--type",
                "project",
                "--title",
                "Conflict",
                "--body",
                "x",
                "--body-file",
                "/dev/null",
            ],
        )
        assert result.exit_code == EXIT_USAGE
        assert "mutually exclusive" in result.output

    def test_add_missing_type(self, runner: CliRunner, store: StubStore) -> None:
        """--type`` is required (Click validates)."""
        result = _invoke(runner, store, ["add", "--title", "No Type"])
        assert result.exit_code == EXIT_USAGE

    def test_add_missing_title(self, runner: CliRunner, store: StubStore) -> None:
        """--title`` is required (Click validates)."""
        result = _invoke(runner, store, ["add", "--type", "project"])
        assert result.exit_code == EXIT_USAGE

    def test_add_body_file_not_found(
        self, runner: CliRunner, store: StubStore
    ) -> None:
        """A missing ``--body-file`` exits 64 (usage error)."""
        result = _invoke(
            runner,
            store,
            [
                "add",
                "--type",
                "project",
                "--title",
                "Missing",
                "--body-file",
                "/nonexistent/path.md",
            ],
        )
        assert result.exit_code == EXIT_USAGE
        assert "not found" in result.output


# ---------------------------------------------------------------------------
# kb get
# ---------------------------------------------------------------------------


class TestGet:
    """"kb get`` fetches a single document by id."""

    def test_get_happy_path(
        self, runner: CliRunner, store: StubStore, sample_doc: Document
    ) -> None:
        """Default get renders Markdown-ish human output."""
        result = _invoke(runner, store, ["get", sample_doc.id])
        assert result.exit_code == EXIT_OK
        assert sample_doc.title in result.output
        assert sample_doc.id in result.output
        assert sample_doc.body in result.output

    def test_get_json(
        self, runner: CliRunner, store: StubStore, sample_doc: Document
    ) -> None:
        """--json returns the full document as JSON."""
        result = _invoke(runner, store, ["get", sample_doc.id, "--json"])
        assert result.exit_code == EXIT_OK
        data = json.loads(result.output)
        assert data["id"] == sample_doc.id
        assert data["title"] == sample_doc.title
        assert data["body"] == sample_doc.body

    def test_get_not_found(self, runner: CliRunner, store: StubStore) -> None:
        """Missing id exits 3."""
        result = _invoke(runner, store, ["get", "nonexistent-id"])
        assert result.exit_code == EXIT_NOT_FOUND
        assert "not found" in result.output

    def test_get_not_found_json(self, runner: CliRunner, store: StubStore) -> None:
        """Missing id with ``--json`` returns machine-readable error."""
        result = _invoke(runner, store, ["get", "nonexistent-id", "--json"])
        data = _assert_json_error(result, EXIT_NOT_FOUND)
        assert data["error"] == "not_found"


# ---------------------------------------------------------------------------
# kb search
# ---------------------------------------------------------------------------


class TestSearch:
    """"kb search`` performs substring search over title + body."""

    def test_search_happy_path(
        self, runner: CliRunner, store: StubStore, sample_doc: Document
    ) -> None:
        """Query matching title returns results."""
        result = _invoke(runner, store, ["search", "Test"])
        assert result.exit_code == EXIT_OK
        assert sample_doc.id in result.output

    def test_search_no_results(self, runner: CliRunner, store: StubStore) -> None:
        """Query with no match prints a friendly message."""
        result = _invoke(runner, store, ["search", "zzzzzz"])
        assert result.exit_code == EXIT_OK
        assert "no results" in result.output

    def test_search_json(
        self, runner: CliRunner, store: StubStore, sample_doc: Document
    ) -> None:
        """"--json`` returns a list of hit objects."""
        result = _invoke(runner, store, ["search", "Test", "--json"])
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["id"] == sample_doc.id

    def test_search_by_type(
        self, runner: CliRunner, store: StubStore, sample_doc: Document
    ) -> None:
        """"--type`` restricts results."""
        # Add a second doc of different type
        store.add(Document(id="dec/other", type="decision", title="Other", body="x"))
        result = _invoke(runner, store, ["search", "Other", "--type", "decision"])
        assert result.exit_code == EXIT_OK
        assert "dec/other" in result.output
        assert sample_doc.id not in result.output

    def test_search_by_tag(
        self, runner: CliRunner, store: StubStore, sample_doc: Document
    ) -> None:
        """"--tag`` (repeatable) filters by AND semantics."""
        result = _invoke(
            runner, store, ["search", "Test", "--tag", "test", "--tag", "cli"]
        )
        assert result.exit_code == EXIT_OK
        assert sample_doc.id in result.output

    def test_search_limit(self, runner: CliRunner, store: StubStore) -> None:
        """"--limit`` caps the number of results."""
        for i in range(5):
            store.add(
                Document(
                    id=f"proj/item-{i}",
                    type="project",
                    title=f"Item {i}",
                    body=f"body {i}",
                )
            )
        result = _invoke(runner, store, ["search", "body", "--limit", "2", "--json"])
        data = json.loads(result.output)
        assert len(data) == 2

    def test_search_empty_query_validation(
        self, runner: CliRunner, store: StubStore
    ) -> None:
        """Empty query raises ValidationError -> exit 2."""
        result = _invoke(runner, store, ["search", ""])
        assert result.exit_code == EXIT_VALIDATION

    def test_search_sort_by_score(self, runner: CliRunner, store: StubStore) -> None:
        """Results are sorted by score (lower offset = better)."""
        # "alpha" appears early in title for first doc, later for second
        store.add(
            Document(id="proj/early", type="project", title="alpha start", body="z")
        )
        store.add(
            Document(id="proj/late", type="project", title="z end alpha", body="z")
        )
        result = _invoke(runner, store, ["search", "alpha", "--json"])
        data = json.loads(result.output)
        assert len(data) == 2
        # early doc should have lower score (better rank)
        assert data[0]["id"] == "proj/early"
        assert data[1]["id"] == "proj/late"


# ---------------------------------------------------------------------------
# kb list
# ---------------------------------------------------------------------------


class TestList:
    """"kb list`` returns documents sorted by updated_at DESC."""

    def test_list_empty(self, runner: CliRunner, store: StubStore) -> None:
        """Empty store prints a friendly message."""
        result = _invoke(runner, store, ["list"])
        assert result.exit_code == EXIT_OK
        assert "no documents" in result.output

    def test_list_with_docs(
        self, runner: CliRunner, store: StubStore, sample_doc: Document
    ) -> None:
        """Default list shows id, type, title, and timestamp."""
        result = _invoke(runner, store, ["list"])
        assert result.exit_code == EXIT_OK
        assert sample_doc.id in result.output
        assert sample_doc.type in result.output
        assert sample_doc.title in result.output

    def test_list_json(
        self, runner: CliRunner, store: StubStore, sample_doc: Document
    ) -> None:
        """"--json`` returns a list of document dicts."""
        result = _invoke(runner, store, ["list", "--json"])
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == sample_doc.id

    def test_list_by_type(self, runner: CliRunner, store: StubStore) -> None:
        """"--type`` filters."""
        store.add(Document(id="proj/a", type="project", title="A", body="x"))
        store.add(Document(id="dec/b", type="decision", title="B", body="x"))
        result = _invoke(runner, store, ["list", "--type", "decision", "--json"])
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["id"] == "dec/b"

    def test_list_by_tag(self, runner: CliRunner, store: StubStore) -> None:
        """"--tag`` filters by AND semantics."""
        store.add(
            Document(id="proj/t1", type="project", title="T1", body="x", tags=["a"])
        )
        store.add(
            Document(
                id="proj/t2", type="project", title="T2", body="x", tags=["a", "b"]
            )
        )
        result = _invoke(
            runner, store, ["list", "--tag", "a", "--tag", "b", "--json"]
        )
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["id"] == "proj/t2"

    def test_list_limit_offset(self, runner: CliRunner, store: StubStore) -> None:
        """"--limit`` and ``--offset`` paginate."""
        for i in range(5):
            store.add(
                Document(
                    id=f"proj/item-{i}",
                    type="project",
                    title=f"Item {i}",
                    body="x",
                )
            )
        result = _invoke(runner, store, ["list", "--limit", "2", "--offset", "1", "--json"])
        data = json.loads(result.output)
        assert len(data) == 2

    def test_list_invalid_limit(self, runner: CliRunner, store: StubStore) -> None:
        """Negative limit raises ValidationError -> exit 2."""
        result = _invoke(runner, store, ["list", "--limit", "-1"])
        assert result.exit_code == EXIT_VALIDATION


# ---------------------------------------------------------------------------
# kb link
# ---------------------------------------------------------------------------


class TestLink:
    """"kb link`` creates typed edges between documents."""

    def test_link_happy_path(
        self, runner: CliRunner, store: StubStore, sample_doc: Document
    ) -> None:
        """Default link prints a human-readable edge."""
        store.add(Document(id="dec/target", type="decision", title="Target", body="x"))
        result = _invoke(
            runner, store, ["link", "--from", sample_doc.id, "--to", "dec/target"]
        )
        assert result.exit_code == EXIT_OK
        assert "relates-to" in result.output
        assert sample_doc.id in result.output
        assert "dec/target" in result.output

    def test_link_json(
        self, runner: CliRunner, store: StubStore, sample_doc: Document
    ) -> None:
        """"--json`` returns the edge details."""
        store.add(Document(id="dec/target", type="decision", title="Target", body="x"))
        result = _invoke(
            runner,
            store,
            ["link", "--from", sample_doc.id, "--to", "dec/target", "--json"],
        )
        data = _assert_json_ok(result)
        assert data["from"] == sample_doc.id
        assert data["to"] == "dec/target"
        assert data["rel"] == "relates-to"

    def test_link_custom_rel(
        self, runner: CliRunner, store: StubStore, sample_doc: Document
    ) -> None:
        """"--rel`` overrides the default."""
        store.add(Document(id="dec/target", type="decision", title="Target", body="x"))
        result = _invoke(
            runner,
            store,
            [
                "link",
                "--from",
                sample_doc.id,
                "--to",
                "dec/target",
                "--rel",
                "depends-on",
            ],
        )
        assert result.exit_code == EXIT_OK
        assert "depends-on" in result.output

    def test_link_idempotent(
        self, runner: CliRunner, store: StubStore, sample_doc: Document
    ) -> None:
        """Re-linking the same triple is a no-op (still exits 0)."""
        store.add(Document(id="dec/target", type="decision", title="Target", body="x"))
        args = ["link", "--from", sample_doc.id, "--to", "dec/target"]
        r1 = _invoke(runner, store, args)
        assert r1.exit_code == EXIT_OK
        r2 = _invoke(runner, store, args)
        assert r2.exit_code == EXIT_OK

    def test_link_from_not_found(
        self, runner: CliRunner, store: StubStore
    ) -> None:
        """Missing ``--from`` id exits 3."""
        store.add(Document(id="dec/target", type="decision", title="Target", body="x"))
        result = _invoke(
            runner, store, ["link", "--from", "missing", "--to", "dec/target"]
        )
        assert result.exit_code == EXIT_NOT_FOUND

    def test_link_to_not_found(
        self, runner: CliRunner, store: StubStore, sample_doc: Document
    ) -> None:
        """Missing ``--to`` id exits 3."""
        result = _invoke(
            runner, store, ["link", "--from", sample_doc.id, "--to", "missing"]
        )
        assert result.exit_code == EXIT_NOT_FOUND

    def test_link_missing_from(self, runner: CliRunner, store: StubStore) -> None:
        """--from is required (Click validates)."""
        result = _invoke(runner, store, ["link", "--to", "dec/target"])
        assert result.exit_code == EXIT_USAGE

    def test_link_missing_to(self, runner: CliRunner, store: StubStore) -> None:
        """--to`` is required (Click validates)."""
        result = _invoke(runner, store, ["link", "--from", "proj/x"])
        assert result.exit_code == EXIT_USAGE


# ---------------------------------------------------------------------------
# kb import (stub  -  deferred to Wave 1B)
# ---------------------------------------------------------------------------


class TestImport:
    """kb import is a stub that exits 5 until Wave 1B."""

    def test_import_stub_exits_5(self, runner: CliRunner, store: StubStore, tmp_path: Path) -> None:
        """Any invocation exits 5 (internal / not implemented)."""
        vault = tmp_path / "vault"
        vault.mkdir()
        result = _invoke(runner, store, ["import", str(vault)])
        assert result.exit_code == EXIT_INTERNAL
        assert "not yet implemented" in result.output or "deferred" in result.output

    def test_import_stub_json(self, runner: CliRunner, store: StubStore, tmp_path: Path) -> None:
        """Stub with ``--json`` still exits 5."""
        vault = tmp_path / "vault"
        vault.mkdir()
        result = _invoke(runner, store, ["import", str(vault), "--json"])
        # The stub raises NotImplementedError which _handle_errors catches
        # and exits 5; JSON error payload is emitted.
        assert result.exit_code == EXIT_INTERNAL

    def test_import_dry_run_stub(self, runner: CliRunner, store: StubStore, tmp_path: Path) -> None:
        """"--dry-run`` does not change the stub behaviour."""
        vault = tmp_path / "vault"
        vault.mkdir()
        result = _invoke(runner, store, ["import", str(vault), "--dry-run"])
        assert result.exit_code == EXIT_INTERNAL


# ---------------------------------------------------------------------------
# kb export (stub  -  deferred to Wave 1B)
# ---------------------------------------------------------------------------


class TestExport:
    """"kb export`` is a stub that exits 5 until Wave 1B."""

    def test_export_stub_exits_5(
        self, runner: CliRunner, store: StubStore, tmp_path: Path
    ) -> None:
        """Any invocation exits 5."""
        out = tmp_path / "out"
        result = _invoke(runner, store, ["export", str(out)])
        assert result.exit_code == EXIT_INTERNAL

    def test_export_stub_json(
        self, runner: CliRunner, store: StubStore, tmp_path: Path
    ) -> None:
        """Stub with ``--json`` still exits 5."""
        out = tmp_path / "out"
        result = _invoke(runner, store, ["export", str(out), "--json"])
        assert result.exit_code == EXIT_INTERNAL

    def test_export_force_stub(
        self, runner: CliRunner, store: StubStore, tmp_path: Path
    ) -> None:
        """"--force`` does not change the stub behaviour."""
        out = tmp_path / "out"
        result = _invoke(runner, store, ["export", str(out), "--force"])
        assert result.exit_code == EXIT_INTERNAL


# ---------------------------------------------------------------------------
# kb doctor
# ---------------------------------------------------------------------------


class TestDoctor:
    """"kb doctor`` runs health checks."""

    def test_doctor_happy_path(self, runner: CliRunner, store: StubStore) -> None:
        """Healthy store prints OK."""
        result = _invoke(runner, store, ["doctor"])
        assert result.exit_code == EXIT_OK
        assert "OK" in result.output

    def test_doctor_json(self, runner: CliRunner, store: StubStore) -> None:
        """"--json`` returns a structured report."""
        result = _invoke(runner, store, ["doctor", "--json"])
        data = _assert_json_ok(result)
        assert data["ok"] is True
        assert "checks" in data
        assert isinstance(data["checks"], list)

    def test_doctor_with_data(
        self, runner: CliRunner, store: StubStore, sample_doc: Document
    ) -> None:
        """Doctor report includes document counts."""
        result = _invoke(runner, store, ["doctor", "--json"])
        data = _assert_json_ok(result)
        check = data["checks"][0]
        assert "1 docs" in check["detail"] or "1 doc" in check["detail"]


# ---------------------------------------------------------------------------
# kb serve (stub  -  deferred to Wave 2A)
# ---------------------------------------------------------------------------


class TestServe:
    """``kb serve`` starts the MCP server (Wave 2A).

    The actual server behaviour is tested in ``tests/test_mcp_e2e.py``
    via subprocess. Here we only test CLI-level validation.
    """

    def test_serve_invalid_log_level(
        self, runner: CliRunner, store: StubStore
    ) -> None:
        """Invalid ``--log-level`` is rejected by Click (usage error, exit 64)."""
        result = _invoke(runner, store, ["serve", "--log-level", "INVALID"])
        assert result.exit_code == EXIT_USAGE


# ---------------------------------------------------------------------------
# Cross-cutting concerns
# ---------------------------------------------------------------------------


class TestJsonFlag:
    """"--json`` produces valid JSON on every supported command."""

    def test_json_on_init(self, runner: CliRunner, store: StubStore) -> None:
        result = _invoke(runner, store, ["init", "--json"])
        data = _assert_json_ok(result)
        assert "message" in data

    def test_json_on_add(self, runner: CliRunner, store: StubStore) -> None:
        result = _invoke(
            runner,
            store,
            ["add", "--type", "project", "--title", "JSON", "--json"],
        )
        data = _assert_json_ok(result)
        assert "id" in data

    def test_json_on_get(
        self, runner: CliRunner, store: StubStore, sample_doc: Document
    ) -> None:
        result = _invoke(runner, store, ["get", sample_doc.id, "--json"])
        assert result.exit_code == EXIT_OK
        data = json.loads(result.output)
        assert data["id"] == sample_doc.id

    def test_json_on_search(
        self, runner: CliRunner, store: StubStore, sample_doc: Document
    ) -> None:
        result = _invoke(runner, store, ["search", "Test", "--json"])
        data = json.loads(result.output)
        assert isinstance(data, list)

    def test_json_on_list(
        self, runner: CliRunner, store: StubStore, sample_doc: Document
    ) -> None:
        result = _invoke(runner, store, ["list", "--json"])
        data = json.loads(result.output)
        assert isinstance(data, list)

    def test_json_on_link(
        self, runner: CliRunner, store: StubStore, sample_doc: Document
    ) -> None:
        store.add(Document(id="dec/target", type="decision", title="Target", body="x"))
        result = _invoke(
            runner,
            store,
            ["link", "--from", sample_doc.id, "--to", "dec/target", "--json"],
        )
        data = _assert_json_ok(result)
        assert data["rel"] == "relates-to"

    def test_json_on_doctor(self, runner: CliRunner, store: StubStore) -> None:
        result = _invoke(runner, store, ["doctor", "--json"])
        data = _assert_json_ok(result)
        assert "checks" in data


class TestExitCodes:
    """Exit codes match cli-reference.md for every error class."""

    def test_exit_ok(self, runner: CliRunner, store: StubStore) -> None:
        result = _invoke(runner, store, ["init"])
        assert result.exit_code == EXIT_OK

    def test_exit_validation(self, runner: CliRunner, store: StubStore) -> None:
        result = _invoke(runner, store, ["search", ""])
        assert result.exit_code == EXIT_VALIDATION

    def test_exit_not_found(self, runner: CliRunner, store: StubStore) -> None:
        result = _invoke(runner, store, ["get", "missing"])
        assert result.exit_code == EXIT_NOT_FOUND

    def test_exit_conflict(self, runner: CliRunner, store: StubStore) -> None:
        args = ["add", "--type", "project", "--title", "Dup"]
        _invoke(runner, store, args)
        result = _invoke(runner, store, args)
        assert result.exit_code == EXIT_CONFLICT

    def test_exit_internal_not_implemented(
        self, runner: CliRunner, store: StubStore, tmp_path: Path
    ) -> None:
        vault = tmp_path / "v"
        vault.mkdir()
        result = _invoke(runner, store, ["import", str(vault)])
        assert result.exit_code == EXIT_INTERNAL

    def test_exit_usage(self, runner: CliRunner, store: StubStore) -> None:
        result = _invoke(runner, store, ["add"])  # missing required options
        assert result.exit_code == EXIT_USAGE


class TestStoreInjection:
    """Tests prove that the injected store is actually used."""

    def test_injected_store_is_used(
        self, runner: CliRunner, store: StubStore
    ) -> None:
        """A doc added via the store directly appears in CLI list."""
        store.add(Document(id="proj/injected", type="project", title="Injected", body="x"))
        result = _invoke(runner, store, ["list", "--json"])
        data = json.loads(result.output)
        assert any(d["id"] == "proj/injected" for d in data)

