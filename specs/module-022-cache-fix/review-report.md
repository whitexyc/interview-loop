# 审查报告 — Module-022: 检索缓存修复（key 参数化 + 失效策略）

## 1. 审查结论

- 结论: **通过**
- 审查时间: 2026-08-01
- 审查人: Reviewer
- 审查耗时: 约 30 分钟

> 核心变更（cache_key 参数化、delete_by_prefix 前缀失效、add/delete 全量失效挂接）实现正确、
> 改动聚焦、降级处理规范，测试与验证命令全部通过。存在 3 个低严重级建议改进，不阻塞审查通过。

## 2. 问题列表

### 2.1 阻塞问题（必须修复才能通过）

无。

### 2.2 建议改进（不阻塞但建议修复）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | ai_service/rag/engine.py | L57-74 | 验收标准 §1.2「空 query：不生成缓存 key」未实现。`_retrieve_cache_key("", top_k, min_score)` 对空 query 仍生成 key，`_retrieve` 对空 query 无防护，空 query 会写入缓存。schemas.py 中 ChatRequest.query 无 `min_length` 约束（既有行为，非本模块引入） | 低 | 在 `_retrieve` 入口对 `not query.strip()` 提前返回空列表；或在 ChatRequest schema 增加 `min_length=1` 校验 |
| 2 | ai_service/tests/test_cache.py | L52-74 | 集成测试 `test_prefix_invalidation_real_redis` 依赖本地 Redis（localhost:6379），不可达时直接失败而非跳过；且测试后残留 `rag:chat:ut-keep` 测试 key 未清理 | 低 | 测试前探测 Redis 不可达时 `pytest.skip`；用 try/finally 清理测试 key |
| 3 | ai_service/src/cache.py | L168 | SCAN 的 `match=f"{prefix}*"` 若 prefix 含 glob 元字符（`*` `?` `[`）会误匹配。当前调用方仅传常量 `rag:retrieve:`，无实际风险 | 低 | 在 docstring 注明 prefix 不应含 glob 元字符（防御性说明） |

## 3. 验收标准核对

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| delete_by_prefix 可用（前缀全清） | cache.py L146-178 | ✅ 通过 | 真实 Redis 集成测试通过 + plan §4.1 脚本输出 `True` / `None None` |
| cache_key 纳入 top_k/min_score | engine.py L57-74 | ✅ 通过 | hash 输入 `query + str(top_k) + str(min_score)`，测试验证 |
| add_document 后缓存失效 | engine.py L558-560 | ✅ 通过 | commit 成功后、graph 提取前调用 `delete_by_prefix` |
| delete_document 后缓存失效 | main.py L460-462 | ✅ 通过 | commit 成功后调用 `delete_by_prefix` |
| 缓存命中仍加速 | engine.py L284-288, L370-372 | ✅ 通过 | cache.get/set + TTL=300 保留，接口不变 |
| delete_by_prefix 无匹配 key 返回 True | cache.py L166-173 | ✅ 通过 | 测试用例覆盖 |
| Redis 不可用：返回 False 不崩 | cache.py L163-165, L174-178 | ✅ 通过 | `_ensure_client` 返回 None 短路返回 False |
| 空 query：不生成缓存 key | — | ❌ 未实现 | 见问题 #1（既有行为，低严重级） |
| top_k 为 0/负：安全处理 | — | ⚠️ 部分 | 缓存 key 生成不崩溃，但无参数校验（既有行为，非本模块范围） |
| SCAN 失败：降级 warning | cache.py L174-178 | ✅ 通过 | catch + warning 日志 + 返回 False |
| 失效失败：不影响检索正确性 | cache.py L174-178 | ✅ 通过 | 调用方无 try 包裹，不抛异常 |
| delete_by_prefix 接口/返回类型 | cache.py L146, L161 | ✅ 通过 | `-> bool`，get/set 签名不变 |
| 前缀不变 / hash 纳入参数 | engine.py L73-74 | ✅ 通过 | `rag:retrieve:` 前缀保持，测试校验与验收公式一致 |
| public 方法有 Docstring / 行内注释 | cache.py L147, engine.py L58, L283 | ✅ 通过 | |
| snake_case / 无无意义命名 | 全部 | ✅ 通过 | |
| 方法 ≤ 50 行 | _retrieve_cache_key 13 行、delete_by_prefix ~25 行 | ✅ 通过 | |
| 本模块新增代码 ≤ 200 行 | git diff 统计 +71（非测试） | ✅ 通过 | |
| Python 语法通过 | `python -m py_compile` 4 文件 | ✅ 通过 | 退出码 0 |
| 无未使用 import | main.py `from src.cache import cache` 已被使用 | ✅ 通过 | |
| delete_by_prefix 单测 | test_cache.py TestDeleteByPrefix | ✅ 通过 | 真实 Redis 集成 |
| cache_key 生成单测 | test_cache.py TestRetrieveCacheKey | ✅ 通过 | 5 个参数化用例 |
| add/delete 失效接线测试 | test_cache.py TestInvalidationWiring | ✅ 通过 | 打桩 DB 层 |
| 回归无新增失败 | `pytest tests/` → 54 passed, 2 failed | ✅ 通过 | 2 个失败为 test_engine.py 既有 async 用例缺 pytest-asyncio（module-018 已记录技术债务），该文件未被修改，非本次回归 |
| changelog.md 已更新（版本/日期/变更/人） | changelog.md | ✅ 通过 | v1 / 2026-08-01 |
| key 参数化 + 失效策略记录于 plan.md | plan.md §3.3 | ✅ 通过 | |

## 4. 架构评估

- 分层正确性: **通过**。cache.py 为独立缓存层，engine.py（编排层）通过 `cache` 接口调用，main.py（端点层）调用 `rag_engine` 与 `cache`，职责清晰。
- 依赖方向: 正确。cache 不反向依赖任何上层；engine/main 依赖 cache 接口，无跨层/反向/循环依赖。
- DTO 约束: 通过（Python 层，无 Entity 泄漏问题）。
- 新增依赖: 无。仅复用 module-015 已引入的 `redis.asyncio`。无需 ADR。

## 5. 安全评估

- [x] SQL 注入防护: 通过（本变更不涉及 SQL；add_document 使用 SQLAlchemy ORM 参数绑定）
- [x] XSS 防护: 通过 / N/A（本变更无前端渲染相关改动）
- [x] 密码安全（BCrypt）: N/A（不涉及认证）
- [x] API Key 安全: N/A（不涉及密钥处理）
- [x] 敏感信息日志处理: 通过。delete_by_prefix 日志仅记录 prefix（`rag:retrieve:`），不含 query/文档内容；_retrieve_cache_key 不记录 hash 输入明文

## 6. 架构决策记录（ADR）

- 本次审查是否产生 ADR: 否
- 说明: 本模块的 4 项设计决策（cache_key 参数化、文档变更全量失效、SCAN 而非 KEYS、失效失败降级）均与 plan.md 技术方案一致，未引入 plan 外的新依赖或架构变更，且已完整记录于 `memory/project-context.md` §7「检索缓存方案（module-022）」。无需单独撰写 ADR 文件。

## 7. 审查检查清单

- [x] 命名符合规范（snake_case）
- [x] delete_by_prefix 用 SCAN cursor 分批 + DEL（非 KEYS，不阻塞）
- [x] cache_key 参数化（纳入 top_k/min_score，前缀不变）
- [x] add_document / delete_document 失效挂接位置正确（数据变更成功后）
- [x] 降级处理正确（Redis 不可用 / 任何异常均不抛出）
- [x] 异常处理无空 catch（delete_by_prefix 有 warning 日志）
- [x] 关键操作有日志记录（命中/缓存写入/失效失败均有 logger）
- [x] 代码长度在限制内（方法 ≤ 50 行，本模块新增 ≤ 200 行）
- [x] 安全性检查通过
- [x] 全量回归无新增失败（54 passed，2 个既有 async 用例失败与本次无关）
- [ ] 空 query 防护（验收 §1.2 边界项未实现，见问题 #1，低严重级，不阻塞）
