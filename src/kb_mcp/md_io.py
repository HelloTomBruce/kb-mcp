"""Markdown I/O: parse frontmatter, render documents, bulk import/export.

This module is the bridge between the on-disk Markdown vault and the
:class:`kb_mcp.store.Store` backend. It only imports from
:mod:`kb_mcp.schema` and :mod:`kb_mcp.store` (the Protocol); it never
touches a concrete backend, which keeps the CLI, MCP server, and
tests decoupled from SQLite.

Public API (defined in :ref:`docs/architecture.md § 4.3 <architecture>`):

.. code-block:: python

    def parse_frontmatter(text: str) -> tuple[Frontmatter, str]: ...
    def render_document(doc: Document) -> str: ...
    def import_dir(store: Store, dir: Path, *, dry_run: bool = False) -> ImportReport: ...
    def export_dir(store: Store, dir: Path, *, force: bool = False) -> int: ...

NFR-S-3 path-traversal guard: any resolved path that escapes the given
directory raises :class:`kb_mcp.schema.ValidationError` with a clear
message.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

import frontmatter

from kb_mcp.schema import (
    Document,
    ImportReport,
    ValidationError,
    make_id,
)

if TYPE_CHECKING:
    # The Store Protocol lives in ``kb_mcp.store`` (the Protocol
    # module). The Wave 0 directory layout puts both ``store.py`` (the
    # Protocol) and ``store/`` (the implementation package) at the same
    # level; Python's import machinery picks the package, shadowing the
    # Protocol module. We only need the Protocol for static type
    # checking — runtime code duck-types against the Protocol — so the
    # import is guarded with TYPE_CHECKING and annotations stay as
    # strings (PEP 563). See deviations_from_architecture.md.
    from kb_mcp.store import Store


# ---------------------------------------------------------------------------
# Frontmatter TypedDict
# ---------------------------------------------------------------------------


class Frontmatter(TypedDict, total=False):
    """Recognised subset of YAML frontmatter keys.

    The TypedDict is ``total=False`` because every key is optional at
    parse time — a file may legitimately have none of them (e.g. a
    Markdown body with no frontmatter block). Unknown keys are passed
    through on the returned dict: :class:`TypedDict` describes only
    the *statically known* shape, not a runtime constraint.
    """

    type: str
    title: str
    tags: list[str]
    source: str
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------


def parse_frontmatter(text: str) -> tuple[Frontmatter, str]:
    """Split YAML frontmatter from Markdown body.

    Args:
        text: Full file contents.

    Returns:
        A ``(frontmatter_dict, body)`` tuple. The frontmatter dict
        preserves every key found in the YAML block (unknown keys are
        passed through). The body is the Markdown content after the
        closing ``---`` line, or the entire input if no frontmatter
        block was present.

    Raises:
        ValueError: if the YAML frontmatter block is malformed. This
            propagates from :mod:`python-frontmatter`; callers in the
            import path catch and report it per-file.
    """
    post = frontmatter.loads(text)
    # Materialise as a plain dict so callers don't see attribute-style
    # surprises (frontmatter.Post supports both, but a plain dict is
    # the documented shape of the TypedDict).
    fm: Frontmatter = dict(post.metadata)  # type: ignore[assignment]
    return fm, post.content


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_document(doc: Document) -> str:
    """Render a :class:`Document` to its stable on-disk Markdown form.

    The output has a YAML frontmatter block (keys sorted alphabetically
    by :func:`frontmatter.dumps` for determinism) followed by a blank
    line and the body. Round-trippable via :func:`parse_frontmatter`
    plus :func:`import_dir`.

    The body is emitted **verbatim** — Markdown is never HTML-converted
    here. Callers wanting HTML should run their own renderer (e.g.
    ``markdown-it-py``) downstream.
    """
    fm: dict[str, Any] = {
        "type": doc.type,
        "title": doc.title,
        "tags": list(doc.tags),
    }
    if doc.source is not None:
        fm["source"] = doc.source
    if doc.created_at is not None:
        fm["created_at"] = doc.created_at.isoformat()
    if doc.updated_at is not None:
        fm["updated_at"] = doc.updated_at.isoformat()

    post = frontmatter.Post(doc.body or "", **fm)
    return frontmatter.dumps(post)


# ---------------------------------------------------------------------------
# Document construction from parsed frontmatter
# ---------------------------------------------------------------------------


def _coerce_tags(value: Any) -> list[str]:
    """Best-effort coercion of the ``tags`` frontmatter value to ``list[str]``.

    Accepts a list (returned as-is with non-string entries stringified)
    or a single string (wrapped in a one-element list). Anything else
    yields an empty list.
    """
    if isinstance(value, list):
        return [str(t) for t in value]
    if isinstance(value, str):
        return [value] if value else []
    return []


def _parse_iso_dt(value: Any) -> datetime:
    """Parse an ISO-8601 string into a timezone-aware datetime.

    Accepts a ``datetime`` (returned unchanged) or a string. Bare
    ``Z`` suffixes and naive datetimes are normalised to UTC so the
    Document model sees a consistent shape.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    s = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as e:
        raise ValidationError(f"invalid ISO-8601 datetime {value!r}: {e}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def doc_from_frontmatter(
    fm: Frontmatter, body: str, source: str | None = None
) -> Document:
    """Build a :class:`Document` from parsed frontmatter + body.

    Public helper so callers (e.g. tests) can reuse the conversion
    logic. Required fields: ``type`` and ``title``. Optional fields:
    ``tags``, ``created_at``, ``updated_at``. The ``source`` argument
    overrides whatever is in the frontmatter (callers from
    :func:`import_dir` always pass the file's relative path).

    Raises:
        ValidationError: if required fields are missing or have an
            invalid type / datetime format.
    """
    type_ = fm.get("type")
    title = fm.get("title")
    if not type_:
        raise ValidationError("frontmatter missing required field 'type'")
    if not isinstance(type_, str) or not type_.strip():
        raise ValidationError(f"frontmatter 'type' must be a non-empty string (got {type_!r})")
    if not title:
        raise ValidationError("frontmatter missing required field 'title'")
    if not isinstance(title, str) or not title.strip():
        raise ValidationError(f"frontmatter 'title' must be a non-empty string (got {title!r})")

    now = datetime.now(timezone.utc)
    created_at_raw = fm.get("created_at")
    updated_at_raw = fm.get("updated_at")

    return Document(
        id=make_id(type_, title),
        type=type_,
        title=title,
        body=body or "",
        tags=_coerce_tags(fm.get("tags", [])),
        source=source,
        created_at=_parse_iso_dt(created_at_raw) if created_at_raw else now,
        updated_at=_parse_iso_dt(updated_at_raw) if updated_at_raw else now,
    )


# ---------------------------------------------------------------------------
# Path-traversal guard
# ---------------------------------------------------------------------------


def _ensure_within(base: Path, candidate: Path, *, what: str) -> Path:
    """Resolve ``candidate`` against ``base`` and verify it stays inside.

    Returns the resolved :class:`Path`. Raises
    :class:`ValidationError` if the resolved location escapes
    ``base`` (NFR-S-3).
    """
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (base / candidate).resolve()
    try:
        resolved.relative_to(base)
    except ValueError:
        raise ValidationError(
            f"{what} escapes base directory: {candidate!r} "
            f"resolves to {resolved!r}, outside {base!r}"
        )
    return resolved


# ---------------------------------------------------------------------------
# import_dir
# ---------------------------------------------------------------------------


def import_dir(
    store: Store, dir: Path, *, dry_run: bool = False
) -> ImportReport:
    """Walk ``dir`` recursively, parse ``.md`` files, insert/update by source.

    Hidden files, hidden directories, and non-``.md`` files are
    skipped. Each parsed :class:`Document` is given a ``source``
    attribute set to the file's path relative to ``dir``. The store's
    :meth:`Store.import_many` handles source-based idempotent
    re-import (existing documents with the same ``source`` are
    updated, not duplicated).

    NFR-S-3: any file whose resolved path escapes ``dir`` is rejected
    with :class:`ValidationError` recorded in the returned report.

    Args:
        store: A backend implementing the :class:`Store` Protocol.
        dir: Root directory of the vault to import.
        dry_run: If True, parse and validate every file but do not
            write to ``store``. The returned report's
            ``inserted``/``updated`` counts are zero; ``errors``
            contains parse-time failures.

    Returns:
        An :class:`ImportReport` aggregating per-file outcomes. Parse
        errors are listed in ``errors``; successfully parsed files
        contribute to ``inserted``/``updated`` via the store.
    """
    base = dir.resolve()
    if not base.is_dir():
        raise ValidationError(f"not a directory: {dir!r}")

    docs: list[Document] = []
    errors: list[str] = []

    for root, dirs, files in os.walk(base):
        # Skip hidden directories in-place so walk doesn't descend into them.
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            if name.startswith("."):
                continue
            if not name.endswith(".md"):
                continue
            path = Path(root) / name
            try:
                # NFR-S-3: resolve (canonicalises symlinks) and verify the
                # file remains inside ``base``.
                resolved = path.resolve()
                try:
                    resolved.relative_to(base)
                except ValueError:
                    errors.append(
                        f"{path}: path traversal blocked "
                        f"(resolves to {resolved!r}, outside {base!r})"
                    )
                    continue

                text = path.read_text(encoding="utf-8")
                fm, body = parse_frontmatter(text)
                rel_source = str(path.relative_to(base))
                doc = doc_from_frontmatter(fm, body, source=rel_source)
                docs.append(doc)
            except ValidationError as e:
                errors.append(f"{path}: {e}")
            except Exception as e:  # noqa: BLE001 — surface any parse error per-file
                errors.append(f"{path}: {type(e).__name__}: {e}")

    if dry_run or not docs:
        return ImportReport(
            inserted=0,
            updated=0,
            skipped=len(docs) if dry_run else 0,
            errors=list(errors),
        )

    # Delegate to the store. import_many implements source-based dedup
    # ("update by source path" per architecture § 4.3).
    report = store.import_many(docs)
    return ImportReport(
        inserted=report.inserted,
        updated=report.updated,
        skipped=report.skipped,
        errors=list(errors) + list(report.errors),
    )


# ---------------------------------------------------------------------------
# export_dir
# ---------------------------------------------------------------------------


def export_dir(
    store: Store, dir: Path, *, force: bool = False
) -> int:
    """Write one ``.md`` per document under ``dir``.

    Filename is the last segment of the document's id (``proj/kb-mcp``
    becomes ``kb-mcp.md``). When multiple documents map to the same
    slug within a single export, a numeric suffix (``-2``, ``-3``, …)
    is appended. Pre-existing files are never overwritten unless
    ``force=True``.

    After a successful write, the document's ``source`` field is
    updated in the store to the new file's path (relative to
    ``dir``). This keeps the import-export round trip idempotent:
    re-importing the exported directory matches documents by source.

    NFR-S-3: every ``doc.source`` is checked up front; any whose
    resolved path escapes ``dir`` raises :class:`ValidationError`
    before any files are written.

    Args:
        store: A backend implementing the :class:`Store` Protocol.
        dir: Destination directory. Created (with parents) if missing.
        force: Overwrite existing files. Default False.

    Returns:
        Count of files written.
    """
    base = dir.resolve()
    base.mkdir(parents=True, exist_ok=True)

    docs = sorted(store.export_all(), key=lambda d: d.id)

    # NFR-S-3: validate every doc's source up front. Bail before any
    # writes if any source escapes the destination.
    for doc in docs:
        if doc.source:
            if os.path.isabs(doc.source):
                raise ValidationError(
                    f"doc {doc.id!r} has absolute source path "
                    f"{doc.source!r} (refusing to export)"
                )
            try:
                (base / doc.source).resolve().relative_to(base)
            except ValueError:
                raise ValidationError(
                    f"doc {doc.id!r} source {doc.source!r} escapes "
                    f"destination {base!r}"
                )

    used_slugs: set[str] = set()
    written = 0

    for doc in docs:
        # Slug = last id segment. Fall back to "untitled" for the empty case.
        slug = doc.id.rsplit("/", 1)[-1] or "untitled"

        # In-run collision: append -2, -3, ... until unique among
        # the filenames we've already claimed in this export.
        candidate = base / f"{slug}.md"
        n = 2
        while candidate.name in used_slugs:
            candidate = base / f"{slug}-{n}.md"
            n += 1
            if n > 10_000:
                raise ValidationError(
                    f"too many filename collisions for slug {slug!r}"
                )
        used_slugs.add(candidate.name)

        # Refuse to clobber a pre-existing file unless force=True.
        if candidate.exists() and not force:
            raise ValidationError(
                f"refusing to overwrite existing file {candidate} "
                f"(use force=True to overwrite)"
            )

        candidate.write_text(render_document(doc), encoding="utf-8")
        written += 1

        # Update doc.source in the store so a subsequent import from
        # ``base`` matches by source. Best-effort: if the backend
        # rejects the update (e.g. validation rule), the export still
        # succeeded; just log it as a per-doc warning.
        try:
            rel = candidate.relative_to(base)
            store.update(doc.id, source=str(rel))
        except ValidationError as e:
            # Append as a non-fatal note; the on-disk file is fine.
            # We surface this through a custom side-channel rather
            # than changing the return type.
            import warnings
            warnings.warn(f"could not update source for {doc.id!r}: {e}")

    return written


__all__ = [
    "Frontmatter",
    "parse_frontmatter",
    "render_document",
    "doc_from_frontmatter",
    "import_dir",
    "export_dir",
]
