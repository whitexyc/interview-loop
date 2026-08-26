# module-081-sag-sql-retrieval 验收标准

## 1. 功能验收

### 1.1 检索模式开关

| # | 验收项 | 验证命令 | 预期输出 |
|---|--------|----------|----------|
| 1.1.1 | config 默认值为 `hybrid` | `python -c "from src.config import settings; print(settings.retrieval_mode)"` | `hybrid` |
| 1.1.2 | PW_ 前缀可覆盖 | `PW_RETRIEVAL_MODE=sag python -c "from src.config import settings; print(settings.retrieval_mode)"` | `sag` |
| 1.1.3 | 非法值启动报错 | `PW_RETRIEVAL_MODE=invalid python -c "from src.config import settings"` | `ValidationError` |

### 1.2 SAG 数据层（DDL + ORM）

| # | 验收项 | 验证命令 | 预期输出 |
|---|--------|----------|----------|
| 1.2.1 | DDL 幂等建表 | `pytest tests/retrieval/test_sag.py::test_sag_ddl_idempotent -v` | `PASSED` |
| 1.2.2 | ORM 模型可导入 | `python -c "from rag.models import SagEntity, SagEvent, SagRelation; print('OK')"` | `OK` |
| 1.2.3 | init_db 挂接 | `grep -n "ensure_sag" ai_service/src/database.py` | `init_db()` 内有调用行 |

### 1.3 SAG 实体/事件抽取 + 入库 hook

| # | 验收项 | 验证命令 | 预期输出 |
|---|--------|----------|----------|
| 1.3.1 | LLM 正常抽取 | `pytest tests/retrieval/test_sag.py::test_extract_entities_events_success -v` | `PASSED` |
| 1.3.2 | LLM 返回非法 JSON 降级 | `pytest tests/retrieval/test_sag.py::test_extract_entities_events_invalid_json -v` | `PASSED`（返回空列表） |
| 1.3.3 | LLM 调用异常降级 | `pytest tests/retrieval/test_sag.py::test_extract_entities_events_exception -v` | `PASSED`（返回空列表） |
| 1.3.4 | 入库 hook 开关开 | `pytest tests/retrieval/test_sag.py::test_ingest_hook_enabled -v` | `PASSED`（实体/事件落表） |
| 1.3.5 | 入库 hook 开关关 | `pytest tests/retrieval/test_sag.py::test_ingest_hook_disabled -v` | `PASSED`（不调用抽取） |
| 1.3.6 | 入库 hook 抽取失败不阻断 | `pytest tests/retrieval/test_sag.py::test_ingest_hook_fail_open -v` | `PASSED`（文档仍入库成功） |

### 1.4 SAG 检索通道

| # | 验收项 | 验证命令 | 预期输出 |
|---|--------|----------|----------|
| 1.4.1 | 实体匹配检索 | `pytest tests/retrieval/test_sag.py::test_sag_retrieve_entity_match -v` | `PASSED`（返回关联文档） |
| 1.4.2 | 一跳关系检索 | `pytest tests/retrieval/test_sag.py::test_sag_retrieve_relation_hop -v` | `PASSED`（返回关联实体的文档） |
| 1.4.3 | 空查询返回空 | `pytest tests/retrieval/test_sag.py::test_sag_retrieve_empty_query -v` | `PASSED`（返回空列表） |
| 1.4.4 | 无匹配返回空 | `pytest tests/retrieval/test_sag.py::test_sag_retrieve_no_match -v` | `PASSED`（返回空列表） |

### 1.5 端点集成

| # | 验收项 | 验证命令 | 预期输出 |
|---|--------|----------|----------|
| 1.5.1 | hybrid 模式端点零回归 | `pytest tests/ -k "chat" -q` | 全部 `PASSED` |
| 1.5.2 | SAG 模式端点可用 | 手动：`PW_RETRIEVAL_MODE=sag` 启动服务 + `curl POST /ai/rag/chat` | `200` + 正常回答 |

---

## 2. 全量回归验收

| # | 验收项 | 验证命令 | 预期输出 |
|---|--------|----------|----------|
| 2.1 | 默认 hybrid 零回归 | `pytest tests/ -q` | `1452+ passed, 4 failed（基线）` |
| 2.2 | py_compile 新文件 | `python -m py_compile rag/retrieval/sag_extractor.py && python -m py_compile rag/retrieval/sag_retriever.py` | exit 0 |
| 2.3 | 存量测试零改动 | `git diff --stat -- ai_service/tests/` | 仅新增 `test_sag.py` |

---

## 3. 代码质量验收

| # | 验收项 | 验证方法 |
|---|--------|----------|
| 3.1 | 生产代码合计 ≤ 200 行 | 统计变更文件行数 |
| 3.2 | conftest autouse 钉住测试环境 | `grep "retrieval_mode" tests/conftest.py` |
| 3.3 | DDL 幂等（CREATE TABLE IF NOT EXISTS） | 代码审查 |
| 3.4 | fail-open 纪律 | SAG 抽取/检索异常不阻断主链路 |
| 3.5 | CONTEXT.md 只增不删 | diff 核查 |
| 3.6 | 三记忆文件已更新 | project-context + file-index + activity-log |

---

## 4. 文档验收

| # | 验收项 | 产出文件 |
|---|--------|----------|
| 4.1 | 开发计划 | `specs/module-081-sag-sql-retrieval/plan.md` |
| 4.2 | 验收标准 | `specs/module-081-sag-sql-retrieval/acceptance-criteria.md` |
| 4.3 | 变更日志（Developer 产出） | `specs/module-081-sag-sql-retrieval/changelog.md` |
| 4.4 | 审查报告（Reviewer 产出） | `specs/module-081-sag-sql-retrieval/review-report.md` |
| 4.5 | 测试报告（Tester 产出） | `specs/module-081-sag-sql-retrieval/test-report.md` |

---

## 5. 验证命令汇总

```bash
# 全量回归（默认 hybrid）
pytest tests/ -q

# SAG 定向测试
pytest tests/retrieval/test_sag.py -v

# py_compile
python -m py_compile rag/retrieval/sag_extractor.py
python -m py_compile rag/retrieval/sag_retriever.py

# config 开关验证
python -c "from src.config import settings; print(settings.retrieval_mode)"

# DDL 幂等（二次运行）
pytest tests/retrieval/test_sag.py::test_sag_ddl_idempotent -v

# 真实 E2E（需服务启动）
PW_RETRIEVAL_MODE=sag uvicorn main:app --port 8001
curl -X POST http://localhost:8001/ai/rag/chat -H "Content-Type: application/json" -d '{"query":"什么是G1 GC"}'
```
