-- kb-mcp migration 0007: async embedding queue
-- v0.8.0 (特性 #1 异步化嵌入). Adds a queue table that records which
-- documents still need an embedding. The EmbeddingWorker (a background
-- thread inside SqliteStore) drains this table; ``kb add`` / ``kb update``
-- enqueue but do not block on the network.
--
-- State machine:
--
--     pending  ──(worker picks)──>  in_progress
--     in_progress  ──(success)──>  done
--     in_progress  ──(transient)──>  pending     (attempts < max_attempts)
--     in_progress  ──(permanent)──>  failed     (attempts >= max_attempts)
--
-- The four states are enforced both by the CHECK below and by code in
-- ``kb_mcp_lite.store.embedding_queue``. ``done`` and ``failed`` are
-- terminal: once a row is in either state the worker will not touch it
-- again until ``kb embed retry <doc_id>`` flips it back to ``pending``.
--
-- ``attempts`` is the number of failed attempts. The worker computes a
-- backoff from this column (1s, 5s, 30s, 5m, 30m) and stores the time
-- of the next eligible attempt in ``last_attempt_at``; the enqueue-time
-- check (``enqueued_at``) is only used for FIFO ordering inside the
-- pending set.
--
-- ``ON DELETE CASCADE`` is intentional: when a document is hard-deleted
-- (prune, hard-restore), the queue row vanishes with it. Soft-deletes
-- leave the row in place — the worker will attempt the embedding, fail
-- on a NotFoundError, and move on; the row eventually reaches ``failed``
-- and can be cleared by ``kb embed retry`` once the user decides.

CREATE TABLE IF NOT EXISTS embedding_queue (
    doc_id          TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    enqueued_at     TEXT NOT NULL,
    attempts        INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 5,
    last_error      TEXT,
    last_attempt_at TEXT,
    state           TEXT NOT NULL DEFAULT 'pending'
        CHECK(state IN ('pending', 'in_progress', 'done', 'failed'))
);

-- The worker polls this index to find the next eligible row in FIFO
-- order. ``(state, enqueued_at)`` keeps the most common query
-- ("next pending row") a single index lookup.
CREATE INDEX IF NOT EXISTS idx_embedding_queue_state
    ON embedding_queue(state, enqueued_at);
