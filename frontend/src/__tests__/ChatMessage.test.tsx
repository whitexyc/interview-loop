/**
 * # ChatMessage 反馈按钮单测（module-048 WP2 前端反馈）+ verifying 态（module-060）
 *
 * 覆盖验收 §2（module-048）：
 * - 无 message_id → 按钮隐藏；有 message_id → 👍👎 按钮展示
 * - 点击后调 POST /ai/feedback（submitFeedback）+ Toast "感谢反馈"
 * - 已反馈消息按钮变已评态（不重复提交）
 * - API 失败 → Toast 失败提示、可重试
 *
 * 覆盖验收 §3（module-060 verify 异步后置）：
 * - verifying=true 且无 verifiedClaims → 显示"正在验证…"小字提示
 * - verifiedClaims 已到 → 显示可信度面板而非"正在验证…"
 * - isStreaming（流式生成中）→ 不显示"正在验证…"
 *
 * 实现说明：mock ragService.submitFeedback；antd 组件保持真实渲染，
 * 仅 spy message.success/error（拦截 Toast 副作用，断言调用参数）。
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import ChatMessage from '../components/ChatMessage';
import { message } from 'antd';

vi.mock('../services/ragService', () => ({
  submitFeedback: vi.fn(),
}));

import { submitFeedback } from '../services/ragService';

describe('ChatMessage 反馈按钮（module-048 WP2）', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
    // 拦截 antd message 副作用（不渲染真实 Toast DOM），断言调用参数
    vi.spyOn(message, 'success').mockImplementation(() => ({}) as never);
    vi.spyOn(message, 'error').mockImplementation(() => ({}) as never);
  });

  it('无 message_id 时隐藏 👍👎 按钮', () => {
    render(<ChatMessage role="assistant" content="测试回答" />);
    expect(screen.queryByTitle('有帮助')).not.toBeInTheDocument();
    expect(screen.queryByTitle('无帮助')).not.toBeInTheDocument();
  });

  it('AI 消息含 message_id 时展示 👍👎 按钮', () => {
    render(<ChatMessage role="assistant" content="测试回答" messageId={42} />);
    expect(screen.getByTitle('有帮助')).toBeInTheDocument();
    expect(screen.getByTitle('无帮助')).toBeInTheDocument();
  });

  it('用户消息即使有 message_id 也不展示反馈按钮', () => {
    render(<ChatMessage role="user" content="你好" messageId={42} />);
    expect(screen.queryByTitle('有帮助')).not.toBeInTheDocument();
    expect(screen.queryByTitle('无帮助')).not.toBeInTheDocument();
  });

  it('点击 👍 提交 rating=1 并 Toast 感谢反馈，进入已评态（不重复提交）', async () => {
    vi.mocked(submitFeedback).mockResolvedValue(undefined);
    render(<ChatMessage role="assistant" content="测试回答" messageId={42} />);
    fireEvent.click(screen.getByTitle('有帮助'));

    await waitFor(() => {
      expect(submitFeedback).toHaveBeenCalledWith({ message_id: 42, rating: 1 });
      expect(message.success).toHaveBeenCalledWith('感谢反馈');
    });
    await waitFor(() => {
      expect(screen.getByTitle('有帮助')).toBeDisabled();
      expect(screen.getByTitle('无帮助')).toBeDisabled();
    });
    expect(submitFeedback).toHaveBeenCalledTimes(1);
  });

  it('点击 👎 提交 rating=-1', async () => {
    vi.mocked(submitFeedback).mockResolvedValue(undefined);
    render(<ChatMessage role="assistant" content="测试回答" messageId={43} />);
    fireEvent.click(screen.getByTitle('无帮助'));

    await waitFor(() => {
      expect(submitFeedback).toHaveBeenCalledWith({ message_id: 43, rating: -1 });
      expect(message.success).toHaveBeenCalledWith('感谢反馈');
    });
  });

  it('已评消息再次点击（👍/👎）不重复提交', async () => {
    vi.mocked(submitFeedback).mockResolvedValue(undefined);
    render(<ChatMessage role="assistant" content="测试回答" messageId={44} />);
    fireEvent.click(screen.getByTitle('有帮助'));

    await waitFor(() => expect(submitFeedback).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByTitle('无帮助'));
    await waitFor(() => expect(submitFeedback).toHaveBeenCalledTimes(1));
    expect(message.success).toHaveBeenCalledTimes(1);
  });

  it('提交失败 Toast 失败提示，按钮未置已评态可重试', async () => {
    vi.mocked(submitFeedback).mockRejectedValueOnce(new Error('网络异常'));
    render(<ChatMessage role="assistant" content="测试回答" messageId={45} />);

    fireEvent.click(screen.getByTitle('有帮助'));
    await waitFor(() => {
      expect(message.error).toHaveBeenCalledWith('反馈提交失败，请重试');
    });

    // 未进入已评态 → 可重试成功
    vi.mocked(submitFeedback).mockResolvedValue(undefined);
    fireEvent.click(screen.getByTitle('有帮助'));
    await waitFor(() => {
      expect(message.success).toHaveBeenCalledWith('感谢反馈');
    });
    expect(submitFeedback).toHaveBeenCalledTimes(2);
  });
});

describe('ChatMessage verifying 态（module-060 verify 异步后置）', () => {
  it('verifying 且无 verifiedClaims → 显示"正在验证…"小字提示', () => {
    render(<ChatMessage role="assistant" content="测试回答" verifying />);
    expect(screen.getByText('正在验证…')).toBeInTheDocument();
  });

  it('verifiedClaims 已到 → 显示可信度面板而非"正在验证…"', () => {
    render(
      <ChatMessage
        role="assistant"
        content="测试回答"
        verifying
        verifiedClaims={{
          claims: [{ claim: '测试', verdict: 'supported', evidence: '[1]' }],
          overall_confidence: 1,
          total_claims: 1,
          supported: 1,
          inferred: 0,
          unsupported: 0,
        }}
      />,
    );
    expect(screen.queryByText('正在验证…')).not.toBeInTheDocument();
    expect(screen.getByText('可信度验证')).toBeInTheDocument();
  });

  it('isStreaming（流式生成中）→ 不显示"正在验证…"', () => {
    render(<ChatMessage role="assistant" content="测试回答" verifying isStreaming />);
    expect(screen.queryByText('正在验证…')).not.toBeInTheDocument();
  });

  it('用户消息不显示"正在验证…"', () => {
    render(<ChatMessage role="user" content="你好" verifying />);
    expect(screen.queryByText('正在验证…')).not.toBeInTheDocument();
  });
});
