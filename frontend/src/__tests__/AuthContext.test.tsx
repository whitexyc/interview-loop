/**
 * # AuthContext 单元测试（module-032）
 *
 * 覆盖（验收 §4.1 前端登录态单测）：
 * - 初始未登录
 * - 登录成功：写 localStorage + 更新 token/user 状态
 * - 登录失败：抛错、不写登录态
 * - 注册成功：自动登录（先 register 后 login）
 * - 退出登录：清空 token + user + localStorage
 * - 启动时从 localStorage 恢复登录态
 *
 * 只 mock apiHttp（client.ts 的 axios 实例），保留真实 localStorage 存取逻辑，
 * 因此能验证 token 是否真的写入 localStorage。
 */
import { useState } from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { AuthProvider, useAuth } from '../auth/AuthContext';
import { apiHttp } from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiHttp: { post: vi.fn() } };
});

const postMock = vi.mocked(apiHttp.post);

/** 探测组件：把登录态渲染出来 + 暴露 login/register/logout 触发按钮与错误信息 */
function AuthProbe() {
  const { user, token, login, register, logout } = useAuth();
  const [err, setErr] = useState('');
  return (
    <div>
      <span data-testid="token">{token ?? 'none'}</span>
      <span data-testid="user">{user ? `${user.username}:${user.user_id}` : 'none'}</span>
      <button onClick={() => login('alice', 'secret1').catch((e: Error) => setErr(e.message))}>login</button>
      <button onClick={() => register('bob', 'secret1').catch((e: Error) => setErr(e.message))}>register</button>
      <button onClick={logout}>logout</button>
      <span data-testid="err">{err}</span>
    </div>
  );
}

function renderAuth() {
  return render(
    <AuthProvider>
      <AuthProbe />
    </AuthProvider>,
  );
}

describe('AuthContext 登录态管理', () => {
  beforeEach(() => {
    localStorage.clear();
    postMock.mockReset();
  });

  it('初始为未登录状态', () => {
    renderAuth();
    expect(screen.getByTestId('token')).toHaveTextContent('none');
    expect(screen.getByTestId('user')).toHaveTextContent('none');
  });

  it('登录成功后写入 localStorage 并更新状态', async () => {
    postMock.mockResolvedValue({
      data: { code: 0, data: { token: 'tok1', username: 'alice', user_id: 1 } },
    });
    renderAuth();

    fireEvent.click(screen.getByText('login'));

    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('alice:1'));
    expect(screen.getByTestId('token')).toHaveTextContent('tok1');
    expect(localStorage.getItem('auth_token')).toBe('tok1');
    expect(JSON.parse(localStorage.getItem('auth_user')!)).toEqual({ username: 'alice', user_id: 1 });
    expect(postMock).toHaveBeenCalledWith('/auth/login', { username: 'alice', password: 'secret1' });
  });

  it('登录失败（HTTP 4xx，后端 msg 字段）抛错且不写入登录态', async () => {
    postMock.mockRejectedValue({ response: { data: { code: 1, msg: '用户名或密码错误' } } });
    renderAuth();

    fireEvent.click(screen.getByText('login'));

    await waitFor(() => expect(screen.getByTestId('err')).toHaveTextContent('用户名或密码错误'));
    expect(screen.getByTestId('user')).toHaveTextContent('none');
    expect(localStorage.getItem('auth_token')).toBeNull();
  });

  it('登录失败（HTTP 200 且 body.code=1）抛错且不写入登录态', async () => {
    postMock.mockResolvedValue({ data: { code: 1, message: '用户名或密码错误' } });
    renderAuth();

    fireEvent.click(screen.getByText('login'));

    await waitFor(() => expect(screen.getByTestId('err')).toHaveTextContent('用户名或密码错误'));
    expect(screen.getByTestId('user')).toHaveTextContent('none');
  });

  it('注册失败（重复用户名）抛错', async () => {
    postMock.mockRejectedValue({ response: { data: { code: 1, msg: '用户名已存在' } } });
    renderAuth();

    fireEvent.click(screen.getByText('register'));

    await waitFor(() => expect(screen.getByTestId('err')).toHaveTextContent('用户名已存在'));
    expect(screen.getByTestId('user')).toHaveTextContent('none');
  });

  it('注册成功后自动登录（先 register 后 login）', async () => {
    postMock
      .mockResolvedValueOnce({ data: { code: 0, data: { user_id: 2 } } })
      .mockResolvedValueOnce({
        data: { code: 0, data: { token: 'tok2', username: 'bob', user_id: 2 } },
      });
    renderAuth();

    fireEvent.click(screen.getByText('register'));

    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('bob:2'));
    expect(postMock).toHaveBeenNthCalledWith(1, '/auth/register', { username: 'bob', password: 'secret1' });
    expect(postMock).toHaveBeenNthCalledWith(2, '/auth/login', { username: 'bob', password: 'secret1' });
    expect(localStorage.getItem('auth_token')).toBe('tok2');
  });

  it('退出登录清空 token、user 与 localStorage', async () => {
    postMock.mockResolvedValue({
      data: { code: 0, data: { token: 'tok1', username: 'alice', user_id: 1 } },
    });
    renderAuth();
    fireEvent.click(screen.getByText('login'));
    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('alice:1'));

    fireEvent.click(screen.getByText('logout'));

    expect(screen.getByTestId('token')).toHaveTextContent('none');
    expect(screen.getByTestId('user')).toHaveTextContent('none');
    expect(localStorage.getItem('auth_token')).toBeNull();
    expect(localStorage.getItem('auth_user')).toBeNull();
  });

  it('启动时从 localStorage 恢复登录态', () => {
    localStorage.setItem('auth_token', 'restored');
    localStorage.setItem('auth_user', JSON.stringify({ username: 'alice', user_id: 1 }));

    renderAuth();

    expect(screen.getByTestId('token')).toHaveTextContent('restored');
    expect(screen.getByTestId('user')).toHaveTextContent('alice:1');
  });
});
