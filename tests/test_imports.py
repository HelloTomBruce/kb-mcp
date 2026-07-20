"""Basic smoke test for mcp_server module imports."""

from __future__ import annotations


def test_mcp_server_imports() -> None:
    """Verify mcp_server module can be imported without errors."""
    import kb_mcp_lite.mcp_server  # noqa: F401
