/**
 * # RAG 知识库类型定义
 *
 * ## 文件职责
 * 定义前端与 Python AI 后端通信的所有数据结构。
 * 这些类型对应 ai_service/rag/schemas.py 中 Pydantic 模型的 TypeScript 版本。
 *
 * ## 数据流
 *   ChatPage → ragService.ts(序列化) → HTTP POST → Python 后端(反序列化 → RAGEngine)
 *
 * ## 设计原则
 * 1. 类型严格对齐后端响应结构，不增不减
 * 2. 所有字段使用驼峰命名（前端约定，后端 Python 也是驼峰）
 * 3. 可空字段不加 ?（后端保证字段一定存在）
 */

/** 证据链验证单条声明 — 模块 module-039 */
export interface VerifiedClaim {
  /** 陈述文本（1-2 句话） */
  claim: string;
  /** 可信度判定 */
  verdict: 'supported' | 'inferred' | 'unsupported';
  /** 证据引用编号（如 "[1]"；unsupported 时为 "N/A"） */
  evidence: string;
}

/** 聊天请求 — 对应 Python RAGEngine.chat() 的入参 */
export interface ChatRequest {
  /** 用户问题 */
  query: string;
  /** 历史对话（支持多轮追问） */
  history: { role: string; content: string }[];
}

/** 引用来源项 — AI 回答中 [n] 标记指向的文档片段 */
export interface SourceItem {
  /** 文档 ID */
  id: number;
  /** 文档标题 */
  title: string;
  /** 文档内容片段 */
  content: string;
  /** 来源标识 */
  source: string;
  /** 引用序号（对应回答中的 [1][2] 标记） */
  ref_index: number;
}

/** 聊天响应 — RAG 全链路执行结果 */
export interface ChatResponse {
  /** AI 生成的回答文本（含 [n] 引用标记） */
  answer: string;
  /** 引用来源列表 */
  sources: SourceItem[];
  /** 状态消息 */
  message: string;
  /** 各步骤中间数据（后端 RAG 链路执行结果） */
  steps?: PipelineSteps;
  /** 证据链验证结果（module-039；无验证数据时为 null） */
  verified_claims?: {
    claims: VerifiedClaim[];
    overall_confidence: number;
    total_claims: number;
    supported: number;
    inferred: number;
    unsupported: number;
  } | null;
}

/** RAG 中间步骤数据 — 对应后端 ChatSteps 模型 */
export interface PipelineSteps {
  /** 意图识别结果 */
  intent?: { label: string; confidence: number };
  /** 检索结果 */
  retrieval?: { count: number; top_score: number; documents?: { title: string; score: number }[]; previews?: { title: string; snippet: string; score: number }[] };
  /** Rerank 结果 */
  rerank?: { before: number; after: number };
  /** 自我反思结果 */
  reflection?: { sufficient: boolean; query_rewritten: boolean; rewritten_query?: string };
}

/**
 * 工具调用事件 — Agent ReAct 循环发起一次工具调用（module-029）
 * 对应后端 SSE 事件 tool_call 的 data 字段。
 */
export interface ToolCallEvent {
  /** 工具名称（如 search_knowledge） */
  name: string;
  /** 工具调用参数 */
  args: Record<string, unknown>;
  /** 累计工具调用次数 */
  tool_count: number;
}

/**
 * 工具执行结果事件 — 工具执行完成返回结果（module-029）
 * 对应后端 SSE 事件 tool_result 的 data 字段（result 已截断前 500 字）。
 */
export interface ToolResultEvent {
  /** 工具名称 */
  name: string;
  /** 工具调用参数 */
  args: Record<string, unknown>;
  /** 工具执行结果文本 */
  result: string;
  /** 累计工具调用次数 */
  tool_count: number;
}

/**
 * 单条工具轨迹 — 前端展示用（tool_call + tool_result 合并，module-029）
 * status 标记工具是否执行完成，用于 PipelinePanel 卡片渲染。
 */
export interface ToolTrace {
  /** 工具名称 */
  name: string;
  /** 工具调用参数 */
  args: Record<string, unknown>;
  /** 工具执行结果（tool_result 到达后才有） */
  result?: string;
  /** 累计工具调用次数（唯一标识一次调用） */
  tool_count: number;
  /** running=执行中，done=已完成 */
  status: 'running' | 'done';
}

/** 搜索请求 — 独立召回（不生成回答） */
export interface SearchRequest {
  /** 搜索关键词 */
  query: string;
  /** 返回结果数量 */
  top_k?: number;
}

/** 单条检索结果 — 从知识库中匹配到的文档 */
export interface SearchResult {
  /** 文档 ID */
  id: number;
  /** 文档标题 */
  title: string;
  /** 文档内容片段（截取前 500 字） */
  content: string;
  /** 来源标识 */
  source: string;
  /** 相关性评分（hybrid_score 或 rerank_score） */
  score: number;
}

/** 搜索响应 */
export interface SearchResponse {
  /** 检索结果列表 */
  results: SearchResult[];
  /** 状态消息 */
  message: string;
}

/** 文档上传请求 — 向知识库添加新文档 */
export interface DocumentUpload {
  /** 文档标题 */
  title: string;
  /** 文档内容（支持 Markdown） */
  content: string;
  /** 来源标识（可选，如文件名或 URL） */
  source?: string;
}

/** 单条文档摘要 — 知识库列表展示 */
export interface DocumentInfo {
  id: number;
  title: string;
  source: string;
  content_preview: string;
  chunk_count: number;
  created_at: string;
}

/** 文档列表响应 */
export interface DocumentListResponse {
  documents: DocumentInfo[];
  total: number;
  page: number;
  page_size: number;
}
