# kb-mcp — Requirements Specification

**Version:** 0.1.0-draft
**Status:** alpha, pre-implementation
**Last updated:** 2026-06-18

This document is the source of truth for *what* kb-mcp is and *what* v0.1.0
will ship. Architecture and internal design live in `architecture.md`; this
file is product-focused and stable.

---

## 1. Background and motivation

### 1.1 The gap

Today's knowledge management falls into three camps:

1. **Human-first** (Notion, Obsidian, Confluence) — rich UIs, free-form
   prose, no schema, no agent protocol.
2. **Search-first** (Elasticsearch, Meilisearch) — inverted indexes over
   arbitrary text, but no document semantics and no agent-native API.
3. **Embedding-first** (Chroma, LanceDB, Pinecone) — semantic similarity
   over chunks, but opaque to LLMs that need *named, typed* facts.

LLM agents live in none of these worlds cleanly. An agent reasoning about a
project needs:

- a way to **store** typed facts ("project X uses stack Y", "we decided Z
  because of W")
- a way to **query** them — exact match, full-text, or "give me everything
  about project X"
- a way to **link** facts ("this decision superseded that one")
- a way to **cite** them when answering the user

All of these are easier when the storage is **typed, local, fast, and
exposed via a protocol the agent already speaks**. There is no off-the-shelf
tool that nails all four. `kb-mcp` does.

### 1.2 Adjacent projects and why not just use them

| Project | Why not |
|---|---|
| **Obsidian + MCP plugin** | Requires Obsidian running; not headless; per-user vault not agent-friendly |
| **Chroma / LanceDB** | Embedding-only, chunk-level, no schema or links; opaque to agents that need named facts |
| **SQLite alone** | No schema, no types, no agent protocol — kb-mcp wraps it |
| **Notion API** | Cloud-only, rate-limited, paid at scale, no MCP |
| **LangChain / LlamaIndex memory** | Coupled to a framework; not portable across agents |

`kb-mcp` is small on purpose: one storage backend (SQLite), one wire
protocol (MCP), one CLI. Anything bigger is out of scope for v0.1.

---

## 2. Target users

### 2.1 Primary: solo developer with an LLM agent setup

Runs `claude-code`, `codex`, `opencode`, `kimi`, or `Hermes`. Wants the
agent to **remember** decisions, projects, and lessons across sessions
without re-explaining each time.

**Wins:** agent pulls up "what stack does project X use" from kb in 100ms
instead of asking the human.

### 2.2 Secondary: small team (2–10 people) sharing agent context

A team using a shared agent pool wants the team-shared facts (decisions,
architecture, glossary) reachable from every agent. v0.1 ships single-user
local; v0.3 plans shared-vault mode (see roadmap).

### 2.3 Out of scope for v0.1

- Large enterprises (need SSO, audit logs, RBAC) → v1.0+
- Non-technical writers (need a web UI) → v0.4+
- Real-time multi-user collaborative editing → not planned

---

## 3. User stories

### 3.1 P0 — must ship in v0.1

- **U1.** As a developer, I can `pip install kb-mcp` and run `kb init` to
  get a working KB in under 60 seconds.
- **U2.** As an agent operator, I can register `kb serve` as an MCP server
  and see `kb_search`, `kb_get`, `kb_add`, `kb_link` exposed to my agent.
- **U3.** As an agent, when asked "what stack does project X use?", I can
  call `kb_search("project X stack", type="project")` and get a
  ranked, snippet-bearing result in under 200ms (10k-doc corpus).
- **U4.** As a human, I can edit a Markdown file in
  `~/.local/share/kb-mcp/vault/` and have the change picked up by `kb
  import` (or hot-reload) without restarting the MCP server.
- **U5.** As a user, my data stays on my machine. No network calls are
  made by `kb-mcp` itself. (Verified by network-traffic audit.)
- **U6.** As an agent, I can create typed documents (`decision`,
  `lesson`, …) with tags and links, and trust that `kb_get(id)` returns
  the same content I wrote.

### 3.2 P1 — nice to have for v0.1, may slip

- **U7.** As a user, `kb export` produces a Markdown directory I can
  commit to git and round-trip via `kb import`.
- **U8.** As an agent, `kb_link(from, to, rel="supersedes")` creates a
  typed edge and `kb_get(id)` includes backlinks.
- **U9.** As a user, `kb doctor` validates the DB, surfaces schema
  drift, and suggests `kb reindex` if FTS is out of sync.

### 3.3 Out of scope for v0.1 (deferred)

- Web UI, mobile UI, semantic search, multi-user auth, hosted mode,
  cloud sync, real-time collab.

---

## 4. Functional scope

### 4.1 In v0.1.0

| ID | Feature | Notes |
|---|---|---|
| F1 | SQLite + FTS5 store | Default at `~/.local/share/kb-mcp/kb.db`; override via `KB_MCP_HOME` |
| F2 | Click CLI: `init / add / get / search / list / link / serve / import / export / doctor` | JSON and human output formats |
| F3 | MCP server on stdio | Four tools: `kb_search`, `kb_get`, `kb_add`, `kb_link` |
| F4 | Six built-in document types | `project`, `decision`, `lesson`, `glossary`, `person`, `faq` |
| F5 | User-extensible types | Subclass `kb_mcp.schema.Document` |
| F6 | Tags, frontmatter-driven Markdown import/export | One Markdown file per document |
| F7 | Typed links between documents | `rel` field; backlink queries |
| F8 | Snippet-aware full-text search | BM25 with snippet extraction via `snippet()` FTS5 function |
| F9 | Config via env vars only | `KB_MCP_HOME`, `KB_MCP_LOG_LEVEL`; no config files for v0.1 |
| F10 | Test suite: pytest, real SQLite temp file, no mocks | Coverage target: ≥ 80% lines on `store.py`, ≥ 70% overall |
| F11 | README + `docs/quickstart.md` + `docs/cli-reference.md` + `docs/requirements.md` (this file) | All English |
| F12 | MIT license + PyPI publish + GitHub Actions CI | CI runs lint + test on Python 3.10, 3.11, 3.12 |

### 4.2 Explicitly **out** of v0.1.0

- ❌ Web UI / TUI
- ❌ Vector search / embeddings
- ❌ Multi-user, auth, RBAC
- ❌ Cloud sync, hosted mode
- ❌ Multi-vault (per-project isolated KBs) — see v0.3
- ❌ Plugin system / hooks
- ❌ Auto-sync from external sources (Notion, GitHub, …)
- ❌ Config-file support (env vars only for v0.1)

---

## 5. Functional requirements

### 5.1 CLI

| ID | Requirement |
|---|---|
| FR-CLI-1 | Every command supports `--json` for machine-readable output |
| FR-CLI-2 | Every command exits 0 on success, non-zero on error; error message goes to stderr |
| FR-CLI-3 | `kb init` is idempotent: re-running on an existing KB does not destroy data unless `--force` is passed |
| FR-CLI-4 | `kb add` validates type against the registered type registry before insert |
| FR-CLI-5 | `kb search` returns at most `limit` results (default 10, max 100), BM25-ranked |
| FR-CLI-6 | `kb serve` runs the MCP server on stdio; SIGINT / SIGTERM shut down cleanly within 2s |
| FR-CLI-7 | `kb import <dir>` recursively walks `.md` files, parses YAML frontmatter, inserts documents |
| FR-CLI-8 | `kb export <dir>` writes one `.md` per document, preserving frontmatter |
| FR-CLI-9 | `kb doctor` checks DB integrity, FTS sync, and orphan links; exit 1 if any issue found |

### 5.2 MCP server

| ID | Requirement |
|---|---|
| FR-MCP-1 | Server announces tool list on `initialize` per MCP spec |
| FR-MCP-2 | Tool inputs are validated with `pydantic` schemas; invalid input returns MCP error `-32602` |
| FR-MCP-3 | `kb_search` returns `{id, title, type, snippet, score}` array; empty result returns `[]`, not error |
| FR-MCP-4 | `kb_get(id)` returns full document body + metadata; unknown id returns MCP error `-32004` |
| FR-MCP-5 | `kb_add` returns the new document's id; if a document with the same `(type, title)` exists, return MCP error `-32005` unless `--allow-duplicate` |
| FR-MCP-6 | `kb_link` is idempotent: re-linking returns success without creating a duplicate edge |

### 5.3 Storage

| ID | Requirement |
|---|---|
| FR-DB-1 | Single SQLite file; `PRAGMA journal_mode=WAL`; `PRAGMA foreign_keys=ON` |
| FR-DB-2 | Schema migration is automatic; `schema_version` table tracks applied migrations |
| FR-DB-3 | FTS5 virtual table mirrors the documents table; triggers keep them in sync |
| FR-DB-4 | All timestamps stored as ISO-8601 UTC strings |
| FR-DB-5 | Soft-delete (`deleted_at`) instead of hard-delete; `kb prune` removes soft-deleted rows after a configurable grace period |

### 5.4 Markdown I/O

| ID | Requirement |
|---|---|
| FR-MD-1 | Frontmatter parsed with `PyYAML` (or `python-frontmatter`); unknown fields preserved on round-trip |
| FR-MD-2 | Body stored verbatim (no Markdown-to-HTML conversion) |
| FR-MD-3 | Filename convention: `<slug>.md` where `slug = kebab-case(title)`; collisions resolved with numeric suffix |
| FR-MD-4 | `kb import` is idempotent: re-importing the same file updates the existing document by `source` path |

---

## 6. Non-functional requirements

### 6.1 Performance

| ID | Target |
|---|---|
| NFR-P-1 | `kb search` on 10k-document corpus: p95 < 200ms |
| NFR-P-2 | `kb add` insert latency: p95 < 50ms |
| NFR-P-3 | MCP server cold-start to first tool call: < 500ms |
| NFR-P-4 | Memory footprint of `kb serve`: < 80 MB RSS for 10k documents |

### 6.2 Compatibility

- Python 3.10, 3.11, 3.12 (CI matrix)
- SQLite ≥ 3.34 (FTS5 with `bm25()` — ships with Python 3.10+ on macOS / Linux)
- OS: macOS 13+, Ubuntu 22.04+, Windows 11 (best-effort)
- MCP protocol version: track latest stable

### 6.3 Security and privacy

- **NFR-S-1.** No network calls in `kb-mcp` core. (Embedding-based features in
  v0.2+ opt-in; the opt-in path is the only one allowed to touch the network.)
- **NFR-S-2.** No telemetry. No analytics. No phone-home.
- **NFR-S-3.** All file paths user-supplied are validated against the vault
  root to prevent path traversal in `kb import / export`.
- **NFR-S-4.** Secrets in document bodies are not auto-redacted. (Out of
  scope for v0.1; document the risk in `docs/security.md`.)

### 6.4 Reliability

- **NFR-R-1.** DB corruption from power loss is bounded to a single
  in-flight transaction (WAL mode).
- **NFR-R-2.** FTS index drift is detectable via `kb doctor` and fixable
  via `kb reindex` (P1).

### 6.5 Observability

- **NFR-O-1.** Structured JSON logs to stderr in `kb serve`; configurable
  log level via `KB_MCP_LOG_LEVEL`.
- **NFR-O-2.** Each tool call logs start / end / duration / result count
  (no body content — privacy).

### 6.6 Internationalisation

- **NFR-I-1.** All user-facing strings in v0.1 are English (CLI output,
  errors, docs).
- **NFR-I-2.** Document bodies may be in any language; full-text search
  uses SQLite's default unicode61 tokenizer (covers most cases;
  language-specific tokenizers are deferred to v0.2).

### 6.7 Licensing

- **NFR-L-1.** MIT license for code and documentation.
- **NFR-L-2.** Third-party deps must be MIT, BSD, Apache-2.0, or
  similarly permissive. No GPL.

---

## 7. Data model (high level)

Full DDL in `architecture.md` § 3; here is the conceptual view:

```
Document
├── id          TEXT PK (slug-style, e.g. "proj_kb_mcp")
├── type        TEXT (one of 6 built-ins or user-defined)
├── title       TEXT
├── body        TEXT (Markdown)
├── tags        TEXT[] (JSON array)
├── source      TEXT (origin file path, if imported)
├── created_at  TEXT (ISO-8601 UTC)
├── updated_at  TEXT
└── deleted_at  TEXT NULL (soft-delete)

Link
├── from_id     TEXT → Document.id
├── to_id       TEXT → Document.id
├── rel         TEXT (e.g. "supersedes", "relates-to", "blocks")
└── created_at  TEXT
```

FTS5 mirror: `(title, body, tags)` indexed; BM25 ranking; snippet via
`snippet(docs_fts, 1, '<b>', '</b>', '…', 12)`.

---

## 8. Error handling

| Class | HTTP-style code | Examples |
|---|---|---|
| Validation | `-32602` (MCP) / exit 2 | Invalid type, missing required field |
| Not found | `-32004` / exit 3 | Unknown document id |
| Conflict | `-32005` / exit 4 | Duplicate `(type, title)` |
| Internal | `-32603` / exit 5 | SQLite I/O failure |
| Usage | exit 64 | Missing arg, unknown command |

CLI exit codes follow `sysexits.h` style where applicable.

---

## 9. Success metrics

| Metric | Target (v0.1.0 → v0.3.0) |
|---|---|
| GitHub stars | 100 → 1k |
| PyPI downloads / month | 500 → 10k |
| Time from `pip install` to first `kb search` returning a result | < 5 min (incl. reading quickstart) |
| `kb doctor` exit-0 rate on user-reported DBs | ≥ 99% |
| Open issues triaged within 7 days | ≥ 80% |
| Test coverage (`store.py`) | ≥ 80% lines |

---

## 10. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| SQLite FTS5 query planner regressions on pathological corpora | Medium | Medium | `kb doctor` exposes query plan; cap result set; v0.2 hybrid ranking |
| MCP spec churn before v0.1 | High | Medium | Pin a tested spec version in CI; ship behind a version pin |
| Users expect Notion-like UI | High | Low | README + quickstart explicitly position as agent-first; roadmap commits to UI later |
| Schema migration breaks existing DBs | Medium | High | All migrations wrapped in transactions; `schema_version` table; `kb doctor` detects drift |
| `last_insert_rowid()` reuse bug (cf. PM-system incident 2026-06-18) | Low | Low | Unit test that INSERTs in a batch and asserts every row has correct FK |

---

## 11. Glossary

| Term | Definition |
|---|---|
| **ADR** | Architecture Decision Record — a structured document capturing a decision, its context, and its consequences |
| **BM25** | Ranking function used by FTS5; standard for full-text search relevance |
| **FTS5** | SQLite's full-text search engine extension; ships with Python's `sqlite3` on most platforms |
| **MCP** | Model Context Protocol — JSON-RPC-based protocol for LLM agents to call external tools |
| **Snippet** | A short excerpt of a document body containing the matched query terms, with markers |
| **Vault** | The collection of Markdown files backing a kb-mcp database |

---

## 12. Open questions

Tracked here until resolved; moved to a "Decisions" section once answered.

- **OQ-1.** Should `kb add` require a body, or allow empty bodies? *Lean: allow empty (title-only "stub" documents are useful for agents).*
- **OQ-2.** Should the default `~/.local/share/kb-mcp/` follow XDG on Linux only, or use it on macOS too? *Lean: XDG on Linux, `~/Library/Application Support/kb-mcp/` on macOS (but check macOS conventions — `~/.local/share` works on modern macOS for many tools).*
- **OQ-3.** How do we handle Markdown body that references an image with a relative path? v0.1: ignore; v0.2+: vault-relative resolution.
- **OQ-4.** Should `kb search` accept a `--since` timestamp filter for time-bounded queries? *Lean: yes (cheap filter; agents will use it).*

---

## 13. References

- MCP spec: <https://modelcontextprotocol.io/>
- SQLite FTS5: <https://www.sqlite.org/fts5.html>
- BM25 background: <https://en.wikipedia.org/wiki/Okapi_BM25>
- Hermetic inspiration: MADR (Markdown ADR) — <https://adr.github.io/madr/>
