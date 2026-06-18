"""Click CLI for kb-mcp (Wave 1C).

This module implements the full command surface described in
``docs/cli-reference.md``:

- ``kb init [--force] [--yes] [--json]``
- ``kb add --type TYPE --title TITLE [--tags ...] [--body | --body-file] [--source] [--json]``
- ``kb get ID [--json]``
- ``kb search QUERY [--type] [--tag]... [--limit] [--json]``
- ``kb list [--type] [--tag]... [--limit] [--offset] [--json]``
- ``kb link --from ID --to ID [--rel] [--json]``
- ``kb import DIR [--json] [--dry-run]``     *(deferred to Wave 1B)*
- ``kb export DIR [--json] [--force]``        *(deferred to Wave 1B)*
- ``kb doctor [--json]``
- ``kb serve [--log-level LEVEL]``            *(deferred to Wave 2A)*

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

For v0.1 the CLI uses :class:`~kb_mcp.store.sqlite.SqliteStore`
(SQLite + FTS5). Tests inject their own
``SqliteStore`` via Click's ``obj`` context object, e.g.::

    runner.invoke(cli, ["add", ...], obj={"store": my_store})

Import / export stubs
---------------------

``kb import`` and ``kb export`` call :func:`_import_dir_stub` and
:func:`_export_dir_stub` respectively. These are inline shims that
raise :class:`NotImplementedError` with a "Wave 1B" message, so the
CLI surface is complete and the commands exit with code 5 until the
real Markdown I/O module (``kb_mcp.md_io``) lands. See the
:mod:`kb_mcp.md_io` contract in ``docs/architecture.md`` § 4.3.
"""

from __future__ import annotations

import functools
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, TypeVar

import click

from kb_mcp.schema import (
    Document,
    DuplicateError,
    ImportReport,
    KbMcpError,
    Link,
    NotFoundError,
    SearchHit,
    ValidationError,
    make_id,
)
from kb_mcp.store.sqlite import SqliteStore


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
    """Map :mod:`kb_mcp` exceptions to the exit codes in
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
            # Import / export / serve stubs land here.
            _emit_error(ctx, as_json, "not_implemented", str(e))
            ctx.exit(EXIT_INTERNAL)
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
            raise click.UsageError(
                f"cannot read body file {body_file}: {e}"
            ) from e
    # Fall back to stdin — read until EOF.
    return click.get_text_stream("stdin").read()


# Markdown I/O stubs (deferred to Wave 1B) ------------------------------------


def _import_dir_stub(
    store: Any, directory: Path, *, dry_run: bool = False
) -> ImportReport:
    """Inline stub for ``kb_mcp.md_io.import_dir``.

    The real implementation lands in Wave 1B. Until then, every
    invocation raises :class:`NotImplementedError`, which the CLI
    surfaces as exit code 5.
    """
    raise NotImplementedError(
        "kb import: deferred to Wave 1B (kb_mcp.md_io.import_dir)"
    )


def _export_dir_stub(
    store: Any, directory: Path, *, force: bool = False
) -> int:
    """Inline stub for ``kb_mcp.md_io.export_dir``.

    See :func:`_import_dir_stub` for the Wave 1B deferral rationale.
    """
    raise NotImplementedError(
        "kb export: deferred to Wave 1B (kb_mcp.md_io.export_dir)"
    )


# Tag parsing -----------------------------------------------------------------


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
@click.version_option(package_name="kb_mcp")
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
        if not click.confirm(
            "--force will recreate the KB. Continue?", default=False
        ):
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
@_json_option
@click.pass_context
@_handle_errors
def search(
    ctx: click.Context,
    query: str,
    doc_type: str | None,
    tags: tuple[str, ...],
    limit: int,
    as_json: bool,
) -> None:
    """Full-text search."""
    store = _get_store(ctx)
    tag_list = list(tags) if tags else None
    hits = store.search(query, type=doc_type, tags=tag_list, limit=limit)
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
@_json_option
@click.pass_context
@_handle_errors
def list_cmd(
    ctx: click.Context,
    doc_type: str | None,
    tags: tuple[str, ...],
    limit: int,
    offset: int,
    as_json: bool,
) -> None:
    """List documents, sorted by ``updated_at`` DESC."""
    store = _get_store(ctx)
    tag_list = list(tags) if tags else None
    docs = store.list(
        type=doc_type, tags=tag_list, limit=limit, offset=offset
    )
    if as_json:
        _emit_json([d.model_dump(mode="json") for d in docs])
    else:
        if not docs:
            click.echo("(no documents)")
            return
        for d in docs:
            click.echo(
                f"{d.id}  [{d.type}]  {d.title}  "
                f"({d.updated_at.isoformat()})"
            )


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
    """Import a directory of Markdown files into the DB.

    Implementation deferred to Wave 1B (``kb_mcp.md_io``). The CLI
    surface is fully wired so the command is discoverable and testable;
    invoking it exits with code 5 until the real module lands.
    """
    store = _get_store(ctx)
    report = _import_dir_stub(store, directory, dry_run=dry_run)
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
    """Export the DB to a directory of Markdown files.

    Implementation deferred to Wave 1B (``kb_mcp.md_io``). See
    :func:`_import_dir_stub` for the deferral rationale.
    """
    store = _get_store(ctx)
    n = _export_dir_stub(store, directory, force=force)
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
    from kb_mcp.mcp_server import run as _run_mcp_server

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
