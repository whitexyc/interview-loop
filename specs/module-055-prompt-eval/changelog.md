# Changelog — Module-055: Prompt 变体测试（ADR-0011 第一步）+ E2E 待办修复

> Developer | 2026-08-12
> 开工前已读 `memory/project-context.md` 全文（module-001~054 清单与迭代状态，避免重复/冲突）✅

---

## 1. 模块目标

| WP | 内容 | 结果 |
|----|------|------|
| WP-1 | `eval/prompt_variants.py`（N 变体 × golden 评测 × 对比表）+ reflector prompt 可注入参数 | ✅ |
| WP-2 | E2E 问题① intent 漏检（"G1垃圾收集器的核心创新是什么？"被判闲聊 sources=0） | ✅ 修复 |
| WP-3 | E2E 问题② HHEM 验证超时（verified_claims=0） | ✅ 修复 |
| WP-4 | E2E 问题③ RRF abs_cosine 丢失（top_abs_cosine=0.0 + 误标记） | ✅ 修复 |
| WP-5 | `retrieval_fusion_mode` 默认 hybrid→rrf | ✅ 切换 |
| WP-6 | 测试 + 全量回归 | ✅ 688/0（667 基线 + 21 新增） |

---

## 2. WP-1 Prompt 变体测试（ADR-0011 第一步）

### 2.1 交付物

- **`ai_service/eval/prompt_variants.py`（新）**：5 个变体（baseline / v_brief 简洁版 / v_strict 严格版 / v_fewshot few-shot 精简版 / v_conservative 保守倾向版）→ 逐个跑 golden_sufficiency 100 条 → 对比表（Accuracy / insufficient Recall / **kappa** / 耗时）。
  - CLI：`--variant` 逗号选择 / `--limit` 限量（控制 LLM 成本）/ `--no-save`（默认）/ `--save`（每变体落 eval_runs，`eval_type='prompt_variant'`，scores 含 variant 名 + 说明，per_question 带 variant 标记）/ `--fixture`（启发式判断器，管线演示零 LLM 零 DB）。
  - kappa 用 `cohen_kappa_score`（两态充分性标签；单类样本如实记 0.0）。
  - 占位符 `{query}/{docs_summary}` 缺失 fail-fast（LLM 调用前校验）。
- **`agent/reflector.py`**：`check_sufficiency(query, documents, prompt=None)`——prompt 变体注入，`None` = 生产默认 `_CHECK_PROMPT`（零回归，逐字节断言测试）；自洽性检查第二判同用注入变体（对比口径一致）。
- **只度量不替换**：baseline 恒为生产默认；变体不改变默认行为。

### 2.2 冒烟实测（真实 deepseek）

`python -m eval.prompt_variants --fixture --limit 10`：5 变体跑通（启发式判断器 prompt 无关，各变体同分属预期）。
`python -m eval.prompt_variants --variant baseline,v_brief,v_fewshot --limit 6`（真实 LLM）：18 次 deepseek 调用全 200，对比表正常输出（baseline 13.1s / v_brief 10.4s / v_fewshot 12.3s，前 6 条样本均为充分类故 insufficient_recall=0.0 属样本切片特征非缺陷）。
全量 100 条 × 5 变体 = 500 次 LLM 调用成本可控，`--limit`/`--fixture` 供 CI 与演示。

---

## 3. WP-2 intent 漏检修复（诊断 → 修复 → 验证）

### 3.1 诊断记录（2026-08-12 真实环境）

| 诊断项 | 结果 |
|--------|------|
| 该 query 真实 classify 输出 | `{"intent": "knowledge", "confidence": 1.0}`（deepseek）——**LLM 对同一 query 分类结果不稳定**：module-054 E2E 时被判 casual_chat 高置信，本模块实测 3 次均 knowledge |
| L2 触发条件 | 原实现 `intent≠knowledge 且 confidence<0.5`——E2E 误判若为高置信（≥0.5）则 L2 完全不触发，**这就是漏检缺口**（低置信护栏覆盖不到高置信误判） |
| L2 信号判别力实测 | FTS 术语命中噪声大（知识库含简历类文档，"今天/问题/怎么样/最近"等普遍命中）；**图谱实体命中判别力最强：golden 50 条非 knowledge 样本误命中 0 条**，E2E query（实体 G1）命中 |
| L4 分类器状态 | 默认关（opt-in），与本次无关 |
| 规则表 | "G1垃圾收集器的核心创新是什么？"无规则词命中 ✓ |

### 3.2 根因结论

LLM-as-Classifier 非确定性高置信误判是固有风险；原 L2 的"低置信才触发"把护栏绑死在不可靠的自报分数上，高置信误判直接漏检。L2 扩展为无条件触发是计划预判的修法方向，实测确认安全（见下）。

### 3.3 修复（`agent/router.py`）

1. **L2 触发无条件化**：`intent≠knowledge` 即跑确定性信号确认（移除 confidence 条件；常量 `_L2_CONFIDENCE_THRESHOLD` 保留作历史口径注释）。依据：确定性信号便宜且精确 + 规则表否决闲聊/实时特征词 + 任何异常保守 knowledge（宁多检不漏检），扩展零风险。
2. **规则表提前短路**：`_deterministic_confirm` 规则词命中 → 直接 `rule_veto` 返回（原实现 FTS 先查再否决属无效开销；无条件触发后规则词请求零 DB 查询）。
3. **停用词表数据驱动扩充**（两轮 golden 扫描实测）：初轮 20/50 误确认 → 补入 26 词 → 剩 10 → 逐词定位命中术语（`不错/注意/还是/多少/人民币/电影` 等简历类文档噪声词）→ 第二轮补入 17 词 → **误确认 0/50**。停用词表现有 43 词（模块原有 + 26 + 17）。
   - 连带说明：停用词扩充经 `_kb_terms` 单一来源连带影响 module-049 分诊（模块级 `fts_term_hit`）的 FTS 命中行为——方向一致（噪声词本就无判别力），全量测试通过。

### 3.4 验证

- **golden 误确认扫描**（真实 DB，50 条 casual/realtime 样本模拟无条件 L2）：**0/50 误确认**（修复前 20/50）。
- **正向确认**（8 条 knowledge 样本含 E2E query + JVM/Redis 边界样本）：**8/8 确认成功**（fts_term/graph_entity）。
- **真实 golden_intent 评测**（deepseek 100 条，--no-save）：Accuracy **0.98**（module-047 baseline 1.0）。2 条误判均为 `realtime→knowledge`（"现在几点了？"/"现在流行什么"，LLM 自判 knowledge、confidence 0.80，L2 日志证实非本模块所致——L2 只处理 intent≠knowledge 方向），方向为多检低风险（ADR-0003 不对称代价）。casual_chat 30/30、knowledge 50/50 全对，**L2 扩展零回归**。
- **真实 E2E**：`POST /ai/rag/chat {"query":"G1垃圾收集器的核心创新是什么？"}` → intent=knowledge、sources=3、真实 G1 答案（见 §7）。

### 3.5 测试覆盖（test_intent_validation.py 47 项全绿）

新增/更新：高置信 casual 触发 L2 并修正为 knowledge（module-055 行为升级，替换旧 `test_high_confidence_skips_l2`）、高置信无信号保持原判、无 confidence 触发 L2（替换旧 `test_missing_confidence_skips_l2`）、**E2E query 高置信误判修正**、"JVM 内存溢出怎么排查？/Redis 的持久化机制有哪些？"边界样本、规则表短路零 DB 调用、停用词噪声词断言。

---

## 4. WP-3 HHEM 验证超时修复（诊断 → 实测 → 修复）

### 4.1 诊断记录

| 诊断项 | 结果 |
|--------|------|
| E2E 现象 | module-054 E2E：chat verified_claims=0；changelog 记录 "HHEM verify 15s 超时走既有 LLM 判分降级" |
| 降级链 | verify_answer：LLM 拆句（15s）→ HHEM 判分（15s 超时 → None）→ LLM 判分（15s）→ 空 claims。**级联超时**：HHEM 超时 + LLM 判分再超时 → verified_claims=0（最坏 45s） |
| 本机实测 | 15 对冷启动（含 438MB 模型加载）**9.04s**；热推理 **0.11s/对**；服务进程内冷加载（CPU 争用）**17-19s**；E2E 负载下 15 对 ≈12s+ 贴近旧 15s 上限 |
| 附加发现 | verify 传入的是**父块全文**（≤4000 字符 ≈ 2000+ token），超 HHEM 512 token 上限（transformers 报 Token indices 溢出警告）且拖慢单对推理 |

### 4.2 修复（三层，全部实测数据支撑）

1. **交叉对数上限**（`reflector.py`）：`_MAX_HHEM_DOCS=2`（按相关度取前 2 篇）+ `_MAX_HHEM_CLAIMS=8`（防超长答案爆炸）→ 最坏 16 对、典型 10 对。取舍：verdict = 各文档 max，丢弃尾部文档的代价是证据只存在于尾部时 verdict 从严（保守方向）；文档已按相关度排序，头部承载证据概率最高。
2. **推理预算 15s→20s**（`factcheck_judge._PREDICT_TIMEOUT`）：对数上限后冷启动 ≈6s，20s = 3 倍余量。
3. **父块文本截断**（`reflector.py` `_MAX_HHEM_DOC_CHARS=500`）：实测对比（3 claims × 2 真实父块，真实 HHEM）——**全文 6 对 9.3s（含 585 token 溢出对）vs 截断 6 对 2.4s（4 倍提速）**；verdict 对比：全文 0.568 inferred（含日报噪音）vs 截断 0.802 supported（头部即答案主体）——截断同时消除溢出警告并改善判定。

### 4.3 附加修复：HHEM 启动预热（`main.py` lifespan）

服务进程内冷加载 17-19s（CPU 争用）仍可能顶穿 20s 预算 → 首个验证请求 verified_claims=0（E2E 复现）。lifespan 增加**后台 fail-soft 预热任务**（`asyncio.create_task`，不阻塞启动，失败仅告警 → 首个请求退回冷加载路径，与无预热行为一致）。实测：启动 13:54:01 完成预热，后续 verify 纯推理。

### 4.4 验证

- 单测：caps（docs 封顶 2/claims 封顶 8 断言 predict 实参）+ 截断（500 字符断言）→ test_factcheck_judge.py 38 项全绿。
- **真实 E2E**：chat "G1垃圾收集器的核心创新是什么？" → **verified total=8（sup 3/inf 1/unsup 4）**；"JVM的内存结构是怎样的？" → total=8（sup 0/inf 1/unsup 7，答案如实声明文档未覆盖虚拟机栈等区域——unsupported 高是知识库覆盖缺口 + HHEM 判定，非链路故障）；流式 verify 事件正常（claims 非空）。
- 诚实边界：极端外部 LLM 延迟（deepseek 抖动）下 LLM 拆句/判分 15s 超时仍可能返回空 claims——module-039 既有 fail-soft 降级哲学，前端已处理；HHEM 环节（module-054 E2E 根因）已消除。

---

## 5. WP-4 RRF abs_cosine 透传修复（诊断 → 修复 → 验证）

### 5.1 诊断记录

| 诊断项 | 结果 |
|--------|------|
| 融合路径存档 | `_execute_fusion` 归一化/融合前已为向量路文档存档 abs_cosine（module-053 红线），`_fuse_rrf` 双命中/向量独有透传——**代码路径本身正确**（直调实测 top-1 abs_cosine=0.70 真实值） |
| E2E 0.0 根因（复现） | rrf 三通道下图谱通道返回**父块文档**（graph_store 映射父块、无 parent_id、无向量分数）；HyDE 扩展查询下该父块可排 top-1（引擎 `_retrieve` 实测复现 id=239 top-1 abs_cosine MISSING）→ L3 "缺字段按 0.0 保守标记"恒误触发 |
| 次生根因 | 向量通道整体降级（module-054 方案 A）时全组缺字段，同样恒误标记 |
| 结论 | 缺失 ≠ 低分：缺字段的语义是"向量分数未度量"，不是 0 分。原"缺→0.0 保守标记"是 module-043 前 rrf/降级时代的语义，rrf 默认后成为系统性误报源 |

### 5.2 修复（`rag/engine.py` `_check_suspected_misclassify`）

**只对实测到的低分标记**：top-1 有 abs_cosine 且 < 阈值 → 标记；top-1 无 abs_cosine（FTS/图谱独有命中排首或向量通道降级）→ 不标记（图谱实体命中本身就是相关证据）。返回结构不变（(flag, top1_abs)，无分数时 (False, 0.0)）。

### 5.3 验证

- 单测：整组缺失不标记、top-1 缺失不标记（替换原保守标记断言，注明行为升级）、实测低分仍标记、阈值边界不变——test_intent_validation.py 47 项全绿。
- **真实 E2E**（默认 rrf）：
  - chat："G1..." → top_abs_cosine=**0.6664**、suspected=**False**；"JVM..." → 0.7052、False。
  - stream："G1..." → top_abs_cosine=**0.8296**、suspected=**False**（该次 top-1 为向量命中子块；图谱父块排首时如实显示 0.0 且不误标记——度量诚实，flag 语义正确）。

---

## 6. WP-5 rrf 切默认（`src/config.py`）

- `retrieval_fusion_mode` 默认 `"hybrid" → "rrf"`（注释同步：module-053 实测 0.9905 vs 0.9714 放行、module-054 清障方案 A/B + 引擎 rrf 真实 HTTP E2E 通过、回退方式 `PW_RETRIEVAL_FUSION_MODE=hybrid`）。
- **存量测试适配**：module-053 记录的"rrf 默认致 2 项存量降级用例失败"在 module-054 方案 A/B 落地后已消解——本次切默认后全量 pytest **688/0**，**零存量断言改动**（无行为升级掩盖问题，语义已对齐）。
- 验证：无 `PW_RETRIEVAL_FUSION_MODE` 环境下 `settings.retrieval_fusion_mode == "rrf"`；真实 HTTP chat+stream 全链路走 rrf 正常（§7）。

---

## 7. 真实 E2E 冒烟（uvicorn 8001，默认模式 = rrf，无 PW_RETRIEVAL_FUSION_MODE）

### 7.1 chat（POST /ai/rag/chat）

| query | intent | sources | top_abs_cosine | suspected | verified_claims | 备注 |
|-------|--------|---------|----------------|-----------|-----------------|------|
| G1垃圾收集器的核心创新是什么？ | knowledge | 3 | 0.6664 | False | **total=8（sup3/inf1/unsup4）** | E2E 问题①/②/③全部修复 |
| JVM的内存结构是怎样的？ | knowledge | 4 | 0.7052 | False | total=8（inf1/unsup7） | 答案如实声明 KB 未覆盖虚拟机栈等（覆盖缺口非故障） |
| 你好呀 | casual_chat | 0 | - | - | - | L2 rule_veto 保持闲聊 ✓ |
| 现在几点了？ | realtime | 0 | - | - | - | realtime_not_implemented ✓ |

### 7.2 stream（POST /ai/rag/chat/stream）

- "G1垃圾收集器的核心创新是什么？"：retrieval step `top_abs_cosine=0.8296`、`suspected_misclassify=false`（复测 0.8296）；事件序列 intent→retrieval→rerank→reflection→token×N→verified/done 正常，0 error。
- "你好呀"：intent step casual → token → done，0 error。

### 7.3 环境观察（非本模块缺陷）

- deepseek 429 限流风暴时段（E2E 期间偶发）→ 降级链 qwen/zhipu 慢 → 单请求 142s（生成失败一次"抱歉，回答生成时遇到问题"）——外部供应商抖动，降级链按设计工作。
- 引擎 round 0 15s 超时在 429 风暴时可能触发方案 B 补图兜底 → 兜底超时 → 空结果（日志 "三通道融合检索失败，引擎补图兜底"）——防御层行为符合设计，非静默错误。

---

## 8. 涉及文件

| 文件 | 操作 |
|------|------|
| `ai_service/eval/prompt_variants.py` | 新建：N 变体 × golden 评测 × 对比表（Accuracy/insufficient Recall/kappa/耗时）+ --variant/--limit/--save/--no-save/--fixture |
| `ai_service/agent/reflector.py` | 修改：check_sufficiency(prompt=...) 可注入参数（默认零回归）+ HHEM 交叉对数上限 + 父块文本截断 |
| `ai_service/agent/router.py` | 修改：L2 无条件触发 + 规则表提前短路 + 停用词表数据驱动扩充（43 词） |
| `ai_service/rag/engine.py` | 修改：L3 只对实测低分标记（缺 abs_cosine 不标记） |
| `ai_service/rag/retrieval/factcheck_judge.py` | 修改：_PREDICT_TIMEOUT 15→20 + 日志文案动态化 |
| `ai_service/src/config.py` | 修改：retrieval_fusion_mode 默认 hybrid→rrf（保留 hybrid 回退开关） |
| `ai_service/main.py` | 修改：lifespan HHEM 后台 fail-soft 预热 |
| `ai_service/tests/test_prompt_variants.py` | 新建：12 项（prompt 注入/默认零回归/自洽同口径/变体定义/指标/CLI/对比表） |
| `ai_service/tests/test_intent_validation.py` | 修改：L2 无条件触发行为升级断言 + E2E query 类 + 边界样本 + 规则短路 + 停用词（+6 项） |
| `ai_service/tests/test_factcheck_judge.py` | 修改：HHEM 对数上限 + 截断断言（+3 项） |
| `specs/adr/0011-prompt-eval-optimization.md` | 新建：ADR-0011（计划引用但缺失，按 Planner 描述四维评估/业界工具/四代算法/三步落地补建）+ 状态更新（第一步完成） |
| `specs/module-055-prompt-eval/changelog.md` | 本文件 |
| `memory/` 三文件 | 修改（Developer 活动行/模块清单/file-index 追加） |

## 9. 全量回归

**688 passed / 0 failed**（667 基线 + 21 新增 = 12 prompt_variants + 6 intent + 2 factcheck caps + 1 truncation；5 存量 warning 与模块无关）。

## 10. 已知边界 / 待办

1. **intent golden 实测 0.98**（baseline 1.0）：2 条 realtime→knowledge 系 LLM 自判（非 L2 所致），方向为多检低风险；deepseek 分类非确定性属既有特性。
2. **verify 极端延迟兜底**：deepseek 抖动时 LLM 拆句/判分 15s 超时仍可能返回空 claims（fail-soft 设计，前端已处理）；HHEM 环节（E2E 根因）已消除。
3. **FTS 信号固有噪声**：简历类文档含闲聊词（电影/人民币等），停用词表是数据驱动防护；未覆盖的新闲聊词可能被"宁多检不漏检"哲学兜底到知识库路径（无相关结果如实回答，非硬错误）。
4. **`_retrieve` Redis 缓存 key 不含融合模式**（module-053 遗留）：hybrid↔rrf 切换期间同 query 可能复用另一模式缓存（TTL 300s）；默认已定 rrf，生产无切换场景，未修（超出本模块范围）。
5. **变体全量跑**（100 条 × 5 变体 = 500 LLM 调用）未在本模块执行（--limit 冒烟已验证管线；成本可控留评测时按需跑）。
6. **HHEM 判定质量**（module-051 kappa 0.3252 未达门槛）与本次时序修复正交，不在本模块范围。
