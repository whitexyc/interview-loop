# Review Report — Module-006: 前端知识库问答界面

> Reviewer: reviewer-001 | 日期: 2026-07-30 | 版本: v1

## 审查范围

| 维度 | 状态 |
|------|------|
| 引用标记 XSS 防护 | PASS |
| 组件职责与单一职责 | PASS (minor) |
| TypeScript 类型完备性 | PASS (minor) |
| Python 端点正确性 | PASS (minor) |
| 错误处理与空状态 | PASS |
| 验收标准覆盖 | PARTIAL |

---

## 1. 引用标记解析与 XSS 防护 — PASS

**结论：安全，无 XSS 风险。**

`ChatMessage.tsx` 中的 `parseCitations()` 函数使用正则 `/\[(\d+)\]/g` 解析 `[n]` 标记，返回类型化数组 `({ type: 'text' | 'citation' })`，然后通过 React JSX 渲染为 `<Tag>` 和 `<Typography.Text>` 组件。

- **未使用 `dangerouslySetInnerHTML`**
- **未使用 `innerHTML` 或任何原生 DOM 注入**
- 正则仅匹配数字序列，不匹配任意 HTML/脚本标签
- 引用标记渲染为 Ant Design `<Tag>` 组件，点击调用 `onCitationClick(refIndex)` 回调

---

## 2. 组件职责 — PASS (minor)

| 组件 | 职责 | 评价 |
|------|------|------|
| `ChatMessage` | 渲染单条消息气泡 + 引用标记解析 | 单一职责 |
| `SearchPanel` | 检索输入 + 结果展示 | 单一职责 |
| `CitationModal` | 引用原文弹窗 | 单一职责 |
| `ChatPage` | 聊天页面编排（消息列表/输入/检索面板/引用弹窗） | 合理，页面级组件承担编排职责 |
| `DocumentPage` | 文档上传表单 | 单一职责 |

**Minor:** Plan 中规划了独立的 `InputBox.tsx` 组件，Developer 将输入框直接内联在 `ChatPage.tsx`（第 170-192 行）。考虑到输入框逻辑简单（仅输入 + Enter发送 + 按钮），此偏离可接受，不用提取。

---

## 3. TypeScript 类型完备性 — PASS (minor)

### 类型定义 (`types/rag.ts`)
- `ChatRequest`, `ChatResponse`, `SearchRequest`, `SearchResponse`, `SourceItem`, `SearchResult`, `DocumentUpload` — 类型完备 ✅
- 所有组件都有完整的 Props 接口 ✅

### 问题发现

**Issue #1（Medium）：`ragService.ts` 跨模块依赖 `resume.ts` 的 `ApiResponse<T>` 类型**

`ragService.ts:2` 从 `../types/resume` 导入 `ApiResponse`。这创建了 module-006 对简历模块类型文件的跨模块依赖。如果后续重构 `resume.ts`（重命名、删除、拆分），`ragService.ts` 会在类型检查时断裂。

**建议**：在 `types/rag.ts` 中定义自己的 API 响应包装类型，或创建一个共享的 `types/api.ts`。

**Issue #2（Low）：Python 端点返回格式与 `ApiResponse<T>` 不完全匹配**

`ApiResponse<T>` 包含 `{code, msg, data, timestamp, request_id}`，但 Python 的 `POST /ai/rag/documents` 仅返回 `{"code": 0, "data": {"id": ..., "title": ...}}`。缺少 `msg`、`timestamp`、`request_id`。运行时 Axios 不做校验不会报错，但存在类型语义偏差。

**建议**：为 Python 服务的响应定义一个独立的 `PythonApiResponse<T>` 类型，或添加共享类型文件。

---

## 4. Python 端点正确性 — PASS (minor)

### POST /ai/rag/documents (`main.py:77-85`)

- 路由注册正确 ✅
- 接收 `title`, `content`, `source` 参数 ✅
- 调用 `rag_engine.add_document()` 并返回结果 ✅

### add_document() (`engine.py:135-155`)

- embedding → Document 创建 → DB 写入流程正确 ✅
- 使用 `async_session_factory()` 上下文管理器 ✅
- 返回 `{"id": ..., "title": ...}` ✅

### 问题发现

**Issue #3（Medium）：`add_document()` 缺少输入验证和异常处理**

```python
async def add_document(self, title: str, content: str, source: str = "") -> dict:
    # 没有检查 title/content 是否为空
    # 没有 try/except 包裹 embedding 和 DB 写入
    embedding = await embedding_service.embed_text(content)
    ...
```

如果 `content` 为空字符串且 embedding 抛出异常，FastAPI 返回 500，前端收到 Axios 错误（不是结构化错误）。虽然前端有 fallback 提示，但缺少明确的错误信息。

**建议**：
- 验证 `title` 和 `content` 非空，非空时返回 `{"code": 1, "msg": "标题和内容不能为空", "data": null}`
- 用 try/except 包裹，返回结构化错误响应

**Issue #4（Low）：`engine.py:76` 残留过时注释**

```python
# 3. 实时数据 → 占位（待 module-006 实现）
```

当前就是 module-006 审查中的代码，此注释应更新或移除。

---

## 5. 错误处理与空状态 — PASS

| 场景 | ChatPage | SearchPanel | DocumentPage |
|------|----------|-------------|--------------|
| Loading | Spin + "AI 思考中..." | Spin | Button loading |
| Error | Alert + 重试按钮 | Typography.Text danger | Alert closable |
| Empty (无数据) | Empty + "输入您的问题，开始与知识库对话" | 区分"未搜索"和"无结果" | N/A |
| 空输入禁止 | `!input.trim()` disabled button | `!trimmed` early return | `!title.trim() || !content.trim()` disabled button |

- 发送失败后 `handleRetry` 通过 `pendingRef` 重试上次请求 ✅
- 所有 async 操作都有 `try/except` 包裹 ✅

### Minor 问题

**Issue #5（Low）：`handleRetry` 在失败后追加新消息而非修复原位**

```typescript
// handleSend 失败时：user 消息已追加到 messages（第 39 行）
// handleRetry 成功时：追加新的 assistant 消息（第 70-73 行）
```

用户会看到：
1. 用户消息出现
2. 加载态出现、消失、报错
3. 点击重试
4. 加载态再次出现，然后弹出 AI 回复

虽然功能正确，但体验上用户消息和 AI 回复之间没有视觉关联。建议：可在用户消息下方显示一个 "重试中..." 的中间状态。

---

## 6. 验收标准覆盖检查

| 验收项 | 状态 | 备注 |
|--------|------|------|
| 聊天页面可输入问题并发送 | ✅ | |
| AI 回答以气泡形式展示 | ✅ | |
| 引用标记 [1][2] 正确渲染为可点击样式 | ✅ | 正则解析 + Tag 渲染，无 XSS 风险 |
| 点击引用标记弹出 Modal 显示原文 | ✅ | |
| 消息历史保留在对话中 | ✅ | `messages` state 维护 |
| 发送消息时显示加载态 | ✅ | Spin + "AI 思考中..." |
| 右侧检索面板可搜索 | ✅ | |
| 检索结果展示标题、摘要、来源、分值 | ✅ | |
| 导航栏有"知识库问答"入口 | ✅ | `/chat` |
| 空输入禁止发送 | ✅ | button disabled + early return |
| API 错误时显示友好提示（重试按钮） | ✅ | Alert + Retry |
| 网络异常时提示 | ✅ | catch -> setError |
| 消息列表自动滚动到底部 | ✅ | `bottomRef.current?.scrollIntoView` |
| TypeScript 类型完备 | ✅ | 见 section 3 的 minor 问题 |
| 组件职责单一、可复用 | ✅ | 见 section 2 |
| 引用解析使用正则，防止 XSS | ✅ | 未使用 dangerouslySetInnerHTML |

### 未覆盖

| 验收项 | 状态 | 备注 |
|--------|------|------|
| **流式问答** | ❌ | Plan 需求描述中提到"流式问答"，但实现使用同步 `POST /ai/rag/chat`，非流式。前端没有 EventSource/WebSocket/streaming fetch 实现 |
| **文件上传（非文本粘贴）** | ❌ | Plan 提到"支持文本粘贴或文件上传"，仅实现了文本粘贴 |
| **`InputBox` 独立组件** | ⚠️ | Plan 规划了独立组件，实际内联在 ChatPage |
| **`documentService.ts`** | ⚠️ | Plan 规划了单独文件，uploadDocument 实现在 ragService.ts 中 |

---

## 7. 综合问题列表

| # | 严重度 | 文件 | 描述 | 建议 |
|---|--------|------|------|------|
| 1 | Medium | `ragService.ts:2` | 跨模块依赖 `resume.ts` 的 `ApiResponse` | 创建共享 `types/api.ts` 或自包含类型 |
| 2 | Medium | `engine.py:135` | `add_document()` 无输入验证和异常处理 | 加非空校验 + try/except |
| 3 | Medium | — | 流式问答未实现（Plan 要求） | 评估是否需要：如果当前同步模式满足需求可 defer |
| 4 | Low | `engine.py:76` | 过时注释 "待 module-006 实现" | 更新或删除 |
| 5 | Low | `ChatPage.tsx` | retry 时追加新消息而非替换 | 增强 retry 状态的视觉关联 |
| 6 | Low | `ragService.ts` 类型 | Python 响应缺少 `msg`/`timestamp`/`request_id` | 定义独立 Python API 响应类型 |

---

## 8. 审查结论

| 维度 | 结论 |
|------|------|
| 整体质量 | **合格（条件通过）** |
| 安全性 | 良好 — XSS 防护到位 |
| 架构一致性 | 良好 — 组件职责清晰 |
| 类型安全 | 良好 — 少数 minor 问题 |
| Python 端点 | 合格 — 需补充输入验证 |

### 条件

1. **高优先级**：`add_document()` 补充空内容验证和异常处理（Issue #2）
2. **中优先级**：评估是否在本模块实现流式问答，或更新 Plan 说明为非流式（Issue #3）
3. **低优先级**：清理过时注释、更新类型独立性（Issue #4, #6）

上述条件完成后可移交 Tester。
