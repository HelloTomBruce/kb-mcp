# Code Review — Waves 2A + 3A + 3B

**Review scope:** 4 commits (`a22c14f`, `32672a7`, `0b446ff`, `42a9d3d`)
**Reviewer:** reviewer agent
**Date:** 2026-06-18

Scope recap:

| Commit | Wave | Contents |
|---|---|---|
| `a22c14f` | 2A | `src/kb_mcp/mcp_server.py` (FastMCP server, 4 tools) + `tests/test_mcp_e2e.py` (15 tests) |
| `32672a7` | — | Wave 1 review fixes (`_UPDATEABLE_FIELDS`, `init --force` docstring, doctor exit code, narrowed test, `uv.lock`) |
| `0b446ff` | 3A | `.github/workflows/ci.yml`, `.github/workflows/publish.yml`, `pyproject.toml` fixes |
| `42a9d3d` | 3B | `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `examples/` (3 files + README) |

Verification performed during review:

- `uv run pytest -q` → **215 passed** (matches Wave 3A claim).
- `uv run ruff check .` → **All checks passed**.
- `uv run ruff check --select A src/kb_mcp/mcp_server.py` → finds `A002` on `kb_get(id: str)` (no `noqa`), confirming `A` is **not** in the default rule set and the `# noqa: A002` comments on the `type` params are inert.
- `mcp` package locked at **1.28.0** (satisfies `mcp>=1.0`); `from mcp.server.fastmcp import FastMCP` imports cleanly.
- `SqliteStore.__init__` does `self._path.parent.mkdir(parents=True, exist_ok=True)` → `kb serve` on a fresh `KB_MCP_HOME` is safe (no need to `kb init` first).

---

## 1. `src/kb_mcp/mcp_server.py` (Wave 2A)

### ✅ Good
- **Pydantic input models match `architecture.md` § 4.4 exactly.** `KbSearchInput`, `KbGetInput`, `KbAddInput`, `KbLinkInput` reproduce the spec field-for-field and constraint-for-constraint (`limit` ge=1 le=100, `title` ≤512, `body` ≤1_000_000, `rel` ≤64, `type` ≤64).
- **Error code mapping matches § 4.4.** `_mcp_error()` returns `-32602 / -32004 / -32005 / -32603` for `ValidationError / NotFoundError / DuplicateError / IntegrityError / other` — identical to the spec table.
- **Deliberate omission of `from __future__ import annotations`**, with an excellent explanatory comment (FastMCP 1.x `Tool.from_function()` calls `issubclass()` on runtime annotations; PEP-563 would turn them into strings and crash). This is a subtle, correct call.
- **Privacy (NFR-O-2).** `kb_add` logs `type`, `title`, `tags`, `source` — never `body`. Structured JSON to stderr only.
- **`__main__` block** enables `python -m kb_mcp.mcp_server`, which is exactly what `test_mcp_e2e.py` spawns. Avoids Click's stdin/stdout interference.
- **`kb_search` returns `{"hits": [...], "count": N}`** instead of a bare list — documented workaround for FastMCP serialising 1-element lists as a single dict. The Python client and E2E tests both consume this shape correctly.

### ⚠️ Concern
- **Error delivery diverges from `architecture.md` § 4.4 — and the spec was never updated.** The spec table is titled "Error → MCP JSON-RPC error code mapping", implying the codes are returned as JSON-RPC `error.code`. The implementation instead raises `RuntimeError(f"MCP error {code}: {msg}")`, which FastMCP turns into a tool result with `isError: true` and the code embedded in the text. **The implementation is correct per the MCP spec** (tool-execution errors are content, not JSON-RPC errors — JSON-RPC errors are for protocol-level issues), and the E2E tests verify the actual behaviour. But § 4.4 still describes the old mechanism. **Action: update § 4.4 to document the `isError:true` + `MCP error <code>: <msg>` text convention.**
- **Internal-error tracebacks are silently dropped.** Each tool wraps `store.*` in `try/except Exception` and calls `logger.error("kb_X failed: %s", msg)` — without `exc_info=True`. So when a real bug surfaces as `-32603`, the traceback is gone. Use `logger.exception(...)` (or `logger.error(..., exc_info=True)`) on the error paths so `-32603` failures are debuggable.
- **`store` is never closed.** `_make_server()` constructs one `SqliteStore` held in a closure; there is no `atexit`/shutdown hook calling `store.close()`. WAL recovers cleanly on next open, so this is not data-corrupting, but an explicit close on shutdown is cleaner.
- **Validation path re-wraps pydantic's `ValidationError` as `kb_mcp.ValidationError(str(e))`.** This works (pydantic v2's `ValidationError` is a different class, caught by the bare `except Exception`), but discards structured error detail. Acceptable for v0.1.
- **`# noqa: A002` on the `type` params is inert**, because `flake8-builtins` (`A`) is not in ruff's default selection (confirmed: `ruff check --select A` finds `A002` on `kb_get(id)` which has *no* `noqa`). If `A` is ever enabled, `kb_get`'s `id` param will fail with no suppression. Either enable `A` consistently and add `# noqa: A002` to `id`, or remove the inert `noqa` comments on `type`.
- **Mixed annotation styles.** Tool signatures use `Optional[str]` / `List[str]` while the pydantic models use `str | None` / `list[str]`. Cosmetic, but worth normalising.

### ❌ Blocker
- None in this file.

---

## 2. `cli.py` — `kb serve` integration (Wave 2A)

### ⚠️ Concern (borderline blocker)
- **`kb serve --log-level` is a no-op.** `serve(ctx, log_level)` validates the `--log-level` choice but then calls `_run_mcp_server()` **without passing `log_level`**. `mcp_server.run()` reads `KB_MCP_LOG_LEVEL` from the environment (default `WARNING`). So `kb serve --log-level DEBUG` still logs at `WARNING`. The option is advertised, validated, and silently ignored. **Fix:** `os.environ["KB_MCP_LOG_LEVEL"] = log_level` before calling `_run_mcp_server()` (or thread the arg through `run()` → `_setup_logging(level)`).

### ❌ Blocker
- None (but see publish.yml below for the actual release blocker).

---

## 3. `tests/test_mcp_e2e.py` (Wave 2A)

### ✅ Good
- **Real subprocess, no mocks** — matches `architecture.md` § 8 ("No mocks" principle). Spawns `python -m kb_mcp.mcp_server` with an isolated `KB_MCP_HOME`.
- **Correct MCP handshake:** `initialize` → assert result → `notifications/initialized` → tool calls.
- **All 4 tools covered**, happy path + at least one error path each.
- **Error-code mapping verified** (`TestErrorCodes`: `-32602`, `-32004`, `-32005`).
- **`_extract_result` robustly handles FastMCP content-block wrapping** — single block (parse JSON), multi-block (collect), empty (return `[]`). Matches the server's actual return shapes.
- **Fixture cleanup** in `finally`: closes stdin, `wait(timeout=5)`, `kill()` on timeout.

### ⚠️ Concern
- **`_recv`'s `timeout` parameter is dead code.** `proc.stdout.readline()` blocks indefinitely; the `timeout` arg is accepted but never used. Consequently `_recv_until_id`'s deadline arithmetic is ineffective — a hung server hangs the whole test suite (and there is no `pytest-timeout` in dev deps). **Fix:** select/poll on the stdout fd against the deadline, or add `pytest-timeout` with a per-test cap.
- **Coverage gaps.** No test exercises:
  - `kb_search` with `type` or `tags` filters (only plain query).
  - `kb_link` with a custom `rel` (only default `relates-to`).
  - `kb_link` idempotency (linking the same pair twice).
  - `kb_add` `source`-based idempotent re-add.
  - `limit` boundaries (`0`, `101`, `100`).
  - `tools/list` input schemas (only asserts tool *names*).
- **Global `_id_counter`** reset in the `mcp_proc` fixture. Fine for sequential runs; would race under `pytest-xdist` (not currently configured, but a footgun).
- **`import re` inside `_extract_error`** — should be module-level (trivial).
- **`test_search_no_results` asserts `data["hits"] == []`** — depends on FastMCP's empty-list serialisation. Currently green, but fragile if the SDK changes.

### ❌ Blocker
- None.

---

## 4. `.github/workflows/ci.yml` (Wave 3A)

### ✅ Good
- **Matrix Python 3.10 / 3.11 / 3.12 with `fail-fast: false`** — matches `requires-python = ">=3.10"`.
- **uv-based:** `astral-sh/setup-uv` with `enable-cache: true` and `cache-dependency-glob: "uv.lock"` (correct cache key).
- **`uv sync --extra dev --python <ver>`** installs the project (editable) + runtime deps + dev extras in one step.
- **Lint then test** — `uv run ruff check .` followed by `uv run pytest -q`.

### ⚠️ Concern
- **No coverage enforcement**, despite `architecture.md` § 8: *"Coverage targets (enforced in CI via `pytest-cov`)"* and `pytest-cov` being a dev dep. CI runs `pytest -q` with no `--cov` and no threshold. Either add `--cov=kb_mcp --cov-fail-under=70` (matching the § 8 target) or retract the claim in `architecture.md`.
- **No `mypy` step**, despite `CONTRIBUTING.md` "Expected state" listing `uv run mypy src/` and `mypy` being a dev dep. Drift between the contributor checklist and the CI gate.
- **No `ruff format --check` step**, despite `CONTRIBUTING.md` listing it as required.
- **`astral-sh/setup-uv@v6`** — could not externally verify this major version is published (web search quota exhausted). If it does not exist, every CI run fails at setup before any test runs. Verify before relying on it; pin to a known-good version otherwise.
- **`ubuntu-latest` only** — no macOS runner. `KB_MCP_HOME` defaults to XDG on both platforms so functionally OK, but there is no macOS CI signal (and the docs discuss macOS paths).

### ❌ Blocker
- None.

---

## 5. `.github/workflows/publish.yml` (Wave 3A)

### ❌ Blocker
Two independent issues, either of which will prevent the first `v0.1.0` tag from publishing:

1. **`environment: ${{ steps.target.outputs.repository }}` references a step output from the *same* job.** GitHub Actions evaluates the job-level `environment` key at job-dispatch time — *before* the job's own steps run. `steps.target` runs inside `publish`, so its output is **empty** when `environment` is resolved. The job therefore targets an empty/nonexistent environment. For OIDC trusted publishing this is fatal: PyPI/TestPyPI match the OIDC `job_environment` claim to the trusted publisher's configured environment; an empty/mismatched environment means the publish step's OIDC token will not authenticate. **Fix:** move target-determination into a separate `determine-target` job and reference `needs.determine-target.outputs.repository` in `environment:` (needs outputs *are* available at job-start), or split into two jobs gated by tag pattern (`if:` on each).

2. **The publish job grants only `id-token: write`.** A job-level `permissions:` block *replaces* the top-level set, so every other permission becomes `none`. `actions/download-artifact@v4` requires `actions: read` to download artifacts from the run. With only `id-token: write`, the download step will fail with a permissions error. **Fix:** add `actions: read` (and `contents: read` for safety) to the publish job's `permissions:`.

### ⚠️ Concern
- **Tag regex** `^v[0-9]+\.[0-9]+\.[0-9]+[ab]|^v[0-9]+\.[0-9]+\.[0-9]+rc` correctly routes `v0.1.0a1` / `v0.1.0b1` / `v0.1.0rc1` → TestPyPI and `v0.1.0` → PyPI. But PEP 440 `.dev` / `.post` / `-alpha` suffixes fall through to PyPI. Fine for the stated `a`/`b`/`rc` convention — document it so future maintainers don't ship a `.dev` build to PyPI.
- **`name: Publish (${{ steps.target.outputs.repository }})`** has the same step-output-timing caveat as `environment:` — likely renders as `Publish ()` until (if) GitHub re-evaluates. Cosmetic.
- The build job's `permissions:` is inherited from the top-level `contents: read` — fine for `uv build` + `upload-artifact`.

### ✅ Good
- **OIDC trusted publishing** (no long-lived PyPI tokens) — the correct modern approach; `id-token: write` is the right permission for it.
- **`pypa/gh-action-pypi-publish@release/v1`** — standard, maintained action.
- **Build → upload → download → publish** separation; `if-no-files-found: error` on upload.
- **`skip-existing: true`** on both targets — makes the workflow re-runnable.

---

## 6. `pyproject.toml` (Wave 3A)

### ✅ Good
- **All imports are now declared.** `click`, `pydantic`, `mcp`, `python-frontmatter` — the Wave 3A commit correctly added `python-frontmatter>=1.0` (previously imported but undeclared, per the commit message).
- **`requires-python = ">=3.10"`** matches the CI matrix and `target-version = "py310"`.
- **`[tool.ruff]`** line-length 100, target py310 — consistent with `CONTRIBUTING.md`.
- **`[tool.pytest.ini_options]`** `testpaths = ["tests"]`, `addopts = "-q"`.
- **`[project.scripts]`** `kb = "kb_mcp.cli:main"` — correct console-script entry point.
- **`project.urls`** point at `zhangbei/kb-mcp` consistently.

### ⚠️ Concern
- **`[tool.mypy]` section is missing**, yet `CONTRIBUTING.md` § Code style claims mypy is configured in `pyproject.toml [tool.mypy]` and lists `uv run mypy src/` as a required check. Doc/impl mismatch — add a minimal `[tool.mypy]` (at least `python_version = "3.10"`, `strict_optional = true`) or remove the contributor reference.
- **No `[tool.coverage]` / `--cov-fail-under`**, despite `pytest-cov` being a dev dep and `architecture.md` § 8 mentioning coverage targets.
- **`mcp>=1.0`** — locked at 1.28.0 (satisfies). The `mcp_server.py` comment referencing "FastMCP 1.12" is slightly stale vs. the locked 1.28.0, but harmless. Consider an upper bound before v1.0 since `mcp` is still evolving.
- **`# noqa: A002`** comments depend on `A` rules being enabled, which they aren't (see mcp_server.py concern).

### ❌ Blocker
- None.

---

## 7. `CONTRIBUTING.md` (Wave 3B)

### ✅ Good
- **Comprehensive:** dev setup, tests, style, commits, PR process, release, help.
- **Conventional Commits** type/scope tables match the actual wave tags used in git history (`feat(wave-2A)`).
- **Correctly notes** `mcp_server.py` deliberately omits `from __future__ import annotations` — saves contributors from "fixing" a non-bug.
- **Privacy callout** (NFR-O-2) and "no `print()` in library code" convention.

### ⚠️ Concern
- **Factual error (line 112):** *"E2E tests (`tests/test_mcp_e2e.py`) spin up the FastMCP server **in-process**"* — they actually spawn a **real subprocess** (`subprocess.Popen`). The test file's own docstring says so. Fix the wording.
- **Line 74 placeholder:** `git clone https://github.com/your-org/kb-mcp` uses `your-org` while `pyproject.toml` URLs use `zhangbei/kb-mcp`. Inconsistent.
- **"Releasing" §** says *"Publish to PyPI: `uv publish`"*, but the actual `publish.yml` uses GitHub Actions OIDC trusted publishing on tags. The manual `uv publish` instruction contradicts the automated workflow, and there is no mention of the TestPyPI prerelease flow.
- **"Expected state" drift:** lists `uv run mypy src/` and `uv run ruff format --check .` as required, but CI runs neither. Either add them to `ci.yml` or soften the checklist to what CI actually enforces.

### ❌ Blocker
- None.

---

## 8. `CODE_OF_CONDUCT.md` (Wave 3B)

### ✅ Good
- **Contributor Covenant 2.1**, unmodified — standard, complete, with the 4-step enforcement ladder and attribution links.

### ⚠️ Concern
- **Enforcement email `opensource@kb-mcp.dev`** — verify the maintainer controls `kb-mcp.dev` and monitors that address. A CoC report address that bounces undermines the enforcement pathway.

### ❌ Blocker
- None.

---

## 9. `examples/` (Wave 3B)

### `claude-desktop-config.json` / `cursor-config.json`

### ✅ Good
- **Valid JSON.** Claude config includes the MCP `$schema` URL (`2024-11-05/server-config.schema.json`).
- **`command: "kb"`, `args: ["serve"]`** matches the real CLI.
- **No credentials** — stdio transport, no auth tokens. Safe to commit.

### ⚠️ Concern
- **Cursor config omits `$schema`** — not required, but adding it (as the Claude config does) would help editors validate the file.

### `python-mcp-client.py`

### ✅ Good
- **Uses the official `mcp` SDK** (`ClientSession`, `StdioServerParameters`, `stdio_client`) — exercises the real server API, not a hand-rolled JSON-RPC client.
- **Correctly parses FastMCP content-block results** — `_extract_id` and `_print_search_results` handle the server's `{"hits": [...], "count": N}` return shape.
- **`kb_add(type="glossary", title="MCP")` → `glossary/mcp`**, then `kb_search("model context protocol")` matches the body. Consistent with `make_id` prefixes and the search return shape.
- **Honours `KB_BIN` and `KB_MCP_HOME`** env vars; inherits env so `PATH` propagates.
- **Graceful on re-run:** a duplicate `kb_add` yields `<unknown>` (no crash), and `kb_search` still finds the existing doc.
- **No injection / path-traversal risk; no credentials.**

### ⚠️ Concern
- **No error handling for tool failures** (duplicate, not-found). Acceptable for an example, but a one-line comment noting that tool errors arrive as `isError:true` content (not exceptions) would educate users porting the snippet.
- **`env=os.environ.copy()`** passes the full parent environment to the subprocess. Fine for a local demo; worth a comment that no secret filtering is performed (none expected here).

### `examples/README.md`

### ✅ Good
- Clear per-client instructions; correct macOS Claude Desktop path (`~/Library/Application Support/Claude/claude_desktop_config.json`); helpful troubleshooting section.

### ⚠️ Concern
- "pip install kb-mcp # from PyPI (when published)" — could also note the TestPyPI prerelease path for early adopters once `publish.yml` is fixed.

### ❌ Blocker
- None (examples overall).

---

## 10. Security (cross-cutting)

### ✅ Good
- **No SQL injection.** MCP tools delegate to `SqliteStore`, which uses parameterised queries for both DML and FTS5 `MATCH`.
- **No path traversal via MCP.** `kb_add.source` is stored metadata, never used for filesystem writes through the MCP surface. `md_io`'s path-traversal guards (Wave 1) are not exposed over MCP (no import/export tools).
- **No credentials committed.** Example configs use stdio with no auth; `publish.yml` uses OIDC trusted publishing (no PyPI token in secrets).
- **Privacy.** Document body is never logged (NFR-O-2) — verified in `mcp_server.py`.

### ⚠️ Concern
- `examples/python-mcp-client.py` inherits the full parent env to the subprocess (no secret filtering) — acceptable for a local demo; noted above.

### ❌ Blocker
- None.

---

## Summary

| File | ✅ Good | ⚠️ Concern | ❌ Blocker |
|------|---------|-----------|-----------||
| `mcp_server.py` | § 4.4 schema fidelity, error-code map, `__future__` omission, privacy, `__main__` | Error-delivery spec drift; tracebacks dropped; `store` never closed; inert `noqa: A002`; mixed annotation styles | — |
| `cli.py` (`serve`) | Real server wired via `kb serve` | **`--log-level` is a no-op** | — |
| `test_mcp_e2e.py` | Real subprocess, handshake, all 4 tools, error codes, robust result extraction | `_recv` timeout dead code → hung-server risk; coverage gaps; global `_id_counter` | — |
| `ci.yml` | Matrix, uv cache, lint+test | No coverage/mypy/format-check; `setup-uv@v6` unverified; ubuntu-only | — |
| `publish.yml` | OIDC trusted publishing, standard action, `skip-existing` | Tag-regex edge cases; cosmetic job-name timing | **Yes: `environment:` from same-job step output (empty at dispatch → OIDC mismatch); publish job lacks `actions: read` → `download-artifact` fails** |
| `pyproject.toml` | All imports declared, ruff/pytest config, entry point | `[tool.mypy]` missing; no coverage config; `noqa` depends on disabled rule | — |
| `CONTRIBUTING.md` | Comprehensive, Conventional Commits, correct `__future__` note | "in-process" error; `your-org` placeholder; release § contradicts publish.yml; CI/ Expected-state drift | — |
| `CODE_OF_CONDUCT.md` | Contributor Covenant 2.1, complete | Verify `opensource@kb-mcp.dev` is monitored | — |
| `examples/*.json` | Valid JSON, correct command, no creds | Cursor config missing `$schema` | — |
| `examples/python-mcp-client.py` | Official SDK, correct result parsing, env-var support, re-run-safe | No error-handling comment; full env inheritance | — |
| `examples/README.md` | Clear instructions, troubleshooting | Could mention TestPyPI prerelease path | — |
| Security | Parameterised queries, no MCP path traversal, no creds, body never logged | Full-env inheritance in Python example | — |

---

## Recommended Actions (ordered by priority)

1. **❌ BLOCKER — fix `publish.yml` before tagging `v0.1.0`:**
   - (a) Move target-determination into a separate `determine-target` job; reference `needs.determine-target.outputs.repository` in `environment:` (needs outputs are available at job-start; same-job step outputs are not). Alternatively split into two `if:`-gated publish jobs.
   - (b) Add `actions: read` (and `contents: read`) to the publish job's `permissions:` so `download-artifact@v4` can fetch the dist artifacts.
   Without both fixes, the first release tag will fail to publish.

2. **⚠️ Fix `kb serve --log-level` no-op:** set `os.environ["KB_MCP_LOG_LEVEL"] = log_level` before `_run_mcp_server()` (or thread the arg through `run()` → `_setup_logging(level)`). The flag is currently validated and silently ignored.

3. **⚠️ Log internal-error tracebacks:** change the `logger.error("kb_X failed: %s", msg)` calls to `logger.exception(...)` (or add `exc_info=True`) so `-32603` internal errors are debuggable.

4. **⚠️ Update `architecture.md` § 4.4** to document the actual error-delivery mechanism: tool errors return `{"result": {"isError": true, "content": [{"text": "MCP error <code>: <msg>"}]}}`, not JSON-RPC `{"error": {"code": ...}}`. The implementation is correct; the spec is stale.

5. **⚠️ Close the CI/docs gap:** either (a) add `--cov=kb_mcp --cov-fail-under=70`, a `mypy` step, and `ruff format --check` to `ci.yml` to match `CONTRIBUTING.md` "Expected state" and `architecture.md` § 8, or (b) soften the docs to what CI actually enforces. At minimum add `pytest-timeout` so a hung MCP server can't hang CI.

6. **⚠️ Harden E2E tests:** make `_recv` honour its `timeout` (select/poll on the stdout fd, or add `pytest-timeout`); add the missing cases — `type`/`tags` filter, custom `rel`, `limit` bounds (0/101/100), `kb_link` idempotency, `source`-based re-add, and `tools/list` input-schema assertion.

7. **⚠️ ruff `A`-rule consistency:** either enable `flake8-builtins` (`A`) in `[tool.ruff.lint]` and add `# noqa: A002` to `kb_get`'s `id` param, or remove the inert `# noqa: A002` comments on the `type` params.

8. **⚠️ Add `[tool.mypy]` to `pyproject.toml`** (or remove the `CONTRIBUTING.md` reference), and add a minimal `[tool.coverage]` if enforcing coverage.

9. **⚠️ `CONTRIBUTING.md` fixes:** line 112 "in-process" → "real subprocess"; line 74 `your-org` → `zhangbei`; reconcile "Releasing" § with the automated OIDC `publish.yml` (and mention the TestPyPI prerelease path).

10. **⚠️ Close `SqliteStore` on shutdown:** add an `atexit` (or try/finally around `mcp.run()`) calling `store.close()` in `_make_server`/`run`.

11. **Low priority / verify:** confirm `astral-sh/setup-uv@v6` is a published action version (else pin to a known-good major); confirm `opensource@kb-mcp.dev` is a monitored mailbox; add `$schema` to `cursor-config.json`.

---

### Verdict

**Waves 2A + 3B are release-ready.** The MCP server correctly implements the § 4.4 contract, the E2E suite is solid, and the examples/docs are high quality. **Wave 3A's `publish.yml` is not release-ready** — it contains two independent bugs that will prevent the first `v0.1.0` tag from publishing (dynamic `environment:` from a same-job step output, and missing `actions: read` permission). `ci.yml` is functionally fine but drifts from the documented testing strategy. Recommend addressing items 1–4 before tagging; items 5–10 can land in a fast follow-up.
