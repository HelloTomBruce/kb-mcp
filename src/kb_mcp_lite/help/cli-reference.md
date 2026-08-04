# kb-mcp CLI Reference

All commands support `--help`. Machine-readable output is available with
`--json` where documented.

## Document Commands

```text
kb init
kb add --type TYPE --title TITLE [--body BODY] [--tags a,b] [--aliases a,b]
kb get ID
kb update ID [--title TITLE] [--body BODY] [--tags a,b] [--aliases a,b]
kb delete ID
kb restore ID [--version N]
kb restore_deleted ID
kb diff ID --v1 N --v2 N
kb history ID
```

## Search and Links

```text
kb search QUERY [--type TYPE] [--tags a,b] [--fuzzy] [--limit N]
kb list [--type TYPE] [--tags a,b] [--limit N]
kb link FROM_ID TO_ID [--rel REL]
kb unlink FROM_ID TO_ID [--rel REL]
kb links ID
```

## Maintenance

```text
kb doctor
kb stats
kb embed [--rebuild]
kb reindex
kb prune [--older-than DAYS]
kb import DIRECTORY [--dry-run]
kb export DIRECTORY [--force]
```

## Serving

```text
kb serve
kb admin start --port 8080
kb vault create NAME
kb vault switch NAME
kb vault status
kb vault pull
kb vault push
kb vault commit
```
