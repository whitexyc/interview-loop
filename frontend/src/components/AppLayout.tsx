import { useNavigate, useLocation } from 'react-router-dom';
import { Layout, Typography, Menu, Button, Tooltip } from 'antd';
import { EditOutlined } from '@ant-design/icons';
import type { ReactNode } from 'react';

const { Header, Content } = Layout;

const navItems = [
  { key: '/', label: '个人简历' },
  { key: '/chat', label: '知识库问答' },
];

interface AppLayoutProps {
  children: ReactNode;
  maxWidth?: number | string;
}

export default function AppLayout({ children, maxWidth }: AppLayoutProps) {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <Layout style={{ minHeight: '100vh', background: '#f0f5f9' }}>
      <Header
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          position: 'sticky',
          top: 0,
          zIndex: 100,
          background: 'rgba(255,255,255,0.85)',
          backdropFilter: 'blur(12px)',
          WebkitBackdropFilter: 'blur(12px)',
          borderBottom: '1px solid rgba(226,232,240,0.6)',
          padding: '0 24px',
          height: 56,
        }}
      >
        <div
          style={{
            position: 'absolute',
            left: 24,
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            cursor: 'pointer',
            whiteSpace: 'nowrap',
          }}
          onClick={() => navigate('/')}
        >
          <div
            style={{
              width: 44,
              height: 44,
              borderRadius: 8,
              background: 'linear-gradient(135deg, #1e40af, #0891b2)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#fff',
              fontSize: 18,
              fontWeight: 700,
              flexShrink: 0,
            }}
          >
            熊
          </div>
          <Typography.Text strong style={{ fontSize: 16, color: '#0f172a', margin: 0 }}>
            张三
          </Typography.Text>
        </div>

        <Menu
          theme="light"
          mode="horizontal"
          selectedKeys={[location.pathname]}
          items={navItems}
          onClick={({ key }) => navigate(key)}
          style={{
            minWidth: 400,
            borderBottom: 'none',
            background: 'transparent',
            justifyContent: 'center',
          }}
        />
        {/* Edit button */}
        <Tooltip title="编辑简历（密码保护）">
          <Button
            type="text"
            icon={<EditOutlined />}
            onClick={() => navigate('/edit-resume')}
            style={{
              position: 'absolute',
              right: 24,
              color: '#64748b',
              fontSize: 16,
              width: 44,
              height: 44,
            }}
          />
        </Tooltip>
      </Header>
      <Content
        style={{
          padding: '24px 32px',
          maxWidth: maxWidth ?? 1200,
          margin: '0 auto',
          width: '100%',
        }}
      >
        {children}
      </Content>
    </Layout>
  );
}
