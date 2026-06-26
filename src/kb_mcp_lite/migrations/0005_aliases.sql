-- kb-mcp migration 0005: document aliases
-- Adds a separate table for document aliases (alternative IDs).
-- An alias is globally unique across all documents.

CREATE TABLE IF NOT EXISTS doc_aliases (
    alias      TEXT PRIMARY KEY,
    doc_id     TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_doc_aliases_doc_id
    ON doc_aliases(doc_id);
