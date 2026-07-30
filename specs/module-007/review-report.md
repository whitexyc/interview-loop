# 审查报告 — Module-007: 前端布局重构（第四轮改动）

## 1. 审查结论

- 结论: **通过**
- TypeScript: `npx tsc --noEmit` → exit code 0
- 测试: `npx vitest run --reporter=verbose` → 2 files / 13 tests 全部通过

本次改动覆盖前后端，涉及 SSE 流式通信、管线可视化重绘、IP 限流、Markdown 分块、消息持久化等多个维度。组件职责清晰，2 条建议修复。

---

## 2. 验证结果

| 项目 | 命令 | 结果 |
|------|------|------|
| 测试 | `npx vitest run` | 2 files / 13 tests 全部通过 |
| 类型检查 | `npx tsc --noEmit` | exit code 0 |

测试变更对照：
- `"should show loading state"` → `"should show user message after sending"`（反映流式改造）
- `"pipeline panel and search section"` → `"pipeline panel and upload section"`（反映左栏重构）
- 测试新增 `sessionStorage.setItem('document_upload_auth', 'true')` 绕过 PasswordGuard

---

## 3. 各改动项审查

### 3.1 PipelinePanel — StateGraph 节点-边布局

**文件**: `frontend/src/components/PipelinePanel.tsx`

**布局**：纵向列表 → 横向节点-边图

```
Row 0:  [意图识别] → [混合检索] → [Rerank]
                                  ↓
Row 1:            [自我反思] → [生成回答]
```

- 每个节点为可点击方块，点击展开/折叠步骤详情 ✅
- 三种状态：当前（蓝色边框+脉冲）、完成（绿色✅）、待执行（灰色） ✅
- SVG 箭头组件（`Arrow`）连接同行节点 ✅
- `↓` 符号连接两行 ✅
- `InfoChip` 紧凑标签展示检索指标 ✅
- 检索步骤内嵌搜索输入框，支持关键词实时检索 ✅
- `renderStepDetail()` 对每个步骤按 `key` 分发渲染 ✅

**步骤序号到 currentStep 的映射**：
```
0=idle → 1=intent → 2=retrieval → 3=rerank → 4=reflect → 5=generate → 6=done
getNodeState(): 节点序号 < currentStep → done; = → active; > → idle
```

### 3.2 流式步骤数据实时展示

**前端** `ChatPage.tsx:134-148`：
- `chatStream()` 支持 `onStep`（步骤数据）和 `onToken`（逐字追加）回调
- `onStep` 通过 `stepMap: {intent:1, retrieval:2, ...}` 同步更新 `PipelinePanel`
- 追加用户消息 + 空白 AI 占位 → 流式填充 → 更新 sources → 管线完成

**后端** `main.py:183-309`：
- SSE 端点 `/ai/rag/chat/stream`
- 事件顺序：`step` → `token`（LLM 逐字输出）→ `done`（含 sources）
- 每步含 `timing_ms` 字段
- 闲聊路径直接 LLM 流式输出，不进入 RAG 链路

### 3.3 检索结果精简

检索功能从独立 `SearchPanel` 迁移到 `PipelinePanel` 的检索步骤详情中：
- 结果仅显示：标题 + 60字摘要 + 来源 · 评分 ✅
- 无独立搜索面板，内嵌在管线节点中 ✅
- `SearchPanel.tsx` 现为死代码（见问题 #1）

### 3.4 引用弹窗白屏修复

**文件**: `CitationModal.tsx`

```tsx
<Modal ... destroyOnHidden>
```
- 用 `destroyOnHidden`（antd v5 推荐 API）替代已弃用的 `destroyOnClose` ✅
- 关闭时销毁 DOM，重新打开时从零渲染 ✅
- 空态兜底显示 ✅

### 3.5 PasswordGuard 留白减少

```
旧: minHeight: '60vh'  → 新: minHeight: 240
```
- 大屏减少约 50% 外部空白区域 ✅
- 卡片内间距保持不变 ✅

### 3.6 IP 会话 + localStorage 消息持久化

**前端** (`ChatPage.tsx:83-109`)：
- `STORAGE_KEY='rag_chat_messages'`，useEffect 启动时恢复、变化时持久化 ✅
- 双重 try/catch 处理 localStorage 不可用/配额满 ✅

**后端** (`main.py:24-28, 99-163`)：
- `IP_SESSION_MESSAGES: dict[str, list[dict]]` 按 IP 存储 ✅
- `MAX_MESSAGES_PER_IP = 50`，超出裁剪旧消息 ✅
- API：`GET /ai/chat/sessions` + `GET /ai/chat/sessions/{ip}/messages`
- 闲聊/实时路径跳过会话存储 ✅

### 3.7 基于 IP 的限流

**文件**: `src/ratelimit.py`
- 滑动窗口：`{ip: [timestamps]}` ✅
- 默认 20 次 / 60 秒 ✅
- 返回 `(allowed, retry_after)` ✅

**中间件** (`main.py:70-95`)：
- 除 `/ai/health` 外全部经过限流 ✅
- 超限返回 429 + `Retry-After` header ✅
- Client IP 提取：优先 `X-Forwarded-For` → `remote_addr` ✅

### 3.8 LangChain MarkdownHeaderTextSplitter 分块

**文件**: `rag/chunker.py`
- 使用 `langchain_text_splitters.MarkdownHeaderTextSplitter` ✅
- 按 `##`（二级标题）分割，保留 metadata ✅
- 最小块 50 字符过滤 ✅
- 标题路径拼接 `"G1 GC > Region 分区"` ✅
- 无标题时整篇作为一块 ✅

**集成** (`engine.py:213-217`)：`add_document()` 先分块 → 逐块向量化 → 批量落库 ✅

---

## 4. 问题列表

### 建议修复

| # | 文件 | 类别 | 问题 | 建议 |
|---|------|------|------|------|
| **1** | `frontend/src/components/SearchPanel.tsx` | 死代码 | `SearchPanel` 不再被任何组件引用。ChatPage 已移除 import，搜索功能已内嵌到 `PipelinePanel` 中。文件存在但已无人使用。 | **删除** `SearchPanel.tsx` 文件及对应 test 文件。 |
| **2** | `frontend/src/components/PipelinePanel.tsx:149-158` | 不可达代码 | 代码访问 `steps.retrieval.documents` 并渲染"命中文档"列表，但后端 SSE 只发送 `{count, relevant, previews}`，不包含 `documents` 字段。该代码路径因 `steps?.retrieval?.documents` 始终为 `undefined` 而永不会执行。 | 方案 A（推荐）：删除 `documents` 渲染分支；方案 B：改为匹配后端实际发送的 `previews` 字段：`steps.retrieval.previews?.slice(0,5).map(...)`。 |

### 观察项

| # | 文件 | 观察 |
|---|------|------|
| 3 | `ChatPage.tsx:193-245` | `handleRetry` 仍独立实现管线逻辑，未使用 `doSend` 统一入口。因使用 `pendingRef` 历史参数，当前拆分合理。 |
| 4 | `ChatPage.tsx:136-142` | `data as PipelineSteps['retrieval']` 类型断言绕过检查。后端数据若格式变更，编译期无法发现。建议明确定义 SSE 事件 data 类型。 |

---

## 5. 组件依赖图（当前状态）

```
App (路由)
  ├─ / → AppLayout(maxWidth=1200) → ResumePage
  ├─ /chat → AppLayout(maxWidth=100%) → ChatPage
  │    ├─ UploadPanel                    ← 密码保护
  │    │    └─ PasswordGuard (document_upload_auth)
  │    ├─ PipelinePanel                  ← 内嵌搜索 (ragService.search)
  │    ├─ ChatMessage
  │    └─ CitationModal
  └─ /edit-resume → AppLayout(maxWidth=1200) → EditResumePage
       └─ PasswordGuard (resume_edit_auth)
```

- **已移除**: `SearchPanel`（死代码）、`DocumentPage`、`/documents` 路由 ✅
- 无循环依赖，层次清晰 ✅

---

## 6. 验收标准核对

| 验收项 | 状态 | 证据 |
|--------|------|------|
| PipelinePanel 横向节点-边布局 | ✅ | Row 0/1 排列，SVG 箭头连接 + 点击展开详情 |
| 步骤数据自动展示 | ✅ | SSE onStep → onToken → done，实时更新 pipelineSteps |
| 检索结果精简 | ✅ | 仅标题 + 60 字摘要 + 评分，嵌入 PipelinePanel 内 |
| 引用弹窗白屏修复 | ✅ | `destroyOnHidden` 替代已弃用 API |
| 密码登录页留白减少 | ✅ | `minHeight: 240`（原 `60vh`） |
| IP 会话 + localStorage 持久化 | ✅ | 前端 localStorage，后端 IP_SESSION_MESSAGES |
| 基于 IP 的限流 | ✅ | 滑动窗口 20次/60秒，429 + Retry-After |
| LangChain Markdown 分块 | ✅ | MarkdownHeaderTextSplitter，h2 分割 |
| 组件职责清晰 | ✅ | 见依赖图 |
| 密码保护有效 | ✅ | sessionStorage + 双 authKey 隔离 |
| tsc --noEmit 零错误 | ✅ | exit code 0 |
| vitest run 全部通过 | ✅ | 13/13 |

---

## 7. 前后端变更清单

| 层 | 文件 | 变更 | 说明 |
|----|------|------|------|
| 前端 | `ChatPage.tsx` | 修改 | SSE 流式 (`chatStream`)、localStorage 持久化、管线动画 |
| 前端 | `PipelinePanel.tsx` | 重写 | StateGraph 布局、点击展开、搜索内嵌 |
| 前端 | `CitationModal.tsx` | 修复 | `destroyOnHidden` 修复白屏 |
| 前端 | `PasswordGuard.tsx` | 修改 | `minHeight: 240` |
| 前端 | `ragService.ts` | 新增 | `chatStream()` SSE 请求函数 |
| 前端 | `SearchPanel.tsx` | 死代码 | 建议删除 |
| 前端 | `__tests__/ChatPage.test.tsx` | 修改 | mock `chatStream`、测试名更新 |
| 后端 | `main.py` | 修改 | SSE 端点 `/ai/rag/chat/stream`、IP 会话管理、限流中间件 |
| 后端 | `src/ratelimit.py` | 新增 | 滑动窗口 IP 限流器 |
| 后端 | `rag/chunker.py` | 新增 | LangChain Markdown 分块器 |
| 后端 | `rag/engine.py` | 修改 | `add_document()` 集成 chunker、流式复用方法 |

---

*审查人: Reviewer (Agent) | 日期: 2026-07-30*
