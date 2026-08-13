/**
 * # ChatMessage — 聊天气泡组件
 *
 * ## 组件职责
 * 渲染单条聊天消息，支持用户和 AI 两种角色：
 * - 用户消息：蓝色渐变气泡，右对齐
 * - AI 消息：白色气泡，左对齐，支持引用标记 [n] 解析和来源展示
 *
 * ## 数据流
 * ChatPage → ChatMessage (role / content / sources / onCitationClick)
 *          → parseCitations(content) 解析 [n] → 混合渲染文本段 + 可点击引用标签
 *
 * ## 引用解析设计
 * AI 回复中可能包含 [1][2] 这样的引用标记，指向知识库中的文档。
 * parseCitations() 利用正则 /\[(\d+)\]/g 将文本拆分为"普通文本"和"引用标记"两个类型，
 * 引用标记渲染为可点击的 Tag 组件，点击触发 onCitationClick 回调。
 *
 * ## 为什么不用 dangerouslySetInnerHTML？
 * 如果 AI 回复携带 HTML 标签，dangerouslySetInnerHTML 会执行脚本（XSS 风险）。
 * 用正则解析 + React JSX 渲染的方式是安全的，即使 [n] 出现在代码示例中也不会误解析。
 *
 * ## 为什么气泡用 max-width 72%？
 * 太宽的文字行在阅读时容易跳行，72% 在桌面和移动端都能保持舒适的阅读体验。
 */
import { useState } from 'react';
import { Button, Typography, message } from 'antd';
// 注：本仓库 @ant-design/icons@5.6.1 无 ThumbUp/ThumbDown 图标，👍/👎 用同形 Like/Dislike
import { LikeOutlined, DislikeOutlined } from '@ant-design/icons';
import { submitFeedback } from '../services/ragService';
import type { SourceItem, VerifiedClaim } from '../types/rag';

interface ChatMessageProps {
  role: 'user' | 'assistant';
  content: string;
  sources?: SourceItem[];
  onCitationClick?: (refIndex: number) => void;
  /** 持久化消息 ID（module-048：仅含 message_id 的 AI 回复展示反馈按钮） */
  messageId?: number;
  /** 是否正在流式输出（仅 AI 消息使用） */
  isStreaming?: boolean;
  /** 证据链验证结果（module-039；无验证数据时退化纯文本） */
  verifiedClaims?: {
    claims: VerifiedClaim[];
    overall_confidence: number;
    total_claims: number;
    supported: number;
    inferred: number;
    unsupported: number;
  } | null;
  /** 异步 verify 进行中（module-060：答案先交付、验证后到，轮询 pending 期间） */
  verifying?: boolean;
}

/**
 * 已反馈消息记录（module-048 反馈飞轮）：key = 持久化消息 id，value = 评级。
 * 模块级 Map + localStorage 双记录：组件重挂载（切会话）、页面刷新后
 * 同一 message_id 仍保持已评态，防止重复/冲突提交污染飞轮训练数据。
 */
const RATED_FEEDBACK_KEY = 'rag_feedback_rated';
const ratedMessages = loadRatedMessages();

function loadRatedMessages(): Map<number, 'up' | 'down'> {
  try {
    const raw = localStorage.getItem(RATED_FEEDBACK_KEY);
    if (!raw) return new Map();
    const parsed = JSON.parse(raw) as Record<string, 'up' | 'down'>;
    return new Map(Object.entries(parsed).map(([id, value]) => [Number(id), value]));
  } catch {
    return new Map();
  }
}

function persistRatedMessages(): void {
  try {
    localStorage.setItem(RATED_FEEDBACK_KEY, JSON.stringify(Object.fromEntries(ratedMessages)));
  } catch {
    /* localStorage 不可用时静默降级（本次会话内模块级 Map 仍生效） */
  }
}

/**
 * 解析 AI 回复中的引用标记 [n]
 *
 * 输入: "G1 GC 将堆分为 Region[1]，这是关键特性[2]"
 * 输出: [
 *   { type: 'text', value: 'G1 GC 将堆分为 Region' },
 *   { type: 'citation', refIndex: 1 },
 *   { type: 'text', value: '，这是关键特性' },
 *   { type: 'citation', refIndex: 2 },
 * ]
 *
 * 实现思路：
 * 1. 用全局正则 /\[(\d+)\]/g 逐步扫描文本
 * 2. 每次匹配到 [n]，将匹配前的文本和当前 [n] 分别压入结果数组
 * 3. 扫描完成后将剩余文本压入数组
 */
function parseCitations(
  text: string,
): Array<{ type: 'text'; value: string } | { type: 'citation'; refIndex: number }> {
  const parts: Array<
    { type: 'text'; value: string } | { type: 'citation'; refIndex: number }
  > = [];
  const regex = /\[(\d+)\]/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    // 提取匹配前的文本段
    if (match.index > lastIndex) {
      parts.push({ type: 'text', value: text.slice(lastIndex, match.index) });
    }
    // 提取匹配到的引用标记
    parts.push({ type: 'citation', refIndex: Number.parseInt(match[1], 10) });
    lastIndex = match.index + match[0].length;
  }

  // 剩余文本
  if (lastIndex < text.length) {
    parts.push({ type: 'text', value: text.slice(lastIndex) });
  }

  return parts;
}

/** 从 evidence 字段提取引用编号（如 "[1]" → 1） */
function parseEvidenceRef(evidence: string): number | null {
  const m = evidence.match(/^\[(\d+)\]$/);
  return m ? Number.parseInt(m[1], 10) : null;
}

export default function ChatMessage({
  role,
  content,
  sources,
  onCitationClick,
  messageId,
  isStreaming,
  verifiedClaims,
  verifying,
}: ChatMessageProps) {
  const isUser = role === 'user';

  /** 已评态（module-048）：组件 state 记录，初始值从模块级 Map 恢复 */
  const [rating, setRating] = useState<'up' | 'down' | null>(() =>
    messageId !== undefined ? ratedMessages.get(messageId) ?? null : null,
  );
  const [submitting, setSubmitting] = useState<'up' | 'down' | null>(null);

  /**
   * 提交反馈：👍 → rating=1，👎 → rating=-1
   * 成功后写入已评态（模块级 Map + localStorage），重复点击不重复提交；
   * 失败 Toast 提示且不置已评态（可重试），不阻塞聊天。
   */
  const handleRate = async (value: 'up' | 'down') => {
    if (messageId === undefined || rating !== null || submitting !== null) return;
    setSubmitting(value);
    try {
      await submitFeedback({ message_id: messageId, rating: value === 'up' ? 1 : -1 });
      ratedMessages.set(messageId, value);
      persistRatedMessages();
      setRating(value);
      message.success('感谢反馈');
    } catch {
      message.error('反馈提交失败，请重试');
    } finally {
      setSubmitting(null);
    }
  };

  return (
    <>
      <style>{`
        @keyframes blink-cursor {
          0%, 50% { opacity: 1; }
          51%, 100% { opacity: 0; }
        }
      `}</style>
      {/**
       * 消息行容器
     * row-reverse（用户）：气泡在右，头像在右
     * row（AI）：气泡在左，头像在左
     */}
    <div
      style={{
        display: 'flex',
        flexDirection: isUser ? 'row-reverse' : 'row',
        gap: 8,
        marginBottom: 10,
        alignItems: 'flex-start',
      }}
    >
      {/* 角色头像 — 32×32 圆形，区分用户 (U) 和 AI */}
      <div
        style={{
          width: 28,
          height: 28,
          borderRadius: 8,
          background: isUser
            ? 'linear-gradient(135deg, #1e40af, #2563eb)'   // 用户：深蓝渐变
            : 'linear-gradient(135deg, #0891b2, #22d3ee)',  // AI：青色渐变
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#fff',
          fontSize: 13,
          fontWeight: 600,
          flexShrink: 0,
          marginTop: 4,
        }}
      >
        {isUser ? 'U' : 'AI'}
      </div>

      {/* 聊天气泡 */}
      <div
        style={{
          maxWidth: '75%',
          padding: '10px 14px',
          borderRadius: isUser
            ? '18px 18px 4px 18px'     // 用户：右下角扁
            : '18px 18px 18px 4px',    // AI：左下角扁
          background: isUser
            ? 'linear-gradient(135deg, #1e40af, #2563eb)'  // 用户：深蓝渐变
            : '#ffffff',                                      // AI：纯白
          color: isUser ? '#fff' : '#0f172a',
          lineHeight: 1.7,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          boxShadow: isUser
            ? '0 2px 8px rgba(30,64,175,0.2)'
            : '0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)',
          border: isUser ? 'none' : '1px solid rgba(226,232,240,0.6)',
        }}
      >
        {isUser ? (
          /* 用户消息：纯文本 */
          <Typography.Text style={{ color: '#fff', margin: 0 }}>
            {content}
          </Typography.Text>
        ) : (
          /* AI 消息：混合渲染文本段 + 可点击引用标记 */
          <div>
            {parseCitations(content).map((part, i) =>
              part.type === 'citation' ? (
                /* 引用标记 [n]：紧凑浅蓝 badge，hover 加深 */
                <span
                  key={i}
                  style={{
                    display: 'inline-block',
                    padding: '0 5px',
                    fontSize: 12,
                    background: '#dbeafe',
                    color: '#1e40af',
                    border: '1px solid #93c5fd',
                    borderRadius: 3,
                    cursor: 'pointer',
                    verticalAlign: 'baseline',
                    lineHeight: '18px',
                    transition: 'all 0.15s ease',
                  }}
                  onClick={(e) => { e.stopPropagation(); onCitationClick?.(part.refIndex); }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = '#bfdbfe';
                    e.currentTarget.style.borderColor = '#60a5fa';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = '#dbeafe';
                    e.currentTarget.style.borderColor = '#93c5fd';
                  }}
                >
                  [{part.refIndex}]
                </span>
              ) : (
                /* 普通文本段 */
                <Typography.Text key={i} style={{ margin: 0, color: '#0f172a' }}>
                  {part.value}
                </Typography.Text>
              ),
            )}
            {/* 打字光标（流式输出中，2px 闪烁竖线） */}
            {!isUser && isStreaming && (
              <span
                style={{
                  display: 'inline-block',
                  width: 2,
                  height: 14,
                  background: '#1e40af',
                  marginLeft: 2,
                  verticalAlign: 'middle',
                  animation: 'blink-cursor 0.8s infinite',
                }}
              />
            )}
            {/* 异步 verify 进行中提示（module-060：答案先交付、验证后到；
                轮询 pending 期间小字提示，done 后走下方验证面板） */}
            {!isUser && !isStreaming && verifying && !verifiedClaims && (
              <div
                style={{
                  marginTop: 12,
                  paddingTop: 10,
                  borderTop: '1px solid #e2e8f0',
                }}
              >
                <Typography.Text style={{ fontSize: 12, color: '#94a3b8' }}>
                  正在验证…
                </Typography.Text>
              </div>
            )}
            {/* 证据链验证面板（module-039：逐句可信度 + 整体置信度进度条） */}
            {!isUser && !isStreaming && verifiedClaims && verifiedClaims.claims.length > 0 && (
              <div
                style={{
                  marginTop: 12,
                  paddingTop: 10,
                  borderTop: '1px solid #e2e8f0',
                }}
              >
                <Typography.Text
                  style={{ fontSize: 12, fontWeight: 600, color: '#64748b', display: 'block', marginBottom: 6 }}
                >
                  可信度验证
                </Typography.Text>
                {verifiedClaims.claims.map((claim, i) => {
                  const isSupported = claim.verdict === 'supported';
                  const isInferred = claim.verdict === 'inferred';
                  const color = isSupported ? '#16a34a' : isInferred ? '#ca8a04' : '#dc2626';
                  const badge = isSupported ? '✓' : isInferred ? '~' : '✗';
                  const bg = isSupported ? '#f0fdf4' : isInferred ? '#fefce8' : '#fef2f2';
                  const refNum = parseEvidenceRef(claim.evidence);
                  return (
                    <div
                      key={i}
                      style={{
                        display: 'flex',
                        alignItems: 'baseline',
                        gap: 6,
                        marginBottom: 3,
                        fontSize: 13,
                        lineHeight: 1.6,
                        padding: '2px 6px',
                        borderRadius: 4,
                        background: bg,
                      }}
                    >
                      <span
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          width: 18,
                          height: 18,
                          borderRadius: 9,
                          background: color,
                          color: '#fff',
                          fontSize: 11,
                          fontWeight: 700,
                          flexShrink: 0,
                        }}
                        title={claim.verdict}
                      >
                        {badge}
                      </span>
                      <span style={{ color: '#0f172a' }}>{claim.claim}</span>
                      {refNum !== null && onCitationClick && (
                        <span
                          style={{
                            display: 'inline-block',
                            padding: '0 4px',
                            fontSize: 11,
                            background: '#dbeafe',
                            color: '#1e40af',
                            border: '1px solid #93c5fd',
                            borderRadius: 3,
                            cursor: 'pointer',
                            lineHeight: '16px',
                            flexShrink: 0,
                            transition: 'all 0.15s ease',
                          }}
                          onClick={(e) => { e.stopPropagation(); onCitationClick(refNum); }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.background = '#bfdbfe';
                            e.currentTarget.style.borderColor = '#60a5fa';
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.background = '#dbeafe';
                            e.currentTarget.style.borderColor = '#93c5fd';
                          }}
                        >
                          [{refNum}]
                        </span>
                      )}
                    </div>
                  );
                })}
                {/* 整体置信度进度条 */}
                <div style={{ marginTop: 8 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                    <Typography.Text style={{ fontSize: 11, color: '#94a3b8' }}>
                      supported={verifiedClaims.supported} inferred={verifiedClaims.inferred} unsupported={verifiedClaims.unsupported}
                    </Typography.Text>
                    <Typography.Text style={{ fontSize: 11, fontWeight: 600, color: '#0f172a' }}>
                      {Math.round(verifiedClaims.overall_confidence * 100)}% 可信
                    </Typography.Text>
                  </div>
                  <div
                    style={{
                      width: '100%',
                      height: 5,
                      background: '#f1f5f9',
                      borderRadius: 3,
                      overflow: 'hidden',
                    }}
                  >
                    <div
                      style={{
                        width: `${Math.round(verifiedClaims.overall_confidence * 100)}%`,
                        height: '100%',
                        background: verifiedClaims.overall_confidence >= 0.8
                          ? 'linear-gradient(90deg, #16a34a, #22c55e)'
                          : verifiedClaims.overall_confidence >= 0.5
                            ? 'linear-gradient(90deg, #ca8a04, #eab308)'
                            : 'linear-gradient(90deg, #dc2626, #ef4444)',
                        borderRadius: 3,
                        transition: 'width 0.3s ease',
                      }}
                    />
                  </div>
                </div>
              </div>
            )}
            {/* 引用来源列表（气泡底部） */}
            {sources && sources.length > 0 && (
              <div
                style={{
                  marginTop: 10,
                  paddingTop: 8,
                  borderTop: '1px solid #e2e8f0',
                  fontSize: 12,
                  color: '#94a3b8',
                }}
              >
                <Typography.Text style={{ fontSize: 12, color: '#94a3b8' }}>
                  来源: {sources.map((s) => s.title).join(', ')}
                </Typography.Text>
              </div>
            )}
            {/* 反馈按钮（module-048 反馈飞轮：仅含 message_id 的已持久化 AI 回复展示，
                👍=1 / 👎=-1；已评态置灰 + 选中高亮，不重复提交） */}
            {!isUser && !isStreaming && messageId !== undefined && (
              <div style={{ marginTop: 8, display: 'flex', gap: 4 }}>
                <Button
                  size="small"
                  type={rating === 'up' ? 'primary' : 'text'}
                  icon={<LikeOutlined />}
                  title="有帮助"
                  disabled={rating !== null || submitting !== null}
                  loading={submitting === 'up'}
                  onClick={() => handleRate('up')}
                />
                <Button
                  size="small"
                  type={rating === 'down' ? 'primary' : 'text'}
                  icon={<DislikeOutlined />}
                  title="无帮助"
                  disabled={rating !== null || submitting !== null}
                  loading={submitting === 'down'}
                  onClick={() => handleRate('down')}
                />
              </div>
            )}
          </div>
        )}
      </div>
    </div>
    </>
  );
}
