-- kb-mcp initial schema (migration 0001)
-- This file is loaded by the migration runner when the DB is empty or
-- when the schema_version table does not contain this version number.
--
-- Edit with care: any change to a column shape, constraint, or index
-- requires a NEW migration file (0002_*.sql, ...). Never edit this file
-- after a release has shipped.

PRAGMA foreign_keys = ON;

-- ---- Migration tracking -------------------------------------------------

CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ---- Documents ----------------------------------------------------------

CREATE TABLE IF NOT EXISTS documents (
    id         TEXT PRIMARY KEY,
    type       TEXT NOT NULL,
    title      TEXT NOT NULL,
    body       TEXT NOT NULL DEFAULT '',
    tags       TEXT NOT NULL DEFAULT '[]',     -- JSON array of strings
    source     TEXT,                            -- origin file path if imported
    created_at TEXT NOT NULL,                   -- ISO-8601 UTC
    updated_at TEXT NOT NULL,
    deleted_at TEXT                             -- ISO-8601 UTC or NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_type
    ON documents(type) WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_documents_updated
    ON documents(updated_at DESC) WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_documents_source
    ON documents(source) WHERE source IS NOT NULL;

-- ---- Links --------------------------------------------------------------

CREATE TABLE IF NOT EXISTS links (
    from_id    TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    to_id      TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    rel        TEXT NOT NULL DEFAULT 'relates-to',
    created_at TEXT NOT NULL,
    PRIMARY KEY (from_id, to_id, rel)
);

CREATE INDEX IF NOT EXISTS idx_links_to ON links(to_id);
CREATE INDEX IF NOT EXISTS idx_links_rel ON links(rel);

-- ---- Full-text search (FTS5) -------------------------------------------
-- Contentless mirror of (title, body, tags). Triggers below keep it in
-- sync with `documents`. Soft-deleted rows are removed from the FTS index
-- via the same trigger.

CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
    title,
    body,
    tags,
    content='documents',
    content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);

-- INSERT
CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON documents BEGIN
    INSERT INTO docs_fts(rowid, title, body, tags)
    VALUES (new.rowid, new.title, new.body, new.tags);
END;

-- DELETE (hard delete via cascade or `prune`)
CREATE TRIGGER IF NOT EXISTS docs_ad AFTER DELETE ON documents BEGIN
    INSERT INTO docs_fts(docs_fts, rowid, title, body, tags)
    VALUES ('delete', old.rowid, old.title, old.body, old.tags);
END;

-- UPDATE — FTS5 doesn't tolerate UPDATE-of-same-content, so we delete+insert.
CREATE TRIGGER IF NOT EXISTS docs_au AFTER UPDATE ON documents BEGIN
    INSERT INTO docs_fts(docs_fts, rowid, title, body, tags)
    VALUES ('delete', old.rowid, old.title, old.body, old.tags);
    INSERT INTO docs_fts(rowid, title, body, tags)
    VALUES (new.rowid, new.title, new.body, new.tags);
END;

-- ---- Seed (built-in types) ----------------------------------------------
-- Type registry is in code (TypeRegistry), not SQL, so nothing seeds here.
-- This is intentional: schema changes for a new built-in type are
-- pydantic-model changes, not DB changes.
