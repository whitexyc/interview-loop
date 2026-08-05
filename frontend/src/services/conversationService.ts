/**
 * 会话管理 API 服务
 * <p>M9: 通过 Java 后端 (/api) 做会话和消息 CRUD</p>
 */
import { apiHttp as http } from '../api/client';
import type { ApiResponse } from '../types/api';
import type { ConversationInfo, MessageDTO } from '../types/conversation';

/** 列出所有会话 */
export async function listConversations(): Promise<ConversationInfo[]> {
  const response = await http.get<ApiResponse<ConversationInfo[]>>('/v1/conversations');
  const body = response.data;
  if (body.code !== 0) throw new Error(body.msg || '获取会话列表失败');
  return body.data || [];
}

/** 创建新会话 */
export async function createConversation(): Promise<ConversationInfo> {
  const response = await http.post<ApiResponse<ConversationInfo>>('/v1/conversations');
  const body = response.data;
  if (body.code !== 0) throw new Error(body.msg || '创建会话失败');
  return body.data!;
}

/** 删除会话 */
export async function deleteConversation(id: number): Promise<void> {
  const response = await http.delete<ApiResponse<unknown>>(`/v1/conversations/${id}`);
  const body = response.data;
  if (body.code !== 0) throw new Error(body.msg || '删除会话失败');
}

/** 获取会话消息 */
export async function getMessages(conversationId: number): Promise<MessageDTO[]> {
  const response = await http.get<ApiResponse<MessageDTO[]>>(`/v1/conversations/${conversationId}/messages`);
  const body = response.data;
  if (body.code !== 0) throw new Error(body.msg || '获取消息失败');
  return body.data || [];
}

/** 全量保存消息（PUT 替换） */
export async function saveMessages(conversationId: number, messages: MessageDTO[]): Promise<void> {
  const response = await http.put<ApiResponse<unknown>>(`/v1/conversations/${conversationId}/messages`, messages);
  const body = response.data;
  if (body.code !== 0) throw new Error(body.msg || '保存消息失败');
}
