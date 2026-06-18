# Contributing to kb-mcp

Thanks for your interest in `kb-mcp`! This document covers everything you need
to start hacking on the project — dev setup, running tests, code style, and the
pull-request / commit workflow.

> **TL;DR** — `uv sync` → `uv run pytest` → `uv run ruff check .` → open a PR
> with a conventional-commit message. Done.

---

## Table of contents

1. [Project layout](#project-layout)
2. [Development setup](#development-setup)
3. [Running tests](#running-tests)
4. [Code style](#code-style)
5. [Commit messages](#commit-messages)
6. [Pull-request process](#pull-request-process)
7. [Releasing](#releasing)
8. [Getting help](#getting-help)

---

## Project layout

```
kb-mcp/
├── src/kb_mcp/           # All importable Python code
│   ├── schema.py         # Document, Link, SearchHit, exceptions, make_id()
│   ├── store/            # Storage backends
│   │   └── sqlite.py     # SqliteStore — SQLite + FTS5 (default backend)
│   ├── migrations.py     # Idempotent DDL migration runner
│   ├── md_io.py          # Markdown + frontmatter import/export
│   ├── mcp_server.py     # FastMCP server: kb_search, kb_get, kb_add, kb_link
│   └── cli.py            # Click CLI (`kb` entry point)
├── tests/                # pytest suite (unit + E2E, real SQLite temp files)
├── docs/                 # Architecture, requirements, CLI reference, plan
├── examples/             # MCP client configs + sample client scripts
├── pyproject.toml        # Build config, deps, ruff/mypy settings
└── README.md
```

### Document types

`kb-mcp` ships six built-in document types: `project`, `decision`, `lesson`,
`glossary`, `person`, `faq`. Subclass `kb_mcp.schema.Document` to add your own.

### MCP tools

The MCP server (started by `kb serve`) exposes four tools over stdio:

| Tool | Purpose |
|---|---|
| `kb_search(query, type?, tags?, limit?)` | BM25 full-text search with snippets |
| `kb_get(id)` | Fetch a full document by id/slug |
| `kb_add(type, title, body, tags?, source?)` | Create a new document |
| `kb_link(from_id, to_id, rel?)` | Create a typed edge between documents |

---

## Development setup

`kb-mcp` uses [`uv`](https://docs.astral.sh/uv/) for dependency management.
If you don't have it yet:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then:

```bash
git clone https://github.com/zhangbei/kb-mcp
cd kb-mcp
uv sync --extra dev      # create .venv + install all dev deps
```

This installs the runtime deps (`click`, `pydantic`, `mcp`) plus the dev
extras (`pytest`, `pytest-cov`, `ruff`, `mypy`) and the `kb` console script in
editable mode.

> Prefer `uv run <cmd>` over activating the venv manually — it always uses the
> project's locked environment.

### Running the CLI locally

```bash
uv run kb init                    # create ~/.local/share/kb-mcp/kb.db
uv run kb add --type project --title "My Project" --body "Hello"
uv run kb search "hello"
uv run kb serve                   # start the MCP server on stdio
```

Set `KB_MCP_HOME=/tmp/kb-test` to point at a throwaway database (handy during
development).

---

## Running tests

```bash
uv run pytest                     # full suite
uv run pytest -q                  # quiet
uv run pytest tests/test_store_sqlite.py   # one file
uv run pytest -k search           # by keyword
uv run pytest --cov=kb_mcp        # with coverage
```

The test suite uses **real SQLite temp files** — no mocks of the database
layer. E2E tests (`tests/test_mcp_e2e.py`) spawn the FastMCP server as a
real subprocess and exercise all four tools. Tests never touch your real
`~/.local/share/kb-mcp/kb.db`; each test creates an isolated temp DB.

### Expected state

Before opening a PR, all of these should pass:

```bash
uv run pytest                     # 0 failures
uv run ruff check .               # no lint errors
uv run ruff format --check .      # no formatting diffs
```

Mypy is configured but not yet enforced in CI (pre-existing type errors
from the `list` method shadowing the builtin). Run it locally and aim
for zero new errors:

```bash
uv run mypy src/                  # informational — not yet gating
```

---

## Code style

| Tool | Config | Notes |
|---|---|---|
| **ruff** (linter + formatter) | `pyproject.toml` `[tool.ruff]` | **Line length: 100** |
| **mypy** (type checker) | `pyproject.toml` `[tool.mypy]` | Run on `src/` |

Auto-format before committing:

```bash
uv run ruff format .
uv run ruff check --fix .
```

### Conventions

- **Type hints everywhere.** All public functions and methods are typed.
  `from __future__ import annotations` is used in modules that don't rely on
  runtime annotation introspection (note: `mcp_server.py` deliberately omits it
  — see the module docstring for why).
- **Docstrings** on public modules, classes, and functions. Triple-quote,
  imperative mood ("Return the document…", not "Returns the document…").
- **Exceptions** — raise the typed exceptions from `kb_mcp.schema`
  (`ValidationError`, `NotFoundError`, `DuplicateError`, `IntegrityError`).
  The CLI and MCP server map these to the right exit codes / JSON-RPC error
  codes; don't raise bare `Exception`.
- **No `print()`** in library code — use `logging` (structured JSON to stderr
  in the MCP server) or `click.echo` in the CLI.
- **Privacy** — document body content is **never** logged (NFR-O-2).

---

## Commit messages

We follow [**Conventional Commits**](https://www.conventionalcommits.org/):

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types

| Type | When |
|---|---|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `test` | Adding or correcting tests |
| `chore` | Build, deps, tooling, repo maintenance |
| `perf` | Performance improvement |
| `ci` | CI configuration changes |

### Scopes

Common scopes: `store`, `mcp`, `cli`, `schema`, `md_io`, `migrations`, `docs`,
`examples`. Use the wave tag when landing a planned wave, e.g.
`feat(wave-2A): …`.

### Rules

- Subject line ≤ 72 chars, imperative mood ("add", not "added").
- No period at the end of the subject.
- Reference issues in the footer: `Closes #42`, `Refs #17`.
- **Squash-merge** is the default — one commit per PR.

### Examples

```
feat(mcp): add kb_link tool for typed document edges
fix(store): handle empty tag list in FTS5 search filter
docs(cli): document --body-file precedence in cli-reference
test(store): add edge cases for make_id slug generation
chore: bump ruff to 0.6 and apply new lint rules
```

---

## Pull-request process

1. **Open an issue first** for anything beyond a trivial fix — this avoids
   wasted work if the change is out of scope. Link the issue in your PR.
2. **Fork & branch** from `main`:
   ```bash
   git checkout -b feat/my-feature
   ```
3. **Write tests.** New behaviour needs new tests. Bug fixes need a regression
   test. PRs that drop coverage will be asked to add tests.
4. **Run the full check suite locally** (see [Running tests](#running-tests)).
5. **Keep the diff focused.** One logical change per PR. Split unrelated
   refactors into their own PRs.
6. **Update docs** if you change CLI flags, MCP tool signatures, the schema,
   or the storage format. Affected files usually live in `docs/` and
   `README.md`.
7. **Open the PR** with a description covering:
   - What & why (link the issue)
   - How to test it
   - Breaking changes (if any)
   - Checklist: tests added, docs updated, `ruff`/`mypy`/`pytest` green
8. **Address review feedback** with new commits (the maintainer will squash on
   merge). Don't force-push mid-review unless asked.

### Review criteria

Maintainers look for:

- ✅ Tests pass and coverage doesn't drop
- ✅ `ruff` + `mypy` clean
- ✅ Public API changes are documented
- ✅ No secrets, no telemetry, no network calls in the library
- ✅ Consistent with the architecture in `docs/architecture.md`

---

## Releasing

Releases are automated via GitHub Actions. The process:

1. Update `version` in `pyproject.toml`.
2. Update the `## Changelog` section in `README.md` (if present).
3. Tag: `git tag v0.X.Y && git push --tags`.
4. The `publish.yml` workflow builds the distribution and publishes
   automatically. Prerelease tags (`v0.1.0a1`, `v0.1.0b1`, `v0.1.0rc1`)
   go to **TestPyPI**; stable tags (`v0.1.0`) go to **PyPI**.

> **Note:** Before the first release, create `pypi` and `testpypi`
> environments in the GitHub repo settings and configure OIDC trusted
> publishing on PyPI/TestPyPI to match those environment names.

---

## Getting help

- Open an issue for bugs or feature requests.
- Check `docs/architecture.md` and `docs/requirements.md` for design context.
- See `docs/plan.md` for the wave-by-wave implementation roadmap.

By participating, you agree to abide by the [Code of Conduct](./CODE_OF_CONDUCT.md).
