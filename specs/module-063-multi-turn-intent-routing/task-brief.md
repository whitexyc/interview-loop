# Module-063 Task Brief：多轮对话意图路由升级

> 自包含执行简报。接手方不需要额外对话上下文，按步骤执行即可。所有"已知事实"均已确认（代码已读），无需重新调研。
> 决策依据见 `specs/adr/0015-multi-turn-intent-routing.md`，本简报是执行层（怎么落地）。

## 一、背景与问题（代码实测）

- `engine.py:237`：`intent_result = await router_agent.classify(request.query)`——**只传当前这一句，会话历史没有进意图路由**
- `router.py:203`：`async def classify(self, query: str) -> dict` 签名无 history 参数
- 历史已在请求里（`engine.py:230` 日志 `history=%d`）、也用于生成侧（`engine.py:258` `*request.history`）——**路由阶段是唯一没吃历史的一环**
- 后果：多轮对话中"为什么""那图谱呢"这类省略句/指代句，单句无特征 → 大概率误判 `casual_chat` 或 `realtime`，走错分支

## 二、范围

WP-A 会话级路由（半天）→ WP-B 短句意图继承（2 小时）→ WP-C 改写喂路由（1 天）→ WP-D 工具历史信号 + 评测（半天）→ WP-E 回归验收。

**不做**：不新增/不删意图类型；不动 `_deterministic_confirm` 现有逻辑（只在其上加"无特征"判断）；不改生成侧历史注入（已在用）。

## 三、WP-A 会话级路由

- `RouterAgent.classify(self, query: str, history: Optional[list] = None) -> dict`
  - `history` 为最近 N 轮消息列表（`[{"role": "user"/"assistant", "content": ...}]`），**取最近 4-6 轮**（`history[-6:]` 取后 6，路由内部用最后 4-6 轮，业界共识 3-8 轮）
  - `history` 为空/None → 行为与现状逐字一致（零回归）
- LLM 侧（`_CLASSIFY_PROMPT` 或等价）：few-shot 加一条"若当前 query 是省略句/指代句（如'为什么''那它呢'），结合最近对话上下文判断意图，而不是只看字面"
- L4 分类器（bge-m3+LR）：特征 = 当前 query 向量 **+ 最近一轮 user query 向量**（拼接 2048 维，训练时同构；`memory_type_clf` 已有"两条拼接"先例可参考 `memory_conflict_clf.py`）
- **通过标准**：
  1. 空 history 时与改动前逐字一致（存量测试零改动）
  2. 构造测试：`[知识库问题, "为什么"]` → intent=knowledge；`[闲聊, "哈哈"]` → casual_chat；`[知识库问题, "今天天气怎么样"]` → realtime（话题漂移不继承）

## 四、WP-B 短句意图继承（规则层，零 LLM）

- 位置：`classify()` 内部、LLM/分类器调用**之前**的判断（低成本短路）
- 规则：
  1. 先**去语气词**（中文：哦/呢/呀/啦/请问/那个；规则表可配）——"为什么呀"→"为什么"
  2. 若去除后 **长度 < 6 字符**（或 < 3 个词）**且** `_deterministic_confirm` 判定**无新特征**（FTS 术语未命中、图谱实体未命中、规则表未命中）→ **继承上一轮 intent**（取 history 最近一条 user 消息的路由结果；history 为空则不继承）
  3. 有特征（命中 FTS/图谱/规则）→ 必须走正常路由（防话题漂移）
- 状态：需要路由结果可回看——`engine.py` 在路由调用处维护 `last_intent`（会话内），或从 `request.history` 推演（**优先后者，无状态**：history 里最近一条 user 消息就是上一轮 query，路由一次即可——注意这多一次调用，评估后定：若成本敏感，改 engine 传 `prev_intent` 参数）
- **通过标准**：
  - `[知识库, "为什么"]` → knowledge（继承）
  - `[知识库, "那图谱呢"]` → knowledge
  - `[知识库, "为什么呀"]` → knowledge（去语气词后触发）
  - `[知识库, "今天天气"]` → 正常路由（>6 字符 or 有新特征）
  - 单轮（无 history）短 query → 走正常路由（不继承，无上轮可继承）

## 五、WP-C 复用分诊式改写喂路由（⭐ 核心增量）

- **关键洞察**：现有分诊式改写（FTS 术语静态分诊 → 模糊才 LLM 改写 → 保真预检余弦回退 → 原/改写并行择优）**就是业界 Hybrid 改写标准形态**——不是新增能力，是"改写结果多喂一个消费方"
- 改动：`engine.py` 检索链里，**改写后的 query（若有）同时用于：① 路由判断 ② 检索**——路由用 `rewritten_query`（改写成功且保真通过时），失败/回退用原始 query
- 现有改写链路位置：`query_rewrite`（retrieval 子包）——先在路由调用点确认改写是否已执行；**若改写发生在路由之后**，则调整为"改写提前到路由之前"（顺序：意图路由需要改写结果 → 改写必须在路由前或路由内）
  - 实施提示：改写是"要不要改写"的分诊判断（FTS 术语命中 → 不改写直接走），意图路由可以**先分诊、后路由**——分诊命中术语 → 大概率 knowledge → 直接短路路由（省一次 LLM 路由调用）
- **通过标准**：
  1. `"为什么"`（前文 knowledge）→ 改写为完整句 → 路由 knowledge
  2. 改写失败/保真回退 → 原始 query 路由，行为与现状一致
  3. 分诊命中 FTS 术语 → 短路为 knowledge（可选优化，验证不破坏现状）

## 六、WP-D 工具历史规则信号 + golden 多轮评测

- **工具历史**（规则层，2 小时）：上一轮 tool_calls 含 `search_knowledge`/`generate_answer`（可从 request 的 agent 轨迹取，若不可得则跳过此项）→ 本轮短 query 强制 knowledge
- **评测**（golden 扩展）：`eval/golden_retrieval.py` 或新增 `eval/golden_multi_turn.py`——构造 ≥10 条多轮追问对（如 `[Q1 知识库题, "为什么"]`, `[Q1, "那图谱呢"]`），三指标：**自包含清晰度**（改写后 query 是否可独立理解）/ **意图保持**（改写前后 intent 一致）/ **检索提升**（改写后检索 Hit@5 不降）
- **通过标准**：10 条多轮对全部意图保持；检索 Hit@5 与单轮基线相比不下降

## 七、WP-E 回归验收

- 全量 pytest **897 基线全绿 + 新增测试**（不破坏现状：默认行为零回归、存量测试不改）
- 新增测试文件建议：`tests/test_multi_turn_routing.py`（WP-A 空历史零回归 + 带历史路由 + WP-B 继承规则 + WP-C 改写喂路由 + WP-D 工具信号 + golden 多轮评测）
- E2E 冒烟（环境允许）：真实 HTTP 两轮对话——第一轮知识库问题，第二轮"为什么"，断言 intent=knowledge 且走检索链路

## 八、纪律项

1. **存量测试零改动**：classify 默认参数（history=None）保证空历史行为不变
2. **两条路径同改**：非流式 `engine.chat`（:237 附近）与流式路径（engine.py 检索链）都要接 history——漏一个就是"chat 正常、stream 回归"
3. **不改意图类型定义**：knowledge/casual_chat/realtime 三个值不动
4. **改写保守**：保真预检回退必须保留（防 over-rewriting，业界第一翻车原因）
5. **历史不全塞**：路由只用最近 4-6 轮，不是全部 50 条
6. **中文语气词规则表**：先做最常用 5-8 个（哦/呢/呀/啦/请问/那个/嘛/吧），不追求全

## 九、交付物

1. WP-A~D 全部代码 + 单测（`test_multi_turn_routing.py`）
2. golden 多轮评测对 ≥10 条 + 三指标结果表
3. changelog.md（WP 逐项 + 测试数：897 基线 + 新增 N）
4. 面试口径更新点（08 文档意图路由节：加"多轮省略句处理"段；ADR-0015 状态行标 ✅）
5. 全量回归记录

## 十、验收标准（最终）

- [ ] 897 基线全绿 + 新增测试全绿
- [ ] 空历史行为与改动前逐字一致（存量测试零改动验证）
- [ ] 多轮省略句（"为什么"/"那图谱呢"/"为什么呀"）在 knowledge 前文下 → knowledge（单测 + E2E 冒烟）
- [ ] 话题漂移（"今天天气"）不被继承，正常路由
- [ ] 改写喂路由：改写成功走改写、失败回退原始，路由结果语义等价
- [ ] golden 多轮评测 10 条意图保持 100%、检索不降
