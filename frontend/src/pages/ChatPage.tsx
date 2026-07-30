/**
 * # ChatPage — 知识库问答聊天页面
 *
 * ## 组件职责
 * 1. 管理聊天消息列表（用户消息 + AI 回复）
 * 2. 管理输入框状态（文本输入、发送、清空）
 * 3. 管理多会话（创建/切换/删除，持久化到后端）
 * 4. 展示 Agentic 执行流程管线（PipelinePanel）
 * 5. 处理加载 / 错误 / 空状态三种 UI 分支
 *
 * ## 数据流
 * 用户输入 → handleSend / handlePromptClick
 *          → doSend（统一发送入口）
 *            → chatStream()（调用 AI 后端，SSE 流式）
 *              → onStep（更新管线步骤）
 *              → onToken（逐字追加 AI 回复）
 *            → 流完成 → saveMessages()（持久化到 Java 后端）
 *            → setPipelineStep(6)（管线完成）
 *
 * ## 会话持久化（M9）
 * - 会话和消息存储在 PostgreSQL，通过 Java 后端 API 读写
 * - 首次使用时自动迁移 localStorage 中的历史消息到数据库
 * - 流式回复完成后自动保存，保存失败时静默降级（消息仍在 React 内存中）
 * - 会话切换时先保存当前会话再加载目标会话
 */
import { useState, useRef, useEffect, useCallback } from 'react';
import { Input, Button, Spin, Alert, Typography, Flex, Tag, Select, Popconfirm } from 'antd';
import { SendOutlined, BulbOutlined, PlusOutlined } from '@ant-design/icons';
import ChatMessage from '../components/ChatMessage';
import PipelinePanel from '../components/PipelinePanel';
import UploadPanel from '../components/UploadPanel';
import CitationModal from '../components/CitationModal';
import { chatStream } from '../services/ragService';
import type { SourceItem, PipelineSteps } from '../types/rag';
import type { ConversationInfo, MessageDTO } from '../types/conversation';
import {
  listConversations,
  createConversation,
  deleteConversation,
  getMessages,
  saveMessages,
} from '../services/conversationService';

/** 空状态提示词按钮 */
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
  // ── 聊天状态 ──
  const [messages, setMessages] = useState<MessageDTO[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [citationSources, setCitationSources] = useState<SourceItem[]>([]);
  const [citationVisible, setCitationVisible] = useState(false);
  const [pipelineStep, setPipelineStep] = useState(0);
  const [pipelineSteps, setPipelineSteps] = useState<PipelineSteps | null>(null);

  // ── 会话管理状态（M9） ──
  const [conversations, setConversations] = useState<ConversationInfo[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<number | null>(null);

  // ── ref ──
  const bottomRef = useRef<HTMLDivElement>(null);
  const pendingRef = useRef({ query: '', history: [] as { role: string; content: string }[] });
  const messagesRef = useRef<MessageDTO[]>([]);
  const saveSuppressed = useRef(false); // 挂载加载后跳过首次 save

  /** 同步 messages 到 ref（避免闭包过期） */
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  /**
   * 挂载时：加载会话列表 → 加载最近会话的消息
   * 如果数据库为空，尝试从 localStorage 迁移
   */
  useEffect(() => {
    (async () => {
      try {
        const list = await listConversations();
        if (list.length > 0) {
          setConversations(list);
          const msgs = await getMessages(list[0].id);
          setActiveConversationId(list[0].id);
          saveSuppressed.current = true;
          setMessages(msgs);
        } else {
          // 尝试从 localStorage 迁移
          const saved = localStorage.getItem('rag_chat_messages');
          if (saved) {
            try {
              const parsed = JSON.parse(saved);
              if (Array.isArray(parsed) && parsed.length > 0) {
                const conv = await createConversation();
                const dtos: MessageDTO[] = parsed.map((m: MessageDTO, i: number) => ({
                  role: m.role,
                  content: m.content,
                  sources: m.sources || [],
                  conversationId: conv.id,
                  sortOrder: i,
                }));
                await saveMessages(conv.id, dtos);
                localStorage.removeItem('rag_chat_messages');
                setConversations([conv]);
                setActiveConversationId(conv.id);
                saveSuppressed.current = true;
                setMessages(dtos);
                return;
              }
            } catch {
              // 迁移失败则创建空会话
            }
          }
          // 创建首个空会话
          const conv = await createConversation();
          setConversations([conv]);
          setActiveConversationId(conv.id);
        }
      } catch (err) {
        setError('加载会话失败: ' + (err instanceof Error ? err.message : ''));
      }
    })();
  }, []);

  /** 自动滚动到底部 */
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  /**
   * 统一发送逻辑（流式版）
   * 发送 → 流式展示 → 完成后自动持久化
   */
  const doSend = useCallback(async (text: string) => {
    if (loading || !activeConversationId) return;

    const history = messagesRef.current.map((m) => ({ role: m.role, content: m.content }));
    pendingRef.current = { query: text, history };

    setMessages((prev) => [...prev, { role: 'user', content: text }, { role: 'assistant', content: '' }]);
    setLoading(true);
    setError(null);
    setPipelineStep(1);
    setPipelineSteps(null);

    try {
      const data = await chatStream(text, history, (step, stepData) => {
        setPipelineSteps((prev) => {
          const updated = { ...(prev || {}) } as PipelineSteps;
          if (step === 'intent') updated.intent = stepData as PipelineSteps['intent'];
          if (step === 'retrieval') updated.retrieval = stepData as PipelineSteps['retrieval'];
          if (step === 'rerank') updated.rerank = stepData as PipelineSteps['rerank'];
          if (step === 'reflection') updated.reflection = stepData as PipelineSteps['reflection'];
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
  }, [loading, activeConversationId]);

  /** 流完成后自动保存（fire-and-forget，跳过挂载加载后的首次触发） */
  useEffect(() => {
    if (loading || !activeConversationId || messages.length === 0) return;
    if (saveSuppressed.current) { saveSuppressed.current = false; return; }
    const lastMsg = messages[messages.length - 1];
    if (lastMsg.role !== 'assistant' || !lastMsg.content) return;

    const dtos: MessageDTO[] = messages.map((m, i) => ({
      role: m.role,
      content: m.content,
      sources: m.sources || [],
      conversationId: activeConversationId,
      sortOrder: i,
    }));
    saveMessages(activeConversationId, dtos).catch(() => {
      // 保存失败静默降级
    });
  }, [messages, loading, activeConversationId]);

  /** 发送输入框内容 */
  const handleSend = useCallback(async () => {
    const trimmed = input.trim();
    if (!trimmed || loading) return;
    setInput('');
    await doSend(trimmed);
  }, [input, loading, doSend]);

  /** 点击提示词按钮直接发送 */
  const handlePromptClick = useCallback(async (text: string) => {
    await doSend(text);
  }, [doSend]);

  /** 失败重试：移除失败的消息对再发起 */
  const handleRetry = useCallback(async () => {
    const { query, history } = pendingRef.current;
    if (!query) { setError(null); return; }

    setLoading(true);
    setError(null);
    setPipelineStep(1);
    setPipelineSteps(null);

    setMessages((prev) => {
      const cleaned = [...prev];
      const len = cleaned.length;
      if (len >= 2
        && cleaned[len - 2].role === 'user'
        && cleaned[len - 1].role === 'assistant') {
        cleaned.splice(len - 2, 2);
      }
      return [...cleaned, { role: 'user', content: query }, { role: 'assistant', content: '' }];
    });

    try {
      const data = await chatStream(query, history, (step, stepData) => {
        setPipelineSteps((prev) => {
          const updated = { ...(prev || {}) } as PipelineSteps;
          if (step === 'intent') updated.intent = stepData as PipelineSteps['intent'];
          if (step === 'retrieval') updated.retrieval = stepData as PipelineSteps['retrieval'];
          if (step === 'rerank') updated.rerank = stepData as PipelineSteps['rerank'];
          if (step === 'reflection') updated.reflection = stepData as PipelineSteps['reflection'];
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

  // ── 会话管理操作（M9） ──

  /** 切换会话 */
  const handleSelectConversation = useCallback(async (id: number) => {
    if (id === activeConversationId) return;

    const currentMessages = messagesRef.current;
    if (activeConversationId && currentMessages.length > 0) {
      const dtos: MessageDTO[] = currentMessages.map((m, i) => ({
        role: m.role,
        content: m.content,
        sources: m.sources || [],
        conversationId: activeConversationId,
        sortOrder: i,
      }));
      try { await saveMessages(activeConversationId, dtos); } catch { /* 忽略 */ }
    }

    try {
      const msgs = await getMessages(id);
      setActiveConversationId(id);
      setMessages(msgs);
      setError(null);
      setPipelineStep(0);
      setPipelineSteps(null);
    } catch (err) {
      setError('加载消息失败: ' + (err instanceof Error ? err.message : ''));
    }
  }, [activeConversationId]);

  /** 新建会话 */
  const handleNewConversation = useCallback(async () => {
    try {
      const conv = await createConversation();
      setConversations((prev) => [conv, ...prev]);
      setActiveConversationId(conv.id);
      setMessages([]);
      setError(null);
      setPipelineStep(0);
      setPipelineSteps(null);
    } catch (err) {
      setError('创建会话失败: ' + (err instanceof Error ? err.message : ''));
    }
  }, []);

  /** 删除当前会话 */
  const handleDeleteConversation = useCallback(async () => {
    if (!activeConversationId || conversations.length <= 1) return;
    try {
      await deleteConversation(activeConversationId);
      const remaining = conversations.filter((c) => c.id !== activeConversationId);
      setConversations(remaining);
      if (remaining.length > 0) {
        const msgs = await getMessages(remaining[0].id);
        setActiveConversationId(remaining[0].id);
        setMessages(msgs);
      }
    } catch (err) {
      setError('删除会话失败: ' + (err instanceof Error ? err.message : ''));
    }
  }, [activeConversationId, conversations]);

  /**
   * 引用标记点击处理
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

  return (
    <Flex style={{ height: 'calc(100vh - 104px)', gap: 16 }}>
      {/* ====== 左栏 ====== */}
      <div style={{ width: 320, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <UploadPanel />
        <PipelinePanel currentStep={pipelineStep} steps={pipelineSteps} />
      </div>

      {/* ====== 右栏 ====== */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        {/* 会话选择器（M9） */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '8px 12px',
            background: '#fff',
            borderRadius: 12,
            marginBottom: 8,
            border: '1px solid rgba(226,232,240,0.6)',
            flexShrink: 0,
          }}
        >
          <Select
            value={activeConversationId}
            onChange={handleSelectConversation}
            style={{ flex: 1 }}
            options={conversations.map((c) => ({ value: c.id, label: c.title }))}
            placeholder="选择对话"
            loading={conversations.length === 0}
          />
          <Button size="small" onClick={handleNewConversation} icon={<PlusOutlined />}>
            新建
          </Button>
          <Popconfirm
            title="确定删除此对话？"
            onConfirm={handleDeleteConversation}
            okText="删除"
            cancelText="取消"
          >
            <Button size="small" danger disabled={conversations.length <= 1}>
              删除
            </Button>
          </Popconfirm>
        </div>

        {/* 消息列表 */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px 8px' }}>
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

        {/* 提示词按钮 */}
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

        {/* 输入框 */}
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
