# Module-061 任务简报：记忆纠错（ADR-0007 P0+P1：升级留后悔药 + 冲突消解）

> 自包含执行简报。接手方不需要额外对话上下文，按步骤执行即可。所有"已知事实"均已确认（代码已读），无需重新调研。
> **用户决策（已确认）**：范围 = **P0（升级留后悔药）+ P1（mDeBERTa NLI 冲突消解 SUPERSEDED）+ 评测闭环**。P2 类型化衰减/P3 冷记忆降权/P4 反馈闭环留后续模块。

## 一、任务背景

**项目**：Agentic RAG 技术文档知识库（`.claude/worktrees/m8-knowledge-panel/ai_service`，FastAPI + asyncpg + pgvector + Apache AGE）。

**要解决的问题（ADR-0007 两个真实软肋，代码实测）**：

| 软肋 | 代码证据 | 后果 |
|---|---|---|
| 升级单向不可逆 | `_promote_memory`（memory.py:712）：复制到长期层后**删除短期副本**；长期层无 TTL/衰减/淘汰 | 抄进"笔记本"就改不回来 |
| 去重是"追加"不是"替换" | `_merge_duplicate`（memory.py:388）：`parent.content = f"{parent.content}\n{content}"` | 用户改口 → 新旧说法**拼接共存**（"讨厌咖啡\n喜欢咖啡"），召回时 LLM 猜哪句是新的 |

**目标**：① P0 升级留后悔药（升级不删短期副本 + 长期层 superseded/updated_at 标记，可审计可回溯）；② P1 写路径冲突消解（新事实与既有记忆 mDeBERTa NLI 判矛盾 → 旧条目标 SUPERSEDED **不删除** + 新条目标存）；③ 记忆评测闭环（矛盾标注集 + NLI 判定准确率 baseline）——用数据决定启用与否，避免"改坏记忆"。

## 二、已知事实（勿重新调查）

### 2.1 记忆代码结构

- `rag/memory/memory.py`：`MemoryManager`——`_promote_memory`（**712**，短期→长期升级，复制后删短期副本，content_hash 幂等）、`_merge_duplicate`（**388**，去重命中追加拼接 content，短期层触发提及刷新 mention_count/last_mentioned_at）、`_find_duplicate`（约 360-386，cosine>settings.memory_dedup_threshold 命中）、`_evolve_recall`（**585**，召回侧进化加权）
- `rag/memory/memory_extractor.py`：`extract_facts`（**99**，LLM 提取记忆事实，importance≥0.6 过滤）
- `rag/memory/session_memory.py`：会话记忆
- 三层记忆**全部复用 documents 表 + source 前缀隔离**（长期 `memory:<identity>:` / 短期 `memory:<identity>:short:` / 会话 `memory:<identity>:session:`），无独立表

### 2.2 mDeBERTa NLI 现状

- 模型已部署：`ai_service/models/mdeberta-nli/`（module-052 下载，557MB，中文多语言 NLI 三分类 entailment/neutral/contradiction）
- 推理代码在 **eval/retest_nli.py / eval/compare_nli_models.py / tests/test_nli_improve.py / tests/test_compare_nli.py**（评测/测试脚本，非生产封装）——P1 需**提炼为生产封装**（对齐 module-050 hhem_loader/hhem_judge 共享加载器 + 延迟加载 + threading.Lock + to_thread + 失败返回 None 降级模式）
- 历史结论（诚实标注）：module-052 kappa 0.4711 > HHEM、module-054 复测 kappa 0.5167 < 0.7 未达放行门槛 → **降级双轨**（NLI 只做矛盾扫描不替换 HHEM 主裁判）；module-057 句级拆解改进证伪（kappa 0.3754 < 基线）。**矛盾判别是短板**（internal 矛盾 11/32 判 neutral）——P1 做记忆级矛盾检测（短句、偏好/事件级）是比 claim_vs_doc 更聚焦的场景，须以评测数据验证，不预设成功

### 2.3 documents 表结构相关

- Document 模型字段：id/title/content/source/embedding/parent_id/content_hash/search_tokens/mention_count/last_mentioned_at/created_at 等（module-046 短期进化加的字段）
- **P0 需加 superseded/updated_at 标记**：documents 表**加列**（module-046 有"本地开发库 schema 未迁移需 ALTER TABLE"经验——用 init_db 幂等 ALTER 或迁移脚本，对齐项目模式，见 plan）
- 召回侧 `_evolve_recall`（585）与检索侧需**过滤 superseded**（或降权），否则标记无意义

### 2.4 配置与开关模式

- `src/config.py` settings 字段 + `PW_` 环境变量；conftest autouse 钉住测试环境开关（对齐 module-056/058/060 成熟模式）
- **启用策略**（对齐 ADR-0003 L4 / module-052 放行）：新开关默认 **false**，评测达标（矛盾判定准确率/召回达标线）后才切 true——**不预设成功，数据说话**

### 2.5 测试基线

- 后端全量 **797 passed / 0 failed**（module-060 收口后，Docker PG/Redis 就绪）
- 前端与后端并存（本模块纯后端，不涉及前端）

## 三、任务步骤（按序，每步有通过标准）

### WP1 评测闭环（先度量，用数据决定方案）

- 新建 `eval/memory_conflict_dataset.py`：构造**记忆场景矛盾标注集**（20-30 条，对齐 build_contradiction_dataset 基建）——改口类（"喜欢咖啡"→"讨厌咖啡"）、迁移类（"住北京"→"搬去上海"）、过时类（"用 V1"→"升级 V2"）、升级冲突类（短期升级与长期层矛盾）、正例（一致/中性）
- mDeBERTa NLI 判定准确率 baseline：同批样本跑现有 NLI（retest_nli.py 逻辑），报 P/R/F1
- **通过标准**：标注集落盘 + baseline 数字如实记录（达标线建议：contradiction Recall≥0.8 且 Precision≥0.8 才启用；不达标如实标注，P1 实现仍保留但默认关）

### WP2 P0 升级留后悔药

- `_promote_memory`（memory.py:712）：**升级时不删除短期副本**（改为短期副本转"已升级"标记或保留）；长期层写入 `superseded=false` + `updated_at=now`
- documents 表加 `superseded BOOLEAN` + `updated_at TIMESTAMP` 列（init_db 幂等 ALTER，对齐项目模式；本地库需 ALTER TABLE 先决）
- 召回/检索侧过滤 superseded（`_evolve_recall` 与检索查询）
- **通过标准**：升级后短期副本仍在（后悔药）+ 长期新条目带 superseded=false/updated_at；重复升级幂等不产生垃圾；全量回归

### WP3 P1 冲突消解（写路径）

- 新建生产封装 `rag/memory/nli_judge.py`（或 rag/retrieval/ 对齐 factcheck_judge 位置）：mDeBERTa 三分类（entailment/neutral/contradiction），延迟加载 + threading.Lock + to_thread + 失败返回 None（降级走旧行为）
- `_merge_duplicate`（memory.py:388）**分流**：去重命中（cosine>阈值）后 → NLI 判冲突：
  - **contradiction** → 旧父块标 superseded=true + updated_at + 新内容按正常新增入库（不拼接共存）
  - **entailment/neutral** → 保持现行为（追加拼接）
  - NLI 不可用（None）→ 保持现行为（追加，降级零回归）
- **触发点设计**：去重命中时（写入侧最轻、语义相近=最可能冲突的场景）。extract_facts 全量比对成本高，不做（如实记录边界）
- **通过标准**：矛盾 → SUPERSEDED+新增（旧记忆不删、可回溯）；一致 → 追加；NLI 降级 → 旧行为；开关 false → 完全旧行为零回归

### WP4 测试 + 文档 + 记忆

- `tests/test_memory_correction.py`（新）：P0（升级留副本/superseded 标记/幂等/召回过滤）+ P1（NLI 封装三分类/冲突分流矛盾/一致追加/降级/开关）+ 评测基线一致性抽查
- conftest autouse 钉住新开关 false
- 文档：changelog/review-report/test-report + **ADR-0007 状态行更新（P0+P1 已实施）** + memory 三件套 + CONTEXT 只增
- **通过标准**：全量 797+新增全绿；记忆三文件硬性约束满足

## 四、纪律项（违反 = 返工）

1. **不预设成功**：新开关默认 false；评测不达标如实标注"改进未达门槛"，P1 保留但默认关（对齐 mDeBERTa 矛盾判别历史）
2. **SUPERSEDED 不删除**：旧记忆标记后仍保留（可审计可回溯，Zep 模式）；不得硬删用户记忆
3. **存量测试不改**：新开关 conftest 钉住 false；存量记忆测试（module-033/034/035/046 相关）零改动
4. **NLI 降级零回归**：NLI 不可用/超时 → 返回 None → 走旧行为（追加拼接），不抛异常不影响写入主链路
5. **诚实**：基线数字（797/0）、评测 baseline、达标线判定均如实记录
6. **ALERT：docs 表加列需先跑 ALTER**（本地库 schema 未迁移先决，module-046 经验）；init_db 幂等

## 五、交付物

1. WP1 记忆矛盾标注集 + NLI baseline 数字
2. WP2 P0 实现（升级留副本 + superseded/updated_at 标记 + 召回过滤）
3. WP3 P1 实现（nli_judge 生产封装 + _merge_duplicate 冲突分流）
4. WP4 测试（797+N 全绿）+ 文档 + memory 三件套 + ADR-0007 状态更新
5. 面试口径更新点（记忆纠错：升级留后悔药 + 写路径矛盾消解 SUPERSEDED，复用 mDeBERTa 零新依赖，评测驱动启用）
