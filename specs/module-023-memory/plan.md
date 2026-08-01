# 功能规格说明书 — Module-023: 长期记忆

> 本文件由 **Planner** 输出，作为模块开发的唯一权威规格文档。
> Developer 严格按本文件编码，Reviewer 和 Tester 按本文件验收。

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-023 |
| 模块名称 | 长期记忆（跨会话记忆沉淀） |
| 版本号 | 0.23.0-module-023 |
| 优先级 | P1 |
| 预估代码量 | ≤ 300 行（含存储/写入/检索，需调整上限） |
| 创建日期 | 2026-08-01 |
| 最后更新 | 2026-08-01 |
| 负责人 | Planner: 规划执行, Developer: 待分配 |

> **代码量调整理由**：含记忆存储（复用 documents）、写入逻辑、检索注入、API 端点。约 300 行。

---

## 2. 需求描述

### 2.1 需求来源

- 来源类型：发散路线图 P1 + 用户确认
- 原始描述：系统无长期记忆（只有 Redis 短期缓存 + 内存 IP 会话，重启丢失）。需跨会话记住用户偏好/历史结论。

### 2.2 用户故事

```
作为 RAG 系统用户
我想要 系统记住我之前问过的问题和偏好
以便 下次对话能引用历史结论（"上次你问过 X，当时结论是 Y"）
```

### 2.3 验收场景（BDD 格式）

```
场景 1：保存记忆
  假设 用户完成一次对话
  当 调用保存记忆接口
  那么 记忆作为文档入库（source='memory:<ip>'）

场景 2：检索记忆
  假设 新会话开始
  当 检索相关记忆
  那么 返回与当前问题相关的历史记忆

场景 3：记忆注入回答
  假设 检索到相关记忆
  当 生成回答
  那么 回答引用历史结论
```

### 2.4 非功能需求

| 类别 | 要求 |
|------|------|
| 复用 | 复用 documents 表 + embedding + 检索管线 |
| 隔离 | 按 IP 隔离（source 前缀） |
| 不回归 | 无记忆时行为与现在完全一致 |

---

## 3. 技术方案

### 3.1 涉及文件

| 文件路径 | 操作类型 | 说明 |
|----------|----------|------|
| `ai_service/rag/memory.py` | 新增 | 长期记忆服务（写入/检索） |
| `ai_service/main.py` | 修改 | 新增 /ai/memory 端点 |
| `ai_service/rag/engine.py` | 修改 | chat 生成前检索记忆注入 |
| `ai_service/rag/schemas.py` | 修改 | 新增记忆请求/响应模型 |

### 3.2 数据库变更

无新表（复用 documents 表，`source='memory:<ip>'` 区分）。

### 3.3 API 接口定义

#### 接口 1：保存记忆

```yaml
请求方法: POST
请求路径: /ai/memory/save
请求体:
  {
    "content": "用户偏好简短 Java 回答",
    "ip": "192.168.1.1"
  }

成功响应:
  {"code": 0, "data": {"id": 1, "title": "记忆-2026-08-01-01", "status": "saved"}}
```

#### 接口 2：检索记忆

```yaml
请求方法: POST
请求路径: /ai/memory/recall
请求体:
  {"query": "Java 线程池", "ip": "192.168.1.1"}

成功响应:
  {"code": 0, "data": {"memories": [{"content": "...", "score": 0.8}]}}
```

### 3.4 业务逻辑说明

#### 核心流程

```
1. memory.py MemoryService:
   save(content, ip):
     - 分块（复用 chunker）→ 写 documents（source='memory:<ip>'）
     - 向量化（复用 embedding_service）→ 1024 维
   recall(query, ip):
     - 检索 source LIKE 'memory:<ip>%' 的记忆文档
     - 复用 hybrid_retriever（限定 source 过滤）
     - 返回 Top-K 相关记忆

2. main.py 端点:
   POST /ai/memory/save
   POST /ai/memory/recall

3. engine.chat 注入:
   - 生成前调用 memory.recall(query, ip)
   - 若命中记忆 → 拼入生成 prompt（"历史记忆: ..."）
   - 无记忆 → 行为不变（零回归）
```

#### 关键设计决策

| 决策 | 说明 |
|------|------|
| 复用 documents 表 | 无新表，复用分块/向量/检索全链路 |
| source='memory:<ip>' | 按 IP 隔离，检索时 source LIKE 过滤 |
| 生成前注入 | 记忆作为额外上下文，不影响无记忆路径 |
| 简单总结优先 | 不自动总结会话（避免复杂度），提供 save 接口由前端/会话结束触发 |

### 3.5 异常处理

| 异常场景 | 异常类型 | 处理方式 |
|----------|----------|----------|
| 记忆写入失败 | Exception | 返回错误码，不崩 |
| 记忆检索失败 | Exception | 返回空记忆，回答照常 |
| embedding 不可用 | Exception | 记忆向量化失败，跳过 |

---

## 4. 验收标准

> 详细验收标准见同目录下的 `acceptance-criteria.md`

### 4.1 可运行的验证命令

```bash
cd ai_service
# 1. 保存记忆
curl -X POST http://localhost:8000/ai/memory/save \
  -H "Content-Type: application/json" \
  -d '{"content": "用户偏好简洁回答", "ip": "192.168.1.1"}'

# 2. 检索记忆
curl -X POST http://localhost:8000/ai/memory/recall \
  -H "Content-Type: application/json" \
  -d '{"query": "回答风格", "ip": "192.168.1.1"}'

# 3. 回归
python -m pytest ai_service/tests/ -x
```

### 4.2 预期输出

```
# 保存
{"code": 0, "data": {"id": 1, "status": "saved"}}

# 检索
{"code": 0, "data": {"memories": [{"content": "用户偏好简洁回答", "score": 0.85}]}}
```

### 4.3 失败诊断方法

| 失败现象 | 可能原因 | 排查步骤 |
|----------|----------|----------|
| 保存失败 | embedding 不可用 | 检查本地嵌入模型 |
| 检索为空 | source 过滤错误 | 检查 source 前缀 |
| 记忆不注入 | engine 注入逻辑 | 检查 recall 调用点 |

---

## 5. 依赖关系

### 5.1 上游依赖

| 依赖模块 | 依赖内容 | 状态 |
|----------|----------|------|
| module-005: RAG 核心 | chunker + embedding + retriever | ✅ |
| module-020 | 本地嵌入（记忆向量化） | ✅ |

### 5.2 下游依赖

无（独立功能）。

### 5.3 外部依赖

无（全部本地）。

---

## 6. 风险点与注意事项

### 6.1 已知风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| 记忆质量 | 总结不当 | 中 | 提供手动 save 接口，后续可加自动总结 |
| 记忆膨胀 | 无限增长 | 中 | 按 IP 隔离，可清理 |

### 6.2 技术注意事项

- [x] 复用 documents 表（source='memory:<ip>'）
- [x] 检索需限定 source（避免记忆污染知识库检索）
- [x] 无记忆时零回归

### 6.3 开发建议

- 优先实现 MemoryService（save/recall）
- 再挂 API 端点 + engine 注入
- 记忆内容由用户/会话结束提供（不自动总结）

---

## 7. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-01 | 初始版本 | Planner |

---

## 8. 审批记录

| 角色 | 姓名 | 审批结果 | 日期 | 备注 |
|------|------|----------|------|------|
| Planner | 规划执行 | ✅ 通过 | 2026-08-01 | |
| Reviewer | | ⏳ 待审查 | | |
| Tester | | ⏳ 待测试 | | |

---

> **下一步**：Developer 根据本规格说明书开始编码实现。
