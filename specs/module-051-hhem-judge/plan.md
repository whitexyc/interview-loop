# 功能规格说明书 — Module-051: verify_answer 接入 HHEM 专职裁判（ADR-0010 P0-② 实施）

> Planner | 2026-08-11

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-051 |
| 模块名称 | HHEM 专职裁判接入：LLM 拆句 + HHEM 判分 + 降级链 + kappa 评测闭环 |
| 版本号 | 0.51.0-module-051 |
| 优先级 | P0（module-050 数据验证结论：中文场景 HHEM Accuracy 0.77 vs MiniCheck 0.51，选型已定） |
| 预估代码量 | factcheck_judge 封装 + verify_answer 拆分 + 评测脚本 + 测试，≤ 450 行 |

---

## 2. 需求

| WP | 内容 | 来源 |
|----|------|------|
| WP1 裁判封装 | 新建 `rag/retrieval/factcheck_judge.py`（或 `rag/factcheck_judge.py`，Developer 按目录细分后归属定）：延迟加载 HHEM（复用 module-050 `compare_factcheck_models.py` 已验证的加载适配：get_class_from_dynamic_module + safetensors 手动加载 + embed_tokens 键展开 + HF_HUB_OFFLINE + flan-t5-base tokenizer）；`predict(docs, claims)` 批量打分；CPU 推理用 `asyncio.to_thread` 不阻塞事件循环（对齐 embeddings 模式）；模型缺失/加载失败/推理异常 → 返回 None（上层降级 LLM） | ADR-0010 P0-② + module-050 结论 |
| WP2 verify_answer 拆分 | `reflector.py::verify_answer` 重构：**LLM 只拆 claims**（`_VERIFY_PROMPT` 精简为纯拆句任务，不再判 verdict）；**verdict 由 HHEM 判定**——每个 claim 与每篇文档打分，取该 claim 的 max 分数映射三态（≥0.7 supported / 0.3-0.7 inferred / <0.3 unsupported，阈值配置化）；**evidence 取 max 分对应文档号**（比 LLM 编引用号真实）；引用号越界校验保留（max 分来源文档天然不越界，但兼容旧 claims 结构）；返回结构不变（claims/overall_confidence/total_claims/supported/inferred/unsupported，前端零改动） | ADR-0010 问题 1/2/3/8 |
| WP3 配置与开关 | config.py：`verify_judge_model`（"hhem" / "llm"，**默认 "hhem"**——数据已验证 HHEM 中文胜出，降级链保证失败回退 LLM 零风险）+ 三态阈值（verify_hhem_threshold_high=0.7 / verify_hhem_threshold_low=0.3）+ PW_ 前缀 | module-050 结论 |
| WP4 降级链 | 三层：① HHEM 不可用（缺失/加载失败/推理异常）→ 回退 LLM 判分（现有逻辑保留）② LLM 也失败 → 空 claims（现有降级哲学）③ 开关 "llm" 时直走旧逻辑（零回归开关） | ADR-0010 降级哲学 |
| WP5 kappa 评测闭环 | 新建 `eval/golden_factcheck.py`：人工标注 **50 条 claims**（从真实答案/SUFFICIENCY_DATASET 构造，supported/inferred/unsupported 三态标注）→ HHEM 判定 vs 人工 **Cohen's kappa > 0.7 门槛**（ADR P1-④）；eval_runs 落库 `eval_type='factcheck'`；`--fixture` 启发式不依赖模型 | ADR-0010 P1-④ |
| WP6 测试 | tests/test_factcheck_judge.py：加载降级（mock 缺失路径）、批量打分、三态映射、evidence 取 max 文档、verify_answer 拆分集成（mock HHEM 分数）、降级链三层、返回结构兼容；全量 579+ 全绿 | AC |

### 验收场景

```
场景 1：HHEM 判分
  假设 答案 3 句，HHEM 给分 [0.85, 0.45, 0.15]，文档 2 篇
  那么 supported=1（0.85≥0.7）、inferred=1（0.45 在 0.3-0.7）、unsupported=1（0.15<0.3）；
       evidence 分别为 [1]/[2]/N/A（取该 claim 各文档 max 分对应文档号）

场景 2：HHEM 不可用降级
  假设 models/hhem-2.1-open 缺失或加载失败
  那么 verify_answer 回退 LLM 判分（旧逻辑），行为与 module-039 完全一致

场景 3：开关回退
  假设 config verify_judge_model="llm"
  那么 完全不加载 HHEM，走旧逻辑（零回归开关）

场景 4：kappa 门槛
  假设 python -m eval.golden_factcheck（真实模式，HHEM 就绪）
  那么 输出 HHEM vs 人工 kappa；kappa < 0.7 时如实标注"未达门槛"，不伪造
```

---

## 3. 技术方案

### 3.1 工作包与涉及文件

| WP | 文件 | 操作 |
|----|------|------|
| WP1 | `ai_service/rag/retrieval/factcheck_judge.py`（新：延迟加载 + predict 批量 + to_thread + 降级 None） | 新建 |
| WP2 | `ai_service/agent/reflector.py`（`_VERIFY_PROMPT` 精简 + `verify_answer` 拆分：LLM 拆句 → HHEM 判分/三态映射/evidence 取 max 文档） | 修改 |
| WP3 | `ai_service/src/config.py`（verify_judge_model 默认 "hhem" + 两阈值 0.7/0.3，PW_ 前缀） | 修改 |
| WP5 | `ai_service/eval/golden_factcheck.py`（50 条人工标注 + kappa + eval_runs + --fixture） | 新建 |
| WP6 | `ai_service/tests/test_factcheck_judge.py` | 新建 |
| 文档 | changelog / review-report / test-report + memory/ 三文件 + ADR-0010 状态更新 | 修改 |

### 3.2 关键实现约束

- **WP1 加载**：严格复用 module-050 `compare_factcheck_models.py` 中已验证的 HHEM 加载路径（不重新发明）——`HF_HUB_OFFLINE=1`、`get_class_from_dynamic_module("configuration_hhem_v2.HHEMv2Config")` / `("modeling_hhem_v2.HHEMv2ForSequenceClassification")`、safetensors `load_file` + `embed_tokens` 键展开（4.x→5.x）、`foundation=models/flan-t5-base` tokenizer（models/ 下已有）；建议把加载逻辑提取为两脚本共享的模块（如 `rag/retrieval/hhem_loader.py`），compare_factcheck_models.py 改为引用之——**单一来源**（若改动成本高可注明取舍，Reviewer 关注）
- **WP1 predict**：`model.predict(list(zip(docs, claims)))` 批量；CPU 推理包 `asyncio.to_thread`；单次调用失败（异常）→ 返回 None 走降级
- **WP2 拆分**：`_VERIFY_PROMPT` 精简为"把答案拆成独立陈述句，每条 1-2 句，只输出 claim 文本数组"（不再判 verdict/填 evidence——verdict 与 evidence 由 HHEM 定）；LLM 拆句失败/超时 → 空 claims（现有降级）；claims 空时 HHEM 不调用
- **WP2 三态映射**：每个 claim 对每篇文档打分 → `max_score = max(各文档分)`，对应文档号 = evidence（1-based，与现结构一致）；`max_score ≥ 0.7 → supported`、`0.3 ≤ max_score < 0.7 → inferred`、`< 0.3 → unsupported`（阈值读配置）；overall_confidence 保持 `1 - unsupported/total`（口径不变，前端零改动）
- **WP4 降级**：HHEM 加载/推理任一失败 → `_judge_by_llm`（保留现有 `_VERIFY_PROMPT` 全量版本或重构后的旧路径——若 prompt 拆分了，把旧 prompt 保留为 `_VERIFY_LLM_PROMPT` 供降级用，避免降级路径行为漂移）；LLM 失败 → 空 claims；开关 "llm" 完全不初始化 HHEM
- **WP5 标注集**：50 条 claims 从 SUFFICIENCY_DATASET 问题 + 文档构造（claim=问题、doc=文档，人工标 supported/inferred/unsupported 与 HHEM 分相关）；kappa 用 sklearn `cohen_kappa_score`（三态直接算，或二值 supported-vs-rest 算，两种都输出）；`--fixture` 用关键词启发式；eval_runs 复用 golden_retrieval 落库函数
- **诚实边界**：HHEM 中文是跨语言泛化（module-050 实测 Accuracy 0.77 是最好可用裁判）；三态阈值 0.7/0.3 是经验值（标注集可校准）；50 条标注量级小（kappa 门槛是方向性验证非最终结论）

### 3.3 降级

| 场景 | 处理 |
|------|------|
| HHEM 模型缺失/加载失败 | 回退 LLM 判分（保留旧 `_VERIFY_PROMPT` 全量版），行为与 module-039 一致 |
| HHEM 推理异常 | 同上（单次失败返回 None 不抛） |
| LLM 拆句失败/超时 | 空 claims（现有降级哲学） |
| LLM 判分也失败 | 空 claims（overall_confidence=0.0，前端已处理） |
| config 开关 "llm" | 零回归直走旧逻辑，不加载 HHEM |
| kappa 未达 0.7 | 如实标注"未达门槛"，不伪造数字，标注集后续扩充 |

---

## 4. 依赖

- module-050（HHEM 加载适配 + 选型结论 + 模型已下载）、module-039（verify_answer 现结构）、module-044（SUFFICIENCY_DATASET 标注数据）、eval_runs 基建（golden_retrieval）
- HHEM 模型已就绪：`models/hhem-2.1-open/`（438MB）+ `models/flan-t5-base/` tokenizer

## 5. 已知边界

- 串行阻塞的"异步后置推送"（答案先返回 + verified 后推）**本轮不做**（P2，改动涉及协议与前端）；HHEM 替代后单次验证成本大幅下降（0.36s/对 vs LLM 1.5-3s），缓解串行等待
- 三态阈值 0.7/0.3 经验值待标注集校准；真实答案句子级验证（claim=答案句子）随本模块落地后自然生效
- 前端已验证 claims 数组逐条渲染（module-039 已实现 P0-①），无需改动
- 全量 pytest 579 全绿保持（本模块新增 +N）
