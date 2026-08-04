/**
 * # LoginPage — 登录 / 注册页（module-032 JWT 登录）
 *
 * 单表单 + Segmented 切换登录/注册模式：
 * - 登录：POST /api/auth/login → 存 token → 跳转首页
 * - 注册：POST /api/auth/register → 自动登录（注册不返回 token）→ 跳转首页
 *
 * 错误通过内联 Alert 展示，不强制登录（未登录用户仍可访问公开页面）。
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Alert, Button, Card, Form, Input, Segmented, Typography } from 'antd';
import { LockOutlined, UserOutlined } from '@ant-design/icons';
import { useAuth } from '../auth/AuthContext';

type Mode = 'login' | 'register';

interface FormValues {
  username: string;
  password: string;
}

export default function LoginPage() {
  const navigate = useNavigate();
  const { login, register } = useAuth();
  const [mode, setMode] = useState<Mode>('login');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** 提交：按当前模式调登录或注册，成功后跳转首页 */
  const handleFinish = async (values: FormValues) => {
    setSubmitting(true);
    setError(null);
    try {
      if (mode === 'login') {
        await login(values.username, values.password);
      } else {
        await register(values.username, values.password);
      }
      navigate('/');
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#f0f5f9',
      }}
    >
      <Card style={{ width: 380 }} styles={{ body: { padding: 32 } }}>
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <Typography.Title level={3} style={{ marginBottom: 4 }}>
            张三
          </Typography.Title>
          <Typography.Text type="secondary">登录后记忆按用户隔离</Typography.Text>
        </div>

        <Segmented
          block
          value={mode}
          onChange={(value) => setMode(value as Mode)}
          options={[
            { label: '登录', value: 'login' },
            { label: '注册', value: 'register' },
          ]}
          style={{ marginBottom: 24 }}
        />

        {error && (
          <Alert type="error" message={error} showIcon style={{ marginBottom: 16 }} />
        )}

        <Form<FormValues>
          name="auth"
          onFinish={handleFinish}
          layout="vertical"
          requiredMark={false}
        >
          <Form.Item
            name="username"
            label="用户名"
            rules={[
              { required: true, message: '请输入用户名' },
              { min: 2, max: 32, message: '用户名长度 2-32 个字符' },
            ]}
          >
            <Input prefix={<UserOutlined />} placeholder="用户名" autoComplete="username" />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[
              { required: true, message: '请输入密码' },
              { min: 6, message: '密码至少 6 位' },
            ]}
          >
            <Input.Password
              prefix={<LockOutlined />}
              placeholder="密码"
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <Button type="primary" htmlType="submit" block loading={submitting}>
              {mode === 'login' ? '登录' : '注册'}
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}
