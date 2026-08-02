/**
 * # ragService 单元测试 — agentStream SSE 工具事件解析（module-029）
 *
 * 覆盖（验收 §4.1 前端工具事件解析单测）：
 * - tool_call / tool_result / token / done 事件正确解析并触发回调
 * - 跨 chunk 拆分的 SSE 数据累积解析（buffer 逻辑）
 * - HTTP 失败抛错
 * - error 事件抛后端错误（不被吞掉）
 *
 * 实现说明：mock 全局 fetch 返回带 ReadableStream 的假响应体，
 * 不依赖真实后端。工具事件按后端 /ai/rag/chat/agent 的实际 SSE 格式构造。
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { agentStream } from '../services/ragService';

interface SSEEvent {
  event: string;
  data: string;
}

/** 构造 SSE 响应体字节流（可选按 chunkSize 分片，模拟网络分包） */
function buildSseBody(events: SSEEvent[], chunkSize = 0): ReadableStream<Uint8Array> {
  const payload = events
    .map(({ event, data }) => `event: ${event}\ndata: ${data}\n\n`)
    .join('');
  const bytes = new TextEncoder().encode(payload);
  return new ReadableStream<Uint8Array>({
    start(controller) {
      if (chunkSize > 0) {
        for (let i = 0; i < bytes.length; i += chunkSize) {
          controller.enqueue(bytes.slice(i, i + chunkSize));
        }
      } else {
        controller.enqueue(bytes);
      }
      controller.close();
    },
  });
}

function sseResponse(events: SSEEvent[], chunkSize = 0): { ok: boolean; body: ReadableStream<Uint8Array> } {
  return { ok: true, body: buildSseBody(events, chunkSize) };
}

describe('agentStream SSE 工具事件解析', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('解析 tool_call / tool_result / token / done 并触发回调', async () => {
    const events: SSEEvent[] = [
      {
        event: 'tool_call',
        data: JSON.stringify({ name: 'search_knowledge', args: { query: 'Java线程池' }, tool_count: 1 }),
      },
      {
        event: 'tool_result',
        data: JSON.stringify({
          name: 'search_knowledge', args: { query: 'Java线程池' },
          result: '文档1...', tool_count: 1,
        }),
      },
      { event: 'token', data: JSON.stringify('线程池核心参数包括') },
      {
        event: 'done',
        data: JSON.stringify({
          answer: '线程池核心参数包括',
          sources: [{ id: 1, title: '文档1', content: '内容', source: 'test', ref_index: 1 }],
          tool_count: 1, budget: 4,
        }),
      },
    ];
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sseResponse(events)));

    const toolCalls: unknown[] = [];
    const toolResults: unknown[] = [];
    let tokens = '';
    const result = await agentStream(
      'Java线程池',
      [],
      (t) => toolCalls.push(t),
      (t) => toolResults.push(t),
      (token) => { tokens += token; },
    );

    expect(fetch).toHaveBeenCalledWith(
      '/ai/rag/chat/agent',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ query: 'Java线程池', history: [] }),
      }),
    );
    expect(toolCalls).toEqual([
      { name: 'search_knowledge', args: { query: 'Java线程池' }, tool_count: 1 },
    ]);
    expect(toolResults).toEqual([
      { name: 'search_knowledge', args: { query: 'Java线程池' }, result: '文档1...', tool_count: 1 },
    ]);
    expect(tokens).toBe('线程池核心参数包括');
    expect(result.answer).toBe('线程池核心参数包括');
    expect(result.sources).toHaveLength(1);
    expect(result.sources[0].id).toBe(1);
  });

  it('跨 chunk 拆分的 SSE 数据也能正确累积解析', async () => {
    const events: SSEEvent[] = [
      { event: 'tool_call', data: JSON.stringify({ name: 'search_fts', args: { query: 'G1 GC' }, tool_count: 1 }) },
      { event: 'done', data: JSON.stringify({ answer: '答案', sources: [], tool_count: 1, budget: 4 }) },
    ];
    // 1 字节分片强制 SSE 块被拆散，验证 buffer 累积逻辑
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sseResponse(events, 1)));

    const toolCalls: unknown[] = [];
    const result = await agentStream('G1 GC', [], (t) => toolCalls.push(t), () => {}, () => {});

    expect(toolCalls).toHaveLength(1);
    expect((toolCalls[0] as { name: string }).name).toBe('search_fts');
    expect(result.answer).toBe('答案');
  });

  it('HTTP 失败抛流式请求错误', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500 }));
    await expect(agentStream('q', [], () => {}, () => {}, () => {})).rejects.toThrow('流式请求失败');
  });

  it('error 事件抛后端错误（不被吞掉）', async () => {
    const events: SSEEvent[] = [
      { event: 'error', data: JSON.stringify({ message: '服务暂时不可用' }) },
    ];
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sseResponse(events)));
    await expect(agentStream('q', [], () => {}, () => {}, () => {})).rejects.toThrow('服务暂时不可用');
  });
});
