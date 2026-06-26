"""Vault management for kb-mcp (v0.4).

A *vault* is a named, independent SQLite knowledge base. Each vault lives in
its own subdirectory under ``KB_MCP_HOME`` (default
``~/.local/share/kb-mcp/``) and contains a ``kb.db`` file.

The vault registry (``vaults.json``) tracks known vaults and the current
active vault. Environment variable ``KB_MCP_VAULT`` overrides the current
vault at runtime.

Migration from v0.3: if ``vaults.json`` does not exist but
``KB_MCP_HOME/kb.db`` does, the first access auto-creates the registry and
registers the existing database as the ``default`` vault.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class VaultError(Exception):
    """Base exception for vault operations."""


class VaultNotFoundError(VaultError):
    """Raised when a named vault does not exist."""


class VaultAlreadyExistsError(VaultError):
    """Raised when creating a vault whose name already exists."""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class VaultInfo:
    """Serialisable metadata for a single vault."""
    name: str
    path: str  # relative to KB_MCP_HOME
    description: str = ""


# ---------------------------------------------------------------------------
# VaultManager
# ---------------------------------------------------------------------------


_DEFAULT_VAULT_NAME = "default"
_VAULTS_JSON = "vaults.json"


def get_kb_home() -> Path:
    """Return the KB root directory.

    Order:
    1. ``KB_MCP_HOME`` env var, if set.
    2. ``~/.local/share/kb-mcp/`` (XDG-style, all platforms).
    """
    env = os.environ.get("KB_MCP_HOME")
    if env:
        return Path(env)
    return Path.home() / ".local" / "share" / "kb-mcp"


def get_current_vault_name() -> str:
    """Return the active vault name from ``KB_MCP_VAULT`` or default."""
    return os.environ.get("KB_MCP_VAULT", _DEFAULT_VAULT_NAME)


class VaultManager:
    """Manage named knowledge-base vaults.

    Usage::

        mgr = VaultManager()
        mgr.list_vaults()       # [VaultInfo(name='default', ...), ...]
        mgr.create("project-x") # creates subdirectory + registers
        mgr.switch("project-x") # sets current in vaults.json
        mgr.resolve_path()      # full path to current vault's kb.db
    """

    def __init__(self, kb_home: Path | str | None = None) -> None:
        self._kb_home = Path(kb_home) if kb_home else get_kb_home()
        self._registry_path = self._kb_home / _VAULTS_JSON
        self._ensure_registry()

    # ---- properties -----------------------------------------------------

    @property
    def kb_home(self) -> Path:
        return self._kb_home

    # ---- registry I/O ---------------------------------------------------

    def _read_registry(self) -> dict[str, Any]:
        if not self._registry_path.exists():
            return {"current": _DEFAULT_VAULT_NAME, "vaults": []}
        return json.loads(self._registry_path.read_text(encoding="utf-8"))

    def _write_registry(self, data: dict[str, Any]) -> None:
        self._registry_path.parent.mkdir(parents=True, exist_ok=True)
        self._registry_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _ensure_registry(self) -> None:
        """Create vaults.json if missing, migrating any existing kb.db.

        Always ensures at least a ``default`` vault exists.
        """
        if self._registry_path.exists():
            return
        legacy_db = self._kb_home / "kb.db"
        default_dir = self._kb_home / _DEFAULT_VAULT_NAME
        default_dir.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {
            "current": _DEFAULT_VAULT_NAME,
            "vaults": [],
        }
        if legacy_db.exists():
            # Migrate: register the existing kb.db as the default vault
            target = default_dir / "kb.db"
            if not target.exists():
                shutil.move(str(legacy_db), str(target))
        data["vaults"].append({
            "name": _DEFAULT_VAULT_NAME,
            "path": _DEFAULT_VAULT_NAME,
            "description": "Default vault",
        })
        self._write_registry(data)

    # ---- vault CRUD -----------------------------------------------------

    def list_vaults(self) -> list[VaultInfo]:
        """Return metadata for every registered vault."""
        data = self._read_registry()
        return [
            VaultInfo(**v) for v in data.get("vaults", [])
        ]

    def get_current(self) -> str:
        """Return the current active vault name."""
        data = self._read_registry()
        return data.get("current", _DEFAULT_VAULT_NAME)

    def create(
        self,
        name: str,
        description: str = "",
    ) -> VaultInfo:
        """Create a new vault with the given name.

        Creates the vault subdirectory and registers it in vaults.json.
        Does NOT create the SQLite database (that happens lazily on first
        access via SqliteStore).

        Raises:
            VaultAlreadyExistsError: if the name is already registered.
        """
        if not name or "/" in name or "\\" in name:
            raise VaultError(f"invalid vault name: {name!r}")
        data = self._read_registry()
        existing = {v["name"] for v in data["vaults"]}
        if name in existing:
            raise VaultAlreadyExistsError(f"vault {name!r} already exists")
        vault_dir = self._kb_home / name
        vault_dir.mkdir(parents=True, exist_ok=True)
        info = {"name": name, "path": name, "description": description}
        data["vaults"].append(info)
        self._write_registry(data)
        return VaultInfo(**info)

    def switch(self, name: str) -> None:
        """Set the current active vault.

        Raises:
            VaultNotFoundError: if the vault is not registered.
        """
        data = self._read_registry()
        names = {v["name"] for v in data["vaults"]}
        if name not in names:
            raise VaultNotFoundError(f"vault {name!r} not found")
        data["current"] = name
        self._write_registry(data)

    def rename(self, old_name: str, new_name: str) -> None:
        """Rename a vault (both registry entry and directory).

        Raises:
            VaultNotFoundError: if ``old_name`` does not exist.
            VaultAlreadyExistsError: if ``new_name`` is already taken.
        """
        if not new_name or "/" in new_name or "\\" in new_name:
            raise VaultError(f"invalid vault name: {new_name!r}")
        data = self._read_registry()
        names = {v["name"] for v in data["vaults"]}
        if old_name not in names:
            raise VaultNotFoundError(f"vault {old_name!r} not found")
        if new_name in names:
            raise VaultAlreadyExistsError(f"vault {new_name!r} already exists")

        old_dir = self._kb_home / old_name
        new_dir = self._kb_home / new_name
        if old_dir.exists():
            old_dir.rename(new_dir)

        for v in data["vaults"]:
            if v["name"] == old_name:
                v["name"] = new_name
                v["path"] = new_name
        if data.get("current") == old_name:
            data["current"] = new_name
        self._write_registry(data)

    def remove(self, name: str, *, delete_files: bool = False) -> None:
        """Remove a vault from the registry.

        Args:
            name: Vault name.
            delete_files: If True, also delete the vault directory and
                all its contents. Default False (registry-only removal).

        Raises:
            VaultNotFoundError: if the vault is not registered.
            VaultError: if trying to remove the last vault.
        """
        data = self._read_registry()
        vaults = data["vaults"]
        idx = next((i for i, v in enumerate(vaults) if v["name"] == name), None)
        if idx is None:
            raise VaultNotFoundError(f"vault {name!r} not found")
        if len(vaults) == 1:
            raise VaultError("cannot remove the last vault")
        vaults.pop(idx)
        if data.get("current") == name:
            data["current"] = vaults[0]["name"]
        self._write_registry(data)
        if delete_files:
            vault_dir = self._kb_home / name
            if vault_dir.exists():
                shutil.rmtree(vault_dir)

    def info(self, name: str) -> VaultInfo:
        """Return metadata for a single vault.

        Raises:
            VaultNotFoundError: if the vault is not registered.
        """
        data = self._read_registry()
        for v in data["vaults"]:
            if v["name"] == name:
                return VaultInfo(**v)
        raise VaultNotFoundError(f"vault {name!r} not found")

    # ---- path resolution ------------------------------------------------

    def resolve_path(self, name: str | None = None) -> Path:
        """Return the full path to a vault's ``kb.db``.

        If ``name`` is None, uses the current active vault.
        """
        if name is None:
            name = self.get_current()
        data = self._read_registry()
        for v in data["vaults"]:
            if v["name"] == name:
                return self._kb_home / v["path"] / "kb.db"
        raise VaultNotFoundError(f"vault {name!r} not found")

    def vault_dir(self, name: str | None = None) -> Path:
        """Return the vault's directory path (parent of ``kb.db``)."""
        return self.resolve_path(name).parent

    def md_dir(self, name: str | None = None) -> Path:
        """Return the ``md/`` sync directory inside the vault."""
        return self.vault_dir(name) / "md"

    # ---- Git sync -------------------------------------------------------

    def _sync_dir(self, name: str | None = None) -> Path:
        """Return the git sync directory for a vault.

        Checks vaults.json for an explicit ``sync_dir``; falls back to
        the vault's own ``md/`` directory.
        """
        data = self._read_registry()
        for v in data["vaults"]:
            if v["name"] == (name or self.get_current()):
                sync = v.get("sync_dir")
                if sync:
                    return Path(sync) / "md"
                break
        return self.md_dir(name)

    def init_git(self, name: str | None = None, sync_dir: Path | str | None = None) -> str:
        """Initialise a Git repository for the vault's Markdown export.

        By default, creates the repo inside the vault directory (``md/``
        subdirectory). Pass ``sync_dir`` to point at an existing git clone
        — the vault's ``md/`` directory will be created there, and the
        location is saved in vaults.json so subsequent sync commands reuse it.

        Creates ``.gitignore`` and an empty ``md/`` directory. Returns the
        git command output.
        """
        import subprocess

        vdir = self.vault_dir(name)
        if sync_dir is None:
            mdir = self.md_dir(name)
        else:
            sync_dir = Path(sync_dir).resolve()
            # Save sync_dir in vaults.json
            data = self._read_registry()
            vault_name = name or self.get_current()
            for v in data["vaults"]:
                if v["name"] == vault_name:
                    v["sync_dir"] = str(sync_dir)
                    break
            self._write_registry(data)
            mdir = sync_dir / "md"
        mdir.mkdir(parents=True, exist_ok=True)
        # Placeholder so git tracks the md/ directory
        placeholder = mdir / ".gitkeep"
        placeholder.write_text("")

        # .gitignore — in the git root (sync_dir or vault dir)
        gitignore_root = sync_dir if sync_dir else vdir
        gitignore = gitignore_root / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(
                "# kb-mcp vault sync\n"
                "kb.db\n"
                "*.db-journal\n"
                "*.db-wal\n"
                "*.db-shm\n"
                "__pycache__/\n"
                ".venv/\n"
            )

        # git init — in the sync root (sync_dir itself, not md/)
        git_cwd = str(sync_dir) if sync_dir else str(vdir)
        result = subprocess.run(
            ["git", "init"],
            cwd=git_cwd,
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise VaultError(f"git init failed: {result.stderr.strip()}")
        return result.stdout.strip()

    def commit(
        self,
        message: str,
        name: str | None = None,
    ) -> str:
        """Export the vault to Markdown, then git add + git commit.

        Returns the git commit output.
        """
        import subprocess

        from kb_mcp_lite.md_io import export_dir as _export_dir
        from kb_mcp_lite.store.sqlite import SqliteStore

        sync_root = self._sync_dir(name)
        mdir = self.md_dir(name)  # fallback if sync_dir not set
        git_dir = sync_root.parent if sync_root != self.md_dir(name) else self.vault_dir(name)
        export_target = sync_root if sync_root != self.md_dir(name) else mdir

        # Ensure git repo exists
        if not (git_dir / ".git").exists():
            raise VaultError("vault not initialised for git; run `kb vault init-git` first")

        # Export to md/
        store = SqliteStore(self.resolve_path(name))
        try:
            _export_dir(store, export_target, force=True)
        finally:
            store.close()

        # git add + commit
        result = subprocess.run(
            ["git", "add", "-A"],
            cwd=str(git_dir),
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise VaultError(f"git add failed: {result.stderr.strip()}")

        result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=str(git_dir),
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            if "nothing to commit" in result.stdout or "nothing to commit" in result.stderr:
                return "nothing to commit"
            raise VaultError(f"git commit failed: {result.stderr.strip()}")
        return result.stdout.strip()

    def push(
        self,
        remote: str = "origin",
        branch: str = "main",
        name: str | None = None,
    ) -> str:
        """Git push the vault's Markdown export.

        Returns the git output.
        """
        import subprocess

        sync_root = self._sync_dir(name)
        git_dir = sync_root.parent if sync_root != self.md_dir(name) else self.vault_dir(name)
        result = subprocess.run(
            ["git", "push", remote, branch],
            cwd=str(git_dir),
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise VaultError(f"git push failed: {result.stderr.strip()}")
        return result.stdout.strip()

    def pull(
        self,
        remote: str = "origin",
        branch: str = "main",
        name: str | None = None,
    ) -> str:
        """Git pull and import Markdown into the vault.

        Returns the git + import summary.
        """
        import subprocess

        from kb_mcp_lite.md_io import import_dir as _import_dir
        from kb_mcp_lite.store.sqlite import SqliteStore

        sync_root = self._sync_dir(name)
        git_dir = sync_root.parent if sync_root != self.md_dir(name) else self.vault_dir(name)
        import_target = sync_root if sync_root != self.md_dir(name) else self.md_dir(name)

        if not (git_dir / ".git").exists():
            raise VaultError("vault not initialised for git; run `kb vault init-git` first")

        # git pull
        result = subprocess.run(
            ["git", "pull", remote, branch],
            cwd=str(git_dir),
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise VaultError(f"git pull failed: {result.stderr.strip()}")
        pull_output = result.stdout.strip()

        # Import the Markdown files
        if import_target.exists():
            store = SqliteStore(self.resolve_path(name))
            try:
                report = _import_dir(store, import_target)
            finally:
                store.close()
            import_summary = f"imported {report.inserted + report.updated} docs ({report.skipped} skipped)"
        else:
            import_summary = "no md/ directory to import"

        return f"{pull_output}\n{import_summary}"


__all__ = [
    "VaultManager",
    "VaultInfo",
    "VaultError",
    "VaultNotFoundError",
    "VaultAlreadyExistsError",
    "get_kb_home",
    "get_current_vault_name",
]
