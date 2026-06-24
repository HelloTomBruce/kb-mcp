"""Storage backends for kb-mcp.

The :class:`~kb_mcp_lite.store.sqlite.SqliteStore` is the v0.1.0 implementation.
Other backends (e.g. in-memory, Postgres) can be added by implementing the
:class:`~kb_mcp_lite.store.Store` Protocol.
"""

from kb_mcp_lite.store.sqlite import SqliteStore

__all__ = ["SqliteStore"]
