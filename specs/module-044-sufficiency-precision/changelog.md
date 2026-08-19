# Module-044 变更记录 — Rerank 截断验证 + 反思充分性精确化

> 各 WP 完成后按时间追加；与 ADR-0004（截断验证）、ADR-0005（层 0-3）的一致性说明见各段。

## 2026-08-09 — WP1 ADR-0004 截断验证 + WP2 层 0 充分性评测闭环（Dev-A）

### WP1 ADR-0004 截断验证（决策：采纳 250）

- 新建 `ai_service/eval/benchmark_rerank.py`：可配截断参数 `--max-chars 250/500/1000/2000` + 2 pair / 6 pair 计时 + 每对 rerank 分数输出；预热 1 对排除模型加载/首次推理影响；文档用知识库代表性内容构造（借 golden 集真实主题 G1 GC / Kafka / AQS，每篇 3200+ 字符模拟"无标题整篇入库"的超长父块，见 ADR-0004 决策 2 背景）
- 实测数据（本地模型 `ai_service/models/bge-reranker-v2-m3`，同一环境、同一组文档，预热后计时）：

| 截断 | 2 pair 耗时 | 6 pair 耗时 | 相关文档分数 | 排序一致性 |
|---|---|---|---|---|
| 250 | 2.161s（1.08s/对） | 5.455s（0.91s/对） | 0.9907 / 0.9912 / 0.9988 | 6/6 与 500、1000 完全一致 |
| 500 | 4.128s（2.06s/对） | 9.900s（1.65s/对） | 0.9904 / 0.9930 / 0.9993 | — |
| 1000 | 7.269s（3.64s/对） | 19.618s（3.27s/对） | 0.9985 / 0.9955 / 0.9996 | 6/6 一致 |
| 2000 | 未跑（ADR-0004 历史：耗时线性涨、精度增益趋零） | | | |

- **决策（数据驱动，满足 plan 决策规则）**：250 相关文档分数全部 ≥ 0.98（0.9907~0.9988，与 500 差 ≤ 0.002，噪声级）且 6 pair 耗时 5.455s vs 9.900s 下降 44.9% → **采纳 250**
- `ai_service/rag/reranker.py`：`_MAX_PAIR_CHARS` 500 → 250（仅改常量 + 注释追加实测依据，行为结构不变）
- 诚实记录的两面性：弱相关文档的绝对分数随截断缩短而下降（如 g1/doc2 0.2195→0.0535，aqs/doc2 0.8672→0.7240），但**相对排序 6/6 不变**——重排只取 Top-5、排序只看相对大小（ADR-0004 决策 3 已接受的分数压缩特性），弱相关文档本就不该进 Top-5；若未来启用分数阈值过滤仍需先做概率校准（ADR-0004 展望，未变）

### WP2 层 0 充分性评测闭环（ADR-0005 层 0 落地）

- 新建 `ai_service/eval/golden_sufficiency.py`：
  - 内嵌 12 条充分性标注集（充分 6 + 不充分 6）：问题借 golden 集真实题目（G1/Kafka/AQS/volatile/Redis/synchronized/CAP 等），注入代表性文档（相关文档 / 不相关文档），不充分样本含"完全不沾边"（问 A 检索到 B）与"主题错位"（问 ZGC 给 G1 文档）两类——LLM 最容易漏判的场景；**每条 2 篇文档**——兼容层 1 数量闸门（文档数 < 2 → 直接判不充分零 LLM，Dev-B 已实现），确保真实模式测到 LLM 判断而非被数量闸门短路
  - 指标：Accuracy + 混淆矩阵（行=真实，列=预测）+ per-class P/R/F1/support；**报告单独大字标出 insufficient Recall（漏判"不充分" → 基于无关文档硬答，最致命）**，scores 含 `insufficient_recall` 字段
  - eval_runs 版本化落库：eval_type='sufficiency' + git_commit + rag_config 快照 + scores/per_question（复用 golden_retrieval.py 的 save_eval_run / get_git_commit / load_rag_config）
  - fixture 模式（`--fixture`）：启发式判断器（问题核心术语 keywords 命中文档 → 充分），确定性、不依赖 LLM/DB，用于无环境演示管线；真实模式默认走 `reflector.check_sufficiency`（失败降级由 reflector 内部兜底默认充分，不误杀）
  - 降级：单条判断失败 → 跳过记录不中断；落库失败警告不影响评估
  - 用法：`python -m eval.golden_sufficiency`（真实模式 + 落库）/ `--fixture` / `--no-save`
- 新建 `tests/test_golden_sufficiency.py`：12 用例（数据集结构校验、fixture 启发式判断器、run_eval 打桩端到端、漏判不充分时 insufficient_recall=0 如实反映、判断异常跳过、eval_runs 落库契约 eval_type='sufficiency'），异步 asyncio.run + stub，不依赖 DB/LLM
- fixture 模式冒烟：12/12 评估 0 跳过，Accuracy 1.0000，insufficient Recall 1.0000（管线验证通过，非真实指标）

### 与 ADR 一致性

- ADR-0004：TODO（测 250）已执行并出结论 → 采纳 250，四档选数表补齐，TODO 状态更新为已验证
- ADR-0005 层 0：充分性标注集 + Accuracy/P/R/F1（重点 insufficient Recall）+ eval_runs eval_type='sufficiency' 版本化回归 + fixture 模式，全部落地
- 层 4 小分类器：本模块明确不做（数据积累后另行模块，与 ADR-0003 L4 同理，plan 已注明）
- 红线核查：未触碰其他会话未提交文件（agent/react.py、agent/langgraph_react.py、main.py、eval/faithfulness.py 等）；reranker.py 仅改 _MAX_PAIR_CHARS 常量与其注释；未运行 git commit

### 测试结果

- `pytest tests/test_golden_sufficiency.py -q`：12 passed
- rerank 相关回归 `pytest tests/test_agent_tools.py tests/test_intent_validation.py tests/test_engine.py tests/test_memory_extractor.py tests/test_stream_memory.py -q`：143 passed（确认 _MAX_PAIR_CHARS=250 零回归）
- 预存环境问题（不计入本模块）：test_identity.py top_k 1 项 + test_rerank_langgraph.py 外部 429 限流 2 项

### 已知边界（诚实记录）

- benchmark 文档为**构造代表性子块**（非线上真实父块）：结构与知识库超长父块一致（标题+开头+正文），结论可外推，但绝对分数非生产值；建议生产上线后观察 6 pair 实际耗时变化
- 弱相关文档绝对分数随截断缩短下降（排序不受影响，见 WP1 记录）；未来分数阈值过滤需先校准（ADR-0004 决策 3 展望）
- 真实模式评测（reflector + LLM）需要 LLM 环境，本 WP 未跑真实模式 baseline（fixture 模式已验证管线）；真实 baseline 由后续 WP3-5 实施后补跑（Dev-B 已完成层 1-3 重构，见下段，重跑 `python -m eval.golden_sufficiency` 即得层 0-3 联动 baseline）

## 2026-08-09 — WP3 层 1 分数/数量硬闸门 + WP4 层 2 prompt 强化 + WP5 层 3 多信号融合（Dev-B）

### WP3 层 1 硬闸门（ADR-0005 层 1 落地，零 LLM）

`ai_service/agent/reflector.py::check_sufficiency` 重构：

- 空文档 → 不充分（现有行为保留）
- **数量闸门**：文档数 < 2 → 直接判不充分 + `rewritten_query=query`（零 LLM 调用）
- **分数闸门**：top-1 `abs_cosine` < 0.4 → 直接判不充分 + `rewritten_query=query`（零 LLM 调用）
- 阈值常量：`_SUFFICIENCY_MIN_DOCS=2` / `_SUFFICIENCY_MIN_ABS_COSINE=0.4`（参照 module-035 `memory_recall_min_score` 口径，ADR-0005 追问 2 的经验值起步）
- **abs_cosine 字段链核对结论**：module-043 在 `retriever.py:327-328` 归一化前存档 abs_cosine；`reranker.py` rerank 只加 `rerank_score` 不删字段；engine.py:248 精排后原样传入 → docs 带字段。仅 FTS 命中文档无该字段（retriever.py:325-326 注释），故用 `d.get("abs_cosine", None)`，缺失/异常值（TypeError/ValueError）跳过闸门走 LLM——**不误杀**（AC 场景 5）
- 与 engine 层 `_MIN_DOCS_SKIP_REFLECT=3`（≥3 篇跳过反思）互补不冲突：本闸门管"太少先反思"，engine 管"足够多不反思"

### WP4 层 2 prompt 强化（ADR-0005 层 2 落地）

- `_CHECK_PROMPT` 重构（返回 JSON 结构不变，向后兼容）：
  - **CoT 信息点比对**：判断步骤 1-3（先列回答所需信息点 ≥2 个 → 逐点比对文档编号标记已覆盖/部分覆盖/未覆盖 → 综合下结论）
  - **few-shot 正反例**：示例 1 充分（线程池核心参数，文档直接覆盖）+ 示例 2 不充分（G1 GC 停顿时间预测模型，文档只覆盖基本概念）
- **自洽性检查**（配置开关 `src/config.py` + `sufficiency_self_check_enabled: bool = False`，env `PW_SUFFICIENCY_SELF_CHECK_ENABLED`）：
  - 默认 False → 零额外 LLM 调用（成本翻倍，按需开启）
  - 开启时同 query 两温度各判一次（0.1 反思温度 / 0.7 `_self_check_temperature` 第二温度），两次 `sufficient` 不一致 → **保守判充分**（防漏判，AC 场景：自洽不一致）
  - 开启时 LLM 异常 → 保守充分（走统一 except → 默认充分，降级表 AC §5）

### WP5 层 3 多信号融合（ADR-0005 层 3 落地）

- 分数达标（≥0.4）或字段缺失 → 才进 LLM 判模糊地带（预算不对称投放）
- **LLM 判不充分 → 尊重语义走 rewritten_query**，不因分数高强制充分（AC 场景 4）
- 分数低 → 直接不充分不调 LLM（省成本）
- 闸门/LLM 异常 → 默认充分（防死循环，保持"默认充分"哲学，未引入任何新强制失败路径）

### 测试（tests/test_reflector.py 追加 TestCheckSufficiencyGates 10 用例，全过）

- 硬闸门 3 例：top-1 0.25 < 0.4 不调 LLM（`mock_get.assert_not_called()` 零 LLM 断言）/ 1 篇不调 LLM / 0.7 达标走 LLM（`assert_called_once` 恰好一次）
- 语义尊重 1 例：0.7 高分 + LLM 判不充分 → 走 rewritten_query
- prompt 结构 1 例：few-shot 正反例（示例 1/示例 2）+ CoT（信息点/判断步骤）+ JSON 结构键存在
- 自洽开关 2 例：开启一致 → 采用结果（2 次调用）；开启不一致 → 保守充分（2 次调用）；默认关闭恰好 1 次调用（零额外，并入达标用例断言）
- 降级 2 例：abs_cosine 缺失走 LLM（不误杀）；LLM 异常 → 默认充分（"默认通过"在 reason 中）
- **既有用例适配 1 处**：`tests/test_reflector_temperature.py::test_check_sufficiency_uses_low_temperature_client` 原传 1 篇文档验证反思温度，会被新数量闸门短路（<2 篇不调 LLM）——补到 2 篇带 abs_cosine 文档，仍验证"反思温度 0.1"意图不变（本模块刻意行为变更的直接后果，非其他会话文件）

### 与 ADR 一致性

- ADR-0005 层 1：文档数 < 2 + top-1 绝对余弦 < 0.4 两道零 LLM 闸门，复用 module-035 绝对余弦口径（module-037 字段名）
- ADR-0005 层 2：few-shot 正反例 + CoT 信息点比对 + 自洽性检查配置开关默认关（不一致保守充分）
- ADR-0005 层 3：分数达标才问 LLM、LLM 不充分仍尊重语义、分数低直接不充分
- ADR-0005 层 4：**本模块明确不做**（标注数据积累后另行模块）
- 红线核查：只动本 WP 文件（agent/reflector.py / src/config.py / tests/test_reflector.py / tests/test_reflector_temperature.py 1 处适配 + 文档）；未触碰其他会话未提交文件（react.py、langgraph_react.py、main.py、faithfulness.py 等）；未运行 git commit

### 测试结果

- `python -m pytest tests/test_reflector.py tests/test_reflector_temperature.py -q`：31 passed
- 全量 `pytest tests/ -q`：**425 passed / 3 failed**（132.61s）——仅 3 项预存环境失败，与本模块无关：
  - `test_identity.py::test_identity_passed_to_service` — 预存 top_k 环境问题（assert 5 == 3，module-034 时代遗留）
  - `test_rerank_langgraph.py` 2 项 — 外部 API 429 限流（test_sse_tool_trace_events 断言 429==200）+ 同源事件流为空（test_budget_zero_endpoint_direct_answer），全量运行本地限流器触发，独立运行该文件通过（module-043 同判）
- 相对 module-043 基线（404/3）净增 21：本 WP +10（TestCheckSufficiencyGates）+ WP1/WP2 其他 Dev 新增用例（benchmark_rerank / golden_sufficiency）

## 2026-08-09 — Tester 全量回归（结论 PASS）

- 全量复跑 `python -m pytest tests/ -q`：**425 passed / 3 failed**（121.49s），与 Dev 自述及 Reviewer 复跑完全一致——仅 3 项预存环境失败（test_identity top_k assert 5==3；test_rerank_langgraph 429 + 限流致事件流为空，日志确认 "IP 127.0.0.1 触发限流: 20 次/60s"），与本模块无关，不计入
- 本模块新增测试单独复跑：test_reflector.py + test_reflector_temperature.py + test_golden_sufficiency.py → **43 passed**（27.32s），其中 TestCheckSufficiencyGates **9 用例**（确认 Dev-B"10 用例"为计数口误）+ test_golden_sufficiency 12 用例全过
- fixture 评测管线实测：`python -m eval.golden_sufficiency --fixture --no-save` → 12/12 评估 0 跳过，Accuracy 1.0000，混淆矩阵 6/0/0/6，insufficient Recall 1.0000 大字标出（管线验证通过，非真实指标）
- WP1 实测数据（250 相关文档分数 ≥0.98、6 pair 耗时降 44.9%、三档排序 6/6 一致）已在 changelog / ADR-0004 / review-report / **test-report.md**（本模块产出，含总览 + 逐条 AC 对照 + 失败详情）四处可查
- 红线独立复核（git status / git diff / git log）：6 条全部通过，未触碰其他会话文件，未运行 git commit
