# 功能规格说明书 — Module-033: 长期记忆自动写入（对话结束异步提取 + 语义去重 + 动态 K 召回）

> 本文件由 **Planner** 输出，作为模块开发的唯一权威规格文档。
> Developer 严格按本文件编码，Reviewer 和 Tester 按本文件验收。

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-033 |
| 模块名称 | 长期记忆自动写入 |
| 版本号 | 0.33.0-module-033 |
| 优先级 | P1（记忆架构三件套之二；身份基础 module-032 已就绪） |
| 预估代码量 | **声明调整：≤ 400 行**（跨提取器/去重/召回/接入，默认 200 行不适用） |
| 创建日期 | 2026-08-05 |
| 最后更新 | 2026-08-05 |
| 负责人 | Planner: 规划执行, Developer: 一次性派发闭环 |

---

## 2. 需求描述

### 2.1 需求来源

- 来源类型：用户拍板的三层记忆方案（2026-08-05：032 JWT登录 / 033 长期记忆 / 034 短期+会话）
- 现状：长期记忆**只能手动 save**（`POST /ai/memory/save`），对话结束后**不自动提取**新事实。参考 `llm-push/19-Agent记忆管理_2026-07-30.md` 的设计（语义去重 0.95 / 相似度阈值 0.75 / 动态 K / 时间衰减）。

### 2.2 用户故事

```
作为 登录用户
我想要 对话结束后系统自动从对话提取值得记住的事实沉淀为长期记忆
以便 跨会话记住我的偏好/事实，且记忆库不膨胀（去重）、检索精准（动态 K）
```

### 2.3 验收场景（BDD 格式）

```
场景 1：对话结束自动提取
  假设 用户进行知识库/闲聊对话
  当 对话结束（chat/stream 返回）
  那么 异步从(query, answer)提取值得记住的事实 → 写入 memory:<user_id>:

场景 2：语义去重
  假设 用户两次说了同一偏好（措辞不同）
  当 第二次自动写入
  那么 相似度>0.95 视为重复，更新旧记忆而非新增（记忆库不膨胀）

场景 3：闲聊不存
  假设 intent=casual_chat
  当 对话结束
  那么 不触发记忆提取（避免存垃圾）

场景 4：动态 K 召回
  假设 召回长期记忆
  当 检索
  那么 按候选相似度质量动态调 K（均值>0.85→5 / 0.75-0.85→3 / <0.75→1）

场景 5：格式化注入
  假设 召回记忆注入生成 prompt
  当 生成
  那么 记忆带"[长期记忆 - 日期]：内容"格式化标记

场景 6：异步不阻塞
  假设 自动写入进行中
  当 用户继续对话
  那么 写入不阻塞响应（fire-and-forget）
```

### 2.4 非功能需求

| 类别 | 要求 |
|------|------|
| 异步 | 记忆写入不阻塞 chat/stream 响应（后台任务，失败降级日志） |
| 零回归 | 匿名降级、手动 save/recall 接口行为不变 |
| 安全 | 提取/去重仅本身份记忆；LIKE 注入防护保留 |
| 成本 | 闲聊/实时路径不提取；提取失败降级不影响对话 |

---

## 3. 技术方案

### 3.1 涉及文件

| 文件路径 | 操作类型 | 说明 |
|----------|----------|------|
| `ai_service/rag/memory_extractor.py` | 新增 | 对话→值得记住的事实提取器（LLM 结构化 JSON） |
| `ai_service/rag/memory.py` | 修改 | 语义去重（save 前查重）+ 动态 K 召回 + 格式化注入 |
| `ai_service/rag/engine.py` | 修改 | `_persist_memory`（fire-and-forget）+ chat 接入 |
| `ai_service/main.py` | 修改 | chat_stream 生成后异步触发提取 |
| `ai_service/src/config.py` | 修改 | 记忆配置（去重阈值/动态K阈值） |
| `ai_service/tests/test_memory_extractor.py` | 新增 | 提取器/去重/动态K/格式化 单测 |

### 3.2 业务逻辑说明

#### 功能 1：记忆提取器 `memory_extractor.py`

```
extract_facts(query, answer, history) → list[dict]
  - LLM 调一次：prompt 要求从 (query, answer, 最近历史) 提取"值得长期记住的事实"
  - 输出结构化 JSON: {"facts": [{"content": str, "importance": 0-1}]}
  - 过滤：importance < 阈值(0.6) 或 content 空 → 丢弃
  - 失败/超时 → 返回 []（降级，不影响对话）
  - 不提取：闲聊/实时路径（由调用方按 intent 跳过）
```

#### 功能 2：语义去重 `memory.py save(dedup=True)`

```
save(content, identity, dedup=True)
  - 去重逻辑（写入前）：
    1. 检索本身份现有记忆候选（source=memory:<identity>:%）
    2. 新事实嵌入 vs 现有记忆嵌入，cosine 相似度
    3. 最高相似度 > 0.95 → 视为重复：更新旧记忆（追加/合并）而非新增
    4. < 0.95 → 正常新增
  - 手动 save 默认也去重（防重复事实堆积）
```

#### 功能 3：动态 K 召回 + 格式化注入 `memory.py recall`

```
recall(query, identity) → 格式化记忆文本
  - 动态 K：hybrid_retriever 先取 top_k=5 候选，
    按候选平均相似度动态调整：
      avg > 0.85 → 用 5 条
      0.75 ≤ avg ≤ 0.85 → 用 3 条
      avg < 0.75 → 用 1 条（宁缺毋滥）
  - 格式化注入：每条记忆 → "[长期记忆 - YYYY-MM-DD]：内容"
    （有 created_at 时间戳；无则省略日期）
  - 返回拼接字符串（供 _recall_memory 注入 prompt）
```

#### 功能 4：自动写入接入（fire-and-forget）

```
chat() / chat_stream() 生成答案后：
  - intent == knowledge 且 answer 非空 → 异步触发 _persist_memory
  - casual_chat / realtime → 跳过
  - _persist_memory(query, answer, identity):
      asyncio.create_task 后台执行（不 await，不阻塞响应）
      内部：extract_facts → 逐条 save(dedup=True) → 失败日志降级
```

### 3.3 关键设计决策

| 决策 | 说明 |
|------|------|
| fire-and-forget 异步 | 不阻塞对话响应；失败降级日志，零回归 |
| 提取只对 knowledge 路径 | 闲聊/实时不提取（省成本，避免存垃圾） |
| 去重阈值 0.95 | 参考 19-Agent记忆管理：语义去重 >0.95 视为重复 |
| 动态 K | 参考文档：均值>0.85→5 / 0.75-0.85→3 / <0.75→1 |
| 手动 save 也去重 | 统一防重复事实堆积 |
| 格式化注入 | "[长期记忆 - 日期]：内容"帮助模型区分记忆与当前对话 |

### 3.4 异常处理

| 异常场景 | 处理方式 |
|----------|----------|
| LLM 提取失败/超时 | 返回 []，对话不受影响 |
| 去重检索失败 | 视为无重复，正常新增（不阻塞） |
| 异步写入异常 | 日志 warning，不抛给响应 |
| 提取出空 facts | 不写任何记忆 |

### 3.5 跨模块契约

```
- 记忆 source 保持：memory:<identity>:（user_id 优先，否则 client_ip）——与 module-032 一致
- recall 返回格式：现有 list[dict] 结构不变，新增动态 K 逻辑
- _recall_memory 返回格式化字符串（带 [长期记忆 - 日期] 前缀）
- chat/stream 端点签名不变（内部新增异步触发）
```

---

## 4. 验收标准

> 详细验收标准见同目录下的 `acceptance-criteria.md`

### 4.1 可运行的验证命令

```bash
cd ai_service
python -m pytest tests/test_memory_extractor.py tests/test_memory.py -q   # 新增+既有记忆测试
python -m pytest tests/ -q                                                 # 全量回归
python -m pytest tests/test_identity.py -q                                 # 身份回归
```

### 4.2 预期输出

```
新增单测全过（提取器/去重/动态K/格式化）
全量回归 215 + 新增 通过 / 0 失败
E2E：登录对话 → 自动提取记忆 → 二次同义对话 → 去重不膨胀
```

### 4.3 失败诊断方法

| 失败现象 | 可能原因 | 排查步骤 |
|----------|----------|----------|
| 不自动写记忆 | intent 判定或 create_task 未触发 | 检查日志 _persist_memory |
| 去重没生效 | 相似度未超 0.95 | 检查嵌入/阈值 |
| 动态 K 异常 | 候选为空 | 检查 recall 空候选分支 |

---

## 5. 依赖关系

### 5.1 上游依赖

| 依赖 | 说明 | 状态 |
|------|------|------|
| module-023 | memory.py 基础（save/recall/source 隔离） | ✅ |
| module-032 | identity（user_id）| ✅ |
| module-027 | embedding_service 并发锁 | ✅ |

### 5.2 下游依赖

- module-034（短期记忆+会话）复用本模块的提取器/去重模式。

---

## 6. 风险点与注意事项

### 6.1 已知风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| 异步写入并发 | 多对话同时写 | 低 | 每身份粒度粗，save 事务原子 |
| LLM 提取成本 | 每对话 1 次 LLM | 中 | 仅 knowledge 路径；importance 过滤 |
| 去重误判 | 相似但不同事实被合并 | 低 | 阈值 0.95 保守；可调 |

### 6.2 技术注意事项

- [x] fire-and-forget 用 asyncio.create_task（不阻塞响应）
- [x] 去重复用 embedding_service（cosine）
- [ ] 提取 prompt 明确"值得长期记住"标准（偏好/事实/任务状态）
- [ ] 时间衰减 λ 本期不做（留 module-034 或后续）

### 6.3 开发建议

- 先提取器 → 再去重 → 动态K/格式化 → 最后接入 chat
- 保持 memory.py 接口兼容（save/recall 签名新增可选参数）

---

## 7. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-05 | 初始版本 | Planner |

---

## 8. 审批记录

| 角色 | 姓名 | 审批结果 | 日期 | 备注 |
|------|------|----------|------|------|
| Planner | 规划执行 | ✅ 通过 | 2026-08-05 | |
| Reviewer | | ⏳ 待审查 | | |
| Tester | | ⏳ 待测试 | | |

---

> **下一步**：Developer 根据本规格说明书开始编码实现。
