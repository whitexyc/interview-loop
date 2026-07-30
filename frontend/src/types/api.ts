/**
 * 统一 API 响应包装（后端 Java CommonResult 格式）
 */
export interface ApiResponse<T> {
  code: number;
  msg: string;
  data: T | null;
  timestamp: number;
  request_id: string;
}
