# 功能规格说明书 — Module-063: 多轮对话意图路由升级

> 本文件由 **Planner** 输出。执行简报见同目录 `task-brief.md`（WP-A~E 完整步骤），决策依据见 `specs/adr/0015-multi-turn-intent-routing.md`。

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-063 |
| 模块名称 | 多轮对话意图路由升级（会话级路由 + 短句继承 + 改写复用） |
| 优先级 | P1（多轮体验核心缺口，ADR-0003 intent 校验演进） |
| 预估代码量 | 功能代码约 150-200 行 + 测试约 200-300 行（含注释/测试总约 500-700 行） |
| 创建日期 | 2026-08-13（task-brief/ADR 已立项） |
| 最后更新 | 2026-08-14 |
| 负责人 | Planner: 主会话, Developer: vibe-coding-workflow |

---

## 2. 需求描述

### 2.1 问题（代码实测）

- `engine.py:237`：`router_agent.classify(request.query)` **只传当前一句**，会话历史没进意图路由
- `router.py:203`：`classify(self, query)` 签名无 history 参数
- 后果：多轮对话中"为什么""那图谱呢"这类省略句/指代句，单句无特征 → 误判 `casual_chat`/`realtime`，走错分支

### 2.2 验收场景（BDD）

```
场景 1：省略句继承
  假设 上一轮是知识库问题（"什么是Java线程池"，intent=knowledge）
  当 用户说"为什么"（<6 字符、去语气词、无新特征）
  那么 继承 knowledge，走检索链路（不误判闲聊）

场景 2：话题漂移不继承
  假设 上一轮是知识库问题
  当 用户说"今天天气怎么样"（正常长度或有实时特征）
  那么 正常路由（realtime），不继承 knowledge

场景 3：改写喂路由
  假设 前文知识库问题，用户说"为什么"
  当 分诊式改写把"为什么"改写成自包含 query
  那么 路由按改写后 query 判 → knowledge，检索也受益

场景 4：空历史零回归
  假设 无 history（首次对话）
  当 任意 query
  那么 classify 行为与改动前逐字一致（存量测试零改动）
```

### 2.3 范围

**做**：WP-A 会话级路由、WP-B 短句意图继承（规则层）、WP-C 改写喂路由、WP-D 工具历史信号 + golden 多轮评测、WP-E 回归。
**不做**：不新增/删意图类型；不动 `_deterministic_confirm` 现有逻辑（只在其上加"无特征"判断）；不改生成侧历史注入。

---

## 3. 技术方案（详见 task-brief）

### 3.1 涉及文件

| 文件路径 | 操作 | 说明 |
|----------|------|------|
| `ai_service/agent/router.py` | 修改 | `classify(query, history=None)` + 短句继承规则 + few-shot 加上下文判断 |
| `ai_service/agent/intent_classifier.py` | 修改 | L4 分类器特征拼接最近一轮 user query 向量（2048 维，训练同构） |
| `ai_service/rag/engine.py` | 修改 | 路由调用点传 history（:237 附近）；改写喂路由（改写提前/喂路由）；工具历史信号 |
| `ai_service/eval/golden_multi_turn.py` | 新增 | golden 多轮追问题型 ≥10 条 + 三指标（自包含/意图保持/检索提升） |
| `ai_service/tests/test_multi_turn_routing.py` | 新增 | WP-A~D 单测 |
| `ai_service/src/config.py` | 修改 | 中文语气词规则表 + 相关开关（如需） |

### 3.2 WP 拆解（通过标准见 task-brief §三~七）

- **WP-A 会话级路由**：`classify(query, history=None)`，history 取最近 4-6 轮；空 history 逐字一致；LLM few-shot + L4 特征拼接
- **WP-B 短句意图继承**：去语气词 → 长度 <6 且 `_deterministic_confirm` 无新特征 → 继承上一轮 intent（零 LLM）
- **WP-C 改写喂路由**：改写结果同时喂路由 + 检索；保真回退保留；分诊命中术语短路 knowledge（可选）
- **WP-D 工具历史信号 + 评测**：上轮 search_knowledge/generate_answer → 短 query 强制 knowledge；golden 多轮 10 条三指标
- **WP-E 回归**：897 基线全绿 + 新增测试

---

## 4. 风险与注意

| 风险 | 缓解 |
|------|------|
| 历史全塞拖慢路由 | 只用最近 4-6 轮（task-brief §八.5） |
| 改写 over-rewriting | 保真预检余弦回退保留（task-brief §八.4，业界第一翻车原因） |
| 话题漂移被继承 | 继承只对"极短且无新特征"query；正常长度必须重新路由 |
| 两条路径漏改 | 非流式 engine.chat + 流式检索链都要接 history（task-brief §八.2） |
| 存量测试漂移 | classify 默认参数 history=None 保证空历史零回归 |

---

## 5. 变更记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1 | 2026-08-14 | 初始（基于用户已写 task-brief + ADR-0015 补齐规格） |
