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

- [x] 📋 高质量候选召回多档 — 验证方式：候选绝对余弦 >0.85 → recall 召回 5 条（K=5 真实可达）
- [x] 📋 中质量召回 3 条 — 验证方式：绝对余弦 0.75-0.85 → K=3
- [x] 📋 低质量召回 1 条 — 验证方式：绝对余弦 <0.75 → K=1（宁缺毋滥保留）
- [x] 📋 低分过滤 — 验证方式：绝对余弦 < memory_recall_min_score 的候选被丢弃
- [x] 📋 空候选不崩 — 验证方式：无候选返回空

### 1.2 去重阈值校准

- [x] 📋 同义改写触发去重 — 验证方式：真实 cosine≈0.88 > 0.85 → 更新而非新增（条数不涨）
- [x] 📋 不同事实正常新增 — 验证方式：不同事实各自新增
- [x] 📋 阈值可配置 — 验证方式：config.memory_dedup_threshold 默认 0.85

### 1.3 min_score 校准

- [x] 📋 chat_stream MIN_SCORE 语义正确 — 验证方式：绝对口径或移除失真阈值
- [x] 📋 relevant_count 统计合理 — 验证方式：校准后统计不误放/误杀

### 1.4 三通道融合（可选，若实施）

- [ ] 📋 RRF 融合实现 — ⚠️ 不适用：P3 评估后不采纳（RRF 分数量纲与 engine._retrieve min_score=0.6 过滤硬阻塞，见 changelog 设计决策 5）
- [ ] 📋 golden_retrieval A/B — ⚠️ 不适用：同上

---

## 2. 接口验收

### 2.1 兼容性

- [x] 📦 memory.save/recall 签名不变
- [x] 📦 recall 返回格式不变（content/score/title/created_at）
- [x] 📦 chat/stream 端点签名不变
- [x] 📦 三层 source 分层不变（module-034）

### 2.2 配置

- [x] 📦 去重阈值默认 0.85 / 低分过滤阈值 可配置（config.py）

---

## 3. 代码质量验收

### 3.1 注释覆盖率

- [x] 💻 所有 public 方法有 Docstring

### 3.2 命名规范

- [x] 💻 Python snake_case

### 3.3 代码长度

- [x] 💻 单方法 ≤ 50 行
- [x] 💻 模块生产代码 ≤ 300 行（plan 声明调整）

### 3.4 编译检查

- [x] 💻 py_compile 通过
- [x] 💻 无未使用 import

---

## 4. 测试验收

### 4.1 单元测试

- [x] 🧪 动态 K 绝对余弦测试（多档 + 低分过滤 + 空候选）
- [x] 🧪 去重阈值 0.85 测试（同义改写触发 / 不同新增 / 失败降级）
- [ ] 🧪 RRF 融合单测（⚠️ 不适用：P3 评估后不采纳，见 changelog 设计决策 5）

### 4.2 回归测试

- [x] 🧪 `python -m pytest tests/ -q`：278 基线 + 新增通过 / 0 失败
- [x] 🧪 身份回归（test_identity.py）

### 4.3 真实 E2E（Tester 可选执行）

- [x] 🧪 登录对话 → 高质量记忆多档召回（K=5/3 可达）— 半真实 E2E 验证：K=5（均值 0.987）/ K=3（均值 0.793）均真实可达
- [x] 🧪 二次同义对话 → 去重触发不膨胀 — 半真实 E2E 验证：同义改写 save status=updated，parents 1→1
- [x] 🧪 低分记忆不注入 — 半真实 E2E 验证：无关记忆 recall K=0，实测 abs_cosine=0.31 < 0.4 被过滤

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

- [x] 📝 changelog.md 已更新（含版本/日期/变更/变更人）

### 5.2 设计说明

- [x] 📝 分数口径方案记录在 plan.md（§3）+ score-issues.md

### 5.3 共享记忆

- [x] 📝 memory/project-context.md 更新（module-035 行 + 技术决策）
- [x] 📝 memory/agent-activity-log.md 更新（PLAN/CODE/REVIEW/TEST）

---

## 验收执行结果

### 分项统计

> 注：原汇总表记 33 项，实际复选框 **35 项**（功能 12 vs 记 11、代码质量 6 vs 记 5），
> 按实际 35 项修正（module-033 先例）。「未执行」3 项为 P3 三通道融合（可选若实施），
> 经评估后决定不采纳（分数量纲与 engine._retrieve min_score=0.6 过滤硬阻塞，见
> changelog.md 设计决策 5），非跳过。

| 验收类别 | 总项数 | 通过 | 失败 | 未执行 |
|----------|--------|------|------|--------|
| 功能验收 | 12 | 10 | 0 | 2（P3 不采纳） |
| 接口验收 | 5 | 5 | 0 | 0 |
| 代码质量验收 | 6 | 6 | 0 | 0 |
| 测试验收 | 8 | 7 | 0 | 1（P3 不采纳） |
| 文档验收 | 4 | 4 | 0 | 0 |
| **合计** | **35** | **32** | **0** | **3** |

### 验收结论

- 审查人: Reviewer（m35-reviewer，已通过）
- 测试人: Tester（m35-tester）
- 验收时间: 2026-08-06
- 结论:
  - [x] ✅ **通过**
  - [ ] ❌ **不通过**
  - [ ] ⚠️ **有条件通过**
- 备注: 全量回归 292 passed / 0 failed；记忆单测 95/95（81 基线 + 14 新增）；
  身份回归 20/20；下游消费者（engine/stream/session）18/18；py_compile OK；
  半真实 E2E 通过（K=5/K=3 真实可达、去重触发不膨胀、低分不注入，测试数据已清理）。
  P3 三通道 RRF 经评估不采纳，记录 backlog。

---

> **下一步**：
> - 通过：更新 `memory/project-context.md`，模块标记 ✅
> - 不通过：通知 Developer 修复后重新验收
