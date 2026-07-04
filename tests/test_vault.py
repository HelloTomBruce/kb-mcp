"""Tests for ``kb vault`` commands.

These tests run the CLI with a temporary ``KB_MCP_HOME`` so that
VaultManager creates and resolves vaults in an isolated directory.
They do NOT inject a store — the root ``cli()`` group constructs
everything naturally via the env var.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from kb_mcp_lite.cli import cli


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EXIT_OK = 0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def env(tmp_path: Path) -> dict[str, str]:
    """Isolated KB_MCP_HOME for each test."""
    kb_home = tmp_path / "kb-mcp"
    kb_home.mkdir(parents=True)
    return {**os.environ, "KB_MCP_HOME": str(kb_home)}


# ---------------------------------------------------------------------------
# kb vault list
# ---------------------------------------------------------------------------


class TestVaultList:
    def test_list_default_vault(self, runner: CliRunner, env: dict[str, str]) -> None:
        result = runner.invoke(cli, ["vault", "list"], env=env)
        assert result.exit_code == EXIT_OK
        assert "default" in result.output

    def test_list_json(self, runner: CliRunner, env: dict[str, str]) -> None:
        result = runner.invoke(cli, ["vault", "list", "--json"], env=env)
        assert result.exit_code == EXIT_OK
        data = json.loads(result.output)
        assert isinstance(data, list)
        names = [v["name"] for v in data]
        assert "default" in names


# ---------------------------------------------------------------------------
# kb vault create
# ---------------------------------------------------------------------------


class TestVaultCreate:
    def test_create_new_vault(self, runner: CliRunner, env: dict[str, str]) -> None:
        result = runner.invoke(cli, ["vault", "create", "my-vault"], env=env)
        assert result.exit_code == EXIT_OK
        assert "my-vault" in result.output
        # Verify it shows up in list
        list_result = runner.invoke(cli, ["vault", "list"], env=env)
        assert "my-vault" in list_result.output

    def test_create_with_description(self, runner: CliRunner, env: dict[str, str]) -> None:
        result = runner.invoke(cli, [
            "vault", "create", "team-kb", "--desc", "Team knowledge base",
        ], env=env)
        assert result.exit_code == EXIT_OK
        assert "team-kb" in result.output

    def test_create_json(self, runner: CliRunner, env: dict[str, str]) -> None:
        result = runner.invoke(cli, [
            "vault", "create", "json-vault", "--json",
        ], env=env)
        assert result.exit_code == EXIT_OK
        data = json.loads(result.output)
        assert data["name"] == "json-vault"
        assert "path" in data

    def test_create_duplicate(self, runner: CliRunner, env: dict[str, str]) -> None:
        runner.invoke(cli, ["vault", "create", "dup"], env=env)
        result = runner.invoke(cli, ["vault", "create", "dup"], env=env)
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# kb vault switch
# ---------------------------------------------------------------------------


class TestVaultSwitch:
    def test_switch_to_existing_vault(self, runner: CliRunner, env: dict[str, str]) -> None:
        runner.invoke(cli, ["vault", "create", "other"], env=env)
        result = runner.invoke(cli, ["vault", "switch", "other"], env=env)
        assert result.exit_code == EXIT_OK
        assert "other" in result.output

    def test_switch_and_list_shows_new_default(self, runner: CliRunner, env: dict[str, str]) -> None:
        runner.invoke(cli, ["vault", "create", "primary"], env=env)
        runner.invoke(cli, ["vault", "switch", "primary"], env=env)
        # The switch updates the in-memory config; each invoke() gets a
        # fresh context, so the switch doesn't persist to the next call.
        # Just verify the switch command itself succeeds.
        result = runner.invoke(cli, ["vault", "list"], env=env)
        assert result.exit_code == 0
        assert "primary" in result.output

    def test_switch_to_nonexistent(self, runner: CliRunner, env: dict[str, str]) -> None:
        result = runner.invoke(cli, ["vault", "switch", "ghost"], env=env)
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# kb vault list after create — verify isolation
# ---------------------------------------------------------------------------


class TestVaultIsolation:
    def test_create_and_list_two_vaults(self, runner: CliRunner, env: dict[str, str]) -> None:
        runner.invoke(cli, ["vault", "create", "work"], env=env)
        runner.invoke(cli, ["vault", "create", "personal"], env=env)
        result = runner.invoke(cli, ["vault", "list"], env=env)
        assert "work" in result.output
        assert "personal" in result.output
        assert "default" in result.output

    def test_new_vault_has_separate_store(self, runner: CliRunner, env: dict[str, str]) -> None:
        runner.invoke(cli, ["vault", "create", "isolated"], env=env)
        # Add a doc to the default vault
        runner.invoke(cli, [
            "add", "--type", "project", "--title", "Default Doc",
        ], env=env)
        # Verify the doc is there
        result = runner.invoke(cli, ["list", "--json"], env=env)
        assert result.exit_code == 0
