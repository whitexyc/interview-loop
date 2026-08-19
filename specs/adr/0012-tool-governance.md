# ADR-0012：工具治理与分层工具选择

## 元信息

- 状态：✅ **P1 已实施（并入 module-058 执行，2026-08-13）**——10 个工具按执行阶段切分：检索组 7 / 生成组 4（re_search 双组），ctx.phase 状态机单向前进，react_loop + langgraph_react_loop 同步改造，PW_TOOL_PHASE_SPLIT 默认 true（false 回退全量）；测试 18 项 + 两循环真实 E2E 冒烟 + 全量 pytest 780/0（详见 specs/module-058-retrieval-chain-opt/changelog.md）
- 日期：2026-08-12（P1 立项：2026-08-13）
- 关联：module-028（ToolRegistry）、agent/react.py（ReAct 循环）、module-030（langgraph_react.py）、ADR-0011（prompt 评估）

## 背景：现状（代码实测，2026-08-13 同步 worktree-m8-knowledge-panel 后复核）

- 工具：`ToolRegistry` 注册 **10 个工具**（search_knowledge / search_fts / search_vector / search_graph / extract_entities / recall_memory / generate_answer / verify_answer / re_search / note_to_self），每个含 name + description + args_schema（JSON Schema）
- **复核记录**：08-13 凌晨曾按同步前代码误判"仅 7 个工具、ADR 口径不符"；同步 worktree 合并（b42da5d）后确认 **10 个工具与原文一致**——verify_answer（module-039 逐句验证，需 docs+answer）、re_search（module-040 充分性检查+改写重检，依赖已有 docs）、note_to_self（module-041 工作笔记 scratchpad）均为已注册工具
- 暴露方式：`react.py:213` `client.chat_with_tools(messages, tools.to_llm_schemas())`——**一次性全量暴露 10 个**给 LLM；main.py 另有 langgraph_react_loop（:643，langgraph_react.py:89 同款全量暴露，module-030）共用同一 registry
- 调用时机（ReAct 循环）：LLM 每轮推理 → 返回 tool_calls → 预算内执行（`allowed = tool_calls[:budget - tool_count]`）→ 结果回传 → 无 tool_calls 则输出答案结束；工具 15s 超时、失败返回空串（降级哲学）
- 注册表无状态：全局单例只存定义，执行时注入 ctx（query/identity/history/docs/记忆/scratchpad），多会话并发安全

## 动机：工具数量会毒害选择准确率（业界硬数据）

| 工具数量 | LLM 选对工具准确率 |
|---|---|
| ~50 | 84–95%（安全区） |
| 200 | 41–83%（看模型） |
| 740 | 接近 0% |

- **Lost in the Middle 效应**：工具列表中间位置最容易被漏选（中间段准确率 22–52% vs 两端 31–32%）
- 退化非线性：特定阈值（如 207→417）会骤降
- 结论：工具少时全量暴露成立；工具多时必须分层

## 方案（按工具量级分三档）

### A. 按执行阶段切分工具集（⭐ 当前最适配，半天可做 → 已立项 module-059）
- 检索阶段（未生成）只暴露：search_knowledge / search_fts / search_vector / search_graph / extract_entities / recall_memory / re_search（7 个）
- 生成阶段（已生成）只暴露：generate_answer / verify_answer / note_to_self / **re_search（双组：验证不充分时生成阶段重检）**（4 个）
- **阶段判定（2026-08-13 设计定稿）**：以"**是否已调用过 generate_answer 或 verify_answer**"为界（`ctx.phase` 状态机），**不是**"ctx.docs 非空"——后者会切断"生成后发现不足→再补检"能力；切换**单向前进**（generation 内调 re_search 不回退，防死循环）
- **归组依据（代码语义）**：verify_answer 需 docs+answer → 生成组；re_search 实现要求已有 docs（tool_registry.py 无 docs 返回"尚未检索"）→ 本质是"反思-重检"工具 → **双组**（初次检索不足 + 生成后验证不充分两个时机都要用）；note_to_self 无前置依赖 → 生成组（草稿纸，可选双组）
- 收益：省 schema token、提准确率、**结构性防止检索阶段误调 generate_answer/verify_answer**（现靠工具内部字符串防御"尚未检索"，升级为阶段隔离）
- 实现：registry 工具加 `group` 属性 + `to_llm_schemas(group=...)` 过滤，react.py 与 langgraph_react.py 按 `ctx.phase` 选组；`PW_TOOL_PHASE_SPLIT` 开关（默认 true，false 回退全量）

### B. 分组 + 路由层（工具 20-50 个时）
- 两级：第一级 ToolRouter 选类别（规则 / embedding / LLM 小调用），第二级只暴露该类工具
- **聪明变体（零成本）**：复用现有意图路由——intent 直接决定工具组（knowledge → 检索+生成组；casual_chat → 零工具直接生成）
- 要点：类别语义最大区分（聚类后重写描述）；路由失败 fallback 全量；第二级工具 description 可写更细（实测 description 精确度提升参数准确率 30%+）

### C. 动态工具检索（工具 50+ 时）
- 工具 description 向量化存 pgvector（**复用项目 RAG 基建**）→ 每次请求 query embedding 检索 top-k（5-8 个）注入
- 业界：语义路由准确率 **86.4%** vs 全量 <50%；**MCP-Zero**（2025）2797 工具中 token 消耗 -98%；**AutoTool**（AAAI 2026）工具调用惯性图结构预测，推理成本 -30%
- 组合工具问题：单次 top-k 可能同类扎堆，需按使用历史/图结构补互补工具

## 决策表

| | A 阶段切分 | B 分组路由 | C 动态检索 |
|---|---|---|---|
| 工具量级 | 10-20 | 20-50 | 50+ |
| 路由方式 | 状态机（ctx.phase） | 类别路由 | embedding 检索 |
| 额外延迟 | 零 | 低 | 低（可缓存） |
| 复杂度 | 最低 | 中 | 中高 |
| 本项目动作 | ✅ module-058 已实施（P1） | 🟡 可复用 intent 路由 | 🔬 50+ 再上 |

## 实施顺序（本项目）

1. **P1 · 方案 A**（✅ 已实施，module-058 并入执行，2026-08-13）：10 工具分"检索组 7 / 生成组 4（generate_answer + verify_answer + note_to_self + re_search 双组）"，react.py + langgraph_react.py 按 ctx.phase 状态机暴露——省 token + 阶段隔离 + 防误调；测试 18 项 + 两循环真实 E2E 冒烟 + 全量 pytest 780/0
2. **P2 · 方案 B 变体**：intent 路由决定工具组（knowledge/casual_chat 分流，casual_chat 零工具直接生成）
3. **P3 · 方案 C**：工具扩到 50+ 后，工具 description 入库 pgvector，query 检索 top-k 注入

## 面试话术

> "我目前 10 个工具全量暴露——10 个在业界安全阈值内（50 个工具内选择准确率还有 84-95%）。但我做了未雨绸缪的**阶段切分**：检索阶段只暴露 7 个检索工具（含 re_search 重检）、生成阶段只暴露 generate_answer / verify_answer / note_to_self + re_search 补检口，用状态机按'是否已调用过生成'切换——省 token、结构性防误调（检索阶段根本调不到生成工具，而不是靠工具内部字符串防御）。同时我清楚工具数量会毒害选择准确率：200 个工具掉到 41-83%、740 个接近零，还有 Lost in the Middle 效应（列表中间的工具最容易被漏选）。所以升级方向按量级分三档：工具多起来后，20-50 个用分组路由（第一级选类别、第二级暴露该类，可复用我的意图路由）；50+ 用动态工具检索（工具 description 向量化进 pgvector，query 检索 top-k 注入——业界语义路由 86.4% vs 全量 <50%，MCP-Zero 在 2797 个工具里省 98% token）。核心认知：'全量暴露'只在工具少时成立。"
