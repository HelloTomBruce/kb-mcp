# kb-mcp Quickstart

Install the package:

```bash
pip install kb-mcp-lite
```

Initialize a default vault:

```bash
kb init
```

Add a document:

```bash
kb add --type project --title "kb-mcp" \
  --tags "knowledge-base,mcp" \
  --body "Agent-native knowledge base backed by SQLite."
```

Search:

```bash
kb search "knowledge base"
kb search "mcp" --type project
kb search "fts5" --fuzzy
```

Start the MCP server for stdio clients:

```bash
kb serve
```

Start the Web admin UI:

```bash
kb admin start --port 8080
```

Manage vaults and Git sync:

```bash
kb vault --help
```
