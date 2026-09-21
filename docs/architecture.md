# Architecture

## Overview

`kb-mcp-lite` is a lightweight, agent-native knowledge base built on SQLite. It exposes data through an MCP server (for AI agents), a Click CLI (for humans), and a FastAPI web UI (for administration).

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  AI Agent   │     │   CLI (kb)  │     │  Admin UI   │
│  (MCP)      │     │  (Click)    │     │  (FastAPI)  │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │
       └───────────────────┼───────────────────┘
                           │
                    ┌──────▼──────┐
                    │    Store    │  (Protocol / Interface)
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │ SqliteStore │  (WAL mode)
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
        ┌─────▼─────┐ ┌───▼───┐ ┌─────▼─────┐
        │ documents │ │ FTS5  │ │  vec0     │
        │  (table)  │ │ index │ │ (vectors) │
        └───────────┘ └───────┘ └───────────┘
```

## Core Principles

1. **Store Protocol** — all storage goes through a PEP 544 `Store` protocol. `SqliteStore` is the production implementation; `StubStore` is used in tests.
2. **Schema-first** — `Document` is a Pydantic v2 model. Frontmatter, CLI args, and MCP inputs all validate against it.
3. **FTS5 + vec0** — full-text search uses SQLite FTS5 (BM25); semantic search uses sqlite-vec `vec0` virtual tables.
4. **Single-file DB** — each vault is a single `.db` file. WAL mode for concurrent reads.
5. **Agent-native** — the MCP server is the primary interface. CLI and web UI are secondary.

## Module Map

```
src/kb_mcp_lite/
├── schema.py              # Document, Link, SearchHit, TypeRegistry, exceptions
├── store.py               # Store Protocol (interface contract)
├── store/
│   ├── sqlite.py          # SqliteStore (composes 4 mixins)
│   ├── search.py          # SearchMixin — FTS5 + vec0 hybrid search
│   ├── embedding.py       # EmbeddingMixin — vec0 vectors, similarity, duplicates
│   ├── versioning.py      # VersioningMixin — history, snapshots, diff, restore
│   ├── maintenance.py     # MaintenanceMixin — doctor, prune, stats, subgraph
│   ├── embedding_queue.py # EmbeddingQueue — async queue with state machine
│   └── connection.py      # Shared sqlite3 connection factory
├── mcp_server.py          # FastMCP server (25 tools, 13 resources, 7 prompts)
├── cli.py                 # Click CLI (28 commands)
├── md_io.py               # Markdown frontmatter parser + bulk import/export
├── embedder.py            # OpenAI-compatible embedding client
├── worker.py              # Background embedding worker thread
├── watcher.py             # File watcher (event/poll modes)
├── scheduler.py           # APScheduler task scheduler (5 built-in tasks)
├── vault.py               # Multi-vault management
├── graph_query.py         # Multi-hop graph query engine (BFS)
├── relations.py           # Typed relation vocabulary + impact analysis
├── link_parser.py         # Body-level reference parser [text](id)
├── context_guard.py       # Git diff → relevant decisions/lessons
├── merge.py               # 3-way Markdown merge
├── config.py              # XDG config loader
├── migrations.py          # Forward-only SQL migration runner
├── admin/                 # FastAPI web UI
│   ├── routes_docs.py     # Document CRUD + search
│   └── routes_meta.py     # Overview, links, graph, settings
└── concurrency/
    └── write_lock.py      # Cross-process flock-based write lock
```

## Data Model

### Document

```python
class Document(BaseModel):
    id: str  # auto-generated if empty (e.g. "decision/use-sqlite")
    type: str  # "project" | "decision" | "lesson" | "glossary" | ...
    title: str
    body: str  # Markdown content
    tags: list[str]
    aliases: list[str]  # alternative IDs
    source: str  # relative file path (for import tracking)
    metadata: dict  # arbitrary key-value pairs
    created_at: str  # ISO 8601
    updated_at: str  # ISO 8601
    deleted_at: str | None  # soft-delete timestamp
```

### 9 Built-in Types

| Type | Use Case |
|------|----------|
| `project` | Project metadata and links |
| `decision` | Architecture Decision Records |
| `lesson` | Post-incident lessons learned |
| `glossary` | Domain terminology |
| `person` | Team member profiles |
| `faq` | Frequently asked questions |
| `api` | API endpoint documentation |
| `runbook` | Operational runbooks |
| `release` | Release notes and changelogs |

### Links

```python
class Link(BaseModel):
    from_id: str  # source document
    to_id: str  # target document
    rel: str  # relation type (e.g. "depends-on", "supersedes")
    created_at: str
```

Links are idempotent on `(from_id, to_id, rel)`.

### 10 Standard Relations

| Relation | Direction | Description |
|----------|-----------|-------------|
| `relates-to` | any | Generic association |
| `supersedes` | A → B | A replaces B |
| `superseded-by` | A → B | B replaces A |
| `depends-on` | A → B | A needs B |
| `governs` | A → B | A constrains B |
| `blocks` | A → B | A prevents B |
| `is_influence` | A → B | A influences B |
| `derives-from` | A → B | A is derived from B |
| `implements` | A → B | A implements B |
| `tests` | A → B | A tests B |

## Search Architecture

```
Query
  │
  ├── lexical  ──→  FTS5 MATCH (BM25 ranking)
  │
  ├── fuzzy    ──→  FTS5 trigram tokenizer (typo-tolerant)
  │
  ├── semantic ──→  vec0 cosine similarity (requires embeddings)
  │
  └── hybrid   ──→  Reciprocal Rank Fusion of all available channels
```

- `rrf_k` (default 60) controls the fusion constant
- `expand_graph` option attaches 1-hop graph neighbors to results
- `decay` parameter controls score falloff for distant neighbors

## Embedding Pipeline

```
Document added/updated
        │
        ▼
embedding_queue (SQLite table)
        │
        ▼
EmbeddingWorker (background thread)
        │
        ▼
OpenAI-compatible API (/v1/embeddings)
        │
        ▼
vec0 virtual table (vector storage)
```

- Queue states: `pending` → `in_progress` → `done` / `failed`
- Exponential backoff on failure (1s → 2s → 4s → ...)
- Worker drains queue automatically on startup

## Concurrency Model

- **WAL mode** — concurrent reads, serialized writes
- **WriteLock** — optional flock-based lock for cross-process safety (`--strict-lock`)
- **EmbeddingWorker** — single background thread (no thread pool)
- **File watcher** — event mode (watchfiles/inotify) or poll mode (os.walk)

## Migrations

Forward-only SQL scripts in `src/kb_mcp_lite/migrations/`:

| Migration | Purpose |
|-----------|---------|
| 0001 | Initial schema (documents, links, FTS5) |
| 0002 | embedding_queue table |
| 0003 | vec0 virtual table |
| 0004 | document history / snapshots |
| 0005 | aliases column |
| 0006 | audit_log table |
| 0007 | metadata column |
| 0008 | schedule_history table |

Migrations run automatically on `SqliteStore` init. Schema version tracked in `meta` table.

## Scheduled Tasks

| Task | Interval | Description |
|------|----------|-------------|
| `auto-commit` | hourly | Export changed docs to vault `md/` directory |
| `auto-embed` | 15min | Process pending embedding queue entries |
| `auto-reindex` | 6h | Rebuild FTS5 index |
| `doctor` | daily | Run health checks |
| `prune` | daily | Remove old soft-deleted documents |

Tasks auto-disable after 3 consecutive failures. Re-enable via `kb scheduler enable <task>`.

## Tech Stack

| Component | Technology |
|-----------|------------|
| Database | SQLite 3 (WAL mode) |
| Full-text search | FTS5 (BM25) |
| Fuzzy search | FTS5 trigram tokenizer |
| Vector search | sqlite-vec (`vec0`) |
| Embedding client | httpx (OpenAI-compatible) |
| MCP server | FastMCP 1.x (stdio) |
| Web admin | FastAPI + Jinja2 |
| CLI | Click 8.x |
| Data model | Pydantic v2 |
| Markdown | python-frontmatter |
| File watching | watchfiles (Rust-based) |
| Scheduling | APScheduler |
| Concurrency | flock (WriteLock) |
| Build | setuptools + pyproject.toml |
| Testing | pytest + pytest-cov (≥70%) |
| Linting | ruff + mypy |
