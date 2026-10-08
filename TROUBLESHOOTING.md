# 排障速查（TROUBLESHOOTING）

> 这份文档里的每一条都来自**真实踩坑记录**，不是推测。
> 共性：它们大多**伪装成代码/API 故障**，错误信息里看不出真正的原因。
> 排查顺序建议：**先跑 `python scripts/doctor.py`，再怀疑代码。**

## 速查表

| 症状 | 根因 | 修复 |
|---|---|---|
| 检索正常，但回答只有一句兜底文案 | `no_proxy` 含 `[::1]`，httpx 抛 `InvalidURL` | 见 [①](#①-检索正常但回答生成失败) |
| 登录了，但长期记忆不按用户隔离 | `PW_JWT_SECRET` 与 Java 侧不一致（**静默**降级） | 见 [②](#②-jwt-密钥不一致静默降级) |
| 后端连不上 Redis | 密码不一致，容器无密码而后端默认发 `AUTH 123456` | 见 [③](#③-redis-密码不一致) |
| 批量灌笔记时大量 `HTTP 429` | 服务自带 IP 限流（默认 20 次/60 秒） | 见 [④](#④-批量入库撞限流) |
| 服务起不来，日志只有一行 addrinfo 错误 | 端口被占 | `python scripts/doctor.py` 会指出 |
| 检索质量差 / 报错说模型缺失 | 本地模型权重未下载（**有意不静默降级**） | 见 [⑤](#⑤-本地模型缺失) |
| 图谱通道没结果 | 库里缺 `age` 扩展，或图谱未创建 | 见 [⑥](#⑥-数据库缺扩展--图谱) |
| 自我反思环节总是超时 | 15s 硬超时包住整条降级链 + 推理模型太慢 | 见 [⑦](#⑦-自我反思总是超时) |
| `interview-admin` 测试报 forked VM 崩溃 | `@{argLine}` 占位符无人赋值 | 见 [⑧](#⑧-interview-admin-测试跑不起来) |
| opencode 报 `MissingSessionID` | Go 端点要 `x-opencode-session`，Zen 免费层要 `X-Session-Id` | 已修复（两种头名都注入）|

---

## ① 检索正常但回答生成失败

**症状**：`POST /ai/rag/chat` 返回 `sources` 正常（能检索到正确笔记），但 `answer` 只有
一句「很抱歉，回答生成时出现问题」。日志里是：

```
ERROR RAG chat 失败: ... InvalidURL: Invalid port: ':1]'
```

**根因**：环境变量 `no_proxy` 里含 IPv6 方括号写法（Windows 上很常见）：

```
no_proxy=localhost,127.0.0.1,::1,[::1]
```

httpx 会把 `no_proxy` 的每一项当作 URL 模式解析，`[::1]` 直接让它抛 `InvalidURL`。
**后果是所有出站 HTTP 调用（LLM 供应商、爬取、内部服务）全部失败**，而错误信息里
完全看不出与代理有关。

**修复**：本项目已在 `ai_service/src/proxy_env.py` 中兜底（`src/__init__.py` 导入即执行），
只移除含方括号或 `::` 的条目，保留 `localhost` / `127.0.0.1` —— 本机流量仍直连，
代理能力不受影响。若你用的是旧版本代码，也可直接改环境变量去掉 `[::1]`。

**预防**：`python scripts/doctor.py` 会对该写法告警。

## ② JWT 密钥不一致（静默降级）

**症状**：能登录、问答也正常，但长期记忆不按用户隔离（`weak_topic:` / `memory:` 的
source 里出现 `127.0.0.1` 而不是 user_id）。

**根因**：`PW_JWT_SECRET`（AI 层）与 `backend/.../application.yml` 的 `jwt.secret`
不一致。AI 层验签失败时**不报错**，而是把请求当匿名处理（`identity.py` 的 fail-open
设计）——这是刻意的，但很容易被误判为「记忆功能坏了」。

**修复**：两侧取同一个值（≥32 字节，HS256 要求），或用 `APP_JWT_SECRET` 环境变量统一注入。

**预防**：`doctor.py` 会比对两侧取值并直接报错。

## ③ Redis 密码不一致

**症状**：后端启动后连不上 Redis（`AUTH failed`）。

**根因**：容器无密码（`ALLOW_EMPTY_PASSWORD=yes`），而后端
`spring.data.redis.password` 默认 `123456`，会主动发 `AUTH`。

**修复**：给 Redis 设密码（`docker compose` 里已用 `--requirepass 123456`），
或在两侧都改为无密码。

## ④ 批量入库撞限流

**症状**：`scripts/sync_notes.py` 灌到第 20 个文件左右开始全部失败：

```
HTTP 429: {"message":"请求过于频繁，请在 58 秒后重试","retry_after":58}
```

**根因**：AI 层按 IP 做 60 秒滑动窗口限流（默认 20 次）。批量同步的请求速率远高于
聊天，必然撞上；且笔记被哈希去重时每个文件只花 2-3 秒，速率更高。

**修复**：
- 脚本已内置退避重试（按响应体的 `retry_after`），可直接跑完
- 灌几百篇时建议临时调高阈值：`ai_service/.env` 设 `PW_RATE_LIMIT_MAX_REQUESTS=200` 后重启 AI 层

## ⑤ 本地模型缺失

**症状**：报 `EmbeddingException: 嵌入模型文件不存在` 或
`RerankerException: 重排模型缺少权重文件`。

**根因**：三个本地模型（约 3.2 GB）不随仓库分发。

**修复**：按 README「下载本地模型」下载到 `ai_service/models/` 对应目录。

> 注意这是**有意设计**：重排模型缺权重时明确报错，不回退 HuggingFace 在线加载 ——
> 让问题可见而非静默降级（见 `rag/retrieval/reranker.py` 注释）。只有 HHEM 幻觉裁判
> 缺失会降级回 LLM 判分。

## ⑥ 数据库缺扩展 / 图谱

**症状**：报 `type "vector" does not exist` / `extension "age" is not available`，
或图谱通道始终没有结果。

**根因**：`docker/postgres/initdb/` 下的脚本**只在数据卷为空时执行一次**。

**修复**：

```bash
docker compose down -v && docker compose up -d    # 清卷重建，initdb 会重新执行
```

若图谱为空但扩展正常，可用 `ai_service/scripts/backfill_graph.py` 对已有文档补跑实体提取
（走 LLM，注意配额）。

## ⑦ 自我反思总是超时

**症状**：`agent/reflector.py` 的充分性判定超时，日志出现
`TimeoutError` / `CancelledError`，回答退化为兜底文案。

**根因**：充分性判定用 `asyncio.wait_for(..., timeout=15)` 包住**整条降级链**。
若首位模型是推理模型（长上下文下 reasoning 可达数千字符），整条链会在 15 秒被取消 ——
**连降级到下一个供应商的机会都没有**。

**修复**：把降级链首位换成 flash 档模型，例如
`PW_OPENCODE_MODEL=deepseek-v4.1-flash` + `PW_FALLBACK_CHAIN=opencode,qwen,zhipu,deepseek`
（实测 2.8 秒返回）。

## ⑧ interview-admin 测试跑不起来

**症状**：`./mvnw test` 报

```
The forked VM terminated without properly saying goodbye. VM crash or System.exit called?
Tests run: 0
```

**根因**：`admin/pom.xml` 的 surefire/failsafe `<argLine>` 里写了 `@{argLine}` 占位符
（供 jacoco 等覆盖率插件注入）。本项目未接覆盖率插件，占位符无人赋值，字面量
`@{argLine}` 被当 JVM 参数传入，forked VM 启动即崩溃。

**修复**：已在 `<properties>` 中显式定义空 `<argLine></argLine>`。修复后 106 项测试
可执行，其中 104 项通过（余下 2 项见 README「已知问题」）。
