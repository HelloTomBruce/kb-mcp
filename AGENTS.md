# 红线
- 未经用户主动要求，禁止提交代码
- 在执行 `git push` 推送远程仓库前，必须在本地完整运行并全绿通过以下 CI 质量体检流水线：
  ```bash
  # 1. 代码格式化与规范修复
  uvx ruff format . && uvx ruff check --fix .
  # 2. 静态类型检查
  uvx --with ".[dev,vec,v0_8]" mypy src/
  # 3. 全量单测验证
  uvx --with ".[dev,vec,v0_8]" pytest -q
  ```
  若有前端代码（`web/`）修改，需先在 `web/` 目录执行 `npm run build` 确保前端构建无报错。只有全部通过后方可执行 push。

---

# kb-mcp AI 协同开发规约：代码与 DocMind 产品文档双向维护

本项目已接入 **DocMind 知识工作台**（结构化 PRD 思维导图与文档系统）。
在任何功能迭代、Bug 修复、MCP 工具扩展或架构重构过程中，**代码与 DocMind 中的产品文档必须通过 MCP 保持双向同步**。

## 1. DocMind 基础设施信息
- **MCP 服务**：`DocMind`（SSE: `http://127.0.0.1:6001/sse`）
- **项目定位**：完全通过 DocMind MCP 接口操作维护，**无需关心本地物理路径**。操作前直接调用：
  ```json
  activate_project({ "name": "kb-mcp" })
  ```
- **核心需求模块树（14 个全景模块）**：
  - `01 产品概述与定位`：AI 原生知识库服务、双向链接、Token 保护与定位
  - `02 文档模型与强 Schema 类型体系`：Frontmatter 校验、Schema 强类型约束
  - `03 多模式智能搜索与 RAG 管线`：BM25 + 向量混合检索、Token 预算保护
  - `04 语义嵌入与异步队列`：异步 Embedding、批量处理与队列重试
  - `05 版本控制与审计`：快照历史、Diff 审计、软删除与恢复
  - `06 类型化知识图谱`：关系词汇定义、双向链接拓扑、影响分析与决策链
  - `07 Git 团队协作与智能合并`：三方智能合并、冲突预防、文件变更监听
  - `08 多 Vault 管理与跨库检索`：多工作区路由、跨库隔离与联邦检索
  - `09 智能计划任务调度`：APScheduler 定时任务、备份与自动化维护
  - `10 MCP 协议服务层`：24+ 个标准 MCP 工具定义与 JSON-RPC 协议
  - `11 CLI 命令行工具`：kb 命令行体系、交互式终端工具
  - `12 Web 管理控制台`：Vue/SPA 控制台、知识图谱可视化、文档编辑器
  - `13 健康诊断与数据维护`：kb_doctor 诊断、ContextGuard 与孤岛检测
  - `14 技术架构与数据模型`：Python 后端架构、SQLite 虚表与数据存储

## 2. 迭代协同标准工作流 (AI 必须严格执行)

### 阶段一：任务开始（需求对齐与状态流转）
1. **激活项目并查阅规格**：
   - 接收任务后，先调用 `activate_project({ "name": "kb-mcp" })`；
   - 调用 `search_requirements` 或 `get_requirement_detail` 查阅目标模块的产品定义与技术约定（例如改动 MCP 工具查阅模块 10，改动图谱查阅模块 06，改动 Web 控制台查阅模块 12）；
   - 若用户提出新功能或新增工具，调用 `add_node` 在对应模块下创建需求节点并补充规格草案。
2. **状态流转**：
   - 调用 `update_requirement_status(node_id, "in_progress")`。

### 阶段二：代码实现与红线检查
- 严格遵守顶部的质量红线（ruff format/check、mypy 类型检查、pytest 全绿、web build 成功）；
- 未经用户明确要求，严禁私自提交 git commit。

### 阶段三：交付闭环（文档同步与状态闭环）
1. **同步更新产品文档**：
   - 编码完成后，若涉及**新增/修改 MCP 工具入参输出、Schema 规则变动、图谱词汇扩展、CLI 命令增删或 Web 界面调整**，必须同时调用 `update_node` 同步更新 DocMind 对应模块的 Markdown 需求规格；
   - 严禁“只改代码不改 PRD”导致文档漂移。
2. **状态闭环**：
   - 调用 `update_requirement_status(node_id, "completed")`。
3. **交付报告输出**：
   - 汇报时向用户清晰列出代码修改文件清单，以及同步更新的 DocMind PRD 模块名称与变更点。