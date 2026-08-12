# CONTEXT.md — 术语表

> Grill with Docs 会话产物。每次讨论涉及的术语在此登记，便于跨会话续接。

## 输入校验领域（module-042 讨论）

- **ChatRequest**：`ai_service/rag/schemas.py:18` 定义的统一请求模型，四个问答端点共用（chat / chat/stream / agent / agent-lg）。FastAPI 反序列化请求体时自动触发 Pydantic 校验。
- **Field 约束**：`Field(..., max_length=2000)` 声明式约束，违反时 Pydantic 抛 ValidationError → FastAPI 返回 **422**。
- **field_validator(mode="before")**：在校验之前处理原始值的钩子。用于 history 超条数静默截断（schemas.py:22-28）。
- **静默截断（silent truncation）**：history > 20 条时保留最近 20 条，不报错。与"拒绝（422）"相对——query 是用户当下输入所以拒绝，history 是累积旧对话所以截断。
- **422 Unprocessable Entity**：FastAPI 对请求校验失败的默认响应码，请求不进业务逻辑、不触发 LLM 调用。
- **双层防线（two-layer defense）**：入口物理校验（schemas.py，防输入不可信）+ LLM 输出校验（router.py，防 LLM 不可信）。
- **LLM 输出校验**：`agent/router.py:_parse_response` 对 LLM 返回的 JSON 做白名单校验（intent 必须 ∈ knowledge/casual_chat/realtime），非法值回退 knowledge。
- **保守路由（conservative routing）**：router.py 任何异常（LLM 失败、超时、解析失败）一律返回 knowledge 意图——"宁多检不漏检"，宁可多检索一次不放过。
- **AC 1.3 / AC 1.4**：module-042 验收标准。AC 1.3 = query>2000 字符 → 422；AC 1.4 = history>20 条 → 静默截断。测试在 `ai_service/tests/test_schemas_validation.py`。

## 相关文件索引

| 文件 | 内容 |
|---|---|
| `specs/adr/0001-two-layer-input-validation.md` | 双层防线决策记录 |
| `specs/module-042-harness-guardrails/test-report.md` | 校验验收测试报告 |
| `ai_service/rag/schemas.py:18-28` | ChatRequest 模型 + 截断 validator |
| `ai_service/agent/router.py:76-122` | LLM 输出校验 + 保守路由 |
