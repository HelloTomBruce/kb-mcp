"""Command-line interface."""
import os
import sys
import json
import functools
from pathlib import Path
from typing import Any, Callable, TypeVar

import click
from pydantic import ValidationError

from kb_mcp_lite import __version__
from kb_mcp_lite.config import load_config as get_config
from kb_mcp_lite.md_io import import_dir, export_dir
from kb_mcp_lite.schema import (
    Document,
    make_id,
    NotFoundError,
    DuplicateError,
    DoctorReport,
)
from kb_mcp_lite.mcp_server import run as run_mcp_server
from kb_mcp_lite.vault import VaultManager


F = TypeVar("F", bound=Callable[..., Any])

# Exit codes — match the expected values from tests.
EXIT_OK = 0
EXIT_VALIDATION = 2
EXIT_NOT_FOUND = 3
EXIT_CONFLICT = 4
EXIT_INTERNAL = 5
EXIT_USAGE = 64


# ---- helpers ----------------------------------------------------------------


def _handle_errors(func: F) -> F:
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except NotFoundError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)
        except DuplicateError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)
        except ValidationError as e:
            click.echo(f"Validation error: {e}", err=True)
            sys.exit(1)
        except Exception as e:
            click.echo(f"Unexpected error: {type(e).__name__}: {e}", err=True)
            if os.environ.get("KB_DEBUG"):
                raise
            sys.exit(1)

    return wrapper  # type: ignore


def _get_store(ctx: click.Context) -> Any:
    return ctx.obj["store"]


def _json_option(func: F) -> F:
    return click.option(
        "--json", "as_json", is_flag=True, help="Output results as JSON."
    )(func)


# ---- main cli -----------------------------------------------------------------


@click.group(name="kb", help=f"kb: Agent-native knowledge base. v{__version__}")
@click.version_option(__version__)
@click.option("--vault", help="Use a specific vault by name or path.")
@click.pass_context
def cli(ctx: click.Context, vault: str | None) -> None:
    config = get_config()
    vault_manager = VaultManager()
    selected_vault = vault or vault_manager.get_current()
    ctx.ensure_object(dict)
    # Use injected store from test if present; otherwise create a new one
    if "store" not in ctx.obj:
        from kb_mcp_lite.store import SqliteStore
        db_path = vault_manager.resolve_path(selected_vault)
        ctx.obj["store"] = SqliteStore(db_path)
    # Use injected config/vault_manager if present; otherwise set them up
    if "config" not in ctx.obj:
        ctx.obj["config"] = config
    if "vault_manager" not in ctx.obj:
        ctx.obj["vault_manager"] = vault_manager


def _emit_json(obj: Any) -> None:
    click.echo(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


# ---- kb init -----------------------------------------------------------------


@cli.command()
@click.pass_context
@_handle_errors
def init(ctx: click.Context) -> None:
    """Initialize a new knowledge base."""
    store = _get_store(ctx)
    store.init()
    click.echo("Initialized kb.")


# ---- kb add ------------------------------------------------------------------


@cli.command()
@click.option("--type", "doc_type", required=True, help="Document type.")
@click.option("--title", required=True, help="Document title.")
@click.option("--tags", help="Comma-separated list of tags.")
@click.option("--body", help="Document body (Markdown).")
@_json_option
@click.pass_context
@_handle_errors
def add(
    ctx: click.Context,
    doc_type: str,
    title: str,
    tags: str | None,
    body: str | None,
    as_json: bool,
) -> None:
    """Add a new document."""
    store = _get_store(ctx)
    tag_list = tags.split(",") if tags else []
    doc = Document(
        id="",  # Auto-generated
        type=doc_type,
        title=title,
        tags=tag_list,
        body=body or "",
    )
    doc_id = store.add(doc)
    if as_json:
        _emit_json({"id": doc_id})
    else:
        click.echo(f"Added document: {doc_id}")


# ---- kb get ------------------------------------------------------------------


@cli.command()
@click.argument("doc_id")
@_json_option
@click.pass_context
@_handle_errors
def get(ctx: click.Context, doc_id: str, as_json: bool) -> None:
    """Get a document by ID."""
    store = _get_store(ctx)
    doc = store.get(doc_id)
    if as_json:
        _emit_json(doc.model_dump(mode="json"))
    else:
        click.echo(f"ID: {doc.id}")
        click.echo(f"Type: {doc.type}")
        click.echo(f"Title: {doc.title}")
        click.echo(f"Tags: {', '.join(doc.tags) if doc.tags else '(none)'}")
        click.echo(f"Created: {doc.created_at.isoformat()}")
        click.echo(f"Updated: {doc.updated_at.isoformat()}")
        click.echo("")
        click.echo(doc.body)


# ---- kb update ---------------------------------------------------------------


@cli.command()
@click.argument("doc_id")
@click.option("--title", help="New title.")
@click.option("--tags", help="New comma-separated tags list.")
@click.option("--body", help="New body.")
@_json_option
@click.pass_context
@_handle_errors
def update(
    ctx: click.Context,
    doc_id: str,
    title: str | None,
    tags: str | None,
    body: str | None,
    as_json: bool,
) -> None:
    """Update a document."""
    store = _get_store(ctx)
    updates: dict[str, Any] = {}
    if title:
        updates["title"] = title
    if tags is not None:
        updates["tags"] = tags.split(",") if tags else []
    if body is not None:
        updates["body"] = body
    if not updates:
        click.echo("No updates specified.", err=True)
        sys.exit(1)
    updated = store.update(doc_id, **updates)
    if as_json:
        _emit_json(updated.model_dump(mode="json"))
    else:
        click.echo(f"Updated {doc_id}")


# ---- kb delete ----------------------------------------------------------------


@cli.command()
@click.argument("doc_id")
@_json_option
@click.pass_context
@_handle_errors
def delete(ctx: click.Context, doc_id: str, as_json: bool) -> None:
    """Soft-delete a document."""
    store = _get_store(ctx)
    store.delete(doc_id)
    if as_json:
        _emit_json({"deleted": doc_id})
    else:
        click.echo(f"Deleted {doc_id}")


# ---- kb restore ---------------------------------------------------------------


@cli.command()
@click.argument("doc_id")
@click.option("--version", type=int, help="Restore to a specific version number.")
@_json_option
@click.pass_context
@_handle_errors
def restore(ctx: click.Context, doc_id: str, version: int | None, as_json: bool) -> None:
    """Restore a soft-deleted document or restore to a previous version."""
    store = _get_store(ctx)
    if version is not None:
        restored = store.restore_version(doc_id, version)
    else:
        restored = store.restore_deleted(doc_id)
    if as_json:
        _emit_json(restored.model_dump(mode="json"))
    else:
        click.echo(f"Restored {doc_id}")


# ---- kb search ---------------------------------------------------------------


@cli.command()
@click.argument("query")
@click.option("--type", "doc_type", help="Filter by document type.")
@click.option("--tags", multiple=True, help="Filter by tags (may be used multiple times).")
@click.option("--fuzzy", is_flag=True, help="Use fuzzy trigram search.")
@click.option("--limit", default=20, type=click.IntRange(1, 100), show_default=True)
@_json_option
@click.pass_context
@_handle_errors
def search(
    ctx: click.Context,
    query: str,
    doc_type: str | None,
    tags: tuple[str, ...],
    fuzzy: bool,
    limit: int,
    as_json: bool,
) -> None:
    """Search the knowledge base."""
    store = _get_store(ctx)
    tag_list = list(tags) if tags else None
    results = store.search(query, type=doc_type, tags=tag_list, mode="fuzzy" if fuzzy else "lexical", limit=limit)
    if as_json:
        _emit_json([
            {
                "doc": hit.doc.model_dump(mode="json"),
                "snippet": hit.snippet,
                "score": hit.score,
            }
            for hit in results
        ])
    else:
        if not results:
            click.echo("(no results)")
            return
        for i, hit in enumerate(results, 1):
            click.echo(f"{i}. {hit.doc.id}  [{hit.doc.type}]  {hit.doc.title}")
            click.echo(f"   {hit.snippet}")
            click.echo()


# ---- kb list -----------------------------------------------------------------


@cli.command("list")
@click.option(
    "--type", "doc_type",
    help="Filter by document type (e.g. decision, lesson).",
)
@click.option(
    "--tags",
    multiple=True,
    help="Filter by tags (all specified tags must be present). May be used multiple times.",
)
@click.option(
    "--project",
    help="Filter documents linked to this project ID (shortcut for --link-to <proj/id>).",
)
@click.option(
    "--link-to",
    help="Filter documents that link to this document ID.",
)
@click.option(
    "--link-from",
    help="Filter documents that are linked from this document ID.",
)
@click.option(
    "--limit",
    default=100,
    show_default=True,
    type=click.IntRange(1, 1000),
    help="Return at most this many results.",
)
@click.option(
    "--offset",
    default=0,
    show_default=True,
    type=click.IntRange(0),
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
    project: str | None,
    link_to: str | None,
    link_from: str | None,
    limit: int,
    offset: int,
    include_deleted: bool,
    as_json: bool,
) -> None:
    """List documents, sorted by ``updated_at`` DESC."""
    store = _get_store(ctx)
    tag_list = list(tags) if tags else None
    
    # Handle --project shortcut
    if project:
        if not project.startswith("proj/"):
            project = f"proj/{project}"
        link_to = project
    
    docs = store.list(
        type=doc_type,
        tags=tag_list,
        link_to=link_to,
        link_from=link_from,
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
    """Create a typed link between two documents."""
    store = _get_store(ctx)
    store.link(from_id, to_id, rel)
    if as_json:
        _emit_json({"from": from_id, "to": to_id, "rel": rel})
    else:
        click.echo(f"Linked {from_id} -> {to_id} ({rel})")


# ---- kb unlink ---------------------------------------------------------------


@cli.command()
@click.option("--from", "from_id", required=True, help="Source document id.")
@click.option("--to", "to_id", required=True, help="Target document id.")
@click.option("--rel", help="Only remove links with this specific relation.")
@_json_option
@click.pass_context
@_handle_errors
def unlink(
    ctx: click.Context,
    from_id: str,
    to_id: str,
    rel: str | None,
    as_json: bool,
) -> None:
    """Remove a link between two documents."""
    store = _get_store(ctx)
    store.unlink(from_id, to_id, rel)
    if as_json:
        _emit_json({"removed": f"{from_id} -> {to_id}"})
    else:
        click.echo(f"Removed link {from_id} -> {to_id}")


# ---- kb links ----------------------------------------------------------------


@cli.command()
@click.argument("doc_id")
@_json_option
@click.pass_context
@_handle_errors
def links(ctx: click.Context, doc_id: str, as_json: bool) -> None:
    """Show all incoming and outgoing links for a document."""
    store = _get_store(ctx)
    outgoing = store.outgoing_links(doc_id)
    incoming = store.incoming_links(doc_id)
    if as_json:
        _emit_json({
            "outgoing": [{"to": l.to_id, "rel": l.rel, "created_at": l.created_at} for l in outgoing],
            "incoming": [{"from": l.from_id, "rel": l.rel, "created_at": l.created_at} for l in incoming],
        })
    else:
        click.echo(f"Links for {doc_id}:")
        click.echo("")
        click.echo("Outgoing:")
        if not outgoing:
            click.echo("  (none)")
        else:
            for l in outgoing:
                click.echo(f"  -> {l.to_id}  ({l.rel})")
        click.echo("")
        click.echo("Incoming:")
        if not incoming:
            click.echo("  (none)")
        else:
            for l in incoming:
                click.echo(f"  <- {l.from_id}  ({l.rel})")


# ---- kb history ---------------------------------------------------------------


@cli.command()
@click.argument("doc_id")
@_json_option
@click.pass_context
@_handle_errors
def history(ctx: click.Context, doc_id: str, as_json: bool) -> None:
    """Show version history for a document."""
    store = _get_store(ctx)
    versions = store.get_versions(doc_id)
    if as_json:
        _emit_json([v if isinstance(v, dict) else v.model_dump(mode="json") for v in versions])
    else:
        if not versions:
            click.echo("(no history)")
            return
        for v in versions:
            if isinstance(v, dict):
                version_id = v.get("version_id", "?")
                created_at = v.get("created_at", "")
                message = v.get("note", "") or v.get("message", "")
            else:
                version_id = v.version
                created_at = v.created_at
                message = getattr(v, "message", "")
            click.echo(f"Version {version_id}: {created_at}")
            if message:
                click.echo(f"  {message}")
            click.echo()


# ---- kb diff -----------------------------------------------------------------


@cli.command()
@click.argument("doc_id")
@click.option("--v1", type=int, required=True, help="First version number.")
@click.option("--v2", type=int, required=True, help="Second version number.")
@_json_option
@click.pass_context
@_handle_errors
def diff(ctx: click.Context, doc_id: str, v1: int, v2: int, as_json: bool) -> None:
    """Show field-level diff between two versions of a document."""
    store = _get_store(ctx)
    diff_result = store.diff_versions(doc_id, v1, v2)
    if as_json:
        _emit_json(diff_result)
    else:
        for field, changes in diff_result.items():
            click.echo(f"{field}:")
            click.echo(f"  v{v1}: {changes['old']}")
            click.echo(f"  v{v2}: {changes['new']}")
            click.echo()


# ---- kb import ---------------------------------------------------------------


@cli.command()
@click.argument("directory", type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("--dry-run", is_flag=True, help="Only show what would be imported, don't write anything.")
@_json_option
@click.pass_context
@_handle_errors
def import_cmd(ctx: click.Context, directory: str, dry_run: bool, as_json: bool) -> None:
    """Import Markdown files from a directory into the knowledge base."""
    store = _get_store(ctx)
    report = import_dir(store, Path(directory), dry_run=dry_run)
    if as_json:
        _emit_json(report.model_dump(mode="json"))
    else:
        click.echo(f"Imported {report.inserted + report.updated} files: {report.inserted} inserted, {report.updated} updated")
        if report.skipped > 0:
            click.echo(f"Skipped {report.skipped} files")
        if report.errors:
            click.echo(f"\nErrors:")
            for err in report.errors:
                click.echo(f"  - {err}")


# ---- kb export ---------------------------------------------------------------


@cli.command()
@click.argument("directory", type=click.Path(file_okay=False, dir_okay=True))
@click.option("--force", is_flag=True, help="Overwrite existing files.")
@_json_option
@click.pass_context
@_handle_errors
def export(ctx: click.Context, directory: str, force: bool, as_json: bool) -> None:
    """Export all documents as Markdown files to a directory."""
    store = _get_store(ctx)
    export_dir(store, Path(directory), force=force)
    if as_json:
        _emit_json({"exported_to": directory})
    else:
        click.echo(f"Exported all documents to {directory}")


# ---- kb doctor ---------------------------------------------------------------


@cli.command()
@_json_option
@click.pass_context
@_handle_errors
def doctor(ctx: click.Context, as_json: bool) -> None:
    """Run health checks on the knowledge base."""
    store = _get_store(ctx)
    report = store.doctor()
    if as_json:
        _emit_json(report.model_dump(mode="json"))
    else:
        click.echo(report.summary())


# ---- kb stats -----------------------------------------------------------------


@cli.command()
@_json_option
@click.pass_context
@_handle_errors
def stats(ctx: click.Context, as_json: bool) -> None:
    """Show knowledge base statistics."""
    store = _get_store(ctx)
    stats_data = store.stats()
    if as_json:
        _emit_json(stats_data)
    else:
        click.echo(f"Total documents: {stats_data['total_docs']}")
        click.echo(f"Total links: {stats_data['total_links']}")
        click.echo(f"Soft deleted: {stats_data['soft_deleted']}")
        click.echo(f"Changes in last 7 days: {stats_data['recent_changes']}")
        click.echo()
        click.echo("Documents by type:")
        for typ, cnt in stats_data["docs_by_type"].items():
            click.echo(f"  {typ}: {cnt}")


# ---- kb reindex ---------------------------------------------------------------


@cli.command()
@click.pass_context
@_handle_errors
def reindex(ctx: click.Context) -> None:
    """Rebuild the full-text search index."""
    store = _get_store(ctx)
    store.reindex()
    click.echo("Reindexed search index.")


# ---- kb prune ----------------------------------------------------------------


@cli.command()
@click.option("--older-than", default=30, type=int, show_default=True, help="Prune documents deleted more than N days ago.")
@_json_option
@click.pass_context
@_handle_errors
def prune(ctx: click.Context, older_than: int, as_json: bool) -> None:
    """Permanently delete soft-deleted documents older than the specified age."""
    from datetime import timedelta
    store = _get_store(ctx)
    deleted = store.prune(timedelta(days=older_than))
    if as_json:
        _emit_json({"deleted": deleted})
    else:
        click.echo(f"Permanently deleted {deleted} documents.")


# ---- kb serve ----------------------------------------------------------------


@cli.command()
@click.option("--transport", default="stdio", type=click.Choice(["stdio", "http"]), show_default=True)
@click.option("--port", default=8000, help="HTTP server port (only for http transport).")
@click.pass_context
@_handle_errors
def serve(ctx: click.Context, transport: str, port: int) -> None:
    """Start the MCP server."""
    store = _get_store(ctx)
    run_mcp_server(store, transport=transport, port=port)


# ---- vault commands ----------------------------------------------------------


@cli.group(name="vault")
def vault_group() -> None:
    """Manage multiple isolated knowledge bases (vaults)."""
    pass


@vault_group.command(name="list")
@_json_option
@click.pass_context
@_handle_errors
def vault_list(ctx: click.Context, as_json: bool) -> None:
    """List all available vaults."""
    vm = ctx.obj["vault_manager"]
    vaults = vm.list_vaults()
    if as_json:
        _emit_json([{"name": v.name, "path": v.path, "description": v.description, "sync_dir": v.sync_dir} for v in vaults])
    else:
        default_vault = ctx.obj["vault_manager"].get_current()
        click.echo(f"Default vault: {default_vault}")
        click.echo()
        click.echo("Available vaults:")
        for vault in vaults:
            is_default = "*" if vault.name == default_vault else " "
            click.echo(f"{is_default} {vault.name}: {vault.path}")


@vault_group.command(name="create")
@click.argument("name")
@click.option("--desc", help="Optional description for the vault.")
@_json_option
@click.pass_context
@_handle_errors
def vault_create(ctx: click.Context, name: str, desc: str | None, as_json: bool) -> None:
    """Create a new vault."""
    vm = ctx.obj["vault_manager"]
    vault_path = vm.create(name, description=desc)
    if as_json:
        _emit_json({"name": name, "path": str(vault_path.path)})
    else:
        click.echo(f"Created vault {name} at {vault_path.path}")


@vault_group.command(name="switch")
@click.argument("name")
@click.pass_context
@_handle_errors
def vault_switch(ctx: click.Context, name: str) -> None:
    """Set the default vault."""
    vm = ctx.obj["vault_manager"]
    vm.switch(name)
    click.echo(f"Default vault set to {name}")


@vault_group.command(name="init-git")
@click.option("--sync-dir", type=click.Path(exists=True, file_okay=False, dir_okay=True), required=True, help="Path to the Git repository to sync with.")
@click.pass_context
@_handle_errors
def vault_init_git(ctx: click.Context, sync_dir: str) -> None:
    """Initialize Git sync for the current vault."""
    vm = ctx.obj["vault_manager"]
    name = vm.get_current()
    output = vm.init_git(name=name, sync_dir=sync_dir)
    click.echo(output or f"Vault sync initialized with directory {sync_dir}")


@vault_group.command(name="commit")
@click.option("--message", "-m", required=True, help="Commit message.")
@click.pass_context
@_handle_errors
def vault_commit(ctx: click.Context, message: str) -> None:
    """Export changes and commit to Git."""
    vm = ctx.obj["vault_manager"]
    name = vm.get_current()
    output = vm.commit(message, name=name)
    click.echo(output or "Changes committed to Git.")


@vault_group.command(name="push")
@click.argument("remote", default="origin")
@click.argument("branch", default="main")
@click.pass_context
@_handle_errors
def vault_push(ctx: click.Context, remote: str, branch: str) -> None:
    """Push committed changes to remote Git repository."""
    vm = ctx.obj["vault_manager"]
    name = vm.get_current()
    output = vm.push(remote=remote, branch=branch, name=name)
    click.echo(output or "Changes pushed to remote.")


@vault_group.command(name="pull")
@click.argument("remote", default="origin")
@click.argument("branch", default="main")
@click.pass_context
@_handle_errors
def vault_pull(ctx: click.Context, remote: str, branch: str) -> None:
    """Pull latest changes from remote Git repository and import them."""
    vm = ctx.obj["vault_manager"]
    name = vm.get_current()
    output = vm.pull(remote=remote, branch=branch, name=name)
    click.echo(output or "Changes pulled and imported.")


# ---- admin commands ----------------------------------------------------------


@cli.group(name="admin")
def admin_group() -> None:
    """Web administration interface commands."""
    pass


@admin_group.command(name="start")
@click.option("--port", default=8888, type=int, help="Port to run the admin server on.")
@click.pass_context
@_handle_errors
def admin_start(ctx: click.Context, port: int) -> None:
    """Start the web administration interface."""
    from kb_mcp_lite.admin import run_admin
    store = _get_store(ctx)
    run_admin(store, port=port)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()


__all__ = [
    "cli",
    "main",
    "EXIT_OK",
    "EXIT_VALIDATION",
    "EXIT_NOT_FOUND",
    "EXIT_CONFLICT",
    "EXIT_INTERNAL",
    "EXIT_USAGE",
]
