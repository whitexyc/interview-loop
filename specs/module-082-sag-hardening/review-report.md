# module-082-sag-hardening 审查报告

> 审查者：Reviewer（独立审查 agent）
> 审查时间：2026-08-28
> 审查对象：changelog.md 所列变更（3 文件：sag_retriever.py / engine.py / test_sag_hardening.py）

## 一、审查结论

# ✅ 通过（PASS）

0 阻塞，3 项 LOW 非阻塞建议。全部变更文件已独立阅读完整代码，8 项重点核查逐一给出结论。

## 二、重点核查项逐项结论

### 2.1 hybrid 零回归 ✅ 通过

**engine.py `search()` 方法**（L154-192）：
- `settings.retrieval_mode in ("sag", "hybrid_sag")` 门控（L157），hybrid 默认不进入该分支
- `settings.retrieval_mode != "sag"` 判断（L175）确保 hybrid 走原有 `hybrid_retriever.retrieve()` 逻辑
- SAG 分支全部包裹在 `try/except` 中（L159/171），失败时 `sag_docs = []`
- 合并逻辑（L180-188）SAG 在前 + 常规在后 + `existing_ids` 去重——hybrid 时 `sag_docs=[]`，合并等价于原逻辑

**engine.py `_retrieve()` 方法**（L817-833）：
- `settings.retrieval_mode in ("sag", "hybrid_sag")` 门控（L821），hybrid 默认不进入
- 零改动路径与 module-081 一致

**结论**：hybrid 默认路径行为零变化，与 plan §3.1 伪代码一致。

### 2.2 search 三模式语义 ✅ 通过

与 plan §3.1 伪代码逐行比对：

| 伪代码 | 实际实现 | 一致性 |
|--------|----------|--------|
| `if retrieval_mode in ("sag", "hybrid_sag"): sag_docs = await sag_retrieve(...)` | L157-170 ✅ | 一致 |
| `for sd in sag_docs: sd["hybrid_score"] *= 1.2` | L165-168 ✅ | 一致 |
| `if retrieval_mode != "sag": regular = await hybrid_retriever.retrieve(...)` | L175-178 ✅ | 一致 |
| `else: regular = []` | L179-180 ✅ | 一致 |
| 合并：SAG 在前 + 常规在后 + existing_ids 去重 | L183-188 ✅ | 一致 |
| 两模式继续走 `_expand_to_parents` + `reranker.rerank` | L195-204 ✅ | 一致 |
| SAG 失败 fail-open | L171-173 ✅ | 一致 |

**结论**：三种模式语义完全对齐 plan §3.1。

### 2.3 兜底提取边界 ✅ 通过

**`_fallback_extract_entities()`**（sag_retriever.py L48-55）：
- 正则切词：`_DELIMITER_PATTERN = re.compile(r'[\s，。、；：？！,.:;?!\n\t]+')`（L45）——覆盖中英文标点+空白 ✅
- 停用词：`_STOPWORDS` 集合（L22-43）包含 ~50 个中英高频词，硬编码常量 ✅
- 单字符过滤：`len(t.strip()) > 1`（L53）✅
- top_k 上限：`candidates[:max_entities]`（L55）默认 5 ✅
- 无有效候选返回 `[]`（L55 列表推导可能为空，L72 `if not entity_names: return []` 兜底）

**LLM 优先**：
- `graph_extractor.extract_from_query` 包裹在 `asyncio.wait_for(timeout=10)`（L70-73）
- LLM 异常时 `logger.warning("SAG 查询实体 LLM 提取失败，启用兜底")`（L74）
- `if not entity_names:` 才触发 `_fallback_extract_entities`（L76-77）
- 结论：LLM 正常时确实优先 LLM，兜底只在 LLM 失败/空时触发 ✅

**asyncio.wait_for 10s 超时**：
- L71: `await asyncio.wait_for(graph_extractor.extract_from_query(query), timeout=10)` ✅

**结论**：兜底边界合理，LLM 优先+降级逻辑正确。

### 2.4 boost 语义 ✅ 通过

- `_SAG_SCORE_BOOST = 1.2` 硬编码常量（engine.py L56）✅
- **search() 路径**：L165-168 `sd["hybrid_score"] = min(sd.get("hybrid_score", sd.get("score", 0.0)) * _SAG_SCORE_BOOST, 1.0)` ✅
- **_retrieve() 路径**：L826-828 同款公式 ✅
- 上限 1.0 截断：`min(..., 1.0)` ✅
- 仅对 SAG 命中项生效：boost 在 SAG 分支内执行，常规结果不经过 ✅
- reranker 前生效：boost 在 `reranker.rerank()` 调用前执行（search: L165-168 < L195; _retrieve: L826-828 < 后续 rerank）✅
- 常规结果不受影响：hybrid 模式不进入 SAG 分支，hybrid_sag 模式 `regular` 列表不经过 boost ✅

**结论**：boost 语义与 plan §3.3 完全一致。

### 2.5 铁律 5（裸 except）✅ 通过

**sag_retriever.py:145 处核实**：

```python
# L142-145:
    except Exception as e:
        logger.warning("SAG 检索失败，返回空: %s", e)
        return []
```

- **非裸 except**：`except Exception as e:` 明确捕获 `Exception` 子类，非裸 `except:`
- **非静默吞没**：带 `logger.warning` 记录异常信息
- **fail-open 语义**：返回空列表，调用方（engine.py）会用常规结果兜底
- **与 module-081 的 7 处 fail-open 一致**

**判定依据**：
1. `except Exception as e:` 不是裸 except（裸 except 是 `except:` 不带 `as`）
2. 带 `logger.warning` 记录异常，不是静默吞掉
3. 返回 `[]` 是 fail-open 语义（SAG 可选，失败不影响主链路）

**结论**：非铁律 5 违规。该处是合理的 fail-open 降级 + 日志记录。

### 2.6 SQL 注入 ✅ 通过

**`_sql_entity_search()`**（L90-145）：
- L116: `stmt = sql_text("""...WHERE se.name ILIKE ANY(:patterns)...""")`
- L122: `await session.execute(stmt, {"patterns": patterns, "limit": top_k * 3})`
- `patterns` 是 Python list，由 `f"%{name}%"` 格式化（L113），但通过参数化绑定传递给 DB 引擎

**`_sql_relation_search()`**（L148-210）：
- 同样使用 `sql_text(...)` + 参数化 `{"patterns": patterns, "limit": top_k * 2}`

**结论**：所有 SQL 均使用 SQLAlchemy 参数化绑定，无字符串拼接，零注入风险。

### 2.7 行数口径 ✅ 通过

**独立统计**：

| 文件 | 082 新增行 | 说明 |
|------|-----------|------|
| sag_retriever.py | ~51 行 | _STOPWORDS(24) + _DELIMITER_PATTERN(1) + _fallback_extract_entities(8) + retrieve Step1(18) |
| engine.py | ~57 行 | _SAG_SCORE_BOOST(1) + search() SAG block(39) + _retrieve boost(17) |
| **合计** | **~108 行** | **≤200 行达标** |

**注意**：check-gates.js 报 520 行是 GATE_DIFF_BASE==HEAD 时扫全部未提交文件（含 081 已提交的 sag 文件）的已知工具误报。本模块 082 实际新增 ~108 行，远低于 200 行预算。

### 2.8 验收标准逐项核对

| # | AC 项 | 结果 | 证据 |
|---|--------|------|------|
| **功能验收** |
| 1.1.1 | hybrid 模式 search 端点行为不变 | ✅ 通过 | L157 门控不进入 SAG 分支，L175-178 走原有逻辑 |
| 1.1.2 | sag 模式返回纯 SAG 结果 | ✅ 通过 | L179-180 `regular = []` + 单测 test_sag_mode_pure_sag PASSED |
| 1.1.3 | hybrid_sag 合并去重 | ✅ 通过 | L183-188 合并逻辑 + 单测 test_hybrid_sag_merges PASSED |
| 1.1.4 | SAG 失败降级 | ✅ 通过 | L171-173 + 单测 test_sag_failure_degrades PASSED |
| 2.1.1 | LLM 正常用 LLM 结果 | ✅ 通过 | L70-74 + 单测 test_llm_normal_uses_llm_result PASSED |
| 2.1.2 | LLM 返回空时启用兜底 | ✅ 通过 | L76-77 + 单测 test_llm_empty_falls_back PASSED |
| 2.1.3 | LLM 抛异常时启用兜底 | ✅ 通过 | L74 + 单测 test_llm_failure_falls_back PASSED |
| 3.1.1 | SAG 命中项 score boost | ✅ 通过 | L165-168 + 单测 test_boost_basic PASSED (0.5→0.6) |
| 3.1.2 | boost 上限 1.0 | ✅ 通过 | `min(..., 1.0)` + 单测 test_boost_capped_at_1 PASSED |
| 3.1.3 | boost 仅对 SAG 生效 | ✅ 通过 | 常规结果不经过 SAG 分支 |
| 3.1.4 | hybrid 无 boost | ✅ 通过 | hybrid 不进入 SAG 分支 |
| **边界验收** |
| 1.2.1 | SAG 为空时返回常规 | ✅ 通过 | `sag_docs=[]` 合并等价于原逻辑 |
| 1.2.2 | 重叠去重 | ✅ 通过 | `existing_ids` set + 单测 test_hybrid_sag_merges 验证 |
| 1.2.3 | config/env 生效 | ✅ 通过 | `settings.retrieval_mode` 读取 |
| 2.2.1 | 兜底过滤停用词 | ✅ 通过 | 单测 test_filters_stopwords PASSED |
| 2.2.2 | 兜底过滤单字符 | ✅ 通过 | 单测 test_filters_single_char PASSED |
| 2.2.3 | 兜底无候选返回空 | ✅ 通过 | 单测 test_empty_when_only_stopwords PASSED |
| 2.2.4 | 兜底数量受限制 | ✅ 通过 | 单测 test_max_entities_limit PASSED |
| 3.2.1 | score=0.0 boost 后仍 0.0 | ✅ 通过 | 单测 test_boost_zero_stays_zero PASSED |
| 3.2.2 | 缺失 score 默认 0.0 | ✅ 通过 | 单测 test_boost_missing_score_defaults_zero PASSED |
| **异常验收** |
| 1.3.1 | SAG 超时不阻塞 | ✅ 通过 | `asyncio.wait_for(timeout=15)` (L160-162) + except 降级 |
| 2.3.1 | LLM 10s 超时后兜底 | ✅ 通过 | `asyncio.wait_for(timeout=10)` (L71) + 单测 test_llm_timeout_falls_back PASSED |
| **代码质量** |
| 4.1 | 生产代码 ≤200 行 | ✅ 通过 | ~108 行（独立统计） |
| 4.2 | conftest 钉住 hybrid | ✅ 通过 | 081 已建立 autouse fixture |
| 4.3 | fail-open 纪律 | ✅ 通过 | 3 处 except+warning+降级 |
| 4.4 | SQL 注入零风险 | ✅ 通过 | 全部参数化绑定 |
| 4.5 | 无新依赖 | ✅ 通过 | 无 requirements.txt 改动 |
| **回归验收** |
| 5.1 | 全量零新增失败 | ✅ 通过 | changelog: 1485/4 基线/3 skip/1 error |
| 5.2 | py_compile OK | ✅ 通过 | changelog: 两文件 exit 0 |
| 5.3 | 存量测试零改动 | ✅ 通过 | 仅新增 test_sag_hardening.py |
| **文档验收** |
| 6.1 | plan + AC 已产出 | ✅ 通过 | 两文件存在 |
| 6.2 | 三记忆文件已更新 | ✅ 通过 | project-context + file-index + activity-log |
| 6.3 | CONTEXT.md 只增不删 | ✅ 通过 | 无删除行 |

**AC 33 项全部通过。**

## 三、安全评估

| 维度 | 结论 |
|------|------|
| SQL 注入 | ✅ 零风险——全部参数化绑定 |
| LLM 输出注入 | ✅ 安全——兜底分词结果仅用于 ILIKE 参数化查询 |
| 停用词泄露 | ✅ 无风险——硬编码常量，不涉及用户数据 |
| 异常吞没 | ✅ 合理——3 处 fail-open 均带 warning 日志 |
| 依赖安全 | ✅ 无新依赖 |

## 四、问题列表

| # | 文件:行号 | 严重级别 | 描述 | 可执行修复建议 |
|---|----------|----------|------|--------------|
| 1 | sag_retriever.py:45 | LOW | `_DELIMITER_PATTERN` 在模块顶层编译，全局 import 时即生效——合理，但建议在 docstring 中说明编译时机 | 无需修复，观察即可 |
| 2 | engine.py:165 | LOW | `sd.get("hybrid_score", sd.get("score", 0.0))` 双层 get 在 score 也为 0 时行为正确，但语义略复杂 | 建议后续简化为单一默认值 |
| 3 | test_sag_hardening.py:218 | LOW | settings mock 遍历所有属性（含 Pydantic computed fields）产生 DeprecationWarning——不影响测试正确性 | conftest 级别 filterwarnings 已有，无需修复 |

## 五、与 module-081 的衔接确认

- module-081 遗留 LOW #1（search 端点不经 SAG 分支）→ **本模块已修复** ✅
- module-081 遗留 LOW #2（SAG 查询实体提取硬依赖 LLM）→ **本模块已修复**（非 LLM 兜底）✅
- module-081 遗留 LOW #3（hybrid_sag 去重排序策略未实现）→ **本模块已实现**（boost ×1.2）✅
- module-081 遗留 LOW #4（reranker 交互确认）→ **本模块确认**（boost 在 reranker 前生效，reranker 用自有 cross-encoder 分数重排）✅

## 六、独立测试验证

Reviewer 独立复跑 `pytest tests/retrieval/test_sag_hardening.py tests/retrieval/test_sag.py -q`：

```
33 passed, 15 warnings in 45.62s
```

新增 18 项 + 存量 15 项 = 33 项全绿。

## 七、结论

**审查通过（PASS）**。module-082 三项补强全部正确实现：search 端点 SAG 感知（三模式语义对齐 plan §3.1）、非 LLM 兜底实体提取（LLM 10s 超时 + fail-open）、hybrid_sag boost ×1.2（上限 1.0 截断 + reranker 前生效）。hybrid 默认零回归确认（AC 33/33 + 全量 1485/4 基线零新增失败）。生产代码 ~108 行 ≤200 达标。3 项 LOW 非阻塞。
