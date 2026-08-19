# 功能规格说明书 — Module-057: 数据验证批（矛盾改进 + 图谱消融 + 改写增益 + RRF 扫描 + 飞轮冒烟）

> Planner | 2026-08-12

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-057 |
| 模块名称 | 数据验证批：mDeBERTa 矛盾改进 / 图谱消融 / 改写增益 / RRF k 扫描 / 飞轮冒烟 |
| 版本号 | 0.57.0-module-057 |
| 优先级 | P0（5 个硬数字：矛盾 kappa、图谱增量、改写增益、RRF 最优 k、反馈落库链路——全部数据说话，简历弹药直接可写） |
| 预估代码量 | 评估侧改进 + 数据扩充 + 冒烟 + 测试，≤ 500 行 |

---

## 2. 需求

| WP | 内容 | 来源 |
|----|------|------|
| WP-A1 mDeBERTa 矛盾改进 | 句级拆解（claim 切子句逐句判，任一矛盾→contradiction）+ 置信度阈值校准（0.5-0.9 扫描）+ 矛盾样本扩至 ≥50 条（internal 重点 ≥20 条多句混合）→ 重跑复测 kappa 对比 0.5167 | module-054 复测失败模式 + 用户"A1-A4 一起做" |
| WP-A2 图谱消融补跑 | DB 已修复（module-053）→ `golden_retrieval --ablate` → "图谱 +X.X Hit@5" 硬数字 | module-047 待环境项（环境已就绪） |
| WP-A3 改写真实增益 | `golden_query_rewrite` 真实模式（DB+LLM 就绪）→ 原始 vs 改写 Recall@K/MRR 对比 | module-049 待环境项（环境已就绪） |
| WP-A4 RRF k 扫描 + 归因 | k 值扫描（20-100 步长 10）→ 本场景最优 k；两通道 RRF 归因（图谱贡献 vs 融合公式贡献：两通道 RRF vs 三通道 RRF 对比） | module-053 已知边界 |
| WP-A5 飞轮冒烟验证 | **自己造对话**（用户指示）→ 真实 HTTP chat 获取回答（含 message_id）→ 模拟点击 👍👎（POST /ai/feedback）→ 验证 feedback 表落库 + 已评态防重复 | 用户指示（飞轮链路端到端验证） |
| WP-A6 测试 + 回归 | tests/test_nli_improve.py + 各 WP 冒烟断言；全量 pytest 700+ 全绿 | AC |

### 验收场景

```
场景 1：矛盾复测（WP-A1）
  假设 扩充样本（≥50 矛盾）+ 句级拆解 + 校准阈值重跑
  那么 输出新 kappa 三分类（对比 0.5167）；≥0.7 → 放行矛盾扫描；未达 → 如实标注 + 下一轮方向

场景 2：图谱消融（WP-A2）
  假设 python -m eval.golden_retrieval --ablate
  那么 输出 graph_only vs hybrid Hit@5 差值（+X.X），eval_runs 落库

场景 3：改写增益（WP-A3）
  假设 python -m eval.golden_query_rewrite（真实模式）
  那么 输出原始 vs 改写 Recall@K/MRR 对比，eval_runs 落库

场景 4：RRF k 扫描（WP-A4）
  假设 扫描 k=20-100
  那么 输出 Hit@5 vs k 曲线，最优 k（对比 k=60 基线），eval_runs 落库

场景 5：飞轮冒烟（WP-A5）
  假设 自己造 3-5 轮对话 → 真实 chat 回答 → 模拟点击 👍👎
  那么 feedback 表新增对应记录（rating ±1/identity/created_at），重复点击不重复落库
```

---

## 3. 技术方案

### 3.1 涉及文件

| WP | 文件 | 操作 |
|----|------|------|
| WP-A1 | `ai_service/eval/retest_nli.py`（句级拆解 + 阈值扫描）+ `ai_service/eval/contradiction_dataset.json`（扩 ≥50 矛盾）+ `build_contradiction_dataset.py`（扩充 + 指南更新） | 修改 |
| WP-A2 | `ai_service/eval/golden_retrieval.py`（--ablate 已就绪，DB 修复后直接跑） | 运行（不改） |
| WP-A3 | `ai_service/eval/golden_query_rewrite.py`（真实模式已就绪） | 运行（不改） |
| WP-A4 | `ai_service/eval/benchmark_rrf_k.py`（新：k 扫描 + 两通道归因）或扩展 golden_retrieval | 新建/修改 |
| WP-A5 | 冒烟脚本（真实 HTTP chat + POST /ai/feedback + feedback 表查询）——`ai_service/eval/flywheel_smoke.py`（新） | 新建 |
| WP-A6 | `ai_service/tests/test_nli_improve.py`（新）+ 各 WP 相关测试 | 新建 |
| 文档 | changelog / review-report / test-report + memory/ 三文件 + ADR-0010（复测结论） | 修改 |

### 3.2 关键实现约束

- **WP-A1**：句级拆解复用 `_pre_chunk` 中文句切（。！？；）；聚合规则：任一子句 contradiction → contradiction（最严）、无矛盾但有 entailment → entailment、全 neutral → neutral；内部矛盾子句两两互判；拆句失败回退整句（零回归）；阈值扫描 0.5-0.9 步长 0.05 + 低置信（max prob < 阈值 → neutral）；最优阈值配置化；eval_runs `eval_type='nli_retest_v2'`；结论写回 ADR-0010（≥0.7 放行 / 未达 + 方向）
- **WP-A2**：`--ablate` 已就绪（module-038），DB 修复后直接跑；输出 graph_only vs hybrid 对比 + delta 落 eval_runs；**注意口径**：评估路径 retriever 直调（rrf 默认已切——新数字是 rrf 三通道口径，与历史 hybrid 口径对比要注明）
- **WP-A3**：golden_query_rewrite 真实模式（DB+LLM 就绪）；输出原始 vs 改写 Recall@K/MRR + delta；eval_runs `eval_type='query_rewrite'`；LLM 失败记 skipped
- **WP-A4**：k 扫描 20-100 步长 10（或更细在拐点附近）；归因 = 两通道 RRF（FTS+向量，无图谱）vs 三通道 RRF → 图谱通道净增益；eval_runs 落库；最优 k 结论入 changelog（是否改配置 `rrf_constant_k` 由数据决定，改则测试适配）
- **WP-A5 飞轮冒烟（用户指示）**：① 自己造 3-5 条知识库问题（如 G1/JVM/Redis/Kafka）→ 真实 HTTP chat（启动 uvicorn）获取回答 + message_id ② 对每条回答模拟点击（POST /ai/feedback，rating 交替 +1/-1，至少 1 条带 comment）③ 查 feedback 表确认落库（message_id/rating/identity/created_at 正确）④ 重复提交同一 message_id → 不重复落库（前端已评态逻辑的 API 侧验证——若后端无幂等则验证前端防重复，如实记录）⑤ 冒烟数据清理策略：保留（飞轮数据就是来攒的）或清理（若污染测试数据则删）——**建议保留为飞轮种子数据**，changelog 注明
- **诚实边界**：人工构造样本方向性验证；矛盾拆解最严语义可能误杀（kappa 说话）；图谱消融/改写增益是 retriever 口径（引擎链路注明）；飞轮冒烟数据是自造的（非真实用户，但验证链路）
- **不改生产 verify_answer/检索默认行为**（A4 若改 k 默认值则测试适配注明）；全量 pytest 700+ 全绿；不改存量测试掩盖

### 3.3 降级

| 场景 | 处理 |
|------|------|
| 复测 kappa 仍 < 0.7 | 如实标注 + 下一轮方向（换模型/更多标注/两阶段） |
| 图谱消融 DB 异常 | 如实标"待环境"（预期可用，DB 已修） |
| 改写评测 LLM 限流 | 记 skipped 不中断，如实标注 |
| 飞轮冒烟 message_id 不可得 | 用真实 chat 返回的 id（Java 后端消息主键）；不可得则用流式会话 id 替代并声明 |
| 全量 pytest | 700+ 全绿保持 |

---

## 4. 依赖

- module-054（矛盾样本 + 复测脚本 + 失败模式）、module-053（DB 修复 + RRF + eval 基建）、module-047（阈值扫描方法学 + 待环境项）、module-050/052（mDeBERTa）、module-048（feedback 表 + 端点）
- 环境：DB 已修复、deepseek 可用、mDeBERTa 本地、rrf 已切默认

## 5. 已知边界

- 本模块全部是"评估侧 + 数据 + 冒烟"——不实施矛盾扫描生产代码（放行后另行模块）、不改 verify_answer/检索默认
- WP-A5 飞轮数据是自造的（非真实用户），作为链路验证与种子数据；真实飞轮仍靠用户点击积累
- 文档类（简历/弹药）不改（用户指示：等优化完成后进行）——但本模块产出的硬数字（图谱增量/改写增益）供后续简历使用
- 全量 pytest 700 全绿保持（本模块新增 +N）
