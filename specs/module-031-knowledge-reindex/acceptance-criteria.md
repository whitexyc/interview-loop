# 验收标准 — Module-031: 知识库重建（父子分块 reindex）

> 本文件由 **Planner** 在输出开发计划时同步编写，由 **Tester** 在测试阶段执行验收。
> 所有检查项使用 `- [ ]` 复选框格式，验收时勾选。

---

## 验收元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-031 |
| 模块名称 | 知识库重建（父子分块 reindex） |
| 关联 plan.md | `specs/module-031-knowledge-reindex/plan.md` |
| 验收日期 | 2026-08-04 |
| 验收人 | Tester |
| 验收版本 | 0.31.0-module-031 |

---

## 1. 功能验收

### 1.1 分块质量（重建后库内数据）

- [ ] 📋 无 >4000 字符父块 — 验证方式：`SELECT COUNT(*) FROM documents WHERE parent_id IS NULL AND LENGTH(content) > 4000` 返回 0（对比重建前 68 个 >8000）
- [ ] 📋 子块平均长度 ~300 字符 — 验证方式：`AVG(LENGTH(content))` 子块在 200-500 区间（对比重建前 21,083）
- [ ] 📋 ### 级父块粒度占比 ≥ 85% — 验证方式：父块标题含 ` > ` 的比例（实测 89%，对比重建前 0%）
- [ ] 📋 旧"整篇 1 父+1 子"记录清零 — 验证方式：无 title 相同且 len>4000 的成对父/子记录

### 1.2 chunker 分块规则（Option C）

- [ ] 📋 ### 子小节成为独立父块，标题"小节 > 子小节"（test_h3_subsection_splits）
- [ ] 📋 超大父块（>4000）被切分为多个子父块，每个 ≤ 上限（test_parent_size_cap）
- [ ] 📋 无 ## 长文档 → 1 父块 + 多子块（test_no_heading_long_text_splits_children）
- [ ] 📋 无 ## 超长文本（>4000）→ 多个子父块（test_no_heading_big_text_size_capped）
- [ ] 📋 所有 ## 小节 < min_chars → 整篇兜底 + 多子块（test_all_sections_below_min_chars_fallback）
- [ ] 📋 极短内容 → 返回空（引擎兜底 1+1，test_tiny_text_returns_empty）

### 1.3 图谱一致性

- [ ] 📋 图谱已清空重建 — 验证方式：Entity/RELATED_TO 无旧 doc_id 引用（graph 查询 doc_ids 均指向重建后父块 id）
- [ ] 📋 图谱提取失败不阻断 — 验证方式：脚本单篇失败 warning 后继续（代码审查确认）

### 1.4 边界条件

- [ ] 🔲 标题冲突（overview 两目录）— 后者加后缀不丢失
- [ ] 🔲 .workbuddy 子目录跳过 — 不入库
- [ ] 🔲 空/极短文件 — 引擎兜底 1+1，不崩溃
- [ ] 🔲 --dry-run 不写库 — 只打印统计

---

## 2. 接口验收

### 2.1 重建脚本

- [ ] 📦 `python reindex_knowledge_base.py` 可运行（含 --dry-run / --no-graph 参数）
- [ ] 📦 documents 表结构不变（title/content/source/embedding/parent_id/content_hash/search_tokens）
- [ ] 📦 检索接口 / RAG 链路零改动（仅数据重建）

### 2.2 幂等性

- [ ] 📦 脚本重跑不产生重复记录 — 验证方式：连续两次运行，第二次无新增

---

## 3. 代码质量验收

### 3.1 注释覆盖率

- [ ] 💻 所有 public 方法有 Docstring

### 3.2 命名规范

- [ ] 💻 函数/变量符合 snake_case

### 3.3 代码长度

- [ ] 💻 单方法 ≤ 50 行（脚本按阶段拆函数）
- [ ] 💻 新增代码 ≤ 400 行

### 3.4 编译检查

- [ ] 💻 Python 语法通过（py_compile）
- [ ] 💻 无未使用 import

---

## 4. 测试验收

### 4.1 单元测试

- [ ] 🧪 tests/test_chunker.py 5/5 passed（含 fallback 加固回归）

### 4.2 数据验证

- [ ] 🧪 重建后无 >8000 字符父块（真实库查询）
- [ ] 🧪 子块平均长度 ~300 字符（真实库查询）

### 4.3 检索质量 E2E

- [ ] 🧪 "什么是G1垃圾收集器" 真实检索返回 G1 文档（不再返回 Redis 缓存文档）
- [ ] 🧪 rerank 输入为 ~300 字符子块（耗时 < 3s 级别）

### 4.4 回归测试

- [ ] 🧪 `python -m pytest ai_service/tests/ -x` 无新增失败（181 passed / 2 既有 async 技术债务失败，无新增）

### 4.5 测试命令

```bash
cd ai_service
# 1. 单元测试
python -m pytest tests/test_chunker.py -q

# 2. 重建前统计（基线）——连接 DSN 从项目配置读取（src.config settings.DATABASE_URL / .env），勿硬编码
python -c "
import asyncio
from sqlalchemy import text
from src.database import async_session_factory
async def main():
    async with async_session_factory() as s:
        big = await s.execute(text(\"SELECT COUNT(*) FROM documents WHERE parent_id IS NULL AND LENGTH(content)>8000\"))
        avg = await s.execute(text(\"SELECT AVG(LENGTH(content)) FROM documents WHERE parent_id IS NOT NULL\"))
        print('父块>8000:', big.scalar())
        print('子块平均:', avg.scalar())
asyncio.run(main())"

# 3. 重建（先 dry-run）
python reindex_knowledge_base.py --dry-run
python reindex_knowledge_base.py

# 4. 重建后统计（同上命令，应满足 AC）

# 5. 回归
python -m pytest tests/ -q
```

**预期输出**：
```
单元测试: 5 passed
重建前: 父块>8000 = 68, 子块平均 = 21083
重建后: 父块>8000 = 0, 子块平均 ≈ 300
回归: ===== 181 passed, 2 failed (既有 async 债务) =====
```

---

## 5. 文档验收

### 5.1 变更记录

- [ ] 📝 changelog.md 已更新
- [ ] 📝 包含版本号/日期/变更内容/变更人（v1 / 2026-08-04 / Developer）

### 5.2 设计说明

- [ ] 📝 chunker fallback 加固记录在 plan.md（§3.2 功能 1）
- [ ] 📝 重建脚本方案记录在 plan.md（§3.2 功能 2）

### 5.3 共享记忆

- [ ] 📝 memory/project-context.md 更新（module-031 行 + 技术决策）
- [ ] 📝 memory/agent-activity-log.md 更新（PLAN/CODE/REVIEW/TEST 活动）

---

## 验收执行结果

### 分项统计

| 验收类别 | 总项数 | 通过 | 失败 | 未执行 |
|----------|--------|------|------|--------|
| 功能验收 | 12 | 0 | 0 | 0 |
| 接口验收 | 3 | 0 | 0 | 0 |
| 代码质量验收 | 6 | 0 | 0 | 0 |
| 测试验收 | 8 | 0 | 0 | 0 |
| 文档验收 | 5 | 0 | 0 | 0 |
| **合计** | **34** | **0** | **0** | **0** |

### 失败详情

| 序号 | 类别 | 失败项 | 失败原因 | 建议修复方式 |
|------|------|--------|----------|--------------|
| — | — | 待执行 | — | — |

### 验收结论

- 审查人: Reviewer
- 测试人: Tester
- 验收时间: 2026-08-04
- 结论:
  - [ ] ✅ **通过**
  - [ ] ❌ **不通过**
  - [ ] ⚠️ **有条件通过**
- 备注: 待执行

---

> **下一步**：
> - 通过：更新 `memory/project-context.md`，模块标记 ✅
> - 不通过：通知 Developer 修复后重新验收
