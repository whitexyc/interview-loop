# 测试报告 — module-035: 记忆/检索分数口径校准

> 📋 本文件由 Tester（m35-tester）维护，记录该模块的测试执行结果和验收结论。
> 验收结论已在 `acceptance-criteria.md` 签署：✅ **通过**。

---

## 模块信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-035 |
| 模块名称 | 记忆/检索分数口径校准 |
| 开发计划 | `specs/module-035-score-calibration/plan.md` |
| 验收标准 | `specs/module-035-score-calibration/acceptance-criteria.md` |
| 变更日志 | `specs/module-035-score-calibration/changelog.md` |
| 审查报告 | `specs/module-035-score-calibration/review-report.md` |
| 测试员 | Tester（m35-tester） |
| 测试日期 | 2026-08-06 |

---

## 1. 测试环境

| 字段 | 内容 |
|------|------|
| 后端框架 | Python FastAPI（ai_service） |
| 数据库 | PostgreSQL 15+（真实库 personal_website，5432） |
| 缓存 | Redis（6379） |
| 测试框架 | pytest 9.1.1 / Python 3.11.15 |
| 平台 / OS | Windows 11 |
| 已知环境坑 | ① 缺 pytest-asyncio（既有技术债务，module-018 起备案，本模块用例用 asyncio.run 规避）；② Windows ProactorEventLoop 下 asyncpg 连接池不可跨 `asyncio.run()` 复用（E2E 脚本需单 loop）；③ 3 个既有 Redis `setex` DeprecationWarning 与模块无关 |
| 依赖前置 | 本地 bge-m3 GGUF（models/bge-m3-gguf/bge-m3-q8_0.gguf） |
| 运行环境 | 本地开发环境（worktree-m8-knowledge-panel） |
| 测试命令 | `cd ai_service && python -m pytest tests/ -q` |
| 变更文件 | `rag/memory.py` / `src/config.py` / `main.py` / `tests/test_memory.py` / `tests/test_memory_extractor.py` |

---

## 2. 单元测试

### 2.1 测试概况

| 统计项 | 值 |
|--------|-----|
| 测试文件数（记忆相关） | 2（test_memory.py + test_memory_extractor.py） |
| 测试用例总数 | 95 |
| 通过 | 95 |
| 失败 | 0 |
| 跳过 | 0 |
| 其中 module-035 新增 | 14（TestRecallDynamicKAbsCosine 7 + TestRecallShortAbsCosine 1 + TestChildEmbeddings 3 + TestDedupThreshold035 2 + TestConfig035 1） |
| 覆盖率要求 | 模块内核心方法均已覆盖（不强制全量覆盖率，按 plan 约定） |

### 2.2 新增/更新用例明细（module-035 核心核对）

| 测试类 | 测试方法 | 场景描述 | 结果 |
|--------|----------|----------|------|
| `TestRecallDynamicKAbsCosine` | `test_high_quality_recalls_five` | 绝对余弦均值 0.9 > 0.85 → K=5 真实可达（不再恒 1） | ✅ |
| `TestRecallDynamicKAbsCosine` | `test_mid_quality_recalls_three` | 绝对余弦均值 0.78 ∈ [0.75,0.85) → K=3 | ✅ |
| `TestRecallDynamicKAbsCosine` | `test_low_quality_recalls_one` | 绝对余弦均值 0.5 < 0.75 → K=1（宁缺毋滥） | ✅ |
| `TestRecallDynamicKAbsCosine` | `test_low_score_candidates_filtered_out` | 候选 abs_cosine=0.3 < min_score(0.4) → 丢弃不注入 | ✅ |
| `TestRecallDynamicKAbsCosine` | `test_all_candidates_low_score_returns_empty` | 全部候选低分 → 返回空（不崩） | ✅ |
| `TestRecallDynamicKAbsCosine` | `test_empty_candidates_returns_empty` | 无候选 → 返回空，_expand_to_parents 不被调用 | ✅ |
| `TestRecallDynamicKAbsCosine` | `test_embedding_failure_degrades_to_hybrid_score` | query 嵌入失败 → 降级用原 hybrid_score（不回退失败，K=1） | ✅ |
| `TestRecallShortAbsCosine` | `test_recall_short_abs_cosine_reaches_three` | recall_short 绝对余弦口径（K=3，TTL 内保留） | ✅ |
| `TestChildEmbeddings` | `test_fetches_embeddings_by_child_ids` | 按子块 id IN 查询读存储 embedding（参数化，无注入） | ✅ |
| `TestChildEmbeddings` | `test_no_ids_returns_empty_without_db` | 无 id 不查库直接返回空 | ✅ |
| `TestChildEmbeddings` | `test_db_failure_returns_empty` | DB 失败返回空 dict（由调用方降级） | ✅ |
| `TestDedupThreshold035` | `test_synonym_paraphrase_cosine_088_triggers_dedup` | 0.88 > 0.85 → 命中重复（更新而非新增） | ✅ |
| `TestDedupThreshold035` | `test_distinct_fact_cosine_080_no_dedup` | 0.80 ≤ 0.85 → 不同事实正常新增 | ✅ |
| `TestConfig035` | `test_dedup_threshold_and_min_score_defaults` | config 默认：dedup 0.85 / min_score 0.4 / 档位 0.85/0.75 | ✅ |

既有用例更新核对：`TestRecall` 两个用例（source_pattern 透传 / 同父块去重取最高分）与
`TestRecallShort` TTL 用例改为 mock `embedding_service.embed_text` 抛异常走**降级路径**，
断言语义不变；`test_memory_extractor.py::TestRecallDynamicK` 四例改绝对余弦口径
（mock query 嵌入 + 候选 embedding），去重注释 0.95→0.85。

### 2.3 失败用例详情

> 无失败用例。

| 测试方法 | 预期结果 | 实际结果 | 失败原因 | 归类 | 严重度 |
|----------|----------|----------|----------|------|--------|
| — | — | — | — | — | — |

---

## 3. 集成测试

### 3.1 测试概况

| 统计项 | 值 |
|--------|-----|
| 测试场景数 | 9 |
| 通过 | 9 |
| 失败 | 0 |

### 3.2 测试场景明细（真实 E2E：真实 HTTP 服务 + 真实 PG + 真实 bge-m3 + JWT）

| 场景 | 描述 | 前置条件 | 预期结果 | 实际结果 | 状态 |
|------|------|----------|----------|----------|------|
| K=5 多档可达 | 5 条近义候选（dedup=False 构造，绝对余弦均值 0.868 > 0.85） | AI 服务 8001 + 真实 PG/bge-m3 | recall 返回 5 条 | 返回 5 条，scores [1.0, 0.903, 0.867, 0.824, 0.748] | ✅ |
| K=3 多档可达 | 5 条中质候选（均值 0.776 ∈ [0.75,0.85)，自然 dedup=True 保存） | 同上 | recall 返回 3 条 | 返回 3 条，scores [0.796, 0.791, 0.775] | ✅ |
| K=1 低质 | 5 条混质候选（均值 0.713 < 0.75） | 同上 | recall 返回 1 条 | 返回 1 条（最高 0.9345），宁缺毋滥 | ✅ |
| 去重 0.85 同义 | 同义改写（真实 cosine≈0.88） | 同上 | status=updated，条数不涨 | updated，parents 1→1 | ✅ |
| 去重不误杀 | 不同事实（cosine≈0.80） | 同上 | 正常新增 | saved，parents 1→2 | ✅ |
| 低分不注入 | 追加无关记忆后 recall 主题 query | 同上 | 低分记忆不出现 | 0 条注入 | ✅ |
| 登录用户多档 | JWT user_id=9001 保存 5 条同义记忆 + recall | AI 服务 + JWT secret | 去重合并 + 多档召回 | 5 次保存去重合并为 3 父块（不膨胀），recall 返回 3 条多档 | ✅ |
| 用户隔离 | user 9002 recall 同 query | 同上 | 无跨用户泄漏 | 0 条 | ✅ |
| chat_stream relevant | 真实 SSE 检索 step 事件 | 真实 LLM 链路 | relevant==count | count=2, relevant=2（MIN_SCORE 失真阈值已移除） | ✅ |

> K=3 档确认是**档位判定**（5 候选均值 0.776 落 [0.75,0.85)），而非候选数截断。
> 登录用户（dedup=True）下 5 条近义记忆被 0.85 去重合并为 3 父块——这正说明去重生效
> 防膨胀；幸存的不同事实父块仍触发多档召回（K=3）。

---

## 4. 回归测试

### 4.1 回归范围

| 已有模块 | 是否受影响 | 回归测试数 | 结果 |
|----------|-----------|-----------|------|
| module-023/033/034 记忆（long/short/session） | 是（口径改） | 95（记忆单测） | 全过 |
| module-032 身份隔离 | 否（隔离逻辑未动） | 20 | 全过 |
| module-025/034 流式/会话消费方 | 否（仅用 content/created_at） | 18 | 全过 |
| 全量套件 | — | 292 | 全过 |

### 4.2 回归结果

| 统计项 | 值 |
|--------|-----|
| 回归测试总数 | 292（278 基线 + 14 新增） |
| 通过 | 292 |
| 失败 | 0 |
| 通过率要求 | 100% |
| 实际通过率 | 100%（0 失败） |

> 与 Developer 自测 / Reviewer 独立复现结果完全一致（记忆 95 / 全量 292 / 身份 20 / 下游 18）。
> 3 个既有 Redis `setex` DeprecationWarning（tests/test_cache.py）与模块无关。

---

## 5. 环境性失败归因

> 本模块测试过程中无**用例失败**，无环境性失败需要归因。记录以下环境观察（均不阻塞）：

| 现象 | 判断标准 | 归类 | 处理方式 |
|------|----------|------|----------|
| E2E 脚本二次 `asyncio.run()` 复用 asyncpg 连接池崩溃（`'NoneType' object has no attribute 'send'`） | Windows ProactorEventLoop 已知问题，module-020 备案 | 环境性（脚本问题） | 改为单 asyncio.run 内完成所有 DB 操作后通过；不影响测试结论 |
| PowerShell 5.1 将 python stderr（jieba 加载日志）包装为 NativeCommandError | 原生 stderr 重定向已知行为 | 环境性（输出捕获） | 脚本实际正常；用 Select-Object 观察结果 |

---

## 6. 真实环境冒烟

> 单元 / 回归全部通过后，启动真实 AI 服务（uvicorn 8001，真实 PG/Redis/bge-m3/DeepSeek，
> JWT secret 注入），沿验收核心路径端到端执行。

### 冒烟环境

- 真实 PG + 真实 Redis + 真实本地 bge-m3 GGUF + 真实 DeepSeek（fallback 链）
- JWT：用与 Java `application.yml` 相同的开发占位 secret 直接签发 HS256 token（AI 侧
  `parse_jwt` 对称校验，等价于 Java 登录下发），模拟登录用户
- 测试身份全部结束后清理（`memory:%` 全库残留 0 行）

### 冒烟结果

| 冒烟项 | 命令/方式 | 结果 | 是否通过 |
|--------|-----------|------|----------|
| 服务健康 | GET /ai/health | status=ok | ✅ |
| K=5 真实可达 | save 5 条近义记忆（dedup=False）→ recall | 5 候选绝对余弦 [1.0, 0.903, 0.867, 0.824, 0.748] 均值 0.868 > 0.85 → **返回 5 条** | ✅ |
| K=3 真实可达 | save 5 条中质记忆（dedup=True）→ recall | 5 候选 [0.796, 0.791, 0.775, 0.763, 0.755] 均值 0.776 ∈ [0.75,0.85) → **返回 3 条** | ✅ |
| K=1 宁缺毋滥 | 5 条混质候选 → recall | 均值 0.713 < 0.75 → 仅返回最高 1 条（0.9345） | ✅ |
| 去重 0.85 触发 | 原句 save → 同义改写 save | saved → **updated**（id 不变），parents 1→1 不涨 | ✅ |
| 去重不误杀 | 不同事实 save | **saved**，parents 1→2 正常新增 | ✅ |
| 低分不注入 | 追加无关记忆（猫咪/爬山）→ recall 主题 query | 0 条低分注入（abs_cosine < 0.4 被过滤） | ✅ |
| 登录用户多档 | JWT Bearer（user_id=9001）save 5 条同义 → recall | 5 次保存去重合并为 3 父块（不膨胀），recall 返回 3 条多档（不再恒 K=1） | ✅ |
| 用户隔离 | user 9002 同 query recall | 0 条（无跨用户泄漏） | ✅ |
| chat_stream 真实链路 | POST /ai/rag/chat/stream（真实检索+真实 LLM） | HTTP 200，事件 step×4/token×N/done；检索 step count=2 relevant=2（相关字段语义正确） | ✅ |
| 数据真实落库 + 清理 | 清理前查父块数 / 清理后查残留 | 与预期一致；`memory:%` 全库 **0 行** | ✅ |

---

## 7. 异常兜底测试

| 测试场景 | 输入 | 预期行为 | 实际行为 | 结果 |
|----------|------|----------|----------|------|
| query 嵌入失败 | `embedding_service.embed_text` 抛异常 | 降级用原 hybrid_score（不回退失败） | K=1 且 score 取 hybrid_score | ✅ |
| 候选 embedding 读取失败 | `_child_embeddings` DB 异常 | 返回空 dict → 降级 hybrid_score | 降级正常，不抛 | ✅ |
| 空候选 | 检索返回 [] | recall 返回空，不调用 _expand_to_parents | 返回空 | ✅ |
| 全低分候选 | 全部 abs_cosine < 0.4 | 返回空（不崩） | 返回空 | ✅ |
| 无 id 候选 | `_child_embeddings([])` | 不查库直接返回空 | 返回空，0 次 DB 调用 | ✅ |
| 维度不一致 embedding | `_cosine` 长度不同 | 返回 0.0（视为不相似） | 返回 0.0 | ✅ |
| 空/空白 query（recall 入口） | 空串 query | 返回空（既有防护） | 返回空 | ✅ |
| 低分过滤 + 排序 | 混合高分低分候选 | 低分丢弃后按绝对余弦降序排序 | 过滤正确，排序正确 | ✅ |

---

## 8. 验收标准核对

> 逐项核对 `acceptance-criteria.md`（实际复选框 **35 项**：功能 12 / 接口 5 / 代码质量 6 /
> 测试 8 / 文档 4；原汇总表记 33 有误，已按实际修正——module-033 先例）。

### 功能验收（12 项：10 通过 + 2 P3 不适用）

| 验收项 | 测试用例 | 结果 |
|--------|----------|------|
| 1.1-1 高质量候选召回多档 | `test_high_quality_recalls_five` + 真实 E2E K=5（均值 0.868→5 条） | ✅ |
| 1.1-2 中质量召回 3 条 | `test_mid_quality_recalls_three` + 真实 E2E K=3（均值 0.776→3 条） | ✅ |
| 1.1-3 低质量召回 1 条 | `test_low_quality_recalls_one` + 真实 E2E（均值 0.713→1 条） | ✅ |
| 1.1-4 低分过滤 | `test_low_score_candidates_filtered_out` + `test_all_candidates_low_score_returns_empty` | ✅ |
| 1.1-5 空候选不崩 | `test_empty_candidates_returns_empty` | ✅ |
| 1.2-1 同义改写触发去重 | `test_synonym_paraphrase_cosine_088_triggers_dedup` + 真实 E2E（updated，条数不涨） | ✅ |
| 1.2-2 不同事实正常新增 | `test_distinct_fact_cosine_080_no_dedup` + 真实 E2E（saved） | ✅ |
| 1.2-3 阈值可配置 | `TestConfig035`（0.85 默认）+ config.py | ✅ |
| 1.3-1 chat_stream MIN_SCORE 语义正确 | 真实 chat_stream SSE：relevant==count（失真阈值已移除，plan 允许） | ✅ |
| 1.3-2 relevant_count 统计合理 | 同上（count=2 relevant=2，仅供 UI 展示） | ✅ |
| 1.4-1 RRF 融合实现 | ⚠️ 不适用：P3 评估后不采纳（分数量纲与 engine._retrieve min_score=0.6 硬阻塞，见 changelog 设计决策 5） | ⚠️ |
| 1.4-2 golden_retrieval A/B | ⚠️ 不适用：同上 | ⚠️ |

### 接口验收（5 项）— 全部通过

| 验收项 | 测试用例 | 结果 |
|--------|----------|------|
| 2.1-1 save/recall 签名不变 | git diff 核对 + 全量回归 | ✅ |
| 2.1-2 recall 返回格式不变 | `_expand_to_parents` 结构不变（content/score/title/created_at） | ✅ |
| 2.1-3 chat/stream 端点不变 | main.py diff 仅内部统计 + 真实 SSE 调用 | ✅ |
| 2.1-4 三层 source 分层不变 | 精确匹配逻辑未动，记忆单测 95 全过 | ✅ |
| 2.2-1 配置默认值 | config.py（0.85 / 0.4）+ `TestConfig035` | ✅ |

### 代码质量验收（6 项）— 全部通过

| 验收项 | 结果 |
|--------|------|
| 3.1-1 所有 public 方法有 Docstring | ✅（新增 `_absolute_cosine_avg` / `_child_embeddings` / `_cosine` 均有） |
| 3.2-1 Python snake_case | ✅ |
| 3.3-1 单方法 ≤50 行 | ✅（`_absolute_cosine_avg` ~44 行） |
| 3.3-2 模块生产代码 ≤300 行 | ✅（净增 ~95 行） |
| 3.4-1 py_compile 通过 | ✅ |
| 3.4-2 无未使用 import | ✅ |

### 测试验收（8 项：7 通过 + 1 P3 不适用）

| 验收项 | 测试用例 | 结果 |
|--------|----------|------|
| 4.1-1 动态 K 绝对余弦测试 | TestRecallDynamicKAbsCosine 7 + TestRecallShortAbsCosine 1 + TestChildEmbeddings 3 | ✅ |
| 4.1-2 去重阈值 0.85 测试 | TestDedupThreshold035 2 + extractor 更新 | ✅ |
| 4.1-3 RRF 融合单测 | ⚠️ 不适用：P3 未实施 | ⚠️ |
| 4.2-1 全量 pytest 0 失败 | **292 passed / 0 failed** | ✅ |
| 4.2-2 身份回归 | **20 passed** | ✅ |
| 4.3-1 真实 E2E 多档召回 | 真实 E2E：登录用户 K=3 / 独立构造 K=5（0.868）/ K=3（0.776） | ✅ |
| 4.3-2 真实 E2E 二次同义去重不膨胀 | 真实 E2E：updated，parents 1→1 | ✅ |
| 4.3-3 真实 E2E 低分不注入 | 真实 E2E：0 条注入 | ✅ |

### 文档验收（4 项）— 全部通过

| 验收项 | 结果 |
|--------|------|
| 5.1-1 changelog.md 已更新 | ✅ |
| 5.2-1 分数口径方案记录 plan.md + score-issues.md | ✅ |
| 5.3-1 project-context.md 更新 | ✅ |
| 5.3-2 agent-activity-log.md 更新 | ✅ |

---

## 9. 测试结论

### 总结

| 统计项 | 值 |
|--------|-----|
| 单元测试通过率 | 95/95 (100%) |
| 集成测试（真实 E2E）通过率 | 9/9 (100%) |
| 回归测试通过率 | 292/292 (100%) |
| 异常兜底测试通过率 | 8/8 (100%) |
| 真实环境冒烟通过率 | 10/10 (100%) |
| **总体验收结论** | **✅ 通过** |

### 验收结论

- [x] ✅ **通过** — 所有测试通过，验收标准全部满足（35 项：32 通过 + 3 不适用 P3 可选未采纳），建议合并
- [ ] ❌ **不通过** — 存在失败用例，需 Developer 修复后重新测试
- [ ] ⚠️ **有条件通过** — 核心路径通过，非核心问题可后续修复

### 签署

| 字段 | 内容 |
|------|------|
| 测试人 | Tester（m35-tester） |
| 签署时间 | 2026-08-06 |
| 结论 | 通过 |
| 记忆库同步确认 | project-context 状态已标记 ✅ / file-index 已更新 ✅ / agent-activity-log 已追加 ✅ |

### 失败详情

> 无失败项。未执行 3 项为 P3 三通道 RRF（可选，评估后不采纳，非失败）。

---

## 10. Reviewer 建议复核（Tester 实测）

| 序号 | 建议 | Tester 复核结论 |
|------|------|-----------------|
| #1 | `docs.sort(key=lambda d: d["abs_cosine"], reverse=True)` 硬键访问；min_score≤0 配置下无 abs_cosine 候选会 KeyError | **默认配置下无影响（确认）**：默认 `memory_recall_min_score=0.4`，无 `abs_cosine` 键的候选 `d.get("abs_cosine", 0.0)`=0.0 < 0.4 会在过滤步骤被移除，不可能到达 sort。仅当 `PW_MEMORY_RECALL_MIN_SCORE` 配置 ≤0 时理论可达，属配置护栏问题，非生产默认路径。建议（低优先级）改为 `d.get("abs_cosine", 0.0)` 或对 min_score 做下限校验 |
| #2 | 无存储 embedding 的候选被静默丢弃（abs_cosine 缺省 0.0 < 0.4） | **确认语义正确**：绝对质量口径下"无法验证质量→丢弃"合理；建议补 debug 日志（非阻塞） |
| #3 | chat 路径 `engine._recall_memory` 仍 `top_k=3`（engine.py L290），K=5 档 chat 不可达 | **确认既有行为（非本模块回归）**：`engine.py:290` `top_k: int = 3`，chat/stream 调用未传 top_k 用默认 3 → chat 候选池最多 3 条，K=5 档在 chat 路径不可达。直接调 `memory_service.recall(query, identity, top_k=5)` 已真实可达 K=5。属 module-033 review #3 既有观察，建议后续模块评估 `_recall_memory` 默认 top_k 提至 5 |
| #4 | acceptance 汇总表 33 vs 实际 35（功能 11 vs 12、代码质量 5 vs 6） | **已修正**：汇总表按实际复选框 35 项修正（功能 12 / 接口 5 / 代码质量 6 / 测试 8 / 文档 4），module-033 先例 |

---

## 11. 改进建议

| 建议 | 优先级 | 建议处理时间 |
|------|--------|-------------|
| `_absolute_cosine_avg` 排序硬键改 `d.get("abs_cosine", 0.0)`（或对 `memory_recall_min_score` 配置加下限校验），消除 min_score≤0 理论 KeyError（Reviewer #1） | 低 | 后续模块 |
| 低分过滤丢弃候选时补 debug 日志（含 id 数），便于排查静默丢弃（Reviewer #2） | 低 | 后续模块 |
| `engine._recall_memory` 默认 `top_k` 3→5，使 chat 路径也能多档注入（Reviewer #3） | 中 | 后续模块（记忆体系收尾） |
| **实测观察**：自然 dedup=True 流程下 5 条近义记忆会被 0.85 去重合并（正是去重目标），故 K=5 档多发生在"不同但均高质量"的候选集——实际对话路径更常触发 K=3/K=1，属 avg 判定预期语义，建议文档说明 K=5 触发场景 | 低 | 后续模块 |
| P3 三通道 RRF 引入时须联动校准 `engine._retrieve` 的 `min_score=0.6` 过滤语义（与绝对余弦口径同思路），记录 backlog | 低 | 引入 RRF 时 |
| 建议把本模块真实 E2E 场景沉淀为 `tests/` 下可重复的集成测试（当前为一次性脚本，已删除） | 低 | 后续模块 |
| 测试数据已全部清理（`memory:%` 全库 0 行）；临时 E2E 脚本已删除 | — | 已完成 |
