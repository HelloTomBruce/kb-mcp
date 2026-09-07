"""Concurrency primitives for kb-mcp.

This subpackage provides cross-process coordination primitives. Currently:

* :class:`WriteLock` — a context-manager file lock used to serialise writers
  across multiple kb-mcp processes (MCP server, watcher, CLI, admin). It is
  the optional strict mode that complements SQLite's built-in ``busy_timeout``
  retry behaviour. When the lock cannot be acquired within the configured
  timeout it raises :class:`ResourceBusyError`.

A functional wrapper, ``write_lock``, is also provided as
:func:`kb_mcp_lite.concurrency.write_lock.write_lock` (imported from the
submodule directly to avoid a name clash with the submodule).
"""

from kb_mcp_lite.concurrency.write_lock import (
    ResourceBusyError,
    WriteLock,
    flock_acquire,
    flock_release,
)

__all__ = [
    "ResourceBusyError",
    "WriteLock",
    "flock_acquire",
    "flock_release",
]
