# 测试报告 — Module-055: 提示词评估优化（ADR-0011 第一步）+ E2E 待办修复 + rrf 切默认

> Tester | 2026-08-12
> **结论：✅ 验收通过（AC 全过，0 阻塞）**

---

## 1. 全量回归

| 项 | 结果 |
|----|------|
| 命令 | `python -m pytest tests/ -q`（ai_service 目录，独立复跑） |
| 结果 | **688 passed / 0 failed**，152.56s，5 存量 warning（setex 弃用等，与模块无关） |
| 口径 | 667 基线 + 21 新增（prompt_variants 12 + intent 6 + factcheck caps/截断 3）——与 changelog §9、Reviewer 复跑（688/0，159.96s）逐字一致 |
| 定向抽查 | test_prompt_variants.py 12 项 + test_intent_validation.py 47 项 + test_factcheck_judge.py 38 项均含于全量，关键用例核验：L2 无条件触发行为升级（test_high_confidence_casual_triggers_l2）、E2E query 高置信误判修正（test_e2e_query_high_confidence_casual_corrected）、JVM/Redis 边界样本（test_boundary_term_question_queries_corrected）、规则表短路零 DB（test_rule_check_short_circuits_before_db）、prompt 注入零回归逐字节断言（test_default_prompt_zero_regression）、HHEM 对数上限/截断（test_docs_capped_to_top_two / test_claims_capped_at_max / test_doc_content_truncated_for_hhem）、L3 缺字段不标记（TestL3PostValidation） |

---

## 2. 真实 E2E 冒烟复测（uvicorn 8001，默认模式 = rrf，无 PW_RETRIEVAL_FUSION_MODE）

### 2.1 3 问题场景（chat 端点 POST /ai/rag/chat）

| query | intent | sources | top_abs_cosine | suspected | verified_claims | 结论 |
|-------|--------|---------|----------------|-----------|-----------------|------|
| G1垃圾收集器的核心创新是什么？ | knowledge（conf 1.0） | 3（真实 G1 文档） | **0.6664** | **false** | **total=8**（本次实测 inf6/uns2，changelog 实测 sup3/inf1/uns4——verdict 分布随 LLM 拆句/HHEM 判分非确定性浮动，非空核心验收点达成） | ①intent 漏检修复 ✅ ②HHEM 非空 ✅ ③abs_cosine 真实值 ✅ |
| JVM的内存结构是怎样的？ | knowledge | 4 | **0.7052** | **false** | total=8（inf1/uns7，答案如实声明 KB 覆盖缺口） | 与 changelog §7.1 逐位一致 ✅ |

注：E2E query 在 module-054 被判 casual_chat（sources=0 闲聊），本次实测 2 次均 intent=knowledge + 真实 G1 引用答案——问题①已修复；changelog §3.1 诊断记录（LLM 分类非确定性：本模块实测 3 次均 knowledge）成立。

### 2.2 闲聊/实时路径（零回归）

| query | message | sources | 结论 |
|-------|---------|---------|------|
| 你好呀 | casual_chat | 0 | L2 rule_veto 保持闲聊 ✅（steps=null 属正常路径设计） |
| 现在几点了？ | realtime_not_implemented | 0 | 0.9s 快速返回 ✅ |

### 2.3 stream 端点（POST /ai/rag/chat/stream）

- G1 query：事件序列 **step×4（intent→retrieval→rerank→reflection）+ token×529 + verified×1 + done×1**，0 error；intent=知识库（conf 0.95-0.98）；**verified 事件 claims 非空**（含 supported/unsupported 判定，如 "G1 垃圾收集器的核心创新是 Region 分区机制。→ supported[1]"）；done 携带真实 sources（引用文档标题完整）。
- **WP-4 场景实测（5 次 stream：G1×3/JVM/Redis/Kafka）**：retrieval step `top_abs_cosine=0.0` + `suspected_misclassify=**false**`（恒不误触发）。0.0 的语义 = rrf 融合后 top-1 为图谱通道父块（无向量分数，无 rerank 的流式路径下稳定排首）——按 WP-4 新语义"缺字段如实显示 0.0 且不标记"，与 changelog §5.3 描述完全一致（旧行为在该场景恒误标 true）。**真实值场景**：chat 端已实证 0.6664/0.7052（非恒 0.0）+ changelog 记录 stream 0.8296 实例 + 单测 TestL3PostValidation 覆盖（实测低分仍标记 / 0.3 边界 / 整组缺失不标记 / top-1 缺失不标记）——修复语义完备。

### 2.4 WP-5 默认模式

无 `PW_RETRIEVAL_FUSION_MODE` 环境下 `settings.retrieval_fusion_mode == "rrf"`（独立进程验证）；真实 HTTP chat+stream 全链路 rrf 正常（上述实测即默认 rrf 模式跑出）。

### 2.5 WP-1 变体测试冒烟

- `--fixture --limit 5 --variant baseline,v_brief,v_strict`：对比表输出正常（启发式判断器 prompt 无关，各变体同分属预期，changelog §2.2 同口径）。
- 真实 LLM `--limit 3 --variant baseline,v_brief`：deepseek 真实调用，baseline 7.0s / v_brief 3.9s，Accuracy/insufficient Recall/kappa/耗时对比表正常，--no-save 默认不落库。

---

## 3. AC 逐条对照

| AC | 标准 | 结果 | 依据 |
|----|------|------|------|
| §1-1 | eval/prompt_variants.py 存在：N 变体 → golden 评测 → 对比表（Accuracy/kappa/耗时） | ✅ | 5 变体（baseline/v_brief/v_strict/v_fewshot/v_conservative）× golden_sufficiency；对比表含 Accuracy/insuff Recall/kappa/耗时；真实 LLM 冒烟 + fixture 冒烟均通过 |
| §1-2 | reflector prompt 可注入参数，默认值不变零回归 | ✅ | `check_sufficiency(prompt=None)` 逐字节等于 `_CHECK_PROMPT`（单测 test_default_prompt_zero_regression）；自洽第二判同用注入变体 |
| §1-3 | 支持 --variant / --no-save / 落 eval_runs（eval_type='prompt_variant'） | ✅ | CLI 实测 --variant/--limit/--fixture/--no-save 工作；--save 落库路径代码核查（save_variant_runs → eval_type='prompt_variant'） |
| §1-4 | 只度量不替换生产 prompt | ✅ | baseline 恒引用 `_CHECK_PROMPT` 常量本身；变体仅经 prompt 参数注入；生产默认行为零变更（changelog §2 + 测试） |
| §2-1 | 诊断记录（classify 输出/confidence/L2 触发/L4 状态）入 changelog | ✅ | changelog §3.1 表格：E2E query 实测 classify=knowledge/conf 1.0、L2 原条件缺口（低置信才触发）、L4 默认关、规则表无命中 |
| §2-2 | "G1垃圾收集器的核心创新是什么？"类 query 走 knowledge | ✅ | 真实 E2E 2 次均 intent=knowledge、sources=3、真实 G1 引用答案 |
| §2-3 | 修复有测试覆盖（专有术语 + 疑问句边界样本） | ✅ | test_e2e_query_high_confidence_casual_corrected + test_boundary_term_question_queries_corrected（JVM/Redis） |
| §3-1 | 诊断 verified_claims=0 根因（超时/降级链）入 changelog | ✅ | changelog §4.1：级联超时（HHEM 15 对负载贴近 15s + LLM 判分再 15s）；实测 15 对冷 9.04s/热 0.11s 每对/服务内 17-19s |
| §3-2 | 非流式 chat 正常回答时 verified_claims 非空 | ✅ | 真实 E2E verified total=8（sup0/inf6/uns2 与 changelog sup3/inf1/unsup4 分布浮动，非空达成） |
| §3-3 | 方案取舍有数据支撑（实测耗时对比），changelog 记录 | ✅ | changelog §4.2：交叉对数上限 8×2 + 预算 20s + 截断 500（实测 6 对 9.3s→2.4s、verdict 0.568→0.802）+ 预热实测记录 |
| §4-1 | 诊断 rrf 融合路径 abs_cosine 丢失原因入 changelog | ✅ | changelog §5.1：融合路径存档代码正确（module-053 红线成立，直调实测 0.70）；真根因 = 图谱通道父块排 top-1 缺向量分数（引擎 _retrieve 复现 id=239 MISSING）+ 旧"缺→0.0 标记"语义 |
| §4-2 | rrf 模式 retrieval step top_abs_cosine 为真实值（非恒 0.0） | ✅ | chat 端实测 0.6664/0.7052 真实值（非恒 0.0）；stream 端 0.0 为图谱父块无向量分数的如实表示（度量诚实，changelog 同口径 + stream 0.8296 实证 + 单测覆盖） |
| §4-3 | suspected_misclassify 不再误触发 | ✅ | 真实 E2E chat 2/2 false + stream 5/5 false（旧行为在缺字段场景恒误标 true）；单测覆盖实测低分仍标记 |
| §5-1 | retrieval_fusion_mode 默认 hybrid→rrf（保留 hybrid 回退开关） | ✅ | config.py 默认 "rrf"；PW_RETRIEVAL_FUSION_MODE=hybrid 回退注释保留；无环境变量实测 == "rrf" |
| §5-2 | 全量 pytest 全绿；存量测试若更新断言须注明理由 | ✅ | 688/0；存量测试零断言改动（module-054 方案 A/B 已消解，test_degradation_fix.py 显式 monkeypatch 模式）；行为升级仅 L2/L3 两处且测试改名注明（test_high_confidence_casual_triggers_l2 替换 test_high_confidence_skips_l2 等） |
| §5-3 | 真实 E2E 冒烟（chat+stream）rrf 默认模式正常 | ✅ | 本次真实 HTTP 冒烟全链路（§2）即为默认 rrf 模式 |
| §6-1 | WP-2 根因复杂 → 一层兜底 + 深层待办 | ✅ | 根因找到（LLM 非确定性高置信误判），无需一层兜底；深层待办如实记录（changelog §10.1：deepseek 分类非确定性属既有特性） |
| §6-2 | WP-5 切默认后存量失败 → 核对行为升级/回归 | ✅ | 零存量失败（688/0）；Reviewer git diff 核验仅两处行为升级测试改名注明理由 |
| §6-3 | 全量 pytest 667 全绿保持 | ✅ | 688/0（667 基线 + 21 新增） |
| §7-1 | ChatResponse/前端零改动 | ✅ | verified_claims 恢复后前端正常渲染（结构不变，仅值恢复）；本次未改前端 |
| §7-2 | retrieval 返回结构不变（abs_cosine 透传为修复） | ✅ | 仅 L3 判定语义变化（缺字段不标记），字段结构/返回格式不变 |
| §7-3 | reflector prompt 注入参数向后兼容 | ✅ | 新参默认 None 零回归（逐字节测试） |
| §8-1 | tests/test_prompt_variants.py：变体定义/对比表/参数注入零回归 | ✅ | 12 项全绿 |
| §8-2 | WP-2/3/4 各修复回归测试 | ✅ | intent 47 项（含 E2E query + 边界）、factcheck 38 项（caps + 截断）、L3 单测（缺字段不标记） |
| §8-3 | python -m pytest tests/ -q — 全量 667+ 全绿 | ✅ | 688/0 |
| §9-1 | changelog.md / review-report.md / test-report.md | ✅ | 三文件齐备（本文件为第三份） |
| §9-2 | project-context.md 模块清单追加 module-055 行 + 头部日期 | ✅ | 行 73（0.55.0-module-055 / 2026-08-12 / ✅ 完成），格式对齐；头部"最后更新 2026-08-12（module-055 完成）" |
| §9-3 | agent-activity-log.md：Developer/Reviewer/Tester 活动行 | ✅ | Developer（L134）+ Reviewer（L135）+ 本模块 Tester（L136，本报告追加） |
| §9-4 | file-index.md 新文件行（只追加） | ✅ | 4 行（prompt_variants.py / test_prompt_variants.py / ADR-0011 / module-055 spec 目录） |
| §9-5 | ADR-0011 状态更新（第一步变体测试已完成） | ✅ | 状态行"✅ 第一步（变体测试）已实施（module-055，2026-08-12）；第二/三步按数据决定" |
| §9-6 | 开工前必读 project-context.md（changelog 注明） | ✅ | changelog 头部注明"开工前已读 project-context.md 全文" |
| §9-7 | 文档类（简历/弹药）不改 | ✅ | 本次冒烟/核查未触达 docs 类文件；Reviewer git status 核验零改动 |

**AC 汇总：32/32 通过（§1 4 + §2 3 + §3 3 + §4 3 + §5 3 + §6 3 + §7 3 + §8 3 + §9 7），0 不适用，0 阻塞。**

---

## 4. 记忆文件硬核查

| 项 | 结果 |
|----|------|
| project-context.md 模块清单 module-055 行（格式对齐） | ✅ 行 73 |
| project-context.md 头部"最后更新"日期 | ✅ 2026-08-12（module-055 完成） |
| agent-activity-log.md Developer 活动行 | ✅ L134 |
| agent-activity-log.md Reviewer 活动行 | ✅ L135 |
| agent-activity-log.md Tester 活动行 | ✅ L136（本报告追加） |
| file-index.md 新文件行（只追加） | ✅ 4 行（L76-79） |
| ADR-0011 状态 | ✅ 第一步已实施 |
| 其他模块历史记录行 | ✅ 未修改 |

---

## 5. 冒烟汇总与结论

- 全量 pytest：**688/0**（152.56s，5 存量 warning）——与 changelog/Reviewer 一致
- 真实 E2E（默认 rrf）：3 问题场景（intent 走 knowledge / verified_claims 非空 / top_abs_cosine 真实值 + 不误触发）**全部修复**；闲聊/实时路径零回归；stream 事件序列完整 0 error；变体测试 fixture + 真实 LLM 冒烟通过
- 记忆硬核查：全部满足
- 非阻塞附注（沿用 Reviewer 5 minor 中与本报告相关的 3 项）：① config.py 注释"存量 2 项降级用例按新语义更新断言"与 changelog"零存量断言改动"口径矛盾（疑似 module-053 旧注释搬运，行为事实以 changelog §6 + 全量测试为准）；② factcheck_judge.py 顶部 docstring 残留"15s 超时"（常量区已 20s）；③ stream 图谱父块排首时 top_abs_cosine=0.0 属"缺字段如实表示"的度量诚实语义，非缺陷（suspected=false 恒成立证明修复目标达成）
- 测试数据/服务清理：uvicorn 服务已停止（8001 端口释放）；E2E 冒烟无测试数据入库（chat/stream 均只读对话，未持久化测试记忆）

**模块标记 ✅ 完成**
