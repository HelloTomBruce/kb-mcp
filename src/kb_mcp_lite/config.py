"""kb-mcp configuration file (XDG-style).

Config file path: ``~/.config/kb-mcp/config.yaml``
Can be overridden via ``KB_MCP_CONFIG`` env var.

Structure:

.. code-block:: yaml

    # ~/.config/kb-mcp/config.yaml

    # Embedding service (optional)
    embedding:
      url: "http://localhost:11434/v1"
      model: "bge-m3"
      # api_key: "${OPENAI_API_KEY}"

    # Data root directory (optional, default ~/.local/share/kb-mcp/)
    data_dir: "~/.local/share/kb-mcp"
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml

_CONFIG_ENV = "KB_MCP_CONFIG"
_CONFIG_REL = ".config/kb-mcp/config.yaml"


def config_path() -> Path:
    """Return the config file path, honouring ``KB_MCP_CONFIG`` env var."""
    env = os.environ.get(_CONFIG_ENV)
    if env:
        return Path(env)
    return Path.home() / _CONFIG_REL


def load_config() -> dict[str, Any]:
    """Load the kb-mcp config file as a dict. Returns ``{}`` if missing."""
    path = config_path()
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def get_data_dir() -> Path:
    """Return the KB data directory from config or default.

    Priority:
    1. ``KB_MCP_HOME`` env var
    2. Config file ``data_dir`` value
    3. ``~/.local/share/kb-mcp/`` (XDG default)
    """
    env = os.environ.get("KB_MCP_HOME")
    if env:
        return Path(env)
    cfg = load_config()
    raw = cfg.get("data_dir")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".local" / "share" / "kb-mcp"


def get_embedding_block() -> dict[str, Any] | None:
    """Extract the ``embedding`` block from kb-mcp config.

    Returns ``None`` if the config file is missing or has no embedding key.
    The block is searched under ``embedding`` (kb-mcp native) and
    ``auxiliary.embedding`` (Hermes compatibility).
    """
    cfg = load_config()
    # kb-mcp native: top-level "embedding" key
    emb = cfg.get("embedding")
    if isinstance(emb, dict):
        return emb
    # Hermes compatibility: "auxiliary.embedding" key
    aux = cfg.get("auxiliary")
    if isinstance(aux, dict):
        emb = aux.get("embedding")
        if isinstance(emb, dict):
            return emb
    return None


def get_embedding_url() -> str | None:
    """Return the embedding service URL, if configured."""
    block = get_embedding_block()
    if block is None:
        return None
    return block.get("url") or block.get("base_url")


def get_embedding_base_url() -> str | None:
    """Alias for :func:`get_embedding_url`."""
    return get_embedding_url()


def get_embedding_model() -> str | None:
    """Return the embedding model name, if configured."""
    block = get_embedding_block()
    if block is None:
        return None
    return block.get("model")


def get_embedding_api_key() -> str | None:
    """Return the embedding API key, if configured."""
    block = get_embedding_block()
    if block is None:
        return None
    return block.get("api_key")


# ---- Config template -----------------------------------------------------

TEMPLATE = """# kb-mcp configuration
# https://github.com/HelloTomBruce/kb-mcp-lite

# Embedding service (optional — without it only lexical/fuzzy search works)
# Supports any OpenAI-compatible /v1/embeddings endpoint.
# embedding:
#   url: "http://localhost:11434/v1"     # e.g. Ollama
#   model: "bge-m3"
#   timeout: 120                         # seconds (Ollama cold-start may need >30)
#   # api_key: "${OPENAI_API_KEY}"       # env var expansion supported

# Data root directory (optional, default ~/.local/share/kb-mcp/)
# data_dir: "~/.local/share/kb-mcp"
"""


def ensure_config() -> Path:
    """Create the config file with a template if it doesn't exist.

    Returns the config path.
    """
    path = config_path()
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE, encoding="utf-8")
    return path


__all__ = [
    "config_path",
    "load_config",
    "get_data_dir",
    "get_embedding_block",
    "get_embedding_url",
    "get_embedding_model",
    "get_embedding_api_key",
    "ensure_config",
    "TEMPLATE",
]
