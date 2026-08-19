# 验收标准 — Module-048: 反馈飞轮 + 前端防护 + 硬闸门阈值

> 图例：📋 功能 / 📦 降级 / 🔌 接口 / 🧪 测试 / 📝 文档

## 1. 功能验收（WP1 后端反馈）

- [ ] 📋 feedback 表存在（id/message_id/rating/comment/identity/created_at）
- [ ] 📋 POST /ai/feedback 端点：rating=±1 落库成功返回 200；rating 非法（0/2）→ 422
- [ ] 📋 comment 可选 ≤500 字符（超长 422）
- [ ] 📋 identity 从 request.state 取（user_id 优先 client_ip 兜底）

## 2. 功能验收（WP2 前端反馈）

- [ ] 📋 ChatMessage 每条 AI 回复下方 👍👎 按钮
- [ ] 📋 点击后调 POST /ai/feedback + Toast 确认（成功"感谢反馈"）
- [ ] 📋 已反馈消息按钮变已评态（不重复提交）
- [ ] 📋 历史消息无 message_id → 按钮隐藏/禁用

## 3. 功能验收（WP3 前端 maxlength）

- [ ] 📋 输入框 maxLength={2000}（超长无法输入）

## 4. 功能验收（WP4 硬闸门阈值 0.55）

- [ ] 📋 config 新增 sufficiency_gate_threshold（默认 0.55，PW_ 前缀）
- [ ] 📋 reflector.py check_sufficiency 硬闸门读配置（不再硬编码 0.4）
- [ ] 📋 测试更新：abs_cosine 0.45 → 直接不充分（旧 0.4 下会走 LLM）

## 5. 功能验收（WP5 白名单防御）

- [ ] 📋 probs 缺 knowledge 键不抛 KeyError（回退默认置信度）

## 6. 降级验收

- [ ] 📦 feedback 落库失败 → 500 + 前端 Toast 失败提示，聊天不受影响
- [ ] 📦 前端 API 失败 → 按钮可重试，不阻塞
- [ ] 📦 全量 pytest 525 全绿保持

## 7. 接口兼容

- [ ] 🔌 ChatResponse / 现有端点不变
- [ ] 🔌 check_sufficiency 返回结构不变
- [ ] 🔌 前端既有功能不变（构建通过）

## 8. 测试验收

- [ ] 🧪 tests/test_feedback.py：端点落库/校验/identity/降级
- [ ] 🧪 test_reflector.py 适配阈值配置（0.55 语义）
- [ ] 🧪 python -m pytest tests/ -q — 全量 525+ 全绿
- [ ] 🧪 前端 npm run build（或 tsc）通过

## 9. 文档验收

- [ ] 📝 changelog.md / review-report.md / test-report.md
- [ ] 📝 记忆文件更新
- [ ] 📝 飞轮数据说明（feedback 表是层 4 重训数据源）
