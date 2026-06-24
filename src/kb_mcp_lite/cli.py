"""Click CLI for kb-mcp (Wave 1C).

This module implements the full command surface described in
``docs/cli-reference.md``:

- ``kb init [--force] [--yes] [--json]``
- ``kb add --type TYPE --title TITLE [--tags ...] [--body | --body-file] [--source] [--json]``
- ``kb get ID [--json]``
- ``kb search QUERY [--type] [--tag]... [--limit] [--json]``
- ``kb list [--type] [--tag]... [--limit] [--offset] [--json]``
- ``kb link --from ID --to ID [--rel] [--json]``
- ``kb import DIR [--json] [--dry-run]``
- ``kb export DIR [--json] [--force]``
- ``kb doctor [--json]``
- ``kb serve [--log-level LEVEL]``

Exit codes follow ``cli-reference.md``:

====  =================================================================
0    Success
2    Validation error
3    Not found
4    Conflict (duplicate)
5    Internal error (DB / I/O) — also used for "not implemented" stubs
64   Usage error
====  =================================================================

Store selection
---------------

For v0.1 the CLI uses :class:`~kb_mcp_lite.store.sqlite.SqliteStore`
(SQLite + FTS5). Tests inject their own
``SqliteStore`` via Click's ``obj`` context object, e.g.::

    runner.invoke(cli, ["add", ...], obj={"store": my_store})

Import / export
----------------

``kb import`` walks a directory of ``.md`` files, parses YAML frontmatter,
and upserts each into the store via :func:`kb_mcp_lite.md_io.import_dir`.
``kb export`` writes one Markdown file per document via
:func:`kb_mcp_lite.md_io.export_dir`. See ``docs/architecture.md`` § 4.3 for
the contract.
"""

from __future__ import annotations

import functools
import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, TypeVar

import click
from pydantic import ValidationError as PydanticValidationError

from kb_mcp_lite.schema import (
    Document,
    DuplicateError,
    KbMcpError,
    NotFoundError,
    ValidationError,
    make_id,
)
from kb_mcp_lite.store.sqlite import SqliteStore


# Type helpers ----------------------------------------------------------------

F = TypeVar("F", bound=Callable[..., Any])

# Exit code constants — mirror the cli-reference.md table.
EXIT_OK = 0
EXIT_VALIDATION = 2
EXIT_NOT_FOUND = 3
EXIT_CONFLICT = 4
EXIT_INTERNAL = 5
EXIT_USAGE = 64


# Store factory ---------------------------------------------------------------


def _create_default_store() -> SqliteStore:
    """Return the default :class:`SqliteStore` for production use.

    DB path comes from ``KB_MCP_HOME`` env var (default
    ``~/.local/share/kb-mcp/kb.db``). Parent directory is auto-created.
    """
    home = os.environ.get("KB_MCP_HOME")
    if home:
        db_path = Path(home) / "kb.db"
    else:
        db_path = Path.home() / ".local" / "share" / "kb-mcp" / "kb.db"
    return SqliteStore(db_path)


def _get_store(ctx: click.Context) -> Any:
    """Return the :class:`Store` bound to this Click context.

    Tests inject a store via ``runner.invoke(cli, [...], obj={"store": s})``.
    The default is a fresh :class:`SqliteStore` per process.
    """
    if ctx.obj is None:
        ctx.obj = {}
    if "store" not in ctx.obj:
        ctx.obj["store"] = _create_default_store()
    return ctx.obj["store"]


# JSON helpers ----------------------------------------------------------------


def _emit_json(payload: dict[str, Any] | list[Any]) -> None:
    """Print ``payload`` as pretty JSON to stdout."""
    click.echo(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def _emit_error(ctx: click.Context, as_json: bool, kind: str, message: str) -> None:
    """Print an error message; honour ``--json`` mode."""
    if as_json:
        click.echo(
            json.dumps(
                {"ok": False, "error": kind, "message": message},
                ensure_ascii=False,
            ),
            err=True,
        )
    else:
        click.echo(f"error: {message}", err=True)


# Exception → exit-code decorator --------------------------------------------


def _handle_errors(func: F) -> F:
    """Map :mod:`kb_mcp_lite` exceptions to the exit codes in
    ``cli-reference.md``. ``click.UsageError`` and ``click.ClickException``
    are re-raised unchanged (Click renders them and sets the right code).
    """

    @functools.wraps(func)
    def wrapper(ctx: click.Context, *args: Any, **kwargs: Any) -> Any:
        # The ``as_json`` kwarg is what the ``--json`` option is bound to
        # in every command that supports it. Fall back to False if absent.
        as_json = bool(kwargs.get("as_json", False))
        try:
            return func(ctx, *args, **kwargs)
        except click.UsageError:
            raise
        except click.ClickException:
            raise
        except NotFoundError as e:
            _emit_error(ctx, as_json, "not_found", str(e))
            ctx.exit(EXIT_NOT_FOUND)
        except DuplicateError as e:
            _emit_error(ctx, as_json, "duplicate", str(e))
            ctx.exit(EXIT_CONFLICT)
        except ValidationError as e:
            _emit_error(ctx, as_json, "validation", str(e))
            ctx.exit(EXIT_VALIDATION)
        except NotImplementedError as e:
            _emit_error(ctx, as_json, "not_implemented", str(e))
            ctx.exit(EXIT_INTERNAL)
        except PydanticValidationError as e:
            _emit_error(ctx, as_json, "validation", str(e))
            ctx.exit(EXIT_VALIDATION)
        except KbMcpError as e:
            _emit_error(ctx, as_json, "error", str(e))
            ctx.exit(EXIT_INTERNAL)
        except Exception as e:  # pragma: no cover - last-resort guard
            _emit_error(ctx, as_json, "internal", str(e))
            ctx.exit(EXIT_INTERNAL)

    return wrapper  # type: ignore[return-value]


# Shared options --------------------------------------------------------------


def _json_option(f: F) -> F:
    """Add ``--json`` to a command. The flag is bound to the kwarg
    ``as_json`` (avoiding the ``json`` builtin name) and is picked up
    by :func:`_handle_errors` and the human/JSON formatters."""
    return click.option(
        "--json",
        "as_json",
        is_flag=True,
        help="Output machine-readable JSON to stdout.",
    )(f)


# Body resolution for `kb add` ------------------------------------------------


def _resolve_body(body: str | None, body_file: str | None) -> str:
    """Return the body string for ``kb add``.

    Precedence:

    1. ``--body BODY`` — use the literal string (may be empty).
    2. ``--body-file PATH`` — read UTF-8 from the file.
    3. neither — read stdin until EOF.

    Raises :class:`click.UsageError` (exit 64) if both are supplied.
    """
    if body is not None and body_file is not None:
        raise click.UsageError("--body and --body-file are mutually exclusive")
    if body is not None:
        return body
    if body_file is not None:
        path = Path(body_file)
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError as e:
            raise click.UsageError(f"body file not found: {body_file}") from e
        except OSError as e:
            raise click.UsageError(f"cannot read body file {body_file}: {e}") from e
    # Fall back to stdin — read until EOF.
    return click.get_text_stream("stdin").read()


# Markdown I/O -----------------------------------------------------------------


def _parse_tags(raw: str | None) -> list[str]:
    """Parse a comma-separated tag list. Empty / unset returns ``[]``."""
    if not raw:
        return []
    out: list[str] = []
    for piece in raw.split(","):
        t = piece.strip()
        if t:
            out.append(t)
    return out


# CLI group -------------------------------------------------------------------


@click.group()
@click.version_option(package_name="kb_mcp_lite")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """kb-mcp: agent-native knowledge base."""


# ---- kb init -----------------------------------------------------------------


@cli.command()
@click.option(
    "--force",
    is_flag=True,
    help="Recreate the DB even if it exists (DESTRUCTIVE; confirms unless --yes).",
)
@click.option(
    "-y",
    "--yes",
    "skip_confirm",
    is_flag=True,
    help="Skip confirmation prompts.",
)
@_json_option
@click.pass_context
@_handle_errors
def init(ctx: click.Context, force: bool, skip_confirm: bool, as_json: bool) -> None:
    """Initialize a kb-mcp database.

    Creates the DB file and runs migrations if it doesn't exist.
    If the DB already exists, this is a no-op. ``--force`` re-runs
    migrations (idempotent) but does **not** drop existing data.
    """
    if force and not skip_confirm and sys.stdin.isatty():
        # Only prompt when running interactively; non-interactive callers
        # (e.g. CliRunner) and explicit --yes skip the check.
        if not click.confirm("--force will recreate the KB. Continue?", default=False):
            raise click.Abort()
    store = _get_store(ctx)
    # Touching the store proves the protocol works end-to-end.
    _ = store.doctor()
    message = "initialized kb-mcp"
    if force:
        message += " (force)"
    if as_json:
        _emit_json({"ok": True, "force": force, "message": message})
    else:
        click.echo(f"kb init: {message}")


# ---- kb add ------------------------------------------------------------------


@cli.command()
@click.option(
    "--type",
    "doc_type",
    required=True,
    help="Document type (e.g. project, decision, lesson).",
)
@click.option("--title", required=True, help="Document title.")
@click.option(
    "--tags",
    "tags_raw",
    default=None,
    help="Comma-separated tag list (e.g. 'kb,mcp,design').",
)
@click.option("--body", default=None, help="Inline Markdown body.")
@click.option(
    "--body-file",
    "body_file",
    default=None,
    type=click.Path(),
    help="Read body from this file (mutually exclusive with --body).",
)
@click.option(
    "--source",
    default=None,
    help="Origin file path (enables idempotent re-import).",
)
@_json_option
@click.pass_context
@_handle_errors
def add(
    ctx: click.Context,
    doc_type: str,
    title: str,
    tags_raw: str | None,
    body: str | None,
    body_file: str | None,
    source: str | None,
    as_json: bool,
) -> None:
    """Create a document."""
    store = _get_store(ctx)
    body_text = _resolve_body(body, body_file)
    tags = _parse_tags(tags_raw)
    new_id = make_id(doc_type, title)
    doc = Document(
        id=new_id,
        type=doc_type,
        title=title,
        body=body_text,
        tags=tags,
        source=source,
    )
    stored_id = store.add(doc)
    if as_json:
        _emit_json({"ok": True, "id": stored_id, "type": doc_type, "title": title})
    else:
        click.echo(stored_id)


# ---- kb get ------------------------------------------------------------------


@cli.command()
@click.argument("doc_id")
@_json_option
@click.pass_context
@_handle_errors
def get(ctx: click.Context, doc_id: str, as_json: bool) -> None:
    """Fetch a document by id."""
    store = _get_store(ctx)
    doc = store.get(doc_id)
    if as_json:
        _emit_json(doc.model_dump(mode="json"))
    else:
        click.echo(f"# {doc.title}")
        click.echo(f"_id: {doc.id}  •  type: {doc.type}  •  updated: {doc.updated_at.isoformat()}_")
        if doc.tags:
            click.echo(f"tags: {', '.join(doc.tags)}")
        click.echo("")
        click.echo(doc.body)


# ---- kb search ---------------------------------------------------------------


@cli.command()
@click.argument("query")
@click.option("--type", "doc_type", default=None, help="Restrict to document type.")
@click.option(
    "--tag",
    "tags",
    multiple=True,
    help="Restrict to documents carrying this tag (repeat for AND).",
)
@click.option(
    "-n",
    "--limit",
    default=10,
    show_default=True,
    help="Max results (capped at 100).",
)
@click.option(
    "--mode",
    default="hybrid",
    show_default=True,
    type=click.Choice(["lexical", "fuzzy", "semantic", "hybrid"], case_sensitive=False),
    help="Scoring mode: lexical (exact BM25), fuzzy (trigram), or hybrid (default).",
)
@_json_option
@click.pass_context
@_handle_errors
def search(
    ctx: click.Context,
    query: str,
    doc_type: str | None,
    tags: tuple[str, ...],
    limit: int,
    mode: str,
    as_json: bool,
) -> None:
    """Full-text search."""
    store = _get_store(ctx)
    tag_list = list(tags) if tags else None
    hits = store.search(query, type=doc_type, tags=tag_list, limit=limit, mode=mode)
    if as_json:
        _emit_json(
            [
                {
                    "id": h.doc.id,
                    "type": h.doc.type,
                    "title": h.doc.title,
                    "snippet": h.snippet,
                    "score": h.score,
                }
                for h in hits
            ]
        )
    else:
        if not hits:
            click.echo("(no results)")
            return
        for h in hits:
            click.echo(f"{h.doc.id}  [{h.doc.type}]  {h.doc.title}")
            click.echo(f"  {h.snippet}")


# ---- kb list -----------------------------------------------------------------


@cli.command(name="list")
@click.option("--type", "doc_type", default=None, help="Restrict to document type.")
@click.option(
    "--tag",
    "tags",
    multiple=True,
    help="Restrict to documents carrying this tag (repeat for AND).",
)
@click.option(
    "-n",
    "--limit",
    default=100,
    show_default=True,
    help="Max results (capped at 1000).",
)
@click.option(
    "--offset",
    default=0,
    show_default=True,
    help="Skip this many results before returning (pagination).",
)
@click.option(
    "--include-deleted",
    is_flag=True,
    help="Include soft-deleted documents (default: hide them).",
)
@_json_option
@click.pass_context
@_handle_errors
def list_cmd(
    ctx: click.Context,
    doc_type: str | None,
    tags: tuple[str, ...],
    limit: int,
    offset: int,
    include_deleted: bool,
    as_json: bool,
) -> None:
    """List documents, sorted by ``updated_at`` DESC."""
    store = _get_store(ctx)
    tag_list = list(tags) if tags else None
    docs = store.list(
        type=doc_type,
        tags=tag_list,
        limit=limit,
        offset=offset,
        include_deleted=include_deleted,
    )
    if as_json:
        _emit_json([d.model_dump(mode="json") for d in docs])
    else:
        if not docs:
            click.echo("(no documents)")
            return
        for d in docs:
            click.echo(f"{d.id}  [{d.type}]  {d.title}  ({d.updated_at.isoformat()})")


# ---- kb link -----------------------------------------------------------------


@cli.command()
@click.option("--from", "from_id", required=True, help="Source document id.")
@click.option("--to", "to_id", required=True, help="Target document id.")
@click.option(
    "--rel",
    default="relates-to",
    show_default=True,
    help="Relation type (default: relates-to).",
)
@_json_option
@click.pass_context
@_handle_errors
def link(
    ctx: click.Context,
    from_id: str,
    to_id: str,
    rel: str,
    as_json: bool,
) -> None:
    """Create or update a typed edge between two documents."""
    store = _get_store(ctx)
    edge = store.link(from_id, to_id, rel=rel)
    if as_json:
        _emit_json(
            {
                "ok": True,
                "from": edge.from_id,
                "to": edge.to_id,
                "rel": edge.rel,
            }
        )
    else:
        click.echo(f"{edge.from_id} --{edge.rel}--> {edge.to_id}")


# ---- kb unlink ---------------------------------------------------------------

# Click would treat "unlink" as a builtin (it isn't one in Python, but the
# convention still suggests we be explicit). The command name is
# ``unlink`` to mirror ``link``.

_UNLINK_HELP = "Remove typed edges between two documents (inverse of ``link``)."


@cli.command(name="unlink")
@click.option("--from", "from_id", required=True, help="Source document id.")
@click.option("--to", "to_id", required=True, help="Target document id.")
@click.option(
    "--rel",
    default=None,
    help="Relation type to remove (default: remove all relations).",
)
@_json_option
@click.pass_context
@_handle_errors
def unlink_cmd(
    ctx: click.Context,
    from_id: str,
    to_id: str,
    rel: str | None,
    as_json: bool,
) -> None:
    """Remove typed edges between two documents.

    With ``--rel``, only that specific relation is removed. Without it,
    all relations between ``--from`` and ``--to`` are removed.
    """
    store = _get_store(ctx)
    n = store.unlink(from_id, to_id, rel=rel)
    if as_json:
        _emit_json({"ok": True, "removed": n, "from": from_id, "to": to_id, "rel": rel})
    else:
        click.echo(f"removed {n} edge(s)")


# ---- kb update ---------------------------------------------------------------


@cli.command()
@click.argument("doc_id")
@click.option("--title", default=None, help="New title.")
@click.option("--body", default=None, help="New inline Markdown body.")
@click.option(
    "--body-file",
    "body_file",
    default=None,
    type=click.Path(),
    help="Read new body from this file (mutually exclusive with --body).",
)
@click.option(
    "--tags",
    "tags_raw",
    default=None,
    help="New comma-separated tag list. Use '-' to clear all tags.",
)
@click.option("--source", default=None, help="New source path.")
@_json_option
@click.pass_context
@_handle_errors
def update(
    ctx: click.Context,
    doc_id: str,
    title: str | None,
    body: str | None,
    body_file: str | None,
    tags_raw: str | None,
    source: str | None,
    as_json: bool,
) -> None:
    """Patch fields on an existing document.

    Only ``--title``, ``--body``, ``--tags``, ``--source`` are accepted.
    The document's ``id``, ``type``, and ``created_at`` cannot be changed.
    """
    store = _get_store(ctx)
    fields: dict[str, object] = {}
    if title is not None:
        fields["title"] = title
    body_text = _resolve_body(body, body_file) if (body is not None or body_file is not None) else None
    if body is not None or body_file is not None:
        fields["body"] = body_text
    if tags_raw is not None:
        if tags_raw == "-":
            fields["tags"] = []
        else:
            fields["tags"] = _parse_tags(tags_raw)
    if source is not None:
        fields["source"] = source
    if not fields:
        raise click.UsageError("update requires at least one of --title/--body/--tags/--source")
    doc = store.update(doc_id, **fields)
    if as_json:
        _emit_json({"ok": True, "id": doc.id, "updated_at": doc.updated_at.isoformat()})
    else:
        click.echo(f"updated {doc.id}")


# ---- kb delete ---------------------------------------------------------------


@cli.command()
@click.argument("doc_id")
@_json_option
@click.pass_context
@_handle_errors
def delete(ctx: click.Context, doc_id: str, as_json: bool) -> None:
    """Soft-delete a document by id.

    Idempotent: deleting an already-deleted document is a no-op.
    Use ``kb doctor`` + ``kb prune`` (when added) to hard-delete.
    """
    store = _get_store(ctx)
    store.delete(doc_id)
    if as_json:
        _emit_json({"ok": True, "id": doc_id})
    else:
        click.echo(f"deleted {doc_id}")


# ---- kb prune -----------------------------------------------------------------


@cli.command()
@click.option(
    "--older-than",
    default="30d",
    show_default=True,
    help="Hard-delete soft-deleted docs older than this (e.g. 30d, 7d, 24h).",
)
@_json_option
@click.pass_context
@_handle_errors
def prune(ctx: click.Context, older_than: str, as_json: bool) -> None:
    """Hard-delete soft-deleted documents past the grace period."""
    import re
    m = re.match(r"^(\d+)([dh])$", older_than)
    if not m:
        raise click.UsageError(f"invalid --older-than {older_than!r} (expected like 30d or 24h)")
    n_units, unit = int(m.group(1)), m.group(2)
    delta = timedelta(days=n_units) if unit == "d" else timedelta(hours=n_units)
    store = _get_store(ctx)
    n = store.prune(delta)
    if as_json:
        _emit_json({"ok": True, "pruned": n})
    else:
        click.echo(f"pruned {n} document(s)")


# ---- kb embed -----------------------------------------------------------------


@cli.command()
@click.option(
    "--rebuild",
    is_flag=True,
    help="Recompute embeddings for all active documents (use after changing models).",
)
@_json_option
@click.pass_context
@_handle_errors
def embed(ctx: click.Context, rebuild: bool, as_json: bool) -> None:
    """Manage semantic-search embeddings.

    With ``--rebuild``, recomputes the embedding for every active
    document (the embedder configured in
    ``~/.hermes/config.yaml``'s ``auxiliary.embedding`` block is
    used). Without ``--rebuild``, this command prints the embedder
    status and number of indexed documents.
    """
    store = _get_store(ctx)
    emb = getattr(store, "_embedder", None)
    enabled = bool(emb and getattr(emb, "enabled", False))
    dim = getattr(emb, "dim", 0) if emb else 0

    if rebuild:
        if not enabled:
            raise click.UsageError(
                "no embedder configured; set auxiliary.embedding in "
                "~/.hermes/config.yaml"
            )
        n = store.reindex_embeddings()
        # Pull the real dim + failure count from the report captured
        # during reindex. ``HttpEmbedder.dim`` is lazy and only fills
        # in after the first embed() call, so reading it before
        # reindex always returns 0 — the report captures the post-
        # reindex value instead.
        report = getattr(store, "last_reindex_report", {}) or {}
        dim = report.get("dim") or dim
        failed = report.get("failed", 0)
        if as_json:
            _emit_json(
                {
                    "ok": True,
                    "reindexed": n,
                    "failed": failed,
                    "dim": dim,
                    "total": report.get("total", n + failed),
                }
            )
        else:
            msg = f"re-embedded {n} document(s) (dim={dim})"
            if failed:
                msg += f", {failed} failed"
            click.echo(msg)
        return

    # Status mode
    try:
        n_vec = store._conn.execute(
            "SELECT COUNT(*) FROM docs_vec"
        ).fetchone()[0] if enabled else 0
    except Exception:  # noqa: BLE001 — vec0 not available
        n_vec = 0
    status = {
        "embedder_enabled": enabled,
        "dim": dim,
        "indexed_documents": n_vec,
    }
    if as_json:
        _emit_json({"ok": True, **status})
    else:
        click.echo(
            f"embedder={'enabled' if enabled else 'disabled'} "
            f"dim={dim} indexed={n_vec}"
        )


# ---- kb import ---------------------------------------------------------------


@cli.command()
@click.argument(
    "directory",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Walk the directory and report what would happen, without writing.",
)
@_json_option
@click.pass_context
@_handle_errors
def import_cmd(
    ctx: click.Context,
    directory: Path,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Import a directory of Markdown files into the DB."""
    from kb_mcp_lite.md_io import import_dir as _import_dir

    store = _get_store(ctx)
    report = _import_dir(store, directory, dry_run=dry_run)
    if as_json:
        _emit_json(report.model_dump())


# ---- kb export ---------------------------------------------------------------


@cli.command()
@click.argument(
    "directory",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
)
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite existing files in the target directory.",
)
@_json_option
@click.pass_context
@_handle_errors
def export_cmd(
    ctx: click.Context,
    directory: Path,
    force: bool,
    as_json: bool,
) -> None:
    """Export the DB to a directory of Markdown files."""
    from kb_mcp_lite.md_io import export_dir as _export_dir

    store = _get_store(ctx)
    n = _export_dir(store, directory, force=force)
    if as_json:
        _emit_json({"ok": True, "written": n})


# ---- kb doctor ---------------------------------------------------------------


@cli.command()
@_json_option
@click.pass_context
@_handle_errors
def doctor(ctx: click.Context, as_json: bool) -> None:
    """Run health checks on the KB."""
    store = _get_store(ctx)
    report = store.doctor()
    if as_json:
        _emit_json(report.model_dump())
    else:
        if report.ok:
            click.echo("kb doctor: OK")
            for c in report.checks:
                click.echo(f"  ✓ {c.name}: {c.detail}")
        else:
            click.echo(report.summary())
            # cli-reference.md says doctor exits 1 on any failure, but
            # the table in § "Exit codes" maps DB / I/O problems to 5.
            # We follow the table (5) for consistency with other I/O
            # errors — see the deviations note in the final report.
            ctx.exit(EXIT_INTERNAL)


# ---- kb serve ----------------------------------------------------------------


@cli.command()
@click.option(
    "--log-level",
    default=os.environ.get("KB_MCP_LOG_LEVEL", "WARNING"),
    show_default=True,
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    help="Log level for the MCP server.",
)
@click.pass_context
@_handle_errors
def serve(ctx: click.Context, log_level: str) -> None:
    """Start the MCP server on stdio (Wave 2A)."""
    from kb_mcp_lite.mcp_server import run as _run_mcp_server

    os.environ["KB_MCP_LOG_LEVEL"] = log_level
    _run_mcp_server()


# Entry point -----------------------------------------------------------------


# Apply the cli-reference.md usage-error exit code at import time so both
# ``cli()`` and ``main()`` honour it. Without this, Click's default of 2
# would leak through for in-process callers (tests) that bypass
# :func:`main`.
click.exceptions.UsageError.exit_code = EXIT_USAGE


def main() -> None:
    """Console-script entry point registered in ``pyproject.toml``."""
    cli(standalone_mode=True)


# Re-export for tests / programmatic use --------------------------------------

__all__ = [
    "cli",
    "main",
    "EXIT_OK",
    "EXIT_VALIDATION",
    "EXIT_NOT_FOUND",
    "EXIT_CONFLICT",
    "EXIT_INTERNAL",
    "EXIT_USAGE",
    "_handle_errors",
    "_get_store",
    "_resolve_body",
    "_parse_tags",
]
