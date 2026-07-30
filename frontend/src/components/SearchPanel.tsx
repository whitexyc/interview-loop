import { useState } from 'react';
import { Input, Button, List, Typography, Spin, Tag, Empty, Space, Flex } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { search } from '../services/ragService';
import type { SearchResult } from '../types/rag';

/** 截断文本到指定长度，保留完整单词/字符 */
function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen) + '…';
}

export default function SearchPanel() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);

  const handleSearch = async () => {
    const trimmed = query.trim();
    if (!trimmed) return;
    setLoading(true);
    setError(null);
    setSearched(true);
    try {
      const data = await search(trimmed);
      setResults(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '搜索失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        background: '#fff',
        borderRadius: 12,
        padding: 16,
        border: '1px solid rgba(226,232,240,0.6)',
        boxShadow: '0 1px 3px rgba(0,0,0,0.05), 0 1px 2px rgba(0,0,0,0.03)',
      }}
    >
      <Typography.Title level={5} style={{ marginBottom: 12, color: '#0f172a', fontSize: 15 }}>
        知识库检索
      </Typography.Title>

      <Space.Compact style={{ width: '100%', marginBottom: 12 }}>
        <Input
          placeholder="输入搜索关键词..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onPressEnter={handleSearch}
          size="small"
          style={{ borderRadius: '8px 0 0 8px', fontSize: 13 }}
        />
        <Button
          type="primary"
          icon={<SearchOutlined />}
          onClick={handleSearch}
          loading={loading}
          size="small"
          style={{ borderRadius: '0 8px 8px 0', fontSize: 13 }}
        >
          搜索
        </Button>
      </Space.Compact>

      {loading && (
        <div style={{ textAlign: 'center', padding: '16px 0' }}>
          <Spin size="small" />
        </div>
      )}

      {error && (
        <Typography.Text type="danger" style={{ fontSize: 12 }}>
          {error}
        </Typography.Text>
      )}

      {!loading && !error && searched && results.length === 0 && (
        <Empty description="未找到相关结果" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ margin: '16px 0' }} />
      )}

      {!loading && results.length > 0 && (
        <List
          dataSource={results}
          split={false}
          size="small"
          renderItem={(item) => (
            <List.Item style={{ padding: '6px 0', borderBottom: '1px solid #f1f5f9' }}>
              <div style={{ width: '100%', overflow: 'hidden' }}>
                <Typography.Text
                  strong
                  style={{ fontSize: 13, display: 'block' }}
                  ellipsis={{ tooltip: item.title }}
                >
                  {item.title}
                </Typography.Text>
                <Typography.Paragraph
                  style={{
                    fontSize: 12,
                    margin: '2px 0 4px',
                    color: '#64748b',
                    lineHeight: 1.4,
                  }}
                  ellipsis={{ rows: 2, tooltip: item.content }}
                >
                  {truncate(item.content, 100)}
                </Typography.Paragraph>
                <Flex gap={4} align="center" wrap="wrap">
                  <Tag
                    style={{
                      fontSize: 11,
                      borderRadius: 4,
                      border: 'none',
                      background: '#f1f5f9',
                      color: '#475569',
                      padding: '0 5px',
                      lineHeight: '18px',
                    }}
                  >
                    {item.source}
                  </Tag>
                  <Typography.Text style={{ fontSize: 11, color: '#94a3b8' }}>
                    评分: {item.score.toFixed(2)}
                  </Typography.Text>
                </Flex>
              </div>
            </List.Item>
          )}
        />
      )}

      {!loading && !error && !searched && (
        <div style={{ textAlign: 'center', padding: '16px 0', color: '#94a3b8' }}>
          <SearchOutlined style={{ fontSize: 20, marginBottom: 4 }} />
          <Typography.Text type="secondary" style={{ display: 'block', fontSize: 13 }}>
            输入关键词开始检索
          </Typography.Text>
        </div>
      )}
    </div>
  );
}
