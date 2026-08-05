# 功能规格说明书 — Module-034: 短期记忆 + 会话记忆

> 本文件由 **Planner** 输出，作为模块开发的唯一权威规格文档。
> Developer 严格按本文件编码，Reviewer 和 Tester 按本文件验收。

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-034 |
| 模块名称 | 短期记忆 + 会话记忆 |
| 版本号 | 0.34.0-module-034 |
| 优先级 | P1（记忆架构三件套之三；module-032 身份 + module-033 长期已就绪） |
| 预估代码量 | **声明调整：≤ 450 行**（跨短期记忆/会话记忆/接入，默认 200 行不适用） |
| 创建日期 | 2026-08-06 |
| 最后更新 | 2026-08-06 |
| 负责人 | Planner: 规划执行, Developer: 一次派发闭环 |

---

## 2. 需求描述

### 2.1 需求来源

- 来源类型：用户拍板的三层记忆方案（2026-08-05：032 JWT登录 / 033 长期记忆 / 034 短期+会话）
- 现状：
  - **会话记忆**：内存态 `IP_SESSION_MESSAGES`（main.py:36），按 client_ip 最多 50 条，**重启丢失**，不跨设备
  - **短期记忆**：**未实现**——无 `memory:<identity>:short:` 分层（module-033 只做长期 `memory:<identity>:`）
  - module-033 Tester 观察：短期/会话是明确缺口，留 module-034

### 2.2 用户故事

```
作为 登录用户
我想要 短期记忆（近期会话摘要/最近主题，TTL 过期）+ 会话记忆（对话历史持久化、跨设备）
以便 记住"最近在做什么"（短期）而不只"长期偏好"（长期），且刷新/换设备不丢对话
```

### 2.3 验收场景（BDD 格式）

```
场景 1：短期记忆自动写入
  假设 用户进行知识库对话
  当 对话结束
  那么 生成会话摘要 → 写入 memory:<identity>:short:（TTL 过期，如 7 天）

场景 2：短期记忆召回
  假设 用户新对话问"我上次聊到哪了"
  当 检索
  那么 召回近期短期记忆（最近主题/摘要）

场景 3：短期记忆 TTL 过期
  假设 短期记忆写入超过有效期
  当 检索/清理
  那么 过期记忆被标记/清理（不参与召回）

场景 4：会话记忆持久化
  假设 用户对话若干轮
  当 刷新/换设备
  那么 会话历史从持久化存储恢复（不再因重启丢失）

场景 5：会话记忆按身份隔离
  假设 用户 A/B 各有过会话
  当 各自访问
  那么 会话按 user_id 隔离（匿名按 client_ip）

场景 6：与长期记忆并存
  假设 同时有短期 + 长期记忆
  当 生成 prompt
  那么 短期注入"最近"上下文、长期注入"持久偏好"，互不混淆
```

### 2.4 非功能需求

| 类别 | 要求 |
|------|------|
| 兼容 | 长期记忆（module-033）行为不变；`memory:<identity>:` 保持 |
| 隔离 | 短期/会话按 identity（user_id 优先否则 client_ip）隔离 |
| 不阻塞 | 短期写入异步（fire-and-forget）；会话持久化不阻塞响应 |
| 成本 | 短期摘要仅在 knowledge 路径生成；TTL 控制膨胀 |

---

## 3. 技术方案

### 3.1 涉及文件

| 文件路径 | 操作类型 | 说明 |
|----------|----------|------|
| `ai_service/rag/memory.py` | 修改 | source 分层 `memory:<identity>:short:` / 长期不变；新增短期 save/recall/清理 |
| `ai_service/rag/session_memory.py` | 新增 | 会话记忆持久化（复用 documents 表，source=`memory:<identity>:session:`） |
| `ai_service/rag/engine.py` | 修改 | 短期记忆召回 + 注入；会话保存/恢复接入 |
| `ai_service/main.py` | 修改 | chat/stream 接入短期摘要生成 + 会话持久化；替换/保留 IP_SESSION_MESSAGES |
| `ai_service/src/config.py` | 修改 | 短期 TTL / 会话上限配置 |
| `ai_service/tests/test_session_memory.py` | 新增 | 会话记忆持久化/隔离/TTL 单测 |
| `ai_service/tests/test_memory.py` | 修改 | short 前缀分层测试 |

### 3.2 业务逻辑说明

#### 功能 1：短期记忆（`memory.py` 扩展）

```
source 分层：
  - 长期：memory:<identity>:          （module-033，不变）
  - 短期：memory:<identity>:short:    （本次新增）
  - 会话：memory:<identity>:session:  （本次新增，见功能 3）

短期记忆 save_short(content, identity):
  - source = memory:<identity>:short:
  - 复用 save 分块/嵌入逻辑（子块带向量参与检索）
  - 复用语义去重（module-033 dedup，同源 short 内查重）

短期记忆 recall_short(query, identity):
  - 检索 memory:<identity>:short:%（复用 hybrid_retriever source_pattern）
  - 动态 K + 格式化注入（复用 module-033 逻辑）
  - 注入位置：生成 prompt 的"最近上下文"段

短期记忆 TTL 清理：
  - 每条短期记忆带 created_at；超过 settings.memory_short_ttl_days（默认 7）视为过期
  - 召回时过滤过期；可选定时/惰性清理
```

#### 功能 2：会话摘要（短期记忆的内容来源）

```
对话结束后（knowledge 路径）：
  - 复用 module-033 的 extract_facts 或轻量摘要 prompt
  - 生成"本次会话摘要"（最近主题/结论/未解决问题）
  - 写入 memory:<identity>:short:（覆盖/合并当日短期摘要，防膨胀）
  - 异步 fire-and-forget（不阻塞响应）
```

#### 功能 3：会话记忆持久化（`session_memory.py`）

```
会话历史持久化（复用 documents 表，source=memory:<identity>:session:）：
  - save_session_messages(identity, messages): 把最近 N 轮对话写入会话记忆
    （按 identity 隔离；每轮一条/或合并一批）
  - get_session_messages(identity, limit): 恢复最近会话历史
    （供 chat 端点 history 参数；刷新/换设备不丢）
  - 与现内存 IP_SESSION_MESSAGES 的关系：
    - 保留 IP_SESSION_MESSAGES 作为会话内即时缓存（快）
    - 新增持久化层（会话结束/定期写库）
    - 或直接替换为持久化（推荐，重启不丢）

会话注入：
  - chat 端点取 request.history 时，优先持久化会话（按 identity）
  - 无持久化 → 用当前请求 history（零回归）
```

### 3.3 关键设计决策

| 决策 | 说明 |
|------|------|
| source 三层分层 | 长期 `memory:<id>:` / 短期 `memory:<id>:short:` / 会话 `memory:<id>:session:`，互不混淆 |
| 短期 TTL 7 天 | 参考 19-Agent记忆管理：任务上下文 7 天；临时笔记 24h（本次 7 天统一，24h 可后续细化） |
| 会话持久化复用 documents | 无新表，复用分块/嵌入/检索链路（与长期记忆一致） |
| 会话摘要异步生成 | 复用 module-033 fire-and-forget 模式，不阻塞 |
| 保留匿名降级 | 会话/短期按 identity（user_id 否则 client_ip）隔离，零回归 |
| IP_SESSION_MESSAGES 处理 | 升级为持久化为主；内存态降级为兜底缓存 |

### 3.4 异常处理

| 异常场景 | 处理方式 |
|----------|----------|
| 短期写入失败 | 异步日志降级，不影响对话 |
| 会话恢复失败 | 返回空 history，用当前请求 history（零回归） |
| TTL 清理失败 | 惰性（召回时过滤过期），不阻塞 |
| 摘要生成失败 | 跳过短期写入，不写垃圾 |

### 3.5 跨模块契约

```
- 长期记忆 source memory:<identity>: 不变（module-032/033 兼容）
- 新增 short / session 前缀，不改变既有检索（长/短/会话 source_pattern 各自独立）
- save/recall 签名兼容（新增可选参数）
- chat/stream 端点签名不变
- 匿名降级（user_id 否则 client_ip）不变
```

---

## 4. 验收标准

> 详细验收标准见同目录下的 `acceptance-criteria.md`

### 4.1 可运行的验证命令

```bash
cd ai_service
python -m pytest tests/test_session_memory.py tests/test_memory.py tests/test_memory_extractor.py -q
python -m pytest tests/ -q   # 全量回归 254 基线
python -m pytest tests/test_identity.py -q   # 身份回归
```

### 4.2 预期输出

```
新增单测全过；全量 254 + 新增 通过 / 0 失败
E2E：登录对话 → 短期摘要写入 → 新对话召回最近主题；刷新/换设备会话恢复
```

### 4.3 失败诊断方法

| 失败现象 | 可能原因 | 排查步骤 |
|----------|----------|----------|
| 短期没写入 | 摘要生成未触发 | 检查 intent/异步触发 |
| 会话不恢复 | source 前缀不对 | 检查 session source |
| TTL 不过期 | 清理逻辑未接 | 检查召回过滤 |

---

## 5. 依赖关系

### 5.1 上游依赖

| 依赖 | 说明 | 状态 |
|------|------|------|
| module-032 | identity（user_id） | ✅ |
| module-033 | 提取器/去重/动态K/格式化（复用） | ✅ |
| module-023/027 | memory.py 基础 + 嵌入锁 | ✅ |

### 5.2 下游依赖

- 无（记忆三件套完成）。

---

## 6. 风险点与注意事项

### 6.1 已知风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| 会话记忆膨胀 | documents 表增长 | 中 | TTL + 上限（每 identity 最多 N 条） |
| 短期/长期混淆 | 注入位置不清 | 中 | source 分层 + 注入段区分 |
| 会话恢复延迟 | 每请求查库 | 低 | 内存缓存兜底 |

### 6.2 技术注意事项

- [x] source 三层分层明确（long/short/session）
- [x] 复用 module-033 提取/去重/动态K（不重复实现）
- [ ] 会话摘要 prompt 明确"最近主题/结论/未解决问题"
- [ ] TTL 值可配置（config.py）

### 6.3 开发建议

- 先 source 分层 → 短期 save/recall → 会话持久化 → 最后接入 chat/stream
- 保持 memory.py 接口兼容

---

## 7. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-06 | 初始版本 | Planner |

---

## 8. 审批记录

| 角色 | 姓名 | 审批结果 | 日期 | 备注 |
|------|------|----------|------|------|
| Planner | 规划执行 | ✅ 通过 | 2026-08-06 | |
| Reviewer | | ⏳ 待审查 | | |
| Tester | | ⏳ 待测试 | | |

---

> **下一步**：Developer 根据本规格说明书开始编码实现。
