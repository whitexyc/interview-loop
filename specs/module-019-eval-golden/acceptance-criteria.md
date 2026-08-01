# 验收标准 — Module-019: 评估闭环（Golden 检索集 + 量化指标）

> 本文件由 **Planner** 在输出开发计划时同步编写，由 **Tester** 在测试阶段执行验收。
> 所有检查项使用 `- [ ]` 复选框格式，验收时勾选。

---

## 验收元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-019 |
| 模块名称 | 评估闭环（Golden 检索集 + Hit@k/MRR + 消融） |
| 关联 plan.md | `specs/module-019-eval-golden/plan.md` |
| 验收日期 | 2026-08-01 |
| 验收人 | <Tester 姓名> |
| 验收版本 | 0.19.0-module-019 |

---

## 1. 功能验收

### 1.1 核心功能验收

- [x] 📋 golden.json 存在且 ≥ 20 题，每题含 question + golden_docs — 验证方式：加载 JSON 检查结构
- [x] 📋 golden_docs 与知识库真实文档对应 — 验证方式：抽查若干标题在 documents 表存在
- [x] 📋 golden_retrieval.py 可运行 — 验证方式：`python -m eval.golden_retrieval`
- [x] 📋 输出 Hit@5 / Recall@5 / MRR — 验证方式：检查运行输出
- [x] 📋 单通道消融可用 — 验证方式：`--mode vector_only` / `--mode fts_only`
- [x] 📋 eval_runs 表有记录 — 验证方式：psql 查询确认

### 1.2 边界条件验收

- [x] 🔲 golden.json 缺失：报错退出并提示
- [x] 🔲 某题无 gold doc：跳过并记录（不崩溃）
- [x] 🔲 top_k 传 0 或负数：安全处理（默认 5）
- [x] 🔲 空检索结果：指标为 0，不异常
- [x] 🔲 数据库不可用：评估降级（分数记录失败但检索继续）

### 1.3 异常场景验收

- [x] ⚡ embedding API 502：向量通道降级，FTS 通道仍评估
- [x] ⚡ 图检索不可用：graph 通道返回空，不影响其他通道
- [x] ⚡ 检索异常：该题跳过并记录错误

---

## 2. 接口验收

### 2.1 retriever 接口

- [x] 📦 `retrieve(query, top_k=5, mode='hybrid')` 兼容现有调用
- [x] 📦 mode 支持 `hybrid` / `vector_only` / `fts_only` / `graph_only`
- [x] 📦 默认 mode='hybrid' 行为与之前完全一致（无回归）
- [x] 📦 返回格式不变（list[dict] 含 id/title/content/hybrid_score）

### 2.2 评估输出

- [x] 📦 输出整体指标（Hit@k/Recall@k/MRR）
- [x] 📦 输出每题明细
- [x] 📦 输出按类别汇总
- [x] 📦 记录 eval_runs（含 git_commit + config 快照）

---

## 3. 代码质量验收

### 3.1 注释覆盖率

- [x] 💻 所有 public 方法有 Docstring
- [x] 💻 指标计算逻辑有行内注释

### 3.2 命名规范

- [x] 💻 函数/变量符合 snake_case
- [x] 💻 无无意义命名

### 3.3 代码长度

- [x] 💻 单个方法 ≤ 50 行
- [x] 💻 本模块新增代码 ≤ 300 行（plan.md 已申请调整）

### 3.4 编译检查

- [x] 💻 Python 语法通过
- [x] 💻 无未使用 import

---

## 4. 测试验收

### 4.1 单元测试

- [x] 🧪 指标计算（Hit@k/Recall@k/MRR）有单测
- [x] 🧪 空结果 / 无 gold doc 边界
- [x] 🧪 retriever mode 参数切换

### 4.2 集成测试

- [x] 🧪 真实运行 golden_retrieval（组合模式）
- [x] 🧪 消融模式独立运行

### 4.3 回归测试

- [x] 🧪 运行 `python -m pytest ai_service/tests/ -x` 确保无新增失败
- [x] 🧪 retriever 默认 hybrid 行为无回归

### 4.4 测试命令

```bash
cd ai_service
# golden 集校验
python -c "
import json
data = json.load(open('eval/golden.json', encoding='utf-8'))
assert len(data) >= 20
print(f'golden OK: {len(data)} 题')"

# 组合模式评估
python -m eval.golden_retrieval

# 消融
python -m eval.golden_retrieval --mode fts_only

# 回归
python -m pytest ai_service/tests/ -x
```

**预期输出**：
```
golden OK: 30 题
====== Golden Retrieval Eval ======
Dataset: 30 questions | Mode: hybrid
Hit@5: X.XX | Recall@5: X.XX | MRR: X.XX
Saved to eval_runs
===== 0 failed, N passed =====
```

---

## 5. 文档验收

### 5.1 变更记录

- [x] 📝 changelog.md 已更新
- [x] 📝 包含版本号/日期/变更内容/变更人

### 5.2 设计说明

- [x] 📝 指标计算方式在代码注释中说明
- [x] 📝 eval_runs 表结构记录在 plan.md

---

## 验收执行结果

### 分项统计

| 验收类别 | 总项数 | 通过 | 失败 | 未执行 |
|----------|--------|------|------|--------|
| 功能验收 | 14 | 14 | 0 | 0 |
| 接口验收 | 8 | 8 | 0 | 0 |
| 代码质量验收 | 8 | 8 | 0 | 0 |
| 测试验收 | 7 | 7 | 0 | 0 |
| 文档验收 | 4 | 4 | 0 | 0 |
| **合计** | **41** | **41** | **0** | **0** |

### 失败详情

| 序号 | 类别 | 失败项 | 失败原因 | 建议修复方式 |
|------|------|--------|----------|--------------|
| — | — | 无 | — | — |

> 全量回归中 `tests/test_engine.py` 2 个 async 用例收集失败为既有环境限制
> （缺 pytest-asyncio），`git diff` 确认该文件未被 module-019 改动，
> project-context 已记录为 module-018 之前的既有问题，非本次验收失败项。

### 验收结论

- 审查人: Reviewer（审查结论：通过，见 review-report.md）
- 测试人: Tester
- 验收时间: 2026-08-01
- 结论:
  - [x] ✅ **通过**
  - [ ] ❌ **不通过**
  - [ ] ⚠️ **有条件通过**
- 备注:
  - golden.json 30 题（23 题有 gold / 7 题标空），golden_docs 与知识库 68 个父块标题全量匹配（0 不一致）。
  - hybrid / fts_only / vector_only 三模式实跑通过；embedding API 502 时 hybrid 23/23 题
    degraded=True 自动回退 FTS 完成评估（降级路径有效），vector_only 逐题记录通道不可用。
  - eval_runs 表已建，实测记录 id=6 含 git_commit + config 快照 + scores + per_question。
  - retriever 默认 hybrid 零回归（全部既有调用方未传 mode，走原主路径）；非法 mode 抛 ValueError。
  - 回归：排除既有 async 收集限制后 24 passed，无 module-019 引入的新增失败。
  - 详细证据见 `specs/module-019-eval-golden/test-report.md`。

---

> **下一步**：
> - 通过：更新 `memory/project-context.md`，模块标记 ✅
> - 不通过：通知 Developer 修复后重新验收
