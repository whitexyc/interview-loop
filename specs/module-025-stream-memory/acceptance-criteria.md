# 验收标准 — Module-025: 流式记忆接入

> 本文件由 **Planner** 在输出开发计划时同步编写，由 **Tester** 在测试阶段执行验收。
> 所有检查项使用 `- [ ]` 复选框格式，验收时勾选。

---

## 验收元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-025 |
| 模块名称 | 流式记忆接入（chat_stream 记忆注入） |
| 关联 plan.md | `specs/module-025-stream-memory/plan.md` |
| 验收日期 | 2026-08-01 |
| 验收人 | Tester |
| 验收版本 | 0.25.0-module-025 |

---

## 1. 功能验收

### 1.1 核心功能验收

- [x] 📋 流式记忆注入 — 验证方式：有记忆时 chat_stream 生成 prompt 含记忆
- [x] 📋 无记忆零回归 — 验证方式：无记忆时 chat_stream 行为不变
- [x] 📋 记忆检索超时降级 — 验证方式：检索超时返回空串不崩

### 1.2 边界条件验收

- [x] 🔲 client_ip 未取到：默认 'unknown'，不崩
- [x] 🔲 记忆为空：memory 参数空串

### 1.3 异常场景验收

- [x] ⚡ 记忆检索失败：返回空串，生成照常
- [x] ⚡ SSE 流式正常：事件格式不变

---

## 2. 接口验收

### 2.1 chat_stream 接口

- [x] 📦 SSE 事件格式不变（step/token/done/error）
- [x] 📦 记忆注入不影响检索/反思步骤

### 2.2 记忆传递

- [x] 📦 generate_answer_stream 收到 memory 参数
- [x] 📦 memory 为空串时行为不变

---

## 3. 代码质量验收

### 3.1 注释覆盖率

- [x] 💻 记忆注入逻辑有行内注释

### 3.2 命名规范

- [x] 💻 变量符合 snake_case

### 3.3 代码长度

- [x] 💻 单个方法 ≤ 50 行
- [x] 💻 本模块新增代码 ≤ 50 行

### 3.4 编译检查

- [x] 💻 Python 语法通过
- [x] 💻 无未使用 import

---

## 4. 测试验收

### 4.1 单元测试

- [x] 🧪 记忆注入调用逻辑

### 4.2 集成测试

- [x] 🧪 有记忆时流式生成含记忆
- [x] 🧪 无记忆零回归

### 4.3 回归测试

- [x] 🧪 `python -m pytest ai_service/tests/ -x` 无新增失败
- [x] 🧪 chat_stream SSE 正常

### 4.4 测试命令

```bash
cd ai_service
# 保存记忆
curl -X POST http://localhost:8000/ai/memory/save \
  -H "Content-Type: application/json" \
  -d '{"content": "用户偏好简洁回答", "ip": "192.168.1.1"}'

# 流式对话
curl -X POST http://localhost:8000/ai/rag/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "回答风格", "history": [], "client_ip": "192.168.1.1"}'

# 回归
python -m pytest ai_service/tests/ -x
```

**预期输出**：
```
SSE 事件流正常（step/token/done）
===== 0 failed, N passed =====
```

---

## 5. 文档验收

### 5.1 变更记录

- [x] 📝 changelog.md 已更新
- [x] 📝 包含版本号/日期/变更内容/变更人

### 5.2 设计说明

- [x] 📝 接入方案记录在 plan.md

---

## 验收执行结果

### 分项统计

| 验收类别 | 总项数 | 通过 | 失败 | 未执行 |
|----------|--------|------|------|--------|
| 功能验收 | 7 | 7 | 0 | 0 |
| 接口验收 | 4 | 4 | 0 | 0 |
| 代码质量验收 | 6 | 6 | 0 | 0 |
| 测试验收 | 5 | 5 | 0 | 0 |
| 文档验收 | 3 | 3 | 0 | 0 |
| **合计** | **25** | **25** | **0** | **0** |

### 失败详情

| 序号 | 类别 | 失败项 | 失败原因 | 建议修复方式 |
|------|------|--------|----------|--------------|
| — | — | 无 | — | — |

### 验收结论

- 审查人: Reviewer
- 测试人: Tester
- 验收时间: 2026-08-01
- 结论:
  - [x] ✅ **通过**
  - [ ] ❌ **不通过**
  - [ ] ⚠️ **有条件通过**
- 备注: 25/25 验收项通过。专项单测 5/5 通过；全量回归 101 passed + 2 既有 async 技术债务失败（test_engine.py 缺 pytest-asyncio，module-018 已记录，非本次回归，无新增失败）。半真实 E2E 验证流式对话引用真实记忆（LLM 429 阻塞，按任务指引验证记忆检索 + 参数传递）。测试报告见 test-report.md。

---

> **下一步**：
> - 通过：更新 `memory/project-context.md`，模块标记 ✅
> - 不通过：通知 Developer 修复后重新验收
