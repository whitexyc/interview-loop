import { apiHttp as http } from '../api/client';
import type { ApiResponse } from '../types/api';
import type { ResumeDTO } from '../types/resume';

/**
 * 获取简历数据
 * @returns ResumeDTO
 * @throws 网络错误或业务错误时抛出异常
 */
export async function getResume(): Promise<ResumeDTO> {
  const response = await http.get<ApiResponse<ResumeDTO>>('/v1/resume');
  const body = response.data;
  if (body.code !== 0 || body.data === null) {
    throw new Error(body.msg || '获取简历失败');
  }
  return body.data;
}

/**
 * 更新简历数据
 * @returns 更新后的 ResumeDTO
 */
export async function updateResume(data: ResumeDTO): Promise<ResumeDTO> {
  const response = await http.put<ApiResponse<ResumeDTO>>('/v1/resume', data);
  const body = response.data;
  if (body.code !== 0 || body.data === null) {
    throw new Error(body.msg || '更新简历失败');
  }
  return body.data;
}
