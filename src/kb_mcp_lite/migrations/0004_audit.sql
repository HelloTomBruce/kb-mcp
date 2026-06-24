-- kb-mcp migration 0004: document versions + audit log
-- Adds append-only history so admin tooling can show who/what/when
-- for content and link changes.

CREATE TABLE IF NOT EXISTS document_versions (
    version_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id       TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    action       TEXT NOT NULL,
    snapshot     TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    actor        TEXT,
    note         TEXT
);

CREATE INDEX IF NOT EXISTS idx_document_versions_doc_id
    ON document_versions(doc_id, version_id DESC);

CREATE TABLE IF NOT EXISTS audit_log (
    audit_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type  TEXT NOT NULL,
    entity_id    TEXT NOT NULL,
    action       TEXT NOT NULL,
    detail       TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL,
    actor        TEXT,
    note         TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_log_entity
    ON audit_log(entity_type, entity_id, audit_id DESC);

CREATE INDEX IF NOT EXISTS idx_audit_log_created_at
    ON audit_log(created_at DESC);
