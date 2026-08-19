# 审查报告 — Module-055: 提示词评估优化（ADR-0011 第一步）+ E2E 待办修复 + rrf 切默认

> Reviewer | 2026-08-12 | 第一轮审查
> **结论：✅ PASS（阻塞 0 项 / minor 5 项非阻塞）**

---

## 0. 审查结论

**verdict: pass。** 实现与验收标准逐条契合；WP-1~5 五个工作包全部落地且修复方向与诊断记录一致；全量 pytest **688/0** 独立复跑与 changelog 声明逐字一致；行为升级（L2 无条件触发 / L3 缺字段不标记 / 高置信触发）均有 E2E 实测支撑 + 测试重命名注明理由，非掩盖；记忆硬性约束满足（Developer 行/模块清单/头部日期/file-index/ADR-0011 状态均已更新）；简历/弹药等文档类零改动；未 git commit。

**三个 E2E 问题的根因诊断结论经代码级核对成立**：
- WP-2 根因 = LLM-as-Classifier 非确定性高置信误判 + 原 L2 触发条件绑死"低置信"（自报分数不可靠）；修法（无条件触发 + 规则表短路 + 43 词停用词数据驱动扩充）方向正确，golden 扫描 20/50→0/50 误确认；
- WP-3 根因 = HHEM 15 对贴近 15s 超时 + LLM 判分再超时 → 级联超时 verified_claims=0；修法（8×2 对数上限 + 500 字符截断 + 预算 20s + lifespan 后台 fail-soft 预热）取舍全部有实测数据（9.04s 冷加载 / 0.11s 每对 / 6 对 9.3s→2.4s / verdict 0.568→0.802）；
- WP-4 根因 = 融合路径存档代码本身正确（module-053 红线成立，直调实测 0.70），真根因是图谱通道父块（无向量分数）排 top-1 + 旧"缺字段→按 0.0 标记"语义恒误触发；修法（只对实测低分标记）语义正确（缺 ≠ 低分），图谱实体命中本身就是相关证据。

---

## 1. 独立复现与核验（全部通过）

| 核验项 | 方法 | 结果 |
|------|------|------|
| 全量测试 | `python -m pytest tests/ -q` 独立复跑 | **688 passed / 0 failed / 5 warnings（159.96s）**，与 changelog 声明 667+21 一致 |
| 定向测试 | test_prompt_variants + test_intent_validation + test_factcheck_judge | **97/97 passed**（12 + 47 + 38，与 changelog 分项一致） |
| rrf 默认生效 | 无 PW_RETRIEVAL_FUSION_MODE 环境 import settings | `retrieval_fusion_mode == "rrf"` ✓（config.py 默认值改 + Literal 枚举保留） |
| WP-2 术语提取 | `RouterAgent._kb_terms("G1垃圾收集器的核心创新是什么？")` | `['G1','垃圾','收集器','核心','创新']`——专有术语保留参与确认 ✓ |
| WP-2 停用词过滤 | `_kb_terms("今天心情不太好")` | `['不太好']`——"今天/心情"已过滤（数据驱动扩充生效）✓ |
| WP-5 存量测试 | git diff 核验存量测试改动 | 仅 test_factcheck_judge / test_intent_validation 更新（行为升级注明理由）；test_degradation_fix.py（module-054 2 项降级用例）monkeypatch 显式设 fusion_mode，与默认值无关 → "零存量断言改动"声明属实 ✓ |
| 零回归契约 | test_default_prompt_zero_regression | `check_sufficiency(prompt=None)` 传给 LLM 的文本与 `_CHECK_PROMPT.format(...)` 逐字节相等 ✓ |
| L3 语义 | engine._check_suspected_misclassify 代码核对 | top-1 有 abs_cosine 且 < 0.3 → 标记；无 abs_cosine → (False, 0.0)；实测 0.0 仍标记（float(0.0) < 0.3）✓ |
| HHEM 预热 | main.py lifespan 代码核对 | `_asyncio.create_task` 后台 fail-soft，`predict(["warmup"],["warmup"])` 签名匹配（docs/claims 逐对配对）✓ |
| 文档类未改 | git status | docs/、简历、弹药零改动 ✓ |
| 未提交 | git status | 无 module-055 commit（主会话统一提交）✓ |

## 2. 验收标准逐条核查（AC 9 节）

| 节 | 标准 | 结果 | 依据 |
|----|------|------|------|
| §1 | eval/prompt_variants.py（N 变体 × golden × 对比表）+ prompt 可注入默认零回归 + --variant/--no-save/落 eval_runs + 只度量不替换 | ✅ | 5 变体（baseline/v_brief/v_strict/v_fewshot/v_conservative）；对比表 Accuracy/insufficient Recall/kappa/耗时；`--variant`/`--limit`/`--no-save`/`--save`（eval_type='prompt_variant'）/`--fixture` 齐全；baseline 恒为生产 `_CHECK_PROMPT`（测试断言逐字节相等）；真实 LLM 冒烟（18 次 deepseek 调用 200 + 耗时记录） |
| §2 | 诊断记录入 changelog + E2E query 走 knowledge + 测试覆盖边界样本 | ✅ | changelog §3.1 记录 classify 输出（knowledge/conf 1.0 三次实测 vs module-054 误判 casual_chat——非确定性实证）/L2 条件缺口/L4 状态/规则表；真实 E2E intent=knowledge、sources=3；测试含 E2E query 高置信误判修正 + JVM/Redis 边界样本（test_e2e_query_high_confidence_casual_corrected / test_boundary_term_question_queries_corrected） |
| §3 | 诊断 verified_claims=0 根因 + 非流式 verified_claims 非空 + 方案取舍有数据 | ✅ | changelog §4.1 诊断"级联超时"（HHEM 15s + LLM 判分 15s 最坏 45s）；实测 15 对冷 9.04s / 热 0.11s 每对 / 服务内 17-19s；修复后 E2E verified total=8（sup3/inf1/unsup4）非空；诚实边界：deepseek 抖动时 LLM 环节仍可能空 claims（fail-soft，前端已处理） |
| §4 | 诊断 rrf 丢失原因 + top_abs_cosine 真实值 + suspected 不误触发 | ✅ | changelog §5.1 复现根因（图谱父块 top-1 缺向量分数 + HyDE 场景 id=239 实测 MISSING）；E2E chat 0.6664/0.7052、stream 0.8296 全部 suspected=False；图谱父块排首时如实显示 0.0 不误标记（度量诚实）；单测覆盖整组缺失/仅 top-1 缺失/实测低分仍标记 |
| §5 | 默认 hybrid→rrf + 存量测试注明理由 + 真实 E2E 默认模式 | ✅ | config.py 默认 "rrf" + `PW_RETRIEVAL_FUSION_MODE=hybrid` 回退保留；**零存量断言改动**（module-054 方案 A/B 已消解，test_degradation_fix 显式设模式，语义已对齐——非掩盖，行为升级仅发生在 L2/L3 两处且均改名注明）；真实 HTTP E2E（uvicorn 8001 无环境变量）chat+stream 全链路走 rrf 正常 |
| §6 | WP-2 根因复杂降级 / WP-5 存量失败核对 / 全量 688 全绿 | ✅ | WP-2 根因找到（LLM 非确定性）无需一层兜底，深层待办如实记录（deepseek 分类非确定性属既有特性）；WP-5 无存量失败；688/0 独立复跑一致 |
| §7 | ChatResponse/前端零改动 + retrieval 结构不变 + prompt 参数向后兼容 | ✅ | verified_claims 恢复后前端零改动渲染；abs_cosine 透传为修复（仅 L3 判定语义变化，字段结构不变）；check_sufficiency 新参默认 None 零回归（逐字节测试） |
| §8 | test_prompt_variants.py + WP-2/3/4 回归测试 + 全量 688+ | ✅ | 12 + 6 + 3 = 21 新增；E2E 场景 query 覆盖；全量 688/0 独立复跑 |
| §9 | changelog/review/test-report + 三记忆文件 + ADR-0011 状态 + 开工前已读 + 文档类不改 | ✅（test-report 移交 Tester） | changelog 注"开工前已读 project-context.md 全文"；三记忆文件已更新（模块行/头部日期 2026-08-12/activity Developer 行/file-index 4 行只追加）；ADR-0011 状态"第一步已实施"；review-report 本文件；test-report 待 Tester；简历/弹药未改 |

## 3. 红线与代码级核对（逐 WP）

1. **WP-1 只度量不替换**：`_CHECK_PROMPT` 常量未被修改（diff 仅新增 `prompt` 参数）；baseline 变体经 `_load_baseline()` 引用常量本身；`check_sufficiency` 中 `prompt if prompt is not None else _CHECK_PROMPT`，自洽第二判同用注入变体（对比口径一致）。变体占位符 fail-fast 在 LLM 调用前（load_variants）。
2. **WP-2 确认路径零 LLM 红线**：`_deterministic_confirm` 仅规则表（纯字符串）/FTS（jieba+SQL 倒排）/图谱（Cypher 实体名子串匹配）——无 LLM 调用，红线保持；规则表提前短路后规则词请求零 DB 查询（单测断言 fts/graph 不被 await）。异常仍保守 knowledge。
3. **WP-3 降级链完整**：上限（8 claims × 2 docs）在"旧格式兼容判断之后、predict 之前"生效；LLM 判分降级路径（_judge_by_llm）用全文 docs_text 不受截断影响；HHEM 返回 None/分数数量异常仍降级；verify_answer 外层兜底空 claims 不变。截断只作用于 HHEM 输入，不影响证据引用号语义（上限内 1-based）。
4. **WP-4 判定与展示同源**：`(flag, top1_abs)` 同源自取（engine.py:302），父块映射前存档（module-045 WP2b 契约保持）；`docs[0].get("abs_cosine")` 改 `is None` 判断——真实测量 0.0 仍触发标记（float(0.0) < 0.3），仅"缺字段"不标记，语义边界正确。
5. **WP-5 回退开关**：`PW_RETRIEVAL_FUSION_MODE=hybrid` 一键回退注释保留；Literal 枚举校验（fail-fast）保留。

## 4. 记忆硬性约束核查

| 项 | 结果 |
|----|------|
| project-context.md 模块清单追加 module-055 行（格式对齐） | ✅ 行 73，含版本 0.55.0-module-055 / 完成时间 2026-08-12 / 状态 ✅ |
| project-context.md 头部"最后更新"日期 | ✅ 2026-08-12（module-055 完成） |
| agent-activity-log.md Developer 活动行 | ✅ 2026-08-12 module-055 段 Developer 行（摘要完整含 6 个 WP + E2E + 688/0） |
| agent-activity-log.md Reviewer 活动行 | ✅ 本报告追加（见下） |
| file-index.md 新文件行（只追加） | ✅ 4 行（prompt_variants.py / test_prompt_variants.py / ADR-0011 / module-055 spec 目录） |
| ADR-0011 状态更新 | ✅ 第一步已实施（specs/adr/0011-prompt-eval-optimization.md 状态行 + 落地路径 + 相关文件） |
| 修改其他模块历史记录行 | ✅ 无（module-033 changelog 的 +47 行为工作树遗留物，见 minor #5） |

## 5. 发现清单（0 阻塞 / 5 minor 非阻塞）

### Minor（不阻塞验收）

1. **config.py 注释与 changelog 口径矛盾（minor #1）**：`src/config.py` retrieval_fusion_mode 注释写"存量 2 项降级用例按新语义更新断言并注明理由——行为升级非掩盖"，但 changelog §6 与实测均为"**零存量断言改动**"（module-054 方案 A/B 已消解，test_degradation_fix.py 显式 monkeypatch 模式与默认值无关）。注释文本疑似从 module-053 旧注释搬运未更新。建议：把该句改为"存量 2 项降级用例在 module-054 方案 A/B 落地后已消解，零断言改动"。

2. **factcheck_judge.py 顶部 docstring 残留 "15s 超时"（minor #2）**：模块 docstring 降级契约行仍写"模型缺失/加载失败/推理异常/15s 超时"，常量区注释已更新为 20s。建议：docstring 同步为 20s。

3. **停用词扩充的隐性侧效应未在 changelog 注明（minor #3）**：`_kb_terms` 是 L2 确认与 module-049 分诊（模块级 `fts_term_hit`）共用单一来源，停用词扩充同样改变了分诊的 FTS 命中行为（噪声词不再驱动分诊）。方向一致（噪声词本就无判别力）且全量测试通过，但属 L2 修复的连带影响，建议 changelog 补一句说明。

4. **HHEM 预热 task 未持有引用（minor #4）**：`_asyncio.create_task(_warmup_hhem())` 返回值未保存；服务在预热期间关闭时可能出现 "Task was destroyed but it is pending" 告警（fail-soft，无功能影响）。建议：保存引用或加 `_asyncio.shield`/`task.add_done_callback` 兜底。

5. **工作树遗留物：module-033 changelog 未提交追加（minor #5，非本模块改动）**：`specs/module-033-long-term-memory/changelog.md` 有 +47 行"附属发现（6 项跨模块缺陷清单）"，落款 Reviewer 2026-08-08——早于 module-055 的既有未提交内容，非本模块写入。specs/ 不 stage 且本模块不背锅，但建议主会话提交时知悉（或按历史惯例保留工作树状态）。

### 附注（非问题）

- golden_intent 实测 0.98 略低于 module-047 baseline 1.0（2 条 realtime→knowledge 系 LLM 自判、L2 日志证实非本模块所致，方向多检低风险）——如实记录，非掩盖。
- 新增代码量约 470 行（12 文件 +404/-67）在 plan ≤500 行预估内。
- 测试执行耗时 159.96s（HHEM 相关测试含模型加载/mock 路径），与历史模块量级一致。

---

**结论：module-055 通过第一轮审查（pass）。** 5 项 minor 建议不阻塞验收，可随主会话一并处理；test-report.md 移交 Tester 产出。
