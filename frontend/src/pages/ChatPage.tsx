/**
 * # ChatPage — 知识库问答聊天页面
 *
 * ## 组件职责
 * 1. 管理聊天消息列表（用户消息 + AI 回复）
 * 2. 管理输入框状态（文本输入、发送、清空）
 * 3. 展示 Agentic 执行流程管线（PipelinePanel）
 * 4. 处理加载 / 错误 / 空状态三种 UI 分支
 *
 * ## 数据流
 * 用户输入 → handleSend / handlePromptClick
 *          → doSend（统一发送入口）
 *            → startPipeline（启动管线动画）
 *            → chat()（调用后端 API）
 *            → completePipeline（管线完成）
 *            → setMessages（追加 AI 回复）
 *
 * ## 状态设计
 * - messages: MessageItem[]        → 对话历史（纯展示，不参与 API 调用）
 * - input: string                  → 输入框受控值
 * - loading: boolean               → 请求进行中（禁用按钮 + spinner）
 * - error: string | null           → 错误信息（Alert 展示 + 重试）
 * - pipelineStep: 0-6             → 管线步骤动画状态
 *   - 0 = idle（未发送请求）
 *   - 1-5 = 步骤依次亮起
 *   - 6 = 全部完成
 *
 * ## 关键设计决策
 * 1. 为什么用 doSend 统一入口？
 *    无论是普通输入还是提示词点击，发送逻辑完全一致，
 *    避免 handleSend 和 handlePromptClick 重复实现。
 * 2. 为什么用 ref 存 pending 请求？
 *    useRef 不触发重渲染，适合存"当前正在处理的请求"，
 *    重试时需要取最后一次请求的参数。
 * 3. 为什么管线动画用 setTimeout 链？
 *    后端暂未返回中间步骤数据，前端模拟步骤流转
 *    让用户感知到"系统在工作"，减少等待焦虑。
 *    setTimeout 链用 ref 存储便于清理（组件卸载时取消）。
 */
import { useState, useRef, useEffect, useCallback } from 'react';
import { Input, Button, Spin, Alert, Typography, Flex, Tag } from 'antd';
import { SendOutlined, BulbOutlined } from '@ant-design/icons';
import ChatMessage from '../components/ChatMessage';
import PipelinePanel from '../components/PipelinePanel';
import UploadPanel from '../components/UploadPanel';
import CitationModal from '../components/CitationModal';
import { chatStream } from '../services/ragService';
import type { SourceItem, PipelineSteps } from '../types/rag';

/** 消息项：区分用户和 AI，AI 消息可附带引用来源 */
interface MessageItem {
  role: 'user' | 'assistant';
  content: string;
  sources?: SourceItem[];
}

/** 空状态提示词按钮 — 覆盖个人背景和技术知识两类 */
const promptSuggestions = [
  '我的学习情况',
  '我的比赛经历',
  '我在校表现',
  '我最近在学什么',
  '什么是G1 GC',
  'Java线程池原理',
  '什么是MoE',
  'Kafka为什么快',
];

export default function ChatPage() {
  // ── 核心状态 ──
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [citationSources, setCitationSources] = useState<SourceItem[]>([]);
  const [citationVisible, setCitationVisible] = useState(false);
  const [pipelineStep, setPipelineStep] = useState(0); // 0=idle, 1-5=processing, 6=done
  const [pipelineSteps, setPipelineSteps] = useState<PipelineSteps | null>(null); // 后端返回的步骤数据

  // ── ref（不触发重渲染，用于跨渲染周期保持数据） ──
  const bottomRef = useRef<HTMLDivElement>(null);           // 消息区底部锚点，用于自动滚动
  const pendingRef = useRef({ query: '', history: [] as { role: string; content: string }[] }); // 最后一次请求的参数（重试用）
  const STORAGE_KEY = 'rag_chat_messages';

  /** 启动时从 localStorage 恢复消息 */
  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length > 0) {
          setMessages(parsed);
        }
      }
    } catch {
      // localStorage 不可用时静默降级
    }
  }, []);

  /** 消息变化时自动持久化到 localStorage */
  useEffect(() => {
    if (messages.length > 0) {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
      } catch {
        // 存储满时静默失败
      }
    }
  }, [messages]);

  /** 自动滚动到底部：当 messages 变化时触发 */
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  /**
   * 统一发送逻辑（流式版）
   * 步骤：追加用户消息 → loading → 启动管线 → onStep 实时更新步骤数据
   *       → onToken 逐字追加到 AI 气泡 → API 完成 → 更新引用来源 → 管线完成
   */
  const doSend = useCallback(async (text: string) => {
    if (loading) return;
    const history = messages.map((m) => ({ role: m.role, content: m.content }));
    pendingRef.current = { query: text, history };

    // 追加用户消息 + 占位 AI 消息（onToken 逐步填充）
    setMessages((prev) => [...prev, { role: 'user', content: text }, { role: 'assistant', content: '' }]);
    setLoading(true);
    setError(null);
    setPipelineStep(1);
    setPipelineSteps(null);

    try {
      const data = await chatStream(text, history, (step, data) => {
        // onStep — 实时更新管线步骤
        setPipelineSteps((prev) => {
          const updated = { ...(prev || {}) } as PipelineSteps;
          if (step === 'intent') updated.intent = data as PipelineSteps['intent'];
          if (step === 'retrieval') updated.retrieval = data as PipelineSteps['retrieval'];
          if (step === 'rerank') updated.rerank = data as PipelineSteps['rerank'];
          if (step === 'reflection') updated.reflection = data as PipelineSteps['reflection'];
          return updated;
        });
        // 推进步骤指示器（1-indexed）
        const stepMap: Record<string, number> = { intent: 1, retrieval: 2, rerank: 3, reflection: 4 };
        const idx = stepMap[step];
        if (idx) setPipelineStep(idx);
      }, (token) => {
        // onToken — 逐字追加到 AI 消息
        setMessages((prev) => {
          const updated = [...prev];
          const lastIdx = updated.length - 1;
          if (lastIdx >= 0 && updated[lastIdx].role === 'assistant') {
            updated[lastIdx] = { ...updated[lastIdx], content: updated[lastIdx].content + token };
          }
          return updated;
        });
      });

      // 流结束后，更新引用来源 + 管线完成
      setMessages((prev) => {
        const updated = [...prev];
        const lastIdx = updated.length - 1;
        if (lastIdx >= 0 && updated[lastIdx].role === 'assistant') {
          updated[lastIdx] = { ...updated[lastIdx], sources: data.sources };
        }
        return updated;
      });
      setPipelineStep(5);
      setTimeout(() => setPipelineStep(6), 300);
    } catch (err) {
      setError(err instanceof Error ? err.message : '请求失败');
      setPipelineStep(6);
    } finally {
      setLoading(false);
    }
  }, [loading, messages]);

  /** 发送输入框内容 */
  const handleSend = useCallback(async () => {
    const trimmed = input.trim();
    if (!trimmed || loading) return;
    setInput('');
    await doSend(trimmed);
  }, [input, loading, doSend]);

  /** 点击提示词按钮直接发送（跳过输入框） */
  const handlePromptClick = useCallback(async (text: string) => {
    await doSend(text);
  }, [doSend]);

  /** 失败重试：重新发送上一次请求（取 pendingRef 中缓存的参数） */
  const handleRetry = useCallback(async () => {
    const { query, history } = pendingRef.current;
    if (!query) {
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    setPipelineStep(1);
    setPipelineSteps(null);
    setMessages((prev) => [...prev, { role: 'user', content: query }, { role: 'assistant', content: '' }]);

    try {
      const data = await chatStream(query, history, (step, data) => {
        setPipelineSteps((prev) => {
          const updated = { ...(prev || {}) } as PipelineSteps;
          if (step === 'intent') updated.intent = data as PipelineSteps['intent'];
          if (step === 'retrieval') updated.retrieval = data as PipelineSteps['retrieval'];
          if (step === 'rerank') updated.rerank = data as PipelineSteps['rerank'];
          if (step === 'reflection') updated.reflection = data as PipelineSteps['reflection'];
          return updated;
        });
        const stepMap: Record<string, number> = { intent: 1, retrieval: 2, rerank: 3, reflection: 4 };
        const idx = stepMap[step];
        if (idx) setPipelineStep(idx);
      }, (token) => {
        setMessages((prev) => {
          const updated = [...prev];
          const lastIdx = updated.length - 1;
          if (lastIdx >= 0 && updated[lastIdx].role === 'assistant') {
            updated[lastIdx] = { ...updated[lastIdx], content: updated[lastIdx].content + token };
          }
          return updated;
        });
      });

      setMessages((prev) => {
        const updated = [...prev];
        const lastIdx = updated.length - 1;
        if (lastIdx >= 0 && updated[lastIdx].role === 'assistant') {
          updated[lastIdx] = { ...updated[lastIdx], sources: data.sources };
        }
        return updated;
      });
      setPipelineStep(5);
      setTimeout(() => setPipelineStep(6), 300);
    } catch (err) {
      setError(err instanceof Error ? err.message : '请求失败');
      setPipelineStep(6);
    } finally {
      setLoading(false);
    }
  }, []);

  /**
   * 引用标记点击处理
   * 用户在 AI 消息中点击 [1][2] 标记时，查找对应的 SourceItem 并弹出 Modal 展示原文。
   * 查找策略：
   *   1. 优先从当前消息的 sources 中查找精确匹配 ref_index 的
   *   2. 找不到则兜底展示最近一条 AI 消息的所有来源
   */
  const handleCitationClick = useCallback(
    (refIndex: number) => {
      for (let i = messages.length - 1; i >= 0; i--) {
        const msg = messages[i];
        if (msg.sources && msg.sources.length > 0) {
          const source = msg.sources.find((s) => s.ref_index === refIndex);
          if (source) {
            setCitationSources([source]);
            setCitationVisible(true);
            return;
          }
        }
      }
      const lastAssistant = [...messages]
        .reverse()
        .find((m) => m.role === 'assistant' && m.sources && m.sources.length > 0);
      if (lastAssistant?.sources) {
        setCitationSources(lastAssistant.sources);
        setCitationVisible(true);
      }
    },
    [messages],
  );

  /**
   * 渲染 — 两栏布局
   * 左栏（260px）：上传面板 + 搜索面板 + Agentic 流程面板
   * 右栏（flex：占大部分宽度）：聊天消息 + 提示词 + 输入框
   */
  return (
    <Flex style={{ height: 'calc(100vh - 104px)', gap: 16 }}>
      {/* ====== 左栏：上传 + 管线 ====== */}
      <div style={{ width: 320, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <UploadPanel />
        <PipelinePanel currentStep={pipelineStep} steps={pipelineSteps} />
      </div>

      {/* ====== 右栏：聊天区域（占大部分宽度） ====== */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        {/* 消息列表（可滚动） */}
        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: '0 8px 8px',
          }}
        >
          {messages.length === 0 && !error && (
            <div style={{ textAlign: 'center', paddingTop: 40 }}>
              <div
                style={{
                  width: 48,
                  height: 48,
                  borderRadius: 14,
                  background: 'linear-gradient(135deg, #eff6ff, #dbeafe)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  margin: '0 auto 12px',
                  color: '#1e40af',
                  fontSize: 20,
                }}
              >
                <SendOutlined />
              </div>
              <Typography.Title level={5} style={{ color: '#0f172a', margin: 0, fontSize: 16 }}>
                知识库问答
              </Typography.Title>
              <Typography.Text type="secondary" style={{ marginTop: 2, display: 'block', fontSize: 14 }}>
                输入问题开始对话
              </Typography.Text>
            </div>
          )}

          {messages.map((msg, i) => (
            <ChatMessage
              key={i}
              role={msg.role}
              content={msg.content}
              sources={msg.sources}
              onCitationClick={handleCitationClick}
            />
          ))}

          {loading && (
            <div style={{ textAlign: 'center', padding: 20 }}>
              <Spin />
              <Typography.Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
                AI 思考中...
              </Typography.Text>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* 错误提示 */}
        {error && (
          <Alert
            type="error"
            message="请求失败"
            description={error}
            showIcon
            style={{ marginBottom: 8, borderRadius: 8, flexShrink: 0 }}
            action={
              <Button size="small" onClick={handleRetry}>
                重试
              </Button>
            }
          />
        )}

        {/* 提示词按钮 — 始终显示在输入框上方 */}
        <Flex justify="center" gap={6} wrap="wrap" style={{ marginBottom: 8 }}>
          {promptSuggestions.map((text) => (
            <Tag
              key={text}
              style={{
                cursor: 'pointer',
                borderRadius: 16,
                padding: '4px 12px',
                fontSize: 13,
                background: '#f1f5f9',
                border: '1px solid #e2e8f0',
                color: '#475569',
                transition: 'all 0.2s ease',
              }}
              onClick={() => handlePromptClick(text)}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = '#e2e8f0';
                e.currentTarget.style.color = '#0f172a';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = '#f1f5f9';
                e.currentTarget.style.color = '#475569';
              }}
            >
              <BulbOutlined style={{ marginRight: 4 }} />
              {text}
            </Tag>
          ))}
        </Flex>

        {/* 输入框区域 */}
        <div
          style={{
            background: '#fff',
            borderRadius: 12,
            border: '1px solid rgba(226,232,240,0.6)',
            boxShadow: '0 -2px 12px rgba(0,0,0,0.04)',
            padding: '10px 14px',
            flexShrink: 0,
          }}
        >
          <Flex gap={8} align="end">
            <Input.TextArea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onPressEnter={(e) => {
                if (!e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder="输入您的问题..."
              rows={2}
              variant="filled"
              disabled={loading}
              style={{ borderRadius: 8, fontSize: 15 }}
            />
            <Button
              type="primary"
              icon={<SendOutlined />}
              onClick={handleSend}
              loading={loading}
              disabled={!input.trim()}
              shape="circle"
              size="large"
              style={{
                width: 40,
                height: 40,
                flexShrink: 0,
                boxShadow: loading ? 'none' : '0 2px 8px rgba(30,64,175,0.25)',
              }}
            />
          </Flex>
        </div>
      </div>

      {/* 引用原文弹窗 */}
      <CitationModal
        open={citationVisible}
        sources={citationSources}
        onClose={() => setCitationVisible(false)}
      />
    </Flex>
  );
}
