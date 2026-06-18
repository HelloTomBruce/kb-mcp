# kb-mcp — CLI Reference

Every command supports `--json` for machine-readable output. Exit codes:

| Code | Meaning |
|---|---|
| 0 | Success |
| 2 | Validation error (bad input) |
| 3 | Not found |
| 4 | Conflict (e.g. duplicate) |
| 5 | Internal error (DB / I/O) |
| 64 | Usage error (bad invocation) |

Environment variables:

| Var | Default | Purpose |
|---|---|---|
| `KB_MCP_HOME` | `~/.local/share/kb-mcp/` | KB root directory |
| `KB_MCP_LOG_LEVEL` | `WARNING` | One of `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `KB_MCP_NO_COLOR` | unset | Set to any value to disable ANSI colour |

---

## `kb init`

Initialize a kb-mcp database. Idempotent unless `--force`.

```
kb init [--force] [--json]
```

| Flag | Effect |
|---|---|
| `--force` | Recreate the DB even if it exists (DESTRUCTIVE — confirms unless `--yes`) |
| `--yes` / `-y` | Skip confirmation prompts |
| `--json` | Output a JSON summary |

---

## `kb add`

Create a document.

```
kb add --type TYPE --title TITLE [--tags t1,t2,...] [--body BODY] [--source PATH] [--json]
```

If `--body` is omitted, `kb` reads body from stdin (until EOF). If `--source`
is set, the document is marked as imported from that path (enables
idempotent re-import).

Returns the new document's id on success.

---

## `kb get`

Fetch a document by id.

```
kb get ID [--json]
```

| Flag | Effect |
|---|---|
| `--json` | Full document as JSON (machine-readable) |

Renders Markdown body for human output.

---

## `kb search`

Full-text search via FTS5 (BM25 ranking).

```
kb search QUERY [--type TYPE] [--tag TAG]... [--limit N] [--json]
```

| Flag | Default | Effect |
|---|---|---|
| `--type` | (any) | Restrict to document type |
| `--tag` | (any) | Restrict to documents carrying every listed tag (AND) |
| `--limit` / `-n` | 10 | Max results (capped at 100) |
| `--json` | off | Output `{id, title, type, snippet, score}[]` |

Human output shows id, type, and a snippet with matched terms in **bold**.

---

## `kb list`

List documents, optionally filtered.

```
kb list [--type TYPE] [--tag TAG]... [--limit N] [--json]
```

Sorts by `updated_at DESC`.

---

## `kb link`

Create or update a typed edge between two documents.

```
kb link --from FROM_ID --to TO_ID [--rel REL] [--json]
```

`--rel` defaults to `relates-to`. Idempotent: re-linking the same
`(from, to, rel)` triple is a no-op.

---

## `kb import`

Import a directory of Markdown files into the DB.

```
kb import DIR [--json] [--dry-run]
```

Walks `DIR` recursively, parses YAML frontmatter (`type`, `title`, `tags`,
`source`), inserts or updates documents keyed by `source` path. Body is the
Markdown content after the frontmatter.

---

## `kb export`

Export the DB to a directory of Markdown files.

```
kb export DIR [--force] [--json]
```

One file per document: `<slug>.md`. Filename collisions get a numeric
suffix (`-1`, `-2`, …). `--force` allows overwriting an existing
directory.

---

## `kb doctor`

Run health checks on the DB.

```
kb doctor [--json]
```

Checks:

1. SQLite `PRAGMA integrity_check` returns `ok`
2. FTS5 row count matches `documents` row count
3. No `Link` row references a missing document
4. All documents have a non-empty `type` and `title`

Exits 5 (`EXIT_INTERNAL`) on any failure (with a per-check summary in human mode).

---

## `kb reindex` *(P1)*

Rebuild the FTS5 index from scratch. Use after `kb doctor` reports FTS
drift, or after bulk-importing outside `kb import`.

```
kb reindex [--json]
```

---

## `kb serve`

Start the MCP server on stdio. Blocks until EOF on stdin or SIGINT.

```
kb serve [--log-level LEVEL]
```

Designed to be spawned by an MCP client. Exposes:

- `kb_search(query, type?, tags?, limit?)`
- `kb_get(id)`
- `kb_add(type, title, body, tags?, source?)`
- `kb_link(from_id, to_id, rel?)`

See [`architecture.md`](./architecture.md) § 4 for the wire-level spec.

---

## Examples

```bash
# Bulk-add from a file
kb add --type project --title "kb-mcp" --tags kb,mcp < body.md

# JSON output for piping
kb search "fts5" --json | jq '.[0].id'

# Strict mode (non-zero exit on missing doc)
kb get nonexistent-id || echo "not found, exit=$?"
```

---

## See also

- [Quickstart](./quickstart.md)
- [Architecture](./architecture.md)
- [Requirements](./requirements.md)
