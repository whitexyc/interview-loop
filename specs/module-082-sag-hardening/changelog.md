# module-082-sag-hardening 变更日志

## 一、变更文件列表

| 文件 | 类型 | 变更内容 |
|------|------|----------|
| `ai_service/rag/retrieval/sag_retriever.py` | 修改 | +`_STOPWORDS` 停用词常量（~60 中英词）+ `_DELIMITER_PATTERN` 正则 + `_fallback_extract_entities()` 兜底函数 + `retrieve()` Step1 改为 LLM 优先 + asyncio.wait_for 10s 超时 + 失败/空时兜底 |
| `ai_service/rag/engine.py` | 修改 | +`_SAG_SCORE_BOOST = 1.2` 常量 + `search()` SAG 感知三分支（hybrid 零改动 / sag 纯 SAG / hybrid_sag 合并去重）+ SAG 命中项 boost ×1.2 + `_retrieve` SAG 分支同步 boost |
| `ai_service/tests/retrieval/test_sag_hardening.py` | **新建** | 18 项单测（兜底 6 + retrieve 三态 4 + boost 4 + search 三模式 4） |

## 二、关键设计说明

### 2.1 search 端点 SAG 感知（子任务 1）

- `hybrid`（默认）：走原有 `hybrid_retriever.retrieve()` 逻辑，**零改动**
- `hybrid_sag`：先 `sag_retriever.retrieve(query, top_k*2)` → SAG 结果置前 + `hybrid_retriever.retrieve()` 结果去重合并 → 走 `_expand_to_parents` + `reranker.rerank` 正常流程
- `sag`：纯 SAG 结果，跳过 `hybrid_retriever`
- SAG 失败 fail-open：catch 异常后降级为仅常规结果
- SAG 检索有 15s 超时保护（`asyncio.wait_for`）

### 2.2 非 LLM 兜底实体提取（子任务 2）

- LLM 正常非空 → 用 LLM 结果（现有行为不变）
- LLM 失败（抛异常）/空 → `_fallback_extract_entities(query)`：
  - 按 `[\s，。、；：？！,.:;?!\n\t]+` 正则切词
  - 过滤停用词集合（~60 个中英高频词硬编码常量）+ 单字符
  - 取前 `top_k`（默认 5）个候选实体名
- 兜底实体名直接复用 `_sql_entity_search` 的 ILIKE
- `graph_extractor.extract_from_query` 外包裹 `asyncio.wait_for(timeout=10)` + `try/except`
- 兜底仅作降级，LLM 正常时仍优先用 LLM 结果

### 2.3 hybrid_sag 融合排序方案 A（子任务 3）

- `_SAG_SCORE_BOOST = 1.2` 硬编码常量
- SAG 命中项 `hybrid_score` ×1.2（上限 1.0 截断）
- 应用位置：`search()` SAG 分支 + `_retrieve` SAG 分支（两处同步）
- 仅对 SAG 命中项生效，常规结果不受影响
- reranker 精排不受 boost 影响（reranker 用自有 cross-encoder 分数重排）

## 三、行数统计

| 文件 | 生产代码行数（增量） |
|------|---------------------|
| sag_retriever.py | +68（停用词 + 兜底函数 + retrieve 改造） |
| engine.py | +49（search SAG 感知 + boost + _retrieve boost） |
| **生产代码合计** | **~117 行** |

## 四、测试结果

### 4.1 新增测试（18 项全绿）

```
tests/retrieval/test_sag_hardening.py::TestFallbackExtractEntities::test_filters_stopwords PASSED
tests/retrieval/test_sag_hardening.py::TestFallbackExtractEntities::test_filters_single_char PASSED
tests/retrieval/test_sag_hardening.py::TestFallbackExtractEntities::test_empty_when_only_stopwords PASSED
tests/retrieval/test_sag_hardening.py::TestFallbackExtractEntities::test_max_entities_limit PASSED
tests/retrieval/test_sag_hardening.py::TestFallbackExtractEntities::test_english_tokens PASSED
tests/retrieval/test_sag_hardening.py::TestFallbackExtractEntities::test_mixed_delimiters PASSED
tests/retrieval/test_sag_hardening.py::TestSAGRetrieveFallback::test_llm_normal_uses_llm_result PASSED
tests/retrieval/test_sag_hardening.py::TestSAGRetrieveFallback::test_llm_failure_falls_back PASSED
tests/retrieval/test_sag_hardening.py::TestSAGRetrieveFallback::test_llm_empty_falls_back PASSED
tests/retrieval/test_sag_hardening.py::TestSAGRetrieveFallback::test_llm_timeout_falls_back PASSED
tests/retrieval/test_sag_hardening.py::TestSAGScoreBoost::test_boost_basic PASSED
tests/retrieval/test_sag_hardening.py::TestSAGScoreBoost::test_boost_capped_at_1 PASSED
tests/retrieval/test_sag_hardening.py::TestSAGScoreBoost::test_boost_zero_stays_zero PASSED
tests/retrieval/test_sag_hardening.py::TestSAGScoreBoost::test_boost_missing_score_defaults_zero PASSED
tests/retrieval/test_sag_hardening.py::TestSearchRetrievalMode::test_hybrid_mode_no_sag PASSED
tests/retrieval/test_sag_hardening.py::TestSearchRetrievalMode::test_sag_mode_pure_sag PASSED
tests/retrieval/test_sag_hardening.py::TestSearchRetrievalMode::test_hybrid_sag_merges PASSED
tests/retrieval/test_sag_hardening.py::TestSearchRetrievalMode::test_sag_failure_degrades PASSED
```

### 4.2 SAG 存量测试（15 项仍全绿）

```
tests/retrieval/test_sag.py 15/15 PASSED
```

### 4.3 全量回归

```
1485 passed, 4 failed, 3 skipped, 1 error in 127.97s
```

- 1485 = 1467 基线 + 18 新增 ✅
- 4 failed = module-028 proxies 基线（环境性，非本模块）
- 1 error = scripts/test_models.py（08-13 陈旧脚本，非本模块）
- **新增 0 失败，hybrid 默认零回归成立**

### 4.4 py_compile

```bash
python -m py_compile rag/retrieval/sag_retriever.py  # OK
python -m py_compile rag/engine.py                    # OK
```

## 五、验证命令

```bash
# SAG 定向测试（存量 15 + 新增 18 = 33）
python -m pytest tests/retrieval/test_sag.py tests/retrieval/test_sag_hardening.py -v

# retrieval 全套（59 项）
python -m pytest tests/retrieval/ -q

# 全量回归
python -m pytest --tb=short -q

# py_compile
python -m py_compile rag/retrieval/sag_retriever.py
python -m py_compile rag/engine.py
```

## 六、待办 / 遗留

1. **兜底实体提取质量**：分词依赖正则切词，中文无分词器（如 jieba），连续中文句子可能切出长串。仅作 LLM 降级兜底，LLM 正常时不用。
2. **boost 系数 1.2 校准**：当前 1.2 是轻 boost，未做 A/B 评测验证最优值。reranker 精排会自行重排，boost 仅影响粗排候选顺序。
3. **real 集成测试**：search 端点 SAG 感知需真实 PostgreSQL + SAG 三表有数据才能端到端验证。当前全 mock。
