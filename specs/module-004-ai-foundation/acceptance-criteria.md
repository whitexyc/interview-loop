# 验收标准 — Module-004: Python AI 层基础架构

## 1. 功能验收
- [ ] `/ai/health` 返回 `{"status": "ok", "service": "ai-service"}`
- [ ] Python 可连接 PostgreSQL，创建 pgvector extension
- [ ] LLM 客户端支持 Claude + DeepSeek 切换
- [ ] `/ai/rag/search` 和 `/ai/rag/chat` 路由注册（返回骨架响应）
- [ ] `/ai/config` 返回当前供应商配置

## 2. 代码质量验收
- [ ] Python 命名符合 snake_case
- [ ] 异步函数使用 async/await
- [ ] 环境变量管理（非硬编码）
- [ ] 异常处理：LLM 调用失败时返回友好错误

## 3. 验证命令
| 验收项 | 命令 | 预期 |
|--------|------|------|
| Python 语法 | `cd ai_service && python -m py_compile main.py` | 无错误 |
| 启动 | `cd ai_service && python main.py` 启动后 curl /ai/health | `{"status":"ok"}` |
