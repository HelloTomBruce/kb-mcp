<div align="center">

# kb-mcp

**An agent-native knowledge base.**

`pip install kb-mcp` — give any LLM agent a structured, queryable, local-first second brain.

[![PyPI version](https://img.shields.io/badge/pypi-v0.2.0-blue)](https://pypi.org/project/kb-mcp/)
[![Python](https://img.shields.io/badge/python-≥3.10-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](./LICENSE)
[![MCP](https://img.shields.io/badge/MCP-compatible-purple)](https://modelcontextprotocol.io/)
[![Status: alpha](https://img.shields.io/badge/status-alpha-orange)](#status)

</div>

---

## The problem

Knowledge bases for humans (Notion, Obsidian) and for search engines
(Elasticsearch, vector DBs) leave a gap: **LLM agents need a knowledge layer
that speaks their protocol and assumes the reader is a model, not a person.**

`kb-mcp` fills it.

| | Obsidian / Notion | Vector DBs (Chroma / LanceDB) | **`kb-mcp`** |
|---|---|---|---|
| Reader-optimised for | Humans | Embeddings | **LLM agents** |
| Protocol | Web UI | SDK | **MCP (stdio)** |
| Schema | Free-form | Free-form | **Typed (project / decision / lesson / ...)** |
| Default storage | Cloud / proprietary | Local files | **SQLite + FTS5** |
| Setup | Sign up | `pip install` + configure | **`pip install` and go** |

---

## Features

- **🧠 Agent-native.** Every document is reachable from any MCP client
  (`Claude Desktop`, `Cursor`, `OpenCode`, `Codex`, …) via
  `kb_search` / `kb_get` / `kb_add` / `kb_link`.
- **📐 Schema-first.** Six built-in document types
  (`project`, `decision`, `lesson`, `glossary`, `person`, `faq`) —
  extensible via Python subclassing.
- **🔍 Full-text search.** SQLite FTS5 with BM25 ranking. Snippet-aware
  results returned to the agent.
- **🔗 Typed links.** Documents reference other documents; backlinks are
  automatic.
- **📝 Markdown friendly.** Round-trip import/export with frontmatter.
  Humans can edit, agents can read.
- **🪶 Zero deps by default.** SQLite ships with Python. `pip install kb-mcp`
  and you're done.
- **🔒 Local-first.** Your data lives in `~/.local/share/kb-mcp/`. No
  cloud, no telemetry, no phone-home.

---

## Quickstart

```bash
pip install kb-mcp
kb init
kb add --type project --title "kb-mcp" --tags kb,mcp,open-source --body "Agent-native knowledge base."
kb search "mcp server"

# Expose to any MCP client
kb serve
```

That's it. Five commands, zero config files.

👉 Full walkthrough: [docs/quickstart.md](./docs/quickstart.md)

---

## Document types

| Type | Purpose | Example |
|---|---|---|
| `project` | Repo / initiative background | `kb-mcp`, `micro-app-fork` |
| `decision` | Architecture Decision Record (ADR) | "Use SQLite FTS5 over Elasticsearch" |
| `lesson` | Post-mortem / lessons learned | "Don't `last_insert_rowid()` across multi-INSERT batches" |
| `glossary` | Term definitions | `FTS5`, `MCP`, `ADR` |
| `person` | People the agent should recognise | "Zhang Bei, owner, uses Hermes" |
| `faq` | Frequently asked questions | "Why SQLite?" |

Subclass `kb_mcp.schema.Document` to add your own.

---

## MCP integration

Add to `~/.config/claude_desktop_config.json` (or any MCP client):

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

The agent then sees four tools:

- `kb_search(query, type?, tags?, limit?)` — BM25-ranked results with snippets
- `kb_get(id)` — full document by id (or slug)
- `kb_add(type, title, body, tags?, source?)` — create document
- `kb_link(from_id, to_id, rel?)` — typed edge between documents

---

## Development

```bash
git clone https://github.com/your-org/kb-mcp
cd kb-mcp
pip install -e ".[dev]"
pytest          # unit + E2E (real SQLite temp file, no mocks)
ruff check .
mypy src/
```

👉 Spec: [docs/requirements.md](./docs/requirements.md) ·
Architecture: [docs/architecture.md](./docs/architecture.md) ·
CLI reference: [docs/cli-reference.md](./docs/cli-reference.md)

---

## Roadmap

| Version | Scope | Status |
|---|---|---|
| **v0.1.0** | CLI + MCP server + SQLite/FTS5 + 6 doc types + Markdown I/O | 🚧 in progress |
| v0.2.0 | Vector search (sqlite-vss) as opt-in, hybrid BM25 + embedding ranking | planned |
| v0.3.0 | Multi-vault (per-project isolated KBs) + shared-vault mode | planned |
| v0.4.0 | Web UI (read-only) + collaborative editing hints | exploring |
| v1.0.0 | Postgres backend, multi-user auth, hosted mode | exploring |

See [docs/requirements.md](./docs/requirements.md) § 4 for v0.1 scope decisions
and out-of-scope list.

---

## Status

**alpha.** API and storage format may change before v0.2.0. Pin minor versions
(`kb-mcp>=0.1,<0.2`) in production.

---

## Contributing

Issues and PRs welcome. See
[CONTRIBUTING.md](./CONTRIBUTING.md) (TODO before v0.1.0 release).

By participating, you agree to abide by the
[Code of Conduct](./CODE_OF_CONDUCT.md) (TODO before v0.1.0 release).

---

## License

[MIT](./LICENSE) — do what you want, just keep the copyright notice.
