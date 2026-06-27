<div align="center">

# kb-mcp

**An agent-native knowledge base.**

`pip install kb-mcp` — give any LLM agent a structured, queryable, local-first second brain.

[![PyPI version](https://img.shields.io/badge/pypi-v0.4.7-blue)](https://pypi.org/project/kb-mcp/)
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

## `kb import` — bulk-import Markdown files

Import an entire directory of Markdown files into the vault at once.

```bash
kb import <directory> [--dry-run] [--json]
```

- `<directory>` — path to a directory of `.md` files (searched recursively)
- `--dry-run` — parse & validate every file without writing anything
- `--json` — output the import report as JSON

### Frontmatter format

Every `.md` file can begin with a YAML frontmatter block (between `---` delimiters).
The body is everything after the closing `---`.

```yaml
---
type: decision
title: Use SQLite FTS5 over Elasticsearch
tags:
  - architecture
  - database
created_at: 2025-01-15T10:00:00Z
updated_at: 2025-01-20T14:30:00Z
---

# Body text goes here

Any valid Markdown.
```

#### Required fields

| Field | Type | Description |
|---|---|---|
| `type` | `str` | Document type. One of `project`, `decision`, `lesson`, `glossary`, `person`, `faq`, or a custom type of your own. |
| `title` | `str` | Document title. Non-empty, max 512 characters. |

#### Optional fields

| Field | Type | Default | Description |
|---|---|---|---|
| `tags` | `list[str]` | `[]` | Tags for filtering and grouping. Each tag: lowercase, alphanumeric + `_`/`-`. Max 64 tags. |
| `source` | `str` | *(auto)* | Overridden by the file's relative path during import. Usually you don't set this. |
| `created_at` | `str` | `now` UTC | ISO-8601 datetime. `2025-01-15T10:00:00Z` or `2025-01-15T10:00:00+00:00`. |
| `updated_at` | `str` | `now` UTC | Same format as `created_at`. |
| `links` | `list[dict]` | `[]` | Outgoing document links. Each entry has `to` (target doc ID) and optional `rel` (default `"relates-to"`). |

> **Note:** Unknown frontmatter keys are silently passed through and ignored.

#### Examples per document type

**Project** — a repository or initiative overview:

```markdown
---
type: project
title: kb-mcp
tags:
  - mcp
  - knowledge-base
  - python
---

Agent-native knowledge base. SQLite + FTS5 + vec0 + MCP server.
```

**Decision** — an Architecture Decision Record (ADR):

```markdown
---
type: decision
title: Use SQLite FTS5 over Elasticsearch
tags:
  - architecture
  - database
created_at: 2025-01-15T10:00:00Z
links:
  - to: proj/kb-mcp
    rel: governs
  - to: glossary/fts5
---

## Context

We need full-text search that works offline with zero setup.

## Decision

Use SQLite FTS5 — it ships with Python, requires no external process,
and handles our scale.

## Consequences

+ No infra to manage
- No distributed search
```

**Lesson** — a post-mortem or lesson learned:

```markdown
---
type: lesson
title: Don't cross-connection last_insert_rowid
tags:
  - sqlite
  - bug
created_at: 2025-02-01T08:30:00Z
---

`last_insert_rowid()` is connection-scoped, not transaction-scoped.
If you INSERT on connection A but call `last_insert_rowid()` on
connection B, you get 0 — silently.
```

**Glossary** — a term definition:

```markdown
---
type: glossary
title: FTS5
tags:
  - sqlite
  - search
---

SQLite's full-text search engine. Supports BM25 ranking, prefix queries,
and incremental merge. Ships as a compile-time option in the standard
`sqlite3` module.
```

**Person** — profile of a person the agent should know about:

```markdown
---
type: person
title: Zhang Bei
tags:
  - team
  - maintainer
---

Owner of kb-mcp. Uses Hermes agent framework. Active in the MCP community.
```

**FAQ** — a frequently asked question:

```markdown
---
type: faq
title: Why SQLite?
tags:
  - faq
  - architecture
---

**Q:** Why SQLite instead of PostgreSQL or a vector DB?

**A:** SQLite ships with Python — zero deps. For a local-first agent
knowledge base, it's fast enough, and FTS5 + vec0 cover search.
```

### Import behavior

1. **Recursive walk** — all `.md` files (excluding hidden files/dirs) are found.
2. **Frontmatter parsed** — each file is read and its YAML frontmatter extracted.
3. **Document constructed** — `type` + `title` are validated (required); missing fields raise errors collected per-file.
4. **Source-based dedup** — if a document with the same `source` path already exists, it is **updated in-place** (preserving `id` and `created_at`). Otherwise a new document is **inserted**.
5. **Links created** — if a file's frontmatter has a `links` field, each link is created via `store.link()`. Failed links (e.g. target doc not found) are reported as errors.
6. **Report generated** — a summary showing inserted / updated / skipped / error counts.

```bash
$ kb import ./docs/
Imported 12 files: 8 inserted, 3 updated, 1 error
Errors:
  ./docs/broken.md: frontmatter missing required field 'type'
```

Use `--dry-run` to see what would happen before making changes:

```bash
$ kb import ./docs/ --dry-run
Would import 12 files: 8 inserted, 3 updated, 0 errors
```

### Export

The reverse — dump every document in the vault as `.md` files:

```bash
kb export <directory> [--force]
```

- Each document becomes a `<slug>.md` file (based on its ID).
- Collisions get a numeric suffix (`kb-mcp-2.md`).
- Pre-existing files are **not** overwritten unless `--force` is passed.
- After export, each document's `source` field is updated in the DB so a
  subsequent `kb import` of the same directory matches correctly.
- Outgoing document links (from `store.outlinks()`) are included in each file's
  frontmatter as a `links` list, so **import-export round-trips preserve
  document relationships**.


---

## Document types

| Type | ID prefix | Purpose | Example |
|---|---|---|---|
| `project` | `proj` | Repo / initiative background | `kb-mcp`, `micro-app-fork` |
| `decision` | `dec` | Architecture Decision Record (ADR) | "Use SQLite FTS5 over Elasticsearch" |
| `lesson` | `lesson` | Post-mortem / lessons learned | "Don't `last_insert_rowid()` across multi-INSERT batches" |
| `glossary` | `glossary` | Term definitions | `FTS5`, `MCP`, `ADR` |
| `person` | `person` | People the agent should recognise | "Zhang Bei, owner, uses Hermes" |
| `faq` | `faq` | Frequently asked questions | "Why SQLite?" |

Every document gets a stable ID auto-generated from its type and title
(e.g. `decision/use-sqlite-fts5-over-elasticsearch`). IDs are permanent —
once created, the `type`, `id`, and `created_at` fields are immutable.

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

| Tool | Description | Example |
|---|---|---|
| `kb_search` | Full-text search (lexical / fuzzy / hybrid) | `kb_search("FTS5 search")` |
| `kb_get` | Fetch document by id (also resolves aliases) | `kb_get("dec/use-sqlite-fts5")` |
| `kb_add` | Create a new document | `kb_add(type="lesson", title="…", body="…")` |
| `kb_update` | Patch fields on an existing document | `kb_update(id="…", title="New title")` |
| `kb_delete` | Soft-delete a document | `kb_delete("proj/kb-mcp")` |
| `kb_list` | Browse documents with type/tag filters | `kb_list(type="decision")` |
| `kb_link` | Create a typed edge between documents | `kb_link(from="dec/…", to="proj/…", rel="governs")` |
| `kb_unlink` | Remove typed edges | `kb_unlink(from="dec/…", to="proj/…")` |
| `kb_history` | View document version history | `kb_history("doc/…")` |
| `kb_restore` | Restore to a previous version | `kb_restore("doc/…", version=3)` |
| `kb_diff` | Field-level diff between versions | `kb_diff("doc/…", v1=1, v2=3)` |
| `kb_restore_deleted` | Restore a soft-deleted document | `kb_restore_deleted("doc/…")` |

... plus **4 Resources** — each returns a structured view:

| Resource URI | Returns |
|---|---|
| `kb://doc/{id}` | Full document with body, metadata, and backlinks |
| `kb://search/{query}` | Search results with relevance scores |
| `kb://links/{id}` | All typed edges for a document (outgoing + incoming) |
| `kb://doctor` | Health check report (integrity, missing refs, schema stats) |

... and **2 Prompts** for richer agent interaction:

| Prompt | Purpose |
|---|---|
| `new-doc` | Guided multi-step doc creation (walks the agent through type/title/body/tags) |
| `search-expert` | Expert search strategist — picks the best search mode for the query |

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
