/**
 * 会话与消息类型定义
 * <p>M9: 聊天记录持久化 — 前端类型</p>
 */

import type { SourceItem } from './rag';

/** 会话摘要（列表项） */
export interface ConversationInfo {
  id: number;
  title: string;
  messageCount: number;
  updatedAt: string;
}

/** 服务端消息格式（含 DB 元数据，扩展了 role/content/sources） */
export interface MessageDTO {
  id?: number;
  conversationId?: number;
  role: 'user' | 'assistant';
  content: string;
  sources?: SourceItem[];
  sortOrder?: number;
  createdAt?: string;
}
