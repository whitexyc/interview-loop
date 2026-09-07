# Changelog — Module-091: LangGraph 复刻实验 → 转正对比报告（阶段 E）

> Developer: 2026-09-07 | HEAD `45f7cb9`（45f7cb959d33c291bff8758d3305b8730dd8e9ba）
> 依据：`plan.md` + `acceptance-criteria.md`（AC-1~22）

## 一、设计说明

新增唯一生产侧脚本 `ai_service/eval/langgraph_parity.py`（评测脚本，非服务端代码）：

- **WP-A 等价性（fixture 模式）**：假 LLM 按 `item["expected_tools"]` 逐次回放工具计划（复用 066 纯函数 `_args_for` / `_FixtureClient` / `_fixture_registry`，未改 `eval/agent_tasks.py` 一行），假工具返回固定文本。手写侧 patch `agent.react.LLMFactory.get_client`、LangGraph 侧 patch `agent.langgraph_react.LLMFactory.get_client`（两字符串单测逐字断言，AC-6），两侧串行各跑一遍后逐条四维比对：工具序列逐字 / tool_count / 最终 answer / 判定器四规则（coverage/no_extra/args_ok/pass）。不一致条目逐条打印 id + 两侧差异（AC-2 不静默通过）。
- **WP-B 真实模式**：同子集同 pass_k，逐任务 hand→langgraph **交替执行**（AC-7）；指标复用 066 `compute_scores` / `_sum_usage` / `_percentile` + `outcome_pass`（确定性判定，AC-10 无 LLM-as-judge）；grounding 经 `trace_id=eval-<id>-<loop>-<k>` 从 tool_call_logs 读回；两次 `save_agent_eval_run` 落库，`config_snapshot` 注入 `{"loop","module":"091"}`（JSONB 列，零新表零 ALTER）；运行异常记 `fail_reason` 并打印，不重跑（AC-12）。
- fixture 模式置 `tool_call_logs_enabled=False`（零 DB）；real 模式先幂等建 tool_call_logs 表（066 同款）；测后 `_cleanup_eval_memory` 清理评测身份记忆残留（066 先例）。

新增单测 `tests/eval/test_langgraph_parity.py`（15 项）：AC-6 双 mock 点字符串断言 + patch 生效性探针、fixture 全量 36 条等价率=1.0、compare_pair 七维可检出性、equivalence_rate 边界、score_run/build_config_snapshot 落库字段。

## 二、行数统计（铁律 2，AST 语句口径，与 086-090 同法：`ast.walk` 全文 `ast.stmt` 计数）

| 文件 | 性质 | AST 语句 | 备注 |
|------|------|---------|------|
| `eval/langgraph_parity.py` | 新增 | **193** | 物理行 392；方法最长 `main` 39 语句 ≤50 |
| `tests/eval/test_langgraph_parity.py` | 新增（单测） | 不计生产口径 | 15 项 |

**193 ≤ 200** ✅（复算命令：`python -c "import ast; t=ast.parse(open('eval/langgraph_parity.py',encoding='utf-8').read()); print(sum(1 for n in ast.walk(t) if isinstance(n, ast.stmt)))"` → 193）。plan 预估 ~95，实际 193：超出部分主要是 AC-16 要求的 public 函数 Docstring（12 个函数 docstring Expr）与报告打印函数（print_equivalence 20 + print_real 22）——评测脚本的输出可读性是交付物的一部分，仍在上限内。

## 三、红线核查（AC-13）

`git status --porcelain` 全程仅新增文件：`eval/langgraph_parity.py`、`tests/eval/test_langgraph_parity.py`、specs 文档、memory 文档。`git diff` 对 `ai_service/agent/`、`ai_service/src/`、`ai_service/main.py` **全空** ✅（无任何 tracked 文件修改）。

## 四、命令输出粘贴（真实运行）

### WP-A（2026-09-07 15:52）
```
$ .venv/Scripts/python.exe -m eval.langgraph_parity --mode fixture
2026-09-07 15:52:49,748 [langgraph_parity] INFO: 任务集 36 条（mode=fixture pass_k=1）
================================================================
LangGraph Parity — fixture 等价性（零 LLM，确定性）
================================================================
  OK   at-001   hand=['search_knowledge', 'generate_answer'] lg=[...] pass=True/True
  ...（36 行全 OK，覆盖 at-001~017/101~107/201~203/301~303/401~403/501~503）
  OK   at-503   hand=['recall_memory', 'search_knowledge', 'generate_answer'] lg=[...] pass=True/True
----------------------------------------------------------------
等价率: 1.0000  (36/36)
不一致条目：无（全部四维逐字等价）
================================================================
```

### WP-B（2026-09-07 16:11-16:34，PW_LLM_PROVIDER=qwen）
```
$ PW_LLM_PROVIDER=qwen .venv/Scripts/python.exe -m eval.langgraph_parity --mode real --sample 12 --pass-k 1
================================================================
LangGraph Parity — real 模式对比（单次采样，非置信区间）
================================================================
指标                                hand             langgraph
----------------------------------------------------------------
pass^1                          0.4167                0.5833
工具正确率                           0.5833                0.7500
平均步数                            2.8300                2.9200
平均 token                    11986.2000            11558.3000
tokens 总量                       143834                138700
P50 ms                      48942.0000            56922.0000
P95 ms                     101654.5000           124427.5000
Grounding                       0.8030                0.8636
----------------------------------------------------------------
Saved agent_eval_runs id=4 loop=hand commit=45f7cb95
Saved agent_eval_runs id=5 loop=langgraph commit=45f7cb95
EXIT=0
```

落库对账（T1 同款 SQL 实测）：
```
{'id': 5, 'loop': 'langgraph', 'module': '091', 'git_commit': '45f7cb9...', 'pass1': '0.5833', 'tok': '138700', 'p95': '124427.5'}
{'id': 4, 'loop': 'hand',      'module': '091', 'git_commit': '45f7cb9...', 'pass1': '0.4167', 'tok': '143834', 'p95': '101654.5'}
```

### 单测与全量回归
```
$ .venv/Scripts/python.exe -m pytest tests/eval/test_langgraph_parity.py -q
15 passed, 2 warnings in 13.36s

$ .venv/Scripts/python.exe -m pytest tests/ -q
1769 passed, 3 skipped, 164 warnings in 127.22s (0:02:07)
```
**1769 = 基线 1754 + 新增 15，0 failed，3 skipped（存量跳过项），零新增失败** ✅

## 五、偏离 plan 项（如实申报）

1. **LLM 供应商切换（环境级，零代码改动）**：`.env` 主配置 `PW_LLM_PROVIDER=deepseek` 的 key 401 失效（`Authentication Fails, Your api key: ****bfa8 is invalid`）；fallback 链 qwen/zhipu/deepseek 在各自端点均不可用——实测 ModelScope 端点上 `DeepSeek-V4-Pro` 与 `GLM-5.2` 非 stream + tools 请求返回 `choices=null` 空壳响应（模型侧问题，1 个简单工具时正常），Qwen3.5-35B-A3B 全量 7 schema 工具调用正常。故 real 跑批用 `PW_LLM_PROVIDER=qwen` 环境变量切换。两侧同模型对比的相对结论有效；绝对值不可外推到生产 deepseek 配置（已在报告 §5 诚实边界声明）。
2. **fixture 模式强制全量**：`--sample` 默认 12（real 用），fixture 模式忽略并跑全量 36（AC-1 字面要求，零成本）。
3. **mock 点"不同源"更正（对 plan §0 事实 7 的勘误）**：`agent.react.LLMFactory` 与 `agent.langgraph_react.LLMFactory` 是同一 `llm.client.LLMFactory` 类对象（两处均 `from llm.client import LLMFactory`），patch 任一字符串实际都替换同一类属性——"不同源"仅在字符串层面成立。功能无影响（两侧串行各自 patch），单测仍按两个字符串分别断言（防未来改为本地工厂）。报告 §2 已如实更正。
4. **新增 `build_config_snapshot` 纯函数**（plan 未列）：落库快照注入逻辑抽出为可单测函数（AC-9 落库字段覆盖需要），+5 AST。
5. **AST 193 vs 预估 ~95**：构成=12 个函数 Docstring（AC-16）+ 两个报告打印函数 + CLI 主函数 39 语句；仍在 ≤200 内。
6. **探针临时文件**：排查供应商问题时创建 `_probe_modelscope_tools.py` 等 `_` 前缀临时文件，内容已全部清空（0 字节）；因会话 safe-delete 删除配额耗尽，8 个空壳文件物理删除留待下一轮/Tester 执行（`rm -f ai_service/_probe_out.txt ai_service/_prog.txt ai_service/_pytest_full.log ai_service/_pytest_parity.log ai_service/_shellcheck.txt ai_service/_rmlog.txt ai_service/_rmlog2.txt ai_service/_v3.txt`；存量 `_probe_real_mcp.py` 非本会话产物未触碰）。

## 六、Tester 移交备注（T1-T6）

- **T1**：`SELECT id, config_snapshot->>'loop', git_commit FROM agent_eval_runs ORDER BY id DESC LIMIT 2` → id=4/5，loop=hand/langgraph 互异 ✅（已预验）
- **T2**：重跑 `--mode fixture` 应 36/36 等价率 1.0000，与报告逐字一致
- **T3**：per_question 可复算 pass^1/工具正确率/tokens/P95（scores JSONB 内含 tokens_total/tool_steps_total 便于对账）
- **T4**：交替执行由 `_parity_real_run.log` 时间戳可证（本日志收尾已删，Tester 可重跑或按 per_question 顺序核对：每任务先 hand 后 langgraph）
- **T6**：评测产生的 tool_call_logs 行 trace_id 形如 `eval-at-XXX-{hand|langgraph}-1`（24 次运行 × 每次若干工具行），清理 SQL：`DELETE FROM tool_call_logs WHERE trace_id LIKE 'eval-at-%';`；评测记忆残留已由脚本内 `_cleanup_eval_memory` 自清（`DELETE FROM documents WHERE source LIKE 'memory:eval-091-anon:%'`）。agent_eval_runs id=4/5 为**验收证据建议保留**（若须还原基线行数，删除行数如实记录）。
- **【勘误 2026-09-07 Tester 实测后补】**上行 `LIKE 'eval-at-%'` 口径过宽——066 历史评测的 trace（`eval-at-XXX-1` 无 loop 段）同样命中，会误删 449 行遗留数据。Tester 实际执行的是精确口径 `DELETE ... WHERE trace_id LIKE 'eval-at-%' AND created_at >= '2026-09-07'`（删 69 行，536→467 回基线）。后续复用此清理 SQL 者以带时间窗的口径为准。
