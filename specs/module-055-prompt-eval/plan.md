# 功能规格说明书 — Module-055: 提示词评估优化（ADR-0011）+ E2E 待办修复

> Planner | 2026-08-12

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-055 |
| 模块名称 | Prompt 变体测试（ADR-0011 第一步）+ E2E 发现的 3 问题修复 + rrf 切默认 |
| 版本号 | 0.55.0-module-055 |
| 优先级 | P0（prompt 评估是"判断提示词好坏"的方法论落地；3 个 E2E 问题影响真实链路质量） |
| 预估代码量 | 变体测试脚本 + 3 处修复 + rrf 默认切换 + 测试，≤ 500 行 |

---

## 2. 需求

| WP | 内容 | 来源 |
|----|------|------|
| WP-1 prompt 变体测试 | 写 `eval/prompt_variants.py`：定义 N 个 prompt 变体 → 逐个跑 golden 评测 → 对比表（消融实验自动化）；`reflector.py` prompt 常量改可注入参数（`check_sufficiency(prompt=...)`）——ADR-0011 第一步（半天） | ADR-0011 落地路径第一步 |
| WP-2 E2E 问题 ①intent 漏检 | 诊断并修复："G1垃圾收集器的核心创新是什么？"被判 casual_chat（E2E 实测返回闲聊）——查 LLM 分类 confidence 与 L2/L3/L4 拦截链为何没触发 | module-054 E2E 发现 |
| WP-3 E2E 问题 ②HHEM 验证超时 | 诊断并修复：非流式 chat verified_claims=0（3×5=15 对 ≈12s 贴近 15s 超时）——缩交叉对数/提高预算/分层，取数据支撑的方案 | module-054 E2E 发现 |
| WP-4 E2E 问题 ③RRF abs_cosine 存档 | 诊断并修复：rrf 模式流式 top_abs_cosine=0.0 + suspected_misclassify=true 误触发（L3 反证失效）——融合路径 abs_cosine 未透传 | module-054 E2E 发现 |
| WP-5 rrf 切默认 | 引擎 rrf HTTP E2E 已通过（module-054 实测 chat/stream 全链路正常）→ `retrieval_fusion_mode` 默认 hybrid→rrf；保留 hybrid 回退开关 | module-054 决策前置已清 |
| WP-6 测试 + 回归 | tests/test_prompt_variants.py + 3 个修复的回归测试；全量 pytest 667+ 全绿 | AC |

### 验收场景

```
场景 1：变体测试
  假设 python -m eval.prompt_variants --variant v1,v2,v3
  那么 逐个跑 golden 评测输出对比表（Accuracy/混淆矩阵/kappa），可落 eval_runs

场景 2：intent 漏检修复
  假设 问 "G1垃圾收集器的核心创新是什么？"
  那么 走 knowledge 检索（不再闲聊）；修复有测试覆盖该 query

场景 3：HHEM 验证不超时
  假设 非流式 chat 正常回答（3-5 句答案）
  那么 verified_claims 非空（supported/inferred/unsupported 正常返回），不再超时降级为空

场景 4：RRF abs_cosine 透传
  假设 rrf 模式流式 chat
  那么 retrieval step 的 top_abs_cosine 为真实值（非恒 0.0），suspected_misclassify 不再误触发

场景 5：rrf 默认
  假设 无 PW_RETRIEVAL_FUSION_MODE 配置
  那么 默认走 rrf（保留 hybrid 开关可回退）；全量 pytest 全绿
```

---

## 3. 技术方案

### 3.1 涉及文件

| WP | 文件 | 操作 |
|----|------|------|
| WP-1 | `ai_service/eval/prompt_variants.py`（新）+ `ai_service/agent/reflector.py`（prompt 可注入参数，默认值不变零回归） | 新建 + 修改 |
| WP-2 | `ai_service/agent/router.py`（诊断后按根因修）+ 相关测试 | 修改 |
| WP-3 | `ai_service/agent/reflector.py` 或 `rag/retrieval/factcheck_judge.py`（超时/对数方案） | 修改 |
| WP-4 | `ai_service/rag/retrieval/retriever.py` 或 `rag/engine.py`（rrf 融合路径 abs_cosine 透传） | 修改 |
| WP-5 | `ai_service/src/config.py`（retrieval_fusion_mode 默认 rrf） | 修改 |
| WP-6 | `ai_service/tests/test_prompt_variants.py`（新）+ 各修复回归测试 | 新建 |
| 文档 | changelog / review-report / test-report + memory/ 三文件 + ADR-0011 状态更新 | 修改 |

### 3.2 关键实现约束

- **WP-1 变体测试**：变体定义 = 同任务不同 prompt 文本（如 check_sufficiency 的 CoT 版本/简洁版/few-shot 版/自洽版）；复用 golden_sufficiency/golden_intent 评测（每变体跑全量集）；对比表含 Accuracy/kappa/耗时；可 `--no-save` 或落 eval_runs（eval_type='prompt_variant'）；**不改生产 prompt 默认值**（只测试，不替换）
- **WP-2 intent 漏检**：先诊断（查该 query 的 classify 输出 confidence/reason + L2 是否触发 + L4 分类器状态）再定修法——可能根因：LLM 高置信误判 casual_chat（L2 只覆盖低置信，需看是否要扩展触发条件）或 L4 分类器误判；**修法要有测试覆盖该 query 类**（含 "G1"/"JVM" 等专有术语 + 疑问句的边界样本）
- **WP-3 HHEM 超时**：诊断 verified_claims=0 的确切原因（HHEM 15 对超时 or 降级链问题）；方案候选：① 限制交叉对数（如 max 10 对抽样）② 提高 verify 超时预算（15s→20s 需评估对延迟影响）③ 分层（先便宜信号）——**取数据支撑的方案**（如实测各方案耗时），changelog 记录取舍
- **WP-4 RRF abs_cosine**：诊断 rrf 融合路径为何 abs_cosine 丢失（module-053 声称"融合前存档红线保持"，实测 0.0——查 `_execute_fusion` 返回的 doc 是否带 abs_cosine 字段 + engine 读取路径）；修复后 rrf 模式 L3 反证恢复正常（top_abs_cosine 真实值 + suspected_misclassify 不再误触发）
- **WP-5 rrf 默认**：config 默认 hybrid→rrf；**存量测试适配**——module-053 已知 rrf 作默认改引擎降级语义致 2 项存量降级用例失败（当时红线不改存量测试所以没切）；module-054 已实现方案 A/B 修复（向量化失败=FTS+图谱照常、引擎补图兜底）——**现在这 2 项测试应能通过或需按新语义更新断言**（模块-054 修复后语义已对齐，先跑再看；若测试断言的是旧降级行为则按新语义更新测试并注明理由——这是行为升级不是掩盖）
- **诚实边界**：WP-2/3/4 先诊断后修（根因不确定时如实报告诊断结果）；变体测试只度量不替换生产 prompt
- **不改前端**；全量 pytest 667+ 全绿

### 3.3 降级

| 场景 | 处理 |
|------|------|
| WP-2 根因复杂（如 L4 分类器问题） | 修一层兜底（如规则表补 G1 类术语）+ 记录深层待办 |
| WP-3 提高预算影响延迟 | 用实测数据对比（15s vs 20s 实际耗时分布）决策，changelog 记录 |
| WP-5 rrf 默认后存量测试失败 | 先核对失败是否因行为升级（模块-054 已修复降级）；是则按新语义更新测试 + 注明；否（回归）则回退默认 hybrid 排查 |
| 变体测试模型调用成本 | 每变体跑 100 条 × N 变体 = N×LLM 调用；可 --limit 或 --no-save 控制 |

---

## 4. 依赖

- ADR-0011（方法论 + 三步路径）、module-054（E2E 发现 3 问题 + 方案 A/B 降级修复 + 引擎 rrf E2E 通过）
- 复用：golden 各集、eval_runs + --compare、threshold_scan 思路（变体扫描）、降级链 LLM

## 5. 已知边界

- WP-1 只做变体测试基建（ADR-0011 第一步），OPRO 循环/DSPy 留后续（数据/需求决定）
- WP-2/3/4 根因未定前先诊断；诊断结果如实入 changelog
- 文档类（简历/弹药）不改（用户指示：等优化完成后进行）
- 全量 pytest 667 全绿保持（本模块新增 +N；rrf 默认切换导致的存量断言更新需注明理由）
