# 变更日志 — Module-015: Redis Query Cache

## 变更概述
为 `_retrieve()` 增加 Redis 查询缓存层：相同查询 5 分钟内直接返回缓存结果，跳过 embedding + FTS + rerank 全链路检索。Redis 不可用时静默降级，不影响核心检索功能。缓存键基于查询文本的 SHA256 前缀，保证不同查询间的隔离。

## 文件变更列表
| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| ai_service/src/cache.py | 新增 | RedisCache 类：懒连接、JSON get/set、TTL 300、优雅降级（所有异常 catch 并返回 None/False） |
| ai_service/src/config.py | 修改 | Settings 新增 redis_url 字段，默认 "redis://localhost:6379/0" |
| ai_service/rag/engine.py | 修改 | _retrieve() 入口增加缓存检查，出口增加缓存写入，导入 src.cache |
| ai_service/requirements.txt | 修改 | 追加 redis>=5.0.0 |

## 关键设计说明

### 设计决策 1: 缓存键使用 SHA256(query)[:12]
- **决策**: `cache_key = f"rag:retrieve:{hashlib.sha256(query.encode()).hexdigest()[:12]}"`
- **原因**: 完整 query 可能包含中文和特殊字符，SHA256 提供固定长度的唯一标识。12 位十六进制 = 48 bits 碰撞概率极低（~1/2^48），比直接截断或 encode 查询更可靠。`rag:retrieve:` 前缀便于 Redis key 管理和监控。

### 设计决策 2: 缓存放置在检索入口和出口，包裹完整 _retrieve() 链路
- **决策**: 缓存检查在 HyDE 之前（入口），缓存写入在 `_expand_to_parents` + `min_score` 过滤之后（出口）
- **原因**: 入口检查在最外层可以跳过整个检索链路（HyDE + 混合检索 + 反思 + 父块映射 + 过滤），最大化缓存收益。出口写入在过滤后确保缓存的是最终结果而非中间数据。

### 设计决策 3: 懒连接 + 连接失败标记
- **决策**: `_ensure_client()` 懒创建连接，失败时设置 `_connected=False`，后续调用直接返回 None
- **原因**: (1) 懒连接避免 Redis 宕机时应用启动失败；(2) 失败标记避免每次请求都重试连接（减少日志噪音和 CPU 浪费）；(3) 连接恢复后新的 `_ensure_client()` 调用会重建 `_client`（因上次失败已将 `_client` 置为 None）

### 设计决策 4: TTL 300 秒
- **决策**: 固定 5 分钟过期，不做主动失效
- **原因**: 5 分钟在缓存命中率和数据新鲜度之间取得平衡。知识库文档不会频繁更新（文档更新频率远低于查询频率），且每次文档更新通常伴随服务重启，自然清空缓存。没有实现主动失效机制，保持实现简单。

### 设计决策 5: 使用 redis.asyncio 异步客户端
- **决策**: `import redis.asyncio as redis`，所有操作均为 async/await
- **原因**: ai_service 整体基于 FastAPI + asyncio 构建，同步 Redis 客户端会阻塞事件循环。`redis-py` 5.x 提供了完善的异步支持，与项目架构一致。

## 验证命令
| 验证项 | 命令 | 结果 |
|--------|------|------|
| cache.py 编译 | `python -m py_compile src/cache.py` | PASS |
| config.py 编译 | `python -m py_compile src/config.py` | PASS |
| engine.py 编译 | `python -m py_compile rag/engine.py` | PASS |
| cache 导入 | `python -c "from src.cache import cache"` | 需 `pip install redis>=5.0.0` 后验证 |

## 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-07-30 | 初始实现：RedisCache 类 + _retrieve() 缓存集成 + config/requirements 更新 | Developer |
