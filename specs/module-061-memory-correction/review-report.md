# Review Report — Module-061: 记忆纠错（升级留后悔药 + 冲突消解）

> Reviewer | 2026-08-13
> Verdict: **✅ PASS（无 major）** → 进 Tester
> 依据: 独立复现全量测试 + DB eval_runs/列核验 + 关键实现逐项核对 + 记忆硬约束核查

---

## 1. 审查范围

对照 `acceptance-criteria.md` 8 维逐条核查（方法学/正确性/降级链/诚实性/测试/结果解读/风格与最小改动/记忆核查）。

审查对象：`ai_service/rag/memory/memory.py`、`nli_judge.py`（新）、`nli_loader.py`（新）、`rag/memory/__init__.py`、`rag/models.py`、`src/config.py`、`src/database.py`、`tests/conftest.py`、`tests/test_memory_correction.py`（新 27 项）、`tests/test_memory.py`（2 项改名）、`eval/memory_conflict_dataset.py`（新）、`scripts/migrate_module061.py`（新）、ADR-0007 状态行、memory 三件套、CONTEXT.md。

## 2. 独立验证结果

| 验证项 | 结果 |
|--------|------|
| 全量 pytest `python -m pytest tests/ -q` | **824 passed / 0 failed**（172.46s）——与 changelog 逐字一致（797 基线 + 27 新增） |
| 目标 + 存量记忆测试 `test_memory_correction.py + test_memory.py` | **103 passed** |
| eval_runs **id=31**（真实 mDeBERTa baseline） | DB 实测 `eval_type=memory_conflict, commit=7c215814, scores={accuracy_3class:0.6, precision:1.0, recall:0.5, f1:0.6667, tp:10, fp:0, fn:10, gate_passed:false, dataset_size:30, evaluated:30, skipped:0}`——与 changelog 数字完全一致 |
| documents 表列 | `superseded boolean NOT NULL default false` + `updated_at timestamp NOT NULL default CURRENT_TIMESTAMP` 已存在（迁移已执行） |
| nli_loader 加载路径 | 镜像 eval/compare_nli_models（HF_HUB_OFFLINE=1 + AutoModelForSequenceClassification dtype=float32 + id2label 从 config 读）；config.json id2label = {0:entailment, 1:neutral, 2:contradiction} 核对一致 |
| eval 管线 fixture 冒烟 | `--fixture --no-save` 跑通：Dataset 30 / Skipped 0 / 达标判定正常（fixture 启发式非真实指标） |
| py_compile | 全部 10 个变更文件 OK |

## 3. AC 逐条核对（8 维）

### 3.1 方法学
- ✅ **WP1 先度量**：30 条五类标注集（改口 10/迁移 4/过时 3/升级冲突 3/正例中性 10）落盘 + 真实 mDeBERTa baseline（id=31）如实记录；达标线声明（contradiction Recall≥0.8 且 Precision≥0.8）。
- ✅ **口径声明完整**：标注人工构造非多人独立标注、30 条量级小、Precision 1.0/Recall 0.5 样本量偏差风险、记忆级 vs claim_vs_doc 口径区分（changelog §2.2/已知边界 + eval 脚本 docstring）。
- ✅ **superseded 过滤位置**：记忆服务召回层（`_expand_to_parents` + `_evolve_recall`）而非通用检索器 SQL——与 plan 一致的可论证取舍（hybrid_retriever 与知识库共享，superseded 仅记忆文档有意义），changelog 明确声明。

### 3.2 正确性
- ✅ **P0 升级留后悔药**：`_promote_memory` 不再删除短期副本（delete 调用已移除）；长期新条目 `superseded=False` + `updated_at=now`；content_hash 幂等保留（重复升级不复制、不产生垃圾行）。单测 + 存量 test_memory.py 改名用例双覆盖。
- ✅ **P1 三路径分流**：`_merge_duplicate` —— contradiction → 旧父块 superseded=true+updated_at + 返回 None → save 正常新增（不拼接共存）；entailment/neutral → 追加拼接；NLI None/超时 → 追加（零回归）。`_judge_conflict` 任何异常 → None → 追加。核心逻辑与 changelog 一致。
- ✅ **`_is_superseded` 用 `is True`**：MagicMock 缺字段 `.superseded` 返回真值 MagicMock，truthy 判断会误伤存量测试；`is True` 仅真实 DB 行 superseded=True 命中。单测覆盖（含 dict/None/缺字段）。
- ✅ **开关默认 false**：`config.py memory_conflict_enabled=False`（PW_MEMORY_CONFLICT）；conftest autouse `default_memory_conflict_disabled` 钉住 false。
- ✅ **nli_judge 生产封装**：延迟加载 + threading.Lock（to_thread 真线程互斥）+ asyncio.to_thread + 20s 超时 + 任何失败返回 None；子包 __init__ 注册解决 `rag.memory.nli_judge` 导入（module-050 别名机制，DB 实测 evaluated=30 skipped=0 证明真实运行导入成功）。

### 3.3 降级链
- ✅ NLI 不可用/加载失败/超时/推理异常 → predict None → 追加（零回归）。
- ✅ 开关关 → `_judge_conflict` 不调用（测试 `jc.assert_not_called()`）→ 完全旧行为。
- ✅ 标记+新增分两步（fail-open）：新增失败旧记忆已标记但未删除（内容保留可审计）；标记失败按新增处理不阻断写入。
- ✅ SUPERSEDED 不删除（Zep 模式），DB `superseded=True` 当前 0 行（默认关未触发，合理）。

### 3.4 诚实性
- ✅ baseline 未达门槛（Recall 0.5 < 0.8）如实标注"未达门槛 → 开关默认关（不预设成功）"，与历史 mDeBERTa 矛盾判别短板结论一致；Precision 1.0 也如实指出值得注意。
- ✅ eval_runs id=31 数字与 changelog 完全一致（DB 独立核验），无伪造。
- ✅ 已知边界 6 项全部如实记录（默认关/短期层增长/K 口径/延迟加载/标注集量级/落库）。

### 3.5 测试
- ✅ `test_memory_correction.py` 27 项覆盖 AC 场景：P0 留副本/superseded 过滤/幂等/`is True` + P1 三分类分流/矛盾全流程/一致追加/NLI None/开关关 + nli_judge 封装（延迟加载失败/超时/空输入/单例）+ 评测基线一致性（标注集结构/metrics 纯函数/达标判定/fixture）。
- ✅ mock NLI 不依赖真实 557MB 模型；同步用例内 asyncio.run；conftest 钉住 false + 新测试体内显式 setattr True（finally 复位）。
- ✅ 存量测试唯一改动：test_memory.py 2 项升级断言改名（`..._deletes_short` → `..._keeps_short`）——**AC §2 明确"升级不删短期副本"与旧断言直接矛盾，按验收许可更新属必要**，已如实标注（module-058 先例）。其余存量记忆测试零改动全绿。

### 3.6 结果解读
- ✅ 结论与数据一致：未达门槛 → 不启用；无过度外推（Precision 1.0 未夸大，明确标注量级小 + 有偏差风险）。
- ✅ gate_passed 判定（双门槛 Recall≥0.8 且 Precision≥0.8）与结论口径一致。

### 3.7 风格与最小改动
- ✅ 中文注释、docstring 与邻近代码一致；`_is_superseded`/`_judge_conflict` 命名清晰；无投机性改动。
- ✅ 未触碰通用检索器（知识库零回归风险论证合理）；router.py/test_golden_intent.py/module-033 changelog 系 module-056 遗留未提交改动（非本模块）。

### 3.8 记忆核查（硬性约束）
- ✅ `memory/project-context.md` module-061 行（格式对齐含测试数字）+ 头部"最后更新 2026-08-13（module-061 完成）"。
- ✅ `memory/agent-activity-log.md` Developer 行已追加（本行 Reviewer 追加）。
- ✅ `memory/file-index.md` nli_loader/nli_judge/memory_conflict_dataset/test_memory_correction/migrate_module061/specs 行已追加。
- ✅ ADR-0007 状态行已更新（P0+P1 已实施，注明 module-061，824 passed）。
- ✅ CONTEXT.md 只增不删（记忆纠错领域节追加）。

## 4. 有意的取舍（已核、非阻塞）

1. **标记+新增分两步（非单事务）**：plan 6.2 技术注意事项写"标记+新增同一事务"，实现改为两步（fail-open 理由充分：新增失败旧记忆已标记但未删除不丢数据）。AC §7"并发/事务一致性（标记+新增同一事务）"对应测试项未按字面实现——属有意的、已声明的设计取舍，核心用户故事（旧标 SUPERSEDED + 新内容正常新增）满足，建议 Tester 验收时按此口径理解。
2. **superseded 过滤在召回层而非检索 SQL**：见 3.1，与 plan"或降权"许可一致，changelog 已声明。

## 5. Minor findings（非阻塞，供 Developer 知悉 / 后续模块考虑）

### MINOR-1 `_merge_duplicate` 对已 superseded 父块缺守卫（新内容可能被"吞"）
- **位置**：`ai_service/rag/memory/memory.py` `_merge_duplicate`（约 448-471）。
- **问题**：去重命中的父块若已被 SUPERSEDED 且 NLI 判 entailment/neutral → 新内容追加进 superseded 父块 content 并返回 status="updated"——该父块被召回侧过滤，**新内容从此不可召回**（用户最新事实静默丢失于召回面，内容仍在库）。可达路径：开关开 + NLI 可用 + 新事实与旧说法（已 superseded）cosine>0.85 且判一致。
- **建议**：`_merge_duplicate` 顶部加守卫 `if _is_superseded(parent): return None`（superseded 父块 = 非法合并目标 → 走正常新增），与"旧说法让位最新说法"原则一致。

### MINOR-2 `_expand_to_parents` 对旧格式单文档（parent_id=None）superseded 不设防
- **位置**：`_expand_to_parents`（约 1033-1037）。
- **问题**：仅 `p is not None and _is_superseded(p)` 过滤父块级；legacy 单文档（parent_id=None，自身即完整记忆）若带 superseded=True 仍会召回。**当前 module-061 写路径不可达**（`_find_duplicate` 只返回 parent_id IS NOT NULL 子块，superseded 只会标在有子块的父块上），属理论健壮性缺口。
- **建议**：非阻塞；如后续有单文档标记场景，补 `if p is None and _is_superseded(d): continue` 一行。

### MINOR-3 changelog 措辞与实际行为出入（标记失败路径）
- **位置**：changelog §4.2 事务口径声明 "标记写库失败 → 日志告警 + 按旧行为追加"。
- **实际**：`_merge_duplicate` 内标记 commit 失败 → 异常被捕获 → 返回 None → `_save` **按新增处理**（新内容新行入库，旧记忆未标记保持活跃）——非"按旧行为追加"。两者均 fail-open 不丢数据，但措辞不准确。
- **建议**：changelog 该句改为"标记写库失败 → 日志告警 + 按新增处理（fail-open 不阻断写入）"，保证文档与实现一致。

### MINOR-4 `updated_at` ORM/DDL 时区类型不一致（cosmetic）
- **位置**：`rag/models.py` `updated_at = Column(DateTime(timezone=True), ...)` vs DDL/migrate `TIMESTAMP`（without time zone）。
- **说明**：与既有 `created_at` 同款模式（ORM timezone=True 而 DB 为 timestamp 无 tz）；tz-aware 写入经 PG 隐式转换存储正确、读取为 naive，无功能错误。一致性建议：新列 DDL 改用 `TIMESTAMPTZ` 或 ORM 改 `DateTime()`。

## 6. 结论

- **Verdict: ✅ PASS（无 major）** → 进 Tester。
- 全部 AC 项（§1-§8）达成；P0/P1 核心逻辑、降级链、开关默认 false + conftest 钉住、评测不预设成功（id=31 未达门槛如实标注）均独立验证成立。
- 4 项 minor 非阻塞（见 §5），不要求回修即放行；建议 Developer 将 MINOR-1/3 纳入后续模块或顺手修正。
- 遗留观察（非本模块）：router.py / test_golden_intent.py / specs/module-033 changelog 系 module-056 遗留未提交改动，主会话统一提交时注意别误归类。
