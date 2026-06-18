"""Click CLI entry point. Implementation lands in v0.1.1."""

import click


@click.group()
@click.version_option()
def main() -> None:
    """kb-mcp: agent-native knowledge base."""


@main.command()
def init() -> None:
    """Initialize a kb-mcp database in the default location."""
    click.echo("init: not yet implemented")


@main.command()
@click.option("--type", "doc_type", required=True, help="Document type")
@click.option("--title", required=True)
def add(doc_type: str, title: str) -> None:
    """Add a document."""
    click.echo(f"add: {doc_type} / {title!r} (not yet implemented)")


@main.command()
@click.argument("query")
def search(query: str) -> None:
    """Full-text search."""
    click.echo(f"search: {query!r} (not yet implemented)")


@main.command()
def serve() -> None:
    """Start MCP server on stdio."""
    click.echo("serve: not yet implemented")
