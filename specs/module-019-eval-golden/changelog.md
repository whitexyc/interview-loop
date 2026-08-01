# 变更日志 — Module-019: 评估闭环（Golden 检索集 + Hit@k/MRR + 消融）

## 变更概述

建立 RAG 召回侧的量化评估闭环：为现有 eval/dataset.json 的 30 题标注 golden_docs
（与知识库真实父块标题一一对应），新增 golden_retrieval.py 评估脚本计算
Hit@k / Recall@k / MRR，支持 hybrid / vector_only / fts_only / graph_only 四种
单通道消融，并将每次运行（git_commit + rag_config 配置快照 + 分数 + 每题明细）
记录到 eval_runs 表，实现版本化回归对比。retriever.retrieve() 增加 mode 参数，
默认 hybrid 与原行为完全一致（零回归）。

## 文件变更列表

| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| ai_service/eval/golden.json | 新增 | 30 题 golden_docs 标注（24 题有 gold，6 题知识库无覆盖标注为空） |
| ai_service/eval/golden_retrieval.py | 新增 | 召回评估脚本（Hit@k/Recall@k/MRR + 消融 + eval_runs 记录 + --compare） |
| ai_service/create_eval_runs_table.py | 新增 | eval_runs 表 DDL 脚本（幂等，DDL 单源在 golden_retrieval.py） |
| ai_service/tests/test_golden_retrieval.py | 新增 | 指标计算与 mode 参数单元测试（10 例） |
| ai_service/rag/retriever.py | 修改 | retrieve() 增加 mode 参数（hybrid/vector_only/fts_only/graph_only）+ VALID_MODES |
| ai_service/eval/evaluate.py | 修改 | 注入 eval_runs 版本化记录（eval_type='ragas'，plan §3.1） |
| ai_service/rag/graph_store.py | 修改 | 修复 search_related 两处既有 bug（block graph_only 通道，见设计决策 7） |

## 关键设计说明

### 设计决策 1: golden_docs 基于真实父块标题 + 空标注策略
- 决策: 逐题核对知识库 documents 表（parent_id IS NULL，68 篇父块），
  仅标注与题目内容真实相关的文档标题；知识库无覆盖的题目
  （5 题简历 + HTTP/2）golden_docs 标注为空列表。
- 原因: 标注非真实文档会导致指标失真（plan §6.1 风险）；空标注走
  "某题无 gold doc：跳过并记录" 的异常路径（plan §3.5），如实反映
  知识库覆盖盲区，不伪造召回。

### 设计决策 2: 检索命中按标题精确匹配
- 决策: 检索返回子块，实测子块标题与父块标题 100% 一致（68/68 exact），
  因此按 `retrieved_title in golden_titles` 精确匹配即可，跳过
  _expand_to_parents（plan §6.2 提示可跳过）。
- 原因: 简单可靠；知识库存在同一标题的多份副本（obsidian/backend-push/
  llm-push 三批入库），标题匹配天然兼容重复文档。

### 设计决策 3: 单通道消融的降级语义
- 决策: retriever.retrieve(mode=...) 中，vector_only 向量化失败抛
  RetrievalException；fts_only 不需要 embedding 可独立评估；graph_only
  复用 engine._retrieve 的图路径（LLM 提取实体 → search_related），
  任一步失败/超时降级返回空（§3.5）。
- 原因: 各通道独立打分互不影响；graph_only 需要 LLM 提取实体，这是
  图检索的固有依赖，不可用时如实记 0。

### 设计决策 4: 评估脚本的 hybrid 降级回退
- 决策: eval 脚本在 hybrid 模式遇到 RetrievalException（embedding 502）
  时自动回退为 fts_only 继续评估，并在每题明细标记 degraded=True；
  vector_only 遇到 embedding 失败则如实记录通道不可用。
- 原因: 满足"向量通道失败时 FTS 仍可评估"的降级要求，且不改动
  retriever 的 hybrid 默认行为（保持零回归）。

### 设计决策 5: eval_runs DDL 单源 + 自愈建表
- 决策: DDL（CREATE TABLE + COMMENT）定义在 golden_retrieval.py 的
  EVAL_RUNS_DDL，save_eval_run 前自动执行 ensure_eval_runs_table()；
  create_eval_runs_table.py 是独立入口脚本。DDL 含多条语句，
  asyncpg 不允许单条 prepared statement 含多命令，故按 ';' 拆分逐条执行。
- 原因: 评估脚本自愈建表避免"表不存在"失败；JSONB 参数统一
  `CAST(:x AS jsonb)` 传入 JSON 字符串，规避 asyncpg 类型编码问题。

### 设计决策 6: evaluate.py 注入 eval_runs（RAGAS 侧）
- 决策: 复用 golden_retrieval 的落库函数，RAGAS 评估完成后以
  eval_type='ragas' 记录 summary/耗时/per_question，记录失败仅告警。
- 原因: 满足 plan §3.1 的 evaluate.py 修改项，让生成侧评估也能参与版本化回归。

### 设计决策 7: 修复 graph_store.search_related 两处既有 bug（module-016 遗留）
- 决策: ① `[:RELATED_TO]` 改为 `[r:RELATED_TO]`——SQLAlchemy text() 把
  前置 `[` 的 `:RELATED_TO` 解析成 bind 参数（报 "A value is required for
  bind parameter 'RELATED_TO'"），命名关系变量 r 使冒号前为单词字符、
  不再被解析为参数（与 `(e:Entity)` 同理）；② 移除 `doc_ids::TEXT` 强转——
  AGE openCypher 不支持 TEXT 类型（报 "type TEXT does not exist"），
  实测 AGE 返回的 agtype 数组 str() 即 JSON 兼容双引号形式，Python 侧
  json.loads 可直接解析，删除强转后语义不变。
- 原因: 该 bug 使 graph_only 消融通道（及生产 engine._retrieve 的图路径）
  恒返回空，属本模块必需通道的阻塞问题（developer.md §2.5 自测归因修复）；
  改动为 module-016 遗留代码，提请 Reviewer 关注。

## 验证命令

| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| golden 集加载 | `python -c "import json; d=json.load(open('eval/golden.json',encoding='utf-8')); assert len(d)>=20; [print(x['question'][:20], len(x['golden_docs'])) for x in d]"` | 30 题，无异常 |
| 建表 | `python create_eval_runs_table.py` | ✅ eval_runs 表已就绪 |
| 单元测试 | `python -m pytest tests/test_golden_retrieval.py -v` | 10 passed |
| 组合模式 | `python -m eval.golden_retrieval` | 输出 Hit@5/Recall@5/MRR + 明细 + Saved to eval_runs |
| 消融 fts_only | `python -m eval.golden_retrieval --mode fts_only` | 独立打分 |
| 消融 vector_only | `python -m eval.golden_retrieval --mode vector_only` | embedding 502 时逐题记录通道不可用 |
| 消融 graph_only | `python -m eval.golden_retrieval --mode graph_only` | 图通道打分或降级为空 |
| 版本化 | `python -m eval.golden_retrieval --compare` | 最近两次运行 delta 表 |
| 回归 | `python -m pytest ai_service/tests/ -x` | 无新增失败（含既有 async 用例收集限制） |

## 实测结果（2026-08-01，embedding API 502 环境）

| 模式 | Evaluated | Hit@5 | Recall@5 | MRR | 说明 |
|------|-----------|-------|----------|-----|------|
| hybrid（自动降级 FTS） | 24 | 0.0000 | 0.0000 | 0.0000 | 24/24 题 degraded=True，回退 FTS |
| fts_only | 24 | 0.0000 | 0.0000 | 0.0000 | 中文查询 FTS 无命中（'simple' 分词限制，既有问题） |
| vector_only | 0 | — | — | — | embedding 502，逐题记录通道不可用 |
| graph_only | 24 | 0.5000 | 0.4375 | 0.2361 | 图通道有效（kafka 类 Hit@5=1.0），依赖 LLM 实体提取 + 图遍历 |

> 注：Hit@5=0（FTS 通道）反映的是既有检索技术债（中文 FTS 未生效 + embedding 502），
> 正是 module-020「中文FTS/缓存修复」要用本评估作为量化基线的场景；
> 本模块交付的是评估基础设施本身。graph_only 通道在修复 graph_store 两处既有 bug 后
> 已能真实检索（kafka 5 题全命中），验证消融通道具备判别力。

> 代码量说明：golden_retrieval.py 355 行（超出 plan §1 调整后的 300 行上限）。
> 原因：脚本承载 6 个 plan 必选能力（指标计算/聚合/消融降级/eval_runs 落库/
> --compare/CLI 报告），且按项目规范所有 public 方法均带完整 Docstring、
> 指标定义与降级策略有行内注释。golden.json 为数据标注（167 行，不计入代码量）。
> 沿用 plan §1 的调整机制，在 changelog 中说明理由。

> 注：Hit@5=0 反映的是既有检索技术债（中文 FTS 未生效 + embedding 502），
> 正是 module-020「中文FTS/缓存修复」要用本评估作为量化基线的场景；
> 本模块交付的是评估基础设施本身。

---

## 变更概述（v2 — Reviewer 反馈修复）

按 review-report.md 修复 4 项问题：① CAP 题移除 HashMap 误标（MIN_TREEIFY_CAPACITY
子串误命中，全文无 CAP 定理内容），golden_docs 仅保留 Nacos；② Docker 题按模块
"无覆盖标空"策略改标空列表，由评估脚本走 no_gold_docs 跳过；③ golden_retrieval.py
`run_eval`（71 行）拆分为 `_eval_question`（单题评估 + 降级）+ `run_eval`（循环聚合），
两方法 42/46 行；④ retriever.py `retrieve`（74 行）将 fts_only/vector_only/graph_only
三通道分派抽为 `_dispatch_mode` 私有方法，`retrieve` 缩至 50 行（hybrid 主路径零改动）。
同时新增 10 例回归测试（数据标注 / 单题降级 / 循环聚合端到端 / 方法行数上限）。

## 文件变更列表（v2）

| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| ai_service/eval/golden.json | 修改 | CAP 题移除 HashMap 误标；Docker 题改标空（7 题无 gold） |
| ai_service/eval/golden_retrieval.py | 修改 | run_eval 拆分 `_eval_question`（单题评估 + hybrid 降级 FTS），run_eval 仅循环 + 聚合 |
| ai_service/rag/retriever.py | 修改 | retrieve 三通道分派抽为 `_dispatch_mode`；精简 docstring/注释到 50 行内 |
| ai_service/tests/test_golden_retrieval.py | 修改 | 新增 10 例回归测试（共 20 例） |
| specs/module-019-eval-golden/changelog.md | 修改 | 追加 v2 变更记录 |

## 关键设计说明（v2）

### 设计决策 1: CAP 题标注按内容语义而非关键词子串
- 决策: 移除 12-HashMap 标注，golden_docs 仅保留 8-Spring-Cloud-Nacos。
- 原因: HashMap 文档唯一 "CAP" 匹配为 MIN_TREEIFY_CAPACITY 子串，无 CAP 定理实质
  内容；错误标注虚增 Recall@k 分母（2→本应 1）并把无关文档检索计为命中。

### 设计决策 2: Docker 题按"无覆盖标空"与 HTTP/2、简历 5 题一致
- 决策: golden_docs 改空列表，评估脚本走 no_gold_docs 跳过并记录。
- 原因: 18-JVM 文档对 Docker 仅一句带过，无 Docker vs 虚拟机核心区别；知识库无
  Docker 主题文档，硬塞标注会把"检索到 JVM 文档"误记为 Docker 题命中。

### 设计决策 3: run_eval / retrieve 拆分保证方法 ≤ 50 行
- 决策: `_eval_question(item, mode, top_k)` 返回 (evaluated, skipped) 二元组承载
  单题检索 + 指标 + 降级/失败处理；`run_eval` 仅循环 + 按 reason 分类日志 + 聚合。
  `_dispatch_mode(query, top_k, session, mode)` 承载 fts_only/vector_only/graph_only
  分派，hybrid 主路径保留在 retrieve 内原样。
- 原因: 满足 CLAUDE.md「方法 ≤ 50 行」；拆分为纯重构，指标与降级语义不变
  （log 消息按 reason 前缀在 run_eval 还原，hybrid 降级警告保留在 _eval_question）。

### 设计决策 4: 回归测试用 mock.AsyncMock 打桩 retrieve，规避数据库依赖
- 决策: 单测在 retrieve 子 mock 上配置 side_effect/return_value（不可配在父 mock，
  属性访问会新建无配置子 mock），经 asyncio.run 直接驱动 _eval_question / run_eval。
- 原因: 端到端验证数据修复（CAP 命中、Docker 跳过）+ 重构行为不变，全程不依赖
  数据库 / embedding / pytest-asyncio。

## 验证命令（v2）

| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| 单测 | `python -m pytest tests/test_golden_retrieval.py -v` | 20 passed |
| 全量回归 | `python -m pytest tests/ --ignore=tests/test_engine.py -q` | 24 passed |
| 评估脚本 | `python -m eval.golden_retrieval --mode fts_only --no-save` | Dataset:30 \| Evaluated:23 \| Skipped:7，Docker 题 reason=no_gold_docs |
| golden 集 | load_golden() 加载 | 30 题，7 题无 gold（CAP 仅 Nacos） |

## 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-01 | 初始实现：golden.json + golden_retrieval.py + retriever mode + eval_runs 表 + 单测 | Developer |
| v2 | 2026-08-01 | 修复 Review 4 项：CAP/Docker 标注修正 + run_eval/retrieve 方法拆分 + 10 例回归测试 | Developer |
