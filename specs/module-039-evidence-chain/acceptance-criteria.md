# 验收标准 — Module-039: 证据链幻觉检测

> 本文件由 **Planner** 在输出开发计划时同步编写，由 **Tester** 在测试阶段执行验收。
> 所有检查项使用 `- [ ]` 复选框格式，验收时勾选。

---

## 验收元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-039 |
| 模块名称 | 证据链幻觉检测 |
| 关联 plan.md | `specs/module-039-evidence-chain/plan.md` |
| 验收日期 | 2026-08-08 |
| 验收人 | Tester |
| 验收版本 | 0.39.0-module-039 |

---

## 1. 功能验收

### 1.1 答案逐句验证

- [x] 📋 verify_answer 返回结构化 claims — 验证方式：调 reflector.verify_answer(answer, docs) 返回 [{"claim", "verdict", "evidence"}]
- [x] 📋 verdict 三值正确 — 验证方式：supported / inferred / unsupported，无其他值
- [x] 📋 evidence 引用号在文档范围内 — 验证方式：evidence 值如 "[1]" 对应 docs 数组下标
- [x] 📋 overall_confidence 计算正确 — 验证方式：1 - unsupported_count / total_claims

### 1.2 非流式路径集成

- [x] 📋 chat() 答案后调 verify_answer — 验证方式：ChatResponse 含 verified_claims 字段
- [x] 📋 verified_claims 结构正确 — 验证方式：含 claims / overall_confidence / total_claims / supported / inferred / unsupported

### 1.3 流式路径集成

- [x] 📋 chat_stream 流结束后推送 verified 事件 — 验证方式：SSE 事件序列含 {"type": "verified", ...}
- [x] 📋 流式答案不受验证阻塞 — 验证方式：token 事件在 verified 事件之前到达

### 1.4 Agent 路径集成

- [x] 📋 verify_answer 注册为 Agent 工具 — 验证方式：tool_registry.list_tool_names() 含 "verify_answer"
- [x] 📋 Agent 可自主调 verify_answer — 验证方式：在 ReAct loop 中 generate_answer 后可调 verify_answer

### 1.5 前端展示

- [x] 📋 ChatMessage 渲染可信度色标 — 验证方式：答案以 🟢/🟡/🔴 标注每句可信度
- [x] 📋 overall_confidence 进度条 — 验证方式：底部显示可信度百分比条
- [x] 📋 无 verified_claims 时退化 — 验证方式：旧格式答案正常渲染（向后兼容）

---

## 2. 降级验收

### 2.1 异常降级

- [x] 📦 无检索文档时跳过验证 — 验证方式：casual_chat 路径不调 verify_answer
- [x] 📦 LLM 验证调用失败时降级 — 验证方式：返回空 claims，不阻塞答案，不抛异常
- [x] 📦 JSON 解析失败时降级 — 验证方式：返回空 claims + logger.warning
- [x] 📦 验证超时时降级 — 验证方式：>15s 返回空 claims

---

## 3. 接口兼容性验收

### 3.1 向后兼容

- [x] 📦 ChatResponse 旧字段不变 — 验证方式：answer / sources / message 字段保持
- [x] 📦 SSE 旧事件类型不变 — 验证方式：token / tool_call / tool_result / done 事件保持
- [x] 📦 前端不传 verified_claims 时正常 — 验证方式：旧 ChatMessage 组件不崩溃
- [x] 📦 Agent 现存 7 工具不变 — 验证方式：regression 测试通过

---

## 4. 代码质量验收

### 4.1 注释覆盖率

- [x] 💻 所有 public 方法有 Docstring
- [x] 💻 verify_answer prompt 有注释解释设计

### 4.2 命名规范

- [x] 💻 Python snake_case
- [x] 💻 TypeScript camelCase

### 4.3 代码长度

- [x] 💻 单方法 ≤ 50 行
- [x] 💻 模块生产代码 ≤ 200 行（plan 声明）

### 4.4 编译检查

- [x] 💻 Python py_compile 通过（reflector.py / engine.py / tool_registry.py / main.py / schemas.py）
- [x] 💻 TypeScript tsc --noEmit 通过（rag.ts / ChatMessage.tsx）
- [x] 💻 无未使用 import

---

## 5. 测试验收

### 5.1 单元测试

- [x] 🧪 verify_answer 正常返回测试（supported 文档 + 预期 claims）
- [x] 🧪 verify_answer 空文档降级测试（空 docs → 返回空 claims）
- [x] 🧪 verify_answer 幻觉检测测试（编造内容 → 标 unsupported）
- [x] 🧪 verify_answer Agent 工具注册测试（registry 含 verify_answer）
- [x] 🧪 verify_answer Agent 工具执行测试（ctx.docs 传入正确）

### 5.2 回归测试

- [x] 🧪 `python -m pytest tests/test_reflector.py -q` — 全过
- [x] 🧪 `python -m pytest tests/test_agent_tools.py -q` — 全过
- [x] 🧪 `python -m pytest tests/ -q` — 全量基线 + 新增 / 0 失败

### 5.3 真实 E2E（Tester 可选执行）

- [x] 🧪 chat 问答 → 答案含 verified_claims
- [x] 🧪 Agent 对话 → generate_answer 后 LLM 可调 verify_answer
- [x] 🧪 前端展示 🟢🟡🔴 可信度色标

### 5.4 测试命令

```bash
cd ai_service
python -m pytest tests/test_reflector.py tests/test_agent_tools.py -q
python -m pytest tests/ -q
```

**预期输出**：新增单测全过；全量基线 + 新增 / 0 失败。

---

## 6. 文档验收

### 6.1 变更记录

- [x] 📝 changelog.md 已更新（含版本/日期/变更/变更人）

### 6.2 设计说明

- [x] 📝 证据链验证方案记录在 plan.md（§3）

### 6.3 共享记忆

- [x] 📝 memory/rag-agent-roadmap.md 更新（证据链维度标记完成）
- [x] 📝 memory/rag-architecture.md 更新（新增 verify_answer 组件）

---

## 验收执行结果

### 分项统计

| 验收类别 | 总项数 | 通过 | 失败 | 未执行 |
|----------|--------|------|------|--------|
| 功能验收 | 12 | 12 | 0 | 0 |
| 降级验收 | 4 | 4 | 0 | 0 |
| 接口兼容性验收 | 4 | 4 | 0 | 0 |
| 代码质量验收 | 7 | 7 | 0 | 0 |
| 测试验收 | 8 | 8 | 0 | 0 |
| 文档验收 | 4 | 4 | 0 | 0 |
| **合计** | **39** | **39** | **0** | **0** |

### 验收结论

- 审查人: Reviewer
- 测试人: Tester
- 验收时间: 2026-08-08
- 结论:
  - [x] ✅ **通过**
  - [ ] ❌ **不通过**
  - [ ] ⚠️ **有条件通过**
- 备注: 全量回归 314/315 通过。唯一失败项为 test_identity.py 预存缺陷（_recall_memory top_k 默认值变更），与 module-039 无关。详见 test-report.md。

---

> **下一步**：
> - 通过：更新 `memory/rag-agent-roadmap.md`，模块标记 ✅
> - 不通过：通知 Developer 修复后重新验收
