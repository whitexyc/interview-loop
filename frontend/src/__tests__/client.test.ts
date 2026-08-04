/**
 * # api/client.ts 单元测试（module-032）
 *
 * 覆盖（验收 §4.1 前端请求封装附加 header）：
 * - setToken/clearToken/getToken 读写 localStorage
 * - authHeader：无 token 返回空，有 token 返回 Bearer 头
 * - createHttp 请求拦截器：存在 token 时给 config.headers 附加 Authorization
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { getToken, setToken, clearToken, authHeader, createHttp } from '../api/client';

/** 读取 createHttp 创建的实例上的第一个请求拦截器（直接触发验证附加逻辑） */
function requestInterceptor(http: ReturnType<typeof createHttp>) {
  const handlers = (http.interceptors.request as unknown as {
    handlers: { fulfilled: (config: { headers: Record<string, unknown> }) => { headers: Record<string, unknown> } }[];
  }).handlers;
  return handlers[0].fulfilled;
}

describe('api/client.ts token 存取与 Authorization 附加', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('setToken/clearToken/getToken 读写 localStorage', () => {
    expect(getToken()).toBeNull();
    setToken('abc.def');
    expect(localStorage.getItem('auth_token')).toBe('abc.def');
    expect(getToken()).toBe('abc.def');
    clearToken();
    expect(localStorage.getItem('auth_token')).toBeNull();
    expect(getToken()).toBeNull();
  });

  it('authHeader 无 token 时返回空对象', () => {
    expect(authHeader()).toEqual({});
  });

  it('authHeader 有 token 时返回 Bearer 头', () => {
    setToken('abc.def');
    expect(authHeader()).toEqual({ Authorization: 'Bearer abc.def' });
  });

  it('createHttp 拦截器存在 token 时附加 Authorization', () => {
    const http = createHttp('/api');
    setToken('tok123');
    const config = requestInterceptor(http)({ headers: {} });
    expect(config.headers.Authorization).toBe('Bearer tok123');
  });

  it('createHttp 拦截器无 token 时不附加 Authorization', () => {
    const http = createHttp('/api');
    const config = requestInterceptor(http)({ headers: {} });
    expect(config.headers.Authorization).toBeUndefined();
  });
});
