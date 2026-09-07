-- kb-mcp migration 0008: scheduled task history
-- v0.8.3 (特性 #7 内置定时任务). Records execution history for
-- scheduled tasks so users can audit what ran, when, and whether it
-- succeeded.

CREATE TABLE IF NOT EXISTS schedule_history (
    run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    task_name     TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT NOT NULL CHECK(status IN ('ok', 'error', 'skipped')),
    duration_ms   INTEGER,
    error         TEXT,
    triggered_by  TEXT  -- 'cron' | 'interval' | 'manual' | 'auto'
);

CREATE INDEX IF NOT EXISTS idx_schedule_history_task
    ON schedule_history(task_name, started_at DESC);

-- Fast lookup for recent errors (doctor / monitoring).
CREATE INDEX IF NOT EXISTS idx_schedule_history_recent
    ON schedule_history(started_at DESC) WHERE status = 'error';
