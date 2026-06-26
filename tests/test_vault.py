"""Tests for kb-mcp vault management (v0.4)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from kb_mcp_lite.cli import cli
from kb_mcp_lite.store.sqlite import SqliteStore
from kb_mcp_lite.vault import (
    VaultAlreadyExistsError,
    VaultManager,
    VaultNotFoundError,
)


# ---------------------------------------------------------------------------
# VaultManager unit tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def kb_home(tmp_path: Path) -> Path:
    return tmp_path / "kb-mcp"


@pytest.fixture()
def mgr(kb_home: Path) -> VaultManager:
    return VaultManager(kb_home)


class TestVaultManager:
    """Unit tests for VaultManager."""

    def test_ensure_registry_creates_default(self, mgr: VaultManager) -> None:
        """Fresh VaultManager creates default vault."""
        vaults = mgr.list_vaults()
        assert len(vaults) == 1
        assert vaults[0].name == "default"
        assert vaults[0].description == "Default vault"

    def test_migrate_legacy_db(self, tmp_path: Path) -> None:
        """Legacy kb.db is migrated to default vault on first access."""
        kb_home = tmp_path / "kb-mcp-migrate"
        kb_home.mkdir(parents=True)
        legacy = kb_home / "kb.db"
        legacy.write_text("fake sqlite data")

        mgr = VaultManager(kb_home)
        # Legacy file should be moved
        assert not legacy.exists()
        assert (kb_home / "default" / "kb.db").exists()
        vaults = mgr.list_vaults()
        assert any(v.name == "default" for v in vaults)

    def test_create(self, mgr: VaultManager) -> None:
        """Creating a vault registers it and creates the directory."""
        info = mgr.create("project-x", description="Project X KB")
        assert info.name == "project-x"
        assert info.description == "Project X KB"
        vaults = mgr.list_vaults()
        names = [v.name for v in vaults]
        assert "project-x" in names

    def test_create_duplicate(self, mgr: VaultManager) -> None:
        """Creating a duplicate vault raises."""
        mgr.create("dup")
        with pytest.raises(VaultAlreadyExistsError):
            mgr.create("dup")

    def test_create_invalid_name(self, mgr: VaultManager) -> None:
        """Names with slashes are rejected."""
        with pytest.raises(Exception):
            mgr.create("a/b")

    def test_switch(self, mgr: VaultManager) -> None:
        """Switching vault updates current."""
        mgr.create("v2")
        mgr.switch("v2")
        assert mgr.get_current() == "v2"

    def test_switch_not_found(self, mgr: VaultManager) -> None:
        """Switching to unknown vault raises."""
        with pytest.raises(VaultNotFoundError):
            mgr.switch("nonexistent")

    def test_resolve_path(self, mgr: VaultManager) -> None:
        """resolve_path returns correct path."""
        mgr.create("my-vault")
        path = mgr.resolve_path("my-vault")
        assert path.name == "kb.db"
        assert "my-vault" in str(path)

    def test_resolve_path_current(self, mgr: VaultManager) -> None:
        """resolve_path with no name uses current vault."""
        mgr.create("current-vault")
        mgr.switch("current-vault")
        path = mgr.resolve_path()
        assert "current-vault" in str(path)

    def test_rename(self, mgr: VaultManager) -> None:
        """Renaming updates registry and directory."""
        mgr.create("old-name")
        mgr.rename("old-name", "new-name")
        names = [v.name for v in mgr.list_vaults()]
        assert "old-name" not in names
        assert "new-name" in names
        assert (mgr.kb_home / "new-name").exists()

    def test_remove(self, mgr: VaultManager) -> None:
        """Removing a vault unregisters it."""
        mgr.create("to-remove")
        mgr.remove("to-remove")
        names = [v.name for v in mgr.list_vaults()]
        assert "to-remove" not in names

    def test_remove_last_vault_fails(self, mgr: VaultManager) -> None:
        """Cannot remove the last vault."""
        with pytest.raises(Exception, match="cannot remove the last vault"):
            mgr.remove("default")

    def test_remove_not_found(self, mgr: VaultManager) -> None:
        """Removing unknown vault raises."""
        with pytest.raises(VaultNotFoundError):
            mgr.remove("nonexistent")

    def test_info(self, mgr: VaultManager) -> None:
        """info returns vault metadata."""
        mgr.create("info-vault", description="Info test")
        info = mgr.info("info-vault")
        assert info.name == "info-vault"
        assert info.description == "Info test"

    def test_info_not_found(self, mgr: VaultManager) -> None:
        """info for unknown vault raises."""
        with pytest.raises(VaultNotFoundError):
            mgr.info("nonexistent")


# ---------------------------------------------------------------------------
# CLI vault integration tests
# ---------------------------------------------------------------------------


class TestCliVault:
    """CLI vault commands via Click CliRunner."""

    @pytest.fixture()
    def runner(self) -> CliRunner:
        return CliRunner()

    @pytest.fixture()
    def env(self, tmp_path: Path) -> dict[str, str]:
        kb_home = tmp_path / "kb-mcp"
        kb_home.mkdir(parents=True)
        return {**os.environ, "KB_MCP_HOME": str(kb_home), "KB_MCP_LOG_LEVEL": "ERROR"}

    def test_vault_list(self, runner: CliRunner, env: dict[str, str]) -> None:
        """vault list shows default vault."""
        result = runner.invoke(cli, ["vault", "list"], env=env)
        assert result.exit_code == 0
        assert "default" in result.output

    def test_vault_create_and_list(self, runner: CliRunner, env: dict[str, str]) -> None:
        """Create a vault and verify it appears in list."""
        result = runner.invoke(cli, ["vault", "create", "test-vault", "--desc", "Test"],
                               env=env)
        assert result.exit_code == 0
        assert "Created vault 'test-vault'" in result.output

        result = runner.invoke(cli, ["vault", "list"], env=env)
        assert "test-vault" in result.output

    def test_vault_switch_and_current(self, runner: CliRunner, env: dict[str, str]) -> None:
        """Switch vault and verify current changes."""
        runner.invoke(cli, ["vault", "create", "other"], env=env)
        result = runner.invoke(cli, ["vault", "switch", "other"], env=env)
        assert result.exit_code == 0
        assert "Switched to vault 'other'" in result.output

        result = runner.invoke(cli, ["vault", "current"], env=env)
        assert result.output.strip() == "other"

    def test_vault_info(self, runner: CliRunner, env: dict[str, str]) -> None:
        """vault info shows details."""
        runner.invoke(cli, ["vault", "create", "info-vault"], env=env)
        result = runner.invoke(cli, ["vault", "info", "info-vault"], env=env)
        assert result.exit_code == 0
        assert "info-vault" in result.output
        assert "kb.db" in result.output

    def test_vault_json_output(self, runner: CliRunner, env: dict[str, str]) -> None:
        """All vault commands support --json."""
        result = runner.invoke(cli, ["vault", "list", "--json"], env=env)
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "current" in data
        assert "vaults" in data

    def test_vault_store_isolation(self, runner: CliRunner, env: dict[str, str],
                                   tmp_path: Path) -> None:
        """Documents in one vault don't appear in another."""
        # Create two vaults
        runner.invoke(cli, ["vault", "create", "va", "--desc", "Vault A"], env=env)
        runner.invoke(cli, ["vault", "create", "vb", "--desc", "Vault B"], env=env)

        # Add a doc to Vault A with a unique body
        runner.invoke(cli, ["vault", "switch", "va"], env=env)
        runner.invoke(cli, ["add", "--type", "project", "--title", "VaultA Doc"], env=env)

        # Add a doc to Vault B
        runner.invoke(cli, ["vault", "switch", "vb"], env=env)
        runner.invoke(cli, ["add", "--type", "project", "--title", "VaultB Doc"], env=env)

        # List in Vault A should include A's doc but not B's
        runner.invoke(cli, ["vault", "switch", "va"], env=env)
        result = runner.invoke(cli, ["list", "--json"], env=env)
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        titles = {d["title"] for d in data}
        assert "VaultA Doc" in titles
        assert "VaultB Doc" not in titles

        # List in Vault B should include B's doc but not A's
        runner.invoke(cli, ["vault", "switch", "vb"], env=env)
        result = runner.invoke(cli, ["list", "--json"], env=env)
        assert result.exit_code == 0
        data = json.loads(result.output)
        titles = {d["title"] for d in data}
        assert "VaultB Doc" in titles
        assert "VaultA Doc" not in titles

    def test_vault_rename(self, runner: CliRunner, env: dict[str, str]) -> None:
        """Rename a vault."""
        runner.invoke(cli, ["vault", "create", "oldie"], env=env)
        result = runner.invoke(cli, ["vault", "rename", "oldie", "newbie"], env=env)
        assert result.exit_code == 0
        assert "Renamed vault 'oldie' to 'newbie'" in result.output
        result = runner.invoke(cli, ["vault", "list"], env=env)
        assert "newbie" in result.output
        assert "oldie" not in result.output

    def test_vault_remove(self, runner: CliRunner, env: dict[str, str]) -> None:
        """Remove a vault."""
        runner.invoke(cli, ["vault", "create", "toremove"], env=env)
        result = runner.invoke(cli, ["vault", "remove", "toremove"], env=env)
        assert result.exit_code == 0
        result = runner.invoke(cli, ["vault", "list"], env=env)
        assert "toremove" not in result.output

    def test_vault_switch_not_found(self, runner: CliRunner, env: dict[str, str]) -> None:
        """Switch to nonexistent vault fails."""
        result = runner.invoke(cli, ["vault", "switch", "nonexistent"], env=env)
        assert result.exit_code == 1
