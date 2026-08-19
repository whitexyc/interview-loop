# Changelog — Module-039: 证据链幻觉检测

## 变更日期: 2026-08-08

## Round 1 (初始实现)

### 1. ai_service/agent/reflector.py
- 新增 `import asyncio`
- 新增 `_VERIFY_PROMPT` 常量（验证 prompt）
- 新增 `verify_answer(self, answer: str, docs: list[dict]) -> dict` 方法
  - 构造完整文档上下文 + 验证 prompt → 调用 LLM（temperature=0, 15s 超时）
  - 解析 JSON 返回到结构化 dict（claims / overall_confidence / 计数）
  - 校验 evidence 引用号越界时降级为 unsupported
  - 超时/调用失败/JSON 解析失败 → 返回空 claims
- 新增 `_parse_verification(response: str) -> list[dict]` 静态方法

### 2. ai_service/rag/engine.py
- `chat()` 方法：在 `reflector.generate_answer()` 后新增 `reflector.verify_answer(answer, docs)` 调用
- ChatResponse 返回新增 `verified_claims=verified` 字段
- 内部错误路径 ChatResponse 新增 `verified_claims=None`

### 3. ai_service/agent/tool_registry.py
- 新增 `_verify_answer(ctx, args)` 异步工具函数
- 新增 `_VERIFY_SCHEMA`（{query, answer} 均为可选 string，required: ["answer"]）
- `register_builtin_tools()` 新增第 8 个工具注册："verify_answer"
- 文档注释更新：7 → 8 个工具

### 4. ai_service/rag/schemas.py
- ChatResponse 新增 `verified_claims: Optional[dict] = None` 字段

### 5. ai_service/main.py
- `chat_stream` SSE 端点：流式答案生成后新增 Step 7 证据链验证
  - 调用 `reflector.verify_answer(full_answer, docs)`
  - 验证有结果时 yield `event: verified` SSE 事件（含 claims / overall_confidence / total_claims / supported / inferred / unsupported）
  - `event: done` 新增 `verified: true/false` + `overall_confidence` 字段

### 6. frontend/src/types/rag.ts
- 新增 `VerifiedClaim` 接口：{claim, verdict, evidence}
- ChatResponse 接口新增 `verified_claims` 可选字段

### 7. frontend/src/components/ChatMessage.tsx
- 新增 `VerifiedClaim` 类型导入
- ChatMessageProps 新增 `verifiedClaims` 可选 prop
- AI 消息气泡新增证据链验证面板：
  - 每条 claim 渲染彩色圆形 badge（绿 ✓ / 黄 ~ / 红 ✗）
  - evidence 引用号渲染为可点击 citation badge（复用 onCitationClick）
  - 底部整体置信度进度条（按置信度阈值变色：≥0.8 绿 / ≥0.5 黄 / <0.5 红）
  - 流式输出中或无 verifiedClaims 时退化纯文本渲染（向后兼容）
- 新增 `parseEvidenceRef(evidence)` 辅助函数

---

## Round 2 (Review 反馈修复)

**Review 结论: CONDITIONAL PASS — 2 blockers**

### Blocker 1: 前端 SSE handler 缺失 (FIXED)

**问题**: 后端发送 `event: verified` SSE 事件，但 `ragService.ts` `chatStream()` 无处理分支，事件被静默丢弃。

**修复文件**:

#### 1. frontend/src/services/ragService.ts
- 导入 `VerifiedClaim` 类型
- `chatStream()` 新增 `verifiedClaims` 局部变量
- 新增 `verified` 事件处理分支：检测 `Array.isArray(parsed.claims)` → 捕获 claims / overall_confidence / total_claims / supported / inferred / unsupported
- 返回 ChatResponse 时携带 `verified_claims: verifiedClaims`

#### 2. frontend/src/pages/ChatPage.tsx
- `doSend()` 中设置最后一条 assistant 消息时同时复制 `data.verified_claims`
- `handleRetry()` 中同样处理
- ChatMessage 渲染时传入 `verifiedClaims={msg.verifiedClaims}`

#### 3. frontend/src/types/conversation.ts
- 导入 `VerifiedClaim`
- `MessageDTO` 新增 `verifiedClaims?` 字段（含 claims / overall_confidence / total_claims / supported / inferred / unsupported）

### Blocker 2: 测试缺失 (ALREADY RESOLVED)

验证结果: `test_reflector.py` (13 passed) + `test_agent_tools.py` (31 passed) = 44 tests all passing。
测试文件已包含完整的 verify_answer 单元测试和工具注册测试，无需额外修改。

### 其他修复

#### ai_service/main.py
- SSE `verified` 事件数据补齐 count 字段：`total_claims`, `supported`, `inferred`, `unsupported`（前端类型对齐需要）

### Minor: _VERIFY_SCHEMA required 字段 (ALREADY FIXED)
- `"required": ["answer"]` 已存在，无需修改。

---

## 关键设计决策
1. 验证使用 temperature=0（确定性），走 fallback 降级链
2. verify_answer 在非流式路径 await 完成后再返回 ChatResponse；流式路径异步推送 verified 事件
3. verified_claims 为可选字段——旧前端无此字段时正常渲染（向后兼容）
4. Agent 工具 verify_answer 依赖 ctx.docs（当前累积的检索结果），无 docs 时返回提示
5. evidence 引用号越界自动降级 verdict → "unsupported"
