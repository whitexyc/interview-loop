# 验收标准 — Module-066: Agent 级评估体系

> 本文件由 **Planner** 在输出开发计划时同步编写，由 **Tester** 在测试阶段执行验收。
> 依据：task-brief（WP-A~D 通过标准）+ ADR-0017 验收标准 + plan.md。
> 所有检查项使用 `- [ ]` 复选框格式，验收时勾选。

## 验收元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-066 |
| 模块名称 | Agent 级评估体系 |
| 关联 plan.md | `specs/module-066-agent-evaluation/plan.md` |
| 验收日期 | YYYY-MM-DD |
| 验收人 | <Tester 姓名> |
| 验收版本 | <版本号> |

---

## 1. 功能验收

### 1.1 WP-A：tool_call_logs 表 + 落库

- [ ] 📋 建表：`tool_call_logs` 表按 ADR-0017 决策 2 结构建表（id/trace_id/tool_name/args/result_ok/result_preview/duration_ms/created_at），`init_db` 幂等（二次启动不报错）— 验证方式：启动服务 + `\d tool_call_logs` / 重复调用 ensure 函数
- [ ] 📋 落库：真实 agent 端点一次对话后，`tool_call_logs` 能查到记录 — 验证方式：agent chat 后 SELECT，每行含 tool_name / args / result_ok / duration_ms / trace_id
- [ ] 📋 只记实际执行：预算截断掉的 LLM 提议不落库（截断行数 = 无对应结果）— 验证方式：构造 budget 截断场景对比落库行数与实际执行数一致
- [ ] 📋 langgraph 端点（agent-lg）同构落库 — 验证方式：agent-lg 对话后同样可查到记录
- [ ] 📋 开关：`PW_TOOL_CALL_LOGS=false`（或等价配置）时零落库零开销 — 验证方式：开关关后对话 0 新行 + 单测断言跳过
- [ ] 📋 result_preview 截断 200 字符（大结果不撑爆列）— 验证方式：工具返回超长结果时预览长度 ≤ 200
- [ ] 📋 开关默认 true（与 request_logs 同生命周期）— 验证方式：无环境变量时默认开启

### 1.2 WP-B：任务级评测集

- [ ] 📋 `eval/agent_tasks.json` 存在且 30-50 条 — 验证方式：加载统计条数
- [ ] 📋 条目结构合法：id 唯一、task（字符串或数组）、expected_tools、answer_points（1-3 个）— 验证方式：schema 校验脚本
- [ ] 📋 expected_tools 全部 ∈ ToolRegistry 10 工具（或空数组）— 验证方式：校验脚本 + 单测
- [ ] 📋 覆盖 ≥6 类路径：knowledge 单轮 / knowledge 多轮 / casual / realtime / 重检 / 记忆 — 验证方式：分类计数输出
- [ ] 📋 多轮任务（task 为数组）存在且构造合理（省略句继承语义，module-063 能力）— 验证方式：抽查条目
- [ ] 📋 手工构造任务已真实检索冒烟验证知识库覆盖（或如实标注无覆盖并移出达标口径）— 验证方式：changelog 记录

### 1.3 WP-C：评测脚本 + agent_eval_runs 落库

- [ ] 📋 `python -m eval.agent_tasks --mode agent`（默认参数）跑通并输出全部三层指标：pass^1 / 工具正确率 / 平均步数 / 平均 token / P50-P95 — 验证方式：运行脚本检查输出
- [ ] 📋 判定器确定性：覆盖（顺序放宽）+ 无多调（re_search 豁免）+ 参数类型（不判值）+ answer_points 关键词包含 — 验证方式：单测逐规则断言
- [ ] 📋 pass^3：`--sample 10 --pass_k 3` 抽样 10 条各跑 3 次、全成功才算对 — 验证方式：运行 + 结果口径核对
- [ ] 📋 `--mode chat` 输出 Outcome + System（Trajectory 如实标注"无轨迹"不伪造）— 验证方式：运行核对
- [ ] 📋 `--fixture` 模式零 LLM/DB 可跑（启发式冒烟）— 验证方式：运行 --fixture
- [ ] 📋 结果落 `agent_eval_runs` 表：git_commit + 配置快照 + per_question 逐任务明细 JSONB — 验证方式：SELECT 检查字段
- [ ] 📋 首次跑通过标准：pass^1 ≥ 0.8（agent 多轮路径 ≥ 0.7）/ 工具正确率 ≥ 0.9 / 平均步数 ≤ 6 / Grounding = 1.0 — 验证方式：运行结果对比
- [ ] 📋 不达标 → 输出失败案例分类报告（工具选错/参数错/路径绕/答案缺要点），不隐藏不改标准 — 验证方式：不达标时检查报告存在且分类完整

### 1.4 WP-D：回归 + 文档收口

- [ ] 📋 存量测试零改动（request_logs / 工具注册表 / react.py 循环逻辑 / langgraph 循环逻辑零改动）— 验证方式：git diff 核对
- [ ] 📋 全量 pytest = 1037 基线 + 新增全绿 — 验证方式：全量运行
- [ ] 📋 changelog.md 已产出（含通过标准达成情况 + 诚实边界 + 失败案例分类如有）
- [ ] 📋 CONTEXT.md 补 ADR-0017 行 + module-066 索引行（只增不删、取更全侧、先备份）— 验证方式：diff 检查无删行
- [ ] 📋 ADR-0017 状态标 ✅ 已实施
- [ ] 📋 memory 三文件更新（project-context module-066 行 + file-index 新文件 + activity-log）

## 2. 边界条件验收

- [ ] 🔲 工具 args 为非法 JSON 字符串（供应商防御路径）时不崩且正常落库（args 兜底 {}）— 验证方式：单测
- [ ] 🔲 工具不存在（tools.get 返回 None）时 result_ok=false 落库、循环继续 — 验证方式：单测
- [ ] 🔲 空 expected_tools 任务（casual/realtime）判定恒过（不要求工具、answer_points 按实际判定）— 验证方式：单测
- [ ] 🔲 任务答案不含任何 answer_points 时 outcome=fail（判定器不过度宽松）— 验证方式：单测
- [ ] 🔲 参数类型校验：args 缺必填字段 → 该任务参数正确率不通过 — 验证方式：单测
- [ ] 🔲 result_preview 超长、含特殊字符（换行/引号）落库无异常 — 验证方式：单测

## 3. 异常场景验收

- [ ] ⚡ tool_call_logs 落库失败（DB 断连）不阻断工具执行循环（fail-open）— 验证方式：mock 落库抛错单测
- [ ] ⚡ LLM 全失败/降级链兜底：Grounding 判定不算错（降级链兜底豁免）— 验证方式：单测 + 真实运行标注
- [ ] ⚡ 评测中途 LLM 429/超时：如实记录为该任务 fail 或跳过（不伪造成功），可重跑 — 验证方式：运行 + 报告标注
- [ ] ⚡ `--no-save` 不落库（dry-run）— 验证方式：运行后 agent_eval_runs 0 新行
- [ ] ⚡ 评测数据清理：memory 路径评测用固定匿名身份，测后清理不污染真实记忆 — 验证方式：残留校验

## 4. 代码质量验收

- [ ] 💻 本模块新增功能代码 ≤ 270 行预算（WP-C eval 脚本豁免 ≤200 单文件上限已声明；WP-A ~100 行 / WP-B 数据文件 0 / WP-C ~270 行）
- [ ] 💻 单个方法 ≤ 50 行（默认，特殊情况见 plan.md）
- [ ] 💻 命名符合既有模式（tool_call_logs 对齐 request_logs、agent_eval_runs 对齐 eval_runs）
- [ ] 💻 无 import 未使用、py_compile 通过
- [ ] 💻 无跨层调用、无反向依赖（新增代码仅 Python 侧，无新分层）

## 5. 测试验收

### 5.1 单元测试

- [ ] 🧪 `tests/test_tool_call_logs.py`：成功/失败落库、开关 false 跳过、preview 截断、args 非法 JSON 防御、fail-open、截断不落库
- [ ] 🧪 `tests/test_agent_tasks.py`：任务集 schema 校验（条数/id 唯一/工具名合法）、判定器四规则逐条（覆盖/无多调/re_search 豁免/参数类型）、answer_points 关键词判定、指标计算（pass^k/步数/P50-P95）、CLI 参数（--mode/--sample/--pass_k/--limit/--no-save/--fixture）、agent_eval_runs 落库
- [ ] 🧪 单测全 mock 不依赖真实 LLM/DB（fixture 例外）

### 5.2 回归测试

- [ ] 🧪 全量 pytest 1037 基线 + 新增全绿、0 failed
- [ ] 🧪 存量测试零改动（除按验收许可的明确更新，如有须标注理由）

### 5.3 真实环境冒烟测试

- [ ] 🌐 真实 DB 建表 + 真实 agent 对话一次 → `SELECT * FROM tool_call_logs` 有记录（含 trace_id）
- [ ] 🌐 agent-lg 端点同构冒烟
- [ ] 🌐 `python -m eval.agent_tasks --limit 5 --no-save` 真实 LLM 跑通输出指标
- [ ] 🌐 冒烟命令与结果已记录到 test-report.md

## 6. 文档验收

- [ ] 📝 changelog.md 已更新，如实反映变更内容（含通过标准达成/未达成 + 失败案例分类如有 + 诚实边界）
- [ ] 📝 memory/project-context.md 模块状态已更新
- [ ] 📝 memory/file-index.md 已登记新文件（database.py 变更行 + eval/agent_tasks.json + eval/agent_tasks.py + 两测试文件）
- [ ] 📝 memory/agent-activity-log.md 已追加本阶段活动记录
- [ ] 📝 CONTEXT.md 只增不删（补 ADR-0017 行 + module-066 索引行，备份先行）
- [ ] 📝 ADR-0017 状态标 ✅ 已实施

---

## 验收执行结果

### 分项统计

| 验收类别 | 总项数 | 通过 | 失败 | 未执行 |
|----------|--------|------|------|--------|
| 功能验收 | | | | |
| 边界条件验收 | | | | |
| 异常场景验收 | | | | |
| 代码质量验收 | | | | |
| 测试验收 | | | | |
| 文档验收 | | | | |
| **合计** | | | | |

### 失败详情

| 序号 | 类别 | 失败项 | 失败原因 | 建议修复方式 |
|------|------|--------|----------|--------------|
| 1 | | | | |
| 2 | | | | |

### 验收结论

- 审查人: <Reviewer 签名>
- 测试人: <Tester 签名>
- 验收时间: YYYY-MM-DD
- 结论:
  - [ ] ✅ **通过** — 所有检查项通过，模块可以标记为完成
  - [ ] ❌ **不通过** — 存在失败项，需要 Developer 修复后重新验收
  - [ ] ⚠️ **有条件通过** — 存在非阻塞性问题，记录技术债务后放行
- 备注: <说明>

---

> **下一步**：
> - memory 三文件全部同步后方可标记模块完成
> - 不通过：通知 Developer 修复问题，修复完成后重新执行验收
> - 有条件通过：记录技术债务到 `memory/project-context.md`，正常进入下一模块
