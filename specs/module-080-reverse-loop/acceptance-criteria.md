# 验收标准 — Module-080: 反向闭环（低分题→待学笔记→自动抓取优先级）

## 1. 功能验收

### 1.1 核心路径验收
- [ ] AC-1.1: `POST /ai/weak-topics/ingest` 端点可接受 `{"topic": "Redis持久化", "context": "RDB快照原理不清楚", "identity": "test-user"}` 并返回 `{"code": 0, "data": {"id": <int>, "title": "Redis持久化", "status": "saved"}}`
- [ ] AC-1.2: 待学笔记落库后，documents 表中存在 source=`weak_topic:test-user:` 的记录，title="Redis持久化"，content 包含 "RDB快照原理不清楚"
- [ ] AC-1.3: `GET /ai/weak-topics` 端点返回当前身份的待学笔记列表（按身份隔离，不同身份互不可见）
- [ ] AC-1.4: `POST /ai/crawl/sources` 端点支持 `priority` 字段（如 `{"url_pattern": "https://redis.io/docs", "name": "Redis官方", "priority": 5}`），`GET /ai/crawl/sources` 返回含 priority 字段
- [ ] AC-1.5: `source_configs` 表存在 `priority INTEGER NOT NULL DEFAULT 0` 列（幂等，二次启动不报错）
- [ ] AC-1.6: 待学笔记主题关键词与源 url_pattern/name 匹配时，`POST /ai/crawl/run` 抓取顺序体现优先级（高优先源先抓）
- [ ] AC-1.7: 待学笔记与知识库检索隔离——`POST /ai/rag/search` 不返回 weak_topic 前缀的文档

### 1.2 边界条件验收
- [ ] AC-2.1: topic 为空字符串时返回 `{"code": 1, "msg": "topic 不能为空"}`
- [ ] AC-2.2: 同一 identity + 同一 topic 重复提交时，去重机制生效（不产生重复记录，status="updated" 或不新增）
- [ ] AC-2.3: priority 字段缺省时默认为 0（向后兼容，存量源不受影响）
- [ ] AC-2.4: 待学笔记无匹配源时，抓取顺序保持默认（priority=0），不报错

### 1.3 异常场景验收
- [ ] AC-3.1: embedding_service 不可用时，待学笔记仍可落库（向量为 NULL，降级保存）
- [ ] AC-3.2: DB 不可用时，`/ai/weak-topics/ingest` 返回 500 错误而非崩溃
- [ ] AC-3.3: 抓取优先级计算异常时不阻断正常抓取（降级为默认优先级）

## 2. 非功能验收

### 2.1 性能验收
- [ ] AC-4.1: `POST /ai/weak-topics/ingest` 端点响应时间 ≤ 2000ms（含嵌入）
- [ ] AC-4.2: 优先级计算（待学笔记关键词匹配）对 100 个源的排序耗时 ≤ 10ms

### 2.2 代码质量验收
- [ ] AC-5.1: 新增生产代码 ≤ 200 行（不含注释/docstring/测试）
- [ ] AC-5.2: 所有新公共方法有 docstring
- [ ] AC-5.3: 无跨层调用（weak_topics.py 不直接调用 crawler.py）
- [ ] AC-5.4: 新增配置项有 PW_ 前缀环境变量支持
- [ ] AC-5.5: init_db 幂等（二次启动不报错）

### 2.3 隔离验收
- [ ] AC-6.1: weak_topic 前缀文档不在 `/ai/documents` 知识库管理面板显示（对齐 memory:% 排除）
- [ ] AC-6.2: 不同 identity 的待学笔记互不可见

## 3. 可运行验证命令

| 验收项 | 验证命令 | 预期输出 |
|--------|----------|----------|
| AC-1.1 落库 | `curl -X POST http://localhost:8001/ai/weak-topics/ingest -H "Content-Type: application/json" -d '{"topic":"Redis持久化","context":"RDB快照原理不清楚","identity":"test-080"}'` | `{"code":0,"data":{"id":<int>,"title":"Redis持久化","status":"saved"}}` |
| AC-1.3 列表 | `curl http://localhost:8001/ai/weak-topics?identity=test-080` | `{"code":0,"data":{"topics":[...]}}` 包含 "Redis持久化" |
| AC-1.4 源配置 | `curl -X POST http://localhost:8001/ai/crawl/sources -H "Content-Type: application/json" -d '{"url_pattern":"https://redis.io/docs","name":"Redis官方","priority":5}'` | `{"code":0,"data":{"priority":5,...}}` |
| AC-1.4 源列表 | `curl http://localhost:8001/ai/crawl/sources` | 返回含 `priority` 字段 |
| AC-1.5 DDL 幂等 | 启动服务两次，观察日志 | 两次均打印 "source_configs 表 priority 列已就绪"，无报错 |
| AC-1.6 优先级抓取 | `curl -X POST http://localhost:8001/ai/crawl/run`（已有 Redis 源 priority=5 + 待学笔记 "Redis"） | 日志显示 Redis 源先于其他源抓取 |
| AC-1.7 隔离 | `curl -X POST http://localhost:8001/ai/rag/search -H "Content-Type: application/json" -d '{"query":"Redis持久化","top_k":5}'` | results 不含 source 以 `weak_topic:` 开头的文档 |
| AC-2.1 空 topic | `curl -X POST http://localhost:8001/ai/weak-topics/ingest -H "Content-Type: application/json" -d '{"topic":"","context":"test"}'` | `{"code":1,"msg":"topic 不能为空"}` |
| AC-2.3 默认 priority | `curl -X POST http://localhost:8001/ai/crawl/sources -H "Content-Type: application/json" -d '{"url_pattern":"https://example.com","name":"Test"}'` | 返回中 `priority=0` |
| AC-5.1 代码量 | `git diff --numstat HEAD -- ai_service/` | 新增生产代码 ≤ 200 行 |
| AC-5.5 幂等 DDL | `python -c "import asyncio; from src.database import init_db; asyncio.run(init_db())"` 二次运行 | 无报错 |
| pytest 全量 | `cd ai_service && python -m pytest tests/ -q` | 全量通过，无新增失败 |

## 4. 端到端闭环验证（核心验收场景）

### 场景 A: 手动录入待学笔记 → 抓取优先级生效
```bash
# 1. 添加一个 Redis 相关源（priority=0）
curl -X POST http://localhost:8001/ai/crawl/sources \
  -H "Content-Type: application/json" \
  -d '{"url_pattern":"https://redis.io/docs","name":"Redis官方文档"}'

# 2. 添加一个 Spring 相关源（priority=0）
curl -X POST http://localhost:8001/ai/crawl/sources \
  -H "Content-Type: application/json" \
  -d '{"url_pattern":"https://spring.io/docs","name":"Spring官方文档"}'

# 3. 录入待学笔记："Redis持久化" 薄弱
curl -X POST http://localhost:8001/ai/weak-topics/ingest \
  -H "Content-Type: application/json" \
  -d '{"topic":"Redis持久化","context":"RDB快照原理不清楚","identity":"test-080"}'

# 4. 触发抓取，观察日志中 Redis 源先于 Spring 源被抓取
curl -X POST http://localhost:8001/ai/crawl/run

# 预期：日志显示 "开始递归抓取: Redis官方文档 (..., priority_boost=10)" 先于 Spring 源
```

### 场景 B: feedback 驱动（端到端自动链路）
```bash
# 1. 用户对话中踩了一条 AI 回复
curl -X POST http://localhost:8001/ai/feedback \
  -H "Content-Type: application/json" \
  -d '{"message_id":990001,"rating":-1,"comment":"Kafka分区机制不清楚","identity":"test-080"}'

# 2. 调用待学笔记录入（可由定时任务或手动触发）
curl -X POST http://localhost:8001/ai/weak-topics/ingest \
  -H "Content-Type: application/json" \
  -d '{"topic":"Kafka分区","context":"Kafka分区机制不清楚","identity":"test-080"}'

# 3. 验证待学笔记已落库
curl http://localhost:8001/ai/weak-topics?identity=test-080

# 4. 后续抓取时，Kafka 相关源优先级提升
```

## 5. 验收结论
- 审查人: Reviewer（2026-08-26，✅ 通过）
- 测试人: Tester（2026-08-26）
- 验收时间: 2026-08-26
- 结论: [x] 通过 / [ ] 不通过
- 备注: 定向 22/22 全绿 + 全量 1449/4 基线/3 skipped + py_compile 6/6 + DB 幂等验证通过。真实冒烟因 8001 未加载 080 代码返回 404，仅执行静态验证；编排者重启服务后需补跑真实冒烟。附条件通过。
