# Module-062 任务简报：记忆进化 2（类型化衰减 + 冷记忆降权，ADR-0007 P2+P3）

> 自包含执行简报。接手方不需要额外对话上下文，按步骤执行即可。所有"已知事实"均已确认（代码已读），无需重新调研。
> 范围：**P2 类型化衰减（A-MAC）+ P3 冷记忆降权（Memory Decay）**。P4 反馈闭环留后续模块。

## 一、任务背景

**项目**：Agentic RAG 技术文档知识库（`.claude/worktrees/m8-knowledge-panel/ai_service`）。

**要解决的问题（ADR-0007 P2/P3，代码实测）**：

| 软肋 | 代码证据 | 后果 |
|---|---|---|
| 衰减参数一刀切 | `_evolve_recall`（memory.py:662）：所有短期记忆同一半衰期 3 天（`memory_short_half_life=3`）+ 提及加权 α=0.2 + 升级 ≥2 次/7 天（config.py:117-121） | 偏好类（"喜欢 Python"）衰减太快、事件类（"下周去北京"）又太慢——没有按记忆类型区分新鲜度 |
| 长期层无降权/淘汰 | `recall`（memory.py:564）：长期层检索无时间降权，永久等权重 | 很久没用的旧长期记忆与刚记的同等权重，可能盖过近期偏好 |
| 提取无类型 | `extract_facts`（memory_extractor.py:99）：LLM 只输出 {content, importance} | 无法按类型做差异化衰减/升级 |

**目标**：① P2 记忆按类型（偏好/事实/事件）差异化衰减——A-MAC 参考：偏好慢衰减、事件快衰减；② P3 长期层冷记忆降权——久未召回的旧记忆检索时降权（×0.3-1.0）不删除；③ 类型判断评测闭环（LLM 判类型 P/R，数据说话不预设成功）。

## 二、已知事实（勿重新调查）

### 2.1 记忆代码现状（module-046 短期进化，已读）

- **`_evolve_recall`**（memory.py:662-680）：短期召回后——① 硬上限 `memory_short_max_days=30`（超限不参与召回）② 平滑衰减 `decay=0.5**(age_days/half_life)`（半衰期 `memory_short_half_life=3` 天）③ 提及加权 `最终分=语义分×decay×(1+α×mention_count)`（`memory_mention_boost_alpha=0.2`）④ 提及刷新（仅过上限项，fire-and-forget）⑤ 升级 `_promote_memory`（mention_count≥`memory_promote_mentions=2` 且 7 天内）⑥ 按新 score 重排
- **`recall`**（memory.py:564）：长期层召回——hybrid_retriever（`_layer_pattern` 精确匹配 'memory:<identity>:'）+ 动态 K（绝对余弦口径），**无时间降权**（长期层永久等权重）
- **`recall_short`**（memory.py:612）：短期层召回——同检索 + `_evolve_recall` 进化
- **`extract_facts`**（memory_extractor.py:99）：LLM 一次调用 → `{"facts": [{content, importance}]}`，过滤 importance≥`memory_importance_threshold`；**无 type 字段**
- **`save`**（memory.py:228）：记忆写入入口
- **配置**（config.py:104-121）：`memory_short_half_life=3`、`memory_short_max_days=30`、`memory_mention_boost_alpha=0.2`、`memory_promote_mentions=2`、`memory_promote_window_days=7`、`memory_dedup_threshold=0.85`

### 2.2 相关既有机制

- **module-061 superseded**：documents 已加 `superseded`/`updated_at` 列（init_db 幂等 ALTER + migrate_module061.py 先例）——本模块再加列沿用同模式
- **迁移先例**：`scripts/migrate_module061.py`（幂等 ALTER documents 补列）；本地库需跑迁移脚本先决
- **评测基建**：`eval/golden_memory.py`（记忆提取评测，28 条标注集 + extract_facts P/R/F1 + eval_runs eval_type='memory_extraction'）——类型判断评测对齐该模式
- **降级哲学**：LLM 失败/超时 → 空结果 fail-open；存量行缺新字段 → 默认值兜底零回归（module-046/061 同款）

### 2.3 测试基线

- 后端全量 **825 passed / 0 failed**（module-061 + Review 守卫后）；前端与后端并存但本模块纯后端
- conftest autouse 钉住测试环境开关（对齐 module-056/058/060/061 成熟模式）

## 三、任务步骤（按序，每步有通过标准）

### WP1 类型判断双方案对比（分类模型 vs LLM，谁好谁上）

> **用户决策（2026-08-13）**：类型判断不只用 LLM——用**分类模型**（bge-m3 + 逻辑回归，复用 module-056 intent 分类器基建）与 LLM **实测对比，谁好谁上**，数据说话。复用已部署模型：bge-m3（嵌入）、mDeBERTa NLI（矛盾检测——module-061 已完成但评测 Recall 0.5<0.8 未达标默认关，如实说明，本模块不重复做矛盾检测）。

- **方案 A 分类模型**：bge-m3 冻结特征 + 逻辑回归头（**复用 module-056 intent_classifier.py / train_intent_classifier.py 基建**，零新模型）——`eval/build_memory_type_dataset.py`（新）生成人造记忆类型标注集（如 120 条：preference 40/fact 40/event 40，与 LLM 评测集零重叠防泄漏）+ `scripts/train_memory_type_clf.py`（新，复用 train_intent_classifier 模式）→ 落盘 models/memory_type_clf.joblib
- **方案 B LLM**：`extract_facts`（memory_extractor.py）`_EXTRACT_PROMPT` 加 type few-shot（preference=喜好/习惯、fact=客观陈述、event=带时间临时事件），输出 {"content", "importance", "type"}；无 type/非法 → 默认 fact
- **对比评测**：`eval/memory_type_dataset.py`（新）——记忆类型评测集（30 条：preference 10/fact 10/event 10，与训练集零重叠）+ 分类模型与 LLM **同集对比**（Accuracy/P/R/F1，eval_runs eval_type='memory_type'，含 model 字段区分 clf/llm）
- **启用决策**：达标线 type Accuracy≥0.8（可微调）——**谁达标谁上**；双方案都达标取更高分者；都不达标 → 类型化回退（type 按默认，不预设成功）。生产注入用 winner（`memory_type_mode` 配置：clf/llm/none）
- **通过标准**：标注集 + 训练 + 对比表（分类模型 vs LLM 各数字）如实记录；达标/回退判定明确

### WP2 P2 类型化衰减

- **documents 加 `type` 列**（init_db 幂等 ALTER + migrate_module062.py 本地先决）：VARCHAR(16) NOT NULL DEFAULT 'fact'
- **`_evolve_recall` 按 type 差异化半衰期**：decay = 0.5**(age_days/type_half_life)，type_half_life 参考（config 可调）：
  - `preference`：30 天（慢衰减——偏好长期有效）
  - `fact`：10 天（中——客观事实较稳定）
  - `event`：1 天（快——临时事件迅速过期）
  - 存量行无 type（默认 'fact'）→ 用 fact 半衰期；`memory_short_half_life` 保留为 fact 默认/兼容
- **升级阈值按 type 可选**：优先只做衰减率区分（升级逻辑不动，保持 ≥2/7 天），如实声明"升级阈值未按类型区分"
- **通过标准**：类型化半衰期生效（单测：同 age 不同 type 衰减系数不同）；存量无 type → fact 行为与现状一致（零回归）；开关 `PW_MEMORY_TYPE_DECAY` 默认 true（false 回退全局 half_life）

### WP3 P3 冷记忆降权（长期层）

- **documents 加 `last_recalled_at` 列**（同批 ALTER）
- **`recall`（长期层）降权**：检索后对命中记忆按距上次召回时间加权——`cold_factor = 1.0`（最近召回）/ 渐降；久未召回（如 >30 天）→ ×0.3（参考 ADR Memory Decay ×0.3-1.5，温和不删）；分数 = 语义分 × cold_factor
- **召回命中刷新 `last_recalled_at`**（fire-and-forget，不阻塞；对齐提及刷新模式）
- 短期层 `recall_short` 是否也降权？——P3 主要针对长期层（短期已有衰减）；长期层降权即可，短期保持现状（如实声明口径）
- **通过标准**：长期层久未召回降权（单测：不同 last_recalled_at 系数不同）；存量无 last_recalled_at → 不降权（×1.0，零回归）；开关 `PW_MEMORY_COLD_DECAY` 默认 true（false 回退）

### WP4 矛盾检测分类器训练启用（用户决策：自建 100+ 案例训练，Precision 达标启用）

> **用户决策（2026-08-13）**：自建 100+ 记忆矛盾案例训练矛盾检测；测试达标情况——**Precision 高（≥0.8）就启用**（module-061 的 `PW_MEMORY_CONFLICT` 打开），**Recall 作为后续提升项不阻塞启用**（保守方向：宁可漏检也不错标）。module-061 已用 mDeBERTa NLI 实现矛盾检测（Precision 1.0 / Recall 0.5 未达原双门槛默认关）——本 WP 训练分类器对比后启用。

- **数据**：`eval/build_memory_conflict_train.py`（新）——自建 **100+ 记忆矛盾案例**（改造口/迁移/过时/升级冲突/正例中性，对齐 module-061 memory_conflict_dataset 30 条口径扩展到 100+；与评测集零重叠防泄漏）
- **训练**：矛盾检测分类器——bge-m3 嵌入**新旧两条记忆**（分别嵌入 → 拼接/差值特征）→ 逻辑回归二分类"矛盾/非矛盾"（**复用 module-045 sufficiency_clf / module-056 intent_classifier 基建**，零新模型依赖）→ 落盘 `models/memory_conflict_clf.joblib`
- **对比**：训练的 clf vs module-061 mDeBERTa NLI（同评测集 Accuracy/P/R/F1）——**Precision ≥ 0.8 者启用**（clf 达标用 clf 注入，mDeBERTa 达标用 mDeBERTa，双达标取 Precision 高者）
- **启用**：`PW_MEMORY_CONFLICT` 默认 false，达标后显式 true（配置 + 测试验证 `_merge_duplicate` 矛盾分流生效）；不达标保持关，如实标注（Recall 后续提升方向：扩充样本/调阈值/更强中文 NLI，入 changelog backlog）
- **通过标准**：训练集 100+ 落盘 + 训练 + clf vs mDeBERTa 对比表 + 启用判定明确（Precision 达标者开）

### WP5 测试 + 文档 + 记忆

- `tests/test_memory_evolution2.py`（新）：类型判断双方案（extract_facts type / clf 推理）/ 类型化半衰期（不同 type 衰减系数）/ 开关回退 / 冷记忆降权（系数/刷新/零回归）/ 矛盾检测 clf 训练推理与启用 / DDL 幂等 / 评测基线一致性
- conftest autouse 钉住新开关（对齐既有模式）；存量 test_memory 测试零改动（默认值兜底）
- 文档：changelog/review-report/test-report + **ADR-0007 状态行更新（P2+P3 已实施）** + memory 三件套 + CONTEXT 只增
- **通过标准**：全量 pytest 825+新增全绿；记忆三文件硬性约束满足

## 四、纪律项（违反 = 返工）

1. **存量零回归**：存量记忆无 type/last_recalled_at → 默认值兜底（type='fact' 半衰期=现状、无 last_recalled_at 不降权）；存量 test_memory 测试零改动（除非验收许可，须如实标注）
2. **新列幂等 ALTER + 本地迁移先决**：init_db 幂等 + migrate_module062.py 执行（module-061 先例）
3. **评测驱动**：类型判断 Accuracy<0.8 → 类型化衰减回退（type 按 fact 处理，不预设成功）；基线数字如实记录
4. **降级 fail-open**：LLM 类型判断失败 → 默认 fact；降权计算异常 → ×1.0 不降权，不影响召回主链路
5. **诚实**：升级阈值未按类型区分、P3 只做长期层等口径如实声明
6. **不破坏现状**：短期层衰减公式结构不变（只按 type 换 half_life）；长期层 recall 接口/返回结构不变（只加权）

## 五、交付物

1. WP1 记忆类型标注集 + LLM 判类型 baseline 数字
2. WP2 类型化衰减（type 列 + _evolve_recall 按类型半衰期 + 开关）
3. WP3 冷记忆降权（last_recalled_at 列 + recall 加权 + 刷新 + 开关）
4. WP4 测试（825+N 全绿）+ 文档 + memory 三件套 + ADR-0007 状态更新
5. 面试口径更新点（记忆类型化衰减 A-MAC 参考 + 冷记忆降权不删旧）
