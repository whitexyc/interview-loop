# Changelog — Module-061: 记忆纠错（升级留后悔药 + 冲突消解）

> Developer | 2026-08-13
> 开工前已读 `memory/project-context.md` 全文（module-001~060 清单与迭代状态，避免重复/冲突）✅
> 用户决策（已确认）：范围 = P0（升级留后悔药）+ P1（mDeBERTa NLI 冲突消解 SUPERSEDED）+ 评测闭环。P2 类型化衰减 / P3 冷记忆降权 / P4 反馈闭环留后续模块。

---

## 1. 模块目标与结果

| WP | 内容 | 结果 |
|----|------|------|
| WP1 | 评测闭环：记忆矛盾标注集 + mDeBERTa NLI baseline | ✅ `eval/memory_conflict_dataset.py`（30 条五类标注集 + P/R/F1 + 达标判定）；真实 baseline **Accuracy 0.60 / contradiction Precision 1.0000 / Recall 0.5000 / F1 0.6667**，eval_runs **id=31** 'memory_conflict'——**未达门槛（Recall 0.5 < 0.8），开关保持默认关（不预设成功，数据说话）** |
| WP2 | P0 升级留后悔药 | ✅ `_promote_memory` 升级**不删除短期副本**（后悔药）+ 长期新条目 `superseded=false` + `updated_at=now`；documents 表加两列（init_db 幂等 ALTER + 迁移脚本）；召回侧过滤 superseded（`_expand_to_parents` + `_evolve_recall`） |
| WP3 | P1 冲突消解（写路径） | ✅ `rag/memory/nli_judge.py` 生产封装（延迟加载 + threading.Lock + to_thread + 失败/超时 None 降级）+ `_merge_duplicate` 分流（contradiction → 旧父块 SUPERSEDED + 新内容正常新增 / entailment·neutral → 追加 / NLI None → 追加零回归）；`memory_conflict_enabled`（PW_MEMORY_CONFLICT）默认 false |
| WP4 | 测试 + 文档 + 记忆 | ⏳ 全量 pytest **824 passed / 0 failed**（797 基线 + 27 新增；存量 test_memory.py 2 项升级断言**按验收许可更新**，见 §7）；ADR-0007 状态行 + 记忆三件套 + CONTEXT.md 只增 |

**核心收益**：
1. **升级留后悔药（P0）**：短期→长期升级不再删短期副本（"抄进笔记本不撕草稿纸"）——升级单向不可逆的软肋解除；长期新条目带 superseded=false/updated_at 可审计可回溯。
2. **改口冲突消解（P1）**：语义去重命中后 mDeBERTa NLI 判矛盾 → 旧父块标 SUPERSEDED（**不删除**，Zep 模式）+ 新内容按正常新增入库——"讨厌咖啡\n喜欢咖啡"拼接共存让 LLM 猜哪句是新的软肋解除。
3. **评测驱动启用（不预设成功）**：记忆级矛盾检测 baseline 未达门槛（contradiction Recall 0.5 < 0.8）→ 冲突消解实现保留但**默认关**，与历史 mDeBERTa 矛盾判别短板（module-054/057 kappa<0.7）结论一致、如实标注。

---

## 2. WP1 评测闭环（先度量，用数据决定启用）

### 2.1 新增 `ai_service/eval/memory_conflict_dataset.py`

- **记忆矛盾标注集 `MEMORY_CONFLICT_DATASET`（30 条，五类）**：
  - 改口类 10（"喜欢咖啡"→"讨厌咖啡"、"偏好简洁"→"希望更详细"…）
  - 迁移类 4（"MySQL"→"PostgreSQL"、"Maven"→"Gradle"…）
  - 过时类 3（"Spring Boot 2.x"→"3.x"、"Java 8"→"Java 21"…）
  - 升级冲突类 3（短期层新事实 vs 长期层旧记忆）
  - 正例/中性 10（entailment 5 + neutral 5——**防 Recall 虚高与过度标矛盾**）
- **口径**：样本 = (premise 旧记忆, hypothesis 新事实)，人工三分类 verdict；**记忆级场景（短句/偏好/事件级）比历史 claim_vs_doc 更聚焦**，是否成立以数据说话。
- **达标线（建议值）**：contradiction **Recall≥0.8 且 Precision≥0.8**——漏判（Recall 低）=旧记忆仍拼接共存（无害降级），误判（Precision 低）=正常记忆被标过期（有害），双门槛同等 ≥0.8。
- **指标**：`contradiction_metrics`（P/R/F1 micro + 三分类 accuracy，纯函数可单测）+ `gate_passed` 达标判定。
- **运行**：`--fixture` 关键词启发式（确定性演示）/ 默认真实 mDeBERTa；`--no-save`/`--limit`；`eval_runs` 落库 eval_type='memory_conflict'。

### 2.2 NLI baseline（真实 mDeBERTa，本地 557MB，eval_runs id=31）

| 指标 | 数值 | 判定 |
|------|------|------|
| Accuracy（3 类） | 0.6000 | 参考 |
| Contradiction **Precision** | **1.0000**（tp=10, fp=0） | 达标（无误判） |
| Contradiction **Recall** | **0.5000**（fn=10） | **未达标（漏判一半）** |
| Contradiction F1 | 0.6667 | — |

**结论：未达门槛（contradiction Recall 0.5 < 0.8）→ 冲突消解保留但默认关（PW_MEMORY_CONFLICT=false）**。

**失败模式定位（如实标注）**：mDeBERTa 在记忆级短句场景**判 contradiction 高度精准（0 误判）但只抓得住一半**——10/20 矛盾判 neutral（如"用户不喜欢吃辣"→"用户最近迷上了麻辣火锅"、"用户习惯晚睡"→"改作息十一点睡"），1 条判 entailment（"用网名称呼"→"让叫全名"）。这与历史结论一致：**mDeBERTa 的矛盾判别是核心短板**（module-054 矛盾 11/32 判 neutral、module-057 句级拆解证伪 kappa 0.3754）。记忆级短句场景 Precision 极高（值得注意），但 Recall 不足是启用门槛的硬约束。

**诚实边界**：
1. 标注集为人工构造（非真实用户改口数据），方向性验证；标注由 Developer 完成，非多人独立标注。
2. 30 条量级小：方向性验证非最终结论；达标/未达判定在标注集扩充后应复测。
3. Precision 1.0 与 Recall 0.5 都基于本批 30 条，样本量小有乐观/悲观偏差风险。
4. 结论不预设成功：P1 实现保留但默认关；将来标注集扩充/换模型/微调后复测达标才切 true。

---

## 3. WP2 P0 升级留后悔药

### 3.1 `_promote_memory`（memory.py:712）

**改前**：复制长期（无向量父块 + 有向量子块，content_hash 幂等）→ **删除短期副本**（父块 + 子块）——"抄进笔记本就撕草稿纸"，升级单向不可逆（长期层无 TTL/衰减/淘汰）。

**改后**：复制长期（同上 + `superseded=False` + `updated_at=now`）→ **短期副本【保留】不删除**——"抄进笔记本不撕草稿纸"，后悔药 = 短期层仍可被 30 天硬上限 + 衰减 + 提及刷新（module-046）自然淘汰、长期层新条目可审计可回溯。

- **幂等保留**：长期层已存在同 content_hash 父块 → 不重复复制（不产生垃圾行），短期副本仍保留。
- **docstring/日志同步更新**（"删除短期副本"→"保留短期副本（后悔药）"）。

### 3.2 documents 表加列（`rag/models.py` + `src/database.py` + `scripts/migrate_module061.py`）

- `Document` 加 `superseded`（Boolean，默认 False）+ `updated_at`（DateTime，server_default now）。
- `MEMORY_SUPERSEDED_DDL` + `ensure_memory_superseded_columns()`：init_db 自愈幂等 ALTER（`ADD COLUMN IF NOT EXISTS` + COMMENT，重复启动不报错），对齐 feedback/request_logs 模式；默认值兜底存量行（superseded=false / updated_at=当前时间，零迁移 fail-open）。
- `scripts/migrate_module061.py`：本地开发库 schema 未迁移先决（module-046 经验），查 information_schema 已存在则跳过 + 校验输出。**已对本地库执行**（两列补成功）。

### 3.3 召回/检索侧过滤 superseded

- `_expand_to_parents`：子块命中映射回父块时，父块 `superseded is True` → 跳过（**长期/短期 recall 输出统一过滤**——用户最新说法优先，旧说法不参与召回）。
- `_evolve_recall`：参考文档加载 `by_content` 排除 superseded + 主循环防御性 skip（口径统一）。
- **`_is_superseded` 辅助**：用 `is True` 而非 truthy 判断——测试桩 MagicMock 的 `.superseded` 返回真值 MagicMock，truthy 判断会把全部测试父块误判为 SUPERSEDED；`is True` 仅真实 DB 行 `superseded=True` 才命中（存量测试零漂移）。
- **口径声明**：superseded 过滤在**记忆服务召回层**（`_expand_to_parents`/`_evolve_recall`），不在通用检索器 SQL——`hybrid_retriever` 与知识库检索共享，superseded 仅记忆文档有意义（知识库文档恒 false），不动检索器防知识库回归。

---

## 4. WP3 P1 冲突消解（写路径）

### 4.1 新增 `ai_service/rag/memory/nli_loader.py` + `nli_judge.py`

- **`nli_loader.py`**：mDeBERTa 本地加载器（单一来源）——加载路径**镜像** eval/compare_nli_models（已验证的 transformers 5.x 离线路径：HF_HUB_OFFLINE=1 + AutoTokenizer + AutoModelForSequenceClassification fp32 CPU + id2label 从 config 读），模型目录 `models/mdeberta-nli`（557MB，module-052 下载）；`require_nli_model` 缺文件明确报错。**顶层只 import stdlib，torch 在函数内延迟导入**（包导入零开销）。
- **`nli_judge.py`**：`MemoryNLIJudge` 生产封装（对齐 module-050/051 hhem_loader + factcheck_judge 模式）——延迟加载（首次 predict 才加载 557MB）+ `threading.Lock`（to_thread 真线程互斥，module-027 经验）+ `asyncio.to_thread`（CPU 推理不阻塞事件循环）+ 20s 超时；**任何失败（缺失/加载失败/推理异常/超时）→ `predict` 返回 None（不抛异常），上层降级旧行为**。全局单例 `nli_judge`。
- **导入注册**：`rag/memory/__init__.py` 追加 nli_loader/nli_judge 导入——`rag.memory` 被旧路径别名（rag/__init__ `_OLD_PATHS["memory"]`）覆盖为普通模块后，未在子包 __init__ 导入的子模块无法经子包路径导入（module-050 兼容机制）；两模块顶层零重依赖，包导入零开销。

### 4.2 `_merge_duplicate`（memory.py:388）分流

```
去重命中（cosine>memory_dedup_threshold=0.85）后：
  若 memory_conflict_enabled 且 NLI 可用（_judge_conflict 非 None）：
    verdict = NLI(旧父块content, 新内容)
    contradiction → 旧父块 superseded=true + updated_at=now（不删除，可审计回溯，Zep 模式）
                    → 返回 None → save 按【正常新增】入库新内容（不拼接共存）
    entailment/neutral → 保持现行为（追加拼接 content）
  否则（开关关 / NLI None / 超时）→ 保持现行为（追加，零回归）
```

- **触发点**：去重命中时（写入侧最轻、语义相近=最可能冲突的场景）。extract_facts 全量比对成本高，不做（如实记录边界）。
- **短期层矛盾路径**：不再刷新旧父块提及（mention_count/last_mentioned_at）——旧记忆已 SUPERSEDED。
- **事务口径声明**：superseded 标记与新增**分两步**（`_merge_duplicate` 标记提交 → `save` 正常新增路径插入新内容）——若新增失败，旧记忆已被标记但**未删除**（内容仍保留可审计，不丢数据 fail-open）；标记写库失败 → 日志告警 + 按旧行为追加（fail-open 不阻断写入，AC §5）。
- **`_judge_conflict` 辅助**：复用 nli_judge 单例（函数内延迟导入）；异常/None → 返回 None → 上层走旧行为追加（**保证"NLI 不可用 → 追加"而非"按新增处理"**，严格满足 AC §3 零回归）。
- 去重追加路径同步刷新 `parent.updated_at`（documents.updated_at 语义 = 升级/冲突标记/去重追加时刷新）。

### 4.3 配置开关（`src/config.py`）

- `memory_conflict_enabled: bool = False`（读 `PW_MEMORY_CONFLICT`）——**默认 false = 不预设成功**（评测达标 contradiction Recall/Precision≥0.8 后才切 true，对齐 ADR-0003 L4 / module-052 放行模式）。
- conftest autouse fixture `default_memory_conflict_disabled` 钉住 false（hermetic，存量记忆测试零漂移；新测试显式 setattr True + mock NLI）。

---

## 5. WP4 测试 + 文档 + 记忆

### 5.1 新增 `tests/test_memory_correction.py`（27 项）

| 测试类 | 覆盖 | 项数 |
|--------|------|------|
| TestPromoteKeepsShortCopy | P0 升级保留短期副本 + superseded/updated_at 标记 + 幂等不产生垃圾 + 无 DELETE | 2 |
| TestSupersededRecallFilter | `_expand_to_parents` 过滤 superseded / 保留 active + `_evolve_recall` 忽略 superseded refs | 3 |
| TestIsSuperseded | `is True` 语义（MagicMock 真值不误判） | 1 |
| TestMergeDuplicateConflict | P1 分流：矛盾→SUPERSEDED+None / 短期矛盾不刷新提及 / entailment·neutral 追加 / NLI None 追加 / 开关关完全旧行为+NLI 不调用 | 6 |
| TestSaveConflictFullFlow | save 全流程：去重命中判矛盾 → 旧 SUPERSEDED + 新内容正常新增（不拼接） | 1 |
| TestNLIJudge | 封装：三分类返回 / 推理失败 None / 超时 None / 空输入 None / 延迟加载失败 None / 单例 | 6 |
| TestJudgeConflict | `_judge_conflict`：None/verdict/异常降级 | 3 |
| TestConfig061 / TestConflictDataset / TestDocumentModel | 开关默认 false / 标注集结构五类 + metrics 纯函数 + 达标判定 + fixture | 5 |

- **mock NLI**：全部 `mock.patch` 打桩，不依赖真实 557MB 模型跑全量（对齐 test_memory.py 模式）；同步用例内 asyncio.run。
- **评测基线一致性**：标注集结构校验（≥20/矛盾≥15/正例中性对照/五类场景）+ `contradiction_metrics` 纯函数 + `gate_passed` 达标判定 + `fixture_judge` 确定性——**不加载模型即可回归评测管线**。

### 5.2 全量 pytest

- **824 passed / 0 failed**（797 基线 + 27 新增）。
- **存量 test_memory.py 2 项按验收许可更新**（module-058 先例）：`test_promotes_to_long_and_deletes_short` → `test_promotes_to_long_and_keeps_short`、`test_promotion_idempotent_skips_duplicate_copy` → `test_promotion_idempotent_keeps_short_copy`——**AC §2 明确规定"升级到长期后不删除短期副本"（后悔药）**，旧断言"DELETE IN (1,2,3)"与新版行为直接矛盾，必须同步；改后断言"无 DELETE + 短期副本保留 + 长期条目 superseded=False/updated_at"。**这是本模块唯一存量测试改动，已如实标注**（其余存量记忆测试 module-033/034/035/046 相关零改动，全绿）。
- py_compile 全部变更文件 OK；本地库迁移脚本执行 OK（superseded/updated_at 列补齐）。

---

## 6. 关键实现决策与取舍

| 决策点 | 选择 | 理由 |
|--------|------|------|
| P0 是否受开关控制 | **不受控（无条件启用）** | AC §2/plan 风险表将"升级不删短期副本"视为确定性行为变更；"后悔药"是安全的（短期层自然淘汰被取代副本），无需评测门槛 |
| superseded 过滤位置 | 记忆服务召回层（`_expand_to_parents`/`_evolve_recall`），**非检索器 SQL** | `hybrid_retriever` 与知识库共享，superseded 仅记忆文档有意义；动检索器风险高收益低 |
| `_is_superseded` 用 `is True` | 显式布尔判断 | 测试桩 MagicMock `.superseded` 返回真值 MagicMock，truthy 判断误伤全部存量测试 |
| 标记+新增事务 | 分两步（非单事务） | `_merge_duplicate` 标记提交 → save 正常新增；新增失败旧记忆已标记但未删除（内容保留不丢数据 fail-open） |
| NLI 触发点 | 仅去重命中（写路径最轻） | extract_facts 全量比对成本高，不做（如实记录边界） |
| eval 脚本 import 生产封装 | `rag.memory.nli_judge` 单例 | 单一来源 + 冒烟生产封装路径 |
| 新模块 import 注册 | 子包 __init__ 追加 | module-050 兼容机制（rag.memory 别名覆盖为普通模块） |

---

## 7. 已知边界（如实记录）

1. **NLI 冲突消解默认关**：baseline 未达门槛（contradiction Recall 0.5 < 0.8）→ `PW_MEMORY_CONFLICT=false` 完全旧行为（去重命中 → 追加拼接）。将来标注集扩充 / 换更强中文 NLI / 微调后复测达标才切 true。
2. **P0 升级保留短期副本 → 短期层条数增长**：被取代副本不会被立即清理，但短期层有 30 天硬上限 + 衰减 + 提及刷新（module-046）自然淘汰；如实记录口径（plan 风险表）。
3. **superseded 过滤的 K 口径**：`_absolute_cosine_avg`/`_dynamic_k` 在 `_expand_to_parents` 过滤前计算（含 superseded 候选）——superseded 记忆不参与输出，但可能轻微影响 dynamic_k 档位（更宽松，非数据丢失）。
4. **nli_judge 延迟加载 557MB**：首次写入路径若开启冲突消解会触发模型加载（秒级），失败自动降级旧行为不阻塞写入主链路。
5. **标注集 30 条人工构造**：方向性验证非最终结论；Precision 1.0/Recall 0.5 有样本量偏差风险。
6. **eval_runs id=31**：'memory_conflict' baseline 已落库（git_commit=7c215814，config 快照含 memory_conflict_enabled=false）。

---

## 8. 面试口径更新点

> **记忆纠错：升级留后悔药 + 写路径矛盾消解 SUPERSEDED，复用 mDeBERTa 零新依赖，评测驱动启用。**

- **P0 升级留后悔药**：短期→长期升级不再删短期副本（"抄进笔记本不撕草稿纸"），长期新条目带 superseded=false/updated_at 可审计可回溯——升级单向不可逆软肋解除。
- **P1 写路径冲突消解**：去重命中后 mDeBERTa NLI 判新事实 vs 旧记忆矛盾 → 旧父块标 SUPERSEDED（不删除，Zep 模式）+ 新内容按正常新增——"讨厌咖啡\n喜欢咖啡"拼接共存软肋解除。
- **评测驱动启用**：记忆矛盾标注集 30 条五类 + NLI baseline（contradiction Precision 1.0 但 Recall 0.5 未达门槛）→ 不预设成功，默认关。
- **复用零新依赖**：mDeBERTa（module-052 已下载）+ hhem_loader/factcheck_judge 模式（module-050/051 已验证）。
