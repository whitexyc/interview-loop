# 验收标准 — Module-040: Adaptive RAG

## 1. 功能验收
- [x] 📋 re_search 注册为第 9 个 Agent 工具 — list_tool_names() 含 "re_search"
- [x] 📋 re_search 检索不足时改写重查 — check_sufficiency 返回 false → 用 rewritten_query 检索
- [x] 📋 re_search 检索充分时跳过 — 返回"当前检索结果已充分"
- [x] 📋 重检结果累积到 ctx.docs — 去重追加
- [x] 📋 ReAct 系统提示词含 re_search 使用规则

## 2. 降级验收
- [x] 📦 check_sufficiency 失败时降级 — 不抛异常
- [x] 📦 改写后检索无结果 — 返回提示
- [x] 📦 无 ctx.docs 时调 re_search — 提示先检索

## 3. 接口兼容
- [x] 📦 现有 8 个工具不变 — regression 全绿
- [x] 📦 react_loop 行为不变 — 零回归

## 4. 测试验收
- [x] 🧪 re_search 工具注册测试
- [x] 🧪 re_search sufficiency check 测试
- [x] 🧪 python -m pytest tests/ -q — 全量 + 新增 / 0 新增失败（320 passed, 1 预存失败）

## 5. 文档验收
- [x] 📝 changelog.md / review-report.md / test-report.md
- [x] 📝 记忆文件更新（rag-architecture.md / rag-agent-roadmap.md）
