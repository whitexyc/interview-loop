# 变更日志 — Module-024: 检索延迟优化

## 变更概述
优化 RAG 检索链路的延迟与稳定性，改动集中在 `ai_service/rag/engine.py` 的 `_retrieve` / `_hyde_expand` 两处：① round 0 向量/图检索用 `gather(return_exceptions=True)` 单路降级，向量超时不再整链路崩溃；② HyDE 扩展接入 Redis 缓存（同一 query 第二次不重复调 LLM）；③ 整链路 30s 总预算，每轮循环检查、超预算用已收集 docs 提前结束；④ 提前终止强化，round 0 收集 ≥3 篇文档即跳过反思与后续轮次。`_retrieve` 返回格式不变（list[dict] 含 id/title/content/hybrid_score），chat / stream / golden 各调用方兼容。

## 文件变更列表
| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| ai_service/rag/engine.py | 修改 | `_retrieve` round 0 降级 + 总预算 + 提前终止强化；`_hyde_expand` 接 HyDE 缓存；新增 `_hyde_cache_key` 纯函数与 module-024 配置常量 |
| ai_service/tests/test_engine_latency.py | 新增 | round 0 降级（含向量 TimeoutError 场景）/ HyDE 缓存 / 预算 / 提前终止单测（13 用例） |

## 关键设计说明

### 设计决策 1: round 0 用 gather(return_exceptions=True) 单路降级
- 决策: 向量与图检索两路并行，`asyncio.gather(vector_task, graph_task, return_exceptions=True)`；向量超时/失败 → 降级为仅图结果；图超时/失败 → 降级为仅向量结果；两路都失败 → 返回空（不崩）。图检索额外套 `asyncio.wait_for(timeout=15)`（原实现无超时，可能无限等待）。
- 原因: 与混合检索 FTS/向量双通道降级哲学一致（retriever._execute 同款模式），一路故障不拖垮整链路；验收 §1.2 明确要求"round 0 图超时：降级为仅向量结果"。

### 设计决策 2: HyDE 缓存 key 用 sha256(query)[:12] 而非内置 hash(query)
- 决策: `hyde_key = "rag:hyde:" + sha256(query.encode())[:12]`；先查缓存命中直接返回，未命中 LLM 生成后写缓存（TTL 300s），失败/超时降级用原始 query。
- 原因: plan.md 伪代码 `hash(query)[:12]` 的 Python 内置 `hash()` 受 PYTHONHASHSEED 影响跨进程不稳定，Redis 缓存跨进程共享时会永远 miss；`hash()` 返回 int 也无法切片。改为代码库既有 sha256 范式（与 `_retrieve_cache_key` 一致）。前缀 `rag:hyde:` 与检索缓存 `rag:retrieve:` 独立，互不污染（验收 §2.2）。
- 实现: 仅在真实生成（answer != query）时写缓存，避免缓存降级值；Redis 不可用时 cache.get/set 内部降级，不阻塞主链路。

### 设计决策 3: 整链路预算 deadline 在 HyDE 前设定
- 决策: `deadline = asyncio.get_running_loop().time() + _RETRIEVE_BUDGET_SECONDS (30s)` 在 HyDE/循环前设定；每轮循环开头检查 `loop.time() >= deadline` 则用已收集 docs 提前 break。
- 原因: deadline 覆盖 HyDE 生成、实体提取、多轮检索的完整链路；预算保证"不无限等待"（验收 §1.1 场景 3），避免最坏 85s 的 3 轮全量执行。

### 设计决策 4: 提前终止强化（round 0 ≥3 篇跳过反思）
- 决策: round 0 合并去重后若 `len(all_docs) >= _MIN_DOCS_SKIP_REFLECT (3)` 直接 break，跳过反思 LLM 调用与后续轮次；不足 3 篇仍走原反思流程（阈值保守）。
- 原因: 显著减少常规查询的一次 LLM 反思调用 + 最多两轮额外检索；≥3 篇文档已足够支撑答案生成，阈值保守不过度牺牲召回。保留原有 `sufficient` 提前 break 逻辑。

## 验证命令
| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| 语法检查 | `python -m py_compile ai_service/rag/engine.py` | 无输出，退出码 0 |
| module-024 单测 | `python -m pytest ai_service/tests/test_engine_latency.py -q` | `13 passed` |
| 全量回归 | `python -m pytest ai_service/tests/ -q` | `95 passed, 2 failed`（2 个失败为 test_engine.py 既有 async 用例缺 pytest-asyncio，module-018 已记录的技术债务，非本次回归） |
| hybrid 评估基线 | `python -m eval.golden_retrieval --mode hybrid --no-save` | Hit@5 = 0.9130 ≥ 0.91 基线 |

## 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-01 | 初始实现：round 0 降级 + HyDE 缓存 + 总预算 + 提前终止 + 单测 | Developer |
