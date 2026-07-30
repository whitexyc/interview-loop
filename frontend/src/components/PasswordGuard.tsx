import { useState, type ReactNode } from 'react';
import { Card, Input, Button, Typography, Space, Flex } from 'antd';
import { LockOutlined } from '@ant-design/icons';

const { Title, Text } = Typography;

const EDIT_PASSWORD = import.meta.env.VITE_EDIT_PASSWORD || 'white-xyc';

interface PasswordGuardProps {
  authKey: string;
  children: ReactNode;
  title?: string;
  description?: string;
}

/** 密码保护包装器：验证通过后才渲染 children */
export default function PasswordGuard({
  authKey,
  children,
  title = '验证身份',
  description = '请输入密码以继续',
}: PasswordGuardProps) {
  const [authed, setAuthedState] = useState(() => sessionStorage.getItem(authKey) === 'true');
  const [passwordInput, setPasswordInput] = useState('');
  const [passwordError, setPasswordError] = useState(false);

  if (authed) {
    return <>{children}</>;
  }

  const handleSubmit = () => {
    if (passwordInput === EDIT_PASSWORD) {
      sessionStorage.setItem(authKey, 'true');
      setAuthedState(true);
      setPasswordError(false);
    } else {
      setPasswordError(true);
    }
  };

  return (
    <Flex justify="center" align="center" style={{ minHeight: 240 }}>
      <Card
        style={{
          width: 400,
          borderRadius: 16,
          boxShadow: '0 1px 3px rgba(0,0,0,0.05), 0 1px 2px rgba(0,0,0,0.03)',
          border: '1px solid rgba(226,232,240,0.6)',
        }}
      >
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <div
            style={{
              width: 48,
              height: 48,
              borderRadius: 12,
              background: 'linear-gradient(135deg, #eff6ff, #dbeafe)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              margin: '0 auto 12px',
              color: '#1e40af',
              fontSize: 22,
            }}
          >
            <LockOutlined />
          </div>
          <Title level={5} style={{ margin: 0, color: '#0f172a' }}>
            {title}
          </Title>
          <Text type="secondary" style={{ display: 'block', marginTop: 4 }}>
            {description}
          </Text>
        </div>
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Input.Password
            placeholder="请输入密码"
            value={passwordInput}
            onChange={(e) => {
              setPasswordInput(e.target.value);
              setPasswordError(false);
            }}
            onPressEnter={handleSubmit}
            status={passwordError ? 'error' : undefined}
            size="large"
            variant="filled"
            style={{ borderRadius: 8 }}
          />
          {passwordError && (
            <Text type="danger" style={{ fontSize: 13 }}>
              密码错误，请重试
            </Text>
          )}
          <Button
            type="primary"
            block
            size="large"
            shape="round"
            onClick={handleSubmit}
            style={{ height: 44 }}
          >
            确认
          </Button>
        </Space>
      </Card>
    </Flex>
  );
}
