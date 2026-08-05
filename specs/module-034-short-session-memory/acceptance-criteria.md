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

- [ ] 📋 短期记忆 save — 验证方式：save_short 写入 source=`memory:<identity>:short:`
- [ ] 📋 会话摘要生成 — 验证方式：knowledge 对话后异步生成摘要写入 short
- [ ] 📋 短期去重 — 验证方式：同源 short 内语义去重（复用 module-033）
- [ ] 📋 摘要失败降级 — 验证方式：摘要生成失败跳过，不写垃圾

### 1.2 短期记忆召回

- [ ] 📋 短期召回 — 验证方式：recall_short 检索 memory:<identity>:short:%（动态K）
- [ ] 📋 注入位置区分 — 验证方式：短期注入"最近上下文"段、长期注入"持久偏好"段
- [ ] 📋 短期 TTL 过期 — 验证方式：超 settings.memory_short_ttl_days 的记忆被过滤
- [ ] 📋 空短期返回 — 验证方式：无短期记忆返回空，不崩

### 1.3 会话记忆持久化

- [ ] 📋 会话保存 — 验证方式：save_session_messages 写 source=`memory:<identity>:session:`
- [ ] 📋 会话恢复 — 验证方式：get_session_messages 恢复最近会话（刷新/换设备不丢）
- [ ] 📋 会话隔离 — 验证方式：A/B 用户会话互不可见（匿名按 client_ip）
- [ ] 📋 无持久化兜底 — 验证方式：无会话记录时用当前请求 history（零回归）

### 1.4 与长期记忆并存

- [ ] 📋 三前缀并存 — 验证方式：long/short/session 三种 source 互不混淆，各自检索独立
- [ ] 📋 长期记忆零回归 — 验证方式：module-033 长期记忆行为不变（254 基线）

---

## 2. 接口验收

### 2.1 兼容性

- [ ] 📦 memory.save/recall 签名兼容（长期不变）
- [ ] 📦 chat/stream 端点签名不变
- [ ] 📦 记忆 source `memory:<identity>:` 格式不变（新增 short/session 后缀）

### 2.2 配置

- [ ] 📦 短期 TTL / 会话上限可配置（config.py）

---

## 3. 代码质量验收

### 3.1 注释覆盖率

- [ ] 💻 所有 public 方法有 Docstring

### 3.2 命名规范

- [ ] 💻 Python snake_case

### 3.3 代码长度

- [ ] 💻 单方法 ≤ 50 行
- [ ] 💻 模块生产代码 ≤ 450 行（plan 声明调整）

### 3.4 编译检查

- [ ] 💻 py_compile 通过
- [ ] 💻 无未使用 import

---

## 4. 测试验收

### 4.1 单元测试

- [ ] 🧪 test_session_memory.py：会话保存/恢复/隔离/TTL
- [ ] 🧪 test_memory.py short 前缀分层测试
- [ ] 🧪 短期 save/recall/去重测试

### 4.2 回归测试

- [ ] 🧪 `python -m pytest tests/ -q`：254 基线 + 新增通过 / 0 失败（无新增失败）
- [ ] 🧪 身份回归（test_identity.py）

### 4.3 真实 E2E（Tester 可选执行）

- [ ] 🧪 登录对话 → 短期摘要写入 → 新对话召回最近主题
- [ ] 🧪 刷新/换设备会话恢复（会话持久化）
- [ ] 🧪 匿名按 client_ip 隔离短期/会话

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

- [ ] 📝 changelog.md 已更新（含版本/日期/变更/变更人）

### 5.2 设计说明

- [ ] 📝 短期/会话记忆方案记录在 plan.md（§3）

### 5.3 共享记忆

- [ ] 📝 memory/project-context.md 更新（module-034 行 + 技术决策）
- [ ] 📝 memory/agent-activity-log.md 更新（PLAN/CODE/REVIEW/TEST）

---

## 验收执行结果

### 分项统计

| 验收类别 | 总项数 | 通过 | 失败 | 未执行 |
|----------|--------|------|------|--------|
| 功能验收 | 14 | 0 | 0 | 0 |
| 接口验收 | 3 | 0 | 0 | 0 |
| 代码质量验收 | 5 | 0 | 0 | 0 |
| 测试验收 | 8 | 0 | 0 | 0 |
| 文档验收 | 4 | 0 | 0 | 0 |
| **合计** | **34** | **0** | **0** | **0** |

### 验收结论

- 审查人: Reviewer
- 测试人: Tester
- 验收时间: 2026-08-06
- 结论:
  - [ ] ✅ **通过**
  - [ ] ❌ **不通过**
  - [ ] ⚠️ **有条件通过**
- 备注: 待执行

---

> **下一步**：
> - 通过：更新 `memory/project-context.md`，模块标记 ✅
> - 不通过：通知 Developer 修复后重新验收
