/**
 * 会话与消息类型定义
 * <p>M9: 聊天记录持久化 — 前端类型</p>
 */

import type { SourceItem, VerifiedClaim } from './rag';

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
  /** 证据链验证结果（module-039：后端 verified event 推送后设置，无验证时为 undefined） */
  verifiedClaims?: {
    claims: VerifiedClaim[];
    overall_confidence: number;
    total_claims: number;
    supported: number;
    inferred: number;
    unsupported: number;
  } | null;
  /** 异步 verify 进行中（module-060：答案先交付、验证后到，轮询 pending 期间为 true） */
  verifying?: boolean;
  sortOrder?: number;
  createdAt?: string;
}
