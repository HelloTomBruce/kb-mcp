# Auto-Link (Content-Level Backlinks)

kb-mcp v0.8 automatically extracts document references from Markdown body content and creates `references` links in the knowledge graph.

## How It Works

When a document is added (`kb add`) or its body is updated (`kb update`), the auto-link system:

1. Parses the body for reference patterns
2. Matches candidates against known document IDs
3. Creates `references` links for matches
4. Removes stale links when body content changes

## Supported Reference Syntax

| Syntax | Example | Parsed As |
|--------|---------|-----------|
| Markdown link | `[text](lesson/sqlite-libs)` | `lesson/sqlite-libs` |
| Inline code | `` `dec/use-sqlite-fts5` `` | `dec/use-sqlite-fts5` |

### Conservative Strategy

- Only matches IDs matching `^[a-z0-9][a-z0-9/_-]*$`
- Only creates links when the target ID exists in the knowledge base (no dangling references)
- Fenced code blocks (` ``` ... ``` `) are excluded from parsing
- The `references` relation type is distinct from `relates-to` — it means "body mentions this document"

## Configuration

Auto-link is enabled by default. Configure in `~/.config/kb-mcp/config.yaml`:

```yaml
kb:
  auto_link:
    enabled: true           # default true
    rel: "references"       # default "references"
    scan_body: true         # default true
    markdown_links: true    # default true
    code_refs: true         # default true
```

### Disabling Auto-Link

```yaml
kb:
  auto_link:
    enabled: false
```

Or per-operation: auto-link only runs on `add` and `update` (when body changes). Manual `kb link` calls are unaffected.

## Example

```markdown
---
type: decision
title: Use SQLite FTS5
---

# Use SQLite FTS5

For full-text search, we adopt FTS5 (see [lesson on pysqlite3](lesson/dont-mix-sqlite-libs)).
This decision supersedes `dec/use-lucene` from the v0.1 prototype.
```

This body automatically creates:
- `this-doc → lesson/dont-mix-sqlite-libs` (references, markdown syntax)
- `this-doc → dec/use-lucene` (references, code syntax)

## MCP Tools

| Tool | Description |
|------|-------------|
| `kb_expand(doc_id)` | Show 1-hop neighbors (includes auto-created references) |
| `kb_search(query, expand_graph=True)` | Search with graph expansion (related docs shown) |

## Implementation Details

- **File**: `src/kb_mcp_lite/link_parser.py`
- **Hook**: `SqliteStore._sync_body_references()` called from `add()` and `update()`
- **Performance**: ~0.4ms per document for 1000-doc benchmark (extract + sync)
- **Staleness**: On body update, old references not found in new body are removed automatically
