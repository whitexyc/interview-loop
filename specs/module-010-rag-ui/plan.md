# M10: RAG UI 优化 — 项目计划

## 元信息

| 字段 | 值 |
|------|-----|
| 模块编号 | M10 |
| 模块名称 | RAG UI 优化（Citation + Feedback + Streaming） |
| 版本号 | 0.10.0-module-010 |
| 创建日期 | 2026-07-30 |
| 前置模块 | M9 |
| 范围 | 前端 only |
| 目标 | 引用琥珀色高亮+tooltip、AI回复赞/踩反馈、流式token batching+打字光标 |

## Agent 配置

| 角色 | 实例数 | 职责 |
|------|--------|------|
| Developer-Frontend | ×1 | React 前端专项开发 |
| Reviewer | ×1 | 代码审查 |
| Tester | ×1 | 前端测试 |

---

## 1. 需求概述

### 1.1 当前状态
- **引用**：`ChatMessage.tsx` 用 `<Tag color="#1e40af">`，padding 过大(8px 10px)，像按钮
- **反馈**：无
- **流式**：`<Spin>` + "AI 思考中..."，无 token batching（每字符一次 re-render）

### 1.2 目标
1. 引用：琥珀色 Tag + Tooltip 显示来源标题 + hover 过渡
2. 反馈：赞/踩按钮，localStorage 持久化
3. 流式：`requestAnimationFrame` token batching、打字光标、三点跳动指示器、移除 Spin

### 1.3 非目标
- 无后端 API（feedback localStorage MVP）
- 无 markdown 流式渲染
- 无新依赖

---

## 2. 技术方案

### 2.1 引用高亮

**文件**：`ChatMessage.tsx`

- 浅蓝底色 badge：`background: '#dbeafe'`, `color: '#1e40af'`, `border: '1px solid #93c5fd'`
- `fontSize: 12`, `padding: '0 5px'`, `lineHeight: '18px'`, `verticalAlign: 'baseline'`
- hover: `background: '#bfdbfe'`, `border-color: '#60a5fa'`, `transition: 'all 0.15s ease'`

### 2.2 反馈按钮

**文件**：`ChatMessage.tsx` + `ChatPage.tsx`

- Icon: `LikeOutlined` / `DislikeOutlined`
- 仅已完成 AI 消息显示（`role==='assistant' && !isStreaming`）
- 状态：未选灰 `#94a3b8`，赞蓝 `#1e40af`+蓝底 `#dbeafe`，踩红 `#dc2626`+红底 `#fee2e2`，toggle 取消
- localStorage key: `rag_feedback`，格式 `Record<conversationId:messageIndex, 'up'|'down'|null>`
- ChatPage 管理 `feedbackMap` + `handleFeedback`

### 2.3 流式增强

**方案**（已实现）：pre-token `Spin` + "AI 思考中..." → post-token 打字光标 + "生成中..."

**typing cursor**（`ChatMessage.tsx`）：`isStreaming && content>0` → 2px 竖线 `@keyframes blink-cursor`

**后续模块**（M10+）：rAF token batching、typing indicator dots、Citation Tooltip

---

## 3. 文件清单

| # | 文件 | 变更 |
|---|------|------|
| 1 | `ChatMessage.tsx` | 引用 Tag 改琥珀色+Tooltip、feedback 按钮、typing cursor+dots、CSS keyframes |
| 2 | `ChatPage.tsx` | token batching、feedbackMap+handleFeedback、移除 Spin、传新 Props |
| 3 | `__tests__/ChatMessage.test.tsx` | **新建**：引用渲染、反馈按钮、光标/dots 渲染测试 |

---

## 4. 实施步骤

1. **引用高亮**：Tag color/size 调整 + Tooltip + hover
2. **反馈按钮**：ChatMessage 加按钮 UI + ChatPage 加状态管理
3. **流式增强**：token batching + 光标 + dots + 移除 Spin
4. **测试**：新建 ChatMessage 测试 + 更新 ChatPage 测试

---

## 5. 风险

| 风险 | 严重度 | 应对 |
|------|--------|------|
| rAF batching 丢失最后 token | 中 | 流完成显式 flushTokenBuffer |
| CSS 命名冲突 | 低 | `m10-` 前缀 |
| 现有测试因移除 Spin 失败 | 中 | 更新测试断言 |
