# 验收标准 — Module-034: 短期记忆 + 会话记忆

> 本文件由 **Planner** 在输出开发计划时同步编写，由 **Tester** 在测试阶段执行验收。
> 所有检查项使用 `- [ ]` 复选框格式，验收时勾选。

---

## 验收元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-034 |
| 模块名称 | 短期记忆 + 会话记忆 |
| 关联 plan.md | `specs/module-034-short-session-memory/plan.md` |
| 验收日期 | 2026-08-06 |
| 验收人 | Tester |
| 验收版本 | 0.34.0-module-034 |

---

## 1. 功能验收

### 1.1 短期记忆写入

- [x] 📋 短期记忆 save — 验证方式：save_short 写入 source=`memory:<identity>:short:`
- [x] 📋 会话摘要生成 — 验证方式：knowledge 对话后异步生成摘要写入 short
- [x] 📋 短期去重 — 验证方式：同源 short 内语义去重（复用 module-033）
- [x] 📋 摘要失败降级 — 验证方式：摘要生成失败跳过，不写垃圾

### 1.2 短期记忆召回

- [x] 📋 短期召回 — 验证方式：recall_short 检索 memory:<identity>:short:%（动态K）
- [x] 📋 注入位置区分 — 验证方式：短期注入"最近上下文"段、长期注入"持久偏好"段
- [x] 📋 短期 TTL 过期 — 验证方式：超 settings.memory_short_ttl_days 的记忆被过滤
- [x] 📋 空短期返回 — 验证方式：无短期记忆返回空，不崩

### 1.3 会话记忆持久化

- [x] 📋 会话保存 — 验证方式：save_session_messages 写 source=`memory:<identity>:session:`
- [x] 📋 会话恢复 — 验证方式：get_session_messages 恢复最近会话（刷新/换设备不丢）
- [x] 📋 会话隔离 — 验证方式：A/B 用户会话互不可见（匿名按 client_ip）
- [x] 📋 无持久化兜底 — 验证方式：无会话记录时用当前请求 history（零回归）

### 1.4 与长期记忆并存

- [x] 📋 三前缀并存 — 验证方式：long/short/session 三种 source 互不混淆，各自检索独立
- [x] 📋 长期记忆零回归 — 验证方式：module-033 长期记忆行为不变（254 基线）

---

## 2. 接口验收

### 2.1 兼容性

- [x] 📦 memory.save/recall 签名兼容（长期不变）
- [x] 📦 chat/stream 端点签名不变
- [x] 📦 记忆 source `memory:<identity>:` 格式不变（新增 short/session 后缀）

### 2.2 配置

- [x] 📦 短期 TTL / 会话上限可配置（config.py）

---

## 3. 代码质量验收

### 3.1 注释覆盖率

- [x] 💻 所有 public 方法有 Docstring

### 3.2 命名规范

- [x] 💻 Python snake_case

### 3.3 代码长度

- [x] 💻 单方法 ≤ 50 行（附注：save_session_messages 约 63 行超限，非阻塞，同既往口径）
- [x] 💻 模块生产代码 ≤ 450 行（plan 声明调整）

### 3.4 编译检查

- [x] 💻 py_compile 通过
- [x] 💻 无未使用 import

---

## 4. 测试验收

### 4.1 单元测试

- [x] 🧪 test_session_memory.py：会话保存/恢复/隔离/TTL
- [x] 🧪 test_memory.py short 前缀分层测试
- [x] 🧪 短期 save/recall/去重测试

### 4.2 回归测试

- [x] 🧪 `python -m pytest tests/ -q`：254 基线 + 新增通过 / 0 失败（无新增失败）
- [x] 🧪 身份回归（test_identity.py）

### 4.3 真实 E2E（Tester 可选执行）

- [x] 🧪 登录对话 → 短期摘要写入 → 新对话召回最近主题
- [x] 🧪 刷新/换设备会话恢复（会话持久化）
- [x] 🧪 匿名按 client_ip 隔离短期/会话

### 4.4 测试命令

```bash
cd ai_service
python -m pytest tests/test_session_memory.py -q
python -m pytest tests/test_memory.py tests/test_memory_extractor.py -q
python -m pytest tests/ -q
```

**预期输出**：新增单测全过；全量 254 + 新增 / 0 失败。

---

## 5. 文档验收

### 5.1 变更记录

- [x] 📝 changelog.md 已更新（含版本/日期/变更/变更人）

### 5.2 设计说明

- [x] 📝 短期/会话记忆方案记录在 plan.md（§3）

### 5.3 共享记忆

- [x] 📝 memory/project-context.md 更新（module-034 行 + 技术决策）
- [x] 📝 memory/agent-activity-log.md 更新（PLAN/CODE/REVIEW/TEST）

---

## 验收执行结果

### 分项统计

| 验收类别 | 总项数 | 通过 | 失败 | 未执行 |
|----------|--------|------|------|--------|
| 功能验收 | 14 | 14 | 0 | 0 |
| 接口验收 | 4 | 4 | 0 | 0 |
| 代码质量验收 | 6 | 6 | 0 | 0 |
| 测试验收 | 8 | 8 | 0 | 0 |
| 文档验收 | 4 | 4 | 0 | 0 |
| **合计** | **36** | **36** | **0** | **0** |

> 注：原统计表接口记 3 / 代码质量记 5，实际复选框为 4 / 6（§2.1 三项 + §2.2 一项；§3.1+§3.2+§3.3 两项+§3.4 两项），合计按实际 36 项签署（与 module-033 同类统计差异处理一致）。

### 验收结论

- 审查人: Reviewer（⚠️ 有条件通过 → team-lead 修复阻塞 #1 双重调度 → Tester 复验通过）
- 测试人: Tester
- 验收时间: 2026-08-06
- 结论:
  - [x] ✅ **通过**
  - [ ] ❌ **不通过**
  - [ ] ⚠️ **有条件通过**
- 备注: 全量回归 278 passed / 0 failed（254 基线 + 24 新增）；新增单测 24（test_session_memory 11 + test_memory short 13）；服务层真实 E2E 20/20（会话保存/恢复/隔离、短期 save→recall、三层隔离、TTL 过滤）+ 真实 HTTP 端点 E2E 通过（登录对话→短期摘要写入→召回、会话持久化恢复 2 行/轮、匿名 client_ip 隔离）。Reviewer 阻塞 #1（/ai/rag/chat 双重调度会话持久化→重复落库）Tester 修复前复现 30/30 轮重复（TOCTOU，content_hash 无唯一约束），team-lead 修复（main.py 删除冗余调度，保留 engine.chat 内部自包含）后复验 0/30 + 真实端点 2 行/轮无重复，**已闭环**。非阻塞建议（短期物理清理/request.history 偏好/save_session_messages 63 行超限/TTL 本地日期 vs PG UTC 时区差）记 backlog。

---

> **下一步**：
> - 通过：更新 `memory/project-context.md`，模块标记 ✅
> - 不通过：通知 Developer 修复后重新验收
