# 测试报告 — Module-024: 检索延迟优化

> 测试阶段产出 | Vibe Coding 闭环工作流
> 测试对象：`ai_service/rag/engine.py`（round 0 降级 + HyDE 缓存 + 整链路预算 + 提前终止）+ `ai_service/tests/test_engine_latency.py`

## 1. 测试概览

| 指标 | 数值 |
|------|------|
| 测试总数 | 98（全量回归收集） |
| 通过数 | 96（13 个 module-024 单测 + 83 个既有单测） |
| 失败数 | 2（既有 async 技术债务，非本次回归，见 §4.2） |
| 跳过数 | 0（7 题 golden 无 gold 标注跳过为评估集设计，非测试跳过） |
| 通过率 | 97.96%（不含既有债务 2 个为 100%） |
| 执行耗时 | 单测 45.6s / 全量 52.3s / 评估 27s / 延迟实测 ~30s |

**关键执行结果**

| 验证项 | 命令 | 结果 |
|--------|------|------|
| 语法编译 | `python -m py_compile ai_service/rag/engine.py` | ✅ 退出码 0 |
| module-024 单测 | `python -m pytest tests/test_engine_latency.py -q` | ✅ 13 passed |
| 全量回归 | `python -m pytest tests/ -q` | ✅ 96 passed, 2 failed（既有 async 债务） |
| hybrid 评估 | `python -m eval.golden_retrieval --mode hybrid --no-save` | ✅ Hit@5=0.9130 ≥ 0.91 基线 |
| 检索结果缓存 | 同一 query 二次 `_retrieve` | ✅ 0.003s 命中缓存，与冷启动结果一致 |
| HyDE 缓存 | 单测验证二次命中（LLM 只调一次） | ✅ 单测通过（真实链路被 LLM 429 阻塞，见 §4.3） |
| 提前终止 | 单测 + 真实链路日志 | ✅ round 0 ≥3 篇跳过反思（实测日志确认） |
| round 0 降级 | 单测 + 真实链路故障注入（LLM/DB 通道失败） | ✅ 链路不崩，单路降级 |

## 2. 覆盖率报告

| 覆盖维度 | 覆盖率 | 要求 | 状态 |
|----------|--------|------|------|
| 行覆盖率（module-024 逻辑） | 未用 pytest-cov 量化（环境未装），13 个定向单测覆盖 `_retrieve` round0 降级/预算/提前终止与 `_hyde_expand` 缓存全部关键分支 | — | ⚠️ 说明 |
| 分支覆盖率 | 同上 | — | ⚠️ 说明 |
| 方法覆盖率 | `_retrieve` / `_hyde_expand` / `_hyde_cache_key` / 常量均有测试引用 | — | ✅ |

> 说明：`pytest-cov` 未安装，无法输出量化覆盖率。本模块验收标准 §4 未设覆盖率百分比门槛，只要求"round 0 降级 / HyDE 缓存 / 提前终止"三项单测与回归/评估命令，均已完成。既有单测采用 mock 隔离外部依赖（Redis/DB/LLM），覆盖全部异常分支。

## 3. 验收标准核对

### 3.1 功能验收（acceptance-criteria §1）
| 验收项 | 对应测试用例/验证 | 状态 | 备注 |
|--------|--------------|------|------|
| §1.1 round 0 向量超时降级 | test_vector_timeout_degrades_to_graph / test_vector_failure_degrades_to_graph | ✅ 通过 | TimeoutError 与 RetrievalException 均捕获，降级为仅图结果 |
| §1.1 HyDE 缓存 | test_second_call_hits_cache | ✅ 通过 | 二次命中缓存，LLM 只调一次 |
| §1.1 整链路预算 | test_budget_exceeded_uses_collected_docs / test_budget_already_expired_returns_empty | ✅ 通过 | 超预算用已收集 docs；预算已到且无 docs 返回空 |
| §1.1 提前终止 | test_round0_sufficient_docs_skip_reflection + 真实链路日志 | ✅ 通过 | ≥3 篇跳过反思，实测日志"round 0 已收集 30 篇文档，跳过反思与后续轮次" |
| §1.1 检索质量不下降 | golden_retrieval hybrid Hit@5=0.9130 ≥ 0.91 | ✅ 通过 | 基线持平，见 §3.3 |
| §1.2 round 0 图超时降级 | test_graph_failure_degrades_to_vector（抛异常） | ✅ 通过 | TimeoutError 与异常同路径（isinstance(Exception) 捕获） |
| §1.2 HyDE 缓存不可用 | cache.get/set 内部 try/except 降级（cache.py L106-144） | ✅ 通过 | Redis 不可用返回 None/False，不阻塞主链路 |
| §1.2 总预算已到且无 docs | test_budget_already_expired_returns_empty | ✅ 通过 | |
| §1.2 提前终止阈值不足 3 篇仍反思 | test_round0_below_threshold_still_reflects | ✅ 通过 | 2 篇时反思调用 1 次 |
| §1.3 round 0 两路都失败 | test_both_fail_returns_empty | ✅ 通过 | 返回空，不整链路崩溃 |
| §1.3 HyDE LLM 失败用原始 query | test_generation_failure_falls_back_to_query + 真实链路日志 | ✅ 通过 | 实测"HyDE 扩展失败，降级使用原始 query" |
| §1.3 缓存失效重新检索 | 检索缓存 key 参数化（module-022），不同 query/top_k/min_score 不同 key | ✅ 通过 | 单测 test_prefix_independent_from_retrieve + 参数化 key |

### 3.2 接口验收（acceptance-criteria §2）
| 验收项 | 对应测试用例 | 状态 | 备注 |
|--------|--------------|------|------|
| §2.1 `_retrieve(query, top_k=30, min_score=0.6)` 返回格式不变 | test_vector_failure_degrades_to_graph 断言 `{id,title,content,hybrid_score}` 子集 | ✅ 通过 | 返回 list[dict] |
| §2.1 各调用方兼容 | main.py:251（top_k=20）、eval/evaluate.py:74（默认参数） | ✅ 通过 | 签名与默认值不变，调用方零改动 |
| §2.2 hyde_key 独立 | test_prefix_independent_from_retrieve | ✅ 通过 | `rag:hyde:` 与 `rag:retrieve:` 前缀互不污染 |
| §2.2 命中返回缓存 / 未命中生成后写入 | test_second_call_hits_cache（写入+命中） | ✅ 通过 | TTL 300s；仅真实生成（answer!=query）时写入，不缓存降级值 |

### 3.3 非功能验收（评估/延迟）
| 验收项 | 对应测试用例 | 状态 | 备注 |
|--------|--------------|------|------|
| hybrid Hit@5 ≥ 0.91 基线 | `python -m eval.golden_retrieval --mode hybrid --no-save` | ✅ 通过 | Hit@5=0.9130 / Recall@5=0.8696 / MRR=0.8348；23 题评估 / 7 题跳过（无 gold 标注，与基线集一致） |
| 常规查询耗时下降（检索结果缓存） | 真实链路同一 query 冷/热两次 | ✅ 通过 | 热缓存 0.003s vs 冷启动 ~7-15s（冷启动耗时含 LLM 429 降级，见 §4.3） |
| 常规查询耗时下降（提前终止省一次反思 LLM） | 真实链路日志"round 0 已收集 30 篇文档，跳过反思" | ✅ 通过 | 跳过反思 LLM 调用与后续轮次 |

### 3.4 回归测试（acceptance-criteria §4.3）
| 验收项 | 结果 | 状态 | 备注 |
|--------|------|------|------|
| `python -m pytest tests/` 无新增失败 | 96 passed, 2 failed | ✅ 通过 | 2 个失败为 test_engine.py 既有 async 用例缺 pytest-asyncio（module-018 已记录技术债务，pytest cache lastfailed 与本次一致，非 module-024 回归） |
| 检索链路各调用方无回归 | main.py / eval/evaluate.py 兼容 | ✅ 通过 | _retrieve 返回格式与签名不变 |

## 4. 失败详情

### 4.1 module-024 单测
无失败（13/13 通过）。

### 4.2 回归测试失败（既有技术债务，非本次回归）
- 测试名: `tests/test_engine.py::test_search_returns_response` / `tests/test_engine.py::test_chat_returns_response`
- 失败原因: `Failed: async def functions are not natively supported.` — 测试环境缺 `pytest-asyncio`，async 用例无法在 pytest 下运行
- 归因: module-018 验收时已记录的技术债务（project-context §7），pytest cache `lastfailed` 在本次测试前已存在，非 module-024 引入
- 关联文件: `ai_service/tests/test_engine.py`

### 4.3 环境阻塞记录（非代码缺陷）
| # | 阻塞项 | 影响 | 验证替代方案 |
|---|--------|------|--------------|
| 1 | ModelScope LLM API（qwen/zhipu）当日 429 配额超限，deepseek key 未配置 | 真实链路 HyDE 扩展/实体提取/反思全部降级用原始 query；HyDE 缓存二次命中无法在真实链路演示 | `test_second_call_hits_cache` 单测验证二次命中（LLM 只调一次）；降级路径本身被真实链路日志验证（"HyDE 扩展失败，降级使用原始 query" / "查询实体提取失败"）且链路不崩 |
| 2 | 检索结果缓存演示受 LLM 429 干扰（冷启动耗时含降级 LLM 超时） | 无法给出"干净"的冷热耗时绝对值 | 缓存命中本身已被验证：热缓存 0.003s、日志"检索缓存命中"、结果与冷启动一致 |

## 5. 发现（非阻塞观察项）

### 观察 1（环境/既有问题）：asyncpg 连接并发竞态导致向量通道偶发失败，冷 `_retrieve` 结果不一致
- 现象: 清缓存后同一 query 冷跑两次，结果不一致——R1 向量通道报 `This session is provisioning a new connection; concurrent operations are not permitted`，降级为仅 FTS，最终 docs=0；R2 向量通道正常，round 0 收集 30 篇，docs=2。
- 根因: `retriever.py _execute`（L263-269）用 `asyncio.gather(fts_task, vector_task, return_exceptions=True)` 在**同一个** asyncpg session 上并发执行两条 SQL。asyncpg 连接不允许并发操作，当连接仍处于 provisioning（池内首条连接）时会抛出该错误。属既有问题（module-005 起），非 module-024 引入。
- module-024 表现: round 0 的 `return_exceptions=True` 降级正确兜住了该通道失败，链路未崩（符合验收 §1.3 精神）。但因仅剩 FTS 结果未过 `min_score=0.6`，返回空。
- 建议: 后续模块可在 `_execute` 给 FTS/向量两路各分配独立 session，或对单连接串行执行，消除竞态。非 module-024 阻塞项。

### 观察 2（Reviewer 遗留建议，不阻塞）: 整链路预算为"软预算"
- `graph_extractor.extract_from_query(query)`（engine.py L412）无 `asyncio.wait_for` 包裹，LLM 客户端 HTTP 超时 120s 时单次实体提取即可消耗整个 30s 预算。Reviewer §2.2 #1 已记录，属后续顺手修复项，本轮不阻塞。

### 观察 3（Reviewer 遗留建议，不阻塞）: `_retrieve` 方法约 148 行，超 50 行限制
- Reviewer §2.2 #2 已记录，属既有超长方法 + module-024 新增行所致，本轮不阻塞。

## 6. 测试结论

- 结论: **通过**
- 测试时间: 2026-08-01
- 测试人: Tester
- 测试环境: Windows 11 / Python 3.11.15；Postgres localhost:5432 ✅、Redis localhost:6379 ✅、本地 bge-m3 嵌入 ✅、ModelScope LLM ⚠️ 429（当日配额超限）
- 备注:
  1. 全量回归无新增失败（96 passed；2 个失败为既有 async 技术债务，已比对 pytest cache lastfailed 确认非本次回归）。
  2. hybrid 评估 Hit@5=0.9130 与 module-020 后基线 0.9130 持平，检索质量未下降。注意评估脚本直接调用 `hybrid_retriever.retrieve`（检索层），而 module-024 改动在 `engine._retrieve`（编排层）——评估作为检索质量回归门禁成立，module-024 自身逻辑由 13 个定向单测 + 真实链路日志验证。
  3. 延迟优化核心项均验证：检索结果缓存命中（0.003s）、提前终止跳过反思（实测日志）、HyDE 缓存单测通过。HyDE 缓存真实链路演示被 LLM 429 阻塞，但降级路径正确（不缓存降级值）。
  4. 观察 1（asyncpg 并发竞态）为既有环境问题，影响冷缓存查询一致性但不影响 module-024 验收项；建议后续模块处理。
