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
import { Typography, Tag } from 'antd';
import type { SourceItem } from '../types/rag';

interface ChatMessageProps {
  role: 'user' | 'assistant';
  content: string;
  sources?: SourceItem[];
  onCitationClick?: (refIndex: number) => void;
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

export default function ChatMessage({
  role,
  content,
  sources,
  onCitationClick,
}: ChatMessageProps) {
  const isUser = role === 'user';

  return (
    /**
     * 消息行容器
     * row-reverse（用户）：气泡在右，头像在右
     * row（AI）：气泡在左，头像在左
     */
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
                /* 引用标记 [n]：可点击 Tag，弹出原文 Modal */
                <Tag
                  key={i}
                  color="#1e40af"
                  style={{
                    cursor: 'pointer',
                    margin: '0 2px',
                    borderRadius: 4,
                    padding: '8px 10px',
                    lineHeight: '28px',
                    fontSize: 16,
                    fontWeight: 600,
                  }}
                  onClick={(e) => { e.stopPropagation(); onCitationClick?.(part.refIndex); }}
                >
                  [{part.refIndex}]
                </Tag>
              ) : (
                /* 普通文本段 */
                <Typography.Text key={i} style={{ margin: 0, color: '#0f172a' }}>
                  {part.value}
                </Typography.Text>
              ),
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
          </div>
        )}
      </div>
    </div>
  );
}
