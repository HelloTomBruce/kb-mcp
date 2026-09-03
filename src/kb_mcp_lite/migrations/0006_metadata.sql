-- kb-mcp migration 0006: document structured metadata column
-- Adds metadata column (JSON text) to documents table for typed facts / attributes.

ALTER TABLE documents ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}';
