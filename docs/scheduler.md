# Scheduled Tasks

kb-mcp v0.8 includes a built-in task scheduler powered by APScheduler. Tasks run automatically in the background when `kb serve`, `kb admin`, or `kb watch` is running.

## Built-in Tasks

| Task | Description | Default Frequency |
|------|-------------|-------------------|
| `auto-commit` | Export vault changes and git commit (no push) | 30m |
| `auto-embed` | Process one batch from the embedding queue | 5m |
| `auto-reindex` | Full FTS5 reindex | Daily 3am |
| `doctor` | Run health check, write audit log | Weekly Monday 9am |
| `prune` | Hard-delete documents soft-deleted >30 days ago | Weekly Sunday 2am |

## Configuration

Add a `schedule` section to `~/.config/kb-mcp/config.yaml`:

```yaml
kb:
  schedule:
    - task: auto-commit
      interval: "30m"
      enabled: true
    - task: auto-embed
      interval: "5m"
      batch_size: 20
    - task: auto-reindex
      cron: "0 3 * * *"
    - task: doctor
      cron: "0 9 * * 1"
    - task: prune
      cron: "0 2 * * 0"
      older_than_days: 30
```

### Trigger Types

| Type | Example | Description |
|------|---------|-------------|
| `interval` | `"30m"`, `"5s"`, `"2h"` | Periodic (suffix: s/m/h) |
| `cron` | `"0 3 * * *"` | Standard cron expression |
| `at` | `"2026-01-01T00:00:00"` | One-shot at specific time |

### Disabling Tasks

```yaml
- task: auto-commit
  interval: "30m"
  enabled: false  # skipped during registration
```

## CLI Commands

```bash
kb scheduler list                # List all registered tasks
kb scheduler status              # Status + next run times
kb scheduler run auto-commit     # Manually trigger a task
kb scheduler history             # Recent execution history
kb scheduler history --limit 50  # More records
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `kb_schedule_list()` | List all registered tasks |
| `kb_schedule_status()` | Scheduler status + next run times |
| `kb_schedule_run(task_name)` | Manually trigger a task |
| `kb_schedule_history(limit?)` | Recent execution history |

## Execution History

All task executions are recorded in the `schedule_history` table:

```sql
CREATE TABLE schedule_history (
    run_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    task_name   TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL,  -- 'ok' | 'error' | 'skipped'
    duration_ms INTEGER,
    error       TEXT,
    triggered_by TEXT           -- 'cron' | 'interval' | 'manual' | 'auto'
);
```

## Dependencies

APScheduler is an optional dependency:

```bash
pip install 'kb-mcp-lite[v0.8]'
```

Without APScheduler, the scheduler is a no-op (tasks don't run, but the rest of kb-mcp works normally).

## Process Model

| Mode | Startup | Use Case |
|------|---------|----------|
| Embedded | `kb serve` / `kb admin` starts scheduler automatically | Single process, single vault |
| Daemon | `kb scheduler start --daemon` (planned) | Multiple vaults |
| Manual | `kb scheduler run <task_name>` | Debugging |

## Cross-Process Safety

Tasks use the same write lock as other operations to prevent concurrent execution across multiple kb-mcp processes. If a task is already running in another process, the current process skips the trigger.
