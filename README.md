<div align="center">

# kb-mcp

**An agent-native knowledge base.**

`pip install kb-mcp` — give any LLM agent a structured, queryable, local-first second brain.

[![PyPI version](https://img.shields.io/badge/pypi-v0.3.0-blue)](https://pypi.org/project/kb-mcp/)
[![Python](https://img.shields.io/badge/python-≥3.10-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](./LICENSE)
[![MCP](https://img.shields.io/badge/MCP-compatible-purple)](https://modelcontextprotocol.io/)
[![Status: beta](https://img.shields.io/badge/status-beta-green)](#status)

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

- **🧠 Agent-native.** Every document is reachable from any MCP client via
  12 tools, 4 Resources, and 2 Prompts.
- **📐 Schema-first.** Six built-in document types
  (`project`, `decision`, `lesson`, `glossary`, `person`, `faq`) —
  extensible via Python subclassing.
- **🔍 Full-text search.** Three modes: lexical (BM25), fuzzy (trigram),
  and hybrid (combined). Optional semantic search with `sqlite-vec`.
- **📜 Version history.** Every create/update/delete is recorded. Restore
  any previous version, diff between versions, or recover soft-deleted docs.
- **🔗 Typed links.** Documents reference other documents; backlinks are
  automatic.
- **📝 Markdown friendly.** Round-trip import/export with frontmatter.
  Aliases let agents reference the same doc from different contexts.
- **🗄️ Multi-vault.** Isolated knowledge bases per project or team.
  Switch between vaults with `kb vault switch`.
- **🪶 Zero deps by default.** SQLite ships with Python. `pip install kb-mcp`
  and you're done.
- **🔒 Local-first.** Your data stays on your machine. No cloud, no
  telemetry, no phone-home.

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

## Vault quickstart (multi-space)

```bash
# Create isolated knowledge bases
kb vault create work --desc "Work projects"
kb vault create personal --desc "Personal learning"

# Switch between them
kb vault switch work
kb add --type project --title "My Work App" --body "..."

kb vault switch personal
kb add --type lesson --title "Rust tutorial notes" --body "..."

# Each vault has its own SQLite database
kb vault list
```

## Team sync (Git)

Share a team vault via any Git remote:

```bash
# A member: set up
kb vault create team --desc "Team shared knowledge"
kb vault init-git                     # git init + .gitignore
kb vault commit -m "Initial KB"       # export → git commit
kb vault push origin main             # push to remote

# B member: clone and start using
git clone <remote-url> ~/.local/share/kb-mcp-custom/
KB_MCP_HOME=~/.local/share/kb-mcp-custom kb vault list
KB_MCP_HOME=~/.local/share/kb-mcp-custom kb vault pull    # pull → import

# Daily workflow:
# Make changes...
kb add --type decision --title "Use SQLite FTS5"
# Share:
kb vault commit -m "Add ADR about FTS5"
kb vault push

# Get teammates' changes:
kb vault pull
```

Both `push` and `pull` accept optional `<remote> <branch>` arguments:
`kb vault push origin main`. When omitted, defaults are `origin` and `main`.

The sync is **text-based**: the vault's Markdown files go to a `md/` subdirectory
under Git, while the binary `.db` stays local and `.gitignore`d.

### First-time import from a Git repo

If you have an existing Git repository with `md/` (exported Markdown files) and
want to import it into a local vault, three approaches:

**①  Use `--sync-dir` (recommended for ongoing sync)**

```bash
# Clone the repo first
git clone <remote-url> ~/my-vault-repo

# Create a vault pointing at the clone
kb vault create my-vault --desc "Team KB"
kb vault init-git --sync-dir ~/my-vault-repo

# Import the Markdown files into SQLite
kb vault pull
```

This links the vault to the git clone so future `kb vault commit` / `push` / `pull`
all work without extra arguments.

**②  Direct `kb import` (one-shot, no git link)**

```bash
kb vault create my-vault
kb import ~/my-vault-repo/md/
```

Fastest for a one-off import, but subsequent `kb vault commit` won't know
where to export to unless you also run `kb vault init-git --sync-dir`.

**③  Override `KB_MCP_HOME` (isolated vault directory)**

```bash
git clone <remote-url> ~/.local/share/kb-mcp-custom/
KB_MCP_HOME=~/.local/share/kb-mcp-custom kb vault list
KB_MCP_HOME=~/.local/share/kb-mcp-custom kb vault pull
```

Puts everything under a custom directory — useful for side-by-side vaults
or testing.


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

The agent sees **12 tools**:

| Tool | Description |
|---|---|
| `kb_search` | Full-text search (lexical / fuzzy / hybrid) |
| `kb_get` | Fetch document by id (also resolves aliases) |
| `kb_add` | Create a new document |
| `kb_update` | Patch fields on an existing document |
| `kb_delete` | Soft-delete a document |
| `kb_list` | Browse documents with type/tag filters |
| `kb_link` | Create a typed edge between documents |
| `kb_unlink` | Remove typed edges |
| `kb_history` | View document version history |
| `kb_restore` | Restore to a previous version |
| `kb_diff` | Field-level diff between versions |
| `kb_restore_deleted` | Restore a soft-deleted document |

... plus **4 Resources** (`kb://doc/`, `kb://search/`, `kb://links/`, `kb://doctor`)
and **2 Prompts** (`new-doc`, `search-expert`) for richer agent interaction.

You can also serve a specific vault:
```bash
kb serve --vault project-x
```

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
| **v0.1.0** | CLI + MCP server + SQLite/FTS5 + 6 doc types + Markdown I/O | ✅ shipped |
| **v0.2.0** | Fuzzy/trigram search, semantic search (sqlite-vec), tools/CLI completion | ✅ shipped |
| **v0.3.0** | MCP Resources & Prompts, version history (restore/diff), aliases | ✅ shipped |
| **v0.4.0** | Multi-vault (isolated knowledge bases), vault CLI + MCP vault selection | ✅ shipped |
| v0.5.0 | Local embedding models, CJK tokenizer, knowledge graph visualization | exploring |
| v0.6.0 | Plugin system, external sync (Notion/GitHub), LLM-native enhancements | exploring |
| v1.0.0 | Postgres backend, multi-user auth, hosted mode | exploring |

---

## Status

**beta.** The API and storage format are stable since v0.3.0. Pin minor versions
(`kb-mcp>=0.3,<0.5`) in production if you prefer conservative upgrades.

---

## Contributing

Issues and PRs welcome. See [CONTRIBUTING.md](./CONTRIBUTING.md).

By participating, you agree to abide by the
[Code of Conduct](./CODE_OF_CONDUCT.md).

---

## License

[MIT](./LICENSE) — do what you want, just keep the copyright notice.
