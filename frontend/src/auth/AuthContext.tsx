/**
 * # AuthContext — 前端登录态管理（module-032 JWT 登录）
 *
 * ## 职责
 * - 维护 token + user 登录态
 * - token 存 localStorage（api/client.ts 的 getToken/setToken/clearToken），启动时恢复
 * - 提供 login / register / logout
 *
 * ## 与请求封装的关系
 * 登录成功把 token 写入 localStorage，api/client.ts 的请求拦截器在每次
 * /api 与 /ai 请求时自动附加 `Authorization: Bearer <token>`。
 *
 * ## 注册设计
 * 注册接口（POST /api/auth/register）只返回 user_id、不返回 token，
 * 因此注册成功后自动再调一次登录接口拿 token，实现"注册即登录"。
 */
import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { apiHttp, clearToken, getToken, setToken } from '../api/client';

/** 登录用户信息（与后端契约一致：username + user_id） */
export interface AuthUser {
  username: string;
  user_id: number;
}

/** 登录态上下文值 */
export interface AuthContextValue {
  /** 当前用户；未登录为 null */
  user: AuthUser | null;
  /** JWT token；未登录为 null */
  token: string | null;
  /** 登录：成功写 localStorage + 更新状态；失败抛 Error */
  login: (username: string, password: string) => Promise<void>;
  /** 注册：成功后自动登录（注册接口不返回 token） */
  register: (username: string, password: string) => Promise<void>;
  /** 退出：清除 token 与用户态 */
  logout: () => void;
}

/**
 * 认证接口响应（跨栈契约）：
 * - 成功 `{code:0, data:{token, username, user_id}}`
 * - 失败 `{code:1, message}`
 */
interface AuthResponse {
  code: number;
  message?: string;
  msg?: string;
  data?: {
    token: string;
    username: string;
    user_id: number;
  } | null;
}

/** localStorage 中用户信息的存储键名 */
const USER_KEY = 'auth_user';

/** 从 localStorage 恢复用户信息（JSON 解析失败返回 null） */
function readStoredUser(): AuthUser | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

/** 解析认证响应错误信息（优先 message，兼容 Java CommonResult 的 msg） */
function errorMessage(body: AuthResponse, fallback: string): string {
  return body.message ?? body.msg ?? fallback;
}

/**
 * 认证接口失败信息提取（兼容两种失败形态）：
 * 1. HTTP 200 但 body.code=1（契约原始形态 `{code:1, message}`）
 * 2. HTTP 4xx AxiosError（后端 BusinessException 统一返回 400，body=`{code:1, msg}`）
 */
function authErrorMessage(err: unknown, fallback: string): string {
  const respData = (err as { response?: { data?: AuthResponse } } | undefined)?.response?.data;
  if (respData) {
    return errorMessage(respData, fallback);
  }
  return err instanceof Error ? err.message : fallback;
}

/**
 * 调认证接口并把失败统一转为带 message 的 Error
 * @returns 响应 body（成功形态 body.code=0）
 * @throws Error - 网络错误、HTTP 4xx 或业务失败（body.code=1）时
 */
async function postAuth(path: string, payload: unknown, fallback: string): Promise<AuthResponse> {
  try {
    const resp = await apiHttp.post<AuthResponse>(path, payload);
    return resp.data;
  } catch (err) {
    throw new Error(authErrorMessage(err, fallback));
  }
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

/** 登录态 Provider，挂载于应用根部 */
export function AuthProvider({ children }: { children: ReactNode }) {
  // 启动时从 localStorage 恢复登录态（惰性初始化只执行一次）
  const [token, setTokenState] = useState<string | null>(() => getToken());
  const [user, setUser] = useState<AuthUser | null>(() => readStoredUser());

  /** 登录：调 /api/auth/login，成功后写 localStorage + 更新状态 */
  const login = useCallback(async (username: string, password: string) => {
    const body = await postAuth('/auth/login', { username, password }, '登录失败');
    if (body.code !== 0 || !body.data) {
      throw new Error(errorMessage(body, '登录失败'));
    }
    const { token: nextToken, username: name, user_id } = body.data;
    setToken(nextToken);
    setTokenState(nextToken);
    const nextUser: AuthUser = { username: name, user_id };
    localStorage.setItem(USER_KEY, JSON.stringify(nextUser));
    setUser(nextUser);
  }, []);

  /** 注册：调 /api/auth/register，成功后自动登录拿 token */
  const register = useCallback(
    async (username: string, password: string) => {
      const body = await postAuth('/auth/register', { username, password }, '注册失败');
      if (body.code !== 0) {
        throw new Error(errorMessage(body, '注册失败'));
      }
      await login(username, password);
    },
    [login],
  );

  /** 退出：清除 token 与用户态 */
  const logout = useCallback(() => {
    clearToken();
    localStorage.removeItem(USER_KEY);
    setTokenState(null);
    setUser(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ token, user, login, register, logout }),
    [token, user, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/** 读取登录态上下文；必须在 <AuthProvider> 内使用 */
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth 必须在 <AuthProvider> 内使用');
  }
  return ctx;
}
