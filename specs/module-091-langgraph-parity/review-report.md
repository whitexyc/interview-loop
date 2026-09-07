# Review Report — Module-091: LangGraph 复刻实验 → 转正对比报告

> Reviewer: 2026-09-07 | 独立全文件审查（非 diff 视角）| 被审：`ai_service/eval/langgraph_parity.py`（393 行）、`ai_service/tests/eval/test_langgraph_parity.py`（158 行）、parity-report / ADR-0020 / changelog
> 依据：`plan.md` + `acceptance-criteria.md`（AC-1~22）| 复核环境：HEAD `45f7cb9`，`.venv/Scripts/python.exe`

## 0. 最终判定：**PASS**（阻塞项 0，LOW 备忘 2）

---

## 1. 八项核查逐项结论

### 1.1 【最高优先】fixture 客户端的实例隔离 — **PASS**

**勘误裁定：plan 事实 7 勘误成立，且不动摇 AC-2 等价性结论的有效性。**

- **同对象事实确认**：`agent/react.py:39` 与 `agent/langgraph_react.py:35` 均为 `from llm.client import LLMFactory`，两模块的 `LLMFactory` 名字解析到同一个 `llm.client.LLMFactory` 类对象。Developer 勘误（parity-report §2:38、changelog §五.3:89）属实。
- **实例隔离确认（核心）**：
  - `run_round` 在每次调用时**新建** `_FixtureClient`：`eval/langgraph_parity.py:109`（`client = at._FixtureClient(_fixture_plan(item), _fixture_answer(item, is_last))`），`_fixture_plan`（:65-74）每次生成新 list；
  - `_FixtureClient` 内部状态独占：`eval/agent_tasks.py:511` `self._plan = list(plan)`（拷贝构造），`:516` `pop(0)` 消费——计划队列不会跨实例串扰；
  - `run_equivalence` 串行两次调用 `run_side`（`langgraph_parity.py:206-207`），hand 与 langgraph 各自走一遍 `run_round` → 各自持有独立 client 实例。**不存在共享实例被消费两次的情形**。
- **patch 机制正确性**：`mock.patch(_LLM_PATCH[loop], return_value=client)`（:110）仅在 `run_round` 上下文内存活；因两侧解析到同一类对象，patch 任一字符串都替换同一类属性——但两侧**串行执行、各自新建 client**，patch 范围互不重叠，功能上无混用风险。
- **AC-6 单测断言的是什么**：`tests/eval/test_langgraph_parity.py:27-38` 三个用例断言 patch 目标**字符串**（字面满足 AC-6"单测断言 patch 目标字符串"）；`:47-55` `test_patch_actually_swaps_llm` 是**行为级**探针——patch 后经 importlib 取回类对象、实际调用 `get_client()` 断言返回假客户端；`:61-67` `test_full_dataset_equivalent` 端到端跑 36 条 × 两侧真环路，若 patch 未生效会打真实 LLM 而失败。字符串断言 + 行为探针 + 端到端零 LLM 三层组合，足以锁定"两侧都用了假 LLM"。
- **结论**：等价性证明不依赖"双 mock 点对象不同源"这一（已被勘误的）前提，只依赖 ① 两侧各自新建 fixture client ② patch 上下文内环路确实拿到假 LLM——两者均成立。**AC-2 等价率 1.0000 的结论有效。**

### 1.2 交替执行真实性（AC-7/T4）— **PASS**

- `run_real`（`eval/langgraph_parity.py:253-256`）：外层 `for item` × 内层 `for loop in (LOOP_HAND, LOOP_LANGGRAPH)` → **逐任务 hand→langgraph 交替**，非先整段跑完一条。
- 固定种子：`:358` `random.Random(42).sample(tasks, ...)`——每次运行新建 Random 实例、显式种子，抽样确定可复现；`:359` 按 id 排序稳定输出顺序。
- 运行日志时间戳证据归 Tester T4（changelog §六:99 已注明日志已删、给出重跑与 per_question 顺序核对两条路径）。

### 1.3 结论诚实性（AC-19/20/22）— **PASS**

- 三判据逐条实测值齐全：parity-report §1:14-16（① 100.0% 36/36；② 0.5833 ≥ 0.3667 反高 +0.1667；③ tokens ×0.964 ✅ / P95 ×1.224 ❌ 超阈 2.4%）。
- 结论二选一明确、无模糊：§1:8 "**维持自研**"，ADR-0020:37 同。
- 不利事实未被弱化：§1:20 专段"对自研不利事实（AC-22）"——pass^1 +16.7pp、工具正确率 +16.7pp、Grounding +6.1pp、tokens −3.6%，且明确写"不是 LangGraph 更差的证明"（:20 末句）；ADR-0020:42 同样照录并注明"维持自研的依据仅是延迟阈值超标"。
- 统计效力局限与重启条件：§5:96"单次采样，非置信区间"；§4:92 与 ADR-0020:42、:54 给出重启条件（多次采样复测延迟 / 归因实验）。**无回避、无找补。**

### 1.4 AST 复算 — **PASS**

- 独立 `ast.walk` 复算 `eval/langgraph_parity.py`：**193 stmt**，与自报一致，≤200（AC-14）。
- 方法规模：最长 `main` 39 语句 ≤50（AC-15）；13 个函数全部有 Docstring（AC-16）；无空 except——仅 `:146`（fail_reason 记录，AC-12 语义）与 `:370`（grounding 降级，带注释 :367）两处，均有处理逻辑（AC-17）。

### 1.5 红线复核 — **PASS**

- `git diff --stat -- ai_service/agent ai_service/src ai_service/main.py` 输出为空（实测）；HEAD `45f7cb959d…` 与 changelog 申报一致。
- `git status --porcelain` 新增文件均为 eval/tests/specs/memory 范畴，无 tracked 生产文件修改。

### 1.6 偏离裁定（changelog §五 6 项）— **5 项成立，1 项 LOW 偏差**

| # | 偏离 | 裁定 |
|---|------|------|
| 1 | deepseek 401 → `PW_LLM_PROVIDER=qwen` | **成立**。实测 `.env:8` 仍为 `PW_LLM_PROVIDER=deepseek`——`.env` **零改动**（且 git-ignored）；切换走运行前 shell 环境变量（parity-report §6:112 命令前缀），正是要求的正确做法 |
| 2 | fixture 强制全量 | 成立（AC-1 字面要求，`:351-353` 实现一致） |
| 3 | mock 点同对象勘误 | 成立（见 §1.1） |
| 4 | 新增 `build_config_snapshot` | 成立（AC-9 可单测性需要，+5 AST 在上限内） |
| 5 | AST 193 vs 预估 ~95 | 成立（构成解释合理：12 个 Docstring + 2 个打印函数 + CLI；仍 ≤200） |
| 6 | 临时文件 | **LOW 偏差**：changelog 称"内容已全部清空（0 字节）"，实测 8 个 `_*.txt` 中 `_final_state.txt`（206B）与 `_verify2.txt`（264B）**仍有内容**（为清理追踪日志，已查无 key/token/secret 泄漏）；物理删除留待下轮已如实申报。不阻塞 |
| - | 相对结论有效性 | **成立**：两侧同模型（Qwen3.5-35B-A3B）同任务集同种子，相对比较不受供应商替换影响；绝对值不可外推已在报告 §5.2 声明 |

### 1.7 落库字段 — **PASS**（代码层面）

- `build_config_snapshot`（`eval/langgraph_parity.py:290-302`）注入 `{"loop": loop, "module": "091"}`，两侧各调一次（:383-386）；
- `save_agent_eval_run`（`eval/agent_tasks.py:550-556`）INSERT 含 `config_snapshot` JSONB 列，`git_commit` 直传入参。
- 落库行（id=4/5）真实性归 Tester T1 对账，本报告不重复验证。

### 1.8 单测质量 — **PASS**

- 复跑 `pytest tests/eval/test_langgraph_parity.py -q` → **15 passed**（32.97s，实测）。
- 断言行为而非凑数：`test_full_dataset_equivalent`（:61-67）端到端跑真环路 36 条；`test_patch_actually_swaps_llm`（:47-55）patch 生效行为探针；`test_detects_each_dimension`（:98-113）七维不一致逐一检出；`TestSaveFields`（:137-157）断言字段值而非 mock 调用次数。全文件无"mock 次数凑数"式用例。

---

## 2. 阻塞项与备忘分级

**阻塞项：0。**

| 级别 | 项 | 说明 |
|------|----|------|
| LOW | 临时文件 2 个非空（`_final_state.txt` 206B、`_verify2.txt` 264B） | 与 changelog"全部 0 字节"申报不符；内容为清理追踪日志、无泄漏。修复归清理轮：`rm -f ai_service/_final_state.txt ai_service/_verify2.txt ai_service/_probe_out.txt ai_service/_prog.txt ai_service/_rmlog.txt ai_service/_rmlog2.txt ai_service/_shellcheck.txt ai_service/_v3.txt` |
| 备忘 | AC-6 字符串断言在同对象现实下偏弱 | 已被 `test_patch_actually_swaps_llm` 行为探针 + 端到端 fixture 用例补偿；changelog 勘误理由（防未来改本地工厂）成立，无需整改 |
| 备忘 | `_LoopFn`/事件消费依赖 `done` 事件 answer 截断 200 字（`agent_tasks.py:443`） | 四维比对两侧同口径，等价性结论不受影响；仅提示 answer 字段为截断值 |

## 3. 验收结论签署

| 角色 | 结论 | 日期 | 备注 |
|------|------|------|------|
| Developer | ⬜ | | changelog.md |
| **Reviewer** | **PASS**（8/8 项核查通过，0 阻塞） | 2026-09-07 | 本报告 |
| Tester | ⬜ | | 待 T1–T6 真实对账 |
