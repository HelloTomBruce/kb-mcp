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
