#!/usr/bin/env python3
"""Minimal MCP client for kb-mcp.

Connects to the kb-mcp MCP server over stdio, calls ``kb_add`` to create a
document, then calls ``kb_search`` to find it again.

Requirements
------------
The ``mcp`` package must be importable. If you installed ``kb-mcp`` with the
dev extras you already have it::

    pip install mcp

Usage
-----
::

    # Make sure `kb` is on your PATH (pip install -e . from the repo root)
    python examples/python-mcp-client.py

    # Or point at a specific kb executable:
    KB_BIN=/path/to/uv-run-kb python examples/python-mcp-client.py

    # Use a throwaway database:
    KB_MCP_HOME=/tmp/kb-demo python examples/python-mcp-client.py

What it does
------------
1. Spawns ``kb serve`` as a subprocess (stdio transport).
2. Initializes the MCP client session.
3. Lists available tools (sanity check — should include kb_add, kb_get,
   kb_search, kb_link).
4. Calls ``kb_add`` to create a ``glossary`` document about "MCP".
5. Calls ``kb_search`` for "model context protocol" and prints the hits.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _server_params() -> StdioServerParameters:
    """Build stdio server params for ``kb serve``.

    Honours the ``KB_BIN`` env var so you can point at a specific ``kb``
    executable (defaults to ``kb`` on PATH).
    """
    command = os.environ.get("KB_BIN", "kb")
    return StdioServerParameters(
        command=command,
        args=["serve"],
        # Inherit the environment so KB_MCP_HOME / PATH propagate.
        env=os.environ.copy(),
    )


async def main() -> None:
    params = _server_params()

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            # 1. Handshake.
            init_result = await session.initialize()
            print(
                f"connected to server: {init_result.serverInfo.name} "
                f"v{init_result.serverInfo.version}",
                file=sys.stderr,
            )

            # 2. List tools (sanity check).
            tools_resp = await session.list_tools()
            tool_names = [t.name for t in tools_resp.tools]
            print(f"available tools: {tool_names}", file=sys.stderr)

            # 3. Create a document with kb_add.
            add_result: Any = await session.call_tool(
                "kb_add",
                {
                    "type": "glossary",
                    "title": "MCP",
                    "body": (
                        "The Model Context Protocol (MCP) is an open standard "
                        "that lets LLM-powered agents call external tools and "
                        "read external context. kb-mcp exposes its knowledge "
                        "base over MCP so any compliant agent can search and "
                        "edit it."
                    ),
                    "tags": ["protocol", "agents"],
                },
            )
            new_id = _extract_id(add_result)
            print(f"kb_add → created document id={new_id!r}", file=sys.stderr)

            # 4. Search for it with kb_search.
            search_result: Any = await session.call_tool(
                "kb_search",
                {"query": "model context protocol", "limit": 5},
            )
            print("\n--- kb_search results ---")
            _print_search_results(search_result)
            print("--- end ---\n")


def _extract_id(result: Any) -> str:
    """Pull the ``id`` field out of a kb_add tool result.

    FastMCP returns results as a structured object whose ``content`` list
    contains TextContent items. The JSON payload is in ``text``.
    """
    import json

    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text:
            try:
                payload = json.loads(text)
                if isinstance(payload, dict) and "id" in payload:
                    return str(payload["id"])
            except json.JSONDecodeError:
                continue
    return "<unknown>"


def _print_search_results(result: Any) -> None:
    """Pretty-print the hits returned by kb_search."""
    import json

    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            print(text)
            continue

        if isinstance(payload, dict) and "hits" in payload:
            hits = payload["hits"]
            if not hits:
                print("(no results)")
                continue
            for h in hits:
                print(
                    f"  {h.get('id')}  [{h.get('type')}]  "
                    f"{h.get('title')}  (score={h.get('score')})"
                )
                snippet = h.get("snippet")
                if snippet:
                    print(f"    {snippet}")
        else:
            print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
