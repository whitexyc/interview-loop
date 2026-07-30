# 变更日志

## 2026-07-30

### 子任务 6: Python 文档入库端点 (Developer-Python)

- **rag/engine.py**: 添加 `add_document` 方法，接收 title/content/source，调用 `embedding_service.embed_text` 向量化后入库
- **main.py**: 注册 `POST /ai/rag/documents` 路由，返回 `{"code": 0, "data": {"id": ..., "title": ...}}`

### 子任务 1-8: 前端聊天 UI + 文档上传 (Developer-Frontend)

- **types/rag.ts** (新增): 定义 ChatRequest / ChatResponse / SourceItem / SearchRequest / SearchResult / SearchResponse / DocumentUpload 类型
- **services/ragService.ts** (新增): 封装 chat / search / uploadDocument 三个 API 函数，遵循现有 Axios + ApiResponse 模式
- **components/ChatMessage.tsx** (新增): 消息气泡组件，支持用户/AI 双端样式，用正则解析 [n] 引用标记为可点击 Tag，阻止 XSS
- **components/SearchPanel.tsx** (新增): 右侧检索面板，含搜索输入框、加载态、结果列表（标题/摘要/来源/分值）、空状态
- **components/CitationModal.tsx** (新增): 引用原文弹窗，基于 antd Modal 展示 Card 列表
- **pages/ChatPage.tsx** (新增): 双栏布局 — 左栏聊天区域（消息列表 + 输入框 + 加载态 + 错误态 + 重试）+ 右栏 SearchPanel + CitationModal
- **pages/DocumentPage.tsx** (新增): 文档上传表单（标题 + 内容文本域），调 uploadDocument，成功/失败提示
- **App.tsx** (修改): 添加路由 `/chat` → ChatPage, `/documents` → DocumentPage
- **AppLayout.tsx** (修改): Header 添加 horizontal Menu，导航项：个人简历 / 知识库问答 / 知识管理
