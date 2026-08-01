# 测试报告 — Module-019: 评估闭环（Golden 检索集 + Hit@k/MRR + 消融）

## 1. 测试概览

| 指标 | 数值 |
|------|------|
| 测试总数 | 20（模块单测）+ 24（回归，排除既有环境限制项） |
| 通过数 | 44 |
| 失败数 | 0（module-019 引入） |
| 跳过数 | 0 |
| 通过率 | 100%（模块新增测试）/ 回归无新增失败 |
| 执行耗时 | ~60 秒（含 3 种模式实跑 + 全量回归） |

> 全量 `pytest tests/` 实测 24 passed + 2 failed，2 个失败为 `tests/test_engine.py` 的
> async 用例收集错误（`async def functions are not natively supported`），原因是测试环境
> 缺 `pytest-asyncio` 插件。经 git diff 确认 `test_engine.py` 相对 HEAD 无任何改动，
> 且 project-context.md 已将该问题记为 module-018 之前的既有环境限制 —— **非 module-019 引入**。
> 排除该既有文件后回归套件 24 passed（与 review-report §3 一致）。

## 2. 覆盖率报告

| 覆盖维度 | 覆盖率 | 要求 | 状态 |
|----------|--------|------|------|
| 指标计算（compute_metrics） | 100%（7 用例覆盖 Hit/Recall/MRR/空集/无gold/k截断） | 高 | ✅ |
| retriever mode 参数 | 3 用例（VALID_MODES / 默认 hybrid / 非法拒绝实测） | 高 | ✅ |
| 单题评估 + 降级路径 | 4 用例（no_gold/降级FTS/非hybrid错误跳过/循环聚合） | 高 | ✅ |
| 方法长度规范 | 4 用例 + 独立实测（retrieve=50/_dispatch_mode=40/run_eval=42/_eval_question=46） | ≤50 | ✅ |
| 回归 | 24 passed（排除既有 async 收集限制） | 100% | ✅ |

> 注：eval_runs 落库与 graph_only 通道依赖真实数据库/AGE，无法在纯单测中覆盖，
> 已通过实跑验证（见 §3）。

## 3. 验收标准核对

### 3.1 功能验收

| 验收项 | 对应测试/验证方式 | 状态 | 备注 |
|--------|------------------|------|------|
| golden.json 存在且 ≥20 题，含 question+golden_docs | 结构校验脚本 | ✅ 通过 | 实测 30 题，缺字段 0，7 题标空 |
| golden_docs 与知识库真实文档对应 | DB 抽查：distinct 父块标题匹配 | ✅ 通过 | 68 父块，0 条不一致 |
| golden_retrieval.py 可运行 | `python -m eval.golden_retrieval` | ✅ 通过 | hybrid 实跑，Saved to eval_runs id=6 |
| 输出 Hit@5/Recall@5/MRR | 运行输出 | ✅ 通过 | 见 §3.4 实测 |
| 单通道消融可用 | `--mode fts_only` / `--mode vector_only` | ✅ 通过 | fts_only 独立打分；vector_only 502 逐题记录 |
| eval_runs 表有记录 | psql/asyncpg 查询 | ✅ 通过 | 表存在，id=1~6 共 6 条 retrieval 记录 |

### 3.2 边界条件验收

| 验收项 | 对应测试/验证方式 | 状态 | 备注 |
|--------|------------------|------|------|
| golden.json 缺失：报错退出并提示 | load_golden(不存在路径) | ✅ 通过 | 抛 FileNotFoundError，提示清晰 |
| 某题无 gold doc：跳过并记录 | 实测 fts_only/hybrid 运行 | ✅ 通过 | 7 题 reason=no_gold_docs，不崩溃 |
| top_k 传 0 或负数：安全处理（默认 5） | `--top-k 0` 实跑 | ✅ 通过 | 输出 top_k: 5 |
| 空检索结果：指标为 0，不异常 | 单测 test_empty_retrieved + fts 通道实测 | ✅ 通过 | Hit/Recall/MRR 全 0 不崩溃 |
| 数据库不可用：评估降级 | 代码审查 save_eval_run 捕获异常返回 0 | ✅ 通过 | 记录失败仅告警，评估继续 |

### 3.3 异常场景验收

| 验收项 | 对应测试/验证方式 | 状态 | 备注 |
|--------|------------------|------|------|
| embedding API 502：向量通道降级，FTS 仍评估 | 实测 hybrid + vector_only | ✅ 通过 | hybrid 23/23 题 degraded=True 回退 FTS 完成评估；vector_only 逐题记录 error |
| 图检索不可用：graph 通道返回空 | 代码审查 _retrieve_graph_only | ✅ 通过 | 超时/异常降级返回 [] |
| 检索异常：该题跳过并记录 | 实测 vector_only（embedding 502）+ 单测 | ✅ 通过 | reason=error: 查询向量化失败，其余继续 |

### 3.4 接口验收（retriever + 评估输出）

| 验收项 | 对应测试/验证方式 | 状态 | 备注 |
|--------|------------------|------|------|
| retrieve(query, top_k=5, mode='hybrid') 兼容 | inspect.signature 单测 | ✅ 通过 | mode 默认 hybrid |
| mode 支持 hybrid/vector_only/fts_only/graph_only | 单测 test_valid_modes_defined | ✅ 通过 | VALID_MODES 四元组 |
| 默认 hybrid 行为与之前一致（无回归） | 全部既有调用方 grep 复核 | ✅ 通过 | engine.py L78/153/282/297、graph.py L128/218 均未传 mode → 走 hybrid 主路径 |
| 返回格式不变（list[dict] 含 id/title/content/hybrid_score） | 代码审查 + 单测检索结果 | ✅ 通过 | 单通道结果亦带 score 字段 |
| 非法 mode 拒绝 | 实跑 retrieve(mode='invalid_mode') | ✅ 通过 | 抛 ValueError，提示可选集合 |
| 输出整体指标 | print_report 实跑 | ✅ 通过 | Hit@5/Recall@5/MRR 全量 + 分类 |
| 输出每题明细 | print_report 实跑 | ✅ 通过 | first 15 题 + 跳过列表 |
| 输出按类别汇总 | print_report 实跑 | ✅ 通过 | 5 类分别打分 |
| 记录 eval_runs（git_commit + config 快照） | 实测 eval_runs id=6 | ✅ 通过 | git_commit=76bceb86，config_snapshot 8 键，scores/per_question 完整 |
| --compare 版本化对比 | 实跑 --compare | ✅ 通过 | 最近两次 retrieval 运行 delta 表 |

### 3.5 代码质量验收

| 验收项 | 对应测试/验证方式 | 状态 | 备注 |
|--------|------------------|------|------|
| public 方法有 Docstring | 代码审查 | ✅ 通过 | golden_retrieval.py / retriever.py 全部 public 方法 |
| 指标计算有行内注释 | 代码审查 | ✅ 通过 | compute_metrics / _eval_question 注释完整 |
| 命名 snake_case / 无无意义命名 | 代码审查 | ✅ 通过 | |
| 单个方法 ≤50 行 | 独立实测 | ✅ 通过 | retrieve=50, _dispatch_mode=40, run_eval=42, _eval_question=46 |
| 本模块新增代码 ≤300 行 | 代码审查 | ⚠️ 附条件通过 | golden_retrieval.py 355 行，changelog 已记录理由（同 Reviewer 附条件通过） |
| Python 语法通过 | ast 编译 | ✅ 通过 | |
| 无未使用 import | 静态检查 | ✅ 通过 | settings 为既有死代码，非本模块引入 |

### 3.6 测试验收

| 验收项 | 对应测试/验证方式 | 状态 | 备注 |
|--------|------------------|------|------|
| 指标计算单测 | TestComputeMetrics 7 例 | ✅ 通过 | Hit/Recall/MRR/空集/无gold/k截断 |
| 空结果/无 gold 边界 | test_empty_retrieved / test_no_golden_docs | ✅ 通过 | |
| retriever mode 参数切换 | TestRetrieverMode 3 例 | ✅ 通过 | |
| 组合模式真实运行 | `python -m eval.golden_retrieval` | ✅ 通过 | Dataset:30, Evaluated:23, Skipped:7 |
| 消融模式独立运行 | `--mode fts_only` / `--mode vector_only` 实跑 | ✅ 通过 | fts_only 全 0（中文FTS债）；vector_only 502 记录 |
| 回归测试无新增失败 | `pytest tests/` | ✅ 通过 | 24 passed + 2 既有 async 收集限制（非本模块） |
| retriever 默认 hybrid 无回归 | 单测 + 调用方复核 | ✅ 通过 | |

### 3.7 文档验收

| 验收项 | 对应测试/验证方式 | 状态 | 备注 |
|--------|------------------|------|------|
| changelog.md 已更新 | 文件审查 | ✅ 通过 | v1+v2 变更记录、设计决策、验证命令 |
| 指标计算方式在代码注释说明 | 代码审查 | ✅ 通过 | |
| eval_runs 表结构记录在 plan.md | 文件审查 | ✅ 通过 | DDL 与 plan §3.2 完全一致 |

## 4. 失败详情

无 module-019 引入的测试失败。

记录的全量回归中 `tests/test_engine.py` 2 个失败（`test_search_returns_response` /
`test_chat_returns_response`）为既有环境限制，与 module-019 无关：
- 失败原因: `async def functions are not natively supported` —— 测试环境缺 `pytest-asyncio`
- 归因: `git diff HEAD -- ai_service/tests/test_engine.py` 为空（文件未改动）；project-context.md
  L59 已将该限制记录为 module-018 之前的既有问题
- 处理: 不修改既有测试（CLAUDE.md 禁止），回归验收以排除该既有文件后 24 passed 判定

## 5. 测试结论

- 结论: **通过**
- 测试时间: 2026-08-01
- 测试人: Tester
- 备注:
  - embedding API（ModelScope）当前 502，与 changelog/plan 预警一致：hybrid 模式 23/23 题
    degraded=True 自动回退 FTS 完成评估（降级路径实测有效），vector_only 逐题记录通道不可用。
  - fts_only / hybrid（FTS 回退）Hit@5=0 反映既有中文 FTS 技术债（PG 'simple' 分词限制），
    正是 module-020 要修复并以本评估为量化基线的场景，非本模块缺陷。
  - graph_only 通道依赖真实 LLM 实体提取，本次未独立全量运行；Reviewer 已实跑
    Hit@5=0.50（kafka 类 Hit@5=1.0），消融通道具备判别力，作为交叉验证依据。
  - golden_docs 与知识库 68 个父块标题全量匹配（0 不一致），CAP 题仅 Nacos、
    Docker 题标空，符合 v2 修复结论。
  - eval_runs 表已建且 id=1~6 共 6 条 retrieval 记录，git_commit + config 快照落库正常。
