# 功能规格说明书 — Module-044: Rerank 截断验证 + 反思充分性精确化

> Planner | 2026-08-09

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-044 |
| 模块名称 | Rerank 截断验证（ADR-0004 TODO）+ 反思充分性精确化（ADR-0005 层 0-3） |
| 版本号 | 0.44.0-module-044 |
| 优先级 | P1（充分性判断仍是 LLM 单点主观，缺客观分数闸门；重排 250 vs 500 拐点未验证） |
| 预估代码量 | WP1 验证实验 + WP2 评测闭环 + WP3-5 重构 ≤ 400 行 |

---

## 2. 需求

### 2.1 现状缺口（两 ADR 依据）

| 缺口 | 现状 | 出处 |
|------|------|------|
| 重排截断拐点未验证 | `_MAX_PAIR_CHARS=500` 已采纳，但 250 是否更优未测（ADR-0004 TODO：补 250/500/1000/2000 四档选数表） | ADR-0004 |
| 充分性判断 LLM 单点 | `check_sufficiency` 只要文档非空就完全由 LLM 说了算，无客观分数参与（仅 3 道代码闸门：空文档短路 / ≥3 篇跳过 / 超时兜底） | ADR-0005 |
| 无充分性评测闭环 | 无法量化"充分性判断对错"，改进盲人摸象 | ADR-0005 层 0 |

### 2.2 目标（ADR-0005 层 0-3 + ADR-0004 TODO；层 4 小分类器明确不做——数据积累后另行模块，与 ADR-0003 L4 同理）

1. **WP1 ADR-0004 验证**：实测 250 vs 500 字符截断的分数与耗时，决策采纳或保持，补四档选数表
2. **WP2 层 0 评测闭环**：充分性标注集 + `eval_type='sufficiency'` 版本化回归 + Accuracy/P/R（重点 Recall）
3. **WP3 层 1 分数硬闸门**：top-1 绝对余弦 < 0.4 → 直接判不充分（不调 LLM）；文档数 < 2 → 判不充分
4. **WP4 层 2 prompt 强化**：few-shot 正反例 + CoT 信息点比对；自洽性检查（两次判断）做配置开关默认关（成本翻倍，按需开启）
5. **WP5 层 3 多信号融合**：分数达标才问 LLM，LLM 只判模糊地带；分数低直接不充分；LLM 不充分仍尊重语义走 rewritten

### 2.3 验收场景

```
场景 1：分数硬闸门（不调 LLM）
  假设 检索结果 top-1 abs_cosine = 0.25（< 0.4），文档非空
  那么 直接返回 sufficient=false + rewritten_query，全程零 LLM 调用

场景 2：文档数闸门
  假设 只有 1 篇文档
  那么 直接判不充分（不调 LLM）

场景 3：分数达标 → LLM 判模糊地带
  假设 top-1 abs_cosine = 0.7，LLM 判充分
  那么 返回 sufficient=true（行为与旧版一致）

场景 4：LLM 语义尊重
  假设 分数高但 LLM 判不充分（看到规则看不到的语义缺口）
  那么 尊重 LLM，走 rewritten_query 二次检索

场景 5：闸门异常 → 保守充分
  假设 abs_cosine 字段缺失/异常
  那么 不误杀，继续走 LLM 判断（保持现有降级哲学）

场景 6：评测闭环
  假设 跑 eval/golden_sufficiency.py
  那么 输出 Accuracy/P/R/F1（重点 Recall）+ eval_runs eval_type='sufficiency' 落库

场景 7：250 截断验证
  假设 改 _MAX_PAIR_CHARS=250 跑 2 pair / 6 pair
  那么 记录分数与耗时 vs 500，补齐四档选数表 → 数据驱动决策
```

---

## 3. 技术方案

### 3.1 工作包与涉及文件

| WP | 内容 | 文件 | 操作 |
|----|------|------|------|
| WP1 | 250 截断验证实验（临时改 _MAX_PAIR_CHARS=250 实测 → 决策 → 记录） | `ai_service/rag/reranker.py` + `ai_service/eval/benchmark_rerank.py` | 新建 benchmark + 可能改 1 行 |
| WP2 | 充分性标注集 + 评测脚本 | `ai_service/eval/golden_sufficiency.py` | 新建 |
| WP2 | 测试 | `ai_service/tests/test_golden_sufficiency.py` | 新建 |
| WP3+4+5 | check_sufficiency 重构：分数/数量硬闸门 + prompt 强化 + 多信号融合 | `ai_service/agent/reflector.py` | 修改 |
| WP3+4+5 | 测试 | `ai_service/tests/test_reflector.py` | 修改（追加） |

### 3.2 核心逻辑

#### WP3+5 check_sufficiency 重构（核心）

```python
async def check_sufficiency(self, query, documents):
    if not documents:
        return {"sufficient": False, "reason": "未检索到任何文档", "rewritten_query": query}
    # 层 1 分数/数量硬闸门（零 LLM）
    if len(documents) < 2:
        return {"sufficient": False, "reason": "文档数不足 2", "rewritten_query": query}
    top1_abs = documents[0].get("abs_cosine", None)   # 注意：需按精排后顺序
    if top1_abs is not None and top1_abs < 0.4:
        return {"sufficient": False, "reason": f"top-1 绝对余弦 {top1_abs:.3f} < 0.4", "rewritten_query": query}
    # 分数达标 → LLM 判模糊地带（层 2 prompt 强化版）
    ...
```

注意点（Dev 必须核对）：
- `documents` 是否带 `abs_cosine`：module-043 已在 retriever 归一化前存档 abs_cosine、engine 精排后 docs 应含该字段——Dev 需沿 engine.py 调用链确认；缺失时 `d.get("abs_cosine", None)` 走 LLM（不误杀）
- 现有 `_MIN_DOCS_SKIP_REFLECT=3` 在 engine 层（≥3 篇跳过反思）与本闸门互补不冲突
- 闸门失败/异常 → 回退 LLM 路径（保持"默认充分防死循环"哲学，不新增强制路径）

#### WP4 _CHECK_PROMPT 强化

- 加 few-shot：充分/不充分真实正反例各 1-2 条
- 加 CoT：先要求 LLM 列出"回答该问题需要的信息点"，再逐点比对文档覆盖情况 → 再下结论
- 自洽性检查：配置开关（`PW_SUFFICIENCY_SELF_CHECK_ENABLED`，默认 False），开启时同 query 两温度各判一次、不一致 → 保守充分
- prompt 变更是向后兼容的（返回结构不变：sufficient/reason/rewritten_query）

#### WP1 benchmark

- 新建 `eval/benchmark_rerank.py`：可配截断参数（--max-chars 250/500/1000/2000）+ 2 pair / 6 pair 计时 + 分数输出
- 实测 250 vs 500（模型在 worktree `ai_service/models/bge-reranker-v2-m3`），数据记录进 changelog/ADR-0004 更新
- 决策规则：250 分数 ≥ 0.98 且耗时显著下降 → 采纳 250；否则保持 500。**数据驱动，结果两种都可能，如实记录**

#### WP2 golden_sufficiency

- 标注集：从 golden 集取问题（真实检索或 fixture 注入）→ 每条标"充分/不充分"（种子脚本生成 + 文档记录人工确认流程）
- 指标：Accuracy + per-class P/R/F1（重点 knowledge-sufficient 的 Recall）+ 混淆矩阵 + eval_runs 落库（eval_type='sufficiency'，对齐 golden_retrieval.py 模式）
- 环境不可用时提供 fixture 模式（注入模拟文档）交付脚本 + 方法学

### 3.3 降级

| 场景 | 处理 |
|------|------|
| abs_cosine 缺失 | 走 LLM（不误杀） |
| LLM 判断失败 | 默认充分（防死循环，现有行为） |
| 自洽性检查开启时 LLM 异常 | 保守充分 |
| 模型/环境不可用 | benchmark 交付脚本 + 方法学，实测数据后补 |

---

## 4. 依赖

- module-035（绝对余弦口径）、module-037（abs_cosine 字段）、module-043（retriever 存 abs_cosine + L3 反证复用同一字段）
- ADR-0004（截断决策 + TODO）、ADR-0005（五层方案）
- module-038（golden 评测集结构，WP2 对齐）

## 5. 已知边界（写入验收）

- **层 4 小分类器不做**：数据积累后另行模块（与 ADR-0003 L4 同理，plan 已注明）
- **预存失败**：test_identity.py top_k（1 项）+ test_rerank_langgraph 外部 429（2 项）为环境问题，不计入
- **worktree 未提交改动**（react.py/main.py 等，来自其他会话）：不得 stage，提交只含本模块文件
