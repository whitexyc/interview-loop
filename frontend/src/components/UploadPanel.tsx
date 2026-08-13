/**
 * # UploadPanel — 极简文档上传按钮
 *
 * ## 设计
 * - 默认：左侧栏顶部一个 "+" 圆形按钮 + "知识库"文字
 * - 点击：弹出 Modal，内含拖拽上传区域
 * - 密码保护：首次使用需验证密码
 *
 * ## 流程
 * 点击 → 密码验证(如未认证) → Modal 打开 → 拖拽文件 → 上传 → 完成
 */
import { useState, useCallback } from 'react';
import { Typography, Alert, Upload, Flex, Modal } from 'antd';
import { PlusOutlined, CheckCircleFilled, LoadingOutlined, InboxOutlined } from '@ant-design/icons';
import PasswordGuard from './PasswordGuard';
import { uploadDocumentFile } from '../services/ragService';

// 多格式上传（module-064）：与后端 document_parser.SUPPORTED_EXTENSIONS 同源
const ACCEPT_EXTENSIONS = '.md,.txt,.pdf,.docx,.xlsx,.pptx,.epub,.csv';

const { Text } = Typography;
const { Dragger } = Upload;

const UPLOAD_STEPS = [
  { key: 'uploading', label: '上传中' },
  { key: 'chunking', label: '分块中' },
  { key: 'vectorizing', label: '向量化' },
  { key: 'done', label: '完成' },
];

export default function UploadPanel() {
  const [modalOpen, setModalOpen] = useState(false);
  const [uploadStep, setUploadStep] = useState(0);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [duplicate, setDuplicate] = useState(false);
  const [fileName, setFileName] = useState('');

  const simulateSteps = useCallback(async () => {
    setUploadStep(1);
    await new Promise((r) => setTimeout(r, 400));
    setUploadStep(2);
    await new Promise((r) => setTimeout(r, 600));
    setUploadStep(3);
    await new Promise((r) => setTimeout(r, 500));
    setUploadStep(4);
    await new Promise((r) => setTimeout(r, 300));
    setUploadStep(5);
  }, []);

  const handleFileDrop = useCallback(
    async (file: File) => {
      const name = file.name.replace(/\.[^.]+$/, '');
      setFileName(name);
      setUploadError(null);
      setDuplicate(false);
      setUploadStep(1);

      try {
        // module-064：二进制格式（pdf/docx/xlsx/...）不能走 file.text()，
        // 直接传原始文件字节走统一解析管线
        setTimeout(() => setUploadStep(2), 400);
        setTimeout(() => setUploadStep(3), 1000);

        const result = await uploadDocumentFile(file, name);
        if (result.duplicate) {
          setDuplicate(true);
          setUploadStep(0);
          setTimeout(() => setDuplicate(false), 3000);
        } else {
          await simulateSteps();
          setTimeout(() => { setUploadStep(0); setModalOpen(false); }, 1500);
        }
      } catch (err) {
        setUploadError(err instanceof Error ? err.message : '上传失败');
        setUploadStep(0);
      }
      return false;
    },
    [simulateSteps],
  );

  const isUploading = uploadStep >= 1 && uploadStep <= 4;

  return (
    <PasswordGuard authKey="document_upload_auth" title="验证身份" description="请输入密码以管理知识库文档">
      {/* "+" 按钮 */}
      <Flex
        align="center"
        gap={8}
        style={{
          padding: '4px 0',
          cursor: 'pointer',
          borderRadius: 8,
          transition: 'background 0.15s',
        }}
        onClick={() => setModalOpen(true)}
        onMouseEnter={(e) => { e.currentTarget.style.background = '#f1f5f9'; }}
        onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
      >
        <div
          style={{
            width: 32,
            height: 32,
            borderRadius: 8,
            background: 'linear-gradient(135deg, #eff6ff, #dbeafe)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#1e40af',
            fontSize: 16,
            flexShrink: 0,
          }}
        >
          <PlusOutlined />
        </div>
        <Text strong style={{ fontSize: 14, color: '#0f172a' }}>知识库</Text>
      </Flex>

      {/* 上传 Modal */}
      <Modal
        title="上传文档到知识库"
        open={modalOpen}
        onCancel={() => { if (!isUploading) setModalOpen(false); }}
        footer={null}
        width={520}
        destroyOnHidden
      >
        {duplicate && (
          <Alert
            type="warning"
            message={`"${fileName}" 该文档已存在，已跳过`}
            showIcon
            closable
            onClose={() => setDuplicate(false)}
            style={{ marginBottom: 12, borderRadius: 6, fontSize: 12, padding: '6px 10px' }}
          />
        )}

        {uploadError && (
          <Alert
            type="error"
            message={uploadError}
            showIcon
            closable
            onClose={() => setUploadError(null)}
            style={{ marginBottom: 12, borderRadius: 6, fontSize: 12, padding: '6px 10px' }}
          />
        )}

        <Dragger
          name="file"
          multiple={false}
          accept={ACCEPT_EXTENSIONS}
          beforeUpload={handleFileDrop}
          showUploadList={false}
          disabled={isUploading}
          style={{
            borderRadius: 12,
            overflow: 'hidden',
            padding: isUploading ? '16px 0' : '24px 0',
            background: isUploading ? '#f8fafc' : undefined,
          }}
        >
          {isUploading ? (
            <Flex vertical align="center" gap={10} style={{ padding: '8px 0' }}>
              {UPLOAD_STEPS.map((step, i) => {
                const idx = i + 1;
                const done = uploadStep > idx;
                const active = uploadStep === idx;
                return (
                  <Flex key={step.key} gap={8} align="center">
                    {done ? (
                      <CheckCircleFilled style={{ color: '#16a34a', fontSize: 14 }} />
                    ) : active ? (
                      <LoadingOutlined style={{ color: '#1e40af', fontSize: 14 }} />
                    ) : (
                      <span style={{ width: 14, height: 14, borderRadius: 7, background: '#e2e8f0' }} />
                    )}
                    <Text style={{ fontSize: 14, color: done ? '#16a34a' : active ? '#1e40af' : '#cbd5e1' }}>
                      {step.label}
                    </Text>
                  </Flex>
                );
              })}
            </Flex>
          ) : (
            <Flex vertical align="center" gap={8} style={{ padding: '8px 0' }}>
              <InboxOutlined style={{ fontSize: 36, color: '#94a3b8' }} />
              <Text strong style={{ fontSize: 15, color: '#0f172a' }}>拖拽文件到此处</Text>
              <Text style={{ fontSize: 13, color: '#64748b' }}>
                或点击选择文件（支持 Markdown / 文本 / PDF / Word / Excel / PPT / EPUB / CSV）
              </Text>
            </Flex>
          )}
        </Dragger>
      </Modal>
    </PasswordGuard>
  );
}
