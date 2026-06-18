# kb-mcp

Agent-native knowledge base. SQLite + FTS5 + MCP server.

A single-binary knowledge base that any LLM agent can query via the Model
Context Protocol (MCP), and any human can drive from the terminal. Markdown
in, structured documents out. Zero external dependencies by default.

## Why

Knowledge bases for humans (Notion, Obsidian) and for search engines
(Elasticsearch, vector DBs) leave a gap: **agents need a knowledge layer
that speaks their protocol.** `kb-mcp` fills it.

- **MCP-native.** Every document is reachable from any MCP client
  (`Claude Desktop`, `Cursor`, `OpenCode`, etc.) via `kb_search`,
  `kb_get`, `kb_add`, `kb_link`.
- **Schema-first.** Documents have typed fields (`type`, `title`,
  `tags`, `source`, `links`), not just free-form markdown.
- **Local-first.** SQLite + FTS5 in your `~/.local/share/kb-mcp/`.
  No server, no cloud, no telemetry.
- **Markdown friendly.** Import/export round-trips with frontmatter.

## Install

\`\`\`bash
pip install kb-mcp
\`\`\`

## Quickstart

\`\`\`bash
kb init                       # creates ~/.local/share/kb-mcp/kb.db
kb add --type project --title "kb-mcp" --tags kb,mcp,open-source
kb search "mcp server"
kb serve                      # start MCP server on stdio
\`\`\`

## Document Types

Six built-in types, all user-extensible:

| Type      | Purpose                              |
| --------- | ------------------------------------ |
| `project` | Repo / initiative background         |
| `decision`| Architecture Decision Record (ADR)  |
| `lesson`  | Post-mortem / lessons learned        |
| `glossary`| Term definitions                     |
| `person`  | People the agent should recognise   |
| `faq`     | Frequently asked questions           |

## License

MIT
