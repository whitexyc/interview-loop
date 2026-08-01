import { useState, type ReactNode } from 'react';
import { Modal, Input, Button, Typography, Space } from 'antd';
import { LockOutlined } from '@ant-design/icons';

const { Text } = Typography;

const EDIT_PASSWORD = import.meta.env.VITE_EDIT_PASSWORD || 'white-xyc';

interface PasswordGuardProps {
  authKey: string;
  children: ReactNode;
  title?: string;
  description?: string;
}

/** 密码保护包装器：点击 children 时弹出小型密码 Modal，验证通过后才渲染 children */
export default function PasswordGuard({
  authKey,
  children,
  title = '验证身份',
  description = '请输入密码以继续',
}: PasswordGuardProps) {
  const [authed, setAuthedState] = useState(() => sessionStorage.getItem(authKey) === 'true');
  const [modalOpen, setModalOpen] = useState(false);
  const [passwordInput, setPasswordInput] = useState('');
  const [passwordError, setPasswordError] = useState(false);

  if (authed) {
    return <>{children}</>;
  }

  const handleOpen = (e: React.MouseEvent) => {
    e.stopPropagation();
    setModalOpen(true);
    setPasswordInput('');
    setPasswordError(false);
  };

  const handleSubmit = () => {
    if (passwordInput === EDIT_PASSWORD) {
      sessionStorage.setItem(authKey, 'true');
      setAuthedState(true);
      setModalOpen(false);
    } else {
      setPasswordError(true);
    }
  };

  return (
    <>
      <div style={{ position: 'relative', display: 'inline-block' }}>
        {children}
        {/* 覆盖层：拦截 children 自身的点击事件，改为弹出密码框 */}
        <div
          onClick={handleOpen}
          style={{ position: 'absolute', inset: 0, cursor: 'pointer', zIndex: 1 }}
        />
      </div>
      <Modal
        title={null}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        footer={null}
        width={340}
        centered
        closable={false}
      >
        <div style={{ textAlign: 'center', padding: '8px 0' }}>
          <div
            style={{
              width: 40, height: 40, borderRadius: 10,
              background: 'linear-gradient(135deg, #eff6ff, #dbeafe)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              margin: '0 auto 10px', color: '#1e40af', fontSize: 18,
            }}
          >
            <LockOutlined />
          </div>
          <Text strong style={{ fontSize: 15, color: '#0f172a', display: 'block' }}>{title}</Text>
          <Text type="secondary" style={{ fontSize: 13, display: 'block', marginTop: 2, marginBottom: 16 }}>{description}</Text>
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <Input.Password
              placeholder="请输入密码"
              value={passwordInput}
              onChange={(e) => { setPasswordInput(e.target.value); setPasswordError(false); }}
              onPressEnter={handleSubmit}
              status={passwordError ? 'error' : undefined}
              size="middle"
              variant="filled"
              style={{ borderRadius: 6 }}
              autoFocus
            />
            {passwordError && <Text type="danger" style={{ fontSize: 13 }}>密码错误，请重试</Text>}
            <Button type="primary" block onClick={handleSubmit} style={{ borderRadius: 6 }}>
              确认
            </Button>
          </Space>
        </div>
      </Modal>
    </>
  );
}
