"""File watcher and incremental indexer for kb-mcp.

Watches the vault's Markdown directory (`md/`) for changes (creation, modification,
deletion) and synchronizes them to the SQLite database with debouncing.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Callable, Dict, Optional, Set

from kb_mcp_lite.md_io import parse_frontmatter, doc_from_frontmatter, _coerce_links
from kb_mcp_lite.schema import Document, NotFoundError, ValidationError
from kb_mcp_lite.store.sqlite import SqliteStore
from kb_mcp_lite.vault import VaultManager

logger = logging.getLogger("kb_mcp_lite.watcher")


class VaultWatcher:
    """Watches a Markdown directory and syncs changes to a SqliteStore."""

    def __init__(
        self,
        vault_name: Optional[str] = None,
        debounce_seconds: float = 1.0,
        vault_manager: Optional[VaultManager] = None,
        on_change: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.vm = vault_manager or VaultManager()
        self.vault_name = vault_name or self.vm.get_current()
        self.debounce_seconds = debounce_seconds
        self.on_change = on_change
        self._running = False
        self._file_mtimes: Dict[Path, float] = {}

    @property
    def watch_dir(self) -> Path:
        """Return the Markdown directory being watched."""
        return self.vm._sync_dir(self.vault_name)

    @property
    def db_path(self) -> Path:
        """Return the database path for the target vault."""
        return self.vm.resolve_path(self.vault_name)

    def scan_once(self, store: Optional[SqliteStore] = None) -> dict[str, list[str]]:
        """Perform a single pass scan over watch_dir and sync detected changes.
        
        Returns a dict of {"created": [...], "updated": [...], "deleted": [...], "errors": [...]}.
        """
        w_dir = self.watch_dir
        if not w_dir.exists():
            w_dir.mkdir(parents=True, exist_ok=True)

        owns_store = store is None
        if owns_store:
            store = SqliteStore(self.db_path)

        created: list[str] = []
        updated: list[str] = []
        deleted: list[str] = []
        errors: list[str] = []

        current_files: Set[Path] = set()

        try:
            for root, dirs, files in os.walk(w_dir):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for file_name in files:
                    if file_name.startswith(".") or not file_name.endswith(".md"):
                        continue
                    file_path = (Path(root) / file_name).resolve()
                    current_files.add(file_path)

                    try:
                        mtime = file_path.stat().st_mtime
                    except OSError:
                        continue

                    prev_mtime = self._file_mtimes.get(file_path)
                    if prev_mtime is None:
                        # Newly detected file
                        self._file_mtimes[file_path] = mtime
                        err = self._sync_file(store, file_path, w_dir)
                        if err:
                            errors.append(f"{file_path}: {err}")
                        else:
                            created.append(str(file_path.relative_to(w_dir)))
                            if self.on_change:
                                self.on_change("created", str(file_path.relative_to(w_dir)))
                    elif mtime > prev_mtime:
                        # Modified file
                        self._file_mtimes[file_path] = mtime
                        err = self._sync_file(store, file_path, w_dir)
                        if err:
                            errors.append(f"{file_path}: {err}")
                        else:
                            updated.append(str(file_path.relative_to(w_dir)))
                            if self.on_change:
                                self.on_change("updated", str(file_path.relative_to(w_dir)))

            # Detect deleted files
            deleted_files = set(self._file_mtimes.keys()) - current_files
            for del_path in deleted_files:
                try:
                    rel_path = del_path.relative_to(w_dir)
                    file_id = rel_path.with_suffix("").as_posix()
                    del self._file_mtimes[del_path]
                    try:
                        store.delete(file_id)
                        deleted.append(str(rel_path))
                        if self.on_change:
                            self.on_change("deleted", str(rel_path))
                    except NotFoundError:
                        pass
                except Exception as e:
                    errors.append(f"{del_path}: {e}")

        finally:
            if owns_store and store:
                store.close()

        return {
            "created": created,
            "updated": updated,
            "deleted": deleted,
            "errors": errors,
        }

    def _sync_file(self, store: SqliteStore, file_path: Path, base_dir: Path) -> Optional[str]:
        """Parse and upsert a single markdown file into the store."""
        try:
            text = file_path.read_text(encoding="utf-8")
            fm, body = parse_frontmatter(text)
            rel_source = str(file_path.relative_to(base_dir))
            file_id = Path(rel_source).with_suffix("").as_posix()
            doc = doc_from_frontmatter(fm, body, source=rel_source, file_id=file_id)

            # Store upsert: if exists, update; else add
            try:
                existing = store.get(doc.id, include_deleted=True)
                store.update(
                    doc.id,
                    title=doc.title,
                    body=doc.body,
                    tags=doc.tags,
                    aliases=doc.aliases,
                    metadata=doc.metadata,
                    source=doc.source,
                )
            except NotFoundError:
                store.add(doc)

            # Sync links if defined in frontmatter
            raw_links = fm.get("links")
            if raw_links:
                parsed_links = _coerce_links(raw_links)
                for lnk in parsed_links:
                    try:
                        store.link(doc.id, lnk["to"], rel=lnk.get("rel", "relates-to"))
                    except Exception:
                        pass

            return None
        except Exception as e:
            return f"{type(e).__name__}: {e}"

    def run(self, interval_seconds: float = 1.0, max_iterations: Optional[int] = None) -> None:
        """Run the watcher loop continuously."""
        self._running = True
        logger.info("Starting watcher for vault %r on %s", self.vault_name, self.watch_dir)
        iterations = 0
        while self._running:
            try:
                res = self.scan_once()
                total_changes = len(res["created"]) + len(res["updated"]) + len(res["deleted"])
                if total_changes > 0:
                    logger.info("Watcher synced: %d created, %d updated, %d deleted",
                                len(res["created"]), len(res["updated"]), len(res["deleted"]))
            except Exception as e:
                logger.error("Watcher error during scan: %s", e)

            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break

            time.sleep(interval_seconds)

    def stop(self) -> None:
        """Signal the watcher loop to stop."""
        self._running = False
