# kb-mcp Architecture

kb-mcp is a local-first, schema-first knowledge base for AI agents.

## Storage

- SQLite is the single-file database.
- FTS5 provides lexical BM25 search.
- Trigram FTS5 provides fuzzy search.
- Optional sqlite-vec plus an OpenAI-compatible embedder provides semantic search.
- Version snapshots and an audit log are stored in SQLite migrations.

## Store

The public contract is a `Store` Protocol in `src/kb_mcp_lite/store.py`.
The SQLite implementation composes mixins for search, versioning,
embeddings, and maintenance.

## MCP Surface

The server exposes:

- 15 tools for search, CRUD, links, versions, health, similarity, and duplicates.
- 13 read-only resources for documents, stats, graphs, exports, and help.
- 7 prompts that guide common agent workflows.

## Lifecycle Boundary

Runtime data operations are available through MCP.
Filesystem batch import/export, pruning, reindexing, vaults, and Git sync
are lifecycle operations owned by the CLI and Web admin UI.
