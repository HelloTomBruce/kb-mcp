# kb-mcp v0.2.0 Release Notes

## Overview

kb-mcp v0.2.0 expands the **agent-native knowledge base** with three
new search modes (fuzzy, semantic, and hybrid) and completes the CRUD
surface so agents no longer need to drop into raw SQL to update or
delete a document. The whole release ships in two extras (`pip install
'kb-mcp[vec]'` for semantic search) and remains a single-file SQLite
database.

## What's new in v0.2.0

### Tools (was 4, now 8)

Four new MCP tools, also wired to the CLI:

| Tool | Purpose |
|---|---|
| `kb_list(type?, tags?, limit?, offset?)` | Browse / paginate |
| `kb_update(id, title?, body?, tags?, source?)` | Patch a document |
| `kb_delete(id)` | Soft-delete (idempotent) |
| `kb_unlink(from, to, rel?)` | Remove a typed edge |

The `kb_search` tool gains a `mode` parameter (`lexical` / `fuzzy` /
`semantic` / `hybrid`).

### Fuzzy search (migration 0002)

A second FTS5 index with the `trigram` tokenizer. With `mode=fuzzy`
the agent can match by 3-gram overlap, which catches:

* **Prefix matches** — `faste` finds `fastech-energy`
* **Token-boundary errors** — `fastech energy` finds `fastech-energy`

It does **not** fix edit-distance typos (FTS5 trigrams are
substring-based, not Levenshtein). For that, use the `hybrid` mode
which also surfaces semantic hits.

### Semantic search (migration 0003)

`sqlite-vec` (vec0 virtual table) plus an OpenAI-compatible
`HttpEmbedder` that reads the same `auxiliary.embedding` block
Hermes' vision config already uses. Configure once in
`~/.hermes/config.yaml`:

```yaml
auxiliary:
  embedding:
    base_url: https://api.example.com/v1
    model: text-embedding-3-small
    api_key: sk-...
```

Then `kb search --mode semantic "what is the LLM-friendly API
convention?"` finds semantically related docs even when no exact
token matches. Hybrid mode combines lexical + fuzzy + semantic,
preferring exact matches.

### CLI additions

* `kb update ID --title/--body/--tags/--source`
* `kb delete ID`
* `kb unlink --from ID --to ID [--rel REL]`
* `kb list --include-deleted`
* `kb search --mode {lexical,fuzzy,semantic,hybrid}`
* `kb embed` (status) / `kb embed --rebuild` (re-embed everything)
* `kb prune --older-than 30d` (hard-delete past grace period)

### Internal

* `SqliteStore` now accepts an `embedder=` parameter (defaults to
  `make_embedder()` which auto-detects from `auxiliary.embedding`).
* Soft-delete no longer drifts the FTS index (the
  external-content projection can't represent deletion; the
  search layer filters `deleted_at IS NULL` instead).
* `kb doctor` reports `active_fts_rows` (FTS rows joined to
  non-deleted docs) rather than the misleading raw count.

## Installation

```bash
pip install kb-mcp            # core (lexical + fuzzy)
pip install 'kb-mcp[vec]'     # adds semantic search (sqlite-vec + pysqlite3)
```

## Compatibility

* **Backwards compatible** with v0.1.0 databases. The two new
  migrations (`0002_trgm`, `0003_vec`) are applied on first connect.
  `0003_vec` is best-effort: it skips silently if `pysqlite3` /
  `sqlite-vec` aren't installed, and the rest of kb-mcp keeps
  working.
* The Store Protocol is unchanged. `mode` is a new keyword
  argument on `search()`; existing callers default to
  `mode="lexical"`, which is identical to v0.1 behaviour.

## Known limitations

* FTS5 trigrams can't fix insert-letter typos (`sqlitte` vs
  `sqlite`). This is a fundamental property of the tokenizer, not
  a bug. For real edit-distance fuzzy matching, use the `hybrid`
  mode (which also calls the embedding API).
* `mode='semantic'` requires the embedder to be configured. If
  not, the call raises `ValidationError` with a clear message
  pointing to `auxiliary.embedding`.
* macOS arm64 requires `pysqlite3` (no `pysqlite3-binary` wheel
  for that platform). The `vec` extra pulls it in automatically.

---

# kb-mcp v0.1.0 Release Notes

## Overview

kb-mcp is an **agent-native knowledge base** built on SQLite + FTS5, exposed as an MCP (Model Context Protocol) server. It lets AI agents store, search, and link structured Markdown documents with full-text search, soft-delete, and typed relationships.

## What's in v0.1.0

### Core Features

- **Document schema** — 6 built-in types (`project`, `decision`, `lesson`, `glossary`, `person`, `faq`) with extensible type registry
- **SQLite + FTS5 backend** — Full-text search with BM25 ranking, snippets, and soft-delete
- **MCP server** — 4 tools over stdio: `kb_search`, `kb_get`, `kb_add`, `kb_link`
- **CLI** — `kb init`, `kb add`, `kb get`, `kb search`, `kb list`, `kb link`, `kb doctor`, `kb import`, `kb export`
- **Markdown I/O** — Import/export documents with YAML frontmatter
- **Migration runner** — Idempotent DDL with versioning

### Technical Highlights

- **Store Protocol** — Abstract interface enabling multiple backends (SQLite, in-memory StubStore)
- **Soft delete + prune** — Documents are marked deleted, not removed; `prune` hard-deletes after grace period
- **Idempotent links** — Typed edges between documents, deduplicated by `(from_id, to_id, rel)`
- **Source-based upsert** — Re-importing the same file updates rather than duplicates
- **100% test coverage** — 136 tests across unit, integration, and E2E (real SQLite, subprocess MCP server)
- **Type-safe** — Full mypy coverage with zero errors

## Commits since scaffold (12)

| Commit | Description |
|--------|-------------|
| `67d75be` | Scaffold project |
| `6b28160` | README, requirements, quickstart, cli-reference |
| `d153593` | 4-wave implementation plan |
| `efc2f69` | Schema + Store Protocol + DDL + architecture |
| `da70d9d` | SqliteStore + migration runner + 38 tests |
| `2192eb5` | Subagent output landed |
| `a22c14f` | MCP server with 4 tools + E2E tests |
| `32672a7` | Address Wave 1 review findings |
| `42a9d3d` | CONTRIBUTING + CoC + client examples |
| `0b446ff` | CI workflows + pyproject fixes |
| `6dcaeaa` | Code review Wave 2A+3 |
| `3640f86` | Address Wave 2A+3 review findings |
| `9839a69` | Wire md_io into CLI + CJK slugify |

## Installation

```bash
pip install kb-mcp
```

Or with uv:
```bash
uv tool install kb-mcp
```

## Quick Start

```bash
# Initialize database
kb init

# Add a document
kb add --type project --title "kb-mcp" --body "Agent-native knowledge base"

# Search
kb search "knowledge base"

# Start MCP server
kb serve
```

## PyPI Trusted Publisher Setup

Before the first release, configure **OIDC trusted publishing** on PyPI and TestPyPI:

1. **PyPI**: Go to [pypi.org/manage/account/publishing](https://pypi.org/manage/account/publishing)
   - Add a new pending publisher:
     - **PyPI Project Name**: `kb-mcp`
     - **Owner**: `zhangbei`
     - **Repository name**: `kb-mcp`
     - **Workflow name**: `publish.yml`
     - **Environment name**: `pypi`

2. **TestPyPI**: Go to [test.pypi.org/manage/account/publishing](https://test.pypi.org/manage/account/publishing)
   - Add a new pending publisher:
     - **PyPI Project Name**: `kb-mcp`
     - **Owner**: `zhangbei`
     - **Repository name**: `kb-mcp`
     - **Workflow name**: `publish.yml`
     - **Environment name**: `testpypi`

The `publish.yml` workflow automatically detects prerelease tags (`v0.1.0rc1`, `v0.1.0a1`) and routes them to TestPyPI; stable tags (`v0.1.0`) go to PyPI.

## Recommended Release Flow

1. Tag `v0.1.0rc1` → TestPyPI → verify OIDC flow works
2. Tag `v0.1.0` → PyPI → stable release

---

**Full documentation**: [docs/architecture.md](docs/architecture.md)  
**Contributing**: [CONTRIBUTING.md](CONTRIBUTING.md)  
**License**: MIT
