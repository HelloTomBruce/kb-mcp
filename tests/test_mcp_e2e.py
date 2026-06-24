"""E2E tests for kb-mcp MCP server (Wave 2A).

Spawns ``kb serve`` as a real subprocess, speaks JSON-RPC over stdin/stdout,
and asserts tool outputs. No mocks.

MCP protocol note: tool execution errors are returned as
``{"result": {"isError": true, "content": [{"text": "..."}]}}``,
NOT as JSON-RPC ``{"error": {"code": ...}}``. The error code is embedded
in the text as ``MCP error <code>: <message>``. This matches the MCP
specification — JSON-RPC errors are for protocol-level issues, not
application-level tool failures.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterator

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_id_counter = 0


def _next_id() -> int:
    global _id_counter
    _id_counter += 1
    return _id_counter


def _send(proc: subprocess.Popen, msg: dict[str, Any]) -> None:
    """Write a JSON-RPC message to the subprocess stdin."""
    assert proc.stdin is not None
    line = json.dumps(msg, ensure_ascii=False)
    proc.stdin.write(line + "\n")
    proc.stdin.flush()


def _recv(proc: subprocess.Popen, timeout: float = 10.0) -> dict[str, Any]:
    """Read a single JSON-RPC line from stdout."""
    assert proc.stdout is not None
    line = proc.stdout.readline()
    if not line:
        stderr = ""
        assert proc.stderr is not None
        try:
            stderr = proc.stderr.read()
        except Exception:
            pass
        raise RuntimeError(f"MCP server closed stdout (no response). stderr: {stderr[:500]}")
    return json.loads(line)


def _recv_until_id(
    proc: subprocess.Popen, expected_id: int, timeout: float = 10.0
) -> dict[str, Any]:
    """Read lines until one with the matching ``id`` arrives."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        msg = _recv(proc, timeout=min(deadline - time.monotonic(), 5.0))
        if msg.get("id") == expected_id:
            return msg
        # Skip notifications (no id) or responses for other ids
    raise RuntimeError(f"Timeout waiting for response id={expected_id}")


def _call_tool(proc: subprocess.Popen, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Send a tools/call request and return the response."""
    rid = _next_id()
    _send(
        proc,
        {
            "jsonrpc": "2.0",
            "id": rid,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    return _recv_until_id(proc, rid)


def _extract_result(resp: dict[str, Any]) -> Any:
    """Extract the tool result data from an MCP response.

    FastMCP wraps return values as:
        {"result": {"content": [{"type": "text", "text": <json_str>}]}}
    For list returns, FastMCP may emit one content block per item.
    For empty lists, content may be empty.
    """
    assert "result" in resp, f"expected result, got: {resp}"
    result = resp["result"]
    content = result.get("content", [])
    if not content:
        return []
    # If multiple content blocks, each is one item — collect and parse.
    if len(content) > 1:
        items = []
        for block in content:
            text = block.get("text", "")
            try:
                items.append(json.loads(text))
            except (json.JSONDecodeError, ValueError):
                items.append(text)
        return items
    # Single content block — parse as JSON (could be dict, list, or scalar).
    text = content[0].get("text", "")
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text


def _extract_error(resp: dict[str, Any]) -> tuple[int, str] | None:
    """Extract (code, message) from an MCP tool error response.

    Returns None if the response is not an error.
    The error text format is: ``Error executing tool X: MCP error <code>: <msg>``
    """
    if "result" not in resp:
        # JSON-RPC level error
        err = resp.get("error", {})
        return (err.get("code", -32603), err.get("message", ""))
    result = resp["result"]
    if not result.get("isError"):
        return None
    text = result.get("content", [{}])[0].get("text", "")
    # Parse "MCP error <code>: <msg>" from the text
    import re

    m = re.search(r"MCP error (-?\d+):\s*(.+)", text)
    if m:
        return (int(m.group(1)), m.group(2))
    return (-32603, text)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Iterator[Path]:
    """A temporary DB path isolated from the user's real KB."""
    db = tmp_path / "kb.db"
    yield db


@pytest.fixture()
def mcp_proc(tmp_db: Path) -> Iterator[subprocess.Popen]:
    """A running ``kb serve`` subprocess with a fresh temp DB."""
    global _id_counter
    _id_counter = 0  # reset per fixture

    env = {
        **os.environ,
        "KB_MCP_HOME": str(tmp_db.parent),
        "KB_MCP_LOG_LEVEL": "ERROR",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "kb_mcp_lite.mcp_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        # Handshake: initialize
        rid = _next_id()
        _send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": rid,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
            },
        )
        init_resp = _recv_until_id(proc, rid)
        assert "result" in init_resp, f"initialize failed: {init_resp}"

        # notifications/initialized
        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        yield proc
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


# ---------------------------------------------------------------------------
# Tool discovery
# ---------------------------------------------------------------------------


class TestDiscovery:
    """MCP server advertises the 4 kb tools."""

    def test_tools_list(self, mcp_proc: subprocess.Popen) -> None:
        """tools/list returns kb_search, kb_get, kb_add, kb_link."""
        rid = _next_id()
        _send(mcp_proc, {"jsonrpc": "2.0", "id": rid, "method": "tools/list"})
        resp = _recv_until_id(mcp_proc, rid)
        assert "result" in resp, f"tools/list failed: {resp}"
        tools = resp["result"]["tools"]
        names = {t["name"] for t in tools}
        assert names == {
            "kb_search", "kb_get", "kb_add", "kb_link",
            "kb_list", "kb_update", "kb_delete", "kb_unlink",
        }


# ---------------------------------------------------------------------------
# kb_add
# ---------------------------------------------------------------------------


class TestKbAdd:
    """kb_add creates documents and returns the generated id."""

    def test_add_happy_path(self, mcp_proc: subprocess.Popen) -> None:
        """Minimal add returns a new id."""
        resp = _call_tool(mcp_proc, "kb_add", {"type": "project", "title": "Hello MCP"})
        data = _extract_result(resp)
        assert data["id"] == "proj/hello-mcp"

    def test_add_with_body_and_tags(self, mcp_proc: subprocess.Popen) -> None:
        """Add with all optional fields."""
        resp = _call_tool(
            mcp_proc,
            "kb_add",
            {
                "type": "lesson",
                "title": "Body Test",
                "body": "Some content here.",
                "tags": ["test", "mcp"],
                "source": "src/x.md",
            },
        )
        data = _extract_result(resp)
        assert data["id"] == "lesson/body-test"

    def test_add_duplicate(self, mcp_proc: subprocess.Popen) -> None:
        """Adding the same (type, title) twice returns error -32005."""
        args = {"type": "project", "title": "Dup"}
        r1 = _call_tool(mcp_proc, "kb_add", args)
        assert _extract_error(r1) is None, f"first add should succeed: {r1}"
        r2 = _call_tool(mcp_proc, "kb_add", args)
        err = _extract_error(r2)
        assert err is not None, f"Expected error for duplicate, got: {r2}"
        assert err[0] == -32005, f"Expected -32005, got {err[0]}"

    def test_add_validation_error(self, mcp_proc: subprocess.Popen) -> None:
        """Empty title returns error -32602."""
        resp = _call_tool(mcp_proc, "kb_add", {"type": "project", "title": ""})
        err = _extract_error(resp)
        assert err is not None, f"Expected validation error, got: {resp}"
        assert err[0] == -32602, f"Expected -32602, got {err[0]}"


# ---------------------------------------------------------------------------
# kb_get
# ---------------------------------------------------------------------------


class TestKbGet:
    """kb_get fetches a document by id."""

    def test_get_happy_path(self, mcp_proc: subprocess.Popen) -> None:
        """Get an existing doc returns full document."""
        # First add a doc
        add_resp = _call_tool(mcp_proc, "kb_add", {"type": "project", "title": "Get Me"})
        doc_id = _extract_result(add_resp)["id"]

        # Now get it
        resp = _call_tool(mcp_proc, "kb_get", {"id": doc_id})
        data = _extract_result(resp)
        assert data["id"] == doc_id
        assert data["title"] == "Get Me"

    def test_get_not_found(self, mcp_proc: subprocess.Popen) -> None:
        """Missing id returns error -32004."""
        resp = _call_tool(mcp_proc, "kb_get", {"id": "nonexistent-id"})
        err = _extract_error(resp)
        assert err is not None, f"Expected not_found error, got: {resp}"
        assert err[0] == -32004, f"Expected -32004, got {err[0]}"


# ---------------------------------------------------------------------------
# kb_search
# ---------------------------------------------------------------------------


class TestKbSearch:
    """kb_search performs full-text search."""

    def test_search_happy_path(self, mcp_proc: subprocess.Popen) -> None:
        """Search returns hits for matching query."""
        # Add a doc with searchable body
        _call_tool(
            mcp_proc,
            "kb_add",
            {
                "type": "project",
                "title": "Searchable",
                "body": "hello world content",
            },
        )

        resp = _call_tool(mcp_proc, "kb_search", {"query": "hello"})
        data = _extract_result(resp)
        assert isinstance(data, dict), f"Expected dict, got: {type(data)}"
        assert data["count"] >= 1, f"Expected >=1 hit, got {data['count']}"
        assert data["hits"][0]["id"] == "proj/searchable"

    def test_search_no_results(self, mcp_proc: subprocess.Popen) -> None:
        """Search with no match returns empty hits."""
        resp = _call_tool(mcp_proc, "kb_search", {"query": "zzzzzz"})
        data = _extract_result(resp)
        assert data["count"] == 0, f"Expected 0 hits, got: {data}"
        assert data["hits"] == []

    def test_search_validation(self, mcp_proc: subprocess.Popen) -> None:
        """Empty query returns error -32602."""
        resp = _call_tool(mcp_proc, "kb_search", {"query": ""})
        err = _extract_error(resp)
        assert err is not None, f"Expected validation error, got: {resp}"
        assert err[0] == -32602, f"Expected -32602, got {err[0]}"


# ---------------------------------------------------------------------------
# kb_link
# ---------------------------------------------------------------------------


class TestKbLink:
    """kb_link creates typed edges between documents."""

    def test_link_happy_path(self, mcp_proc: subprocess.Popen) -> None:
        """Link two existing docs."""
        # Add two docs
        _call_tool(mcp_proc, "kb_add", {"type": "project", "title": "From Doc"})
        _call_tool(mcp_proc, "kb_add", {"type": "project", "title": "To Doc"})

        resp = _call_tool(
            mcp_proc,
            "kb_link",
            {"from_id": "proj/from-doc", "to_id": "proj/to-doc"},
        )
        data = _extract_result(resp)
        assert data["ok"] is True
        assert data["rel"] == "relates-to"

    def test_link_not_found(self, mcp_proc: subprocess.Popen) -> None:
        """Linking a missing doc returns error -32004."""
        resp = _call_tool(
            mcp_proc,
            "kb_link",
            {"from_id": "missing", "to_id": "also-missing"},
        )
        err = _extract_error(resp)
        assert err is not None, f"Expected not_found error, got: {resp}"
        assert err[0] == -32004, f"Expected -32004, got {err[0]}"


# ---------------------------------------------------------------------------
# Error code mapping (architecture.md § 4.4)
# ---------------------------------------------------------------------------


class TestErrorCodes:
    """Error codes match architecture.md § 4.4."""

    def test_validation_error_code(self, mcp_proc: subprocess.Popen) -> None:
        """ValidationError → -32602."""
        resp = _call_tool(mcp_proc, "kb_search", {"query": ""})
        err = _extract_error(resp)
        assert err is not None
        assert err[0] == -32602

    def test_not_found_error_code(self, mcp_proc: subprocess.Popen) -> None:
        """NotFoundError → -32004."""
        resp = _call_tool(mcp_proc, "kb_get", {"id": "missing"})
        err = _extract_error(resp)
        assert err is not None
        assert err[0] == -32004

    def test_duplicate_error_code(self, mcp_proc: subprocess.Popen) -> None:
        """DuplicateError → -32005."""
        args = {"type": "project", "title": "DupCode"}
        _call_tool(mcp_proc, "kb_add", args)
        resp = _call_tool(mcp_proc, "kb_add", args)
        err = _extract_error(resp)
        assert err is not None
        assert err[0] == -32005
