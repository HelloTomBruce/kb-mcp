# CLI Reference

All commands start with `kb`. Global options apply to every subcommand:

| Option | Default | Description |
|--------|---------|-------------|
| `--vault <name>` | `default` | Target vault name or path |
| `--strict-lock / --no-strict-lock` | `$KB_MCP_STRICT_LOCK` or `False` | Cross-process write locking |
| `--lock-timeout <float>` | `10.0` | Lock acquisition timeout (seconds) |
| `--version` | | Show version |

---

## Document CRUD

### `kb add`

```
kb add --type <TYPE> --title <TITLE> [--body <BODY>] [--tags <TAGS>] [--json]
```

Add a new document. `--tags` accepts comma-separated values.

### `kb get <DOC_ID>`

```
kb get <DOC_ID> [--section <HEADING>] [--json]
```

Fetch a document. Use `--section` to extract a single heading.

### `kb update <DOC_ID>`

```
kb update <DOC_ID> [--title <TITLE>] [--tags <TAGS>] [--body <BODY>] [--json]
```

Patch fields on an existing document.

### `kb delete <DOC_ID>`

```
kb delete <DOC_ID> [--json]
```

Soft-delete a document.

### `kb restore <DOC_ID>`

```
kb restore <DOC_ID> [--version <INT>] [--json]
```

Restore a soft-deleted document or roll back to a previous version.

### `kb history <DOC_ID>`

```
kb history <DOC_ID> [--json]
```

Show version history.

### `kb diff <DOC_ID>`

```
kb diff <DOC_ID> --v1 <INT> --v2 <INT> [--json]
```

Field-level diff between two versions.

---

## Search & List

### `kb search <QUERY>`

```
kb search <QUERY> [--type <TYPE>] [--tags <TAG>]... [--fuzzy] [--limit <N>] [--json]
```

Full-text search. Use `--fuzzy` for trigram mode. `--tags` may be repeated.

### `kb list`

```
kb list [--type <TYPE>] [--tags <TAG>]... [--project <ID>] [--link-to <ID>] [--link-from <ID>]
        [--limit <N>] [--offset <N>] [--include-deleted] [--json]
```

List documents sorted by `updated_at` DESC.

---

## Links & Relations

### `kb link`

```
kb link --from <FROM_ID> --to <TO_ID> [--rel <REL>] [--json]
```

Create a typed edge. Default `--rel` is `relates-to`.

### `kb unlink`

```
kb unlink --from <FROM_ID> --to <TO_ID> [--rel <REL>] [--json]
```

Remove edges. Omit `--rel` to remove all edges between the two documents.

### `kb links <DOC_ID>`

```
kb links <DOC_ID> [--json]
```

Show all incoming and outgoing links.

### `kb rel list`

```
kb rel list [--json]
```

List all 10 standard relation types.

### `kb rel show <REL_NAME>`

```
kb rel show <REL_NAME> [--json]
```

Show details for a specific relation (direction, description, examples).

---

## Impact & Chain Analysis

### `kb impact <DOC_ID>`

```
kb impact <DOC_ID> [--max-depth <N>] [--max-results <N>] [--json]
```

Find all documents influenced by the given document (traverses `governs`, `depends-on`, `supersedes`, `blocks`).

### `kb chain <DECISION_ID>`

```
kb chain <DECISION_ID> [--json]
```

Trace the supersession chain for a decision document.

---

## Import & Export

### `kb import <DIRECTORY>`

```
kb import <DIRECTORY> [--dry-run] [--json]
```

Import Markdown files from a directory. Files must have YAML frontmatter (`type`, `title`).

### `kb export <DIRECTORY>`

```
kb export <DIRECTORY> [--force] [--json]
```

Export all documents as Markdown files.

---

## Embeddings

### `kb embed`

```
kb embed [--json]
```

Show embedder status summary.

### `kb embed status`

```
kb embed status [--json]
```

Show embedding queue state (pending / in_progress / done / failed).

### `kb embed retry [DOC_ID]`

```
kb embed retry [DOC_ID] [--all] [--json]
```

Re-queue failed embedding jobs. Omit `DOC_ID` + `--all` to reset all failures.

---

## Sync & Git

### `kb watch`

```
kb watch [--interval <SEC>] [--mode <auto|event|poll>] [--debounce-ms <MS>]
```

Watch the Markdown directory and auto-sync changes to SQLite.

### `kb reindex`

```
kb reindex
```

Rebuild the full-text search index.

---

## Vault Management

### `kb vault list`

```
kb vault list [--json]
```

### `kb vault create <NAME>`

```
kb vault create <NAME> [--desc <TEXT>] [--json]
```

### `kb vault switch <NAME>`

```
kb vault switch <NAME>
```

### `kb vault init-git`

```
kb vault init-git --sync-dir <PATH>
```

### `kb vault commit`

```
kb vault commit -m <MESSAGE> [--full] [--json]
```

### `kb vault push [REMOTE] [BRANCH]`

```
kb vault push [origin] [main]
```

### `kb vault pull [REMOTE] [BRANCH]`

```
kb vault pull [origin] [main]
```

### `kb vault status`

```
kb vault status
```

### `kb vault sync`

```
kb vault sync [-m <MESSAGE>] [--remote <REMOTE>] [--branch <BRANCH>]
```

Export → commit → pull → push in one step.

---

## Scheduled Tasks

### `kb scheduler list`

```
kb scheduler list [--json]
```

List all registered tasks with disabled/failure status.

### `kb scheduler status`

```
kb scheduler status [--json]
```

Show scheduler running state and next run times.

### `kb scheduler run <TASK_NAME>`

```
kb scheduler run <TASK_NAME> [--json]
```

Manually trigger a task. Built-in tasks: `auto-commit`, `auto-embed`, `auto-reindex`, `doctor`, `prune`.

### `kb scheduler history`

```
kb scheduler history [--limit <N>] [--json]
```

Show task execution history.

---

## Administration

### `kb doctor`

```
kb doctor [--json]
```

Run health checks (FTS integrity, vec0, schema version, migrations).

### `kb stats`

```
kb stats [--json]
```

Show document counts, types, tag distribution.

### `kb prune`

```
kb prune [--older-than <DAYS>] [--json]
```

Permanently delete soft-deleted documents older than N days (default 30).

### `kb diff-check`

```
kb diff-check [--json]
```

Analyze current git diff and recommend ADRs, lessons, and constraints.

### `kb admin start`

```
kb admin start [--port <PORT>]
```

Start the web administration interface (default port 8888).

### `kb serve`

```
kb serve [--log-level <LEVEL>] [--vault <NAME>]
```

Start the MCP server on stdio.

---

## MCP Tools (Agent Interface)

These tools are available when `kb-mcp` is used as an MCP server. They mirror most CLI commands with richer parameters.

| Tool | Description |
|------|-------------|
| `kb_add` | Create document (supports `aliases`, `metadata`, `source`, `id`) |
| `kb_get` | Fetch document (supports `vault` param) |
| `kb_update` | Patch document (supports `aliases`, `metadata`, `source`) |
| `kb_delete` | Soft-delete |
| `kb_restore` | Restore to a specific version |
| `kb_restore_deleted` | Restore soft-deleted document |
| `kb_search` | Search with `mode` (lexical/fuzzy/semantic/hybrid/rrf), `vault` wildcard |
| `kb_list` | List documents (supports `vault`) |
| `kb_link` | Create typed edge |
| `kb_unlink` | Remove edges |
| `kb_rel_spec` | List or describe relation types |
| `kb_query_relations` | Multi-hop graph traversal |
| `kb_impact` | Impact analysis |
| `kb_decision_chain` | Supersession chain |
| `kb_expand` | 1-hop graph expansion |
| `kb_similar` | Embedding similarity search |
| `kb_duplicates` | Near-duplicate detection |
| `kb_embed_status` | Embedding queue status |
| `kb_embed_retry` | Re-queue failed embeddings |
| `kb_schedule_list` | List scheduled tasks |
| `kb_schedule_status` | Scheduler status |
| `kb_schedule_run` | Trigger a task |
| `kb_schedule_history` | Task execution history |
| `kb_history` | Version history |
| `kb_diff` | Version diff |
| `kb_doctor` | Health check |
| `kb_diff_check` | Git diff analysis |
