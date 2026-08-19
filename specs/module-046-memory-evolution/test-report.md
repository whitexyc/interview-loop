# Module-046 测试报告

> 记忆进化：强化/衰减/升级 + 会话摘要 + 提取评测闭环（ADR-0007 实施）
> 测试执行：2026-08-10 | 执行人：Dev-A（WP1）+ Dev-B（WP2/WP3）+ 修复 Developer（review 复核）

---

## 1. 全量结果

| 指标 | 数值 |
|---|---|
| 命令 | `python -m pytest tests/ -q` |
| 全量通过 | **503 passed / 0 failed**（含 review 修复回归 3 例） |
| 历史基线 | 448 passed（全绿保持，0 新失败） |
| 模块新增 | +55（WP1 18 + review 修复 3 + WP2 12 + WP3 22） |

---

## 2. 各文件用例明细

### tests/test_memory.py（60 → 76，+16）

| 测试类 | 用例数 | 覆盖 |
|---|---|---|
| TestSave | 5 | 分块+向量化+入库、空内容/空 IP/通配符 IP、embedding 失败回滚 |
| TestRecall | 7 | 空 query、source_pattern 隔离、父子块映射、动态 K 降级 |
| TestNextTitle | 4 | 标题序号按 source+当日计数、date 对象绑定 |
| TestSourceFilter | 4 | 默认排除 memory、source_pattern 拼入 SQL |
| TestEngineMemoryInjection | 4 | 记忆注入零回归前提 |
| TestEngineRealtimeSkipsMemory | 2 | realtime 跳过记忆召回 |
| TestPromptZeroRegression | 1 | 空 sections 逐字节一致 |
| TestListDocumentsExcludesMemory | 1 | 列表排除记忆 |
| TestSourceLayering | 4 | 三层 source 精确匹配 |
| TestSaveShort | 4 | 短期层写入/去重范围/标题计数 |
| TestRecallShort | 4 | 硬上限过滤/隔离/失败降级 |
| TestRecallDynamicKAbsCosine | 7 | 三档真实可达/低分过滤/嵌入失败降级 |
| TestRecallShortAbsCosine | 1 | 短期动态 K 绝对余弦 |
| TestChildEmbeddings | 3 | 批量取 embedding |
| TestDedupThreshold035 | 2 | 0.85 阈值校准 |
| TestConfig035 | 1 | 分数口径配置默认值 |
| TestMergeDuplicateMentionRefresh | 3 | 写入侧提及刷新（短期/存量 None/长期不触碰） |
| TestRecallShortEvolution | 6 | 衰减 0.5^(7/3)≈0.198/提及加权 1.4/存量 fail-open/进化异常走原逻辑/多候选重排（新鲜排前）/动态 K=1 截取新分数最高者 |
| TestRecallHitRefreshesMention | 2 | 召回命中刷新 UPDATE/超硬上限项不刷新（修复回归） |
| TestPromotion | 4 | 升级复制+删短期/幂等/阈值未达/窗口超期 |
| TestRememberDetection | 4 | 记住直达长期/变体/失败降级/原路径 |
| TestConfig046 | 1 | 5 项进化配置默认值 |

### tests/test_session_memory.py（+12）

| 测试类 | 用例数 | 覆盖 |
|---|---|---|
| TestSessionSummary | 7 | 超限写入摘要行/增量 MemGPT 递归/LLM 失败 fail-open/空输出跳过/未超限不调 LLM/最新一条+降级/source 隔离 |
| TestLayeredInjection | 5 | 摘要段前置+最近 20 条/无摘要逐字节一致/摘要失败跳过/无持久化回退/空身份回退 |

### tests/test_golden_memory.py（新建 22）

| 测试类 | 用例数 | 覆盖 |
|---|---|---|
| TestLoadMemoryGolden | 3 | 标注集结构（≥20 条/dialogue/facts/不应提取样本）/非法结构 ValueError |
| TestDialogueMapping | 4 | 末轮 user/assistant 映射+history/无回答 None/空文本 |
| TestPrfMetrics | 6 | 双向包含匹配/tp-fp-fn/贪心防重复/过度提取全 fp/已知值 P/R/F1/空行 0.0 |
| TestRunEval | 3 | stub 端到端满分/过度提取惩罚/提取器异常跳过 |
| TestRecordEvalRun | 3 | eval_runs 契约（eval_type='memory_extraction'）/落库失败返回 0 |
| TestFixtureExtract | 3 | 关键词命中切句/无关键词空/确定性无 LLM |

### 相关既有文件（零回归）

test_identity.py / test_memory_extractor.py / test_engine.py 等 448 基线用例全过，
engine.py 两 Dev 改动共存验证通过。

---

## 3. review 修复回归（3 例，全绿）

| 用例 | 修复前行为（review 实证） | 修复后断言 |
|---|---|---|
| `TestRecallShortEvolution::test_evolved_score_reorders_candidates_fresh_first` | `_evolve_recall` 只改分不重排，返回顺序仍为原始语义分序（旧候选在前） | 按新 score 降序：今天主题（≈0.7）在前、20 天前主题（≈0.009）在后 |
| `TestRecallShortEvolution::test_evolved_ranking_drives_dynamic_k_truncation` | dynamic_k=1 时按语义分序截取，返回衰减到≈0 的旧候选，新鲜候选被丢弃 | 只返回新分数最高者（新鲜候选），旧候选被截断丢弃 |
| `TestRecallHitRefreshesMention::test_beyond_hard_cap_not_refreshed` | UPDATE IN (1, 2) 含超硬上限项，被刷新后 age≈0 复活，击穿 30 天硬上限 | UPDATE 仅 IN (1)（通过硬上限过滤、参与召回）的参考文档；超上限项不产生 UPDATE |

---

## 4. 冒烟与回归结论

- 全量 `python -m pytest tests/ -q`：503 passed / 0 failed；历史 448 基线全绿，未引入任何新失败。
- `python -m eval.golden_memory --fixture --no-save`：28/28 评估 0 跳过、过度提取 0
  （管线验证；fixture 为启发式非真实指标，真实指标需 LLM 环境补跑）。
- 红线核对：只动工作包文件（engine.py 两 Dev 区域不重叠共存全绿）；零迁移
  （存量 NULL/0 fail-open）；长期层零改动；未执行 git commit。
- 已知边界（非本模块回归，详见 changelog）：摘要段在 reflector 纯反射路径可能被
  [-6:] 截断（module-005 遗留）；本地开发库 documents 表无两新列，部署前需
  ALTER TABLE ADD COLUMN last_mentioned_at / mention_count（测试全 mock 不受影响）。

---

## 5. Tester 独立复核（2026-08-10）

> 执行人：Tester（独立全量回归，非 Dev/Reviewer 结果复述）

### 5.1 全量回归（红线 4）

| 指标 | 实测值 |
|---|---|
| 命令 | `python -m pytest tests/ -q`（独立执行） |
| 结果 | **503 passed / 0 failed / 5 warnings，117.90s** |
| 历史基线 | 448 passed（全绿保持，0 新失败，+55 全为本模块新增） |

### 5.2 新增测试逐文件验证

| 文件 | 收集数 | 独立运行结果 | 覆盖核对 |
|---|---|---|---|
| tests/test_memory.py | 76（+16） | 通过 | 提及刷新（TestMergeDuplicateMentionRefresh 3）、衰减/加权/重排/动态 K/存量 fail-open（TestRecallShortEvolution 6）、召回命中刷新 + 硬上限不复活（TestRecallHitRefreshesMention 2）、升级幂等（TestPromotion 4）、记住检测（TestRememberDetection 4）、进化配置（TestConfig046 1）、硬上限过滤（TestRecallShort 内） |
| tests/test_session_memory.py | 24（+12） | 通过 | 摘要维护（TestSessionSummary 7：超限先摘要/增量递归/LLM 失败 fail-open/空输出跳过/≤cap 不调 LLM/最新一条/source 隔离）、分层注入（TestLayeredInjection 5：摘要前置+最近 20 条/无摘要逐字节一致/摘要失败跳过/回退） |
| tests/test_golden_memory.py | 22（新建） | 通过 | 标注集结构（≥20/不应提取样本/非法 ValueError）、dialogue 映射、P/R/F1（已知值/空行/过度提取惩罚）、eval_runs 契约（eval_type='memory_extraction'）、fixture 确定性无 LLM |
| 三文件合计 | 122 | **122 passed，55.75s** | 与全量一致 |

### 5.3 WP3 管线冒烟（独立复跑）

- `python -m eval.golden_memory --fixture --no-save`：exit=0，
  Dataset 28 / Evaluated 28 / Skipped 0 / Over-extraction 0。
- P/R/F1=0.0 为 fixture 关键词启发式的预期表现（返回含关键词的整句含"用户:"前缀，
  与标注浓缩事实无法包含匹配）——脚本 docstring 明示"仅用于演示评测管线，
  不代表真实提取能力"；真实指标逻辑由单测覆盖（stub 满分 / 过度提取惩罚 /
  已知值 P/R/F1）。非缺陷。

### 5.4 结论

- 红线 4（全量全绿）✅：503 passed / 0 failed，448 基线 0 新失败。
- 验收 §4"全量 pytest 428+ 全绿"与 §6"全量全绿"✅。
- 验收 §6 三测试文件新增用例 ✅（提及刷新/衰减/硬上限/升级幂等/记住；
  摘要维护/分层注入/≤20 条零回归；标注集结构/P-R/eval_runs/fixture）。
- **Tester verdict：PASS（0 失败）**
