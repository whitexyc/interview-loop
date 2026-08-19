# 验收标准 — Module-042: Harness 围栏

## 1. 功能验收
- [x] 📋 AgentTool.run 含 15s 超时 — asyncio.wait_for 包裹 → passed
- [x] 📋 工具超时返回提示 — "(工具 X 执行超时)" 不抛异常 → passed
- [x] 📋 ChatRequest.query max_length=2000 — 超长返回 422 → passed
- [x] 📋 ChatRequest.history max_length=20 — 超条数截断 → passed

> 上限依据（2026-08-08 grill 确认）：2000 字符 ≈ 中文 650 字问题，正常提问远达不到，
> 拦截对象是长文粘贴 / token 滥用；20 条 ≈ 10 轮对话，覆盖常见多轮追问。
> 目的仅为防滥用，非业务需求推导。
- [x] 📋 答案 >10000 字符截断 — 末尾加"[答案过长，已截断]" → passed

## 2. 降级验收
- [x] 📦 工具超时不阻塞 loop — LLM 可继续 → passed
- [x] 📦 现有一切工具行为不变 — 短耗时工具不受影响 → passed
- [x] 📦 截断不丢 sources — sources 完整返回 → passed

## 3. 接口兼容
- [x] 📦 ChatRequest 旧字段不变 — query + history 保持 → passed
- [x] 📦 短 query/少 history 不受影响 → passed

## 4. 测试验收
- [x] 🧪 工具超时测试 + ChatRequest 校验测试 + 答案截断测试 → passed
- [x] 🧪 python -m pytest tests/ -q — 全量 355 pass, 3 pre-existing failures (none from module-042) → passed

## 5. 文档验收
- [x] 📝 changelog.md / review-report.md / test-report.md → passed
