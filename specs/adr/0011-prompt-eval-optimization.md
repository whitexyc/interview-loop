# ADR-0011 — 提示词评估优化：四维评估 + 三步落地路径

- 状态：✅ 第一步（变体测试）已实施（module-055，2026-08-12）；第二/三步按数据决定
- 日期：2026-08-12
- 背景：反思（check_sufficiency）、意图分类（router）、验证（verify）等环节的 prompt 目前是"单版本 + 主观判断"：改一句措辞无法量化好坏。本项目已有 golden 评测闭环（retrieval/sufficiency/intent/factcheck/memory 五套 + eval_runs 版本化落库），缺的是"对同一任务的不同 prompt 做消融对比"的方法论落地。本 ADR 记录评估维度、业界工具、算法代际与落地路径。

## 1. 问题拆解：为什么"判断提示词好坏"难

| 难点 | 说明 |
|------|------|
| 单次评估不可比 | 一次跑分受 LLM 非确定性、样本切片影响，需同集同口径对比 |
| 维度单一 | 只看 Accuracy 会忽略"漏判不充分最致命"这类不对称代价（本仓库已用 insufficient Recall 覆盖） |
| 无基线 | 没有"当前 prompt 得分"就没有改进依据（本仓库已用 eval_runs 版本化解决） |
| 无消融 | 改一句话不知道是哪个成分（CoT/few-shot/措辞倾向）起的作用 |

## 2. 四维评估框架

对每个 prompt 变体在同一 golden 集上度量：

| 维度 | 指标 | 本仓库落点 |
|------|------|-----------|
| 正确性 | Accuracy / 混淆矩阵 | golden_sufficiency/golden_intent 已有 |
| 不对称代价 | 关键类 Recall（不充分漏判/知识漏检最致命） | insufficient_recall（sufficiency）、knowledge Recall（intent）已有 |
| 一致性 | Cohen's kappa（两判者一致程度） | module-055 变体对比表新增 |
| 成本 | 单样本耗时/调用数 | module-055 变体对比表新增（elapsed） |

## 3. 业界工具扫描（结论：本项目已具备等价能力，不引入新工具）

| 工具 | 能力 | 本项目对应 |
|------|------|-----------|
| OpenAI Evals | 评测集 + 对比报告 | eval/ 五套 golden + eval_runs 落库 + golden_retrieval.compare_runs |
| promptfoo | CLI 变体对比矩阵 | eval/prompt_variants.py（module-055） |
| Ragas | RAG 指标 | eval/ragas 历史实现 + faithfulness（module-038） |
| LangSmith/Langfuse | 在线追踪 + 评测 | 本项目走离线 eval_runs + 反馈飞轮（module-048 feedback 表） |

结论：本仓库离线评测闭环已成型，缺的只是"变体消融"脚本（第一步）与"自动寻优"（第二/三步）——不引入外部评测平台（部署/成本/数据出境考量）。

## 4. 提示词优化算法代际（三步落地）

| 代际 | 方法 | 说明 | 状态 |
|------|------|------|------|
| 第一代 | **变体测试**（手动构造 N 个变体 → 同集评测 → 对比表） | 消融实验自动化，量化"哪句话有用"；只度量不替换生产 prompt | ✅ module-055 已实施（eval/prompt_variants.py + check_sufficiency prompt 可注入参数） |
| 第二代 | **OPRO**（Optimization by PROmpting） | LLM 基于历史变体得分迭代生成新变体，每轮打分淘汰——用 LLM 当优化器，最大化评测指标 | 待办：数据/需求决定（需评估成本：每轮 N×100 次 LLM 调用） |
| 第三代 | **DSPy**（Declarative Signature） | 把 prompt 变成可编译模块，自动搜索指令/示例（BootstrapFewShot 等） | 待办：引入新依赖 + 学习成本，数据积累后评估 |

## 5. 落地路径

1. **变体测试基建**（第一步，✅ module-055）：`eval/prompt_variants.py`（baseline + 4 个异质变体）+ `check_sufficiency(prompt=...)` 注入（默认零回归）。
2. **OPRO 循环**（第二步，待办）：复用变体对比表得分 → LLM 生成候选 → 择优入 eval_runs；成本受控（--limit）。
3. **DSPy**（第三步，待办）：若 OPRO 后仍低于预期，引入 DSPy 做指令/示例自动搜索。
4. **应用范围**：反思 prompt（sufficiency）先行（评测集最成熟：100 条标注）；intent/verify prompt 复用同一脚本框架（--task 扩展）。

## 6. 相关文件

- `ai_service/eval/prompt_variants.py`（module-055 新建）
- `ai_service/agent/reflector.py`（check_sufficiency prompt 可注入参数）
- `ai_service/tests/test_prompt_variants.py`（module-055 新建）
- 模块文档：`specs/module-055-prompt-eval/`
