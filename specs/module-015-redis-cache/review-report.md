# 审查报告 — Module-015: Redis Query Cache

## 1. 审查结论

- 结论: **PASS_WITH_ISSUES**（附条件通过 -- 1 个阻塞问题须修复）
- 审查时间: 2026-07-30
- 审查人: Reviewer
- 审查耗时: ~30 分钟

**不通过项**: 自动重连逻辑存在 bug（见问题 #1），违反验收标准"Redis 恢复后自动重连"。其余所有验收项通过。

---

## 2. 问题列表

### 2.1 阻塞问题（必须修复才能通过）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | `cache.py` | L112-115, L137-140 | **Redis 恢复后无法自动重连**。当 Redis 在会话中宕机：`get()`/`set()` catch 异常后设置 `_connected = False`，但 `_client` 仍指向旧连接（非 None）。下次调用 `_ensure_client()` 时 L71 行 `if self._client is not None` 命中，直接返回已断开的旧客户端，跳过了重连逻辑。`get()`/`set()` 随后检测 `not self._connected` 返回 None/False，永久不再重试。验收标准明确要求"Redis 恢复后自动重连"。 | 阻塞 | **方案 A**（推荐）: 在 `get()` L114 和 `set()` L139 处，同时设置 `self._client = None`，强制下次 `_ensure_client()` 执行重连。<br>**方案 B**: 修改 `_ensure_client()` L71 行为 `if self._client is not None and self._connected:`。方案 A 更简洁，改动更小。 |

### 2.2 高优先级问题（必须修复）

无。

### 2.3 建议改进（不阻塞，建议修复）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 2 | `engine.py` | L324-327 | 检索结果为空时（`docs=[]`）不写缓存，下次相同查询会重复全链路检索（HyDE + 3轮检索 + 反思 + 父块映射 + 低分过滤），全部白跑。对于高频"无结果"查询（如用户反复问知识库外的问题），会造成不必要的 CPU/LLM 开销。 | 低 | 增加空结果缓存：`else: await cache.set(cache_key, [], ttl=120)`（空结果 TTL 可设更短，如 2 分钟）。注意：空结果缓存的语义不是"结果为空"而是"该查询无匹配文档"——若后续入库了相关文档，2 分钟后缓存过期，新查询能命中。 |
| 3 | `cache.py` | L61-70 | `_ensure_client` docstring 提到"不维护连接池（单例实例 + 异步连接足够轻量）"，但 `redis.asyncio.from_url()` 默认使用连接池（`ConnectionPool`）。表述不够严谨，但行为正确——不影响功能。 | 低 | 将 docstring 改为"连接复用由 redis-py 内置连接池管理，本类不额外管理连接生命周期"。不影响功能，可后续改。 |

---

## 3. plan.md 技术方案逐项核对

### 3.1 新增 `src/cache.py`

| 要求 | 代码位置 | 状态 | 备注 |
|------|----------|------|------|
| `RedisCache` 类 | L39-144 | PASS | |
| 懒连接（lazy connect） | L61-90 `_ensure_client()` | PASS | 首次 get/set 时才连接 |
| get 方法（JSON 反序列化） | L92-115 | PASS | `json.loads(data)` |
| set 方法（JSON 序列化） | L117-140 | PASS | `json.dumps(value, ensure_ascii=False)` |
| TTL 300 秒 | L117 `ttl: int = 300`, L135 `setex(key, ttl, ...)` | PASS | |
| 优雅降级（Redis 不可用不抛异常） | L112-115 (get), L137-140 (set) | PASS | 所有 Redis 操作包裹 try/except |

### 3.2 修改 `config.py`

| 要求 | 代码位置 | 状态 | 备注 |
|------|----------|------|------|
| `redis_url: str = "redis://localhost:6379/0"` | config.py L18 | PASS | 默认值正确，通过 `PW_REDIS_URL` 环境变量可覆盖（`env_prefix = "PW_"`） |

### 3.3 修改 `engine.py` `_retrieve()`

| 要求 | 代码位置 | 状态 | 备注 |
|------|----------|------|------|
| import cache | engine.py L29 `from src.cache import cache` | PASS | |
| 入口: 构建 cache_key = `rag:retrieve:{sha256[:12]}` | engine.py L257 | PASS | |
| 入口: cache.get → 命中直接返回 | engine.py L258-261 | PASS | 含日志"检索缓存命中" |
| 出口: cache.set(key, docs, ttl=300) | engine.py L324-327 | PASS | 含日志"检索结果已缓存" |
| Redis 不可用时静默降级 | engine.py L258 (cache.get 返回 None → 走正常检索) | PASS | 降级由 cache.py 内部 try/except 保证 |

### 3.4 检索流程变更

```
变更前:
  query → 无缓存 → _hyde_expand → hybrid_retrieve ×3 → _expand_to_parents → min_score_filter → return

变更后:
  query → cache.get(cache_key) → 命中? → 直接返回 (跳过所有检索+HyDE)
                                → 未命中? → _hyde_expand → hybrid_retrieve ×3 → ...
                                  → cache.set(cache_key, docs, ttl=300) → return
```

实现与 plan 完全一致。PASS。

### 3.5 文件清单

| # | 文件 | 操作 | 状态 | 备注 |
|---|------|------|------|------|
| 1 | `ai_service/src/cache.py` | 新建 | PASS | 145 行 |
| 2 | `ai_service/src/config.py` | 修改 (+redis_url) | PASS | L18 |
| 3 | `ai_service/rag/engine.py` | 修改 (+cache import/check/write) | PASS | L29, L256-261, L324-327 |
| 4 | `ai_service/requirements.txt` | 修改 (+redis>=5.0.0) | PASS | L22 |

---

## 4. 验收标准核对

### 4.1 功能

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| 首次查询后缓存写入（日志"检索结果已缓存"） | engine.py L326-327 `logger.info("检索结果已缓存: key=%s, docs=%d", ...)` | PASS | |
| 5 分钟内相同查询命中缓存（日志"检索缓存命中"，跳过检索） | engine.py L258-261 `logger.info("检索缓存命中: key=%s, docs=%d", ...)` | PASS | TTL=300 秒 |
| TTL 过期后重新检索 | cache.py L135 `client.setex(key, ttl, ...)` → Redis 自动过期 → `get()` 返回 None → 走正常检索 | PASS | |
| 不同查询 key 隔离 | engine.py L257 `cache_key = f"rag:retrieve:{hashlib.sha256(query.encode()).hexdigest()[:12]}"` | PASS | SHA256 碰撞概率极低（48 bits） |

### 4.2 降级

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| Redis 宕机：日志"Redis 缓存不可用"，检索正常 | cache.py L87 `logger.warning("Redis 缓存不可用 (连接失败): %s", e)`<br>L113 `logger.warning("Redis 缓存读取失败: %s", e)`<br>L138 `logger.warning("Redis 缓存写入失败: %s", e)` | PASS | 所有异常 catch → 返回 None/False → 检索链路不受影响 |
| Redis 恢复后自动重连 | — | **FAIL** | 见阻塞问题 #1。`_client` 未置 None，`_ensure_client` 短路不重试。 |

### 4.3 代码质量

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| cache.py 有 docstring | L1-26 模块 docstring + L39-55 类 docstring + L61-70 / L92-115 / L117-140 方法 docstring | PASS | 26 行模块 docstring 解释设计决策 |
| get/set 均有 try/except | get: L104-115, set: L131-140 | PASS | |
| config.py 有合理默认值 | L18 `redis_url: str = "redis://localhost:6379/0"` | PASS | |
| requirements.txt 格式正确 | L22 `redis>=5.0.0` | PASS | 无尾随逗号，格式与其他行一致 |
| `python -m py_compile src/cache.py` 通过 | 待 Tester 验证，语法层面无可见问题 | 待验证 | |

---

## 5. 正确性分析

### 5.1 缓存键唯一性

```
cache_key = f"rag:retrieve:{hashlib.sha256(query.encode()).hexdigest()[:12]}"
```

- SHA256 前 12 位十六进制 = 48 bits，碰撞概率约 `n² / 2^49`。30 万条不同 query 时碰撞概率约 1.6e-4。知识库场景中高频问题数量远小于此，安全。PASS
- `rag:retrieve:` 命名空间前缀避免与其他键冲突。PASS
- 使用原始 query 而非 HyDE 扩展后的查询作为 key —— 正确：相同用户输入应命中相同缓存，HyDE 只是内部检索优化手段。PASS

### 5.2 缓存读取时机

```
L257: cache_key = ...
L258: cached = await cache.get(cache_key)     ← 在 HyDE 之前
L259-261: if cached: return cached            ← 跳过 HyDE + 检索
L268: hyde_query = await self._hyde_expand(query)  ← 仅在未命中时执行
```

- 缓存命中时跳过 HyDE（节省 LLM 调用）。正确。PASS
- 缓存 key 是原始 query 的 hash，不包含 HyDE 输出。正确（同一 query 始终映射到同一 cache key）。PASS

### 5.3 缓存写入时机

```
L316: docs = await self._expand_to_parents(all_docs)  ← 父块映射后
L319-322: docs = [filtered]                          ← 低分过滤后
L324-326: await cache.set(cache_key, docs, ttl=300)  ← 最终结果写入缓存
```

- 缓存的 docs 是经过父块映射 + 低分过滤的最终结果。正确（调用方直接得到可用结果）。PASS
- 空结果不写入缓存（`if docs:`）。设计了"无结果不缓存"，见建议 #2。技术上不是 bug。PASS

### 5.4 并发安全

- `RedisCache` 是单例（`cache = RedisCache()` L144），所有请求共享同一实例。PASS
- `_ensure_client` 不是线程安全的（无锁），但在 asyncio 单线程模型下不会出现竞态。PASS
- `_connected` / `_client` 的读写可能交错（两个并发请求同时调用 `_ensure_client`），但最坏结果是创建两个连接（后创建者覆盖 `_client`），旧的被 GC。可接受。PASS

---

## 6. 代码质量评估

### 6.1 注释覆盖率

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 模块 docstring | PASS | cache.py L1-26: 26 行 docstring，说明 4 项设计决策 |
| 类 docstring | PASS | L39-55: 职责、使用示例、单例说明 |
| 方法 docstring | PASS | `_ensure_client` L61-70、`get` L92-115、`set` L117-140 均有 Args/Returns |
| 行内注释 | PASS | L75 `decode_responses=True  # 自动 decode bytes → str`<br>L81 `# 验证连接可用（空 ping 只是连接检查，无副作用）` |
| 日志信息 | PASS | 连接成功/连接失败/读取失败/写入失败 4 条 warning + info，级别正确 |

### 6.2 命名规范

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 类名 PascalCase | PASS | `RedisCache` |
| 方法名 snake_case | PASS | `get`, `set`, `_ensure_client` |
| 私有方法前缀 `_` | PASS | `_ensure_client` |
| 变量命名 | PASS | `cache_key`, `_client`, `_connected` |

### 6.3 代码长度

| 检查项 | 行数 | 上限 | 状态 |
|--------|------|------|------|
| cache.py 总行数 | 145 | 500 | PASS |
| `_ensure_client()` | 30 | 50 | PASS |
| `get()` | 24 | 50 | PASS |
| `set()` | 26 | 50 | PASS |

### 6.4 异常处理

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 无空 catch | PASS | 所有 catch 含日志 + 状态标记 + 返回安全值 |
| 连接异常 | PASS | `_ensure_client` catch → `_connected=False, _client=None, return None` |
| 读写异常 | PASS | get/set catch → `_connected=False` + `return None/False` |
| 降级不传播 | PASS | 异常绝不传播到 engine.py 调用方 |

---

## 7. 安全评估

- [x] **无硬编码密码**: `redis_url` 从 settings 读取，默认值 `redis://localhost:6379/0` 无密码（本地开发默认合理）
- [x] **无注入风险**: cache key 为 SHA256(query)，query 内容通过哈希处理，不直接用作 Redis key
- [x] **JSON 序列化安全**: `json.dumps(value, ensure_ascii=False)` + `json.loads(data)` 标准安全序列化
- [x] **连接超时**: `socket_connect_timeout=3, socket_timeout=3`，防止 Redis 宕机时阻塞
- [ ] SQL 注入: N/A
- [ ] XSS: N/A

---

## 8. 依赖审计

| 依赖 | 版本要求 | 操作 | 状态 |
|------|----------|------|------|
| `redis` | >=5.0.0 | 新增 | PASS -- redis-py 5.x 是官方推荐版本，无已知安全漏洞 |

**新增依赖**: 1 个（redis>=5.0.0）。Plan 中已明确要求。

**ADR 需求**: 无需 ADR（依赖为计划中明确要求的标准组件，无争议）。

---

## 9. 架构评估

- **分层正确性**: PASS。`src/cache.py` 属基础设施层，被 `rag/engine.py`（编排层）调用，单向依赖。
- **模块职责**: `RedisCache` 单一职责（仅缓存读写），不涉及检索逻辑。PASS
- **全局单例**: `cache = RedisCache()` L144，与 `rag_engine = RAGEngine()` 模式一致。PASS
- **无状态设计**: `RedisCache` 仅持有连接对象，不存储业务数据。PASS

---

## 10. 审查检查清单

- [x] 已读取 plan.md 和 acceptance-criteria.md
- [x] 已阅读全部变更文件: cache.py(145行), engine.py L29+L256-261+L324-327, config.py L18, requirements.txt L22
- [x] plan.md 技术方案逐项核对（全部 PASS）
- [x] 验收标准逐项核对（1 项 FAIL: 自动重连）
- [x] 正确性分析完成（缓存键唯一性、读写时机、并发安全）
- [x] 命名符合规范
- [x] 异常处理无空 catch
- [x] 代码长度检查通过
- [x] 安全评估完成（无硬编码密码、无注入风险）
- [x] 依赖审计完成（1 个新依赖）
- [x] 每个问题都标注了文件路径 + 行号
- [x] review-report.md 已输出

---

## 11. 总结

M15 Redis Query Cache 实现整体质量高：

- **架构清晰**: `RedisCache` 单一职责，懒连接 + TTL + 优雅降级设计完整
- **文档卓越**: 26 行模块 docstring 解释 4 项设计决策（SHA256/300s TTL/懒连接/try-except），方法 docstring 完备
- **异常隔离**: 所有 Redis 操作双层 try/except（`_ensure_client` + get/set），降级路径完整
- **引擎集成精准**: engine.py 仅增加 12 行（import + cache check + cache write），改动最小化
- **安全合规**: 无硬编码凭证，cache key 通过 SHA256 哈希防注入

**必须修复的 1 个阻塞问题**:

**问题 #1**: `get()`/`set()` 异常处理中仅设置 `_connected = False` 但未重置 `_client = None`。导致 `_ensure_client()` 检查 `self._client is not None` 时短路返回旧连接，跳过重连逻辑。Redis 恢复后缓存永久失效。修复只需在 `get()` L114 和 `set()` L139 的 catch 块各加一行 `self._client = None`。
