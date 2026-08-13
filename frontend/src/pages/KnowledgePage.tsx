import { useState, useEffect, useCallback } from 'react';
import { Table, Button, Popconfirm, message, Input, Typography, Modal, Upload, Flex, Alert } from 'antd';
import { DeleteOutlined, SearchOutlined, PlusOutlined, InboxOutlined, CheckCircleFilled, LoadingOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { listDocuments, deleteDocument, uploadDocumentFile } from '../services/ragService';
import type { DocumentInfo } from '../types/rag';
import PasswordGuard from '../components/PasswordGuard';
import LLMChainPanel from '../components/LLMChainPanel';

const { Title, Text } = Typography;
const { Dragger } = Upload;

const UPLOAD_STEPS = [
  { key: 'uploading', label: '上传中' },
  { key: 'chunking', label: '分块中' },
  { key: 'vectorizing', label: '向量化' },
  { key: 'done', label: '完成' },
];

export default function KnowledgePage() {
  const [docs, setDocs] = useState<DocumentInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const pageSize = 15;

  // ── 上传状态（M18） ──
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadStep, setUploadStep] = useState(0);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [duplicate, setDuplicate] = useState(false);
  const [fileName, setFileName] = useState('');

  const fetchDocs = useCallback(async (p: number) => {
    setLoading(true);
    try {
      const res = await listDocuments(p, pageSize);
      setDocs(res.documents);
      setTotal(res.total);
    } catch {
      message.error('加载文档列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  const simulateSteps = useCallback(async () => {
    setUploadStep(1); await new Promise((r) => setTimeout(r, 400));
    setUploadStep(2); await new Promise((r) => setTimeout(r, 600));
    setUploadStep(3); await new Promise((r) => setTimeout(r, 500));
    setUploadStep(4); await new Promise((r) => setTimeout(r, 300));
    setUploadStep(5);
  }, []);

  const handleFileDrop = useCallback(async (file: File) => {
    const name = file.name.replace(/\.[^.]+$/, '');
    setFileName(name); setUploadError(null); setDuplicate(false);
    setUploadStep(1);
    try {
      // module-064：多格式（含二进制 pdf/docx/xlsx）走原始文件字节上传
      setTimeout(() => setUploadStep(2), 400);
      setTimeout(() => setUploadStep(3), 1000);
      const result = await uploadDocumentFile(file, name);
      if (result.duplicate) {
        setDuplicate(true); setUploadStep(0);
        setTimeout(() => setDuplicate(false), 3000);
      } else {
        await simulateSteps();
        setTimeout(() => { setUploadStep(0); setUploadOpen(false); fetchDocs(page); }, 1500);
      }
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : '上传失败');
      setUploadStep(0);
    }
    return false;
  }, [simulateSteps, fetchDocs, page]);

  const isUploading = uploadStep >= 1 && uploadStep <= 4;

  useEffect(() => { fetchDocs(page); }, [page, fetchDocs]);

  const handleDelete = async (id: number, title: string) => {
    try {
      await deleteDocument(id);
      message.success(`已删除「${title}」`);
      fetchDocs(docs.length === 1 && page > 1 ? page - 1 : page);
    } catch {
      message.error('删除失败');
    }
  };

  const filtered = search
    ? docs.filter(d => d.title.toLowerCase().includes(search.toLowerCase()))
    : docs;

  const columns: ColumnsType<DocumentInfo> = [
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
      width: '35%',
    },
    {
      title: '来源',
      dataIndex: 'source',
      key: 'source',
      ellipsis: true,
      width: '20%',
      render: (s: string) => s || '-',
    },
    {
      title: '分块数',
      dataIndex: 'chunk_count',
      key: 'chunk_count',
      width: 100,
      align: 'center',
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (t: string) => t ? t.slice(0, 10) : '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      align: 'center',
      render: (_, record) => (
        <Popconfirm
          title="确认删除"
          description={`删除「${record.title}」及其所有分块？`}
          onConfirm={() => handleDelete(record.id, record.title)}
          okText="删除"
          cancelText="取消"
          okButtonProps={{ danger: true }}
        >
          <Button type="text" danger icon={<DeleteOutlined />} size="small" />
        </Popconfirm>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Title level={4} style={{ margin: 0 }}>知识库管理</Title>
        <Flex gap={8}>
          <Input
            placeholder="搜索标题..."
            prefix={<SearchOutlined />}
            value={search}
            onChange={e => setSearch(e.target.value)}
            allowClear
            style={{ width: 280 }}
          />
          <PasswordGuard authKey="document_upload_auth" title="验证身份" description="请输入密码以管理知识库文档">
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setUploadOpen(true)}>
              上传文档
            </Button>
          </PasswordGuard>
        </Flex>
      </div>

      {/* LLM 供应商顺序设置（module-029：降级链动态调序） */}
      <div style={{ marginBottom: 20 }}>
        <LLMChainPanel />
      </div>

      <Table
        columns={columns}
        dataSource={filtered}
        rowKey="id"
        loading={loading}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: false,
          onChange: p => setPage(p),
          showTotal: t => `共 ${t} 篇`,
        }}
        locale={{ emptyText: '暂无文档' }}
      />

      {/* 上传 Modal（M18：将上传集成到知识库页面） */}
      <Modal
        title="上传文档到知识库"
        open={uploadOpen}
        onCancel={() => { if (!isUploading) setUploadOpen(false); }}
        footer={null}
        width={520}
        destroyOnHidden
      >
        {duplicate && (
          <Alert
            type="warning"
            message={`"${fileName}" 该文档已存在，已跳过`}
            showIcon closable
            onClose={() => setDuplicate(false)}
            style={{ marginBottom: 12, borderRadius: 6, fontSize: 12, padding: '6px 10px' }}
          />
        )}
        {uploadError && (
          <Alert
            type="error" message={uploadError} showIcon closable
            onClose={() => setUploadError(null)}
            style={{ marginBottom: 12, borderRadius: 6, fontSize: 12, padding: '6px 10px' }}
          />
        )}
        <Dragger
          name="file" multiple={false} accept=".md,.txt,.pdf,.docx,.xlsx,.pptx,.epub,.csv"
          beforeUpload={async (f) => { handleFileDrop(f as File); return false; }}
          showUploadList={false} disabled={isUploading}
          style={{ borderRadius: 12, overflow: 'hidden', padding: isUploading ? '16px 0' : '24px 0' }}
        >
          {isUploading ? (
            <Flex vertical align="center" gap={10} style={{ padding: '8px 0' }}>
              {UPLOAD_STEPS.map((step, i) => {
                const idx = i + 1;
                return (
                  <Flex key={step.key} gap={8} align="center">
                    {uploadStep > idx ? <CheckCircleFilled style={{ color: '#16a34a', fontSize: 14 }} />
                      : uploadStep === idx ? <LoadingOutlined style={{ color: '#1e40af', fontSize: 14 }} />
                      : <span style={{ width: 14, height: 14, borderRadius: 7, background: '#e2e8f0' }} />}
                    <Text style={{ fontSize: 14, color: uploadStep > idx ? '#16a34a' : uploadStep === idx ? '#1e40af' : '#cbd5e1' }}>
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
    </div>
  );
}
