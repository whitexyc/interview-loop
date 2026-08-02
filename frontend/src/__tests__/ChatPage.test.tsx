import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import ChatPage from '../pages/ChatPage';

// Mock the rag service
vi.mock('../services/ragService', () => ({
  chatStream: vi.fn(),
  chat: vi.fn(),
  search: vi.fn(),
  agentStream: vi.fn(),
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

    const input = screen.getByPlaceholderText('输入您的问题...');
    fireEvent.change(input, { target: { value: '你好' } });

    const sendButton = screen.getByRole('button', { name: /send/i });
    expect(sendButton).not.toBeDisabled();
    fireEvent.click(sendButton);

    // User message should appear
    expect(screen.getByText('你好')).toBeInTheDocument();
  });

  it('should render pipeline panel and upload section', () => {
    sessionStorage.setItem('document_upload_auth', 'true');
    render(<ChatPage />);

    // Agentic pipeline panel (always visible)
    expect(screen.getByText('Agentic 执行流程')).toBeInTheDocument();

    // Knowledge base upload trigger
    expect(screen.getByText('知识库')).toBeInTheDocument();
  });

  it('should show error alert when chat API fails', async () => {
    const { chatStream } = await import('../services/ragService');
    vi.mocked(chatStream).mockRejectedValue(new Error('网络异常'));

    render(<ChatPage />);

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
