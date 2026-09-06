/**
 * # 可观测看板 API 服务层（module-085）
 *
 * 封装 GET /ai/observability/dashboard（窗口聚合 4 指标：成功率 / 延迟
 * P50+P95 / token 成本 / 工具调用次数）。响应字段名与后端 plan §8 契约
 * 逐字一致（requests/latency/cost/tools/window），勿改。
 *
 * ## 错误处理策略（对齐 resumeService）
 * - 业务错误：code !== 0 → 抛 Error(msg)（含后端 fail-open 提示）
 * - 网络错误：axios 自动抛出，调用方 catch 即可
 * 页面 catch 后 Alert 展示（fail-open 不白屏）。
 */
import { aiHttp } from '../api/client';

/** 单端点请求分组 */
export interface EndpointStat {
  endpoint: string;
  total: number;
  errors: number;
}

/** 单工具调用分组（duration_p95_ms 兑现 module-083 WP-C 预留） */
export interface ToolStat {
  tool_name: string;
  calls: number;
  failures: number;
  duration_p95_ms: number;
}

/** 单供应商 token 分桶（历史桶 'llm' 原样保留不合并） */
export interface ProviderStat {
  provider: string;
  prompt_tokens: number;
  completion_tokens: number;
}

/** 看板聚合响应（null 语义：空窗口 success_rate/latency 为 null → 页面显示"—"） */
export interface DashboardMetrics {
  window: { hours: number; since: string; generated_at: string };
  requests: {
    total: number;
    errors: number;
    success_rate: number | null;
    by_endpoint: EndpointStat[];
  };
  latency: { p50_ms: number; p95_ms: number; samples: number } | null;
  cost: {
    total_prompt: number;
    total_completion: number;
    by_provider: ProviderStat[];
  };
  tools: { total: number; by_tool: ToolStat[] };
}

/**
 * 拉取可观测看板 4 指标（窗口聚合快照，手动刷新不轮询）
 * @param hours - 统计窗口小时数（0=全部数据）
 * @returns DashboardMetrics
 * @throws code!==0 或网络异常时抛出 Error
 */
export async function getDashboard(hours: number): Promise<DashboardMetrics> {
  const response = await aiHttp.get('/observability/dashboard', {
    params: { hours },
  });
  const body = response.data;
  if (body.code !== 0) {
    throw new Error(body.msg || '看板查询失败');
  }
  return body.data;
}
