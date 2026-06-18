# kb-mcp — Implementation Plan

**Goal:** ship v0.1.0 (CLI + MCP server + SQLite/FTS5 + 6 doc types + Markdown I/O)
**Strategy:** four-wave build. Wave 0 is serial and produces the **interface
contract** that all later workers code against in parallel. Waves 1–3 fan out
within the cap of `max_concurrent_children=3` and converge at integration tests.

> ⚠️ **Wave 0 is the highest-leverage step.** Skimping on it (skipping the
> protocol/interface docs, jumping straight to "build the Store") is the
> #1 way multi-agent parallel work goes wrong — agents stub against
> different assumptions and integration becomes a re-write.

---

## At-a-glance

```
Wave 0  [serial, 1 worker]   ──▶  interface contract + pydantic models + architecture.md
                                          │
Wave 1  [parallel, 3 workers] ──▶  SQLite Store  │  Markdown I/O  │  CLI skeleton
                                          │
Wave 2  [parallel, 3 workers] ──▶  MCP server  │  real CLI wiring  │  integration tests
                                          │
Wave 3  [parallel, 2 workers] ──▶  CI + PyPI  │  CONTRIBUTING / examples / README polish
                                          │
                                       v0.1.0
```

Mapping to PM tasks (project id 9):

| Wave | Worker | PM task(s) | Module |
|------|--------|-----------|--------|
| 0 | coder (serial) | 30 | schema + architecture.md + Protocol contracts |
| 1A | coder (serial within wave) | 31 | `store.py` — SQLite + FTS5 + schema_version + migrations |
| 1B | subagent #1 | 35 | `md_io.py` — frontmatter parser + import/export |
| 1C | subagent #2 | 33 | `cli.py` — Click skeleton with stubbed Store calls |
| 2A | subagent #1 | 34 | `mcp_server.py` — FastMCP, 4 tools on stdio |
| 2B | subagent #2 | 33 (cont) | `cli.py` — wire stubs to real Store from 1A |
| 2C | subagent #3 / coder | 36 | `tests/` — pytest, real SQLite temp file, no mocks |
| 3A | subagent #1 | 37, 38 | `.github/workflows/`, `pyproject.toml` polish, TestPyPI |
| 3B | subagent #2 | 37, 39 | `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, MCP client demo |

---

## Wave 0 — Foundation (serial)

**Owner:** coder (this session). Do not delegate; this wave's output is the
contract every later wave depends on.

**Deliverables:**

1. `docs/architecture.md` covering:
   - Module layout (`store`, `md_io`, `cli`, `mcp_server`, `schema`)
   - Data model: full SQLite DDL (`documents`, `links`, `schema_version`,
     FTS5 virtual table + sync triggers)
   - Type registry: how `project / decision / lesson / glossary / person /
     faq` are declared, how users add custom types
   - **Interface contracts**: every public function signature in
     `kb_mcp/store.py` (Store Protocol), `kb_mcp/md_io.py`
     (Markdown I/O API), `kb_mcp/mcp_server.py` (tool input/output
     schemas)
2. `src/kb_mcp/schema.py` — pydantic models for all 6 built-in types + a
   `TypeRegistry` class
3. `src/kb_mcp/store.py` — `Store` Protocol only (no implementation), with
   docstrings spelling out failure modes, return shapes, and concurrency
   assumptions
4. `tests/test_contracts.py` — protocol conformance test stubs that fail
   with `NotImplementedError`; these become the test suite in Wave 2C

**Exit criteria:**
- `docs/architecture.md` exists and is referenced from README
- All public type signatures are typed and import-clean
- A new subagent in Wave 1 can read `architecture.md` and know exactly
  what to build without asking

**Why serial:** Wave 0's cost is ~30 minutes of focused work; the alternative
is 2× that spent on integration rewrites in Wave 2.

---

## Wave 1 — Parallel implementation (3 workers)

All three workers start simultaneously after Wave 0 lands. Each works on a
separate module. They never touch each other's files.

### Wave 1A — SQLite Store (coder, ~2h)

**Files:** `src/kb_mcp/store/sqlite.py`, `src/kb_mcp/migrations/0001_init.sql`

**Implements:** the `Store` Protocol from `store.py` against SQLite + FTS5.

**Sub-deliverables:**
- `documents` and `links` tables with FK constraints
- FTS5 virtual table `docs_fts` with triggers (INSERT / UPDATE / DELETE sync)
- `schema_version` migration runner
- All Protocol methods: `add`, `get`, `search`, `list`, `link`,
  `unlink`, `backlinks`, `import_many`, `export_all`, `prune`, `doctor`
- `kb doctor` CLI command (functional in this wave; no other CLI yet)

**Contract:** conforms to `tests/test_contracts.py` from Wave 0.

### Wave 1B — Markdown I/O (subagent #1, ~1h)

**Files:** `src/kb_mcp/md_io.py`, `src/kb_mcp/frontmatter.py`

**Implements:** the Markdown I/O API declared in `architecture.md`.

**Sub-deliverables:**
- `parse_frontmatter(text: str) -> (Frontmatter, body: str)`
- `render_document(doc: Document) -> str` (frontmatter + body)
- `import_dir(store: Store, dir: Path) -> ImportReport` — idempotent by
  `source` path
- `export_dir(store: Store, dir: Path) -> ExportReport`
- Path-traversal guard (NFR-S-3)
- `python-frontmatter` lib or hand-rolled `PyYAML` parser (decision logged
  in `architecture.md` § 6)

**Independent test fixture:** a temp directory with 3-5 sample `.md`
files; round-trip test (import → export → import → diff must be no-op).

### Wave 1C — CLI skeleton (subagent #2, ~1h)

**Files:** `src/kb_mcp/cli.py` (full rewrite of stub)

**Implements:** Click commands with **stubbed Store calls** that hit an
in-memory dict (`StubStore`). Real Store is wired in Wave 2B.

**Sub-deliverables:**
- `kb init / add / get / search / list / link / import / export / doctor`
- `--json` flag on every command
- Exit-code table from `cli-reference.md`
- Help text per command, validated against `cli-reference.md`

**Independent test fixture:** `tests/test_cli_stub.py` exercising every
command against `StubStore`.

---

## Wave 2 — MCP + integration (3 workers)

### Wave 2A — MCP server (subagent #1, ~1.5h)

**Files:** `src/kb_mcp/mcp_server.py`

**Implements:** FastMCP server exposing 4 tools. Depends on the `Store`
Protocol — works against either real Store (1A) or `StubStore` (1C) for
dev.

**Sub-deliverables:**
- `kb_search(query, type?, tags?, limit?)` → `{id, title, type, snippet, score}[]`
- `kb_get(id)` → full document or MCP error `-32004`
- `kb_add(type, title, body, tags?, source?)` → new id, or `-32005` on
  duplicate
- `kb_link(from_id, to_id, rel?)` → success (idempotent)
- stdio transport, JSON-RPC per MCP spec
- Stderr-only logging; structured JSON logs at debug level

### Wave 2B — Wire CLI to real Store (subagent #2, ~45min)

**Files:** `src/kb_mcp/cli.py` (replace stub wiring)

**Implements:** swap `StubStore` for `SqliteStore` everywhere. All other
behaviour unchanged. No new commands.

**Test:** existing `test_cli_stub.py` should pass against real Store after
parameterising the fixture.

### Wave 2C — End-to-end tests (subagent #3 / coder, ~1.5h)

**Files:** `tests/test_e2e.py`, `tests/test_mcp_e2e.py`, `tests/conftest.py`

**Implements:**
- CLI E2E: spawn `kb` as subprocess, drive every command, assert on
  stdout/stderr/exit code
- MCP E2E: spawn `kb serve` as subprocess, send JSON-RPC over stdin,
  parse responses from stdout, assert on tool outputs
- Real SQLite temp file per test (`tmp_path` fixture); no mocks
- Coverage target: ≥ 80% lines on `store/sqlite.py`, ≥ 70% overall

**Exit criteria for v0.1:**
- `pytest` green on Python 3.10, 3.11, 3.12
- `mypy src/` and `ruff check src/` clean
- `kb doctor` exits 0 on a freshly imported sample vault

---

## Wave 3 — Ship (2 workers)

### Wave 3A — CI + publish (subagent #1, ~1h)

**Files:** `.github/workflows/ci.yml`, `pyproject.toml` (polish), `MANIFEST.in`

**Implements:**
- GitHub Actions matrix: Python 3.10/3.11/3.12, run `ruff`, `mypy`, `pytest`
- Build sdist + wheel on tag push; upload to TestPyPI on `v*` tags from
  branches matching `release/*`
- README badge URLs point at the real `your-org/kb-mcp` (after the user
  creates the GitHub repo)

### Wave 3B — Community files (subagent #2, ~45min)

**Files:** `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `docs/usage-mcp-client.md`,
`README.md` (polish with demo gif or asciinema)

**Implements:**
- CONTRIBUTING.md with dev setup, test instructions, PR template
- CODE_OF_CONDUCT.md (Contributor Covenant v2.1)
- Usage docs for Claude Desktop, Cursor, OpenCode, Codex — copy-paste-ready
  JSON snippets
- README demo: either an asciinema recording or a static Markdown screenshot
  sequence

---

## Risk register for the plan itself

| Risk | Likelihood | Mitigation |
|---|---|---|
| Wave 0 contracts are vague → integration drift in Wave 2 | Medium | Wave 0 exit criterion: `tests/test_contracts.py` exists with all signatures |
| Subagent in 1B/1C ignores architecture.md | Medium | Wave 0 worker (coder) reads subagent output before Wave 2 starts and patches gaps |
| FTS5 trigger edge cases (UPDATE-of-same-content) | Low | Wave 2C E2E covers re-import round-trip |
| MCP spec version drift | Medium | Pin spec version in `pyproject.toml`; CI runs against pinned schema |
| Time overruns cascade into Wave 3 | Medium | Each wave's exit criteria are independently verifiable; can pause and ship a partial v0.1.0-rc |

---

## Coordination protocol

- **Single source of truth:** `docs/architecture.md`. If a worker changes a
  contract, they edit architecture.md **first** and announce in their
  handoff note.
- **No cross-wave file edits.** A worker in Wave 1 does not touch files in
  Wave 2A's module. If they need a change, they request it; the orchestrator
  (coder in this session) makes it.
- **Subagent handoff note:** every subagent returns a summary including
  `files_changed`, `tests_added`, `deviations_from_architecture.md`,
  `open_questions_for_user`.
- **Pause points:** between waves, coder reviews subagent output, updates
  architecture.md if needed, and runs `pytest` before launching the next wave.

---

## Status

- [x] Wave 0 — design contracts (next step)
- [ ] Wave 1 — parallel implementation
- [ ] Wave 2 — MCP + integration tests
- [ ] Wave 3 — CI + community + publish
