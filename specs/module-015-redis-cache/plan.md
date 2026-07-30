# M15: Redis 查询缓存 — 项目计划

## 元信息

| 字段 | 值 |
|------|-----|
| 模块编号 | M15 |
| 模块名称 | Redis Query Cache |
| 版本号 | 0.15.0-module-015 |
| 前置模块 | M5 |
| 范围 | ai_service only |
| 目标 | 缓存 `_retrieve()` 结果 5 分钟，相同查询跳过 embedding+FTS+rerank |

---

## 1. 技术方案

### 1.1 新增 `src/cache.py`
`RedisCache` 类：懒连接、get/set JSON、TTL 300、优雅降级

### 1.2 修改 `config.py`
`redis_url: str = "redis://localhost:6379/0"`

### 1.3 修改 `engine.py` `_retrieve()`
- 入口：cache_key = `rag:retrieve:{sha256(query)[:12]}` → cache.get → 命中直接返回
- 出口：cache.set(cache_key, docs, ttl=300)
- Redis 不可用时静默降级

---

## 2. 文件清单

| # | 文件 | 操作 |
|---|------|------|
| 1 | `ai_service/src/cache.py` | 新建 (RedisCache 类) |
| 2 | `ai_service/src/config.py` | 修改 (+redis_url) |
| 3 | `ai_service/rag/engine.py` | 修改 (+cache import/check/write) |
| 4 | `ai_service/requirements.txt` | 修改 (+redis>=5.0.0) |
