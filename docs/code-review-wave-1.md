# Code Review — Waves 0, 1A, 1C+2B

**Review scope:** 3 commits (efc2f69, da70d9d, 2192eb5)  
**Reviewer:** reviewer agent  
**Date:** 2026-06-18  

---

## 1. `schema.py` (Wave 0)

### ✅ Good
- **Pydantic v2 idiomatic usage.** `ConfigDict(frozen=False, str_strip_whitespace=True)` on `Document`, `frozen=True` on `Link` — correct application of model config.
- **Discriminated union subclasses.** `Project`, `Decision`, etc. use `type: Literal["project"] = "project"  # type: ignore[override]` — this is the [officially documented pattern](https://docs.pydantic.dev/latest/concepts/postponed_annotations/#subclassing-a-pydantic-model-with-a-literal-field) for narrowing the `type` literal. Correct.
- **ID validation regex.** `^[a-z0-9][a-z0-9/_-]*$` properly constrains slugs. Empty string allowed at model layer (store fills it in) — sensible split of responsibility.
- **Exceptions hierarchy.** `KbMcpError` base class with specific subclasses (`NotFoundError`, `DuplicateError`, `ValidationError`, `IntegrityError`) — clean, catches broadly without swallowing unrelated errors.
- **`_parse_dt` before-validator.** Handles `datetime`, ISO-8601 strings, `Z` suffix normalization — robust.

### ⚠️ Concern
- **`slugify` regex.** `re.sub(r"[^\w]+", "-", s, flags=re.UNICODE)` — `\w` includes underscores, so underscores survive the substitution and become part of the slug. This means a title like `"test_slug"` produces `"test_slug"` (underscore preserved), but `"test  slug"` produces `"test-slug"`. This is internally consistent but slightly surprising: underscores are treated as word characters (preserved) while spaces are not. Not a bug per se, but worth documenting the distinction.
- **`make_id` catches `ValueError` from `DocumentType(doc_type)` but also `KeyError`** — the `try/except` handles both, but `DocumentType` is an `Enum` so `KeyError` is impossible. Minor dead-code path.

### ❌ Blocker
- None.

---

## 2. `store.py` (Store Protocol — Wave 0)

### ✅ Good
- **`@runtime_checkable` Protocol.** Clean separation of interface from implementation. Allows `StubStore` without subclassing.
- **Module docstring.** Excellent documentation of concurrency guarantees, soft-delete semantics, and failure modes. Sets clear expectations for implementers.
- **Method signatures match architecture spec § 4.1.** Every method has correct return type, raises documented exceptions.
- **`list()` and `search()` have sensible limits.** `limit` capped at 1000 for list, 100 for search — prevents runaway queries.

### ⚠️ Concern
- **`list()` docstring says "callers needing more should switch to `search`"** — this is a design suggestion, not enforced. No programmatic enforcement of the "switch to search" advice. Fine for v0.1.
- **`unlink()` returns `int` (count removed)** — the Protocol doesn't document what this count means semantically (rows affected vs. links actually deleted). Minor: the implementation returns `rowcount` which is correct.

### ❌ Blocker
- None.

---

## 3. `store/sqlite.py` (Wave 1A)

### ✅ Good
- **WAL mode + FK enforcement.** Both PRAGMAs set on every connection. FK is per-connection, so setting it in `__init__` is correct for single-store-instance usage.
- **Soft-delete semantics.** All read queries filter `WHERE deleted_at IS NULL`. `delete()` is idempotent on already-deleted docs (returns no-op instead of raising).
- **`import_many` idempotency.** Source-based upsert: if `doc.source` matches an existing doc, it updates in place. This makes `kb import` safe for re-runs.
- **`doctor()` checks 4 health indicators.** integrity_check, FTS sync, orphan links, valid type/title — comprehensive for v0.1.
- **`_txn()` context manager.** Proper BEGIN/COMMIT/ROLLBACK with exception safety.
- **FTS5 tokenizer.** `unicode61 remove_diacritics 2` — good default for multi-language support.

### ⚠️ Concern
- **`update()` allows `_UPDATEABLE_FIELDS` but `type` is in the set.** The Protocol docstring says "`id`, `type`, `created_at` cannot be changed via this method." However, `_UPDATEABLE_FIELDS = frozenset({"title", "body", "tags", "source", "type"})` includes `type`. The CLI never passes `type` to `update()`, but the Protocol contract is violated here. **This should be removed from `_UPDATEABLE_FIELDS`.**
- **`_txn()` uses `isolation_level=None` (autocommit) but then manually does `BEGIN`/`COMMIT`.** The `SqliteStore.__init__` sets `isolation_level=None` which means autocommit mode. The `_txn()` context manager then executes `BEGIN` explicitly. This works but is unusual — normally you'd either use autocommit (no explicit txns) or use a transaction mode (`isolation_level=""` or `DEFERRED`). The manual `BEGIN`/`COMMIT` works because `executescript` is not used inside `_txn()`, but it's confusing and fragile. Consider switching to `isolation_level="DEFERRED"` and letting sqlite3 manage transactions.
- **`search()` FTS query doesn't filter by tags in SQL.** Tags filtering is done in Python after fetching FTS results. This means FTS returns extra hits that get filtered client-side, wasting I/O. For small DBs (< 10k docs) this is fine, but for larger corpora it's inefficient. Document as a known limitation.
- **`link()` uses `INSERT OR IGNORE` then re-fetches.** The `OR IGNORE` suppresses the duplicate-key error, then the re-fetch returns the existing link. This is correct but subtly hides the idempotency in SQL rather than expressing it clearly. Add a comment explaining the pattern.

### ❌ Blocker
- **`_UPDATEABLE_FIELDS` includes `type`.** Per the Protocol docstring in `store.py` line 94: "`id`, `type`, `created_at` cannot be changed via this method." But `_UPDATEABLE_FIELDS` on line 41 of `sqlite.py` includes `"type"`. This is a direct Protocol violation. **Fix: remove `"type"` from `_UPDATEABLE_FIELDS`.**

---

## 4. `migrations.py` (Wave 1A)

### ✅ Good
- **Forward-only, versioned migrations.** `schema_version` table tracks applied versions. Refuses to downgrade.
- **`executescript()` owns the transaction.** The commit message notes the fix: "was opening BEGIN then calling executescript() which commits implicitly." The current code lets `executescript()` manage its own transaction — correct.
- **`_migration_files()` skips non-.sql files.** Robust against stray files in the migrations directory.

### ⚠️ Concern
- **Partial migration failure leaves DB in indeterminate state.** The code itself acknowledges this in the docstring (§ 77-80). For v0.1 this is acceptable (development-time failure mode), but should be escalated to a TODO: wrap each migration in a savepoint or verify the migration is idempotent.
- **`_MIGRATIONS_DIR` resolved from `__file__`.** Works for editable installs and wheels. Good.

### ❌ Blocker
- None.

---

## 5. `md_io.py` (Wave 1B)

### ✅ Good
- **Path-traversal guard (NFR-S-3).** `_ensure_within()` resolves paths and verifies containment. Used in both `import_dir` and `export_dir`. Symlink resolution via `.resolve()` prevents `../` attacks.
- **Round-trip consistency.** `render_document()` produces stable YAML (keys sorted by `frontmatter.dumps`), and `parse_frontmatter()` reverses it. Unknown frontmatter keys are preserved.
- **`_coerce_tags` handles edge cases.** List, single string, or anything else → empty list. Graceful degradation.
- **Hidden file/directory skipping.** `dirs[:] = sorted(d for d in dirs if not d.startswith("."))` — in-place modification prevents `os.walk` from descending into hidden dirs.

### ⚠️ Concern
- **`export_dir` updates `doc.source` in the store after writing.** If the store `update()` fails (e.g., validation error), the on-disk file is already written but the source isn't updated. The code handles this with a `warnings.warn()` — good, but the warning goes to stderr and is easy to miss. Consider logging it through the structured logger (NFR-O-1).
- **`import_dir` processes files in filesystem order.** `os.walk` order is platform-dependent. While `sorted()` is applied to `dirs` and `files`, the overall import order isn't deterministic across platforms. For idempotent re-imports this doesn't matter (source-based dedup), but for `imported` counts it could vary.
- **`frontmatter` library dependency.** `python-frontmatter` is a thin wrapper around `PyYAML`. If `PyYAML` isn't installed (e.g., minimal environments), `parse_frontmatter` fails at import time. Document this as a hard dependency.

### ❌ Blocker
- None.

---

## 6. `cli.py` (Wave 1C + 2B)

### ✅ Good
- **Click 8 idioms.** `@click.pass_context`, `@_handle_errors` decorator, `--json` flag via shared `_json_option` — clean and DRY.
- **Exit codes match `cli-reference.md`.** `EXIT_OK=0, EXIT_VALIDATION=2, EXIT_NOT_FOUND=3, EXIT_CONFLICT=4, EXIT_INTERNAL=5, EXIT_USAGE=64` — all documented and consistently applied.
- **`click.exceptions.UsageError.exit_code = EXIT_USAGE`** at module level — clever global monkey-patch so all usage errors get exit code 64 instead of Click's default 2.
- **Body resolution precedence.** `--body` > `--body-file` > stdin — matches the CLI spec.
- **`_create_default_store()` uses `KB_MCP_HOME` env var.** Falls back to `~/.local/share/kb-mcp/kb.db` — matches architecture spec § 5.
- **Import/export stubs.** Raise `NotImplementedError` with clear "Wave 1B" message — the CLI surface is complete and testable.

### ⚠️ Concern
- **Global monkey-patch of `UsageError.exit_code`.** `click.exceptions.UsageError.exit_code = EXIT_USAGE` modifies Click's class-level default. This affects ALL Click apps in the same process, not just kb-mcp. For a CLI entry point this is fine (single process, single app), but if `cli.py` is ever imported by another process that also uses Click, it could cause unexpected behavior. Consider scoping this to just the `main()` function or using a custom Click `Group` subclass.
- **`init` command doesn't actually create the DB.** It calls `_get_store(ctx)` which creates a `SqliteStore`, which runs migrations. But `init` with `--force` doesn't drop and recreate — it just touches the existing DB. The docstring says "--force drops and recreates the DB" but the code doesn't do that. **This is a discrepancy between the CLI docstring and implementation.**
- **`doctor` exits with `EXIT_INTERNAL` (5) on failure, but `cli-reference.md` says "Exits 1 on any failure".** The code comments acknowledge this discrepancy (§ 647-651) and chooses consistency with the exit code table over the command-specific documentation. This is a reasonable choice but should be reconciled — either update `cli-reference.md` or change the code.

### ❌ Blocker
- None.

---

## 7. `stub_store.py` (Wave 1C)

### ✅ Good
- **Full Protocol conformance.** Implements every method in the `Store` Protocol. `__enter__`/`__exit__`/`close` for context manager support.
- **Search scoring.** Lower score = better match (character position of first hit) — mirrors FTS5 BM25 convention. Consistent with `SqliteStore` behavior.
- **Source index (`_by_source`).** O(1) lookup for idempotent re-import — matches `SqliteStore`'s source-based dedup.
- **`import_many` handles per-doc errors gracefully.** Collects errors in the report rather than failing the entire batch.

### ⚠️ Concern
- **`search()` snippet bolding uses `**...**` (markdown) not `<b></b>` (HTML).** `SqliteStore.search()` uses `snippet(docs_fts, ..., '<b>', '</b>', ...)` which produces HTML bold. The CLI renders HTML snippets for human output but markdown snippets for stub tests. This inconsistency is fine for tests but worth noting if someone expects visual parity.
- **`_Store = object` placeholder.** The NOTE explains why the Protocol isn't imported (namespace shadowing after Wave 1A). This is correct but fragile — if someone renames `store.py` or the package layout changes, the type checker gets no guidance. Consider adding a `pyright: ignore` or `# type: ignore` comment.

### ❌ Blocker
- None.

---

## 8. Test Files

### `test_store_sqlite.py` (38 tests)
- ✅ **Real SQLite temp files via `tmp_path`.** No mocks — exercises actual SQL.
- ✅ **Covers all Store methods.** add, get, list, search, update, delete, link, unlink, backlinks, outlinks, import_many, export_all, doctor, prune, reindex, context manager.
- ✅ **WAL + FK verification.** Explicitly checks PRAGMAs.
- ⚠️ **`test_add_invalid_id_raises` uses `pytest.raises(Exception)`.** Too broad — should use `pytest.raises(ValidationError)` or at least `KbMcpError`. This test passes because pydantic raises `ValidationError`, but the assertion doesn't verify the exception class.

### `test_md_io.py` (39 tests)
- ✅ **Round-trip coverage.** Import → export → import produces identical results.
- ✅ **Path-traversal tests.** Symlink escape, `../` attack vectors.
- ✅ **Frontmatter edge cases.** Empty frontmatter, multiline values, unknown keys preserved.
- ⚠️ **Uses `SqliteStore` as the store backend.** This is good for integration testing but means `md_io.py` is tested against the concrete implementation, not the Protocol. The Protocol abstraction benefit is reduced for this module.

### `test_cli_stub.py` (80+ tests)
- ✅ **Every CLI command tested.** init, add, get, search, list, link, import, export, doctor, serve.
- ✅ **Exit code verification.** Every error path asserts the correct exit code.
- ✅ **`--json` flag coverage.** JSON output format validated for every command.
- ✅ **`_assert_json_ok` / `_assert_json_error` helpers.** DRY error checking.
- ⚠️ **`import` and `export` commands test stub behavior.** They verify `NotImplementedError` → exit code 5. Once Wave 1B is done, these tests need to be updated to exercise the real `md_io` functions.

### `test_cli_sqlite.py` (46 tests)
- ✅ **Cross-invocation persistence.** Tests that `add` in one invocation can be `get` in another (real file-backed SQLite).
- ✅ **Happy path for all commands.** Mirrors `test_cli_stub.py` structure but against real SQLite.
- ✅ **`--json` output validation.** Parses JSON and checks structure.

---

## 9. `architecture.md` (Wave 0)

### ✅ Good
- **4 ADRs documented.** Each covers context, decision, and consequences. Append-only format.
- **ADR-0003 (Protocol-based Store).** Correctly identifies the trade-off: `isinstance` checks only method names, covered by `test_store_contract.py`.
- **Testing strategy section (§ 8).** Clear table mapping layers to test files. "No mocks" principle stated.
- **Cross-cutting concerns (§ 7).** Logging, exit codes, thread safety all documented.

### ⚠️ Concern
- **§ 4 (Interface Contracts) says `Store.update` raises `NotFoundError` if `doc_id` doesn't exist**, but the actual `SqliteStore.update()` first calls `self.get(doc_id, include_deleted=True)` which returns a deleted doc if it exists. Then it proceeds to update. The Protocol docstring says "`id`, `type`, `created_at` cannot be changed" but the implementation allows `type` to be changed (see blocker above).
- **ADR-0001 mentions "single-writer at a time" as a consequence of WAL.** WAL mode actually allows concurrent readers with a single writer — it doesn't serialize all writers. The ADR wording is slightly misleading.

### ❌ Blocker
- None.

---

## Summary

| File | ✅ Good | ⚠️ Concern | ❌ Blocker |
|------|---------|-----------|-----------|
| `schema.py` | Pydantic v2, discriminated unions, exceptions | `slugify` underscore behavior | — |
| `store.py` | Protocol design, docstrings, limits | Minor doc inconsistencies | — |
| `store/sqlite.py` | WAL, FK, soft-delete, doctor, FTS5 | `_UPDATEABLE_FIELDS` includes `type` (Protocol violation!) | **Yes: remove `"type"` from `_UPDATEABLE_FIELDS`** |
| `migrations.py` | Forward-only, versioned, `executescript()` fix | Partial migration failure mode | — |
| `md_io.py` | Path-traversal guard, round-trip, edge cases | `export_dir` source update race | — |
| `cli.py` | Click idioms, exit codes, env vars | `--force` doesn't drop/recreate; global `UsageError` monkey-patch | — |
| `stub_store.py` | Full Protocol, search scoring, source index | Snippet format mismatch with SqliteStore | — |
| Tests | 194 tests, no mocks, real SQLite | `test_add_invalid_id_raises` too broad | — |
| `architecture.md` | 4 ADRs, testing strategy, cross-cutting | §4 contract vs. implementation gap | — |

## Recommended Actions

1. **Blocker fix (do now):** Remove `"type"` from `_UPDATEABLE_FIELDS` in `sqlite.py:41`. This violates the Store Protocol contract.
2. **Reconcile `--force` behavior:** Either implement actual DB recreation in `init --force`, or update the docstring to match current behavior (which is just "touch the DB").
3. **Reconcile `doctor` exit code:** Either change `cli.py:651` to exit 1 (per `cli-reference.md`), or update `cli-reference.md` to say exit 5.
4. **Narrow `test_add_invalid_id_raises`:** Change `pytest.raises(Exception)` to `pytest.raises((ValidationError, KbMcpError))`.
5. **TODO for Wave 1B:** Update `test_cli_stub.py` import/export tests from stub verification to real `md_io` integration.
