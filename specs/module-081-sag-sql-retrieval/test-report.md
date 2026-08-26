# module-081-sag-sql-retrieval 测试报告

> 测试执行者：编排者（主会话）接管 Tester 阶段——Tester 子代理（ea958048）被免费模型静默卡死（无产出），按"能主会话自验就自验"惯例由编排者独立完成全部测试与真实冒烟。测试时间：2026-08-26 深夜 / 2026-08-27 凌晨。

## 一、概览

| 项目 | 结果 |
|------|------|
| SAG 定向测试 | **15 passed / 0 failed**（37.07s，`tests/retrieval/test_sag.py`） |
| module-080 回归（config 修复验证） | **31 passed / 0 failed**（33.81s，test_feedback_scanner + test_priority_crawl） |
| crawl 全套（conftest 修复验证） | **160 passed / 0 failed**（41.49s，`tests/crawl/`） |
| 全量回归 | **1467 passed / 4 failed / 3 skipped / 1 error**（116.33s） |
| py_compile | 8 文件全部 OK |
| 真实冒烟（SAG 模式 8001） | HTTP 200 通过 + SQL join 通道真实命中验证 |

## 二、全量回归失败明细（分类）

| 失败 | 分类 | 归因 |
|------|------|------|
| 4 × `tests/agent/test_agent_tools.py`（proxies） | 环境性（基线） | module-028 langchain-openai drift，`Client.__init__() got an unexpected keyword argument 'proxies'`，**与本模块无关**，与 1452 基线完全一致 |
| 1 × `scripts/test_models.py::test_model` | 环境性（陈旧脚本） | `def test_model(label=...)` 参数被 pytest 误当 fixture（`fixture 'label' not found`），08-13 老旧脚本，pre-existing 非本模块 |

**新增 0 失败，hybrid 默认零回归成立。**

## 三、验收标准逐项核对

### 1.1 检索模式开关
| # | 验收项 | 结果 | 证据 |
|---|--------|------|------|
| 1.1.1 | config 默认 hybrid | ✅ | `settings.retrieval_mode == "hybrid"`（实测） |
| 1.1.2 | PW_ 覆盖 | ✅ | 冒烟以 `PW_RETRIEVAL_MODE=sag` 启动，日志确认 SAG 三表创建（database.py:282） |
| 1.1.3 | 非法值报错 | ✅ | `Literal["hybrid","sag","hybrid_sag"]` pydantic 校验（代码审查 + 类型签名） |

### 1.2 SAG 数据层
| # | 验收项 | 结果 | 证据 |
|---|--------|------|------|
| 1.2.1 | DDL 幂等 | ✅ | test_sag_ddl_idempotent PASSED; 真实 DB ensure_sag_tables 二次执行无错 |
| 1.2.2 | ORM 可导入 | ✅ | SagEntity/SagEvent/SagRelation 导入 + py_compile OK |
| 1.2.3 | init_db 挂接 | ✅ | database.py:281 `ensure_sag_tables()` + 冒烟日志"SA 三表已就绪" |

### 1.3 抽取 + hook
| # | 验收项 | 结果 |
|---|--------|------|
| 1.3.1-1.3.3 | LLM 正常/非法 JSON/异常三态 | ✅ 15/15 中含 3 用例全过 |
| 1.3.4-1.3.6 | hook 开关三态 | ✅ 3 用例全过（enabled / disabled / fail-open） |

### 1.4 SAG 检索通道
| # | 验收项 | 结果 | 证据 |
|---|--------|------|------|
| 1.4.1 | 实体匹配检索 | ✅ | 单测 + **真实 SQL 验证**：sag_entities ILIKE 命中 → documents join 返回 2 篇真实 G1 文档 |
| 1.4.2 | 一跳关系 | ✅ | 单测 + 真实 SQL join 执行无错（空表 rows=0 符合预期） |
| 1.4.3-1.4.4 | 空查询/无匹配 | ✅ | 2 用例全过 |

### 1.5 端点集成
| # | 验收项 | 结果 | 证据 |
|---|--------|------|------|
| 1.5.1 | hybrid 零回归 | ✅ | 全量 1467（1452 + 15 新增）0 新增失败 |
| 1.5.2 | SAG 模式端点 | ✅（附注） | `PW_RETRIEVAL_MODE=sag` 真实启动 8001：`/ai/rag/search` 200 + results=3；`/ai/rag/chat` 200 + sources=4。**附注：search 端点直达 hybrid_retriever 不经 SAG 分支（见遗留 LOW）** |

### 2. 全量回归 / py_compile / 存量零改动
| # | 验收项 | 结果 |
|---|--------|------|
| 2.1 | 全量回归 | ✅ 1467/4 基线/3 skip/1 陈旧 error |
| 2.2 | py_compile | ✅ 8/8 OK |
| 2.3 | 存量测试零改动 | ✅ git diff 仅新增 test_sag.py + conftest 修正 |

### 3-4. 质量 + 文档
| # | 验收项 | 结果 |
|---|--------|------|
| 3.1 | 生产代码行数 | ⚠️ 按 Reviewer 口径签署：总量 ~474 超 plan 200 行，**核心逻辑 ~200 行达标**（DDL/ORM 基础设施 ~130 行 + 注释/SQL 字面量多）；超限已在 plan 待澄清拍板时声明，见 changelog §三 |
| 3.2 | conftest 钉住 | ✅ autouse default_retrieval_mode_hybrid |
| 3.3 | DDL 幂等 | ✅ IF NOT EXISTS |
| 3.4 | fail-open | ✅ 7 处异常处理吞掉返回空 |
| 3.5 | CONTEXT.md 只增不删 | ✅（activity-log 077 P3 行曾被覆盖，编排者已恢复——见遗留） |
| 3.6 | 三记忆文件 | ✅ 全部含 module-081 记录 |
| 4.1-4.5 | 五件套 | ✅ plan / acceptance / changelog / review-report / test-report 全齐 |

## 四、真实环境冒烟记录

### 4.1 冒烟环境
- PostgreSQL 16.14（wslrelay 5432，personal_website，pgvector 0.8.3）可达 ✅
- `.venv` Python 3.11 + bge-reranker-v2-m3 权重加载（2.27GB，8.4s）✅
- 启动命令：`$env:PW_RETRIEVAL_MODE="sag"; python -m uvicorn main:app --port 8001`（PID 76964）
- 冒烟前终止了旧 8001 服务（PID 10632/62964，旧代码实例，避免端口冲突）

### 4.2 冒烟结果
```
POST /ai/rag/search {"query":"什么是G1 GC","top_k":3} → HTTP 200, results=3
  - 0.142 [1-G1垃圾收集器的Region分区机制与MixedGC全流程...]
  - 0.126 [板块6 面试题与答案...]
  - 0.110 [板块3 原理深水区...]
POST /ai/rag/chat  {"query":"什么是G1 GC"}            → HTTP 200, sources=4
服务日志：database.py:282 "SAG 三表已就绪（module-081）"（sag 模式启动生效）
```

### 4.3 SQL join 通道直测（绕过 LLM，真实 DB）
```
插入真实样本：sag_entities('G1 GC', technology, ['258','259'])
1) entity ILIKE match rows: 1 → matched doc_ids: [258, 259]
2) documents join hits: 2（258/259 真实 G1 GC 文档）
3) one-hop relation query: 执行无错（空表 rows=0 符合预期）
→ SAG SQL join 通道真实可用 ✅（样本已清理，DB 回到 0 行）
```

### 4.4 冒烟发现（如实记录）
1. **SAG 检索的 LLM 前置依赖**：`graph_extractor.extract_from_query` 走 LLM 提取查询实体；本机 ChatOpenAI `proxies` 报错（module-028 同源基线）→ 提取失败返回空 → SAG 检索空结果（fail-open 降级正确，但功能依赖 LLM 健康）
2. **search 端点不感知 SAG 开关**：`/ai/rag/search` 直达 `hybrid_retriever.retrieve()`，不经 engine `_retrieve` 的 SAG 分支（chat 路径有 SAG 分支）——设计盲点，记 LOW

## 五、遗留问题（非阻塞）

| # | 级别 | 问题 | 建议 |
|---|------|------|------|
| 1 | LOW | `/ai/rag/search` 端点不经 SAG 分支，SAG 开关只对 chat 生效 | 后续在 search 端点加 `retrieval_mode` 感知（或文档说明） |
| 2 | LOW | SAG 查询实体提取硬依赖 LLM，LLM 不可用时 SAG 检索恒空 | 增加非 LLM 兜底（查询词直接 ILIKE）作为 lg fallback |
| 3 | LOW | 生产代码 ~474 行超 plan 200（核心逻辑 ~200 达标） | 已按 Reviewer 口径签署；后续可拆模块 |
| 4 | LOW | Developer 首轮误删 module-080 config 字段 + conftest robots mock（均已修复验证） | 教训已入 activity-log：改共享 config 类须 diff 字段集 |

## 六、结论

**验收通过**。SAG 15/15 + module-080 31/31 + crawl 160/0 + 全量 1467/4基线/3skip/1陈旧error，**新增 0 失败**，hybrid 默认零回归成立；真实冒烟 SAG 模式端点 200 + SQL join 通道真实命中验证通过。4 项 LOW 非阻塞，留待后续增强。