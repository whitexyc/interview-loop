/**
 * # observabilityService 单元测试（module-085 WP-E）
 *
 * 覆盖（AC-26）：
 * - GET 路径与 hours params 透传（aiHttp mock 断言）
 * - code=0 解包 data 返回
 * - code!=0 抛 Error 含后端 msg（fail-open 提示透传）
 * - 网络异常原样上抛
 *
 * 实现说明：vi.mock('../api/client') mock aiHttp，不依赖真实后端。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api/client', () => ({
  aiHttp: { get: vi.fn() },
}));

import { aiHttp } from '../api/client';
import { getDashboard } from '../services/observabilityService';
import type { DashboardMetrics } from '../services/observabilityService';

const getMock = vi.mocked(aiHttp.get);

/** 响应契约 fixture（字段名与后端 plan §8 逐字一致） */
const FIXTURE: DashboardMetrics = {
  window: { hours: 24, since: '2026-09-05T12:00:00', generated_at: '2026-09-06T12:00:00' },
  requests: {
    total: 31,
    errors: 1,
    success_rate: 0.9677,
    by_endpoint: [{ endpoint: 'chat_stream', total: 14, errors: 0 }],
  },
  latency: { p50_ms: 4100.5, p95_ms: 8200.0, samples: 30 },
  cost: {
    total_prompt: 123456,
    total_completion: 23456,
    by_provider: [
      { provider: 'deepseek', prompt_tokens: 100000, completion_tokens: 20000 },
      { provider: 'llm', prompt_tokens: 23456, completion_tokens: 3456 },
    ],
  },
  tools: {
    total: 467,
    by_tool: [{ tool_name: 'search_knowledge', calls: 285, failures: 0, duration_p95_ms: 4200.0 }],
  },
};

describe('observabilityService.getDashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('GET /observability/dashboard 且 hours 走 params 透传', async () => {
    (getMock as any).mockResolvedValue({ data: { code: 0, msg: 'success', data: FIXTURE } });
    await getDashboard(168);
    expect(getMock).toHaveBeenCalledWith('/observability/dashboard', {
      params: { hours: 168 },
    });
  });

  it('code=0 解包返回 data（DashboardMetrics 原样）', async () => {
    (getMock as any).mockResolvedValue({ data: { code: 0, msg: 'success', data: FIXTURE } });
    await expect(getDashboard(24)).resolves.toEqual(FIXTURE);
  });

  it('code!=0 抛 Error 含后端 msg（fail-open 提示透传给页面）', async () => {
    (getMock as any).mockResolvedValue({
      data: { code: 1, msg: '看板查询失败（fail-open）' },
    });
    await expect(getDashboard(24)).rejects.toThrow('看板查询失败（fail-open）');
  });

  it('网络异常原样上抛（调用方 catch 后 Alert 展示）', async () => {
    (getMock as any).mockRejectedValue(new Error('Network Error'));
    await expect(getDashboard(24)).rejects.toThrow('Network Error');
  });
});
