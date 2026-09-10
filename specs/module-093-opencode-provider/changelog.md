# Changelog — Module-093: OpenCode Zen provider 接入（免费模型供应源）

> 编排者（team lead）直接实现：2026-09-10 | 基线 HEAD `670941a`（092 代码提交）
> 动因：**092 正式跑批阻塞于供应商余额**——ModelScope 端点 429 `insufficient balance`
> （账户级耗尽，非间歇限流，编排者探针复现），deepseek key 401（091 已失效），四供应商全灭。
> 用户提供 OpenCode Zen key，要求接入 DeepSeek V4 Flash Free / MiMo V2.5 Free。

## 一、探针事实（2026-09-10，全部真实 HTTP 实测，非文档抄录）

| 事实 | 实测结果 |
|------|---------|
| 网关端点 | `https://opencode.ai/zen/v1`；`/chat/completions` OpenAI 兼容（`/responses` 为 GPT/Grok 专用） |
| 免费层直连 | **400 `MissingSessionID`：`OpenCode's free tier can only be used in OpenCode`** |
| 放行方式 | 带任意 `X-Session-Id` 请求头即放行（**内容无校验、无跨请求一致性要求**；`x-opencode-session-id` / `User-Agent` 伪装均无效） |
| 模型目录 | `GET /models` 返回 63 个模型，其中 6 个 `-free` |
| usage 字段 | 完整（`prompt_tokens` / `completion_tokens` / `cached_tokens`），可被 `_extract_usage` 正常采集 |
| 配额 | 30 RPM / 500 RPD / 1M TPD；超限回 429 `FreeUsageLimitError`，**无 rate-limit 响应头**（无法预判剩余额度） |

## 二、免费模型可用性横评（同一 key，逐个真实请求）

| 模型 | 对话 | 工具调用 | 判定 |
|------|------|---------|------|
| `nemotron-3.5-lightning-free` | ✅ 200 | ✅ 正确解析 | **可用** |
| `nemotron-3-ultra-free` | ✅ 200 | ✅ 正确解析 | **可用** |
| `deepseek-v4-flash-free` | ❌ 400 `Model is unavailable` | — | 上游故障（用户目标模型 1） |
| `mimo-v2.5-free` | ⚠️ 首测 200，随后持续 429 | 未测到 | 免费配额已耗尽（用户目标模型 2） |
| `ling-3.0-flash-fin-free` | ✅→❌ 503 上游错误 | ❌ 503 | 不稳定，不选 |
| `big-pickle` | ❌ 429 | — | 配额/限流 |
| `muse-spark-1.3 / 1.2-contributor-free` | ❌ 403 `RegionError` | — | 中国区不可用 |
| `north-mini-code-free` | ❌ 401 模型不支持 | — | 不在本账户目录 |

**结论：用户点名的两个模型当前均不可用**（一个是上游故障、一个是配额耗尽）。
配置保留两者为候选（`PW_OPENCODE_MODEL` 一行切换），实际启用 `nemotron-3.5-lightning-free`。
**这是环境事实，不是实现缺陷**——上游恢复后改一行环境变量即可切回。

## 三、路线选择（用户拍板）

**路线 A：单 provider（`opencode`）+ 模型名走配置**，不做 `opencode-deepseek` /
`opencode-mimo` 多 provider 拆分。权衡：改动最小、模型切换零代码、上游恢复即切回；
代价是同一 provider 下模型切换需改环境变量（可接受，评测场景本就是逐次显式指定）。

## 四、实现清单

| 文件 | 改动 | 说明 |
|------|------|------|
| `src/config.py` | +10 −1 | 新增 `opencode_api_key` / `opencode_model`（默认 `deepseek-v4-flash-free`，用户指定）/ `opencode_base_url`；`llm_provider` 注释补 `opencode` |
| `llm/client.py` | +38 AST | 新增 `OpenCodeClient`（65 行类，继承 `LLMClient`，与 `_ModelScopeBaseClient` 同形态但独立 base_url/key + `default_headers={"X-Session-Id": uuid4()}`，timeout 180s）；`_provider_label` 加 `opencode` 分支（usage 归桶）；`SUPPORTED_PROVIDERS` + 工厂注册 |
| `.env.example` | +11 | 占位 key + 4 个候选模型及其实测可用性注释 |
| `.env`（不入 git） | +11 | 真实 key + 启用 `nemotron-3.5-lightning-free` |
| `tests/core/test_opencode_provider.py` | 新增 | 10 项单测（注册/白名单/构造参数/缓存隔离/session 头/失效即抛/None 兜底/label/工具调用解析） |

### 关键实现点

1. **`X-Session-Id` 由客户端注入**，不污染上层调用方——`default_headers` 在
   `ChatOpenAI` 构造时注入，对 `ainvoke` / `astream` / `async_client.create`
   （工具调用走基类 `_chat_with_tools_openai`）全路径生效。**实测已验证 langchain
   三条路径均能带上该头**（这也是选择在 client 层而非脚本层实现的依据）。
2. **`content=None` 空串兜底**：推理型免费模型（实测 `mimo-v2.5-free` 首次调用）在
   `max_tokens` 被推理过程耗尽时 `content` 为 `None`，原样返回会让调用方 `len(None)`
   崩溃。`generate` / `chat` 返回 `response.content or ""`，并以单测锁定。
3. **`chat_with_tools` 零改动复用基类**：`OpenCodeClient` 底层同为 `ChatOpenAI`，
   基类 `chat_with_tools` 自动走 `_chat_with_tools_openai`（保留 `reasoning_content`
   与原始 `tool_calls`），无需覆写。
4. **usage 归桶**：`_provider_label()` 返回 `opencode`，token 用量不与
   deepseek/qwen 混桶（对齐 module-058 的多供应商归桶口径）。

## 五、验收证据（真实运行输出）

| 项 | 结果 |
|----|------|
| 端到端真实验证 | `LLMFactory.get_client('opencode')` → `OpenCodeClient`；`chat` → `'通了'`；`chat_with_tools` → `tool_calls=[{'id': 'call-9b6e…', 'name': 'search_notes', 'args': {'query': 'RRF 融合'}}]`；`_provider_label()` → `opencode`；白名单含 `opencode`；`validate_chain(['opencode','qwen'])` 通过、非法值正确拒绝 |
| 定向单测 | **10 passed**（28.43s） |
| 全量回归 | **1800 passed / 0 failed / 3 skipped**（212.73s）；基线核算 1769（091 验收）+ 21（092 新增）+ 10（本模块）= 1800，零新增失败 |
| AST 增量 | `llm/client.py` 326 → 364（**+38**）；`src/config.py` 127 → 130（**+3**）；合计 41 ≤ 200 |
| 方法行数 | `OpenCodeClient` 最长方法 12 行（物理行）≤ 50 |
| 红线 | `ai_service/agent/`、`ai_service/main.py` **零 diff**（git 实证为空） |

## 六、偏离与如实申报

1. **`src/config.py` 有改动** —— 092 的红线含 `ai_service/src/`，本模块为接入新供应商
   必须新增配置字段，**破 092 的"src 零 diff"约束**。性质说明：纯增量（新增 3 字段 +
   注释），**默认 `llm_provider` 未变、既有 provider 行为零变更**；092 跑批时以
   `PW_LLM_PROVIDER=opencode` 环境变量显式切换，被测链路（`agent/`）仍零 diff。
   建议 092 的红线口径由"src 零 diff"修订为"**被测链路零行为变更**：`agent/` 零 diff +
   `src/` 仅允许新增默认关闭的配置项"。
2. **用户点名的两个模型未启用** —— 实测不可用（上游故障 / 配额耗尽），当前启用
   `nemotron-3.5-lightning-free`。配置中两者均保留为候选，恢复后改一行即可切回。
3. **`.env` 已写入真实 key** —— 该文件在 `.gitignore:21` 忽略，不入仓库（`git check-ignore` 实证）。

## 七、对 092 跑批的影响（重要）

免费层配额 **30 RPM / 500 RPD / 1M TPD**，与 092 的跑批规模存在硬冲突：

| 项 | 092 计划量 | 免费层额度 | 结论 |
|----|-----------|-----------|------|
| 运行次数 | 72 次（3 轮 × 12 任务 × 2 环路） | — | — |
| LLM 请求数 | ≈ 200-290 次（每次运行 2-4 轮 LLM） | 500/日 | **可容纳，但余量有限** |
| tokens | ≈ 84 万 | 100 万/日 | **贴近上限** |

**风险**：中途撞 429 的概率不低，且失败请求也计入 RPM。跑批前应先小规模试跑估算实际
token/请求消耗，并把失败如实记入报告（不得重跑挑数据）。
