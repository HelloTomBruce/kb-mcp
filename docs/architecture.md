# kb-mcp — Architecture

This is the **internal design** document. For *what* kb-mcp is and *what*
v0.1.0 ships, see [`requirements.md`](./requirements.md). For *how* to use
it, see [`quickstart.md`](./quickstart.md). For the **implementation
plan and wave structure**, see [`plan.md`](./plan.md).

**Audience:** anyone contributing to the codebase or integrating kb-mcp as
a library. Anyone just *using* kb-mcp can stop reading here.

---

## 1. Module layout

```
src/kb_mcp/
├── __init__.py          # re-exports the public API
├── schema.py            # pydantic models, TypeRegistry, exceptions, ID helpers
├── store.py             # Store Protocol (no implementation)
├── store/
│   ├── __init__.py      # re-exports SqliteStore
│   └── sqlite.py        # SQLite + FTS5 implementation
├── md_io.py             # Markdown frontmatter parser + import/export
├── cli.py               # Click CLI (init/add/get/search/list/link/import/export/doctor/serve)
├── mcp_server.py        # FastMCP server (stdio)
└── migrations/
    └── 0001_init.sql    # initial SQLite DDL

tests/
├── test_schema.py           # pydantic models + slug/id generation
├── test_store_contract.py   # Protocol conformance: StubStore + SqliteStore pass
├── test_store_sqlite.py     # SQLite-specific behaviour (FTS sync, WAL, etc.)
├── test_md_io.py            # Markdown I/O round-trip
├── test_cli_stub.py         # CLI driven against StubStore
├── test_e2e.py              # CLI end-to-end (real subprocess)
└── test_mcp_e2e.py          # MCP server end-to-end (real subprocess)
```

**Dependency graph** (no cycles; arrows point from importer to importee):

```
cli ──┐
      ├──▶ store (Protocol)
mcp ──┤    ├──▶ schema
md_io ┘    └──▶ migrations (raw SQL, loaded by sqlite impl)

schema   ← standalone (only depends on pydantic)
```

`mcp_server` and `cli` and `md_io` only ever import from `store` (the
Protocol module), **never** from `store.sqlite`. The concrete SQLite
implementation is wired in at the entry point (either `cli.main` or
`mcp_server.main`), not at the module level.

---

## 2. Public API surface

Everything importable from `kb_mcp` is listed in `__init__.py`. Anything
not re-exported there is internal and may change without notice.

```python
from kb_mcp import (
    Document, Project, Decision, Lesson, Glossary, Person, Faq,
    DocumentType, Link, SearchHit, ImportReport, DoctorReport, DoctorCheck,
    TypeRegistry, default_registry,
    make_id, slugify,
    NotFoundError, DuplicateError, ValidationError, IntegrityError,
)
```

The `Store` Protocol is importable from `kb_mcp.store` but **not** from
`kb_mcp` directly — users who want to type-hint against it must reach in.

---

## 3. Data model

### 3.1 SQLite DDL

The full DDL is in [`migrations/0001_init.sql`](../src/kb_mcp/migrations/0001_init.sql).
This section explains the design choices; the file itself is the
authoritative source.

#### `documents`

```
id         TEXT PRIMARY KEY          -- slug, e.g. "proj/kb-mcp"
type       TEXT NOT NULL             -- "project" | "decision" | ... | custom
title      TEXT NOT NULL
body       TEXT NOT NULL DEFAULT ''
tags       TEXT NOT NULL DEFAULT '[]'   -- JSON array of strings
source     TEXT                         -- origin file path (nullable)
created_at TEXT NOT NULL                -- ISO-8601 UTC
updated_at TEXT NOT NULL
deleted_at TEXT                         -- ISO-8601 UTC or NULL (soft delete)
```

Indexes:

- `idx_documents_type` — partial, `WHERE deleted_at IS NULL`
- `idx_documents_updated` — partial, ordered DESC for `list()`
- `idx_documents_source` — partial, `WHERE source IS NOT NULL`, for
  idempotent re-import

Why `tags` is JSON-encoded text rather than a join table: every query
pattern that needs tags also needs the document body, and the
denormalised form keeps the row count low. For v0.1 scale (≤ 100k docs)
this is the right trade-off. If tag-only queries become hot later, add
a `document_tags(document_id, tag)` table in migration 0002+.

#### `links`

```
from_id    TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE
to_id      TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE
rel        TEXT NOT NULL DEFAULT 'relates-to'
created_at TEXT NOT NULL
PRIMARY KEY (from_id, to_id, rel)
```

Idempotent on the primary key. `rel` is a free-form string up to 64 chars;
the store validates it is non-empty but does not restrict to a closed set
(so users can define custom relations like `supersedes`,
`blocks`, `references`).

#### `docs_fts` (FTS5 virtual table)

```
CREATE VIRTUAL TABLE docs_fts USING fts5(
    title, body, tags,
    content='documents',
    content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);
```

Contentless mirror of `documents`. Triggers `docs_ai` / `docs_ad` /
`docs_au` keep it in sync. **Soft-delete** is handled at the
search layer (filter `WHERE deleted_at IS NULL` after the FTS match),
because the trigger-based mirror cannot see soft-delete state without
extra logic. See `store/sqlite.py::SqliteStore.search` for the exact
query.

The `unicode61 remove_diacritics 2` tokenizer handles CJK reasonably
well for v0.1. A language-specific tokenizer (e.g. `trigram` for
Chinese, `porter` for stemming) is a v0.2+ concern; see
[requirements.md § 6.6 (NFR-I-2)](./requirements.md).

#### `schema_version`

```
version    INTEGER PRIMARY KEY
name       TEXT NOT NULL
applied_at TEXT NOT NULL
```

Migration runner reads this table; missing row means migration not yet
applied; out-of-order version numbers are rejected.

### 3.2 Pydantic models

See [`src/kb_mcp/schema.py`](../src/kb_mcp/schema.py). Key invariants:

- `Document.id` matches `^[a-z0-9][a-z0-9/_-]*$`
- `Document.tags` items match `^[a-z0-9][a-z0-9_-]*$` (lowercase, no spaces)
- `Document.title` non-empty after stripping
- `Document.body` capped at 1 MB
- `created_at` / `updated_at` / `deleted_at` accept `datetime` or ISO-8601
  string; always serialised as ISO-8601 in the SQLite layer
- Subclasses (`Project`, `Decision`, …) lock the `type` field via
  `Literal[...]` for static type-checkers but add no extra fields in v0.1
- `Link` is **frozen** (immutable; primary-key semantics)
- `SearchHit` carries `doc`, `snippet`, `score` (raw BM25 — lower is better)

### 3.3 ID scheme

`kb_mcp.schema.make_id(type, title)` returns `<prefix>/<slug>`, where:

- prefix is `proj | dec | lesson | glossary | person | faq` for the six
  built-in types
- prefix is the type name itself for custom types
- slug is `slugify(title)` (lowercase, runs of non-word → `-`, trimmed)

Examples:

```
make_id("project", "kb-mcp")            # "proj/kb-mcp"
make_id("decision", "Use SQLite FTS5")  # "dec/use-sqlite-fts5"
make_id("custom-type", "Hello World")   # "custom-type/hello-world"
```

The CLI auto-generates the id when the user passes `--title` without
`--id`. The MCP server does the same on `kb_add`. Collision policy: the
store raises `DuplicateError`; callers may retry with a numeric suffix
(`-1`, `-2`, …). v0.1.0 does not auto-suffix — the agent / user
explicitly chooses.

### 3.4 Soft delete

`Store.delete(id)` sets `deleted_at = now()`. Reads (`get`, `list`,
`search`) filter `WHERE deleted_at IS NULL`. `prune(older_than)`
hard-deletes soft-deleted rows after the grace period. `kb export`
includes soft-deleted docs only if `--include-deleted` is passed.

This makes `kb import` reversible within the grace period: a bad
re-import does not destroy data, only marks it for pruning.

---

## 4. Interface contracts

### 4.1 `Store` Protocol

Defined in [`src/kb_mcp/store.py`](../src/kb_mcp/store.py). Method-by-method:

| Method | Returns | Raises |
|---|---|---|
| `add(doc)` | stored id (str) | `DuplicateError`, `ValidationError` |
| `update(id, **fields)` | updated `Document` | `NotFoundError`, `ValidationError` |
| `delete(id)` | None | `NotFoundError` |
| `get(id, include_deleted=False)` | `Document` | `NotFoundError` |
| `list(type?, tags?, limit=100, offset=0, include_deleted=False)` | `list[Document]` | — |
| `search(query, type?, tags?, limit=10)` | `list[SearchHit]` | `ValidationError` |
| `link(from, to, rel="relates-to")` | `Link` | `NotFoundError`, `ValidationError` |
| `unlink(from, to, rel=None)` | int (count removed) | — |
| `backlinks(id)` | `list[Link]` | — |
| `outlinks(id)` | `list[Link]` | — |
| `import_many(docs)` | `ImportReport` | — (per-doc errors collected in report) |
| `export_all(include_deleted=False)` | `list[Document]` | — |
| `doctor()` | `DoctorReport` | — (always returns a report) |
| `prune(older_than)` | int (count removed) | — |
| `close()` | None | — |

Full docstrings live in the source. Implementers MUST honour these
contracts; the test suite (`tests/test_store_contract.py`) enforces
them against any class registered as a `Store`.

### 4.2 `TypeRegistry`

```python
from kb_mcp.schema import TypeRegistry, default_registry

registry = TypeRegistry()                # empty
registry = default_registry              # ships with 6 built-ins
registry.register("custom-type", MyDoc)  # user-extensible
registry.model_for("project")            # → Project class
registry.known_types()                   # → ["decision", "faq", ...]
registry.validate("project")             # raises ValidationError on unknown (planned)
```

For v0.1.0, custom types are still backed by the same SQLite schema —
they only differ in the pydantic model used for validation. This keeps
the migration story simple. v0.2+ may add per-type table extensions.

### 4.3 Markdown I/O API (`kb_mcp.md_io`)

```python
def parse_frontmatter(text: str) -> tuple[Frontmatter, str]: ...
def render_document(doc: Document) -> str: ...
def import_dir(store: Store, dir: Path, *, dry_run: bool = False) -> ImportReport: ...
def export_dir(store: Store, dir: Path, *, force: bool = False) -> int: ...
```

- `parse_frontmatter` returns the YAML frontmatter as a dict (typed via
  `TypedDict`) plus the body. Unrecognised frontmatter keys are preserved.
- `render_document` produces a stable Markdown representation: frontmatter
  block (YAML) + body, separated by `\n---\n\n`.
- `import_dir` walks `dir` recursively, skipping hidden files and
  non-`.md` files. Updates by `source` path (idempotent re-import).
  Returns per-file outcomes in `ImportReport.errors`.
- `export_dir` writes one `.md` per document, named `<slug>.md`, with
  numeric suffix on collision. Refuses to overwrite existing files unless
  `force=True`. Returns count written.

**Path-traversal guard (NFR-S-3):** `import_dir` rejects any file whose
resolved path escapes `dir`. `export_dir` rejects any `doc.source`
whose resolved path escapes `dir`.

### 4.4 MCP tool schemas

```python
# kb_search
class KbSearchInput(BaseModel):
    query: str = Field(min_length=1)
    type: str | None = None
    tags: list[str] | None = None
    limit: int = Field(default=10, ge=1, le=100)

# kb_get
class KbGetInput(BaseModel):
    id: str = Field(min_length=1)

# kb_add
class KbAddInput(BaseModel):
    type: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=512)
    body: str = Field(default="", max_length=1_000_000)
    tags: list[str] | None = None
    source: str | None = None

# kb_link
class KbLinkInput(BaseModel):
    from_id: str
    to_id: str
    rel: str = Field(default="relates-to", min_length=1, max_length=64)
```

Error handling — tool errors use MCP's `isError` content convention (not
JSON-RPC-level `error` objects). The server raises `RuntimeError(f"MCP error
{code}: {msg}")`, which FastMCP converts to a tool result with `isError: true`
and the error text embedded in the content. The code is included as a prefix
for programmatic extraction by clients.

Error code mapping (embedded in the error text):

| kb-mcp exception | MCP code | Notes |
|---|---|---|
| `ValidationError` | `-32602` | Invalid params |
| `NotFoundError` | `-32004` | |
| `DuplicateError` | `-32005` | Caller may retry with disambiguating title |
| `IntegrityError` | `-32603` | Internal error |
| Other | `-32603` | Internal error |

---

## 5. Configuration & paths

v0.1.0 ships with **environment variables only** — no config file.
See [`cli-reference.md`](./cli-reference.md) for the full table.

| Var | Default | Purpose |
|---|---|---|
| `KB_MCP_HOME` | `~/.local/share/kb-mcp/` | DB root |
| `KB_MCP_LOG_LEVEL` | `WARNING` | DEBUG / INFO / WARNING / ERROR |
| `KB_MCP_NO_COLOR` | unset | Disable ANSI colour |

**`KB_MCP_HOME` resolution:**

1. Env var, if set
2. `~/.local/share/kb-mcp/` on Linux/macOS
3. `~/Library/Application Support/kb-mcp/` on macOS as fallback (TODO:
   pick one; see [requirements.md § 12 (OQ-2)](./requirements.md))

---

## 6. Decision log

Architecture-level decisions recorded here. Each decision cites its
context, choice, and consequences. Append-only; do not edit past entries.

### ADR-0001 — SQLite + FTS5 as the v0.1 backend

- **Context:** need a single-binary, zero-deps storage layer with
  full-text search that ships before v1.0.
- **Decision:** SQLite (stdlib) + FTS5 extension. No server process.
- **Consequences:**
  - ✅ `pip install kb-mcp` and go — no extra services
  - ✅ Trivial backup (single file)
  - ⚠️ Concurrent writers serialised — single-writer at a time
  - ⚠️ v0.2 may add `sqlite-vss` for hybrid BM25 + embedding ranking

### ADR-0002 — Soft delete with grace-period prune

- **Context:** `kb import` must be idempotent and reversible within a
  reasonable window; hard delete on `kb import` would lose data on
  every bad re-import.
- **Decision:** `delete()` sets `deleted_at`. `prune(older_than=30d)`
  hard-deletes soft-deleted rows. Default 30-day grace period.
- **Consequences:**
  - ✅ `kb import` is reversible within 30 days by re-importing the
    previous vault
  - ⚠️ DB grows during grace period; users can `kb prune --older-than 1d`
  - ⚠️ `search()` MUST filter `deleted_at IS NULL`

### ADR-0003 — Protocol-based Store, not abstract base class

- **Context:** need `StubStore` for unit tests and a possible future
  Postgres backend.
- **Decision:** `typing.Protocol` with `@runtime_checkable`. The CLI and
  MCP server depend on the Protocol, not the concrete `SqliteStore`.
- **Consequences:**
  - ✅ `StubStore` works without subclassing
  - ✅ Alternative backends can drop in by implementing the Protocol
  - ⚠️ `isinstance(x, Store)` only checks method *names*, not signatures
    — covered by `test_store_contract.py` instead

### ADR-0004 — Markdown frontmatter via `python-frontmatter`

- **Context:** need a parser for YAML frontmatter that handles comments,
  multiline values, and unknown keys gracefully.
- **Decision:** Use `python-frontmatter` library (BSD-licensed, ~600 LOC,
  zero transitive deps).
- **Consequences:**
  - ✅ Battle-tested
  - ✅ Preserves unknown frontmatter keys for round-trip
  - ⚠️ One more dep (acceptable; already in the dependency tree)

---

## 7. Cross-cutting concerns

### 7.1 Logging

`kb serve` writes structured JSON to **stderr**. Body content is **never**
logged (privacy; cf. NFR-O-2). Default level `WARNING`; settable via
`KB_MCP_LOG_LEVEL`.

### 7.2 Exit codes

CLI follows `sysexits.h` style where applicable:

| Code | Meaning |
|---|---|
| 0 | Success |
| 2 | Validation error |
| 3 | Not found |
| 4 | Conflict |
| 5 | Internal error |
| 64 | Usage error |

### 7.3 Thread safety

Single-threaded per process. SQLite WAL handles multi-process writers,
but a single `kb` invocation is not concurrent. `kb serve` runs MCP
requests serially.

---

## 8. Testing strategy

| Layer | Test file | What it proves |
|---|---|---|
| Schema validation | `test_schema.py` | Pydantic models reject bad input; ID/slug generation is correct |
| Store contract | `test_store_contract.py` | Both `StubStore` and `SqliteStore` satisfy the Protocol |
| Store / SQLite | `test_store_sqlite.py` | FTS triggers fire, WAL mode active, FK on, soft-delete filter correct |
| Markdown I/O | `test_md_io.py` | Round-trip import → export → import is no-op; path-traversal blocked |
| CLI (in-process) | `test_cli_stub.py` | Every Click command wired and exit-coded correctly |
| E2E CLI | `test_e2e.py` | Subprocess `kb` invocations work; `--json` flag; exit codes |
| E2E MCP | `test_mcp_e2e.py` | `kb serve` speaks JSON-RPC correctly; tools registered |

**No mocks.** Real SQLite temp file via `tmp_path` fixture. Real subprocess
for CLI / MCP. The only stub is `StubStore` itself, which is the
in-memory implementation under test.

**Coverage targets** (enforced in CI via `pytest-cov`):

- `store/sqlite.py` ≥ 80% lines
- overall ≥ 70% lines

---

## 9. Open architectural questions

See [`requirements.md` § 12 (open questions)](./requirements.md). Most
pressing:

- **OQ-2.** Default `KB_MCP_HOME` on macOS — `~/.local/share/kb-mcp/`
  (XDG-style, simpler) vs `~/Library/Application Support/kb-mcp/`
  (Apple convention). v0.1 ships with XDG-style on both platforms; we
  can revisit before v1.0.
- **OQ-3.** Markdown body image references — v0.1 ignores; v0.2 may
  resolve relative paths against the vault root.
