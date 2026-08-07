/**
 * # RAG 知识库 API 服务层
 *
 * ## 组件职责
 * 封装与 Python AI 后端的所有 HTTP 通信。
 * 三个接口分别对应 RAG 链路的三个关键操作：
 * - chat: 问答（全链路：检索→反思→生成）
 * - search: 独立检索（仅召回，不生成）
 * - uploadDocument: 文档入库（向量化 + 存储）
 *
 * ## 数据流
 * 前端页面 → 调用服务函数 → Axios POST → Python AI 后端 → 数据库/LLM → 返回结构化数据
 *
 * ## 与后端通信设计
 * Python AI 后端（8000 端口）不走 Java 后端的 CommonResult 包装，
 * 直接返回业务对象。这是因为 Python 端不是 Java 那个统一网关。
 * Vite 代理配置：/ai → http://localhost:8000
 *
 * ## 错误处理策略
 * - 网络错误：Axios 自动抛出，调用方 catch 即可
 * - 业务错误：uploadDocument 手动检查 code 字段
 * - 超时：http 实例 timeout=60000ms，超时抛 Error
 */
import { aiHttp as http, authHeader } from '../api/client';
import type {
  ChatResponse,
  SearchResult,
  SearchResponse,
  DocumentUpload,
  DocumentListResponse,
  ToolCallEvent,
  ToolResultEvent,
  VerifiedClaim,
} from '../types/rag';
import type { ApiResponse } from '../types/api';

/**
 * 统一 AI 请求实例（module-032 起走 api/client.ts 统一封装）
 *
 * baseURL: '/ai' → Vite 代理转发到 http://localhost:8000/ai
 * timeout: 60000ms（60 秒，RAG 全链路含多次 LLM 调用，可能耗时 20-40 秒）
 *
 * 由 createHttp('/ai', 60000) 创建，登录后请求自动附加
 * Authorization: Bearer <token>，供 AI 服务解析 user_id 实现记忆隔离。
 */

/**
 * 发送聊天消息 — RAG 问答全链路（非流式）
 *
 * 对应后端 RAGEngine.chat()，完整响应后返回。
 * 用于不需要流式展示的场景。
 */
export async function chat(
  query: string,
  history: { role: string; content: string }[],
): Promise<ChatResponse> {
  const response = await http.post<ChatResponse>('/rag/chat', { query, history });
  return response.data;
}

/**
 * 发送聊天消息 — 流式版（SSE）
 *
 * 步骤事件（step）在生成回答前就推送，便于前端 PipelinePanel 实时展示。
 * token 事件逐字输出 LLM 生成内容。
 *
 * @param query - 用户问题
 * @param history - 对话历史
 * @param onStep - 步骤事件回调（收到即展示）
 * @param onToken - token 回调（逐字追加到气泡）
 * @returns 最终 ChatResponse（含完整 answer 和 sources）
 */
export async function chatStream(
  query: string,
  history: { role: string; content: string }[],
  onStep: (step: string, data: unknown) => void,
  onToken: (text: string) => void,
): Promise<ChatResponse> {
  const resp = await fetch('/ai/rag/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeader() },
    body: JSON.stringify({ query, history }),
  });

  if (!resp.ok || !resp.body) {
    throw new Error('流式请求失败');
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let answer = '';
  let sources: { id: number; title: string; content: string; source: string; ref_index: number }[] = [];
  let verifiedClaims: { claims: VerifiedClaim[]; overall_confidence: number; total_claims: number; supported: number; inferred: number; unsupported: number } | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (line.startsWith('event: ')) {
        continue;
      }
      if (line.startsWith('data: ')) {
        const raw = line.slice(6).trim();

        try {
          const parsed = JSON.parse(raw);

          // token events are plain strings
          if (typeof parsed === 'string') {
            answer += parsed;
            onToken(parsed);
            continue;
          }

          // step events have step field
          if (parsed.step) {
            onStep(parsed.step, parsed.data || {});
            continue;
          }

          // done event has sources
          if (parsed.sources) {
            sources = parsed.sources;
            continue;
          }

          // verified event: claims + overall_confidence + counts (module-039)
          if (Array.isArray(parsed.claims)) {
            verifiedClaims = {
              claims: parsed.claims,
              overall_confidence: parsed.overall_confidence ?? 0,
              total_claims: parsed.total_claims ?? 0,
              supported: parsed.supported ?? 0,
              inferred: parsed.inferred ?? 0,
              unsupported: parsed.unsupported ?? 0,
            };
            continue;
          }

          // error event
          if (parsed.message && !parsed.step) {
            throw new Error(parsed.message);
          }
        } catch {
          // Not JSON = regular data line, skip
        }
      }
    }
  }

  return {
    answer,
    sources,
    message: 'ok',
    verified_claims: verifiedClaims,
  } as ChatResponse;
}

/**
 * 发送聊天消息 — Agent 工具化流式版（SSE，module-029）
 *
 * 对应后端 POST /ai/rag/chat/agent（module-028）。Agent 端点不推 step 事件，
 * 而是推送工具轨迹事件：LLM 自主决定调用工具，每步 tool_call → tool_result，
 * 推理/回答文本走 token 事件，最后 done 事件带最终 answer + sources。
 *
 * SSE 事件：
 *   event: tool_call    data: {name, args, tool_count}
 *   event: tool_result  data: {name, args, result, tool_count}
 *   event: token        data: "文本片段"
 *   event: done         data: {answer, sources, tool_count, budget}
 *   event: error        data: {message}
 *
 * @param query - 用户问题
 * @param history - 对话历史
 * @param onToolCall - 工具调用事件回调（触发即展示"正在调用"卡片）
 * @param onToolResult - 工具执行结果回调（更新卡片结果）
 * @param onToken - token 回调（逐字追加到气泡）
 * @returns 最终 ChatResponse（含完整 answer 和 sources）
 */
export async function agentStream(
  query: string,
  history: { role: string; content: string }[],
  onToolCall: (tool: ToolCallEvent) => void,
  onToolResult: (tool: ToolResultEvent) => void,
  onToken: (text: string) => void,
): Promise<ChatResponse> {
  const resp = await fetch('/ai/rag/chat/agent', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeader() },
    body: JSON.stringify({ query, history }),
  });

  if (!resp.ok || !resp.body) {
    throw new Error('流式请求失败');
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let answer = '';
  let sources: { id: number; title: string; content: string; source: string; ref_index: number }[] = [];

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const raw = line.slice(6).trim();

      try {
        const parsed = JSON.parse(raw);

        // token events are plain strings
        if (typeof parsed === 'string') {
          answer += parsed;
          onToken(parsed);
          continue;
        }

        // tool_call / tool_result: 均有 name + tool_count；有 result 字段即 tool_result
        if (parsed.name && typeof parsed.tool_count === 'number') {
          if (typeof parsed.result === 'string') {
            onToolResult(parsed as ToolResultEvent);
          } else {
            onToolCall(parsed as ToolCallEvent);
          }
          continue;
        }

        // done event: 最终 answer + sources
        if (parsed.sources || typeof parsed.answer === 'string') {
          if (typeof parsed.answer === 'string') answer = parsed.answer;
          if (Array.isArray(parsed.sources)) sources = parsed.sources;
          continue;
        }

        // error event
        if (parsed.message) {
          throw new Error(parsed.message);
        }
      } catch (err) {
        // 仅吞掉 JSON 解析失败（非 JSON 数据行，跳过不影响对话）；
        // error 事件抛出的 Error 需继续传播给调用方展示
        if (!(err instanceof SyntaxError)) {
          throw err;
        }
      }
    }
  }

  return {
    answer,
    sources,
    message: 'ok',
  } as ChatResponse;
}

/**
 * 获取当前 LLM 降级链顺序（module-029）
 *
 * 对应后端 GET /ai/llm/chain。返回运行时链（Redis 持久化优先），否则配置默认。
 *
 * @returns 供应商顺序数组（如 ["deepseek", "qwen", "zhipu"]）
 * @throws Error - 后端返回 code != 0 时
 */
export async function getLLMChain(): Promise<string[]> {
  const response = await http.get<ApiResponse<{ chain: string[] }>>('/llm/chain');
  const body = response.data;
  if (body.code !== 0) throw new Error(body.msg || '获取供应商顺序失败');
  return body.data?.chain ?? [];
}

/**
 * 调整 LLM 降级链顺序（module-029）
 *
 * 对应后端 PUT /ai/llm/chain。后端校验合法后持久化到 Redis 并即时生效
 * （clear_cache 重建 FallbackClient，无需重启服务）。
 *
 * @param chain - 新的供应商顺序（需全为支持供应商且不重复）
 * @returns 保存后的供应商顺序（后端规范化结果）
 * @throws Error - 校验失败或 Redis 持久化失败
 */
export async function updateLLMChain(chain: string[]): Promise<string[]> {
  const response = await http.put<ApiResponse<{ chain: string[] }>>('/llm/chain', { chain });
  const body = response.data;
  if (body.code !== 0) {
    throw new Error(body.msg || (body as { message?: string }).message || '保存供应商顺序失败');
  }
  return body.data?.chain ?? chain;
}

/**
 * 检索知识库 — 独立召回（不生成回答）
 *
 * 用于右侧搜索面板，让用户直接浏览知识库中的相关内容。
 * 调用 HybridRetriever + Reranker，返回排序后的文档列表。
 *
 * @param query - 搜索关键词
 * @param top_k - 返回结果数量（默认 5，最大 50）
 * @returns SearchResult[] - 检索结果列表，每项含 title/content/source/score
 */
export async function search(query: string, top_k = 5): Promise<SearchResult[]> {
  const response = await http.post<SearchResponse>('/rag/search', { query, top_k });
  return response.data.results;
}

/**
 * 上传文档到知识库
 *
 * 前端先将文档文本传给 Python 后端，后端做：
 * 1. 检查是否重复（同名或同内容）
 * 2. EmbeddingService.embed_text() 向量化
 * 3. 存入 PostgreSQL（含向量字段）
 *
 * @param data - { title: 文档标题, content: 文档内容, source?: 来源标识 }
 * @returns { id, duplicate } - duplicate=true 表示检测到重复
 * @throws Error - 网络异常或后端错误
 */
export async function uploadDocument(data: DocumentUpload): Promise<{ id: number; duplicate?: boolean }> {
  const response = await http.post<ApiResponse<{ id: number; duplicate?: boolean }>>('/rag/documents', data);
  const body = response.data;
  if (body.code !== 0) {
    throw new Error(body.msg || '上传失败');
  }
  return body.data || { id: 0 };
}

/** 获取知识库文档列表（分页） */
export async function listDocuments(page = 1, pageSize = 20): Promise<DocumentListResponse> {
  const response = await http.get<ApiResponse<DocumentListResponse>>('/documents', { params: { page, page_size: pageSize } });
  const body = response.data;
  if (body.code !== 0) throw new Error(body.msg || '获取文档列表失败');
  return body.data || { documents: [], total: 0, page: 1, page_size: 20 };
}

/** 删除知识库文档 */
export async function deleteDocument(id: number): Promise<void> {
  const response = await http.delete<ApiResponse<unknown>>(`/documents/${id}`);
  const body = response.data;
  if (body.code !== 0) throw new Error(body.msg || '删除失败');
}
