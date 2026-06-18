# kb-mcp — Quickstart

Get from `pip install` to a working MCP server in five minutes.

---

## 1. Install

```bash
pip install kb-mcp
```

Verify:

```bash
kb --version
# kb-mcp, version 0.1.0
```

---

## 2. Initialize

```bash
kb init
```

Creates `~/.local/share/kb-mcp/` containing:

```
kb-mcp/
├── kb.db          # SQLite + FTS5
└── vault/         # (empty; created on first import)
```

The location is overridable via the `KB_MCP_HOME` env var:

```bash
KB_MCP_HOME=~/work/project-x/.kb kb init
```

`kb init` is idempotent. Re-running on an existing DB does nothing unless
you pass `--force`.

---

## 3. Add your first document

```bash
kb add \
  --type project \
  --title "kb-mcp" \
  --tags kb,mcp,open-source \
  --body "Agent-native knowledge base. SQLite + FTS5 + MCP server."
```

Output:

```
created doc/proj/kb-mcp  (id=proj_kb-mcp)
```

Add a decision:

```bash
kb add \
  --type decision \
  --title "Use SQLite FTS5 over Elasticsearch" \
  --tags architecture,storage \
  --body "Single-binary install, zero ops, sufficient for <100k docs."
```

Add a lesson:

```bash
kb add \
  --type lesson \
  --title "Don't reuse last_insert_rowid() across batch INSERTs" \
  --tags sqlite,bug \
  --body "FK violations silently fail in the SQLite CLI; use INSERT...SELECT instead."
```

---

## 4. Search

```bash
kb search "sqlite fts"
```

Output (human-readable):

```
proj_kb-mcp          project   "Agent-native knowledge base. **SQLite** + **FTS5** + MCP…"
dec_use-sqlite-fts5  decision  "Single-binary install, zero ops, sufficient for <100k docs…"
```

Restrict to a type:

```bash
kb search "mcp" --type project --limit 5
```

JSON output (for piping / scripting):

```bash
kb search "mcp" --json | jq '.[].title'
```

---

## 5. Get a document by id

```bash
kb get proj_kb-mcp
```

Renders full body + metadata.

```bash
kb get proj_kb-mcp --json
```

---

## 6. List everything

```bash
kb list
kb list --type decision --tag architecture
```

---

## 7. Link documents

```bash
kb link --from dec_use-sqlite-fts5 --to proj_kb-mcp --rel relates-to
```

Now `kb get dec_use-sqlite-fts5` includes the backlink to `proj_kb-mcp`.

---

## 8. Markdown I/O

Import a directory of Markdown files:

```bash
mkdir my-vault
cat > my-vault/my-project.md <<'EOF'
---
type: project
title: My Project
tags: [python, mcp]
---

# My Project

A demo project.
EOF

kb import my-vault/
```

Export the database to Markdown:

```bash
kb export my-vault-backup/
ls my-vault-backup/
# decision-use-sqlite-fts5.md
# lesson-dont-reuse-last-insert-rowid.md
# project-kb-mcp.md
```

Round-trip is lossless: `kb import` after `kb export` produces an
equivalent DB.

---

## 9. Expose to an MCP client

### Claude Desktop

`~/.config/claude_desktop_config.json` (macOS:
`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "kb": {
      "command": "kb",
      "args": ["serve"]
    }
  }
}
```

Restart Claude Desktop. The agent now sees four tools:
`kb_search`, `kb_get`, `kb_add`, `kb_link`.

### Cursor

`~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "kb": {
      "command": "kb",
      "args": ["serve"]
    }
  }
}
```

### OpenCode / Codex / generic stdio MCP

See your client's docs. The transport is stdio JSON-RPC; `kb serve` speaks
it out of the box.

---

## 10. Sanity check

```bash
kb doctor
```

Verifies DB integrity, FTS sync, and absence of orphan links. Exits 0 on
a healthy DB.

---

## 11. Where to go next

- Spec: [`requirements.md`](./requirements.md)
- CLI reference: [`cli-reference.md`](./cli-reference.md)
- Architecture: [`architecture.md`](./architecture.md)
- Issues / discussions: <https://github.com/your-org/kb-mcp/issues>
