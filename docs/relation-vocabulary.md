# Relation Vocabulary

kb-mcp v0.8 introduced a typed relation vocabulary that gives semantic meaning to document links.

## Standard Relations

| Name | Forward Label | Influence | Supersession | Description |
|------|--------------|-----------|--------------|-------------|
| `relates-to` | 与...相关 | - | - | 通用关联，无方向语义 |
| `supersedes` | 取代了 | ✓ | ✓ | 本决策/方案取代了目标 |
| `superseded-by` | 被...取代 | ✓ | ✓ | 本决策/方案已被目标取代 |
| `depends-on` | 依赖于 | ✓ | - | 本方案/组件的运行依赖目标 |
| `blocks` | 阻塞 | ✓ | - | 本任务阻塞了目标任务的执行 |
| `implements` | 实现了 | - | - | 本组件/模块实现了目标的接口/规范 |
| `references` | 引用了 | - | - | 正文中提到的目标（自动提取） |
| `governs` | 约束了 | ✓ | - | 本规范/政策约束了目标的实现方式 |
| `owned-by` | 归属于 | - | - | 本资源/项目的负责人 |
| `tagged-with` | 标记为 | - | - | 通过 tag 关联的同主题文档 |

### Influence vs Non-Influence

- **Influence** relations (`supersedes`, `superseded-by`, `depends-on`, `blocks`, `governs`) participate in **impact analysis** — when a document changes, all downstream influenced documents are identified.
- **Non-influence** relations are structural links that don't propagate impact.

### Supersession Chain

Relations marked as **supersession** (`supersedes`, `superseded-by`) form decision evolution chains. Use `kb chain <decision-id>` to trace how a decision has evolved over time.

## Custom Relations

Users can add custom relations in `~/.config/kb-mcp/config.yaml`:

```yaml
kb:
  custom_relations:
    - name: "on-call-for"
      forward_label: "on-call 负责"
      backward_label: "由...on-call"
      is_influence: false
      description: "person X on-call 负责 service Y"
    - name: "postmortem-of"
      forward_label: "事后总结"
      backward_label: "事后总结"
      is_influence: false
      description: "本 lesson 总结了 incident X"
```

Custom relations must be lowercase and must not conflict with standard relation names.

## Unknown Relations

Any relation string not in the standard or custom vocabulary is treated as `relates-to` for traversal purposes — this ensures backward compatibility.

## CLI Commands

```bash
kb rel list                    # List all standard relations
kb rel show supersedes         # Show details for a specific relation
kb impact <doc-id>             # Impact analysis (follows influence edges)
kb chain <doc-id>              # Trace supersession chain
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `kb_rel_spec(rel_name?)` | List all relations or show details for one |
| `kb_impact(doc_id, max_depth?)` | Impact analysis from a root document |
| `kb_decision_chain(decision_id)` | Trace supersession chain |
| `kb_expand(doc_id, depth?, max_neighbors?)` | Graph expansion (1-hop neighbors) |
