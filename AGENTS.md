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