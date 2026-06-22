-- kb-mcp migration 0002: trigram FTS5 for fuzzy / typo-tolerant search
-- v0.2.0 (Wave 1 of C). Adds a second FTS5 virtual table that tokenises
-- text into 3-grams, then keeps it in sync with the `documents` table via
-- triggers (mirroring the structure of `docs_fts`). The store's search()
-- queries both tables and merges BM25 hits so that:
--
--   * exact token matches rank first (original `docs_fts`)
--   * fuzzy / typo / prefix matches still surface (`docs_fts_trgm`)
--
-- Storage cost: ~3x the original FTS index. For a 10k-doc KB this is
-- still <10 MB. See docs/v0.2-plan.md for trade-off discussion.

CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts_trgm USING fts5(
    title,
    body,
    tags,
    content='documents',
    content_rowid='rowid',
    tokenize='trigram'
);

-- INSERT
CREATE TRIGGER IF NOT EXISTS docs_ai_trgm AFTER INSERT ON documents BEGIN
    INSERT INTO docs_fts_trgm(rowid, title, body, tags)
    VALUES (new.rowid, new.title, new.body, new.tags);
END;

-- DELETE (hard delete via cascade or `prune`)
CREATE TRIGGER IF NOT EXISTS docs_ad_trgm AFTER DELETE ON documents BEGIN
    INSERT INTO docs_fts_trgm(docs_fts_trgm, rowid, title, body, tags)
    VALUES ('delete', old.rowid, old.title, old.body, old.tags);
END;

-- UPDATE — same dance as docs_fts: delete+insert to dodge FTS5's
-- "same content" no-op on UPDATE.
CREATE TRIGGER IF NOT EXISTS docs_au_trgm AFTER UPDATE ON documents BEGIN
    INSERT INTO docs_fts_trgm(docs_fts_trgm, rowid, title, body, tags)
    VALUES ('delete', old.rowid, old.title, old.body, old.tags);
    INSERT INTO docs_fts_trgm(rowid, title, body, tags)
    VALUES (new.rowid, new.title, new.body, new.tags);
END;

-- Backfill: existing active documents must also be indexed by trigram
-- (the triggers above only fire for rows written AFTER this migration).
-- Soft-deleted rows are excluded to match `docs_fts` semantics.
INSERT INTO docs_fts_trgm(rowid, title, body, tags)
    SELECT rowid, title, body, tags
    FROM documents
    WHERE deleted_at IS NULL;
