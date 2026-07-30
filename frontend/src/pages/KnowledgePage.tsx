import { useState, useEffect, useCallback } from 'react';
import { Table, Button, Popconfirm, message, Input, Typography } from 'antd';
import { DeleteOutlined, SearchOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { listDocuments, deleteDocument } from '../services/ragService';
import type { DocumentInfo } from '../types/rag';

const { Title } = Typography;

export default function KnowledgePage() {
  const [docs, setDocs] = useState<DocumentInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const pageSize = 15;

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
        <Input
          placeholder="搜索标题..."
          prefix={<SearchOutlined />}
          value={search}
          onChange={e => setSearch(e.target.value)}
          allowClear
          style={{ width: 280 }}
        />
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
    </div>
  );
}
