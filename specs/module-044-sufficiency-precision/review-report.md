# Review Report — Module-044: Rerank 截断验证 + 反思充分性精确化

> Reviewer | 2026-08-09 | 结论：**approved**（发现均为 minor，无 critical/major）

## 1. 红线核查

| 红线 | 核查方式 | 结果 |
|---|---|---|
| ① 只动自己工作包文件 | `git diff` 核对：reflector.py 纯增量（常量+prompt+闸门+自洽块，generate/verify/stream 路径零改动）、reranker.py 仅常量+注释 5 行、config.py +5 行、测试 +179/+6；其余改动文件（react.py/langgraph_react.py/main.py/faithfulness.py/module-033 changelog）为其他会话既有未提交状态 | ✅ 通过 |
| ② 不 stage/提交他人改动 | `git status`：索引为空（全部 ' M'/??），无暂存内容；HEAD 仍为 module-043 提交 0984c80，无新 commit | ✅ 通过 |
| ③ 预存环境失败不计入 | 全量复跑 `pytest tests/ -q`：425 passed / 3 failed（127.83s），3 项失败与自述完全一致（test_identity top_k assert 5==3；test_rerank_langgraph 429 + 事件流为空） | ✅ 通过 |
| ④ 不运行 git commit | git log 无 module-044 提交 | ✅ 通过 |
| ⑤ 返回结构不变 | 全部路径核验：空文档/<2 篇/分数闸门 → `{sufficient:false, reason, rewritten_query}`；LLM 路径经 `_parse_check` 产出 `{sufficient, reason, rewritten_query?}`（仅不充分时带 rewritten_query，与旧版一致）；异常 → `{sufficient:true, reason}` | ✅ 通过 |
| ⑥ 闸门失败/异常 → 回退 LLM 或保守充分 | 代码核验：abs_cosine 缺失（None）→ 跳过闸门走 LLM；异常值（TypeError/ValueError）→ warning 后走 LLM；LLM 异常 → 默认充分；自洽开启不一致 → 保守充分；无任何新强制失败路径 | ✅ 通过 |

### 硬闸门零 LLM 证据（grep + 测试断言）

- `reflector.py:183-186` 数量闸门、`reflector.py:193-199` 分数闸门均在 `LLMFactory.get_client`（line 211）之前 return，无调用路径
- 测试 `test_gate_top1_score_below_threshold_no_llm` / `test_gate_fewer_than_two_docs_no_llm` 用 `mock_get.assert_not_called()` 断言零 LLM 调用；`test_score_passes_gate_goes_llm` 用 `assert_called_once` 断言自洽默认关时恰好一次（零额外）——全部实测通过
- 自洽开关：`config.py:85 sufficiency_self_check_enabled=False`（env `PW_SUFFICIENCY_SELF_CHECK_ENABLED`），默认关 → 单次调用

### WP1 实测数据真实性复核（Reviewer 独立重跑）

用本地模型 `ai_service/models/bge-reranker-v2-m3` 重跑 `python -m eval.benchmark_rerank --max-chars 250/500 --pairs 6`（预热后计时）：

| 项 | Dev-A 记录 | Reviewer 重跑 | 一致性 |
|---|---|---|---|
| 250 相关文档分数 | 0.9907/0.9912/0.9988 | 0.990730/0.991224/0.998833 | **完全一致**（确定性） |
| 250 弱相关 g1/doc2 | 0.0535 | 0.053540 | **完全一致** |
| 500 相关文档分数 | 0.9904/0.9930/0.9993 | 0.990354/0.993020/0.999288 | **完全一致** |
| 500 弱相关 g1/doc2 | 0.2195 | 0.219546 | **完全一致**（changelog "0.2195→0.0535" 属实） |
| 250 6 pair 耗时 | 5.455s | 5.696s | 同量级（±4%，机器负载噪声） |
| 500 6 pair 耗时 | 9.900s | 9.864s | 同量级 |
| 降幅 | 44.9% | (9.864-5.696)/9.864=42.3% | 结论一致：250 显著更快 |
| 排序 | 6/6 一致 | 重跑 250/500 两档 doc1 全部居前 | 一致 |

结论：WP1 数据**真实且可复现**（分数确定性完全吻合，耗时同量级）；决策规则（250 相关文档分数 ≥0.98 + 耗时显著下降）满足 → 采纳 250 数据驱动成立。ADR-0004 TODO 更新与四档选数表（2000 行引用历史数据，plan 只要求实测 250 vs 500，可接受）如实记录。

## 2. 逐条 AC 对照

### §1 功能验收（WP3+5 层 1+3）
- [x] docs 为空 → 不充分（现有行为保留，reflector.py:178-180）
- [x] 文档数 < 2 → 直接不充分 + rewritten_query，零 LLM（line 183-186 + 测试断言）
- [x] top-1 abs_cosine < 0.4 → 直接不充分 + rewritten_query，零 LLM（line 193-199）
- [x] 分数达标 ≥0.4 → 才进 LLM 判模糊地带（line 204 起）
- [x] LLM 判不充分 → 尊重语义走 rewritten_query（`test_llm_insufficient_respected_high_score` 实测通过）
- [x] 返回结构不变（见红线 ⑤）

### §2 功能验收（WP4 层 2）
- [x] few-shot 正反例各 1（_CHECK_PROMPT 示例 1 充分 / 示例 2 不充分）
- [x] CoT 信息点比对步骤（判断步骤 1-3：列信息点 ≥2 → 逐点比对编号标记 → 综合下结论）
- [x] 自洽性检查配置开关默认 False；开启两温度各判一次（0.1/0.7）、不一致保守充分（2 个测试实测）
- [x] 输出 JSON 结构不变（prompt 尾部返回格式段落未变，`_parse_check` 未动）

### §3 功能验收（WP2 层 0）
- [x] golden_sufficiency.py 跑通：Accuracy + 混淆矩阵 + per-class P/R/F1（fixture 冒烟实测：12/12 评估 0 跳过，Accuracy 1.0，混淆矩阵 6/0/0/6 正确）
- [x] eval_runs 落库 eval_type='sufficiency' + git_commit + 配置快照（契约与 golden_retrieval.save_eval_run 签名逐参核对一致，测试打桩验证）
- [x] 标注集充分/不充分各 6、问题借 golden 集真实题目、fixture 模式不依赖 DB/LLM（12 用例实测通过）
- [x] 报告重点标出 insufficient Recall（scores 含 `insufficient_recall` 字段 + 报告大字行）

### §4 功能验收（WP1 ADR-0004 验证）
- [x] benchmark_rerank.py 可配 --max-chars（250/500/1000/2000）+ 2/6 pair 计时 + 每对分数输出（Reviewer 实跑通过）
- [x] 实测 250 vs 500（本地模型）→ 数据记录（真实性已复核，见上）
- [x] 四档选数表补齐 → 数据驱动决策采纳 250，如实记录两面性（弱相关分数下降但排序不变）

### §5 降级验收
- [x] abs_cosine 缺失/异常 → 不误杀走 LLM（`test_degrade_missing_abs_cosine_goes_llm` 实测）
- [x] 闸门/LLM 异常 → 默认充分（`test_degrade_llm_exception_conservative_sufficient` 实测）
- [x] 自洽开启时 LLM 异常 → 保守充分（统一 except → 默认充分）
- [x] 正常路径零回归（分数达标 + LLM 判充分 → 行为与旧版一致；全量 425/3 仅预存失败）

### §6 接口兼容
- [x] 返回结构不变；generate_answer / generate_answer_stream / verify_answer 未受影响（diff 零改动）；engine.py 调用点未动（无需改动，缺失时 reflector 侧兜底）

### §7 测试验收
- [x] TestCheckSufficiencyGates 9 用例（硬闸门 2 + 达标走 LLM 1 + 语义尊重 1 + prompt 结构 1 + 自洽 2 + 降级 2），零 LLM mock 断言、assert_called_once、prompt 结构断言齐备——Dev-B 自述"10 用例"为计数口误（枚举清单实为 9，见 findings）
- [x] test_golden_sufficiency.py 12 用例全过（Reviewer 实测 12 passed）
- [x] 全量 425/3 复现（与 module-043 基线同源的 3 项预存环境失败）

### §8 文档验收
- [x] changelog.md 两段（WP1+WP2 / WP3-5）含实测数据与决策
- [x] ADR-0004 TODO 状态更新（已验证 + 四档表）；ADR-0005 状态更新（层 0-3 已实现，层 4 留待数据）
- [x] 记忆文件 3 份更新（存在重复/过期条目，见 findings #2）
- [x] 层 4 明确说明本模块不做及理由（标注数据不足，与 ADR-0003 L4 同理）
- [ ] test-report.md 尚未产出（按验收应含 WP1 实测数据）——建议由 Tester/Planner 补一份；WP1 数据已在 changelog + ADR-0004 + 本报告三处可查，不阻塞

## 3. ADR 一致性

- **ADR-0004**：一致。决策正文未重写；验证结论（采纳 250）与决策 2 的"精度-成本拐点"框架一致；弱相关文档绝对分数下降但排序不变符合决策 3 已接受的分数压缩特性；"分数阈值过滤需校准"展望原样保留。已复制入 worktree specs/adr/（specs/ 被 .gitignore 忽略，与 module-033/043 先例一致，Planner 提交时需 `git add -f`）。
- **ADR-0005**：一致。层 0（标注集 + 指标 + eval_runs sufficiency 落库 + fixture）与层 1-3（零 LLM 硬闸门 / prompt 强化 + 自洽开关 / 多信号融合）全部按 ADR 设计落地；层 4 明确未做。实施状态段追加于决策正文之后，未改正文。
- 阈值 0.4 为经验值（对齐 module-035 memory_recall_min_score），ADR-0005 追问 2 已注明待层 0 阈值扫描校准，本轮不阻塞——Dev 已诚实记录。

## 4. Findings（全部 minor，不阻塞合入）

1. **（minor）abs_cosine 字段链"应含该字段"的断言过于乐观（Dev-B）**：retriever.py Step 4 合并（350-351 行）对"FTS+向量双命中"文档只复制 `vector_score`，`abs_cosine`（归一化前只存于向量路）未随合并带入——双命中文档（真实链路中占比可观）在精排后**没有**该字段，分数闸门会被静默跳过走 LLM。方向安全（正合 plan"缺失走 LLM 不误杀"），但生产中层 1 闸门覆盖率低于测试表现；reflector.py:189-191 注释"仅 FTS 命中文档无该字段"不准确。建议后续模块在合并循环补 `merged[doc_id]["abs_cosine"] = doc["abs_cosine"]`（retriever 属 module-043 域，本模块不动）。
2. **（minor）记忆文件存在重复/过期条目**：MEMORY.md 第 16 行与 rag-agent-roadmap.md 第 27 行仍为"🚧 进行中（WP1/WP2 待做）"（Dev-B 早期写入），与已完成条目（MEMORY.md 15 行、roadmap 25 行）矛盾；rag-architecture.md 37/39 两行内容重叠。建议 Planner 合入前清理去重，避免误导后续会话。
3. **（minor）Dev-B 自述"TestCheckSufficiencyGates 10 用例"实为 9 个测试方法**（枚举清单亦为 9 条）——纯计数口误，changelog/记忆文件沿用该数；不影响覆盖（9 例覆盖全部 AC 要求场景且实测全过）。
4. **（minor）reranker.py 140-142 行注释残留"前 1000 字符已含主要语义，截断后约 3.4s"**，与新常量 250 矛盾（Dev-A 更新了头部注释块但漏了此处的历史注释）。纯文档问题，无功能影响。
5. **（信息）engine 循环交互说明**：<2 篇或分数不达标时闸门返回 insufficient + rewritten_query=query（恒等改写），engine 对恒等改写 break（既有逻辑）→ 该轮不触发二次检索、直接以现有文档生成。这是 plan 场景 2/5 的既定语义且防死循环，但"不充分"结论在 1 篇文档场景下不再触发改写重检（旧版可能由 LLM 改写重检）——行为差异为刻意设计，如实记录供上线观察。
6. **（信息）benchmark 2000 档未重测**（引 ADR-0004 历史数据"耗时线性涨、精度增益趋零"）——plan 只要求实测 250 vs 500，四档表内容完整，可接受。

## 5. 结论

**approved**。两条工作包均按 plan/AC 实现：WP1 数据经 Reviewer 独立重跑验证真实可复现、决策规则满足；WP2 评测闭环（12 条标注集 + 指标 + 落库 + fixture）完整；WP3-5 层 1-3 代码核验与 9 项测试全过、降级哲学与返回结构保持；红线 6 条全部遵守。发现均为 minor（字段链覆盖说明、记忆文件去重、注释/计数口误），不阻塞合入，建议随模块收尾一并清理。
