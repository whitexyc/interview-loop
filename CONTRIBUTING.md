# 贡献指南

## 仓库结构

本仓库是一个 monorepo，包含三个技术栈与一个子项目：

| 目录 | 技术栈 | 测试 |
|---|---|---|
| `ai_service/` | Python 3.11 / FastAPI | `pytest`（1876 项）|
| `backend/` | Java / Spring Boot 3.2 | `mvn test` |
| `frontend/` | React 18 / Vite / TypeScript | `vitest`（63 项）|
| `interview-admin/` | Java / Spring Boot 3.2（第三方子项目）| `./mvnw test`（106 项，2 项已知红）|

## 本地环境

```bash
docker compose up -d          # PostgreSQL 16 + pgvector + AGE、Redis
python scripts/doctor.py      # 环境自检：先跑这个
```

再按 [README「快速开始」](README.md#快速开始) 下载本地模型并启动各服务。

> `scripts/doctor.py` 覆盖的都是真实踩过的坑（Redis 密码不一致、JWT 密钥不一致会
> **静默**降级为按 IP 隔离、`no_proxy` 含 `[::1]` 会让 httpx 崩溃等）。改动环境相关
> 代码后请顺手跑一遍。

## 提交前

- 改动哪个栈就跑哪个栈的测试；跨栈改动请全跑
- 新增功能补充最小可验证测试（本项目的评测与验收均为**确定性判定**，不用 LLM 评 LLM）
- **不要提交真实密钥**：凭据一律走环境变量（`ai_service/.env` 已在 `.gitignore` 中，
  参考 `ai_service/.env.example`）
- 不要把模型权重、构建产物、`docs/`、`.workbuddy/`、IDE 私有文件提交进来

## 本项目的工作流约定

这个项目用一套模块制流程做迭代，欢迎沿用：

- **模块规格**：较大的改动在 `specs/module-XXX-*/` 下放五件套 ——
  `plan.md` / `acceptance-criteria.md` / `changelog.md` / `review-report.md` / `test-report.md`
- **架构决策**：关键选型写 ADR 放 `specs/adr/`（已有 23 份可参考）
- **红线**：单个模块的生产代码 **AST ≤ 200 行**；改前说明影响面、改后跑全量回归
- **判据事前定死**：涉及性能/质量对比的改动，先把判据写进 plan，再跑数据；
  结论不利也照实记录（见 [`METRICS.md`](METRICS.md) 与 module-091/092/093）

## 分支与提交

- 分支：`feature/<topic>`、`fix/<topic>`、`docs/<topic>`
- 提交信息直接说明意图，可用前缀：`[feat]` / `[fix]` / `[docs]` / `[chore]` / `[security]`

## Pull Request

PR 描述建议包含：

- 变更背景与要解决的问题
- 主要实现点
- 兼容性或风险说明
- 测试方式与实测结果（贴关键输出，而不是「已测试」）
- 涉及接口或 UI 时附截图 / 响应示例

## 文档

- 用户可见说明进 README（中英双版：`README.md` / `README_en.md`）
- 量化指标以 [`METRICS.md`](METRICS.md) 为单一事实源，避免多处各写一份数字
- `interview-admin/` 的界面素材放 `interview-admin/docs/assets/`
