# LLM 供应商接入台账（非模块）

> **定位**：记录评测/运行环境的 LLM 供应商接入事实——端点、鉴权、可用模型、配额、踩坑。
> 新增供应商**直接追加小节**，不占 module 编号、不走 Plan/Develop/Review/Test 四阶段流程。
> （用户 2026-09-10 明确要求：「新增免费模型不算一个 module」。）
>
> 相关模块：092（跑批因供应商余额阻塞，衍生本台账）、091（LangGraph 对比评测）。
> 原 `specs/module-093-opencode-provider/changelog.md` 内容已并入本文件（2026-09-10）。

---

## 一、OpenCode Zen（2026-09-10 接入，✅ 可用）

### 1.1 接入事实（全部真实 HTTP 实测，非文档抄录）

| 项 | 值 |
|----|-----|
| 端点 | `https://opencode.ai/zen/v1`；`/chat/completions` OpenAI 兼容（`/responses` 为 GPT/Grok 专用，`/messages` 为 Claude/Qwen 原生格式） |
| 鉴权 | `Authorization: Bearer <key>` |
| **免费层限制** | 直连报 **400 `MissingSessionID`：`OpenCode's free tier can only be used in OpenCode`** |
| **放行方式** | **带任意 `X-Session-Id` 请求头**（内容无校验、无跨请求一致性要求）。`x-opencode-session-id`、User-Agent 伪装（`opencode/1.18.23`）**均无效** |
| 模型目录 | `GET /models` → 63 个模型，其中 6 个 `-free` |
| usage 字段 | 完整（`prompt_tokens` / `completion_tokens` / `cached_tokens`），可被 `_extract_usage` 采集 |
| 配额 | 30 RPM / 500 RPD / 1M TPD；超限 429 `FreeUsageLimitError`，**无 rate-limit 响应头**（无法预判剩余额度） |

### 1.2 免费模型横评（同一 key，逐个真实请求）

| 模型 | 对话 | 工具调用 | 判定 |
|------|------|---------|------|
| `nemotron-3.5-lightning-free` | ✅ 200 | ✅ 正确解析 | **可用**（当前启用） |
| `nemotron-3-ultra-free` | ✅ 200 | ✅ 正确解析 | **可用** |
| `deepseek-v4-flash-free` | ❌ 400 `Model is unavailable` | — | 上游故障 |
| `mimo-v2.5-free` | ⚠️ 首测 200 后持续 429 | 未测到 | 免费配额耗尽 |
| `ling-3.0-flash-fin-free` | ✅→❌ 503 | ❌ 503 | 不稳定，不选 |
| `big-pickle` | ❌ 429 | — | 配额/限流 |
| `muse-spark-1.3 / 1.2-contributor-free` | ❌ 403 `RegionError` | — | 中国区不可用 |
| `north-mini-code-free` | ❌ 401 模型不支持 | — | 不在本账户目录 |

### 1.3 实现（路线 A：单 provider + 模型名走配置）

| 文件 | 改动 |
|------|------|
| `ai_service/src/config.py` | +3 字段：`opencode_api_key` / `opencode_model` / `opencode_base_url`；`llm_provider` 注释补 `opencode` |
| `ai_service/llm/client.py` | +38 AST：`OpenCodeClient`（65 行类，独立 base_url/key + `default_headers={"X-Session-Id": uuid4()}`，timeout 180s，`content=None` 空串兜底）；`_provider_label` 加 `opencode` 分支（usage 归桶）；`SUPPORTED_PROVIDERS` + 工厂注册 |
| `ai_service/.env`（不入 git） | 真实 key + 启用 `nemotron-3.5-lightning-free` |
| `ai_service/.env.example` | 占位 key + 候选模型及可用性注释 |
| `ai_service/tests/core/test_opencode_provider.py` | 新增 10 单测 |

**关键实现点**

1. `X-Session-Id` 由客户端注入，不污染上层调用方——`default_headers` 在 `ChatOpenAI`
   构造时注入，对 `ainvoke` / `astream` / `async_client.create`（工具调用走基类
   `_chat_with_tools_openai`）全路径生效。
2. `content=None` 空串兜底：推理型免费模型在 `max_tokens` 被推理过程耗尽时
   `content` 为 `None`（`finish_reason=length`），原样返回会让调用方 `len(None)` 崩溃。
3. `chat_with_tools` 零改动复用基类（底层同为 `ChatOpenAI`）。

**验收**：端到端真实调用通过（`chat` → `'通了'`；`chat_with_tools` → tool_calls 正确解析）；
定向单测 10/10；全量回归 **1800 passed / 0 failed / 3 skipped**；AST 增量合计 41 ≤ 200。

### 1.4 配额与 092 跑批的冲突（实测校准）

小规模试跑实测（2 任务 × 1 轮 + 冷启动，7.2 分钟墙钟）：**37004 tokens**（两环路合计）。
线性外推 092 正式跑批（12 任务 × 3 轮）：

| 项 | 外推值 | 免费层额度 | 结论 |
|----|--------|-----------|------|
| tokens | ≈ 66.6 万 | 100 万/日 | 勉强够，无余量 |
| 请求数 | ≈ 360 次 | 500 RPD | 勉强够，失败重试即超 |
| 墙钟 | ≈ 1.7 小时（单次 ≈ 85 秒） | — | 原估 40-60 分钟偏乐观 |

**风险**：中途撞 429 概率不低（失败请求也计入 RPM/RPD）。跑批前必须小规模试跑校准，
失败如实记入报告，不得重跑挑数据。

---

## 二、Command Code（2026-09-10 探针，⚠️ 待账户充值）

### 2.1 接入事实

| 项 | 值 |
|----|-----|
| 端点 | `https://api.commandcode.ai/provider/v1/chat/completions`（OpenAI 兼容） |
| 鉴权 | `Authorization: Bearer <key>`（用户提供的是 `user_` 前缀的 key） |
| 模型目录 | `GET /models` → 68 个模型，其中 3 个 free |
| 文档 | https://commandcode.ai/models 、https://commandcode.ai/docs/resources/pricing-limits |

### 2.2 免费模型（文档声明 $0 计费）

| 模型 | 上下文 | 日限 | 备注 |
|------|--------|------|------|
| `meituan/LongCat-2.0:free` | 1M | **100 请求/天/账户** | 美团万亿参数开源模型 |
| `poolside/laguna-s-2.1-free` | 256K | 未标注（while capacity lasts） | Poolside 开源 agentic coding 模型 |
| `inclusionai/ling-3.0-flash-sante:free` | 262K | **100 请求/天/账户** | inclusionAI 124B MoE，原生工具调用 |

### 2.3 ⚠️ 阻塞：免费模型需要账户有 ≥ $1 余额

文档原文（pricing-limits 页，三个免费模型均适用）：

> "Available to all customers: Go, GOAT, Pro, Max, Ultra, and Team Pro.
> **Need to have $1 of credits in your account to start a session.**"

**实测结果**：三个免费模型**全部返回 400 `insufficient credits`**（当前 key 账户余额为 0）：

```
[对话] meituan/LongCat-2.0:free             400 {"error":{"message":"You have insufficient credits to make this request..."}}
[对话] poolside/laguna-s-2.1-free           400 同上
[对话] inclusionai/ling-3.0-flash-sante:free 400 同上
```

无公开的余额查询端点（`/account`、`/usage`、`/credits`、`/me`、`/balance` 均 404）。

**解法**：在 Studio > Billing 充值 **$1**（免费模型 $0 计费，$1 是启动门槛而非消耗）。
充值后 3 个免费模型即可用——但注意 LongCat / Ling 有 **100 请求/天**限制，
不够 092 的 ≈360 次请求（需分 4 天跑，或改用下面的折扣模型）。

### 2.4 附带发现：mimo-v2.5 折扣极大

Command Code 上 `mimo-v2.5`（即用户原本想用的 MiMo V2.5）有 **98% 折扣**：
输入 $0.80 → **$0.14**、输出 $4.00 → **$0.28** / 1M tokens（`mimo-v2.5-pro` 折扣 99%）。
另有 `minimax-m3` 2× 用量、DeepSeek V4 系列错峰半价（UTC 01-04 / 06-10 为高峰）。
**$1 余额按此价可跑约 350 万 tokens 的 mimo-v2.5**，且无 100 请求/天限制——
比免费模型更适合 092 这种批量评测。

---

## 三、跑批阻塞背景（2026-09-10）

092 正式跑批曾完全阻塞于供应商余额：

| 供应商 | 状态 |
|--------|------|
| ModelScope（qwen/zhipu/modelscope 同端点） | 429 `insufficient balance`（账户级耗尽，编排者探针复现） |
| deepseek 独立 API | key 401 失效（091 已知） |
| **OpenCode Zen** | ✅ 已接入（本台账 §一） |
| **Command Code** | ⚠️ 待充值 $1（本台账 §二） |

**教训**：跑批类任务的供应商余额应在 **Planner 阶段就探针**——092 plan 查了代码事实
（usage 上报路径、span 表结构）却没查"钱包"，导致代码全部写完才卡在最后一环。

---

## 四、运行时降级链（2026-09-10 调整）

### 4.1 发现问题

排查时发现**两个独立的失效点**：

1. `.env` 的 `PW_LLM_PROVIDER=deepseek` 是**单供应商模式，不走降级链**，
   而该 key 已 401 失效 → 服务重启后任何 LLM 调用必失败。
2. **Redis 运行时链 `llm:fallback_chain = deepseek,qwen,zhipu`，链首同样是失效的 deepseek**。
   ⚠️ **Redis 链优先级高于 `.env` 配置**（`main.py:95 load_fallback_chain_from_redis`，
   启动时加载；只有链为空/非法才回退配置默认）——**只改 `.env` 不生效**。

### 4.2 调整（三处同步，缺一不可）

| 位置 | 改前 | 改后 |
|------|------|------|
| `.env` `PW_LLM_PROVIDER` | `deepseek`（单点） | `fallback`（自动降级） |
| `.env` `PW_FALLBACK_CHAIN` | 未设置（走 config 默认） | `qwen,zhipu,opencode,deepseek` |
| `src/config.py` `fallback_chain` 默认值 | `qwen,zhipu,deepseek` | `qwen,zhipu,opencode,deepseek` |
| **Redis `llm:fallback_chain`** | `deepseek,qwen,zhipu` | `qwen,zhipu,opencode,deepseek` |

**理由**：deepseek key 失效 → 移到链尾兜底；`opencode`（本文件 §一 新接入）补入倒数第二；
链首保持 `qwen`。四家全挂才会整体失败。

### 4.3 验证

- **端到端**：模拟启动路径（`load_fallback_chain_from_redis()` → `get_client('fallback')` → 实调）
  通过——链读回 `['qwen','zhipu','opencode','deepseek']`，`FallbackClient._chain` 一致，
  实调走 qwen 返回成功。
- **回归**：全量 **1800 passed / 0 failed / 3 skipped**（与改动前逐字一致，零新增失败）。

### 4.4 六 provider 实测状态（2026-09-10 13:27，逐个真实探针）

| provider | 模型 | key | 实测 |
|----------|------|-----|------|
| claude | claude-sonnet-5-20251001 | ❌ 空 | 未配置 |
| deepseek | deepseek-v4-flash | 已配置 | ❌ 服务不可用（401） |
| **qwen** | Qwen/Qwen3.5-35B-A3B | 走 ModelScope | ✅ **可用** |
| **zhipu** | ZhipuAI/GLM-5.2 | 走 ModelScope | ✅ **可用** |
| **modelscope** | deepseek-ai/DeepSeek-V4-Pro | 已配置 | ✅ **可用** |
| **opencode** | nemotron-3.5-lightning-free | 已配置 | ✅ 可用 |

**ModelScope 余额已恢复**（此前 429 `insufficient balance`，是 092 跑批阻塞的根因）。

### 4.5 对 092 跑批的结论

ModelScope 恢复后，**092 应改用 `qwen` 而非 OpenCode 免费层**：

1. **与 091 同源**（091 就是用 `PW_LLM_PROVIDER=qwen` 跑的）→ 对比结论可直接对话；
   换免费模型会引入不可比因素（供应商差异 + 模型行为差异）。
2. **无硬配额顶**（免费层是 500 RPD / 1M TPD，72 次运行无重试余量）。
3. **避免工具超时污染**：`nemotron` 是推理型模型，实测慢到触发 `generate_answer` 15s 超时
   （试跑日志实证 2 次），会让延迟数据被超时/重试主导。

OpenCode 免费层降为**链上兜底**（第四顺位前的第三位），主用途是"其他家全挂时还能跑"。
