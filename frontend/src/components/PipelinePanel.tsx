/**
 * # PipelinePanel — Agentic 执行流程（纵向自动展示）
 *
 * 纵向布局，每步按顺序从上到下排列，中间竖线连接。
 * 执行到哪步自动显示该步数据，无需点击展开。
 *
 * 状态映射：
 * - currentStep < stepIdx: 灰色 + "等待执行"
 * - currentStep === stepIdx: 蓝色 + 脉冲 + 实时数据
 * - currentStep > stepIdx: 绿色 + ✅ + 结果数据
 */
import { useCallback, useState } from 'react';
import { Typography, Flex, Input, Button, Spin, Empty } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import {
  BulbOutlined, SortAscendingOutlined, SyncOutlined, EditOutlined,
  CheckCircleFilled, LoadingOutlined, ToolOutlined,
} from '@ant-design/icons';
import { search } from '../services/ragService';
import type { PipelineSteps, SearchResult, ToolTrace } from '../types/rag';

const { Text } = Typography;

interface StepDef {
  key: string; icon: React.ReactNode; label: string; detail: string;
}
const STEPS: StepDef[] = [
  { key: 'intent',    icon: <BulbOutlined />,          label: '意图识别', detail: '闲聊/知识库' },
  { key: 'retrieval', icon: <SearchOutlined />,        label: '混合检索', detail: 'BM25 + 向量' },
  { key: 'rerank',    icon: <SortAscendingOutlined />, label: 'Rerank',   detail: '重排 Top 5' },
  { key: 'reflect',   icon: <SyncOutlined />,          label: '自我反思', detail: '充分/改写' },
  { key: 'generate',  icon: <EditOutlined />,          label: '生成回答', detail: '引用溯源' },
];

interface Props {
  currentStep: number;
  steps?: PipelineSteps | null;
  /** 工具轨迹（Agent 模式，module-029） */
  toolTrace?: ToolTrace[];
  /** Agent 模式：仅展示工具轨迹卡片，不展示固定管线步骤 */
  agentMode?: boolean;
}

export default function PipelinePanel({ currentStep, steps, toolTrace, agentMode }: Props) {
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);

  const handleSearch = useCallback(async () => {
    const t = searchQuery.trim();
    if (!t) return;
    setSearchLoading(true); setSearchError(null); setSearched(true);
    try {
      setSearchResults(await search(t));
    } catch (e) {
      setSearchError(e instanceof Error ? e.message : '搜索失败');
    } finally {
      setSearchLoading(false);
    }
  }, [searchQuery]);

  /** 单步渲染：图标 + 状态 + 摘要 + 自动展示数据 */
  const renderStep = (s: StepDef, idx: number) => {
    const stepNum = idx + 1;
    const isDone = currentStep > stepNum;
    const isActive = currentStep === stepNum;
    const isWaiting = currentStep < stepNum;

    return (
      <div key={s.key} style={{ position: 'relative' }}>
        {/* 步骤行 */}
        <Flex align="flex-start" gap={12} style={{ padding: '6px 0', position: 'relative', zIndex: 1 }}>
          {/* 圆形指示器 */}
          <div style={{
            width: 28, height: 28, borderRadius: 14, flexShrink: 0, marginTop: 1,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: isDone ? '#dcfce7' : isActive ? '#eff6ff' : '#f1f5f9',
            color: isDone ? '#16a34a' : isActive ? '#1e40af' : '#94a3b8',
            fontSize: 13,
            animation: isActive ? 'pulse 1.5s ease-in-out infinite' : 'none',
          }}>
            {isDone ? <CheckCircleFilled style={{ fontSize: 14 }} /> :
             isActive ? <LoadingOutlined style={{ fontSize: 14 }} /> : s.icon}
          </div>
          {/* 名称+摘要 */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <Text strong style={{ fontSize: 13, color: isDone ? '#16a34a' : isActive ? '#1e40af' : '#64748b' }}>
              {s.label}
              {isWaiting && <Text style={{ fontSize: 11, marginLeft: 6, color: '#94a3b8' }}>等待执行</Text>}
            </Text>
            <Text style={{ fontSize: 11, display: 'block', color: '#94a3b8' }}>{s.detail}</Text>
          </div>
        </Flex>

        {/* 步骤数据（自动显示，不需点击） */}
        {(isActive || isDone) && (
          <div style={{ padding: '4px 0 8px 40px' }}>
            {renderStepData(s.key)}
          </div>
        )}
      </div>
    );
  };

  /** 渲染步骤数据 */
  const renderStepData = (key: string) => {
    switch (key) {
      case 'intent': return renderIntent();
      case 'retrieval': return renderRetrieval();
      case 'rerank': return renderRerank();
      case 'reflect': return renderReflect();
      case 'generate': return renderGenerate();
      default: return null;
    }
  };

  const renderIntent = () => {
    if (!steps?.intent) return <Text style={{ fontSize: 11, color: '#94a3b8' }}>处理中...</Text>;
    const { label, confidence } = steps.intent;
    const low = confidence < 0.5;
    return (
      <Flex gap={8} wrap="wrap">
        <InfoChip label="分类" value={label} color={low ? '#dc2626' : '#1e40af'} />
        <InfoChip label="置信度" value={`${(confidence * 100).toFixed(1)}%`} color={low ? '#dc2626' : '#16a34a'} />
        {low && <Text style={{ fontSize: 11, color: '#dc2626' }}>偏低</Text>}
      </Flex>
    );
  };

  const renderRetrieval = () => (
    <Flex vertical gap={6}>
      {steps?.retrieval && (
        <Flex wrap="wrap" gap={4}>
          <InfoChip label="召回" value={`${steps.retrieval.count ?? '?'} 条`} />
          <InfoChip label="最高分" value={steps.retrieval.top_score?.toFixed(3) ?? 'N/A'} />
        </Flex>
      )}
      {/* 命中文档列表：只显示标题+分数 */}
      {((steps?.retrieval?.documents?.length ?? 0) > 0 || (steps?.retrieval?.previews?.length ?? 0) > 0) && (
        <Flex vertical gap={2}>
          {(steps?.retrieval?.documents ?? steps?.retrieval?.previews ?? []).slice(0, 5).map((d: any, i: number) => (
            <div key={i} style={{ padding: '3px 6px', borderRadius: 4, background: '#f8fafc', border: '1px solid #f1f5f9', display: 'flex', justifyContent: 'space-between' }}>
              <Text style={{ fontSize: 11 }} ellipsis={{ tooltip: d.title }}>{d.title}</Text>
              <Text style={{ fontSize: 10, color: '#94a3b8', flexShrink: 0, marginLeft: 4 }}>{(d.score ?? 0).toFixed(3)}</Text>
            </div>
          ))}
        </Flex>
      )}
      {/* 独立搜索框 */}
      <div style={{ borderTop: '1px solid #e2e8f0', paddingTop: 6 }}>
        <Flex gap={4} style={{ marginBottom: 4 }}>
          <Input size="small" placeholder="搜索..." value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)} onPressEnter={handleSearch}
            style={{ borderRadius: 6, fontSize: 12 }} />
          <Button type="primary" size="small" icon={<SearchOutlined />} onClick={handleSearch} loading={searchLoading} style={{ borderRadius: 6 }} />
        </Flex>
        {searchLoading && <Spin size="small" style={{ display: 'block', margin: '4px auto' }} />}
        {searchError && <Text type="danger" style={{ fontSize: 11 }}>{searchError}</Text>}
        {!searchLoading && !searchError && searched && searchResults.length === 0 &&
          <Empty description="未找到" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ margin: '2px 0' }} />}
        {!searchLoading && searchResults.length > 0 && (
          <Flex vertical gap={2}>
            {searchResults.map((item) => (
              <div key={item.id} style={{ padding: '3px 6px', borderRadius: 4, background: '#f8fafc', border: '1px solid #f1f5f9', display: 'flex', justifyContent: 'space-between' }}>
                <Text style={{ fontSize: 11 }} ellipsis={{ tooltip: item.title }}>{item.title}</Text>
                <Text style={{ fontSize: 10, color: '#94a3b8', flexShrink: 0, marginLeft: 4 }}>{item.score.toFixed(2)}</Text>
              </div>
            ))}
          </Flex>
        )}
        {!searchLoading && !searched && <Text style={{ fontSize: 11, color: '#94a3b8' }}>输入关键词检索</Text>}
      </div>
    </Flex>
  );

  const renderRerank = () => {
    if (!steps?.rerank) return <Text style={{ fontSize: 11, color: '#94a3b8' }}>处理中...</Text>;
    const { before, after } = steps.rerank;
    return (
      <Flex wrap="wrap" gap={4}>
        <InfoChip label="候选" value={`${before} 条`} />
        <InfoChip label="保留" value={`${after} 条`} color="#16a34a" />
        {before > after && <Text style={{ fontSize: 11, color: '#64748b' }}>过滤 {before - after} 条</Text>}
      </Flex>
    );
  };

  const renderReflect = () => {
    if (!steps?.reflection) return <Text style={{ fontSize: 11, color: '#94a3b8' }}>处理中...</Text>;
    const { sufficient, query_rewritten, rewritten_query } = steps.reflection;
    return (
      <Flex vertical gap={4}>
        <InfoChip label="充分性" value={sufficient ? '充分 ✓' : '不充分，二次检索'} color={sufficient ? '#16a34a' : '#d97706'} />
        {query_rewritten && rewritten_query && (
          <div style={{ padding: '4px 8px', borderRadius: 4, background: '#fefce8', border: '1px solid #fde68a' }}>
            <Text style={{ fontSize: 11 }}>改写: {rewritten_query}</Text>
          </div>
        )}
      </Flex>
    );
  };

  const renderGenerate = () => {
    if (currentStep >= 6) return <Text style={{ fontSize: 12, color: '#16a34a' }}>回答已生成至右侧聊天区</Text>;
    if (currentStep >= 5) return <Flex gap={6} align="center"><LoadingOutlined style={{ color: '#1e40af' }} /><Text style={{ fontSize: 12, color: '#64748b' }}>生成中...</Text></Flex>;
    return null;
  };

  /**
   * 工具轨迹卡片列表（module-029）
   * 每张卡片展示：工具名 + 参数 + 结果摘要；执行中蓝色 / 已完成绿色。
   */
  const renderToolTrace = () => {
    const trace = toolTrace ?? [];
    if (trace.length === 0) {
      return <Text style={{ fontSize: 11, color: '#94a3b8' }}>等待工具调用...</Text>;
    }
    return (
      <Flex vertical gap={6}>
        {trace.map((t, i) => (
          <div key={i} style={{ padding: '6px 8px', borderRadius: 6, background: '#f8fafc', border: '1px solid #e2e8f0' }}>
            <Flex justify="space-between" align="center">
              <Text strong style={{ fontSize: 12, color: '#0f172a' }}>{t.name}</Text>
              <Text style={{ fontSize: 10, color: t.status === 'done' ? '#16a34a' : '#1e40af' }}>
                {t.status === 'done' ? '已完成' : '执行中'}
              </Text>
            </Flex>
            <Text style={{ fontSize: 11, display: 'block', color: '#64748b', marginTop: 2 }}>
              参数: {JSON.stringify(t.args)}
            </Text>
            {t.result !== undefined && (
              <Text
                style={{ fontSize: 11, display: 'block', color: '#475569', marginTop: 2 }}
                ellipsis={{ tooltip: t.result }}
              >
                结果: {t.result.length > 120 ? `${t.result.slice(0, 120)}...` : t.result}
              </Text>
            )}
          </div>
        ))}
      </Flex>
    );
  };

  return (
    <div style={{
      background: '#fff', borderRadius: 12, padding: 16,
      border: '1px solid rgba(226,232,240,0.6)',
      boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
    }}>
      <Typography.Title level={5} style={{ marginBottom: 12, color: '#0f172a', fontSize: 15 }}>
        {agentMode ? 'Agent 工具轨迹' : 'Agentic 执行流程'}
      </Typography.Title>

      {agentMode ? (
        <div>{renderToolTrace()}</div>
      ) : (
        <div style={{ position: 'relative' }}>
          {/* 连接竖线 */}
          <div style={{
            position: 'absolute', left: 13, top: 10, bottom: 10, width: 2,
            background: '#e2e8f0', zIndex: 0,
          }} />

          {STEPS.map((s, i) => renderStep(s, i))}
        </div>
      )}

      {/* 非 Agent 模式：如后端也推了工具事件，在管线下方附加展示 */}
      {!agentMode && toolTrace && toolTrace.length > 0 && (
        <div style={{ marginTop: 12, borderTop: '1px solid #e2e8f0', paddingTop: 10 }}>
          <Flex gap={6} align="center" style={{ marginBottom: 8 }}>
            <ToolOutlined style={{ color: '#64748b', fontSize: 12 }} />
            <Text strong style={{ fontSize: 12, color: '#0f172a' }}>工具轨迹</Text>
          </Flex>
          {renderToolTrace()}
        </div>
      )}

      <style>{`
        @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.6; } }
      `}</style>
    </div>
  );
}

function InfoChip({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ padding: '2px 8px', borderRadius: 4, background: '#f1f5f9', border: '1px solid #e2e8f0' }}>
      <Text style={{ fontSize: 11, color: '#64748b' }}>{label}: </Text>
      <Text strong style={{ fontSize: 11, color: color || '#0f172a' }}>{value}</Text>
    </div>
  );
}
