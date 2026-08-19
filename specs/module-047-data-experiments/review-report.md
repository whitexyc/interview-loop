# Review Report — Module-047 数据实验批（真实 baseline + 阈值校准 + golden 扩样本 + 图谱消融）

> Reviewer | 2026-08-10 | 依据 plan.md / acceptance-criteria.md / changelog.md
> 结论：**APPROVED（通过）** — 无 critical / major，4 项 minor（均已在 changelog/issues_known 如实披露，不阻塞验收）

---

## 1. 红线核查（全部通过）

| 红线 | 核查方式 | 结果 |
|------|----------|------|
| ① 只动 plan 3.1 列出的文件 | `git status` + `git diff` 核查：工作树改动 = `eval/golden.json`（数据，plan 3.1 允许）+ `tests/test_golden_retrieval.py`（见 §5 说明）+ 新文件 `eval/threshold_scan.py` / `tests/test_threshold_scan.py`（plan 3.1 新建）；`eval/golden_intent.py` / `eval/golden_sufficiency.py` 零改动 | ✅ 通过（1 处必须的测试适配，有据可查） |
| ② 数字真实性 | 全部实测数字逐一与 `.ua/` 运行日志 + DB `eval_runs` + 缓存复跑交叉核对，见 §2 | ✅ 通过，无一编造；WP4 如实标注"待环境" |
| ③ 不运行 git commit | `git log` HEAD 仍为 2eac844（module-046 提交），工作树无新提交 | ✅ 通过 |
| ④ 全量 pytest 503 全绿保持 | Reviewer 独立复跑 `python -m pytest tests/ -q`：**525 passed / 0 failed**（5 预存 warnings），与 `m047_full_test.log`（525 passed）一致 | ✅ 通过（503 基线 + 22 新增，零回归） |

## 2. 数字真实性核查（全部交叉验证，无编造）

### WP1 真实 baseline

| 声明 | 日志核对（`.ua/m047_golden_intent.log` / `m047_golden_sufficiency.log`） | DB 核对（eval_runs） | 结论 |
|------|------|------|------|
| intent Accuracy 1.0000（100/100，skipped 0，混淆矩阵全对角 30/50/20） | ✅ 日志逐行一致（含 100 次真实 DeepSeek 调用记录、confidence min 0.75/max 1.00） | ✅ id=11，accuracy=1.0，100/100/0，git_commit=2eac844c | 一致 |
| sufficiency Accuracy 1.0000 / insufficient Recall 1.0000（100/100，skipped 0） | ✅ 日志逐行一致（100 次真实 LLM 反思调用） | ✅ id=12，accuracy=1.0，insufficient_recall=1.0 | 一致 |

### WP2 阈值扫描（Reviewer 用 `python -m eval.threshold_scan` 从缓存复跑，零 LLM 调用，逐行重现）

- **L2 触发扫描**：t=0.20~0.70 全 TP=0/FP=0/FN=2（final_acc 0.98）；t=0.75/0.80 TP=1/FP=1/FN=1（F1=0.5，final_acc 0.98）——与 changelog §3.1 表完全一致。
- **首轮采样**（`m047_threshold_scan.log`）：应触发样本 0（FN 全阈值 0，final_acc 0.99）——changelog 的"0→2 LLM 非确定性"记录属实。
- **两轮 confidence min 均 0.700**（日志行 `n=100 min=0.700`）——changelog 声明属实。
- **硬闸门扫描**：t=0.35 起 6/0/44 → 0.40 20/0/30 → 0.45 37/0/13 → 0.50 46/1/4 → 0.55 49/1/1 → 0.60 50/3/0；P/R/F1/Accuracy 手工复核（如 0.55 行 P=49/50=0.98、R=49/50=0.98、F1=0.98；0.60 行 P=50/53=0.9434、R=1.0）全部自洽。
- **余弦分布**：充分类 n=50 min 0.490/median 0.714/max 0.807；不充分类 min 0.322/median 0.422/max 0.550——与日志、缓存复跑完全一致。
- **生产常量对齐**：`agent/router.py:54` `_L2_CONFIDENCE_THRESHOLD=0.5`、`agent/reflector.py:45` `_SUFFICIENCY_MIN_ABS_COSINE=0.4` 与扫描脚本经验值断言（test_empirical_values_are_current_production）一致。
- **L2 逻辑对齐**：`threshold_scan.l2_final_accuracy` 与 `router.classify` L2 段（router.py:192-205：intent≠knowledge 且 confidence 非空且 <t 且确认信号 → 修正 knowledge）逐行一致。
- **推荐推导**：0.55 为 argmax F1（0.98）；0.4 经验值 Recall 0.40（漏判 60%）"明显偏低"结论与曲线一致；0.5 保守备选（R=0.92、误杀 1/50）计算无误；0.60 零漏判但误杀 3/50 的权衡记录属实。

### WP3 golden 扩样本

- **数量/结构**：112 题（30 原题 + 82 新增）；无空 question；无重复题（question 分组全 count=1）；新增题 golden_docs 全非空；格式对齐（question+golden_docs+category，无 ground_truth 与既有条目一致）。
- **原 30 题零改动**：`git show HEAD:ai_service/eval/golden.json` 与现文件前 30 条逐项相等（含字段顺序）。
- **主题真实性**：82 新题主题全部对应真实文档（G1/线程池/AQS/HashMap/volatile/JMM/Spring/MyBatis/MySQL/Redis/Nacos/一致性哈希/ZK/雪花/Seata/Sentinel/Gateway/Kafka/RocketMQ/Netty/TCP/TLS/AI 系列/Agent 系列/ES/单例），无知识库外内容。
- **golden_docs 引用**：50 个 distinct 引用，37 个在 documents 表精确命中；13 个为"标题前缀锚点"（DB 中仅存 `标题 > 板块N > ...` 分块行，无裸标题行）——但这 13 个引用对应的题目在检索回归（id=13）中全部命中（如 CAP/微服务→Nacos 文档 Hit=1.0、MoE 命中、Spring/MySQL/RocketMQ/TLS/ZeRO 命中），运营口径"0 悬空引用"成立（见 §5 minor 3）。
- **检索回归**：DB eval_runs id=9（30 题，hit_at_k=0.9565/recall=0.9130/mrr=0.9130）→ id=13（112 题，0.9714/0.9571/0.9270）——与 changelog §4.2 表完全一致；3 未命中题（Transformer Self-Attention / Cache Aside / RocketMQ-Kafka 选型）与 per-category 缺口吻合（ai_llm 16/17、redis 3/4、mq 2/3）。
- **测试适配**：`test_golden_retrieval.py` diff 仅 1 处断言逻辑（硬编码 30/23/7 → 数据无关），CAP/Docker 标注回归意图保留，20/20 通过。

### WP4 图谱消融

- **环境故障属实**：`m047_ablate.log` 含 `UndefinedColumnError: documents.last_mentioned_at does not exist`；DB 实测 information_schema 确认 documents 表无 last_mentioned_at/mention_count 列（缺 module-046 迁移）、public schema 无任何图谱/entity/relationship 表；documents 7506 行与声明一致。
- **graph_only Hit@5=0.0000 判定为"环境故障非真实表现"合理**（全题走"图搜索失败降级空"路径），delta +0.9714 明确标注不可引用、ADR-0004 决策 4 留白保持"待环境"——诚实，不伪造。
- 方法学 + 已就绪命令（`python -m eval.golden_retrieval --ablate --top-k 5`）与前置条件（迁移列/建图/实体链接）记录完整。

## 3. 测试验收

- `tests/test_threshold_scan.py` 22 用例：compute_prf（含 0 分母降级）/ scan_scores 手工计算样例 / recommend_threshold（min_recall 约束 + 无候选回退）/ l2_trigger_samples / l2_final_accuracy（复现生产 L2 逻辑）/ scan_l2 / scan_gate / 扫描区间常量（0.2-0.8 步长 0.05、0.2-0.6 步长 0.05、经验值与生产常量一致）——纯函数测试，不依赖 LLM/DB/embedding，设计合理。
- Reviewer 独立全量复跑：525 passed / 0 failed，与模块声明一致。

## 4. 文档验收

- `changelog.md` 新建，含全部实测数字表（intent/sufficiency 混淆矩阵、L2 曲线、闸门曲线+分布、检索回归对比、消融结果）+ 结论 + 降级/边界/待办，质量高。
- 记忆文件 3 份（rag-architecture.md / rag-agent-roadmap.md / MEMORY.md）均已追加 module-047 记录，数字与 changelog 一致。
- 简历弹药 06 已按新口径更新：112 题/105 有效/0.9714（102/105，id=13）；图谱增量收益标注"待环境"；0.96 旧口径保留为历史数字不混用。

## 5. 发现（4 项 minor，均不阻塞）

| # | 级别 | 事项 | 说明 |
|---|------|------|------|
| 1 | minor | `tests/test_golden_retrieval.py` 改动不在 plan 3.1 文件清单内 | 数据扩样后硬编码 30/23/7 断言必然失败，为保红线④全绿必须适配；改动仅 1 处断言、diff 可审，changelog §4.3 已说明原因。建议 Planner 提交时知悉（可接受，不返工） |
| 2 | minor | L2 触发阈值校准证据强度有限 | 应触发样本 0→2 受 LLM 非确定性影响；LLM confidence 下限 0.70 使 t<0.70 区间永远零触发——"保持 0.5"是"零回归+无更优证据"的诚实结论而非强证明。dev 已在 issues_known #3/#5 披露，后续需更难样本集（扫描区间上移 0.6-0.95） |
| 3 | minor | 13/50 个 golden_docs 引用为标题前缀锚点而非精确行 | documents 表按"标题 > 板块 > 题目"分块存储、无裸标题根行；检索按前缀命中（id=13 相关题全命中），无功能影响。仅提示：后续做"引用存在性校验"时需前缀匹配而非等值匹配，否则会误报 |
| 4 | minor | 硬闸门推荐值的外部效度 | 扫描分数源是标注集注入文档的实测余弦（question vs 注入文档 top-1），非生产真实检索分布；且隔离闸门假设"未触发默认充分"会低估生产 LLM 层的兜底（该层在标注集上 100% 判对）。0.4→0.5~0.55 的方向性证据充分、量级需上线前真实检索分数抽样复核——dev 已在 changelog §3.2 / issues_known #1/#6 完整披露。另 `.ua/m047_threshold_cache.json` 未被 gitignore 覆盖（.ua/ 目录会话前即未跟踪），dev 已建议 Planner 提交时排除 |

## 6. 结论

模块 4 个工作包全部按验收标准交付：WP1 真实 baseline 落库（数字经日志+DB 双重核实）；WP2 数据驱动阈值校准（逻辑与推荐值推导复核通过，经验值 0.4 偏低结论成立，改代码留后续模块处置得当）；WP3 golden 扩样本 112 题质量合格（原题零改动、无重复、主题真实、引用有效、检索回归 0.9565→0.9714 实测落库）；WP4 环境不可用如实标注"待环境"、不伪造数字、交付方法学。

红线 4 条全部通过，全量测试 525 全绿（独立复跑确认），无 critical/major 发现。**verdict: approved**。
