# 功能规格说明书 — Module-049: 分诊式 Query 改写（ADR-0009 实施）

> Planner | 2026-08-10

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-049 |
| 模块名称 | 分诊式策略化改写：静态分诊 + 保真预检 + 并行检索择优 + 评测闭环 |
| 版本号 | 0.49.0-module-049 |
| 优先级 | P0（ADR-0009 方案已定；改写是检索质量增强，本次落地 P0+P1 核心，P2 留待后续） |
| 预估代码量 | 改写模块 + engine 接入 + 评测脚本 + 测试，≤ 450 行 |

---

## 2. 需求

| WP | 内容 | 来源 |
|----|------|------|
| WP1 静态分诊 | 复用 `router._kb_terms` + FTS 倒排命中（毫秒级零成本）：术语命中 → 精确 query 直接检索，不走改写；术语不命中/纯泛词 → 模糊 query 走改写路径 | ADR-0009 问题 1/8，P1 改写路由 |
| WP2 改写路径 | ① LLM 改写（复用现有 rewritten_query 生成能力，独立封装）→ ② **保真预检**：改写 vs 原 query 余弦 < 0.6 → 回退原话（省一次检索）→ ③ **并行检索**：原 query + 改写 query 各检索一次（记录各自 top-1 绝对余弦）→ ④ **择优**：改写检索绝对余弦 > 原检索 → 用改写结果；否则回退原结果（防合并噪声） | ADR-0009 问题 2/4/6，P0 检索前主动重写 |
| WP3 改写评测闭环 | 新建 `eval/golden_query_rewrite.py`：复用 golden 112 题，对比"原始 query 检索 vs 改写后检索"的 Recall@K/MRR（重点看不充分题是否有增益）；eval_runs 落库 `eval_type='query_rewrite'`；`--fixture` 模式不依赖 LLM/DB | ADR-0009 问题 3，P0 评测闭环 |
| WP4 降级与回归 | LLM 改写失败/超时 → 回退原话零影响；现有反思充分性检查（check_sufficiency）保留为事后兜底，不删除；全量 pytest 全绿保持 | ADR-0009 兼容性 |

### 验收场景

```
场景 1：精确 query 不分诊
  假设 用户问 "G1垃圾收集器MixedGC流程"（FTS 术语命中）
  那么 不走改写路径，直接检索 + 反思 + 生成（链路延迟不增加）

场景 2：模糊 query 走改写 + 保真回退
  假设 用户问 "内存调优有没有什么好办法"（泛词，FTS 不命中）
  那么 ① LLM 改写 → ② 改写与原 query 余弦 < 0.6 → 直接用原 query 检索（跳过并行）

场景 3：改写择优
  假设 改写 query 检索 top-1 绝对余弦 0.62 > 原 query 检索 0.55
  那么 采用改写检索结果（含 abs_cosine 存档），生成基于择优结果

场景 4：改写失败降级
  假设 LLM 改写超时/异常
  那么 回退原 query，检索照常进行，链路不中断（与 HyDE 失败降级同哲学）

场景 5：评测闭环
  假设 python -m eval.golden_query_rewrite --fixture
  那么 输出原始 vs 改写 Recall@K/MRR 对比表 + 建议；真实模式落 eval_runs
```

---

## 3. 技术方案

### 3.1 工作包与涉及文件

| WP | 文件 | 操作 |
|----|------|------|
| WP1+2 | `ai_service/rag/query_rewrite.py`（新：分诊 + 保真预检 + 并行检索择优，无状态函数/类）+ `ai_service/rag/engine.py`（chat 链路接入，替换"反思驱动改写"前置为分诊式改写；流式链路同步接入）+ `ai_service/agent/router.py`（`_kb_terms`/FTS 命中提取为可复用公开接口或本模块内复用，不动现有 L2 逻辑） | 新建 + 修改 |
| WP2 | `ai_service/src/config.py`（rewrite 开关 + 阈值：`query_rewrite_enabled`、`rewrite_fidelity_threshold=0.6`，PW_ 前缀） | 修改 |
| WP3 | `ai_service/eval/golden_query_rewrite.py`（新）+ `eval/golden_retrieval.py`（复用 save_eval_run/load_rag_config/get_git_commit） | 新建 |
| 测试 | `ai_service/tests/test_query_rewrite.py`（新） | 新建 |
| 文档 | changelog / review-report / test-report + 记忆文件 + ADR-0009 状态更新（📋→✅ 实施中/已完成） | 修改 |

### 3.2 关键实现约束

- **WP1 分诊**：判据是"词表对得上"（检索质量信号），不是"答案对不对"（生成太贵）——复用 `router._kb_terms`（jieba → 过滤 `_FUNCTION_STOPWORDS` → 长度≥2）逐词查 FTS 倒排（search_tokens），任一命中即精确。**改动最小化**：router 内已有 `_fts_term_hit`，提取为可复用的模块级函数或 router 上公开方法，engine 调用时注入 DB session（对齐现有会话模式），不动 L2 确认语义
- **WP2 保真预检**：余弦用本地 bge-m3 嵌入（1024 维，`embeddings.py` 现有 encode），改写文本与原 query 归一化后点积；阈值 0.6 配置化。**并行检索**用 `asyncio.gather(return_exceptions=True)` 单路失败降级另一路（对齐 round 0 模式）。**择优判据**：改写检索的 top-1 abs_cosine > 原检索 top-1 abs_cosine → 用改写结果；否则回退原结果；相等/缺失 → 回退原结果（保守）。abs_cosine 缺失的文档按 0 处理
- **WP2 与既有链路关系**：HyDE 保留（round 0 首轮扩展，与改写正交）；反思 check_sufficiency 保留（事后充分性兜底，仍可触发 rewritten_query 二次补救）——分诊改写是**前置**增强，不删除任何现有环节，只把"改写时机"提前
- **WP3 评测**：每题跑 ①原 query 检索 ②改写 query 检索，对比 Recall@K（K=5）/MRR；**不改变生产行为**（评测只度量，不接线）；LLM 改写失败/超时 → 记 skipped 不中断；`--fixture` 用启发式（分词术语存在即"命中"）演示管线
- **降级哲学**：改写系统任何一环失败 = 回退原 query，行为与现状完全一致（零回归）

### 3.3 降级

| 场景 | 处理 |
|------|------|
| LLM 改写失败/超时 | 回退原 query，链路照常（与 HyDE 降级一致） |
| 保真预检失败/余弦不可得 | 跳过预检直接并行检索（或保守回退，取更简单者：直接并行，让择优兜底） |
| 并行检索单路失败 | 用成功路结果；双路失败 → 空结果走现有无结果降级 |
| 分诊 DB 不可用 | 分诊失败 → 默认"模糊"走改写路径（保守，宁多检不漏检）；分诊本身有 FTS 查询超时防护 |
| 评测 DB 不可用 | --fixture 模式演示，如实标注"待环境" |

---

## 4. 依赖

- ADR-0009（方案）、module-035 绝对余弦口径、module-043/045 retriever abs_cosine 透传、module-044/048 反思充分性链、module-020 jieba FTS
- `router._kb_terms` 复用（不复制实现）
- 评测基建复用 `eval/golden_retrieval.py` 的落库函数

## 5. 已知边界

- 改写质量依赖 LLM（deepseek-v4-flash）；保真预检只拦"跑偏"不保证"更优"——择优失败即回退，损失上限=一次 LLM 调用 + 一次并行检索
- 多候选 RRF 融合（P0 #2）、对话上下文化（P1 #5）、子查询分解（P2 #6）、专用重写器（P2 #7）本次不做，留待后续模块（评测闭环落地后按数据决定）
- 本模块不改 golden 集、不改检索核心（retriever/reranker），只加"改写时机"前置层
- 全量 pytest 533 全绿保持
