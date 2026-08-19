# 验收标准 — Module-041: Agent 工作记忆 Scratchpad

## 1. 功能验收
- [x] 📋 ReactContext.scratchpad 字段存在 — 初始化为空列表
- [x] 📋 note_to_self 注册为第 10 个 Agent 工具 — list_tool_names() 含 "note_to_self"
- [x] 📋 note_to_self 写入 scratchpad — ctx.scratchpad 追加笔记
- [x] 📋 generate_answer 读取 scratchpad — prompt 含"[工作笔记]"段
- [x] 📋 空 scratchpad 零回归 — generate_answer 行为不变
- [x] 📋 ReAct 系统提示词含 note_to_self

## 2. 降级验收
- [x] 📦 空内容 note — 返回提示
- [x] 📦 note 过长自动截断 — 500 字上限
- [x] 📦 ReactContext 无 scratchpad 时 generate_answer 不抛异常

## 3. 接口兼容
- [x] 📦 现有工具不变 — regression
- [x] 📦 react_loop 行为不变
- [x] 📦 verify_answer 不受影响

## 4. 测试验收
- [x] 🧪 note_to_self 工具注册 + 执行测试
- [x] 🧪 与 module-039 verify_answer 共存测试
- [x] 🧪 python -m pytest tests/ -q — 全量 + 新增 / 0 失败

## 5. 文档验收
- [x] 📝 test-report.md
- [ ] 📝 changelog.md / review-report.md
- [ ] 📝 记忆文件更新
