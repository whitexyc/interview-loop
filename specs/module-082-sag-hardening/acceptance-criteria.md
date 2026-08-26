# module-082-sag-hardening 验收标准

## 概览

| 类别 | 项数 |
|------|------|
| 功能验收 | 12 |
| 边界验收 | 6 |
| 异常验收 | 4 |
| 代码质量 | 5 |
| 回归验收 | 3 |
| 文档验收 | 3 |
| **合计** | **33** |

---

## 1. search 端点 SAG 感知（子任务 1）

### 1.1 核心功能

| # | 验收项 | 验证命令 | 预期输出 |
|---|--------|----------|----------|
| 1.1.1 | `hybrid` 模式 search 端点行为不变 | `python -c "from src.config import settings; settings.retrieval_mode='hybrid'; from rag.engine import rag_engine; import asyncio; r=asyncio.run(rag_engine.search(type('R',(),{'query':'G1 GC','top_k':3})())); print(len(r.results))"` | 返回常规检索结果，与改造前一致 |
| 1.1.2 | `sag` 模式 search 端点返回纯 SAG 结果 | mock `retrieval_mode='sag'` + mock `sag_retriever.retrieve` 返回 2 篇 → search 返回 2 篇 | 结果仅来自 SAG，无常规检索结果 |
| 1.1.3 | `hybrid_sag` 模式 search 端点返回合并结果 | mock `retrieval_mode='hybrid_sag'` + SAG 返回 2 篇 + 常规返回 3 篇 → search 返回 5 篇（无重复） | SAG 结果在前，常规结果在后，去重 |
| 1.1.4 | SAG 检索失败降级为常规结果 | mock `sag_retriever.retrieve` 抛异常 → search 仍返回常规结果 | 不抛异常，结果来自常规检索 |

### 1.2 边界验收

| # | 验收项 | 验证命令 | 预期输出 |
|---|--------|----------|----------|
| 1.2.1 | SAG 结果为空时 search 返回常规结果 | mock SAG 返回 `[]` → search 返回常规结果 | 不影响常规检索 |
| 1.2.2 | SAG 结果与常规结果有重叠时去重 | SAG 返回 doc_id=[1,2] + 常规返回 doc_id=[2,3] → 结果 id=[1,2,3] | 无重复 doc_id |
| 1.2.3 | `retrieval_mode` 通过 config/env 生效 | 设置 `PW_RETRIEVAL_MODE=sag` → search 走 SAG 路径 | 日志确认 SAG 检索执行 |

### 1.3 异常验收

| # | 验收项 | 验证命令 | 预期输出 |
|---|--------|----------|----------|
| 1.3.1 | SAG 检索超时不阻塞 search | mock `sag_retriever.retrieve` 15s 超时 → search 仍返回常规结果 | 15s 超时后降级，不阻塞 |

---

## 2. 非 LLM 兜底实体提取（子任务 2）

### 2.1 核心功能（三态覆盖）

| # | 验收项 | 验证命令 | 预期输出 |
|---|--------|----------|----------|
| 2.1.1 | LLM 正常返回实体时使用 LLM 结果 | mock `extract_from_query` 返回 `["G1","GC"]` → retrieve 使用 LLM 结果 | entity_names == ["G1","GC"] |
| 2.1.2 | LLM 返回空时启用兜底 | mock `extract_from_query` 返回 `[]` → retrieve 使用兜底结果 | entity_names 非空（来自兜底分词） |
| 2.1.3 | LLM 抛异常时启用兜底 | mock `extract_from_query` 抛 `RuntimeError` → retrieve 使用兜底结果 | entity_names 非空（来自兜底分词） |

### 2.2 边界验收

| # | 验收项 | 验证命令 | 预期输出 |
|---|--------|----------|----------|
| 2.2.1 | 兜底分词过滤停用词 | `_fallback_extract_entities("什么是G1 GC的原理")` | 返回 `["G1","GC","原理"]`，不含"什么""的" |
| 2.2.2 | 兜底分词过滤单字符 | `_fallback_extract_entities("a b 你好世界")` | 返回 `["你好世界"]`，不含"a""b" |
| 2.2.3 | 兜底无有效候选时返回空 | `_fallback_extract_entities("的 了 是")` | 返回 `[]` |
| 2.2.4 | 兜底结果数量受 top_k 限制 | `_fallback_extract_entities("a b c d e f g", max_entities=3)` | 返回 3 个候选 |

### 2.3 异常验收

| # | 验收项 | 验证命令 | 预期输出 |
|---|--------|----------|----------|
| 2.3.1 | LLM 超时（10s）后启用兜底 | mock `extract_from_query` sleep 15s → retrieve 等待 10s 后兜底 | 不抛异常，兜底结果非空 |

---

## 3. hybrid_sag 融合排序策略（子任务 3）

### 3.1 核心功能

| # | 验收项 | 验证命令 | 预期输出 |
|---|--------|----------|----------|
| 3.1.1 | SAG 命中项 score 被 boost | SAG doc `hybrid_score=0.5` → boost 后 `0.6` | `0.5 * 1.2 == 0.6` |
| 3.1.2 | boost 后 score 上限 1.0 | SAG doc `hybrid_score=0.9` → boost 后 `1.0` | `min(0.9 * 1.2, 1.0) == 1.0` |
| 3.1.3 | boost 仅对 SAG 命中项生效 | 常规结果 `hybrid_score` 不变 | 常规结果 score 不变 |
| 3.1.4 | `hybrid` 默认路径无 boost | `retrieval_mode='hybrid'` → 无 SAG 分支执行 → 无 boost | score 不变 |

### 3.2 边界验收

| # | 验收项 | 验证命令 | 预期输出 |
|---|--------|----------|----------|
| 3.2.1 | SAG doc `hybrid_score=0.0` boost 后仍为 0.0 | `0.0 * 1.2 == 0.0` | `0.0` |
| 3.2.2 | SAG doc `hybrid_score` 字段缺失时默认 0.0 | doc 无 `hybrid_score` key → boost 后 `0.0` | `0.0` |

---

## 4. 代码质量

| # | 验收项 | 验证命令 | 预期输出 |
|---|--------|----------|----------|
| 4.1 | 生产代码 ≤ 200 行 | `git diff --numstat main -- ai_service/rag/engine.py ai_service/rag/retrieval/sag_retriever.py` | 总增量 ≤ 200 行 |
| 4.2 | conftest autouse 钉住 hybrid | `grep -n 'default_retrieval_mode_hybrid' ai_service/tests/conftest.py` | fixture 存在且钉住 `hybrid` |
| 4.3 | fail-open 纪律 | 所有 SAG 相关异常路径均吞掉返回空/降级 | 无未捕获异常 |
| 4.4 | SQL 注入零风险 | 所有 SQL 均参数化绑定 | 无字符串拼接 |
| 4.5 | 无新依赖 | `git diff main -- ai_service/requirements.txt` | 无新增依赖 |

---

## 5. 回归验收

| # | 验收项 | 验证命令 | 预期输出 |
|---|--------|----------|----------|
| 5.1 | 全量回归零新增失败 | `python -m pytest --tb=short -q` | 新增 0 失败（基线 4 failed + 1 error 不变） |
| 5.2 | py_compile 新文件 OK | `python -m py_compile rag/engine.py` + `python -m py_compile rag/retrieval/sag_retriever.py` | 两文件 exit 0 |
| 5.3 | 存量测试零改动 | `git diff main -- ai_service/tests/` (排除新增文件) | 无存量测试文件改动（conftest 除外） |

---

## 6. 文档验收

| # | 验收项 | 验证命令 | 预期输出 |
|---|--------|----------|----------|
| 6.1 | plan.md + acceptance-criteria.md 已产出 | `ls specs/module-082-sag-hardening/` | 两文件存在 |
| 6.2 | 三记忆文件已更新 | 检查 project-context.md + file-index.md + agent-activity-log.md | 含 module-082 记录 |
| 6.3 | CONTEXT.md 只增不删 | `git diff main -- CONTEXT.md` | 无删除行 |

---

## 验证命令汇总

```bash
# SAG 定向测试（新增）
python -m pytest tests/retrieval/test_sag.py -v

# 全量回归
python -m pytest --tb=short -q

# py_compile
python -m py_compile rag/engine.py
python -m py_compile rag/retrieval/sag_retriever.py

# config 开关验证
python -c "from src.config import settings; print(settings.retrieval_mode)"

# conftest 钉住验证
grep -n 'default_retrieval_mode_hybrid' tests/conftest.py
```
