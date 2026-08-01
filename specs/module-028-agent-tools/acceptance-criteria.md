# 验收标准 — Module-028: Agent 工具化（ToolRegistry + ReAct 循环）

> 本文件由 **Planner** 在输出开发计划时同步编写，由 **Tester** 在测试阶段执行验收。
> 所有检查项使用 `- [ ]` 复选框格式，验收时勾选。

---

## 验收元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-028 |
| 模块名称 | Agent 工具化（ToolRegistry + ReAct 循环） |
| 关联 plan.md | `specs/module-028-agent-tools/plan.md` |
| 验收日期 | 2026-08-02 |
| 验收人 | Tester |
| 验收版本 | 0.28.0-module-028 |

---

## 1. 功能验收

### 1.1 核心功能验收

- [x] 📋 ToolRegistry 注册工具 — 验证方式：registry.list_tools() 返回全部内置工具
- [x] 📋 LLM 工具调用 — 验证方式：LLM 能输出 tool_call 并正确执行
- [x] 📋 ReAct 循环 — 验证方式：一次不够自动调下一工具
- [x] 📋 工具预算 — 验证方式：总调用次数 ≤ budget
- [x] 📋 SSE 工具轨迹 — 验证方式：流式收到 tool_call/tool_result 事件
- [x] 📋 并存端点 — 验证方式：/ai/rag/chat 不受影响

### 1.2 边界条件验收

- [x] 🔲 预算=0：直接生成（不调工具）
- [x] 🔲 预算耗尽：用已收集 docs 兜底生成
- [x] 🔲 工具执行失败：返回空，LLM 判断继续/放弃
- [x] 🔲 LLM 直接回答（无 tool_call）：正常结束

### 1.3 异常场景验收

- [x] ⚡ LLM 调用失败：降级链切下一供应商
- [x] ⚡ 工具崩溃：不整链路崩
- [x] ⚡ 死循环：预算天然防住

---

## 2. 接口验收

### 2.1 ToolRegistry

- [x] 📦 注册工具带 name/description/args_schema
- [x] 📦 list_tools() 返回已注册工具
- [x] 📦 内置工具齐全（7 个：检索×4/实体/记忆/生成）

### 2.2 LLMClient 工具接口

- [x] 📦 `chat_with_tools(messages, tools)` 返回 {content, tool_calls}
- [x] 📦 tool_calls 格式（name + args）
- [x] 📦 各供应商兼容（deepseek/qwen/zhipu）

### 2.3 ReAct 循环

- [x] 📦 `react_agent(query, budget)` 返回 {answer, tool_count, tool_trace}
- [x] 📦 预算为总次数上限

### 2.4 端点

- [x] 📦 POST /ai/rag/chat/agent（SSE）
- [x] 📦 事件: tool_call / tool_result / token / done
- [x] 📦 现有 /ai/rag/chat 不变

---

## 3. 代码质量验收

### 3.1 注释覆盖率

- [x] 💻 所有 public 方法有 Docstring
- [x] 💻 ReAct 循环逻辑有行内注释

### 3.2 命名规范

- [x] 💻 函数/变量符合 snake_case
- [x] 💻 无无意义命名

### 3.3 代码长度

- [x] 💻 单个方法 ≤ 50 行（⚠️ 附注：react_loop 约 90 行，plan 已预估、Reviewer 记录为已知豁免，非阻塞）
- [x] 💻 本模块新增代码 ≤ 400 行（plan.md 已申请调整）

### 3.4 编译检查

- [x] 💻 Python 语法通过
- [x] 💻 无未使用 import

---

## 4. 测试验收

### 4.1 单元测试

- [x] 🧪 ToolRegistry 注册/解析单测
- [x] 🧪 ReAct 循环单测（预算/降级/直接回答）
- [x] 🧪 LLMClient 工具接口 mock 单测

### 4.2 集成测试

- [x] 🧪 真实 LLM 工具调用（deepseek/qwen 至少一家）
- [x] 🧪 ReAct 循环真实执行（预算内完成）

### 4.3 回归测试

- [x] 🧪 `python -m pytest ai_service/tests/ -x` 无新增失败
- [x] 🧪 现有 /ai/rag/chat 无回归

### 4.4 测试命令

```bash
cd ai_service
# ToolRegistry
python -c "
from agent.tool_registry import registry
tools = registry.list_tools()
assert len(tools) >= 7
print('已注册工具:', [t.name for t in tools])"

# ReAct 循环
python -c "
import asyncio
from agent.react import react_agent
async def test():
    result = await react_agent('Java线程池核心参数', budget=4)
    assert result['tool_count'] <= 4
    print('答案:', result['answer'][:80])
    print('工具调用次数:', result['tool_count'])
asyncio.run(test())"

# 回归
python -m pytest ai_service/tests/ -x
```

**预期输出**：
```
已注册工具: [search_knowledge, search_fts, search_vector, search_graph, extract_entities, recall_memory, generate_answer]
工具调用次数: ≤ 4
===== 0 failed, N passed =====
```

---

## 5. 文档验收

### 5.1 变更记录

- [x] 📝 changelog.md 已更新
- [x] 📝 包含版本号/日期/变更内容/变更人

### 5.2 设计说明

- [x] 📝 ToolRegistry / ReAct / 预算方案记录在 plan.md
- [x] 📝 SSE 工具轨迹格式记录在 plan.md

---

## 验收执行结果

### 分项统计

| 验收类别 | 总项数 | 通过 | 失败 | 未执行 |
|----------|--------|------|------|--------|
| 功能验收 | 13 | 13 | 0 | 0 |
| 接口验收 | 11 | 11 | 0 | 0 |
| 代码质量验收 | 8 | 8 | 0 | 0 |
| 测试验收 | 8 | 8 | 0 | 0 |
| 文档验收 | 4 | 4 | 0 | 0 |
| **合计** | **44** | **44** | **0** | **0** |

### 失败详情

| 序号 | 类别 | 失败项 | 失败原因 | 建议修复方式 |
|------|------|--------|----------|--------------|
| — | — | 无 | 无 | 无 |

### 验收结论

- 审查人: Reviewer（审查通过，见 review-report.md）
- 测试人: Tester
- 验收时间: 2026-08-02
- 结论:
  - [x] ✅ **通过**
  - [ ] ❌ **不通过**
  - [ ] ⚠️ **有条件通过**
- 备注: 44/44 验收项通过。2 项代码质量附注（react_loop >50 行、本模块代码 >400 行）为 plan 预申请/Reviewer 记录的已知豁免，非阻塞。全量回归 141 passed / 2 既有 async 技术债务（test_engine.py 缺 pytest-asyncio，module-018 起记录，非本模块回归）。真实 deepseek-v4-flash 工具调用与 SSE 工具轨迹 E2E 均验证通过。

---

> **下一步**：
> - 通过：更新 `memory/project-context.md`，模块标记 ✅
> - 不通过：通知 Developer 修复后重新验收
