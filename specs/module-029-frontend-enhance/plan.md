# 功能规格说明书 — Module-029: 前端增强（SSE 工具轨迹展示 + 降级链动态调序）

> 本文件由 **Planner** 输出，作为模块开发的唯一权威规格文档。
> Developer 严格按本文件编码，Reviewer 和 Tester 按本文件验收。

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-029 |
| 模块名称 | 前端增强（SSE 工具轨迹展示 + 降级链动态调序） |
| 版本号 | 0.29.0-module-029 |
| 优先级 | P2 |
| 预估代码量 | ≤ 400 行（前端组件 + 后端 API + 测试） |
| 创建日期 | 2026-08-02 |
| 最后更新 | 2026-08-02 |
| 负责人 | Planner: 规划执行, Developer: 待分配 |

---

## 2. 需求描述

### 2.1 需求来源

- 来源类型：module-028 后续 + 用户确认（1+2 合并）
- 原始描述：
  ① SSE 工具轨迹前端展示：module-028 后端已发 tool_call/tool_result 事件，前端未展示"Agent 在想什么"。
  ② 降级链动态调序：目前链顺序是 .env 静态配置，改需重启。需支持前端手动调整供应商顺序。

### 2.2 用户故事

```
作为 RAG 系统用户
我想要 ① 看到 Agent 正在调用什么工具（可视化 Agent 思维）
      ② 手动调整 LLM 供应商顺序（不用改配置重启）
以便 理解 Agent 行为、灵活控制供应商优先级
```

### 2.3 验收场景（BDD 格式）

```
场景 1：工具轨迹展示
  假设 走 Agent 端点（流式）
  当 每次工具调用
  那么 前端展示"正在调用 search_knowledge"等工具卡片

场景 2：动态调序
  假设 前端调整供应商顺序
  当 保存
  那么 后续 LLM 调用按新顺序降级

场景 3：调序持久化
  假设 调整顺序后重启服务
  当 重新加载
  那么 顺序保持（Redis 持久化）
```

### 2.4 非功能需求

| 类别 | 要求 |
|------|------|
| 兼容 | 现有聊天界面不破坏 |
| 持久 | 调序存 Redis，跨重启 |
| 即时 | 调序后立即生效（不用重启服务） |

---

## 3. 技术方案

### 3.1 涉及文件

| 文件路径 | 操作类型 | 说明 |
|----------|----------|------|
| `frontend/src/pages/ChatPage.tsx` | 修改 | 接入工具轨迹展示 |
| `frontend/src/components/PipelinePanel.tsx` | 修改 | 新增工具轨迹步骤 |
| `frontend/src/services/ragService.ts` | 修改 | 解析 tool_call/tool_result 事件 |
| `frontend/src/types/rag.ts` | 修改 | 新增工具轨迹类型 |
| `ai_service/main.py` | 修改 | 新增 /ai/llm/chain GET/PUT |
| `ai_service/llm/client.py` | 修改 | 动态链支持（clear_cache 后重建） |
| `ai_service/src/cache.py` | 修改 | 链顺序存 Redis |

### 3.2 业务逻辑说明

#### 功能 1：SSE 工具轨迹前端展示

```
后端（已就绪，module-028）:
  /ai/rag/chat/agent → SSE 事件 tool_call / tool_result / token / done

前端:
  1. ragService 新增 agentStream() 解析 tool_call/tool_result 事件
  2. ChatPage 用 agentStream（新增"Agent 模式"开关，或复用现有流式入口）
  3. PipelinePanel 新增"工具轨迹"步骤，展示工具调用卡片（工具名+参数+结果摘要）
```

#### 功能 2：降级链动态调序

```
后端:
  1. GET /ai/llm/chain → 返回当前链顺序
  2. PUT /ai/llm/chain {chain: ["deepseek","qwen","zhipu"]} →
     - 校验链合法（都在支持的供应商内、不重复）
     - 存 Redis（key: llm:fallback_chain）
     - LLMFactory.clear_cache() → 下次 get_client("fallback") 按新链重建
  3. 启动时：优先读 Redis 链，无则用配置默认

前端:
  1. 新增"LLM 供应商顺序"设置（可拖拽/上下移排序）
  2. 保存 → PUT /ai/llm/chain
  3. 加载时 → GET /ai/llm/chain 显示当前顺序
```

#### 关键设计决策

| 决策 | 说明 |
|------|------|
| 链存 Redis | 跨重启持久，不写 .env（无需重启服务） |
| clear_cache 重建 | FallbackClient 实例销毁重建，按新链 |
| 启动读 Redis 优先 | 持久化的用户配置优先于默认 |
| 工具轨迹复用 PipelinePanel | 已有管线面板，加步骤即可 |

### 3.3 异常处理

| 异常场景 | 异常类型 | 处理方式 |
|----------|----------|----------|
| 链校验失败 | ValueError | 返回错误，不修改 |
| Redis 不可用 | Exception | 调序不生效但服务正常（用配置默认） |
| 工具事件解析失败 | — | 跳过该事件，不影响对话 |

---

## 4. 验收标准

> 详细验收标准见同目录下的 `acceptance-criteria.md`

### 4.1 可运行的验证命令

```bash
cd ai_service
# 1. 动态调序 API
curl -X GET http://localhost:8000/ai/llm/chain
curl -X PUT http://localhost:8000/ai/llm/chain \
  -H "Content-Type: application/json" \
  -d '{"chain": ["zhipu", "deepseek", "qwen"]}'
curl -X GET http://localhost:8000/ai/llm/chain  # 应返回新顺序

# 2. 回归
python -m pytest ai_service/tests/ -x

# 3. 前端（构建 + 测试）
cd frontend
npm run build
npm test
```

### 4.2 预期输出

```
GET /ai/llm/chain → {"code":0, "data": {"chain": ["deepseek","qwen","zhipu"]}}
PUT 后 GET → 新顺序
pytest 0 failed
npm build / test 通过
```

### 4.3 失败诊断方法

| 失败现象 | 可能原因 | 排查步骤 |
|----------|----------|----------|
| 调序不生效 | clear_cache 未调用 | 检查 PUT 是否清缓存 |
| 重启后顺序丢失 | Redis 未读 | 检查启动读 Redis 逻辑 |
| 工具轨迹不显示 | 事件解析失败 | 检查 ragService 解析 |

---

## 5. 依赖关系

### 5.1 上游依赖

| 依赖模块 | 依赖内容 | 状态 |
|----------|----------|------|
| module-028 | Agent 端点 + SSE 工具事件 | ✅ |
| module-022 | cache.delete_by_prefix | ✅ |

### 5.2 下游依赖

无（独立增强）。

---

## 6. 风险点与注意事项

### 6.1 已知风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| 前端改动破坏聊天 | 现有界面回归 | 中 | 增量加组件，不重构现有 |
| 链校验遗漏 | 非法顺序 | 低 | 白名单校验 |

### 6.2 技术注意事项

- [x] 链存 Redis 而非 .env（跨重启）
- [x] clear_cache 后重建 FallbackClient
- [x] 工具轨迹复用 PipelinePanel
- [ ] 前端 Agent 模式开关（避免改变现有交互）

### 6.3 开发建议

- 优先后端调序 API（独立可测），再前端
- 工具轨迹展示用现有 PipelinePanel 扩展

---

## 7. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-02 | 初始版本 | Planner |

---

## 8. 审批记录

| 角色 | 姓名 | 审批结果 | 日期 | 备注 |
|------|------|----------|------|------|
| Planner | 规划执行 | ✅ 通过 | 2026-08-02 | |
| Reviewer | | ⏳ 待审查 | | |
| Tester | | ⏳ 待测试 | | |

---

> **下一步**：Developer 根据本规格说明书开始编码实现。
