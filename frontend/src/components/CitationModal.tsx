import { Modal, Typography, Tag } from 'antd';
import type { SourceItem } from '../types/rag';

interface CitationModalProps {
  open: boolean;
  sources: SourceItem[];
  onClose: () => void;
}

/** 引用原文弹窗，点击 [n] 标记时展示对应原文片段 */
export default function CitationModal({ open, sources, onClose }: CitationModalProps) {
  return (
    <Modal
      title={
        <span style={{ color: '#0f172a', fontWeight: 600 }}>引用原文</span>
      }
      open={open}
      onCancel={(e) => { e?.stopPropagation?.(); onClose(); }}
      footer={null}
      width={640}
      getContainer={false}
    >
      {sources.length === 0 ? (
        <Typography.Text type="secondary">暂无引用来源</Typography.Text>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {sources.map((source) => (
            <div
              key={source.ref_index}
              style={{
                padding: 16,
                borderRadius: 10,
                border: '1px solid #e2e8f0',
                background: '#f8fafc',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginBottom: 8,
                }}
              >
                <Typography.Text strong style={{ fontSize: 15, color: '#0f172a' }}>
                  <Tag
                    color="#1e40af"
                    style={{ borderRadius: 4, marginRight: 6 }}
                  >
                    [{source.ref_index}]
                  </Tag>
                  {source.title}
                </Typography.Text>
                <Typography.Text style={{ fontSize: 13, color: '#94a3b8' }}>
                  {source.source}
                </Typography.Text>
              </div>
              <Typography.Paragraph
                style={{
                  fontSize: 14,
                  lineHeight: 1.7,
                  color: '#475569',
                  whiteSpace: 'pre-wrap',
                  margin: 0,
                }}
              >
                {source.content}
              </Typography.Paragraph>
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}
