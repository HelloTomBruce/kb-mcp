"""Tests for kb-mcp config loading and helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from kb_mcp_lite.config import (
    config_path,
    ensure_config,
    get_data_dir,
    get_embedding_api_key,
    get_embedding_block,
    get_embedding_model,
    get_embedding_url,
    load_config,
)


def test_load_config_missing_file() -> None:
    """load_config returns {} when config file doesn't exist."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("KB_MCP_CONFIG", "/nonexistent/path/config.yaml")
        result = load_config()
        assert result == {}


def test_ensure_config_creates_file(tmp_path: Path) -> None:
    """ensure_config creates config file with template content."""
    cfg_path = tmp_path / "config.yaml"
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("KB_MCP_CONFIG", str(cfg_path))
        result = ensure_config()
        assert result == cfg_path
        assert cfg_path.exists()
        content = cfg_path.read_text(encoding="utf-8")
        assert "kb-mcp configuration" in content


def test_ensure_config_idempotent(tmp_path: Path) -> None:
    """ensure_config returns existing path without overwriting."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("custom content")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("KB_MCP_CONFIG", str(cfg_path))
        result = ensure_config()
        assert result == cfg_path
        assert cfg_path.read_text() == "custom content"


def test_get_data_dir_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """get_data_dir uses KB_MCP_HOME env var when set."""
    monkeypatch.setenv("KB_MCP_HOME", str(tmp_path))
    result = get_data_dir()
    assert result == tmp_path


def test_get_data_dir_from_config(tmp_path: Path) -> None:
    """get_data_dir reads data_dir from config file."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("data_dir: /custom/data/dir\n")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("KB_MCP_CONFIG", str(cfg_path))
        mp.delenv("KB_MCP_HOME", raising=False)
        result = get_data_dir()
        assert str(result) == "/custom/data/dir"


def test_get_embedding_block_from_config(tmp_path: Path) -> None:
    """get_embedding_block reads the embedding section."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("""
embedding:
  url: "https://api.example.com/v1"
  model: "test-model"
  api_key: "sk-test123"
""")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("KB_MCP_CONFIG", str(cfg_path))
        block = get_embedding_block()
        assert block is not None
        assert block["url"] == "https://api.example.com/v1"
        assert block["model"] == "test-model"

        url = get_embedding_url()
        assert url == "https://api.example.com/v1"

        model = get_embedding_model()
        assert model == "test-model"

        api_key = get_embedding_api_key()
        assert api_key == "sk-test123"


def test_get_embedding_block_hermes_compat(tmp_path: Path) -> None:
    """get_embedding_block falls back to auxiliary.embedding."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("""
auxiliary:
  embedding:
    url: "https://hermes.example.com/v1"
""")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("KB_MCP_CONFIG", str(cfg_path))
        block = get_embedding_block()
        assert block is not None
        assert block["url"] == "https://hermes.example.com/v1"


def test_get_embedding_url_from_base_url(tmp_path: Path) -> None:
    """get_embedding_url returns base_url if url not set."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("""
embedding:
  base_url: "https://base.example.com/v1"
""")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("KB_MCP_CONFIG", str(cfg_path))
        url = get_embedding_url()
        assert url == "https://base.example.com/v1"


def test_get_embedding_block_none_when_missing(tmp_path: Path) -> None:
    """get_embedding_block returns None when config is missing."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("KB_MCP_CONFIG", str(tmp_path / "nonexistent.yaml"))
        block = get_embedding_block()
        assert block is None


def test_config_path_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """config_path honours KB_MCP_CONFIG env var."""
    custom = tmp_path / "custom-config.yaml"
    monkeypatch.setenv("KB_MCP_CONFIG", str(custom))
    assert config_path() == custom
