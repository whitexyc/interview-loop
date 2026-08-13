import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import ChatPage from '../pages/ChatPage';

// Mock the rag service
vi.mock('../services/ragService', () => ({
  chatStream: vi.fn(),
  chat: vi.fn(),
  search: vi.fn(),
  agentStream: vi.fn(),
  submitFeedback: vi.fn(),
  fetchVerifyResult: vi.fn(),
}));

// Mock 会话服务（module-060 轮询测试需 activeConversationId 就绪，doSend 才继续；
// 顺带修复既有环境性失败——jsdom 下 conversationService 真实网络请求必失败）
vi.mock('../services/conversationService', () => ({
  listConversations: vi.fn().mockResolvedValue([]),
  createConversation: vi.fn().mockResolvedValue({ id: 1, title: '会话1', messageCount: 0, updatedAt: '' }),
  deleteConversation: vi.fn().mockResolvedValue(undefined),
  getMessages: vi.fn().mockResolvedValue([]),
  saveMessages: vi.fn().mockResolvedValue(undefined),
}));

describe('ChatPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should render chat page with title, input and send button', () => {
    render(<ChatPage />);

    // Title
    expect(screen.getByText('知识库问答')).toBeInTheDocument();

    // Input placeholder
    expect(screen.getByPlaceholderText('输入您的问题...')).toBeInTheDocument();

    // Send button
    expect(screen.getByRole('button', { name: /send/i })).toBeInTheDocument();
  });

  it('should disable send button when input is empty', () => {
    render(<ChatPage />);

    const sendButton = screen.getByRole('button', { name: /send/i });
    expect(sendButton).toBeDisabled();
  });

  it('should show user message after sending', async () => {
    const { chatStream } = await import('../services/ragService');
    vi.mocked(chatStream).mockImplementation(() => new Promise(() => {}));

    render(<ChatPage />);
    // 等待挂载建会话完成（createConversation → activeConversationId 就绪），
    // 否则 doSend 的 activeConversationId 守卫提前 return（module-029 记录的环境性失败）
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });

    const input = screen.getByPlaceholderText('输入您的问题...');
    fireEvent.change(input, { target: { value: '你好' } });

    const sendButton = screen.getByRole('button', { name: /send/i });
    expect(sendButton).not.toBeDisabled();
    fireEvent.click(sendButton);

    // User message should appear
    expect(screen.getByText('你好')).toBeInTheDocument();
  });

  it('should limit input to 2000 characters (module-048 WP3)', () => {
    render(<ChatPage />);

    const input = screen.getByPlaceholderText('输入您的问题...');
    expect(input).toHaveAttribute('maxlength', '2000');
  });

  it('should render pipeline panel and agent switch', () => {
    sessionStorage.setItem('document_upload_auth', 'true');
    render(<ChatPage />);

    // Agentic pipeline panel (always visible)
    expect(screen.getByText('Agentic 执行流程')).toBeInTheDocument();

    // Agent 模式开关（module-029；旧"知识库"上传文案 M18 已移入 KnowledgePage，断言随之更新）
    expect(screen.getByText('Agent 模式')).toBeInTheDocument();
  });

  it('should show error alert when chat API fails', async () => {
    const { chatStream } = await import('../services/ragService');
    vi.mocked(chatStream).mockRejectedValue(new Error('网络异常'));

    render(<ChatPage />);
    // 等待挂载建会话完成（同"should show user message"环境性修复）
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });

    const input = screen.getByPlaceholderText('输入您的问题...');
    fireEvent.change(input, { target: { value: '测试' } });

    const sendButton = screen.getByRole('button', { name: /send/i });
    fireEvent.click(sendButton);

    await waitFor(() => {
      expect(screen.getByText('网络异常')).toBeInTheDocument();
    });

    // Should show retry button
    expect(screen.getByRole('button', { name: /重\s*试/ })).toBeInTheDocument();
  });
});

describe('ChatPage verify 异步轮询（module-060）', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  /** 挂载后输入并点击发送（fake timers 下 flush 微任务，使 mount 建会话 + doSend 完成） */
  async function sendMessage(text: string) {
    // 先 flush mount 微任务（listConversations → createConversation →
    // setActiveConversationId），确保 doSend 的 activeConversationId 守卫通过
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    const input = screen.getByPlaceholderText('输入您的问题...');
    fireEvent.change(input, { target: { value: text } });
    fireEvent.click(screen.getByRole('button', { name: /send/i }));
    // flush doSend 内 executeSend resolve 微任务（消息 patch + startVerifyPolling + setLoading(false)）
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  }

  it('答案交付后 loading 立即结束，轮询 done 更新 verifiedClaims 面板', async () => {
    vi.useFakeTimers();
    const { chatStream, fetchVerifyResult } = await import('../services/ragService');
    vi.mocked(chatStream).mockResolvedValue({
      answer: '答案', sources: [], message: 'ok', verified_claims: null, verifyTaskId: 'task-1',
    } as any);
    vi.mocked(fetchVerifyResult).mockResolvedValue({
      status: 'done',
      claims: [{ claim: '测试', verdict: 'supported', evidence: '[1]' }],
      overall_confidence: 1, total_claims: 1, supported: 1, inferred: 0, unsupported: 0,
      verified_in_ms: 1200,
    } as any);

    render(<ChatPage />);
    await sendMessage('什么是G1 GC');

    // loading 立即结束（答案先交付、不等 verify）：消息级 loading 指示器消失、
    // 消息进入"正在验证…"态（注意："生成中..." 是 PipelinePanel 步骤状态文案，
    // 与消息 loading 无关，不能用它断言 loading 结束）
    expect(screen.queryByText('AI 思考中...')).not.toBeInTheDocument();
    expect(screen.getByText('正在验证…')).toBeInTheDocument();

    // 2s 后首轮轮询 → done → verifiedClaims 面板展示、"正在验证…"消失
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(screen.getByText('可信度验证')).toBeInTheDocument();
    expect(screen.queryByText('正在验证…')).not.toBeInTheDocument();
    expect(fetchVerifyResult).toHaveBeenCalledWith('task-1');
  });

  it('pending 多轮后 done 才更新面板', async () => {
    vi.useFakeTimers();
    const { chatStream, fetchVerifyResult } = await import('../services/ragService');
    vi.mocked(chatStream).mockResolvedValue({
      answer: '答案', sources: [], message: 'ok', verified_claims: null, verifyTaskId: 'task-2',
    } as any);
    vi.mocked(fetchVerifyResult)
      .mockResolvedValueOnce({ status: 'pending' } as any)
      .mockResolvedValueOnce({
        status: 'done',
        claims: [{ claim: 'x', verdict: 'supported', evidence: '[1]' }],
        overall_confidence: 1, total_claims: 1, supported: 1, inferred: 0, unsupported: 0,
      } as any);

    render(<ChatPage />);
    await sendMessage('问题');

    // 第 1 次轮询 pending → 仍在"正在验证…"
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(screen.getByText('正在验证…')).toBeInTheDocument();
    expect(screen.queryByText('可信度验证')).not.toBeInTheDocument();

    // 第 2 次轮询 done → 面板更新
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(screen.getByText('可信度验证')).toBeInTheDocument();
    expect(fetchVerifyResult).toHaveBeenCalledTimes(2);
  });

  it('failed 停止轮询 fail-open（不显示验证面板、不报错）', async () => {
    vi.useFakeTimers();
    const { chatStream, fetchVerifyResult } = await import('../services/ragService');
    vi.mocked(chatStream).mockResolvedValue({
      answer: '答案', sources: [], message: 'ok', verified_claims: null, verifyTaskId: 'task-3',
    } as any);
    vi.mocked(fetchVerifyResult).mockResolvedValue({ status: 'failed', error: 'verify timeout' } as any);

    render(<ChatPage />);
    await sendMessage('问题');
    expect(screen.getByText('正在验证…')).toBeInTheDocument();

    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(screen.queryByText('正在验证…')).not.toBeInTheDocument();
    expect(screen.queryByText('可信度验证')).not.toBeInTheDocument();
  });

  it('卸载清理 verify 轮询 timer（不再调用 fetchVerifyResult）', async () => {
    vi.useFakeTimers();
    const { chatStream, fetchVerifyResult } = await import('../services/ragService');
    vi.mocked(chatStream).mockResolvedValue({
      answer: '答案', sources: [], message: 'ok', verified_claims: null, verifyTaskId: 'task-4',
    } as any);
    vi.mocked(fetchVerifyResult).mockResolvedValue({ status: 'pending' } as any);

    const { unmount } = render(<ChatPage />);
    await sendMessage('问题');
    expect(screen.getByText('正在验证…')).toBeInTheDocument();

    unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(fetchVerifyResult).not.toHaveBeenCalled();
  });
});
