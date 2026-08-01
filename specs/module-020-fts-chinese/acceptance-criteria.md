# 验收标准 — Module-020: 中文 FTS 复活（jieba 预分词）

> 本文件由 **Planner** 在输出开发计划时同步编写，由 **Tester** 在测试阶段执行验收。
> 所有检查项使用 `- [ ]` 复选框格式，验收时勾选。

---

## 验收元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-020 |
| 模块名称 | 中文 FTS 复活（jieba 预分词） |
| 关联 plan.md | `specs/module-020-fts-chinese/plan.md` |
| 验收日期 | 2026-08-01 |
| 验收人 | Tester |
| 验收版本 | 0.20.0-module-020 |

---

## 1. 功能验收

### 1.1 核心功能验收

- [x] 📋 分词工具 tokenize() 正确分词中文 — 验证方式：`tokenize('Java线程池核心参数')` → 含"线程 池 核心 参数"
- [x] 📋 入库时写入 search_tokens — 验证方式：新增文档后查询 search_tokens 非空
- [x] 📋 FTS 检索用 search_tokens — 验证方式：`_fts_search` SQL 查 search_tokens
- [x] 📋 查询侧 jieba 分词 — 验证方式：中文查询能命中
- [x] 📋 FTS 评估 Hit@5 提升 — 验证方式：`golden_retrieval --mode fts_only` 从 0.0 提升到 > 0.3

### 1.2 边界条件验收

- [x] 🔲 空文本分词：返回空串不崩溃
- [x] 🔲 纯英文文本：分词正常（jieba 处理英文）
- [x] 🔲 search_tokens 为 NULL 的旧文档：FTS 查询过滤掉
- [x] 🔲 查询为空串：FTS 返回空列表

### 1.3 异常场景验收

- [x] ⚡ jieba 未安装：明确报错提示
- [x] ⚡ 分词异常：跳过该文档并记录，不影响其他
- [x] ⚡ backfill 中途失败：可重跑（幂等）

---

## 2. 接口验收

### 2.1 分词工具接口

- [x] 📦 `tokenize(text) -> str` 返回空格连接的分词串
- [x] 📦 同一文本重复调用返回相同结果（缓存）
- [x] 📦 特殊字符（标点/符号）被正确过滤

### 2.2 FTS 检索

- [x] 📦 `_fts_search` 仍返回 list[dict]（含 id/title/content/hybrid_score）
- [x] 📦 mode='fts_only' 行为正确
- [x] 📦 mode='hybrid' 中 FTS 通道用新逻辑（无回归）

### 2.3 数据库

- [x] 📦 search_tokens 列存在
- [x] 📦 GIN 索引存在
- [x] 📦 backfill 后已有文档都有 search_tokens

---

## 3. 代码质量验收

### 3.1 注释覆盖率

- [x] 💻 所有 public 方法有 Docstring
- [x] 💻 分词/检索逻辑有行内注释

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

- [x] 🧪 分词工具单测（中文/英文/空/特殊字符）
- [x] 🧪 _fts_search 查询逻辑

### 4.2 集成测试

- [x] 🧪 新增文档后 search_tokens 正确写入
- [x] 🧪 backfill 脚本对已有文档生效
- [x] 🧪 FTS 检索命中中文查询

### 4.3 回归测试

- [x] 🧪 `python -m pytest ai_service/tests/ -x` 无新增失败
- [x] 🧪 retriever hybrid/vector_only 无回归
- [x] 🧪 golden_retrieval 各模式可运行

### 4.4 测试命令

```bash
cd ai_service
# 分词测试
python -c "
from rag.text_tokenizer import tokenize
t = tokenize('Java线程池核心参数')
assert '线程' in t and '池' in t and '核心' in t
print('分词 OK:', t)"

# backfill
python backfill_search_tokens.py

# FTS 评估
python -m eval.golden_retrieval --mode fts_only

# 回归
python -m pytest ai_service/tests/ -x
```

**预期输出**：
```
分词 OK: java 线程 池 核心 参数
Hit@5: 0.3+（从 0.0 提升）
===== 0 failed, N passed =====
```

---

## 5. 文档验收

### 5.1 变更记录

- [x] 📝 changelog.md 已更新
- [x] 📝 包含版本号/日期/变更内容/变更人

### 5.2 设计说明

- [x] 📝 分词方案（jieba + simple）记录在 plan.md
- [x] 📝 search_tokens 列与 GIN 索引记录在 plan.md

---

## 验收执行结果

### 分项统计

| 验收类别 | 总项数 | 通过 | 失败 | 未执行 |
|----------|--------|------|------|--------|
| 功能验收 | 12 | 12 | 0 | 0 |
| 接口验收 | 9 | 9 | 0 | 0 |
| 代码质量验收 | 8 | 8 | 0 | 0 |
| 测试验收 | 8 | 8 | 0 | 0 |
| 文档验收 | 4 | 4 | 0 | 0 |
| **合计** | **41** | **41** | **0** | **0** |

### 失败详情

| 序号 | 类别 | 失败项 | 失败原因 | 建议修复方式 |
|------|------|--------|----------|--------------|
| 1 | | | | |

### 验收结论

- 审查人: Reviewer（已于 review-report.md 签署 ✅，2026-08-01）
- 测试人: Tester
- 验收时间: 2026-08-01
- 结论:
  - [x] ✅ **通过**
  - [ ] ❌ **不通过**
  - [ ] ⚠️ **有条件通过**
- 备注: FTS Hit@5 由基线 0.0 提升至 0.4348（阈值 0.3）；tokenizer 单测 10/10、新增 _fts_search 单测 4/4、test_golden_retrieval 20/20 全过；backfill 幂等（68/68 已回填，重跑 0 pending）；hybrid Hit@5=0.9130 / vector_only Hit@5=0.8696 无回归；全量 pytest 38 passed + 2 failed（2 failed 为既有 pytest-asyncio 环境问题，非本模块回归，详见 test-report.md）。「无未使用 import」项中 retriever.py 的 `settings` import 为 module-020 之前遗留，本模块新增 import 均使用，不计为失败。

---

> **下一步**：
> - 通过：更新 `memory/project-context.md`，模块标记 ✅
> - 不通过：通知 Developer 修复后重新验收
