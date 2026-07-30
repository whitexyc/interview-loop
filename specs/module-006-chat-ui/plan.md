# 开发计划 — Module-006: 前端知识库问答界面

> Planner: Claude | 日期: 2026-07-30 | 版本: v1

## 0. Agent 配置清单
- **Developer-Frontend ×1** — React 聊天界面 + 文档上传页面
- **Developer-Python ×1** — Python `/ai/rag/documents` 端点
- **Tester ×1** — 前端测试

## 1. 需求描述
- **需求来源**: prompt.md（Agentic RAG 知识库模块）
- **功能描述**: 创建前端知识库问答聊天界面，调用 `/ai/rag/chat` 和 `/ai/rag/search` 接口，支持流式问答、知识库检索展示、引用溯源展示
- **页面结构**: 双栏布局 — 左侧聊天对话区 + 右侧知识库检索面板
- **优先级**: P1

## 2. 页面设计

```
┌────────────────────────────────────────────────┐
│  张三 - 个人网站  导航                        │
├──────────────────────┬─────────────────────────┤
│  知识库问答           │  知识库检索              │
│                      │                         │
│  ┌──────────────────┐│  ┌──────────────────┐   │
│  │ 用户: xxx        ││  │ 搜索框            │   │
│  │ AI: 回答 [1][2]  ││  │                   │   │
│  │   来源: doc-1    ││  │ 检索结果列表       │   │
│  │   来源: doc-2    ││  │  doc-1 ...        │   │
│  └──────────────────┘│  │  doc-2 ...        │   │
│                      │  └──────────────────┘   │
│  [输入框......][发送] │                         │
├──────────────────────┴─────────────────────────┤
│  引用弹窗: 点击 [1] 查看原文片段                 │
└────────────────────────────────────────────────┘
```

## 3. 模块拆分

### 子任务 1: API 服务层
- **描述**: 封装 `/ai/rag/chat` 和 `/ai/rag/search` 的 Axios 调用
- **代码量**: ~40 行
- **涉及文件**:
  - `frontend/src/services/ragService.ts` (新增)

### 子任务 2: 类型定义
- **描述**: 定义 ChatRequest/ChatResponse/SearchRequest/SearchResponse 的 TypeScript 接口
- **代码量**: ~30 行
- **涉及文件**:
  - `frontend/src/types/rag.ts` (新增)

### 子任务 3: 聊天页面组件（主）
- **描述**: 左侧聊天区：消息列表（用户/AI 气泡）、输入框、发送按钮、加载状态
  - AI 回答中的 [1][2] 引用标记可点击，点击弹出原文片段
- **代码量**: ~120 行
- **涉及文件**:
  - `frontend/src/pages/ChatPage.tsx` (新增)
  - `frontend/src/components/ChatMessage.tsx` (新增)
  - `frontend/src/components/InputBox.tsx` (新增)

### 子任务 4: 知识库检索面板（右侧）
- **描述**: 右侧面板：搜索输入框、检索结果列表（标题/摘要/来源/分值）
  - 搜索按钮触发 `/ai/rag/search`
- **代码量**: ~70 行
- **涉及文件**:
  - `frontend/src/components/SearchPanel.tsx` (新增)

### 子任务 5: 引用溯源弹窗
- **描述**: 点击回答中的 [1] 引用标记，弹出 Modal 显示原文内容
- **代码量**: ~30 行
- **涉及文件**:
  - `frontend/src/components/CitationModal.tsx` (新增)

### 子任务 6: Python 文档入库端点
- **描述**: Python 端实现 POST `/ai/rag/documents` 接收文档文本，调用 embedding 向量化后存入 pgvector
- **代码量**: ~50 行
- **涉及文件**:
  - `ai_service/rag/engine.py` (修改) — 添加 add_document() 方法
  - `ai_service/main.py` (修改) — 注册 POST /ai/rag/documents 路由

### 子任务 7: 文档上传页面
- **描述**: 在导航栏添加"知识管理"页面，支持文本粘贴或文件上传，调用 documents 端点入库
- **代码量**: ~60 行
- **涉及文件**:
  - `frontend/src/pages/DocumentPage.tsx` (新增)
  - `frontend/src/services/documentService.ts` (新增)
  - `frontend/src/App.tsx` (修改，添加路由)
  - `frontend/src/components/AppLayout.tsx` (修改，导航加"知识管理"项)

### 子任务 8: 路由集成
- **描述**: 添加 `/chat` 路由入口，更新导航栏
- **代码量**: ~20 行
- **涉及文件**:
  - `frontend/src/App.tsx` (修改)
  - `frontend/src/components/AppLayout.tsx` (修改，导航加"知识库问答"项)

## 3. 技术方案

### API 端点

| 端点 | 方法 | 请求 | 响应 |
|------|------|------|------|
| `/ai/rag/chat` | POST | `{query, history}` | `{answer, sources, message}` |
| `/ai/rag/search` | POST | `{query, top_k}` | `{results, message}` |

### 组件树
```
ChatPage
  ├── ChatMessage (x N)      ← 消息气泡（支持引用标记渲染）
  │     └── CitationLink     ← 可点击引用标记
  ├── InputBox               ← 输入框 + 发送按钮
  └── SearchPanel (aside)    ← 右侧检索面板
        └── SearchResult     ← 单条检索结果

CitationModal                ← 引用原文弹窗（全局）
```

### 数据流
```
用户输入 → InputBox → ChatPage.submit()
  → ragService.chat({query, history})
  → 响应流式追加到 message list
  → 渲染 ChatMessage（含 [1][2] 引用）

用户搜索 → SearchPanel.search()
  → ragService.search({query})
  → 展示结果列表
```

## 4. 验收标准
见同目录 `acceptance-criteria.md`

## 5. 风险评估
- 依赖 module-005 的 `/ai/rag/chat` 和 `/ai/rag/search` 端点
- `[1][2]` 引用标记解析需要正则处理，注意 XSS 防护
- 消息历史管理需用 useRef 或 Zustand

## 6. 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-07-30 | 初始版本 | Planner |
