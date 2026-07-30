# 变更日志 — Module-010: RAG UI 优化

## 变更概述
对 ChatMessage 和 ChatPage 两个文件进行三项前端 UI 优化：引用标记从 Ant Design Tag 改为紧凑浅色 badge、AI 回复增加 thumbs-up/down 反馈按钮（localStorage 持久化）、流式响应增加打字光标和分阶段加载提示。零新依赖，所有新 Props 可选（向后兼容）。

## 文件变更列表
| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| frontend/src/components/ChatMessage.tsx | 修改 | 引用 badge 改为 `<span>` + inline style，新增 feedback 按钮 UI（LikeOutlined/DislikeOutlined），新增打字光标 `<span>` + `@keyframes blink-cursor`，扩展 Props（messageIndex/isStreaming/feedbackRating/onFeedback） |
| frontend/src/pages/ChatPage.tsx | 修改 | 新增 feedbackMap 状态 + handleFeedback（localStorage 读写 toggle 模式），消息渲染传递新 Props，loading 区域按 token 到达分阶段显示（Spin → 生成中...） |

## 关键设计说明

### 设计决策 1: 引用 badge 使用原生 span 替代 Ant Design Tag
- **决策**: 用 `<span>` + inline style 实现紧凑浅蓝 badge（padding: 0 5px, fontSize: 12, 背景 #dbeafe, hover 加深 #bfdbfe），移除 Tag import
- **原因**: Tag 默认 padding 过大（8px 10px），视觉上像按钮而非脚注标记；原生 span 更轻量，样式完全可控

### 设计决策 2: 反馈存储使用 localStorage + toggle 模式
- **决策**: 反馈以 `Record<string, 'up'|'down'|null>` 存储在组件 state 中，key 格式 `{conversationId}:{messageIndex}`，持久化到 localStorage key `rag_feedback`
- **原因**: 无后端 API 可用时 localStorage 是最简 MVP 方案；toggle 模式（同按钮再点取消）减少误操作；localStorage 不可用时 try-catch 静默降级

### 设计决策 3: 反馈按钮使用 span + 图标而非 Button 组件
- **决策**: 用 `<span>` 包裹 `<LikeOutlined>`/`<DislikeOutlined>` 图标，灰色(#94a3b8)未选中 / 蓝(#1e40af)红(#dc2626)选中
- **原因**: 避免引入额外组件，保持代码简洁，inline-flex 布局自然融入气泡底部

### 设计决策 4: 打字光标 + 分阶段加载提示
- **决策**: `<style>` 标签注入 `@keyframes blink-cursor`（0.8s 周期闪烁），光标为 2px 宽竖线；loading 区域根据 `hasTokens`（最后一条 AI 消息 content 长度 > 0）切换 Spin+"AI 思考中..." 与 "生成中..."
- **原因**: 完整改造流式体验：首 token 前显示思考态，token 到达后光标闪烁提示机器正在输出，完成时全部消失

### 设计决策 5: 所有新 Props 设为 optional
- **决策**: `messageIndex`、`isStreaming`、`feedbackRating`、`onFeedback` 全部带 `?` 修饰符，`isStreaming` 未传时默认 false
- **原因**: 保证向后兼容，现有 ChatMessage 调用（未传新 Props）不受影响

## 验收标准对照
| 验收项 | 状态 |
|--------|------|
| 引用标记以紧凑浅蓝 badge 显示 | 通过 |
| 标记 baseline 对齐、hover 过渡平滑 | 通过 |
| 点击标记弹出 CitationModal 行为不变 | 通过 |
| AI 回复底部 thumbs-up/down 按钮 | 通过 |
| 灰/蓝/红状态切换 + toggle 取消 | 通过 |
| localStorage 持久化（rag_feedback） | 通过 |
| 用户消息无反馈按钮、流式中无反馈按钮 | 通过 |
| 流式加载：Spin → 光标 + "生成中..." → 消失 | 通过 |
| `npm run build` TypeScript 编译无错误 | 通过 |
| localStorage 不可用时静默降级 | 通过 |
| `isStreaming` 未传时默认 false | 通过 |

## 验证命令
| 验证项 | 命令 | 结果 |
|--------|------|------|
| TypeScript 编译 + Vite 构建 | `npm run build` | PASS（3099 modules, built in 15.71s） |

## 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-07-30 | 初始实现：引用 badge、反馈按钮、流式增强 | Developer |
