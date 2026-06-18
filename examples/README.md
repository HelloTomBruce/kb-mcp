# Examples

Client configurations and sample code for connecting to the **kb-mcp** MCP
server. The server is started with `kb serve` (stdio transport) and exposes
four tools: `kb_search`, `kb_get`, `kb_add`, `kb_link`.

## Files

| File | What it is |
|---|---|
| [`claude-desktop-config.json`](./claude-desktop-config.json) | Drop-in config for **Claude Desktop**. Copy the `mcpServers.kb` block into your `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`). |
| [`cursor-config.json`](./cursor-config.json) | Drop-in config for **Cursor**. Add the `mcpServers.kb` block to your Cursor MCP settings (`~/.cursor/mcp.json` or via *Settings → MCP*). |
| [`python-mcp-client.py`](./python-mcp-client.py) | A standalone Python script that spawns `kb serve`, calls `kb_add` to create a document, then `kb_search` to find it. Uses the official `mcp` SDK. |

## Prerequisites

`kb` must be on your `PATH`:

```bash
pip install kb-mcp          # from PyPI (when published)
# or, from a clone of this repo:
pip install -e .
```

Verify:

```bash
kb --version
kb serve --help
```

## Quickstart

### Claude Desktop

1. Install `kb-mcp` so `kb` is on your PATH.
2. Open (or create) `~/Library/Application Support/Claude/claude_desktop_config.json`.
3. Paste the contents of [`claude-desktop-config.json`](./claude-desktop-config.json)
   (or merge the `mcpServers.kb` entry into your existing file).
4. Restart Claude Desktop. The agent now has `kb_search`, `kb_get`, `kb_add`,
   and `kb_link` available.

### Cursor

1. Install `kb-mcp` so `kb` is on your PATH.
2. Open Cursor → *Settings → MCP* (or edit `~/.cursor/mcp.json`).
3. Merge the `mcpServers.kb` entry from [`cursor-config.json`](./cursor-config.json).
4. Reload the window. The tools are now callable from Cursor's agent.

### Python client

```bash
# Use your default KB (~/.local/share/kb-mcp/kb.db)
python examples/python-mcp-client.py

# Use a throwaway DB so you don't pollute your real knowledge base
KB_MCP_HOME=/tmp/kb-demo python examples/python-mcp-client.py

# Point at a specific kb binary (e.g. via uv)
KB_BIN="$(pwd)/.venv/bin/kb" python examples/python-mcp-client.py
```

The script:

1. Spawns `kb serve` as a subprocess (stdio transport).
2. Initializes the MCP session and lists available tools.
3. Calls `kb_add` to create a `glossary` document about "MCP".
4. Calls `kb_search` for "model context protocol" and prints the ranked hits.

## Using a custom database location

All examples inherit your environment. Set `KB_MCP_HOME` to point `kb serve`
at a different database directory:

```bash
export KB_MCP_HOME=/tmp/kb-demo
kb init
python examples/python-mcp-client.py
```

## Troubleshooting

- **`kb: command not found`** — `kb-mcp` isn't installed or your venv isn't
  activated. Run `pip install -e .` from the repo root, or set `KB_BIN` to the
  full path of the `kb` executable.
- **Claude Desktop doesn't see the tools** — restart the app after editing the
  config; check the logs in `~/Library/Logs/Claude/mcp*.log`.
- **Python client hangs** — ensure no other `kb serve` process is holding the
  database; SQLite uses file locking. Use `KB_MCP_HOME` for isolation.
