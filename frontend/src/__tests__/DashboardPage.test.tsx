/**
 * # DashboardPage 组件测试（module-085 WP-E）
 *
 * 覆盖（AC-28 / AC-25 / AC-31）：
 * - mock service fixture → 四指标核心数字渲染断言（请求总数/成功率%/P50/P95/
 *   token 总量/工具表首行）
 * - 请求失败 → Alert 提示不白屏
 * - 空数据（success_rate/latency 为 null）→ 显示"—"不显示 NaN/undefined
 *
 * 实现说明：vi.mock('../services/observabilityService') 整体替换 service 层；
 * jsdom 无 ResizeObserver（antd Table 依赖），本文件内 stub 不动共享 setup.ts。
 */
import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import DashboardPage from '../pages/DashboardPage';
import { getDashboard } from '../services/observabilityService';
import type { DashboardMetrics } from '../services/observabilityService';

vi.mock('../services/observabilityService', () => ({
  getDashboard: vi.fn(),
}));

beforeAll(() => {
  if (!('ResizeObserver' in globalThis)) {
    vi.stubGlobal(
      'ResizeObserver',
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    );
  }
});

/** 正常窗口 fixture（数字与 AC 对账示例同源） */
const FIXTURE: DashboardMetrics = {
  window: { hours: 24, since: '2026-09-05T12:00:00', generated_at: '2026-09-06T12:00:00' },
  requests: {
    total: 31,
    errors: 1,
    success_rate: 0.9667,
    by_endpoint: [{ endpoint: 'chat_stream', total: 14, errors: 0 }],
  },
  latency: { p50_ms: 4100.5, p95_ms: 8200.0, samples: 30 },
  cost: {
    total_prompt: 123456,
    total_completion: 23456,
    by_provider: [{ provider: 'deepseek', prompt_tokens: 100000, completion_tokens: 20000 }],
  },
  tools: {
    total: 467,
    by_tool: [{ tool_name: 'search_knowledge', calls: 285, failures: 0, duration_p95_ms: 4200.0 }],
  },
};

describe('DashboardPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('渲染四指标核心数字与工具表首行', async () => {
    vi.mocked(getDashboard).mockResolvedValue(FIXTURE);
    render(<DashboardPage />);
    await waitFor(() => {
      expect(screen.getByText('96.67%')).toBeInTheDocument();
    });
    expect(screen.getByText('31')).toBeInTheDocument(); // 请求总数
    expect(screen.getByText('错误 1')).toBeInTheDocument(); // 副行错误数
    expect(screen.getByText('4100.5 ms')).toBeInTheDocument(); // P50
    expect(screen.getByText('8200.0 ms')).toBeInTheDocument(); // P95
    expect(screen.getByText('146912')).toBeInTheDocument(); // token 总量
    expect(screen.getByText('search_knowledge')).toBeInTheDocument(); // 工具表
    expect(screen.getByText('285')).toBeInTheDocument();
  });

  it('请求失败显示 Alert 不白屏（后端 fail-open msg 透传）', async () => {
    vi.mocked(getDashboard).mockRejectedValue(new Error('看板查询失败（fail-open）'));
    render(<DashboardPage />);
    await waitFor(() => {
      expect(screen.getByText(/看板查询失败：看板查询失败（fail-open）/)).toBeInTheDocument();
    });
    expect(screen.queryByText('96.67%')).not.toBeInTheDocument();
  });

  it('空窗口 null 显示"—"（不显示 NaN/undefined/0%）', async () => {
    vi.mocked(getDashboard).mockResolvedValue({
      ...FIXTURE,
      requests: { total: 0, errors: 0, success_rate: null, by_endpoint: [] },
      latency: null,
      cost: { total_prompt: 0, total_completion: 0, by_provider: [] },
      tools: { total: 0, by_tool: [] },
    });
    render(<DashboardPage />);
    await waitFor(() => {
      // 请求总数 0 与 token 总量 0 两处 Statistic 均正常渲染（0 不是伪造的
      // 成功率/延迟——null 语义仍显示"—"）
      expect(screen.getAllByText('0').length).toBeGreaterThanOrEqual(2);
    });
    expect(screen.getByText('错误 0')).toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(3); // 成功率 + P50 + P95
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument();
    expect(screen.queryByText(/undefined/)).not.toBeInTheDocument();
  });
});
