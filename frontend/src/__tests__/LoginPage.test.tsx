/**
 * # LoginPage 单元测试（module-032）
 *
 * 覆盖（验收 1.2「登录/注册页 表单可提交并跳转」）：
 * - 登录成功：调 /api/auth/login，写 token 并跳转首页
 * - 登录失败：显示后端错误信息，不跳转
 * - 注册成功：先 register 后自动 login，跳转首页
 *
 * 渲染时用 MemoryRouter 提供 /login 与 / 两个路由，验证跳转行为。
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import LoginPage from '../pages/LoginPage';
import { AuthProvider } from '../auth/AuthContext';
import { apiHttp } from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiHttp: { post: vi.fn() } };
});

const postMock = vi.mocked(apiHttp.post);

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<div>首页</div>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

function fillForm(username: string, password: string) {
  fireEvent.change(screen.getByPlaceholderText('用户名'), { target: { value: username } });
  fireEvent.change(screen.getByPlaceholderText('密码'), { target: { value: password } });
}

describe('LoginPage 登录 / 注册', () => {
  beforeEach(() => {
    localStorage.clear();
    postMock.mockReset();
  });

  it('渲染登录表单与标题', () => {
    renderLogin();
    expect(screen.getByText('张三')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('用户名')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('密码')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /登\s*录/ })).toBeInTheDocument();
  });

  it('登录成功：调 /auth/login、写 token 并跳转首页', async () => {
    postMock.mockResolvedValue({
      data: { code: 0, data: { token: 'tok1', username: 'alice', user_id: 1 } },
    });
    renderLogin();

    fillForm('alice', 'secret1');
    fireEvent.click(screen.getByRole('button', { name: /登\s*录/ }));

    await waitFor(() => expect(screen.getByText('首页')).toBeInTheDocument());
    expect(postMock).toHaveBeenCalledWith('/auth/login', { username: 'alice', password: 'secret1' });
    expect(localStorage.getItem('auth_token')).toBe('tok1');
  });

  it('登录失败（HTTP 400，后端 msg 字段）：显示错误信息，不跳转', async () => {
    postMock.mockRejectedValue({ response: { data: { code: 1, msg: '用户名或密码错误' } } });
    renderLogin();

    fillForm('alice', 'wrong-password');
    fireEvent.click(screen.getByRole('button', { name: /登\s*录/ }));

    await waitFor(() => expect(screen.getByText('用户名或密码错误')).toBeInTheDocument());
    expect(screen.queryByText('首页')).not.toBeInTheDocument();
  });

  it('注册成功：先 register 后自动 login，跳转首页', async () => {
    postMock
      .mockResolvedValueOnce({ data: { code: 0, data: { user_id: 2 } } })
      .mockResolvedValueOnce({
        data: { code: 0, data: { token: 'tok2', username: 'bob', user_id: 2 } },
      });
    renderLogin();

    fireEvent.click(screen.getByText('注册'));
    fillForm('bob', 'secret1');
    fireEvent.click(screen.getByRole('button', { name: /注\s*册/ }));

    await waitFor(() => expect(screen.getByText('首页')).toBeInTheDocument());
    expect(postMock).toHaveBeenNthCalledWith(1, '/auth/register', { username: 'bob', password: 'secret1' });
    expect(postMock).toHaveBeenNthCalledWith(2, '/auth/login', { username: 'bob', password: 'secret1' });
  });
});
