/**
 * # 可观测看板页（module-085）
 *
 * 基于 request_logs / tool_call_logs 只读聚合的 4 指标看板：
 * 请求总数（副行错误数）/ 成功率 / 延迟 P50+P95 / token 用量（按供应商分桶），
 * 附按端点统计与工具调用统计表（含失败数与耗时 P95）。
 *
 * 交互：窗口 Select（24h/7d/30d/全部）+ 手动刷新按钮（不做自动轮询）。
 * null 语义（空窗口）：成功率 / 延迟显示"—"，不显示 NaN/undefined/0%。
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Alert, Button, Card, Col, Empty, Row, Select, Space, Spin, Statistic,
  Table, Typography,
} from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import {
  getDashboard,
  type DashboardMetrics,
  type EndpointStat,
  type ToolStat,
} from '../services/observabilityService';

/** 统计窗口选项（hours=0 表示全部数据，枚举约束无自由输入口） */
const WINDOW_OPTIONS = [
  { value: 24, label: '近 24 小时' },
  { value: 168, label: '近 7 天' },
  { value: 720, label: '近 30 天' },
  { value: 0, label: '全部' },
];

/** 空窗口 null 显示"—"；数值保留 1 位小数 + ms 单位 */
const fmtMs = (v: number | null | undefined) =>
  v === null || v === undefined ? '—' : `${v.toFixed(1)} ms`;

/** 成功率 0~1 → 百分比（2 位小数）；null → "—" */
const fmtRate = (v: number | null | undefined) =>
  v === null || v === undefined ? '—' : `${(v * 100).toFixed(2)}%`;

const ENDPOINT_COLUMNS = [
  { title: '端点', dataIndex: 'endpoint', key: 'endpoint' },
  { title: '请求数', dataIndex: 'total', key: 'total' },
  { title: '错误数', dataIndex: 'errors', key: 'errors' },
];

const TOOL_COLUMNS = [
  { title: '工具', dataIndex: 'tool_name', key: 'tool_name' },
  { title: '调用次数', dataIndex: 'calls', key: 'calls' },
  { title: '失败', dataIndex: 'failures', key: 'failures' },
  {
    title: '耗时 P95 (ms)',
    dataIndex: 'duration_p95_ms',
    key: 'duration_p95_ms',
    render: (v: number) => (v === null || v === undefined ? '—' : v.toFixed(1)),
  },
];

/** 指标卡片（Statistic 一律传字符串 + 关闭千分位分组，渲染确定可断言） */
function MetricCard(props: { title: string; value: string; sub?: string }) {
  return (
    <Card>
      <Statistic title={props.title} value={props.value} groupSeparator="" />
      {props.sub && (
        <Typography.Text type="secondary" style={{ fontSize: 13 }}>
          {props.sub}
        </Typography.Text>
      )}
    </Card>
  );
}

export default function DashboardPage() {
  const [hours, setHours] = useState(24);
  const [metrics, setMetrics] = useState<DashboardMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async (h: number) => {
    setLoading(true);
    setError('');
    try {
      setMetrics(await getDashboard(h));
    } catch (e) {
      setError(e instanceof Error ? e.message : '看板查询失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(hours);
  }, [load, hours]);

  const cost = metrics?.cost;
  const tokenTotal = cost ? cost.total_prompt + cost.total_completion : 0;

  return (
    <Space direction="vertical" style={{ width: '100%' }} size={16}>
      <Typography.Title level={3} style={{ marginBottom: 0 }}>
        观测看板
      </Typography.Title>

      <Space wrap>
        <Select
          value={hours}
          onChange={setHours}
          options={WINDOW_OPTIONS}
          style={{ width: 140 }}
        />
        <Button icon={<ReloadOutlined />} onClick={() => void load(hours)}>
          刷新
        </Button>
      </Space>

      {error && <Alert type="error" showIcon message={`看板查询失败：${error}`} />}

      {loading ? (
        <div style={{ textAlign: 'center', padding: 64 }}>
          <Spin size="large" />
        </div>
      ) : metrics ? (
        <>
          <Row gutter={[16, 16]}>
            <Col span={6}>
              <MetricCard
                title="请求总数"
                value={String(metrics.requests.total)}
                sub={`错误 ${metrics.requests.errors}`}
              />
            </Col>
            <Col span={6}>
              <MetricCard title="成功率" value={fmtRate(metrics.requests.success_rate)} />
            </Col>
            <Col span={6}>
              <MetricCard
                title="延迟 P50"
                value={fmtMs(metrics.latency?.p50_ms)}
                sub={`样本 ${metrics.latency?.samples ?? 0}`}
              />
            </Col>
            <Col span={6}>
              <MetricCard title="延迟 P95" value={fmtMs(metrics.latency?.p95_ms)} />
            </Col>
          </Row>

          <Card title="Token 用量（按供应商，成本口径不含金额换算）">
            <Statistic title="Token 总量" value={String(tokenTotal)} groupSeparator="" />
            <div style={{ marginTop: 8 }}>
              {cost?.by_provider.length ? (
                cost.by_provider.map((p) => (
                  <Typography.Text key={p.provider} style={{ marginRight: 16 }}>
                    {p.provider}：prompt {p.prompt_tokens} / completion{' '}
                    {p.completion_tokens}
                  </Typography.Text>
                ))
              ) : (
                <Typography.Text type="secondary">窗口内无 token 用量</Typography.Text>
              )}
            </div>
          </Card>

          <Card title="按端点统计">
            <Table<EndpointStat>
              rowKey="endpoint"
              size="small"
              columns={ENDPOINT_COLUMNS}
              dataSource={metrics.requests.by_endpoint}
              pagination={false}
            />
          </Card>

          <Card title="工具调用统计">
            <Table<ToolStat>
              rowKey="tool_name"
              size="small"
              columns={TOOL_COLUMNS}
              dataSource={metrics.tools.by_tool}
              pagination={false}
            />
          </Card>
        </>
      ) : (
        <Empty description="暂无数据" />
      )}
    </Space>
  );
}
