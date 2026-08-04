import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ConfigProvider, theme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { AuthProvider } from './auth/AuthContext';
import AppLayout from './components/AppLayout';
import ResumePage from './pages/ResumePage';
import ChatPage from './pages/ChatPage';
import EditResumePage from './pages/EditResumePage';
import KnowledgePage from './pages/KnowledgePage';
import LoginPage from './pages/LoginPage';

const customTheme = {
  token: {
    colorPrimary: '#1e40af',
    colorInfo: '#0891b2',
    colorSuccess: '#059669',
    colorWarning: '#d97706',
    colorError: '#dc2626',
    borderRadius: 12,
    borderRadiusLG: 16,
    fontSize: 16,
    lineHeight: 1.5,
    colorBgLayout: '#f0f5f9',
    colorBorderSecondary: '#e2e8f0',
    colorText: '#0f172a',
    colorTextSecondary: '#475569',
    colorBgContainer: '#ffffff',
    colorBgElevated: '#ffffff',
    colorLink: '#1e40af',
    fontFamily:
      "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  },
  algorithm: theme.defaultAlgorithm,
};

export default function App() {
  return (
    <ConfigProvider locale={zhCN} theme={customTheme}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route
              path="/"
              element={
                <AppLayout>
                  <ResumePage />
                </AppLayout>
              }
            />
            <Route
              path="/chat"
              element={
                <AppLayout maxWidth="100%">
                  <ChatPage />
                </AppLayout>
              }
            />
            <Route
              path="/edit-resume"
              element={
                <AppLayout>
                  <EditResumePage />
                </AppLayout>
              }
            />
            <Route
              path="/knowledge"
              element={
                <AppLayout>
                  <KnowledgePage />
                </AppLayout>
              }
            />
            <Route path="/login" element={<LoginPage />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </ConfigProvider>
  );
}
