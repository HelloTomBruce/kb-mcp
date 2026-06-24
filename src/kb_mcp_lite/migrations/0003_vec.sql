-- kb-mcp migration 0003: sqlite-vec for semantic search
-- v0.2.0 (Phase D). Adds a vec0 virtual table that stores one float[N]
-- vector per document, used by the semantic / hybrid search modes.
--
-- The dimension is fixed at 1536 — a common default for OpenAI's
-- text-embedding-3-small / BGE-base / M3E-base. If your embedding
-- model uses a different dim, run ``kb embed --rebuild`` after this
-- migration; the table will be dropped and recreated automatically.
--
-- Why 1536: covers the most common public embedding APIs (OpenAI
-- ada-002, text-embedding-3-small, BGE-base-en, M3E-base) and is the
-- smallest dim that still gives reasonable semantic quality.

CREATE VIRTUAL TABLE IF NOT EXISTS docs_vec USING vec0(
    embedding float[1536] distance_metric=cosine
);
