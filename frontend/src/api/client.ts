/**
 * # 统一请求封装（module-032 JWT 登录）
 *
 * ## 职责
 * 提供带登录态的 HTTP 请求基础设施：
 * - token 存取（localStorage），供 AuthContext 与请求层共享
 * - 统一 axios 实例工厂：请求时自动附加 `Authorization: Bearer <token>`
 * - 预置 `/api`（Java 8080）与 `/ai`（Python AI 8000）两个实例
 *
 * ## 为什么统一
 * 避免各 service 各自创建 axios 实例而漏带 token，保证登录后 Java 与
 * AI 服务都能识别用户身份（跨栈契约：前端→/api 与 /ai 均附 Bearer 头）。
 */
import axios from 'axios';
import type { AxiosInstance, InternalAxiosRequestConfig } from 'axios';

/** localStorage 中 token 的存储键名 */
const TOKEN_KEY = 'auth_token';

/**
 * 读取当前登录 token
 * @returns token 字符串；未登录返回 null
 */
export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

/**
 * 保存登录 token 到 localStorage
 * @param token - 后端签发的 JWT
 */
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

/**
 * 清除登录 token（退出登录时调用）
 */
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

/**
 * 构造 Authorization 请求头
 * @returns 存在 token 时 `{ Authorization: 'Bearer <token>' }`，否则空对象
 */
export function authHeader(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * 创建统一 axios 实例：请求时自动附加 Authorization 头
 *
 * 请求拦截器在每次请求发出前读取 localStorage 中的 token，
 * 存在则写入 `Authorization: Bearer <token>`，供 Java/AI 服务识别用户。
 *
 * @param baseURL - '/api'（Java）或 '/ai'（Python AI）
 * @param timeout - 超时毫秒数
 * @returns 已挂载请求拦截器的 axios 实例
 */
export function createHttp(baseURL: string, timeout = 10000): AxiosInstance {
  const http = axios.create({ baseURL, timeout });
  http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
    const token = getToken();
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  });
  return http;
}

/** Java 后端实例（经 Vite 代理 → http://localhost:8080） */
export const apiHttp = createHttp('/api', 10000);

/** Python AI 服务实例（经 Vite 代理 → http://localhost:8000，RAG 链路耗时较长） */
export const aiHttp = createHttp('/ai', 60000);
