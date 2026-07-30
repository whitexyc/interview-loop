# 验收标准 — Module-005: Agentic RAG 知识库核心

## 1. 功能验收
- [ ] 文档向量化：调用 embedding 服务写入 pgvector
- [ ] 混合检索：BM25 全文检索 + 向量检索加权融合
- [ ] Rerank：Top 20 → Top 5 重排
- [ ] 意图路由：知识库查询/闲聊/实时数据分类
- [ ] 自我反思：检索不充分时自动改写 Query 二次检索
- [ ] 引用溯源：回答附带原文片段和文档 ID
- [ ] `/ai/rag/chat` 完整链路通过

## 2. 边界条件验收
- [ ] 知识库为空时返回友好提示
- [ ] 闲聊意图不走检索，直接 LLM 回答
- [ ] 二次检索仍不充分时如实告知

## 3. 验证命令
| 验收项 | 命令 | 预期 |
|--------|------|------|
| 语法检查 | `cd ai_service && python -m py_compile main.py` | 无错误 |
| 单元测试 | `cd ai_service && python -m pytest tests/` | 全部通过 |
