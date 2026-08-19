# 功能规格说明书 — Module-019: 评估闭环（Golden 检索集 + 量化指标）

> 本文件由 **Planner** 输出，作为模块开发的唯一权威规格文档。
> Developer 严格按本文件编码，Reviewer 和 Tester 按本文件验收。

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-019 |
| 模块名称 | 评估闭环（Golden 检索集 + Hit@k/MRR + 消融） |
| 版本号 | 0.19.0-module-019 |
| 优先级 | P0 |
| 预估代码量 | ≤ 300 行（含新脚本 + 评估逻辑，需调整模块上限并说明理由） |
| 创建日期 | 2026-08-01 |
| 最后更新 | 2026-08-01 |
| 负责人 | Planner: 规划执行, Developer: 待分配 |

> **代码量调整理由**：本模块包含 3 个文件（golden.json 标注、golden_retrieval.py 评估脚本、eval_runs 表），其中 golden.json 是数据标注（约 60 行 JSON），评估脚本约 200 行。合计超 200 行默认上限，特此申请调整为 ≤ 300 行。

---

## 2. 需求描述

### 2.1 需求来源

- 来源类型：发散路线图 P0 推荐 + 用户确认
- 原始描述：当前 RAGAS 评估只有生成侧指标（faithfulness/relevancy），**没有"该检索到哪些文档"的 gold 标签**，召回本身不可量化。所有检索优化都无法验证，也容易在优化途中悄悄回归。需建立 golden 检索集 + 召回指标 + 版本化回归。

### 2.2 用户故事

```
作为 RAG 系统开发者
我想要 一个可量化的检索评估体系（golden集 + Hit@k/MRR + 消融）
以便 每次检索优化都能"改参数→跑分→验证"，且防止回归
```

### 2.3 验收场景（BDD 格式）

```
场景 1：golden 检索集存在
  假设 eval/golden.json 已创建
  当 加载它
  那么 每题包含 question + golden_docs（相关文档标题/id），与知识库真实文档对应

场景 2：召回指标计算
  假设 执行检索评估
  当 对每题用检索器检索 top_k
  那么 输出 Hit@k / Recall@k / MRR，反映检索命中情况

场景 3：单通道消融
  假设 执行消融模式
  当 分别用 仅向量 / 仅FTS / 仅图 / 组合 检索
  那么 各通道独立打分，可对比各通道贡献

场景 4：版本化回归
  假设 连续两次运行评估
  当 记录 eval_runs 表
  那么 两次结果可对比 delta，识别回归
```

### 2.4 非功能需求

| 类别 | 要求 |
|------|------|
| 运行时间 | 30 题 × 3 模式 ≤ 10 分钟（无 LLM 生成，纯检索） |
| 可重复性 | 同一代码版本跑分结果一致 |
| 数据依赖 | golden_docs 与知识库真实文档对应 |

---

## 3. 技术方案

### 3.1 涉及文件

| 文件路径 | 操作类型 | 说明 |
|----------|----------|------|
| `ai_service/eval/golden.json` | 新增 | 30 题标注 gold doc（标题/id） |
| `ai_service/eval/golden_retrieval.py` | 新增 | 召回评估脚本（Hit@k/MRR/消融） |
| `ai_service/eval/evaluate.py` | 修改 | 注入 eval_runs 版本化记录 |
| `ai_service/src/database.py` | 不动 | 复用连接 |
| `ai_service/rag/retriever.py` | 修改 | 暴露按通道检索开关（mode 参数） |

### 3.2 数据库变更

新建表 `eval_runs`：

```sql
CREATE TABLE IF NOT EXISTS eval_runs (
    id            BIGSERIAL    PRIMARY KEY,
    eval_type     VARCHAR(20)  NOT NULL DEFAULT 'retrieval',
    git_commit    VARCHAR(64)  NOT NULL DEFAULT '',
    config_snapshot JSONB      NOT NULL DEFAULT '{}',
    scores        JSONB        NOT NULL DEFAULT '{}',
    per_question  JSONB        NOT NULL DEFAULT '[]',
    created_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE eval_runs IS '评估运行记录（版本化回归基准）';
COMMENT ON COLUMN eval_runs.git_commit IS '评估时的 git commit';
COMMENT ON COLUMN eval_runs.config_snapshot IS '评估时 rag_config 快照';
COMMENT ON COLUMN eval_runs.scores IS '整体指标分数';
COMMENT ON COLUMN eval_runs.per_question IS '每题明细';
```

### 3.3 API 接口定义

无 HTTP API 变更（内部评估脚本）。

### 3.4 业务逻辑说明

#### 核心流程（golden_retrieval.py）

```
1. 加载 eval/golden.json（30 题，含 golden_docs）
2. 对每题执行检索（默认组合模式，或 --mode 指定通道）
3. 计算指标：
   - Hit@k: 前 k 个结果中是否命中任意 gold doc
   - Recall@k: 命中的 gold doc 数 / gold doc 总数
   - MRR: 第一个命中 gold doc 的位置倒数
4. 输出：整体指标 + 每题明细 + 按类别汇总
5. 记录 eval_runs 表（含 git_commit + config 快照）
```

#### 单通道消融

`retriever.retrieve()` 增加 `mode` 参数（`hybrid` / `vector_only` / `fts_only` / `graph_only`）：
- `vector_only`：只跑 `_vector_search`
- `fts_only`：只跑 `_fts_search`
- `graph_only`：只跑 `graph_store.search_related`
- `hybrid`：默认组合

#### 版本化回归

- 每次评估记录 `git_commit` + `config_snapshot`（从 rag_config 表读取）
- 支持 `--compare` 对比最近两次 eval_runs 的 delta

### 3.5 异常处理

| 异常场景 | 异常类型 | 处理方式 |
|----------|----------|----------|
| golden.json 缺失 | FileNotFoundError | 报错退出，提示运行标注脚本 |
| 检索通道失败 | RetrievalException | 该通道返回空，不影响其他通道 |
| 数据库不可用 | Exception | 记录分数失败，打印警告继续 |
| 某题无 gold doc | ValueError | 跳过该题并记录 |

---

## 4. 验收标准

> 详细验收标准见同目录下的 `acceptance-criteria.md`

### 4.1 可运行的验证命令

```bash
# 1. golden 集加载测试
cd ai_service
python -c "
import json
data = json.load(open('eval/golden.json', encoding='utf-8'))
assert len(data) >= 20
for item in data:
    assert 'question' in item and 'golden_docs' in item
print(f'golden 集 OK: {len(data)} 题')
"

# 2. 召回评估（组合模式）
python -m eval.golden_retrieval

# 3. 单通道消融
python -m eval.golden_retrieval --mode vector_only
python -m eval.golden_retrieval --mode fts_only

# 4. 版本化记录确认
psql -U postgres -d personal_website -c "SELECT id, eval_type, git_commit, created_at FROM eval_runs ORDER BY id DESC LIMIT 3;"
```

### 4.2 预期输出

```
# 召回评估预期
====== Golden Retrieval Eval ======
Dataset: 30 questions
Mode: hybrid
Hit@5: 0.73
Recall@5: 0.65
MRR: 0.61
Saved to eval_runs (id=1, commit=xxxxx)
```

### 4.3 失败诊断方法

| 失败现象 | 可能原因 | 排查步骤 |
|----------|----------|----------|
| embedding API 502 | 外部服务不可用 | 检查网络/重试，评估可降级为仅 FTS |
| Hit@k 全 0 | golden_docs 标注错误 | 检查 gold 文档标题与知识库实际一致 |
| eval_runs 无记录 | 数据库连接失败 | 检查 DSN |

---

## 5. 依赖关系

### 5.1 上游依赖

| 依赖模块 | 依赖内容 | 状态 |
|----------|----------|------|
| module-005: RAG 核心 | hybrid_retriever.retrieve | ✅ |
| module-016: Graph RAG | graph_store.search_related | ✅ |
| module-018: Rerank | reranker（可选，评估基础召回） | ✅ |

### 5.2 下游依赖

| 被依赖模块 | 提供内容 | 状态 |
|------------|----------|------|
| module-020+: 中文FTS/缓存修复 | 可量化的验收基准 | 📋 |

### 5.3 外部依赖

| 外部服务 | 用途 | 可用性要求 |
|----------|------|------------|
| ModelScope embedding API | 向量检索 | 评估时可用（502 时降级仅 FTS） |

---

## 6. 风险点与注意事项

### 6.1 已知风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| embedding API 502 | 向量通道无法评估 | 中 | 消融模式可独立跑 FTS |
| golden_docs 标注不准确 | 指标失真 | 中 | 每题标注 1-3 个真实文档，人工核对 |

### 6.2 技术注意事项

- [x] golden_docs 用**文档标题**匹配（父块标题唯一，如 `G1垃圾收集器的Region分区机制与MixedGC全流程_2026-07-11`）
- [x] 评估只检索父块（`parent_id IS NULL`）
- [x] retriever 增加 mode 参数需保持默认 hybrid 不变
- [ ] 注意：`_expand_to_parents` 在评估中可跳过（直接评估子块命中）

### 6.3 开发建议

- 优先实现 golden.json + 组合模式评估，消融后做
- Hit@k 用 k=5（与生产 top_k 一致）
- 评估脚本独立于 RAGAS（纯检索，不调 LLM，快且可重复）

---

## 7. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-01 | 初始版本 | Planner |

---

## 8. 审批记录

| 角色 | 姓名 | 审批结果 | 日期 | 备注 |
|------|------|----------|------|------|
| Planner | 规划执行 | ✅ 通过 | 2026-08-01 | |
| Reviewer | | ⏳ 待审查 | | |
| Tester | | ⏳ 待测试 | | |

---

> **下一步**：Developer 根据本规格说明书开始编码实现。
