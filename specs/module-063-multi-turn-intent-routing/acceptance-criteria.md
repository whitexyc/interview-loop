# 验收标准 — Module-063: 多轮对话意图路由升级

> 图例：📋 功能 / 📦 降级 / 🔌 接口 / 🧪 测试 / 📝 文档
> 范围（task-brief §二）：WP-A 会话级路由 / WP-B 短句继承 / WP-C 改写喂路由 / WP-D 工具信号+评测 / WP-E 回归

## 1. 功能验收（WP-A 会话级路由）

- [ ] 📋 `RouterAgent.classify(self, query, history=None)`——history 为最近消息列表，**取最近 4-6 轮**（`history[-6:]`）
- [ ] 📋 `history` 为空/None → 行为与现状逐字一致（存量测试零改动）
- [ ] 📋 LLM 侧 `_CLASSIFY_PROMPT` few-shot 加"省略句/指代句结合上下文判断意图"
- [ ] 📋 L4 分类器特征 = 当前 query 向量 + 最近一轮 user query 向量（拼接 2048 维，训练同构）
- [ ] 📋 构造测试：`[知识库, "为什么"]` → knowledge；`[闲聊, "哈哈"]` → casual_chat；`[知识库, "今天天气怎么样"]` → realtime（话题漂移不继承）

## 2. 功能验收（WP-B 短句意图继承，规则层零 LLM）

- [ ] 📋 先去语气词（哦/呢/呀/啦/请问/那个/嘛/吧，规则表可配）——"为什么呀"→"为什么"
- [ ] 📋 去语气词后长度 <6 字符 且 `_deterministic_confirm` 无新特征 → **继承上一轮 intent**（history 空不继承）
- [ ] 📋 有特征（FTS 术语/图谱实体/规则表命中）→ 正常路由（防话题漂移）
- [ ] 📋 继承来源：history 最近一条 user 消息路由结果（无状态，从 history 推演；成本敏感改 engine 传 prev_intent）
- [ ] 📋 用例：`[知识库, "为什么"/"那图谱呢"/"为什么呀"]` → knowledge；`[知识库, "今天天气"]` → 正常路由；单轮短 query → 正常路由

## 3. 功能验收（WP-C 改写喂路由）

- [ ] 📋 改写后的 query（改写成功且保真通过）同时用于路由 + 检索；失败/回退用原始 query（零回归）
- [ ] 📋 改写提前到路由之前或路由内（顺序：路由需要改写结果）
- [ ] 📋 分诊命中 FTS 术语 → 短路 knowledge（可选优化，验证不破坏现状）
- [ ] 📋 用例：`"为什么"`（前文 knowledge）→ 改写为完整句 → knowledge；改写失败 → 原始 query 路由

## 4. 功能验收（WP-D 工具信号 + 评测）

- [ ] 📋 上一轮 tool_calls 含 `search_knowledge`/`generate_answer` → 本轮短 query 强制 knowledge（轨迹不可得则跳过）
- [ ] 📋 `eval/golden_multi_turn.py`：≥10 条多轮追问对 + 三指标（自包含清晰度/意图保持/检索提升）
- [ ] 📋 10 条多轮对全部意图保持；检索 Hit@5 与单轮基线相比不降

## 5. 验收（WP-E 回归）

- [ ] 📋 `tests/test_multi_turn_routing.py`（新）：WP-A 空历史零回归 + 带历史路由 + WP-B 继承 + WP-C 改写 + WP-D 工具信号 + 多轮评测
- [ ] 📋 存量测试零改动；全量 pytest **897 基线全绿 + 新增测试**
- [ ] 📋 E2E 冒烟（环境允许）：真实两轮对话——第一轮知识库问题、第二轮"为什么"，断言 intent=knowledge 走检索链路
- [ ] 📋 ADR-0015 状态行更新（✅ 已实施）；面试口径更新点落盘（多轮省略句处理）

## 6. 降级/接口兼容

- [ ] 📦 空历史 → 逐字一致零回归；改写失败/保真回退 → 原始 query
- [ ] 📦 工具轨迹不可得 → 跳过工具信号（不阻塞）
- [ ] 🔌 不新增/删意图类型（knowledge/casual_chat/realtime 三个值不动）；`_deterministic_confirm` 现有逻辑不动
- [ ] 🔌 非流式 `engine.chat` + 流式路径**都**接 history（漏一个 = chat 正常/stream 回归）

## 7. 测试验收

- [ ] 🧪 `python -m pytest tests/ -q` → 897 + N 全绿（不改存量测试掩盖）
- [ ] 🧪 mock LLM/分类器（不依赖真实 LLM 跑全量）；多轮用例用构造 history

## 8. 文档验收（含记忆硬性约束）

- [ ] 📝 changelog.md / review-report.md / test-report.md（含多轮评测三指标数字 + 空历史零回归验证）
- [ ] 📝 memory/project-context.md 追加 module-063 行 + 头部日期
- [ ] 📝 memory/agent-activity-log.md / file-index.md
- [ ] 📝 ADR-0015 状态行 ✅；CONTEXT.md 只增（多轮意图路由术语）
- [ ] 📝 开工前必读 project-context.md（Developer 在 changelog 注明已读）
