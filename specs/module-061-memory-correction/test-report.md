# Test Report — Module-061: 记忆纠错（升级留后悔药 + 冲突消解）

> Tester | 2026-08-13
> 结论：**验收通过（全部 AC 通过，0 阻塞）**——全量 pytest 824/0 全绿 + 评测基线数字与 DB/文档三方一致 + 关键实现逐项核对 + 记忆硬约束落实。

---

## 1. 测试环境与方法

- 后端目录：`ai_service/`（git worktree `m8-knowledge-panel`）
- 全量：`python -m pytest tests/ -q`
- 冒烟：`python -m eval.memory_conflict_dataset --fixture --no-save`（避免重复落库）+ eval_runs id=31 DB 实查
- 真实模型冒烟：`nli_judge.predict` 生产封装真实加载 557MB mDeBERTa 三对验证
- DB：本地开发库（documents 表已补 superseded/updated_at 列）

## 2. 全量测试结果

| 项 | 数值 |
|----|------|
| 全量 pytest `tests/ -q` | **824 passed / 0 failed**（195s，43 个既有 warning 与模块无关） |
| 目标 + 存量记忆测试 `test_memory_correction.py + test_memory.py` | **103 passed** |
| 新增 test_memory_correction.py | 27 项（TestPromoteKeepsShortCopy 2 / TestSupersededRecallFilter 3 / TestIsSuperseded 1 / TestMergeDuplicateConflict 6 / TestSaveConflictFullFlow 1 / TestNLIJudge 6 / TestJudgeConflict 3 / TestConfig061 1 / TestConflictDataset 4） |
| 与 changelog 一致性 | 824/0 = 797 基线 + 27 新增，逐字一致 |

**存量测试零改动**：除 test_memory.py 2 项升级断言按验收许可改名（`..._deletes_short`→`..._keeps_short`、`..._skips_duplicate_copy`→`..._keeps_short_copy`，实查 line 1352/1383）——**AC §2 明确"升级到长期后不删除短期副本"，旧断言与新版行为直接矛盾，更新属必要**（module-058 先例，已如实标注）。其余存量记忆测试零改动全绿。

## 3. 冒烟复跑与数字一致性

| 验证项 | 结果 |
|--------|------|
| eval `--fixture --no-save` | Dataset 30 / Evaluated 30 / Skipped 0；达标判定管线正常（fixture 为关键词启发式，非真实指标） |
| **eval_runs id=31**（真实 mDeBERTa baseline）DB 实查 | `accuracy_3class=0.6, precision=1.0, recall=0.5, f1=0.6667, tp=10, fp=0, fn=10, gate_passed=false, dataset_size=30, evaluated=30, skipped=0, commit=7c215814`——与 changelog §2.2 **逐位一致** |
| 达标判定 | contradiction Recall 0.5 < 0.8 → **未达门槛** → 开关默认关（不预设成功，数据说话）——与 ADR-0007 状态行 / review-report / changelog 一致 |
| 真实模型生产封装冒烟 | `nli_judge.predict("喜欢美式咖啡…","讨厌咖啡…")` → **contradiction**（正确）；`("喜欢美式咖啡","喜欢咖啡")` → **entailment**（正确）；`("","")` → **None**（降级契约成立）——真实加载 557MB 权重成功，生产封装端到端可用 |
| documents 表列 DB 实查 | `superseded boolean NOT NULL default false` + `updated_at timestamp NOT NULL default CURRENT_TIMESTAMP` 已存在（迁移已执行，信息表实查） |

## 4. 实现抽查（与 changelog 一致性）

### 4.1 P0 升级留后悔药（`_promote_memory`，memory.py:788）
- **不删除短期副本**：`memory.py` 全局 grep `.delete(` **0 处残留**——升级路径不再删短期副本（"抄进笔记本不撕草稿纸"）。
- 长期新条目带 `superseded=False` + `updated_at=now`（父块/子块/旧格式单文档三路径，line 836-857）。
- 幂等保留：长期层同 content_hash 父块存在 → 不重复复制（line 832 dup 分支）。
- 升级失败降级：异常捕获日志告警不丢短期数据（line 866-867）。

### 4.2 superseded 过滤（召回层统一口径）
- `_expand_to_parents`（line 1036）：`if p is not None and _is_superseded(p): continue`。
- `_evolve_recall`（line 706/720）：参考文档加载排除 superseded + 主循环防御性 skip。
- `_is_superseded`（line 108）：`getattr(doc, "superseded", False) is True`——MagicMock-safe（单测 TestIsSuperseded 覆盖）。
- **口径声明**：过滤在**记忆服务召回层**而非通用检索器 SQL——`hybrid_retriever` 与知识库共享，superseded 仅记忆文档有意义（知识库恒 false），不动检索器防知识库回归（有意取舍，changelog §3.3 / review §3.1 已声明）。

### 4.3 P1 三路径分流（`_merge_duplicate`，memory.py:405）
- `settings.memory_conflict_enabled` 且 `_judge_conflict` 判 **contradiction** → 旧父块 `superseded=True` + `updated_at=now`，commit 后返回 None → save 按**正常新增**入库（不拼接共存），短期层不刷新提及（line 449-460）。
- **entailment/neutral** → 保持追加拼接（line 462-471）。
- **NLI 不可用（None）/开关关** → 追加（零回归）。
- `_judge_conflict`（line 476）：任何异常 → None → 追加。
- 去重追加路径刷新 `parent.updated_at`（line 468）。
- 返回结构不变 `{"id","title","status":"updated"}` 或 None（AC §6）。

### 4.4 生产封装与开关
- `nli_judge.py`：MemoryNLIJudge 延迟加载（首次 predict 才加载）+ `threading.Lock` + `asyncio.to_thread` + 20s 超时 + 任何失败返回 None（不抛异常）+ 全局单例 `nli_judge`——对齐 factcheck_judge 模式。
- `nli_loader.py`：镜像 eval compare_nli_models 已验证路径（HF_HUB_OFFLINE + AutoModelForSequenceClassification fp32 + id2label 从 config），顶层零重依赖。
- 子包 `__init__.py`：nli_loader/nli_judge 已注册（module-050 别名兼容机制）。
- `src/config.py:129`：`memory_conflict_enabled: bool = False`（env_prefix `PW_` → `PW_MEMORY_CONFLICT` 默认 false）。
- `tests/conftest.py:88`：`@pytest.fixture(autouse=True) default_memory_conflict_disabled` 钉住 false（hermetic，存量测试零漂移）。
- DB 迁移：`MEMORY_SUPERSEDED_DDL` + `ensure_memory_superseded_columns()` init_db 幂等 ALTER（database.py:140-168）+ `scripts/migrate_module061.py` 幂等查列跳过（已执行）。

## 5. AC 逐条对照

| AC 项 | 判定 | 依据 |
|-------|------|------|
| §1-1 eval/memory_conflict_dataset.py（30 条五类标注集） | ✅ 通过 | 实读脚本：改口 10/迁移 4/过时 3/升级冲突 3/正例 5/中性 5 = 30 条，结构校验（≥20/矛盾≥15/正例中性对照）在 eval 单测覆盖 |
| §1-2 NLI baseline 数字如实记录（P/R/F1 三口径） | ✅ 通过 | eval_runs id=31 DB 实查 accuracy 0.6 / P 1.0 / R 0.5 / F1 0.6667，与 changelog 逐位一致 |
| §1-3 达标线声明 + 未达门槛如实标注 + 开关默认关 | ✅ 通过 | GATE 双门槛 Recall≥0.8 且 Precision≥0.8（changelog §2.2）；Recall 0.5<0.8 → `gate_passed=false` → 开关默认 false（不预设成功） |
| §2-1 _promote_memory 不删短期副本 + superseded=false/updated_at=now | ✅ 通过 | memory.py grep 0 delete 残留；长期三路径带 superseded=False/updated_at=now；实查 DB 列默认 false/now |
| §2-2 Document 加字段 + init_db 幂等 ALTER | ✅ 通过 | models.py:57-60 superseded/updated_at；database.py MEMORY_SUPERSEDED_DDL + ensure 幂等；DB 实查两列在 |
| §2-3 重复升级幂等（content_hash 不产生垃圾） | ✅ 通过 | line 832 dup 分支 + 单测 test_promotion_idempotent_keeps_short_copy |
| §2-4 召回/检索侧过滤 superseded | ✅ 通过 | `_expand_to_parents` + `_evolve_recall` 双路过滤（召回层统一口径，检索器 SQL 不动——有意取舍已声明，superseded 仅记忆文档有意义） |
| §2-5 升级失败降级不丢数据 | ✅ 通过 | 异常捕获日志告警，短期数据保留（"先复制后删除"→本次不删除更安全） |
| §3-1 nli_judge 生产封装（延迟加载+Lock+to_thread+超时/异常→None） | ✅ 通过 | 实读 nli_judge.py 全量（line 1-98）+ 真实模型冒烟三对验证 + 单测 TestNLIJudge 6 项 |
| §3-2 _merge_duplicate contradiction → SUPERSEDED + 新增不拼接 | ✅ 通过 | line 449-460 + 单测 test_contradiction_marks_superseded_and_returns_none / test_conflict_saves_new_as_separate_memory |
| §3-3 entailment/neutral → 追加 | ✅ 通过 | line 462-471 + 单测 test_entailment_appends_like_before / test_neutral_appends_like_before |
| §3-4 NLI 不可用/超时 → 追加零回归 | ✅ 通过 | _judge_conflict 异常→None + 单测 test_nli_none_degrades_to_append / test_predict_timeout_returns_none |
| §3-5 PW_MEMORY_CONFLICT 默认 false；false 完全旧行为 | ✅ 通过 | config.py:129 默认 false（PW_ 前缀）+ conftest autouse 钉住 false + 单测 test_switch_off_is_fully_old_behavior（含 `jc.assert_not_called()`） |
| §4-1 test_memory_correction.py 新（P0+P1+评测基线一致性） | ✅ 通过 | 27 项实跑全绿（103 含存量 memory 76） |
| §4-2 conftest autouse 钉住 false；新测试显式开 true | ✅ 通过 | conftest.py:88 `@pytest.fixture(autouse=True)`；test_memory_correction.py:359 体内 setattr True（finally 复位） |
| §4-3 ADR-0007 状态行更新 | ✅ 通过 | adr 0007 line 3 实读：P0+P1 已实施（module-061, 2026-08-13, 824 passed） |
| §4-4 面试口径更新点落盘 | ✅ 通过 | changelog §8 记忆纠错三句口径 |
| §5-1 NLI 不可用/失败/超时 → None → 追加 | ✅ 通过 | nli_judge 失败返回 None（不抛）+ _judge_conflict 异常→None + 单测覆盖 |
| §5-2 SUPERSEDED 标记写库失败 → 日志告警 + fail-open | ✅ 通过 | _merge_duplicate 异常捕获 → 日志告警 → 返回 None（标记失败实际按新增处理，均 fail-open 不丢数据；review MINOR-3 措辞已记录，行为正确） |
| §5-3 SUPERSEDED 不删除用户记忆 | ✅ 通过 | memory.py 0 delete 残留；仅 superseded=True 标记（Zep 模式） |
| §5-4 PW_MEMORY_CONFLICT=false → 与 module-046 完全一致 | ✅ 通过 | 开关 false 时 `_merge_duplicate` 完全旧路径（追加拼接）；conftest 钉住 + 单测零回归 |
| §5-5 全量 pytest 797+N 全绿 | ✅ 通过 | **824 passed / 0 failed** |
| §6-1 三层记忆存储结构不变 | ✅ 通过 | 仍 documents 表 + source 前缀隔离，无新表 |
| §6-2 无新 HTTP 端点；_merge_duplicate 返回结构不变 | ✅ 通过 | 纯内部逻辑改造；返回 `{"id","title","status"}` 或 None 不变 |
| §6-3 documents 加列增量 + init_db 幂等 | ✅ 通过 | ADD COLUMN IF NOT EXISTS + 默认值兜底存量行；重复启动不报错 |
| §6-4 superseded 过滤仅在标记存在时生效 | ✅ 通过 | `is True` 判断，存量行 superseded=false 不受影响（单测 TestIsSuperseded + TestExpandToParentsKeepsActiveParent） |
| §7-1 test_memory_correction.py 覆盖 AC 场景 | ✅ 通过 | 27 项覆盖：P0 留副本/标记/幂等/过滤 + P1 三分类/矛盾分流/一致追加/None 降级/开关关 + 评测基线一致性 |
| §7-2 mock NLI 不依赖真实模型；并发/事务一致性 | ✅ 通过 | 全部 mock.patch 打桩（单测 103 passed 无真实模型）；标记+新增分两步为**有意的、已声明的设计取舍**（review §4.1：新增失败旧记忆已标记但未删除不丢数据 fail-open） |
| §7-3 存量记忆测试零改动全绿 | ✅ 通过 | 除 2 项按 AC §2 验收许可改名（与新版行为直接矛盾，module-058 先例，已如实标注）外全部零改动全绿 |
| §7-4 全量 797+N 全绿（不改存量测试掩盖） | ✅ 通过 | 824/0；唯一存量改动是 AC §2 强制的语义同步，非掩盖 |
| §8-1 changelog/review/test-report（含 baseline 数字+达标判定+降级声明+口径变化） | ✅ 通过 | 三文档齐全，数字一致 |
| §8-2 project-context.md module-061 行 + 头部日期 | ✅ 通过 | 模块清单 line 78 module-061 行（含 824/0 + baseline 数字）+ 头部"最后更新 2026-08-13（module-061 完成）" |
| §8-3 agent-activity-log.md Dev/Rev/Test 三行 | ✅ 通过 | Dev（line 173）+ Rev（line 174）已存在；Test 本行追加（见 §7） |
| §8-4 file-index.md 新文件行 | ✅ 通过 | line 101-106（nli_loader/nli_judge/memory_conflict_dataset/test_memory_correction/migrate_module061/specs）+ line 153 模块产出行 |
| §8-5 ADR-0007 状态行更新 | ✅ 通过 | adr line 3 实读 |
| §8-6 CONTEXT.md 只增不删 | ✅ 通过 | 实读 CONTEXT.md line 199-203 记忆纠错领域节（SUPERSEDED/升级留后悔药/写路径冲突消解） |
| §8-7 开工前必读 project-context.md | ✅ 通过 | changelog 头注明已读全文 |

## 6. Reviewer minor 复核（非阻塞）

| Minor | 说明 | Tester 复核 |
|-------|------|-------------|
| MINOR-1 | `_merge_duplicate` 对已 superseded 父块缺守卫（开关开时理论可达，新内容可能被吞） | 开关默认关 + NLI 达标后才开，当前不可达；逻辑真实存在，建议后续模块补 `if _is_superseded(parent): return None`——非阻塞 |
| MINOR-2 | `_expand_to_parents` legacy 单文档（parent_id=None）superseded 不设防 | 当前写路径不可达（superseded 只标在有子块的父块上），理论健壮性——非阻塞 |
| MINOR-3 | changelog "标记写库失败→按旧行为追加" 与实际（→按新增）出入 | 行为正确（均 fail-open 不丢数据），措辞建议修正——非阻塞 |
| MINOR-4 | updated_at ORM timezone=True vs DDL TIMESTAMP 无 tz | 与既有 created_at 同款模式，无功能错误——非阻塞 |

## 7. 记忆核查结论（硬性约束）

- ✅ `memory/project-context.md`：module-061 行存在（格式对齐含测试数字）+ 头部日期 2026-08-13。
- ✅ `memory/agent-activity-log.md`：Developer 行 + Reviewer 行已存在；Tester 验收行本报告同时追加。
- ✅ `memory/file-index.md`：6 条新文件行 + 模块产出行已追加。
- ✅ ADR-0007 状态行 + CONTEXT.md 只增（记忆纠错领域节）。
- 缺项 = **0**。

## 8. 结论

**验收通过（0 阻塞）**。全量 pytest **824/0 全绿**（797 基线 + 27 新增）；评测 baseline（eval_runs id=31）DB/文档/changelog 三方数字一致且如实标注未达门槛（Recall 0.5<0.8）→ 开关默认关（不预设成功）；P0 升级留后悔药（不删短期副本 + superseded/updated_at + 召回过滤）与 P1 三路径分流（矛盾→SUPERSEDED+新增 / 一致→追加 / 降级→旧行为）关键实现与 changelog 逐项一致；降级链（NLI None/开关关 → 完全旧行为零回归）与 SUPERSEDED 不删除（grep 0 delete）验证成立；真实模型生产封装冒烟（contradiction/entailment/None 三对）通过；记忆三件套 + ADR + CONTEXT 硬约束全落实。
