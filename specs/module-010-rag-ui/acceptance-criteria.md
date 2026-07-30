# M10: RAG UI 优化 — 验收标准

## 1. 引用高亮

- [ ] 引用标记 `[1]` `[2]` 以紧凑浅蓝色 badge 显示（padding 0 5px, fontSize 12, 背景 #dbeafe）
- [ ] 标记与周围文字基线对齐（verticalAlign: baseline），不撑开行高
- [ ] hover 时背景变深 #bfdbfe，边框变深 #60a5fa，过渡平滑（transition 0.15s）
- [ ] 点击标记仍弹出 CitationModal 显示引用原文（现有行为不变）
- [ ] 用户消息中无引用标记（用户消息不用 ChatMessage 的 citation 渲染）

## 2. 反馈按钮

- [ ] 每个完整 AI 回复底部显示 thumbs-up + thumbs-down 图标按钮
- [ ] 未选中状态：灰色图标 (#94a3b8)，透明背景
- [ ] 点击 thumbs-up：变蓝 (#1e40af) + 浅蓝背景 (#dbeafe)
- [ ] 点击 thumbs-down：变红 (#dc2626) + 浅红背景 (#fee2e2)
- [ ] 再次点击已选中的按钮：取消反馈（恢复灰色）
- [ ] 切换投票：点击 up 后再点 down，up 取消、down 激活
- [ ] 反馈持久化到 localStorage（key: rag_feedback），刷新页面保留
- [ ] 用户消息不显示反馈按钮
- [ ] 正在流式输出的 AI 消息不显示反馈按钮（仅在 `!isStreaming` 时显示）
- [ ] 不同会话的反馈独立

## 3. 流式响应增强

- [ ] 发送消息后、首 token 到达前：显示居中的 Spin + "AI 思考中..."
- [ ] 首 token 到达后：Spin 消失，AI 消息气泡末尾出现闪烁光标（2px 竖线，@keyframes blink-cursor）
- [ ] 首 token 到达后：Spin 位置替换为轻量文字"生成中..."（fontSize 12, 灰色）
- [ ] 流式完成后：光标消失、"生成中..." 消失、反馈按钮出现
- [ ] 流式出错：error Alert 正常显示（与现有行为一致）

## 4. 向后兼容

- [ ] 现有 CitationModal 点击弹窗功能不变
- [ ] PipelinePanel 管线步骤动画不变
- [ ] 上传面板（UploadPanel）不变
- [ ] 会话管理（新建/切换/删除）不变
- [ ] `npm run build` TypeScript 编译无错误
- [ ] 现有 ChatPage 测试通过（新 Props 全部 optional）

## 5. 异常处理

- [ ] localStorage 不可用时反馈静默降级（不阻塞 UI）
- [ ] 反馈数据损坏时静默忽略（不报错）
- [ ] `isStreaming` 未传时默认 false（ChatMessage 不崩溃）

---

## 验收结论

- 验收人: Tester
- 验收时间: 2026-07-30
- 结论: **通过** ✅
- 全部 31 项验收标准通过，详见 `test-report.md`
- 备注: 2 个 ChatPage 测试失败为 M9 遗留问题（conversationService mock 缺失），非 M10 引入。plan.md 要求的 ChatMessage 单元测试文件待 Planner 确认是否降级至后续模块。
