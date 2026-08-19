# 功能规格说明书 — Module-039: 证据链幻觉检测

> 本文件由 **Planner** 输出，作为模块开发的唯一权威规格文档。
> Developer 严格按本文件编码，Reviewer 和 Tester 按本文件验收。

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-039 |
| 模块名称 | 证据链幻觉检测（Claim-Level Citation Verification） |
| 版本号 | 0.39.0-module-039 |
| 优先级 | P1（RAG 答案可信度——当前引用靠 prompt engineering，无验证） |
| 预估代码量 | ≤ 200 行（reflector 80 行 + engine/main 30 行 + 前端 90 行） |
| 创建日期 | 2026-08-08 |
| 最后更新 | 2026-08-08 |
| 负责人 | Planner: 规划执行, Developer: 一次派发闭环 |

---

## 2. 需求描述

### 2.1 需求来源

- 来源类型：Agent+RAG 审计（2026-08-08）→ 证据链维度缺口
- 现状缺口：

| 能力 | 当前状态 | 缺失 |
|---|---|---|
| 引用标注 | ✅ `generate_answer` prompt 要求 `[1][2]` 标记 | 无验证——LLM 可能编造引用号 |
| 引用来源 | ✅ `sources[]` 数组返回前端 | 截断 300 字符，用户看不到完整上下文 |
| 答案可信度 | ❌ 无 | 用户不知道答案中哪句有依据、哪句是推测 |

### 2.2 用户故事

```
作为 RAG 系统的用户
我想要 看到答案中每句话的可信度标注（有依据/推测/无依据）
以便 判断哪些内容可以信任、哪些需要进一步确认
```

### 2.3 验收场景（BDD 格式）

```
场景 1：答案逐句验证
  假设 已生成一个带 [1][2] 引用的答案
  当 调 verify_answer(answer, docs)
  那么 返回每个 claim 的验证结果：supported / inferred / unsupported

场景 2：前端展示可信度
  假设 后端返回 verified_claims
  当 前端渲染答案
  那么 每句话前面显示绿/黄/红可信度色标

场景 3：全部 supported 的正常答案
  假设 答案完全基于检索文档
  当 验证
  那么 overall_confidence ≥ 0.8，无红色标注

场景 4：包含推测的答案
  假设 LLM 在文档基础上做了合理推断
  当 验证
  那么 推断部分标黄色 "inferred"，其余标绿色

场景 5：严重幻觉
  假设 LLM 编造了文档中不存在的事实
  当 验证
  那么 编造部分标红色 "unsupported"，overall_confidence < 0.5

场景 6：无文档兜底（casual_chat 路径）
  假设 闲聊路径无检索文档
  当 验证
  那么 跳过验证，不报错（零回归）

场景 7：流式端点延迟验证
  假设 走 SSE 流式
  当 答案流式输出完成
  那么 异步触发验证 → 通过新 SSE 事件推送 verified_claims

场景 8：Agent 路径独立验证
  假设 Agent ReAct 调用 generate_answer
  当 答案生成后
  那么 LLM 可主动调 verify_answer 工具检查可靠性
```

### 2.4 非功能需求

| 类别 | 要求 |
|------|------|
| 延迟 | 验证不阻塞答案流式输出；非流式路径验证并行于响应组装 |
| 复用 | 复用现有 DeepSeek 客户端，temperature=0（确定性） |
| 零回归 | 闲聊路径跳过验证；无检索文档时降级为空 claims |
| 前端兼容 | 旧 ChatMessage 无 verified_claims 时正常渲染（向后兼容） |

---

## 3. 技术方案

### 3.1 涉及文件

| 文件路径 | 操作类型 | 说明 |
|----------|----------|------|
| `ai_service/agent/reflector.py` | 修改 | 新增 `verify_answer()` 方法（LLM 逐句验证） |
| `ai_service/rag/engine.py` | 修改 | chat() 非流式路径：答案后并行调 verify_answer |
| `ai_service/agent/tool_registry.py` | 修改 | 注册 `verify_answer` 为 Agent 工具 |
| `ai_service/main.py` | 修改 | chat_stream SSE 添加 `verified` 事件 + ChatResponse 加 verified_claims 字段 |
| `ai_service/rag/schemas.py` | 修改 | ChatResponse 加 verified_claims 字段 |
| `frontend/src/types/rag.ts` | 修改 | 新增 `VerifiedClaim` / `VerificationResult` 类型 |
| `frontend/src/components/ChatMessage.tsx` | 修改 | 渲染逐句可信度色标 |
| `ai_service/tests/test_reflector.py` | 修改 | verify_answer 单元测试 |
| `ai_service/tests/test_agent_tools.py` | 修改 | verify_answer 工具测试 |

### 3.2 核心逻辑

#### 3.2.1 verify_answer() — Reflector 新增方法

```
输入:
  - answer: str（带 [N] 引用的 LLM 答案）
  - docs: list[dict]（检索到的文档，含 id/title/content）

流程:
  1. 构造验证 prompt：
     "把以下答案拆成逐条陈述（claim），每条标注：
      - claim: 原文句子
      - verdict: supported（文档中有直接依据）
                | inferred（基于文档的合理推断）
                | unsupported（文档中无依据）
      - evidence: 引用文档编号 [N]（supported/inferred 时填写；
                   unsupported 时写 "N/A"）
      返回 JSON 数组"

  2. 调 LLM（temperature=0）→ 解析 JSON

  3. 校验：
     - 每个 claim 的 evidence 引用号是否在 docs 范围内
     - unsupported claim 占比 (overall_confidence = 1 - unsupported_ratio)
     - 返回结构化 VerificationResult

输出: VerificationResult {
  claims: [{claim, verdict, evidence}],
  overall_confidence: float (0.0-1.0),
  total_claims: int,
  supported: int, inferred: int, unsupported: int,
}
```

#### 3.2.2 engine.py chat() — 非流式路径

```
现状:
  answer = await reflector.generate_answer(query, docs, ...)
  sources = [...]
  return ChatResponse(answer=answer, sources=sources, message="ok")

改后:
  answer = await reflector.generate_answer(query, docs, ...)
  # 并行触发验证（不阻塞 answer 返回，但 await 后再组装 response）
  verified = await reflector.verify_answer(answer, docs)
  sources = [...]
  return ChatResponse(answer=answer, sources=sources, verified_claims=verified, message="ok")
```

#### 3.2.3 main.py chat_stream — SSE 流式路径

```
现状: Step 6 调用 reflector.generate_answer → 逐 token yield
改后:
  - Step 6: 流式输出 answer（同现状）
  - Step 7 (新增): 流结束后异步调 verify_answer → yield "verified" SSE 事件
  - 事件格式: {"type": "verified", "claims": [...], "overall_confidence": 0.85}
```

#### 3.2.4 tool_registry.py — Agent 工具注册

```
新增 verify_answer 工具:
  - name: "verify_answer"
  - description: "逐句验证已生成答案是否被检索文档支持，标注可信度"
  - args: {query, answer}  # answer 从 ReactContext 或参数获取
  - 实现: 调 reflector.verify_answer(ctx.docs 或参数 docs)
  使 Agent 在 generate_answer 后可主动检查回答质量
```

#### 3.2.5 前端 ChatMessage.tsx

```
现状: 直接渲染 markdown 答案文本
改后:
  - 若 verified_claims 存在 → 渲染逐句可信度
    - 🟢 green dot: supported + evidence 引用可点击跳转
    - 🟡 yellow dot: inferred
    - 🔴 red dot: unsupported
  - 若 verified_claims 不存在 → 退化为纯文本渲染（向后兼容）
  - 底部显示 overall_confidence 进度条
```

### 3.3 验证 Prompt 设计

```
你是 RAG 系统的答案验证专家。检查以下答案是否被检索文档支持。

## 检索文档
{docs_text}

## 待验证答案
{answer}

## 任务
1. 把答案拆成独立的陈述句（claims），每条 1-2 句话
2. 对每条陈述判断：
   - "supported": 文档中有直接文字依据
   - "inferred": 没有直接文字，但可以从文档合理推断
   - "unsupported": 文档中找不到依据
3. 对 supported/inferred，填写 evidence 字段（关联文档编号，如 "[1]"）
4. 只返回 JSON 数组，不要其他文字

格式：[{"claim": "...", "verdict": "supported|inferred|unsupported", "evidence": "[1]"}]
```

### 3.4 关键设计决策

| 决策 | 说明 |
|------|------|
| temperature=0 | 验证需确定性，不引入随机性 |
| 非流式路径 await 验证 | 非流式用户期望完整结果，验证需在返回前完成 |
| 流式路径异步推送 | 不阻塞 answer token 流，验证结果通过额外 SSE 事件推送 |
| claim 粒度 | 1-2 句一个 claim，太细 LLM 分不准，太粗无意义 |
| 向后兼容 | verified_claims 为可选字段，前端 fallback 纯文本 |

### 3.5 异常处理

| 异常场景 | 处理方式 |
|----------|----------|
| 无检索文档（casual_chat） | 跳过验证，verified_claims=None |
| LLM 验证调用失败 | 降级：返回空 claims，不阻塞答案返回 |
| JSON 解析失败 | 降级：返回空 claims + logger.warning |
| evidence 引用号越界 | claim.verdict 降级为 "unsupported" |
| 验证超时（>15s） | asyncio.wait_for，超时返回空 claims |

### 3.6 跨模块契约

```
- ChatResponse 新增可选字段 verified_claims（不影响旧前端）
- SSE 新增 "verified" 事件类型（旧前端忽略未知事件）
- Agent 新增 verify_answer 工具（不影响现有 7 个工具）
- 现有 evaluate.py / faithfulness.py 的评估逻辑不变
```

---

## 4. 验收标准

> 详细验收标准见同目录下的 `acceptance-criteria.md`

### 4.1 可运行的验证命令

```bash
cd ai_service
python -m pytest tests/test_reflector.py -q
python -m pytest tests/test_agent_tools.py -q
python -m pytest tests/ -q   # 全量回归
```

### 4.2 预期输出

```
新增单测全过；全量基线 + 新增通过 / 0 失败
E2E：chat 问答 → 答案含 verified_claims → 前端展示可信度色标
```

---

## 5. 依赖关系

### 5.1 上游依赖

| 依赖 | 说明 | 状态 |
|------|------|------|
| module-028 | ReactContext / ToolRegistry / Agent 工具框架 | ✅ |
| module-004 | Reflector / generate_answer | ✅ |
| module-005 | RAG engine / chat() / chat_stream | ✅ |
| module-006 | 前端 ChatMessage / CitationModal | ✅ |

### 5.2 下游依赖

- 无（本模块是增量功能，不改契约）

---

## 6. 风险点与注意事项

### 6.1 已知风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| LLM 验证本身不准确 | 误标 supported/unsupported | 中 | temperature=0 + prompt 要求引用 document 编号 |
| 验证增加延迟 | 非流式用户感知慢 | 低 | verify_answer 单次 LLM 调 ~1-2s |
| 前端新增类型破坏旧渲染 | ChatMessage 崩溃 | 低 | verified_claims 为可选字段，缺省时退化 |

### 6.2 技术注意事项

- [x] `reflector.generate_answer` 已存在（module-004）
- [x] `ChatResponse` schema 在 `rag/schemas.py`
- [ ] 验证 prompt 需含完整文档内容（非截断 300 字），否则 LLM 无法判断
- [ ] Agent 路径的 verify_answer 工具需访问 ctx.docs（当前累积的检索结果）
- [ ] 前端渲染需处理 markdown 混合 trusted claim 标注

---

## 7. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-08 | 初始版本 | Planner |

---

## 8. 审批记录

| 角色 | 姓名 | 审批结果 | 日期 | 备注 |
|------|------|----------|------|------|
| Planner | 规划执行 | ✅ 通过 | 2026-08-08 | |
| Reviewer | | ⏳ 待审查 | | |
| Tester | | ⏳ 待测试 | | |

---

> **下一步**：Developer 根据本规格说明书开始编码实现。
