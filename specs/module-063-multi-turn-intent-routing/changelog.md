# Module-063 变更日志 — 多轮对话意图路由升级（会话级路由 + 短句继承 + 改写复用）

> Developer 产出 | 2026-08-14 | 中文，含多轮评测三指标数字 + 取舍/降级 + 已知边界/口径声明
> 开工前已读 memory/project-context.md 全文（模块清单/ADR 索引/迭代状态）
> 决策依据：specs/adr/0015-multi-turn-intent-routing.md + task-brief.md（WP-A~E）

## 一、实现总览

落地 ADR-0015 全部决策：会话级路由（classify 吃 history）+ 短句意图继承（规则层零 LLM）+ 分诊式改写喂路由 + 工具历史信号 + golden 多轮评测。五个工作包：

| WP | 内容 | 产出 |
|----|------|------|
| WP-A | 会话级路由：classify(query, history) + LLM 上下文 + L4 特征拼接 | router.py / intent_classifier.py / config.py |
| WP-B | 短句意图继承（去语气词 → 长度<6 无特征 → 继承上一轮 intent，零 LLM） | router.py `_short_inherit` |
| WP-C | 分诊式改写提前到路由前：改写结果同时喂路由 + 检索；precise 短路 | engine.py |
| WP-D | 工具历史信号 + golden_multi_turn 评测（≥10 对 + 三指标） | router.py / eval/golden/golden_multi_turn.py |
| WP-E | 回归验收：全量 pytest + 真实 E2E 冒烟 + 文档 | tests / changelog / ADR / memory |

全量 pytest **951 passed / 0 failed**（897 基线 + 54 新增：test_multi_turn_routing.py 35 + test_golden_multi_turn.py 19）。**存量测试零改动**（897 基线全绿验证）。

## 二、WP-A 会话级路由（classify(query, history)）

- `RouterAgent.classify(query, history=None, tool_history=None)`——history 为最近消息列表，内部 `history[-6:]`（路由只用最近 4-6 轮，task-brief §八.5 历史不全塞）。**空/None history → 行为与改动前逐字一致**（存量测试零改动，897 基线验证）。
- **LLM few-shot 上下文**：`_build_prompt` 有 history 时在 `_PROMPT_TEMPLATE` 后拼 `_MULTITURN_CONTEXT`（最近 4 轮、每条截断 300 字符）——"省略句/指代句结合上下文判断意图；含义完整句按字面判断"（防多轮闲聊被错误归因 knowledge 的 LLM 侧护栏）。空 history 用原模板逐字一致。
- **L4 分类器特征拼接**：`IntentClassifier.predict_proba(query, prev_user_query=None)`——prev 提供时拼接最近一轮 user query 向量（**list 拼接 2048 维**，训练时同构，参考 memory_conflict_clf 两条嵌入先例）。**诚实边界：当前落盘模型 intent_clf.joblib 为单 query 1024 维训练**——传入 prev 会触发 sklearn 维度不匹配抛 ValueError → router 捕获回退 LLM（fail-open 零回归）。新 config `intent_classifier_multi_turn`（PW_）默认 **false**（存量模型零回归）；置 true 需先重训（train_intent_classifier.py 构造含 prev 的配对样本，模型维度对齐 2048）。**L4 多轮拼接能力已就绪但未重训生效，如实声明**。
- **L4 + L2 对齐（本模块实测暴露的新增）**：L4 路径原本不走 L2 确定性信号确认（module-056 L4 为决策主体时直接返回）。golden_multi_turn 真实测量暴露：L4 单句分类无历史上下文，多轮省略句（"怎么解决呢"）误判 casual（0.65）→ 分诊 FTS 术语"解决"命中本应拉回 knowledge 却被 L4 短路。修复：**L4 路径对 intent≠knowledge 同样走 `_deterministic_confirm`**（与 LLM 路径同款零 LLM 安全网；module-055 已证 L2 信号精确——golden 50 条非 knowledge 样本误确认 0）。真实复测：该对由 casual → knowledge，意图保持 11/12 → **12/12**。存量 L4 测试全部返回 knowledge 高概率 → L2 不触发，零改动全绿。
- 通过标准：空历史零回归 ✓ / `[知识库,"为什么"]`→knowledge ✓ / `[闲聊,"哈哈"]`→casual_chat ✓ / `[知识库,"今天天气怎么样"]`→realtime（话题漂移不继承）✓。

## 三、WP-B 短句意图继承（规则层零 LLM）

- `_short_inherit` 在 classify 内部、LLM/分类器调用**之前**短路。规则：
  1. **去语气词** `_strip_particles`（`_PARTICLE_WORDS` = 哦/呢/呀/啦/请问/那个/嘛/吧，task-brief §八.6 先做最常用 8 个）——"为什么呀"→"为什么"、"那图谱呢"→"那图谱"。
  2. 去除后 **长度 < 6 字符** 且 `_deterministic_confirm` **无新特征**（FTS 术语未命中/图谱实体未命中/规则表未命中）→ **继承上一轮 intent**（history 最近一条 user 消息的路由结果，无状态从 history 推演，`_classify_prev` 递归允许省略句链式继承，深度上限 `_INHERIT_MAX_DEPTH=3` 防无限递归）。
  3. **有特征（FTS/图谱/规则）→ 必须正常路由**（防话题漂移："今天天气"靠规则表 rule_veto 挡住不继承）。
- 继承来源无状态：从 history 推演（task-brief 优选方案，未引入 engine 会话状态）。成本声明：继承仅对"短 + 无特征 + 有历史"的省略句触发，典型 `[完整问题, "为什么"]` 只需 1 次 prev 路由（prev 为完整问题，长度≥6 直接跳过继承判断零额外 DB）；省略句链（"为什么"前又是"为什么"）逐层回退，深度≤3 有界。
- 通过标准：`[知识库,"为什么"/"那图谱呢"/"为什么呀"]`→knowledge ✓；`[知识库,"今天天气"]`→正常路由 ✓；单轮（无 history）短 query → 正常路由（无上轮可继承）✓。

## 四、WP-C 分诊式改写喂路由（⭐ 核心增量）

- **关键洞察落地**：现有分诊式改写（FTS 静态分诊 → 模糊 LLM 改写 → 保真预检余弦回退 → 原/改写并行择优）本就是业界 Hybrid 改写标准形态——本模块把它**提前到路由前**，改写结果**多喂一个消费方**（路由 + 检索）。
- `engine.chat` 重构：改写块从知识库路径前移到意图路由前。`current_query` = 改写成功且保真通过时的改写后 query（`prepare` 并行择优 `used_rewrite=True`），失败/回退 = 原始 query。路由用 `classify(current_query, history=request.history)`。
- **分诊短路（可选优化，已验证不破坏现状）**：`prepare` 返回 `mode=="precise"`（FTS 术语命中）**且非闲聊/实时规则词**（`router_agent._rule_hits(query)` 为 False）→ 短路为 knowledge（省一次 LLM/L4 路由调用）。rule_hits 守卫防"你好"被强归 knowledge。
- **降级保留**（改写保守，task-brief §八.4）：改写失败/超时/保真未过/无变化 → 原始 query 路由+检索，行为与现状一致（单测断言 classify 收原 query）。
- **两条路径同改（纪律 §八.2）**：非流式 `engine.chat`（:237 附近）+ 流式 `main.py chat_stream`（Step 1 路由）都接 `history=request.history`；LangGraph 编排 `rag/graph/graph.py classify_intent` 同步接 `state["history"]`（一致性补全，空 history 零回归）。
- **流式路径改写喂路由边界（如实声明）**：流式 `_retrieve` 内部的 `prepare_query` 改写仍只喂检索、不喂流式路由（路由用原始 query + history——WP-A 上下文 + WP-B 继承已覆盖省略句场景）；非流式完整实现改写喂路由。纪律 §八.2 的"两条路径接 history"已满足。
- 通过标准：`"为什么"`（前文 knowledge）改写为完整句 → 路由 knowledge ✓（改写成功用改写 query）；改写失败/保真回退 → 原始 query 路由，行为与现状一致 ✓；分诊命中 FTS 术语 → 短路 knowledge ✓（单测验证不破坏现状）。

## 五、WP-D 工具历史信号 + golden 多轮评测

- **工具历史信号（规则层）**：`classify(query, history, tool_history)`——`tool_history` 含 `search_knowledge`/`generate_answer`（`_KB_TOOL_NAMES`）且短 query → **强制 knowledge**（确定性零 token，轨迹是意图的强信号）。**轨迹不可得（chat/chat_stream 请求 history 无工具轨迹）→ tool_history=None → 跳过**（不阻塞）。生产 chat 路径当前不携带工具轨迹（agent 轨迹不持久化进请求 history），故该信号为"能力就绪 + 单测覆盖"，待 agent 轨迹接入后接线（如实声明）。
- **评测闭环 `eval/golden/golden_multi_turn.py`**：12 条多轮追问对（prev 完整知识库问题 + follow_up 省略句/指代句，全部 expected=knowledge）+ 三指标：
  - **自包含清晰度** self_contained_ratio：对话改写把省略句补全成可独立理解 query 的比例（改写成功且 != 原 follow_up）。
  - **意图保持** intent_preserved_ratio：生产多轮路由 `classify(follow_up, history=[prev])` intent == 标注；对照 raw_intent_ratio（单句路由基线，展示省略句漏检）。
  - **检索提升** retrieval_delta：改写后检索与"上一轮完整问题检索"（相关锚点）的重叠度增量 = mean(overlap(rewrite, prev) - overlap(raw, prev))。**无 golden 标注 → 用 prev 检索作相关锚点，代理口径如实声明**。
  - `--fixture` 模式（启发式改写+意图，不依赖 LLM/DB，检索待环境）；`eval_type='multi_turn'` 落库（record_eval_run）；单元测试 19 项（数据集校验/启发式/重叠度/三指标纯函数/fixture）。

### 5.1 真实评测数字（2026-08-14，LLM deepseek + DB，--no-save 未落库）

| 指标 | 修复前 | **修复后（L4+L2 对齐）** |
|------|--------|--------------------------|
| 自包含清晰度 | 0.9167（11/12） | **0.9167**（11/12，"为什么"改写返回 None 回退） |
| 意图保持（多轮路由） | 0.9167 | **1.0000（12/12）** ✅ |
| 对照单句路由 | 0.8333 | **0.9167**（11/12，"为什么"单句无特征漏检——正是多轮要解决的场景） |
| 检索提升 retrieval_delta | +0.3818 | **+0.4363**（raw_overlap 0.2364 → rewritten_overlap 0.6727） |

- **意图保持 12/12 全部达成**（AC：10 条多轮对全部意图保持）；检索提升 +0.4363（改写把省略句对齐回主题文档，raw_overlap→rewritten_overlap 显著提升，AC：检索不降）。
- 单句对照 11/12 暴露"为什么"单句无特征 → 误判 casual（无历史无法推断）——正是本模块会话级路由 + 短句继承要解决的缺口，多轮路由补上后 12/12。
- 自包含 11/12：真实 LLM 对话改写 "为什么" 该次返回 None（改写与原句相同/失败回退），如实标注（LLM 非确定性，多次运行可能不同）。

## 六、WP-E 回归验收

- **全量 pytest 951 passed / 0 failed**（897 基线 + 54 新增）。存量测试**零改动**（897 基线全绿）。
- 新增测试：
  - `tests/agent/test_multi_turn_routing.py`（35 项）：WP-A 空历史零回归 / LLM 上下文 / L4 prev 拼接 2048 维 / L4+L2 修正；WP-B 去语气词 / 短句继承 / 话题漂移不继承 / 单轮不继承 / 有特征正常路由 / 省略句链式继承 / 历史截断 [-6:]；WP-C engine 改写喂路由 / precise 短路 / 失败回退 / 默认关零回归 / 流式+LangGraph 接 history；WP-D 工具信号 / 轨迹不可得跳过。
  - `tests/eval/test_golden_multi_turn.py`（19 项）：数据集校验 / 启发式改写+意图 / 重叠度 / 三指标纯函数 / fixture 运行。
- **真实 E2E 冒烟（DB + Redis + 本地 bge-m3 + HHEM + deepseek，2026-08-14）**：
  - 路由冒烟：round1 完整知识库问题→knowledge（L4）；round2 "为什么"→**knowledge（短句意图继承，reason 可见）**；round3 "今天天气怎么样"→realtime（话题漂移不继承）；round4 "哈哈"→casual_chat。PASS。
  - 全链路 engine.chat 冒烟：round1 message=ok / 4 sources / 74.5s；round2 "为什么" message=ok / **5 sources（走检索链路）** / 70.9s。PASS（省略句成功路由知识库并检索出引用）。

## 七、已知边界 / 口径声明

1. **L4 多轮拼接未重训生效**：`intent_classifier_multi_turn` 默认 false，当前 L4 用单 query 1024 维（存量模型）。2048 维拼接能力已实现 + 单测覆盖，需多轮标注数据重训后置 true（fail-open：维度不匹配 → 回退 LLM，零回归）。
2. **工具历史信号未接生产 chat**：chat/chat_stream 请求 history 无工具轨迹 → 跳过（能力 + 单测就绪，待 agent 轨迹持久化后接线）。
3. **流式路径改写不喂路由**：流式 `_retrieve` 改写只喂检索；流式路由用原始 query + history（WP-A 上下文 + WP-B 继承覆盖）。非流式完整改写喂路由。
4. **检索提升用 prev 检索作锚点（代理口径）**：多轮 follow_up 无 golden 标注，重叠度 = 改写后与"上一轮完整问题检索"的标题命中比例，非 golden Hit@5。量级趋势可信（+0.4363 显著），绝对语义请勿过度外推。
5. **L4+L2 对齐的风险面**：L4 判非 knowledge 且 FTS/图谱命中 → 修正 knowledge（与 LLM 路径同款语义）。L2 信号 precision 已由 module-055 golden 50 条非 knowledge 样本误确认 0 背书；仍存在理论误转（闲聊 query 恰好含知识库术语）——与 LLM 路径风险同源，非本模块新增。
6. **多轮评测在真实 deepseek 环境跑出**：LLM 非确定性（改写/分类）→ 数字是单次运行快照，意图保持 12/12 有趋势意义但非证明；自包含 "为什么" 单次改写失败即为非确定性实例。
7. **`_PARTICLE_WORDS` 放在 router.py 而非 config.py**：任务 brief 的 config 项是"如需"引导，项目惯例规则表都在 router.py（`_RULE_TABLE`/`_FUNCTION_STOPWORDS`），保持一致性。

## 八、面试口径（08 文档意图路由节更新点）

> 多轮对话意图路由：单句识别漏掉省略句/指代句（"为什么"无前文特征会被误判闲聊）。生产级三层：① 路由带最近几轮历史（会话级路由 classify(query, history)，LLM prompt 拼上下文，L4 分类器拼接最近一轮 query 向量）；② 极短无特征 query 继承上一轮意图（规则层零 LLM，先去语气词再判长度）；③ 复用分诊式改写把省略句改写成自包含 query 再路由+检索（一次改写两头受益）。业界标准叫 conversational query rewriting（百度千帆上线召回 62.5%→89.2%、平均轮次 3.2→1.8）。踩坑：历史不全塞（4-6 轮够）、改写必须保守（保真预检回退防 over-rewriting）、继承只对极短 query 生效（防话题漂移）、L4 单句分类也要走 L2 确定性信号（实测暴露省略句误判）。工具调用历史是附加规则信号（上轮 search_knowledge → 短 query 强制 knowledge）。

## 九、测试清单

| 文件 | 数量 | 内容 |
|------|------|------|
| tests/agent/test_multi_turn_routing.py | 35 | WP-A/B/C/D 路由 + engine 接线 |
| tests/eval/test_golden_multi_turn.py | 19 | golden 多轮评测脚本（数据集/指标/fixture） |
| **合计新增** | **54** | 全量 897 + 54 = **951 全绿** |
