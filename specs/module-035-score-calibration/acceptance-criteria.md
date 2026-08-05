# 验收标准 — Module-035: 记忆/检索分数口径校准

> 本文件由 **Planner** 在输出开发计划时同步编写，由 **Tester** 在测试阶段执行验收。
> 所有检查项使用 `- [ ]` 复选框格式，验收时勾选。

---

## 验收元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-035 |
| 模块名称 | 记忆/检索分数口径校准 |
| 关联 plan.md | `specs/module-035-score-calibration/plan.md` |
| 验收日期 | 2026-08-06 |
| 验收人 | Tester |
| 验收版本 | 0.35.0-module-035 |

---

## 1. 功能验收

### 1.1 动态 K 绝对余弦

- [ ] 📋 高质量候选召回多档 — 验证方式：候选绝对余弦 >0.85 → recall 召回 5 条（K=5 真实可达）
- [ ] 📋 中质量召回 3 条 — 验证方式：绝对余弦 0.75-0.85 → K=3
- [ ] 📋 低质量召回 1 条 — 验证方式：绝对余弦 <0.75 → K=1（宁缺毋滥保留）
- [ ] 📋 低分过滤 — 验证方式：绝对余弦 < memory_recall_min_score 的候选被丢弃
- [ ] 📋 空候选不崩 — 验证方式：无候选返回空

### 1.2 去重阈值校准

- [ ] 📋 同义改写触发去重 — 验证方式：真实 cosine≈0.88 > 0.85 → 更新而非新增（条数不涨）
- [ ] 📋 不同事实正常新增 — 验证方式：不同事实各自新增
- [ ] 📋 阈值可配置 — 验证方式：config.memory_dedup_threshold 默认 0.85

### 1.3 min_score 校准

- [ ] 📋 chat_stream MIN_SCORE 语义正确 — 验证方式：绝对口径或移除失真阈值
- [ ] 📋 relevant_count 统计合理 — 验证方式：校准后统计不误放/误杀

### 1.4 三通道融合（可选，若实施）

- [ ] 📋 RRF 融合实现 — 验证方式：hybrid 模式用 RRF 排名融合（golden A/B 不劣于现状才采纳）
- [ ] 📋 golden_retrieval A/B — 验证方式：Hit@k/MRR 对比 RRF vs 加权

---

## 2. 接口验收

### 2.1 兼容性

- [ ] 📦 memory.save/recall 签名不变
- [ ] 📦 recall 返回格式不变（content/score/title/created_at）
- [ ] 📦 chat/stream 端点签名不变
- [ ] 📦 三层 source 分层不变（module-034）

### 2.2 配置

- [ ] 📦 去重阈值默认 0.85 / 低分过滤阈值 可配置（config.py）

---

## 3. 代码质量验收

### 3.1 注释覆盖率

- [ ] 💻 所有 public 方法有 Docstring

### 3.2 命名规范

- [ ] 💻 Python snake_case

### 3.3 代码长度

- [ ] 💻 单方法 ≤ 50 行
- [ ] 💻 模块生产代码 ≤ 300 行（plan 声明调整）

### 3.4 编译检查

- [ ] 💻 py_compile 通过
- [ ] 💻 无未使用 import

---

## 4. 测试验收

### 4.1 单元测试

- [ ] 🧪 动态 K 绝对余弦测试（多档 + 低分过滤 + 空候选）
- [ ] 🧪 去重阈值 0.85 测试（同义改写触发 / 不同新增 / 失败降级）
- [ ] 🧪 RRF 融合单测（若实施 P3）

### 4.2 回归测试

- [ ] 🧪 `python -m pytest tests/ -q`：278 基线 + 新增通过 / 0 失败
- [ ] 🧪 身份回归（test_identity.py）

### 4.3 真实 E2E（Tester 可选执行）

- [ ] 🧪 登录对话 → 高质量记忆多档召回（K=5/3 可达）
- [ ] 🧪 二次同义对话 → 去重触发不膨胀
- [ ] 🧪 低分记忆不注入

### 4.4 测试命令

```bash
cd ai_service
python -m pytest tests/test_memory.py tests/test_memory_extractor.py -q
python -m pytest tests/ -q
python -m pytest tests/test_retriever_rrf.py -q   # 若实施 P3
python -m eval.golden_retrieval                   # 若实施 P3
```

**预期输出**：新增/更新单测全过；全量 278 + 新增 / 0 失败。

---

## 5. 文档验收

### 5.1 变更记录

- [ ] 📝 changelog.md 已更新（含版本/日期/变更/变更人）

### 5.2 设计说明

- [ ] 📝 分数口径方案记录在 plan.md（§3）+ score-issues.md

### 5.3 共享记忆

- [ ] 📝 memory/project-context.md 更新（module-035 行 + 技术决策）
- [ ] 📝 memory/agent-activity-log.md 更新（PLAN/CODE/REVIEW/TEST）

---

## 验收执行结果

### 分项统计

| 验收类别 | 总项数 | 通过 | 失败 | 未执行 |
|----------|--------|------|------|--------|
| 功能验收 | 11 | 0 | 0 | 0 |
| 接口验收 | 5 | 0 | 0 | 0 |
| 代码质量验收 | 5 | 0 | 0 | 0 |
| 测试验收 | 8 | 0 | 0 | 0 |
| 文档验收 | 4 | 0 | 0 | 0 |
| **合计** | **33** | **0** | **0** | **0** |

### 验收结论

- 审查人: Reviewer
- 测试人: Tester
- 验收时间: 2026-08-06
- 结论:
  - [ ] ✅ **通过**
  - [ ] ❌ **不通过**
  - [ ] ⚠️ **有条件通过**
- 备注: 待执行

---

> **下一步**：
> - 通过：更新 `memory/project-context.md`，模块标记 ✅
> - 不通过：通知 Developer 修复后重新验收
