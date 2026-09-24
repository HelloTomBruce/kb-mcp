-- kb-mcp migration 0009: vault-scoped custom document types
-- Stores custom type definitions directly in SQLite so each vault maintains
-- its own isolated custom types, preserving metadata on backup/sync.

CREATE TABLE IF NOT EXISTS custom_types (
    name        TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    color       TEXT NOT NULL DEFAULT '#64748b',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
