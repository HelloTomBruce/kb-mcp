"""Document models and type registry.

This module is the canonical source for the document schema. Every other
module (``store``, ``md_io``, ``mcp_server``, ``cli``) imports from here.
If you change a field name or a validation rule, you change it here and
propagate — never duplicate.

Built-in types: ``project``, ``decision``, ``lesson``, ``glossary``,
``person``, ``faq``. Users can add custom types via :class:`TypeRegistry`.

Conventions
-----------

- All IDs are **slugs** (``a-z0-9-`` plus ``/`` for grouping). Examples:
  ``proj/kb-mcp``, ``dec/use-sqlite-fts5``, ``lesson/dont-reuse-lastrowid``.
- All timestamps are **ISO-8601 UTC strings** in the SQLite layer
  (``datetime.utcnow().isoformat()``); pydantic models accept
  ``datetime`` and serialise to ISO.
- ``body`` is **Markdown**; the store does not parse it.
- ``tags`` are stored as a JSON array string in SQLite for portability;
  pydantic models expose ``list[str]``.
"""

from __future__ import annotations

import os

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Built-in document types
# ---------------------------------------------------------------------------


class DocumentType(str, Enum):
    """Built-in document types shipped with kb-mcp v0.1.0.

    Custom types are allowed (any non-empty string); this enum is the
    *known-good* set with sensible defaults.
    """

    PROJECT = "project"
    DECISION = "decision"
    LESSON = "lesson"
    GLOSSARY = "glossary"
    PERSON = "person"
    FAQ = "faq"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class KbMcpError(Exception):
    """Base for all kb-mcp exceptions."""


class NotFoundError(KbMcpError):
    """Raised when a document id does not exist."""

    def __init__(self, doc_id: str) -> None:
        super().__init__(f"document not found: {doc_id!r}")
        self.doc_id = doc_id


class DuplicateError(KbMcpError):
    """Raised when adding a document whose (type, title) already exists."""

    def __init__(self, doc_id: str, existing_id: str | None = None) -> None:
        msg = f"document already exists: {doc_id!r}"
        if existing_id and existing_id != doc_id:
            msg += f" (existing id: {existing_id!r})"
        super().__init__(msg)
        self.doc_id = doc_id
        self.existing_id = existing_id


class ValidationError(KbMcpError):
    """Raised when input fails pydantic validation or store invariants."""


class IntegrityError(KbMcpError):
    """Raised when DB integrity check fails (rare; usually bug)."""


# ---------------------------------------------------------------------------
# ID helpers
# ---------------------------------------------------------------------------


_TYPE_PREFIX = {
    DocumentType.PROJECT: "proj",
    DocumentType.DECISION: "dec",
    DocumentType.LESSON: "lesson",
    DocumentType.GLOSSARY: "glossary",
    DocumentType.PERSON: "person",
    DocumentType.FAQ: "faq",
}


def slugify(title: str) -> str:
    """Convert ``title`` to a URL-safe ASCII-first slug.

    Lowercase, replace runs of non-alphanumeric with ``-``, strip
    non-ASCII characters, and trim leading/trailing dashes. Non-ASCII
    characters that cannot be represented in ASCII (e.g. CJK characters)
    are dropped, which keeps IDs compatible with the
    ``^[a-z0-9][a-z0-9/_-]*$`` validation regex.

    >>> slugify("Use SQLite FTS5!")
    'use-sqlite-fts5'
    >>> slugify("kb-mcp 项目")
    'kb-mcp'

    **CJK / non-ASCII titles** (where the ASCII-only result is empty or
    degenerates to a number, e.g. "1. 概述" or "项目概述") previously
    produced a blank slug and collided on every CJK document of the same
    type. As of v0.2.2, when the ASCII-cleaned result is empty, the
    function falls back to ``cjk-<sha1[:8]>`` derived from the original
    title. This is **idempotent** (same title → same fallback slug) and
    **bounded** (always 12 chars + ``cjk-`` prefix).

    >>> slugify("项目概述")
    'cjk-<hash>'
    >>> slugify("1. 概述")
    'cjk-<hash>'   # '1' is degenerate → fallback
    """
    import hashlib
    import re
    import unicodedata

    s = title.strip().lower()
    # Normalize (decomposes accented chars), then drop non-ASCII.
    s_ascii = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s_ascii = re.sub(r"[^a-z0-9]+", "-", s_ascii).strip("-")
    if s_ascii and not s_ascii.replace("-", "").isdigit():
        # Genuine ASCII slug (has at least one alpha char).
        return s_ascii
    # Fallback: empty / pure-digit (likely truncated CJK) → stable hash.
    h = hashlib.sha1(title.encode("utf-8")).hexdigest()[:8]
    return f"cjk-{h}"


def make_id(doc_type: str, title: str) -> str:
    """Return ``<prefix>/<slug>`` for a built-in type, ``<type>/<slug>``
    otherwise.

    The prefix keeps related documents clustered in listings and lets the
    CLI hint at type from the id alone.

    >>> make_id("project", "kb-mcp")
    'proj/kb-mcp'
    >>> make_id("custom-type", "Hello World")
    'custom-type/hello-world'
    """
    try:
        prefix = _TYPE_PREFIX[DocumentType(doc_type)]
    except (ValueError, KeyError):
        prefix = doc_type
    return f"{prefix}/{slugify(title)}"


# ---------------------------------------------------------------------------
# Document model
# ---------------------------------------------------------------------------


class Document(BaseModel):
    """A typed Markdown document in the knowledge base.

    Subclassing is supported for type-specific fields (see ``Project``,
    ``Decision``, etc. below). The base model is sufficient for every
    built-in type at v0.1; subclasses exist to document type-specific
    conventions and to give static type-checkers hints.

    Validation rules:

    - ``id`` matches ``^[a-z0-9][a-z0-9/_-]*$``
    - ``title`` is non-empty after stripping
    - ``type`` is non-empty (any string for custom types)
    - ``tags`` items match ``^[a-z0-9][a-z0-9_-]*$`` (lowercase, no spaces)
    """

    model_config = ConfigDict(frozen=False, str_strip_whitespace=True)

    id: str = Field(
        ..., description="Slug-style id; auto-generated from type+title if omitted on add"
    )
    type: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=512)
    body: str = Field(default="", max_length=1_000_000)  # 1 MB cap
    tags: list[str] = Field(default_factory=list, max_length=64)
    aliases: list[str] = Field(default_factory=list, description="Alternative IDs for this document")
    source: str | None = Field(default=None, description="Origin file path if imported")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    deleted_at: datetime | None = None

    @field_validator("source")
    @classmethod
    def _check_source(cls, v: str | None) -> str | None:
        if v and os.path.isabs(v):
            raise ValueError(
                f"source must be a relative path, got absolute path {v!r}"
            )
        return v

    @field_validator("id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        # Empty id is allowed at the model layer; the store layer is
        # responsible for filling it in via ``make_id(type, title)``.
        # This split lets callers build a Document with just type+title
        # and let the store assign the slug.
        if v == "":
            return v
        import re as _re

        if not _re.match(r"^[a-z0-9][a-z0-9/_-]*$", v):
            raise ValueError(f"id must match ^[a-z0-9][a-z0-9/_-]*$ (got {v!r})")
        return v

    @field_validator("tags")
    @classmethod
    def _check_tags(cls, v: list[str]) -> list[str]:
        import re

        for t in v:
            if not re.match(r"^[a-z0-9][a-z0-9_-]*$", t):
                raise ValueError(f"tag {t!r} must match ^[a-z0-9][a-z0-9_-]*$")
        return v

    @field_validator("created_at", "updated_at", "deleted_at", mode="before")
    @classmethod
    def _parse_dt(cls, v: Any) -> Any:
        if v is None or v == "":
            return None
        if isinstance(v, datetime):
            return v
        if isinstance(v, str):
            # Accept "...Z" suffix as UTC.
            s = v.replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(s)
            except ValueError as e:
                raise ValueError(f"invalid ISO-8601 datetime {v!r}: {e}") from e
        raise ValueError(f"unsupported datetime value: {v!r}")

    # ---- helpers --------------------------------------------------------

    def to_row(self) -> dict[str, Any]:
        """Serialise to a flat dict suitable for SQLite INSERT.

        ``tags`` becomes a JSON string. ``created_at`` / ``updated_at`` /
        ``deleted_at`` become ISO-8601 strings.
        """
        import json

        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "body": self.body,
            "tags": json.dumps(self.tags, ensure_ascii=False),
            "source": self.source,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Document":
        """Inverse of :meth:`to_row`."""
        import json

        data = dict(row)
        tags_raw = data.get("tags") or "[]"
        if isinstance(tags_raw, str):
            data["tags"] = json.loads(tags_raw)
        return cls.model_validate(data)


# ---------------------------------------------------------------------------
# Link model
# ---------------------------------------------------------------------------


class Link(BaseModel):
    """A typed edge between two documents.

    Edges are idempotent: re-inserting the same ``(from_id, to_id, rel)``
    triple is a no-op (same primary key in SQLite).
    """

    model_config = ConfigDict(frozen=True)

    from_id: str
    to_id: str
    rel: str = Field(default="relates-to", min_length=1, max_length=64)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Search result
# ---------------------------------------------------------------------------


class SearchHit(BaseModel):
    """A single search result with a snippet.

    ``score`` is the raw BM25 score returned by SQLite FTS5 (lower = more
    relevant; not normalised). The CLI and MCP server may normalise it
    before exposing to callers; this model preserves the raw value.
    """

    doc: Document
    snippet: str = Field(default="", description="Body excerpt with markers around matched terms")
    score: float = 0.0


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


class ImportReport(BaseModel):
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = Field(default_factory=list)


class DoctorCheck(BaseModel):
    name: str
    ok: bool
    detail: str = ""


class DoctorReport(BaseModel):
    ok: bool
    checks: list[DoctorCheck] = Field(default_factory=list)

    def summary(self) -> str:
        if self.ok:
            return "kb doctor: OK"
        bad = [c for c in self.checks if not c.ok]
        lines = ["kb doctor: FAIL", f"  {len(bad)} check(s) failed:"]
        for c in bad:
            lines.append(f"  - {c.name}: {c.detail}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Type registry (extensibility point)
# ---------------------------------------------------------------------------


class TypeRegistry:
    """Registry of known document types and their default behaviours.

    The six built-in types are pre-registered. Users can register custom
    types to:

    - constrain which fields are allowed on a document,
    - override slug generation,
    - attach a Markdown template.

    For v0.1.0 the registry stores **metadata only** — every document is
    still backed by the same SQLite schema. Field-level constraints are
    enforced at the pydantic layer via subclasses (see ``Project``,
    ``Decision``, …); the registry is the lookup table for which subclass
    to use.
    """

    def __init__(self) -> None:
        self._types: dict[str, type[Document]] = {
            "project": Project,
            "decision": Decision,
            "lesson": Lesson,
            "glossary": Glossary,
            "person": Person,
            "faq": Faq,
        }

    def register(self, type_name: str, model: type[Document]) -> None:
        if not type_name or not type_name.replace("-", "").replace("_", "").isalnum():
            raise ValueError(f"type_name must be alphanumeric/dash/underscore (got {type_name!r})")
        if type_name in self._types:
            raise ValueError(f"type {type_name!r} already registered")
        self._types[type_name] = model

    def model_for(self, type_name: str) -> type[Document]:
        return self._types.get(type_name, Document)

    def known_types(self) -> Iterable[str]:
        return sorted(self._types.keys())

    def validate(self, type_name: str) -> None:
        if not type_name:
            raise ValidationError("type must be non-empty")
        # Any non-empty type string is allowed; this is a no-op for now
        # but is the hook for future stricter enforcement.


# ---------------------------------------------------------------------------
# Per-type subclasses (v0.1: metadata only; no extra fields yet)
# ---------------------------------------------------------------------------


class Project(Document):
    """A project / repo / initiative. Body typically summarises purpose,
    stack, status, owners. Tag convention: ``<lang>``, ``<framework>``,
    ``<domain>``."""

    type: Literal["project"] = "project"


class Decision(Document):
    """An Architecture Decision Record (ADR). Body should follow the
    MADR-style structure: context → decision → consequences."""

    type: Literal["decision"] = "decision"


class Lesson(Document):
    """A post-mortem or lessons-learned entry. Body should describe the
    incident, the root cause, and the prevention rule."""

    type: Literal["lesson"] = "lesson"


class Glossary(Document):
    """A term definition. Body is the definition; canonical form."""

    type: Literal["glossary"] = "glossary"


class Person(Document):
    """A person the agent should recognise. Body is bio + context.
    Tag convention: ``<role>``, ``<team>``."""

    type: Literal["person"] = "person"


class Faq(Document):
    """A frequently asked question. Title is the question; body is the
    answer."""

    type: Literal["faq"] = "faq"  # noqa: F821


# Module-level singleton for convenience
default_registry = TypeRegistry()


__all__ = [
    # types
    "DocumentType",
    "Document",
    "Link",
    "SearchHit",
    "ImportReport",
    "DoctorCheck",
    "DoctorReport",
    # subclasses
    "Project",
    "Decision",
    "Lesson",
    "Glossary",
    "Person",
    "Faq",
    # registry
    "TypeRegistry",
    "default_registry",
    # helpers
    "slugify",
    "make_id",
    # exceptions
    "KbMcpError",
    "NotFoundError",
    "DuplicateError",
    "ValidationError",
    "IntegrityError",
]
