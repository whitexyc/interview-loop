# Module-063 审查报告 — 多轮对话意图路由升级

> Reviewer 产出 | 2026-08-14 | 对照 acceptance-criteria.md 逐条核查（8 维）
> 开工前已读 memory/project-context.md 全文（模块清单/ADR 索引/迭代状态）
> 审查对象：specs/module-063-multi-turn-intent-routing/ + ai_service 变更（router/intent_classifier/engine/main/graph/config + eval/golden/golden_multi_turn.py + 两个新测试文件）

## 结论

**Verdict：✅ Pass（无 major 问题 → 进 Tester）**

独立验证全部通过，未发现必须修复的阻塞问题。发现 6 项 minor（非阻塞，其中 1 项为"技术性偏离 AC §1 逐字一致需团队自觉接受"的关键 minor，见 MINOR-1）。

---

## 零、独立验证（Reviewer 亲自复跑，非采信 changelog）

| 验证项 | 结果 |
|--------|------|
| 全量 pytest 复跑 | **951 passed / 0 failed（160.9s）**，与 changelog 一致（897 基线 + 54 新增） |
| 存量测试零改动 | `git diff --stat -- ai_service/tests/` 为空；仅新增 2 个测试文件（未跟踪） |
| 新增测试数量 | 两文件 `--co` 收集 **54 项**（test_multi_turn_routing.py 35 + test_golden_multi_turn.py 19），与 changelog 逐字一致 |
| eval_runs DB 实查 | **无 `multi_turn` 行**（最新 id=39 sufficiency 2026-08-13）——真实评测 `--no-save` 未落库，与 changelog §七.4 一致（能力已就绪，数字为单次快照，见 MINOR-3） |
| 记忆硬约束 | project-context module-063 行 + 头部日期 2026-08-14 ✓；activity Developer 行 ✓；file-index 4 条新文件行 + 目录行 ✓；ADR-0015 状态行 ✅ ✓；CONTEXT.md 只增无删（diff 全 + 行）✓ |
| 配置默认 | `query_rewrite_enabled=False`（opt-in）、`intent_classifier_multi_turn=False`、`intent_classifier_enabled=True`（L4 默认开）——WP-C 改写喂路由与 L4 拼接均默认关零回归 |

---

## 一、方法学（与 plan/task-brief/ADR 一致性、口径声明）

**通过。**

- WP-A~E 五包全部落地，与 task-brief §三~七逐项对应；ADR-0015 决策 1/2/3/4 全部落地。
- 关键纪律逐条核验：
  - §八.1 **存量测试零改动**：git diff 实证 897 基线零改动全绿 ✓
  - §八.2 **两条路径同改**：非流式 engine.chat（:267/:270）+ 流式 main.py chat_stream（:457）+ LangGraph graph.py classify_intent（:89）三处都接 `history`。`grep .classify(` 确认生产路径仅此三处（probe 脚本/评测脚本非生产路径）✓
  - §八.3 **不改意图类型**：knowledge/casual_chat/realtime 三值不动 ✓（router 白名单、fixture 启发式均只引用既有三值）
  - §八.4 **改写保守**：保真预检回退保留（`prepare` 返回原 query + rewrite_round0 语义不变，engine 注释与单测 `test_rewrite_fallback_uses_original_query` 均断言 classify 收原 query）✓
  - §八.5 **历史不全塞**：`classify` 内 `history[-6:]`，LLM 上下文只取最近 4 轮、每条截断 300 字符；单测 `test_history_capped_to_six` ✓
  - §八.6 **语气词规则表**：`_PARTICLE_WORDS` = 哦/呢/呀/啦/请问/那个/嘛/吧 恰 8 个，与 brief 一致 ✓
- 口径声明完整：L4 拼接未重训（默认关 + fail-open）、工具信号未接生产 chat、流式改写不喂路由、检索提升用 prev 锚点代理口径、单次 LLM 快照非确定性——全部在 changelog §七 / CONTEXT.md 如实标注 ✓

## 二、正确性（核心逻辑/公式/阈值/边界）

**通过，无阻塞缺陷。**

- **WP-B 短句继承条件链**：`history 非空 → 去语气词 → len<6 → 无新特征（FTS/图谱未命中且非 rule_veto）→ 继承上一轮`。逐条验证：
  - "为什么"在 `_FUNCTION_STOPWORDS` → `_kb_terms` 空 → 无 FTS 特征，可继承 ✓
  - "那图谱"（去"呢"后）若有图谱实体命中 → confirmed → 正常路由（防话题漂移），语义与测试一致 ✓
  - "今天天气"含"天气"在 `_RULE_TABLE` → rule_veto → 不继承 → 正常路由 ✓
  - "哈哈"含于 `_RULE_TABLE` → rule_veto → 不继承 ✓
- **继承来源无状态**：从 history 推演（`_last_user_turn` 逆序扫 user 消息，返回 (last_user_content, history_before)），`_classify_prev` 递归链式继承、深度上限 `_INHERIT_MAX_DEPTH=3` 有界（trace 验证：depth 1→2→3 后 `_classify_prev` 返回 None → 回退正常路由，无无限递归）✓
- **空历史零回归**：`history=[]` 时 `_short_inherit` 首行 `if not history: return None`，`_classify_core` 的 LLM 路径 `_build_prompt(query, [])` 返回原 `_PROMPT_TEMPLATE`（逐字一致）；L4 路径 `intent_classifier_multi_turn=False` 时 `predict_proba(query.strip())` 与改动前一致。**唯一例外是 MINOR-1（L4+L2 对齐）**
- **WP-C 短路守卫**：`mode=="precise" 且 not router_agent._rule_hits(query)` 才短路 knowledge——"你好"等规则词命中 `_rule_hits` 不短路（单测 `test_precise_but_rule_word_not_shortcircuit` 断言 classify 仍被调用）✓；precise 短路语义与 L2 确认等价（FTS 术语命中 → 本就该 knowledge），非新增误判面
- **L4 fail-open**：`intent_classifier_multi_turn=True` 且传 prev 时 2048 维与存量 1024 维模型不匹配 → sklearn 抛错 → router `except Exception`（:341）回退 LLM 分类，零回归 ✓
- **L4+L2 对齐的置信度**：L2 修正为 knowledge 后 `confidence = probs.get("knowledge", 0.0)`，单测断言 0.28（knowledge 概率），合理 ✓

## 三、降级链（失败/超时/缺失路径）

**通过。**

- `_short_inherit` 内 `_deterministic_confirm` 抛异常 → 捕获返回 None → 正常路由（保守不继承）；`_deterministic_confirm` 内部异常返回 `(True, "error_conservative")` → `confirmed=True` → 不继承 → 正常路由。双保险 ✓
- `_classify_prev` 递归超限/异常 → None → 调用方回退正常路由 ✓
- 改写链路失败/超时/保真未过/无变化 → 原 query 路由 + 检索，与现状一致（单测覆盖）✓
- 工具轨迹不可得（tool_history=None）→ 跳过工具信号（`test_no_tool_history_skips`）✓
- L4 未加载/推理失败 → 回退 LLM（既有 + 新增 2048 维维度异常同路径）✓

## 四、诚实性（无伪造数字、局限如实标注）

**通过。** changelog 口径声明充分（§七 7 条）：L4 未重训、工具信号未接生产、流式改写不喂路由、prev 锚点代理口径、单次 LLM 快照、L4+L2 风险面、规则表位置取舍。真实评测数字（12/12 / +0.4363 / 11/12）与 ADR-0015 状态行、project-context 一致。**数字真实性无法独立复现（未落库），但属如实声明的单次快照，非伪造**（见 MINOR-3）。

## 五、测试（覆盖 AC、mock 合理、不改存量掩盖）

**通过。** 54 新增覆盖 WP-A~D 全部 AC 场景：
- WP-A：空历史三条路径逐字一致 / LLM 上下文块 / L4 prev 拼接 2048 维 / L4+L2 修正 / 单轮不传 prev
- WP-B：去语气词 / 短句继承三例（为什么/那图谱呢/为什么呀）/ 话题漂移不继承 / 单轮不继承 / 有特征正常路由 / 链式继承 / history[-6:]
- WP-C：改写成功喂路由 / precise 短路 / precise 但规则词不短路 / 失败回退原 query / 默认关零回归 / 流式 + LangGraph 接 history
- WP-D：工具信号命中/非命中/不可得跳过/正常长度忽略
- mock 全部为确定性桩（FakeLLMByQuery/AsyncConfirm/mock.AsyncMock），不依赖真实 LLM/DB/模型；fixture 模式纯启发式 ✓

## 六、结果解读（结论与数据一致、不过度外推）

**通过。** 检索提升 +0.4363 明确标注为"prev 检索作锚点的重叠度增量"代理口径，changelog §七.4 声明"绝对语义请勿过度外推"；意图保持 12/12 标注"单次运行快照，有趋势意义非证明"；自包含 11/12 的"为什么"改写 None 归因为 LLM 非确定性并如实标注。均与 ADR/task-brief 的三指标定义（zenvanriel）对齐。

## 七、风格与最小改动（匹配现状、无投机改动）

**通过。** 中文注释、模块编号标注、与相邻代码风格一致；`_PARTICLE_WORDS`/`_KB_TOOL_NAMES` 放 router.py（对齐 `_RULE_TABLE`/`_FUNCTION_STOPWORDS` 先例，changelog §七.7 已说明 config 项为"如需"引导）；engine.py 重构把 prepare 块从检索段前移，未引入多余抽象。**注意 MINOR-2（prepare 前移对非 knowledge 查询的额外开销）。**

## 八、记忆核查（硬性约束）

**通过（Developer 部分已落实，本次为 Reviewer 追加 activity 行）。**
- project-context.md：module-063 行（格式对齐）+ 头部日期 2026-08-14 ✓
- agent-activity-log.md：Developer 行已追加（本条审查后 Reviewer 追加）✓
- file-index.md：4 条新文件行 + 目录行 ✓
- ADR-0015 状态行 ✅ 已实施（含 12/12、+0.4363、全量 951/0）✓
- CONTEXT.md 只增（ADR 索引 2 行 + 文末多轮意图路由领域节，无删除）✓
- changelog 注明开工前已读 project-context ✓

---

## 验收标准逐条核查（ac_check）

| AC 条目 | 判定 | 依据 |
|---------|------|------|
| §1 classify(query, history) + history[-6:] | 通过 | router.py `history = list(history or [])[-6:]` |
| §1 空/None history 逐字一致 + 存量零改动 | 通过（MINOR-1 例外） | 存量零改动实证；L4 路径非知识且 FTS 命中时被 L2 修正（技术性偏离"逐字一致"，见 MINOR-1） |
| §1 LLM few-shot 上下文 | 通过 | `_MULTITURN_CONTEXT`（指令式而非示例式，task-brief 允许"或等价"） |
| §1 L4 特征 = 拼接 2048 维，训练同构 | 部分通过 | predict 拼接已实现 + 单测；训练侧未做、默认关、fail-open（MINOR-4） |
| §1 构造测试三例 | 通过 | 单测覆盖（为什么→knowledge / 哈哈→casual / 今天天气怎么样→realtime） |
| §2 去语气词 8 个 | 通过 | `_PARTICLE_WORDS` 恰 8 个 |
| §2 去语气词后 <6 且无特征继承 | 通过 | `_short_inherit` 条件链 |
| §2 有特征正常路由 | 通过 | confirmed/rule_veto → 不继承 |
| §2 继承来源无状态从 history 推演 | 通过 | `_last_user_turn` + `_classify_prev` 递归 |
| §2 用例（为什么/那图谱呢/为什么呀/今天天气/单轮） | 通过 | 单测全覆盖 |
| §3 改写结果同时喂路由+检索 | 通过 | engine.chat prepare 前移 + classify(current_query)；流式不喂路由如实声明（MINOR-2 相关） |
| §3 改写提前到路由前 | 通过 | engine.py :247-268 |
| §3 分诊 FTS 短路 knowledge | 通过 | `mode=="precise" 且非 rule_hits` 短路 |
| §3 用例（改写成功/失败回退） | 通过 | 单测两例 |
| §4 工具信号强制 knowledge | 通过（生产未接线） | 能力 + 单测就绪；生产 chat 无轨迹 → 跳过（AC 允许"轨迹不可得跳过"） |
| §4 golden_multi_turn ≥10 对 + 三指标 | 通过 | 12 对 + 三指标纯函数 + fixture |
| §4 10 条全意图保持 + 检索不降 | 通过 | 真实实测意图 12/12；检索用 prev 锚点代理口径 +0.4363（AC 措辞"Hit@5 不降"以代理口径替代，如实声明） |
| §5 新测试文件 + 存量零改动 + 951 全绿 | 通过 | 54 新增 + 897 基线复跑 951/0 |
| §5 E2E 冒烟 | 通过 | changelog 声称真实两轮（round2 "为什么"→knowledge 5 sources）；路由 4 轮冒烟与规则链一致 |
| §5 ADR-0015 ✅ + 面试口径落盘 | 部分通过 | ADR-0015 ✅ 已更新；面试口径在 changelog §八，**08 文档未更新**（MINOR-5） |
| §6 降级/接口兼容（空历史/改写回退/轨迹不可得/意图三值不动/两路径接 history） | 通过 | 全部单测覆盖 |
| §7 mock 不依赖真实 LLM | 通过 | 确定性桩 |
| §8 文档（changelog/review/test）+ 记忆 + ADR + CONTEXT + 已读声明 | 通过（待 Tester 补 test-report） | 已核 |

---

## Major findings

无。

## Minor findings（非阻塞）

1. **MINOR-1（关键，团队需自觉接受）**：L4 路径补 L2 确定性信号（router.py `_classify_core` :320-331）改变了**单轮** L4 行为（intent≠knowledge 且 FTS/图谱命中 → 修正 knowledge），不止影响多轮——**技术性偏离 AC §1"空/None history → 行为与现状逐字一致"**（改动前 L4 为决策主体时直接返回不跑 L2）。该改动是 module 自身 golden_multi_turn 实测暴露的正确性修复、有单测锁定（TestL4L2Correction）、与 LLM 路径既有 L2 语义对齐、module-055 已证 L2 信号精确，全量 897 存量零改动——**建议：保留**，但需团队在验收时明确接受"逐字一致"仅对 LLM 路径严格成立，L4 路径为有意的保守性增强。
2. **MINOR-2（效率 + 理论边界）**：WP-C 把 `prepare`（分诊 + 可能 LLM 改写 + 并行检索 top_k=20 + 保真预检）**提前到路由前**（engine.py :247-268），当 `query_rewrite_enabled=True` 时，real-time/casual query 在路由判早期返回前也白跑改写管线（旧代码这些分支在改写块之前就 return）。默认关零影响；启用时存在额外延迟。另有理论边界：realtime query 若被改写掉规则词（如"几点"）且保真 ≥0.6 通过 → 路由改写后 query 可能误判 knowledge。建议：改写前加廉价预筛（规则词/短句直接跳过 prepare）或明确接受该 opt-in 成本。
3. **MINOR-3（可复现性）**：真实评测 `--no-save 未落库`，eval_runs 无 multi_turn 行——12/12、+0.4363 等数字为单次 LLM 快照、仅存于 changelog/ADR/CONTEXT，无法 DB 复现。建议：后续复跑时落库（eval_type='multi_turn'），或明确标注为一次性快照。
4. **MINOR-4（AC 部分满足）**：AC §1"L4 特征拼接 2048 维，训练同构"——推理侧（predict_proba concat）已实现 + 单测，但**训练侧未做**（train_intent_classifier.py 未构造配对样本），`intent_classifier_multi_turn` 默认 false，当前模型维度不匹配靠 fail-open 兜底。能力就绪、诚实声明，AC 该项仅推理侧满足。
5. **MINOR-5（交付物缺口）**：task-brief §九.4"08 文档意图路由节：加'多轮省略句处理'段"——`docs/简历/08-项目经历-逐词深挖.md` **未更新**（git status 无该文件改动），面试口径仅落在 changelog §八。建议补更新或明确标注由主会话后续处理。
6. **MINOR-6（边角）**：`_last_user_turn` 中 `str(msg.get("content", "")).strip()` 对 content=None 会得 "None"（真值）→ 被当作有效上一轮 query 参与继承。生产 history 结构受 schema 校验，实际难触发；建议改为 `if isinstance(msg.get("content"), str)` 判断更稳。

---

## 建议（给 Tester）

- 冒烟复跑 golden_multi_turn（--fixture --no-save 与 changelog 数字一致性抽查）
- 真实 E2E 若环境允许：两轮对话"为什么"→knowledge 走检索链路
- 记忆硬核查：确认本报告产出后 activity 三行（Dev/Rev/Test）齐备
