# Changelog — Module-053: 检索融合升级（RRF 三通道消融验证）

> Developer | 2026-08-12
> 全量基线 614 passed → module-052 并行新增 15 → 本模块新增 16 → **645 passed / 0 failed**
> 开工前已读 memory/project-context.md（模块清单 module-001~051，避免重复/冲突）

---

## 0. 放行决策（结论先行）

**放行 RRF 三通道融合（推荐启用：`PW_RETRIEVAL_FUSION_MODE=rrf`；代码默认保持 `hybrid`）。**

| 方案（同 golden 112 题 / 105 题评估 / top_k=5 / 同脚本 / eval_runs） | Hit@5 | Recall@5 | MRR | eval_runs id |
|------|------|------|------|------|
| 基线 hybrid 两通道（FTS+向量 alpha 加权） | 0.9714 | 0.9571 | 0.9270 | 17 |
| **RRF 三通道（FTS/向量/图谱，k=60）** | **0.9905** | **0.9762** | **0.9341** | 18 |
| 加权三通道 0.3/0.6/0.1 | 0.9714 | 0.9571 | 0.9270 | 19 |
| 加权三通道 0.25/0.5/0.25 | 0.9714 | 0.9619 | 0.9246 | 20 |

- RRF 相对基线 **+0.0191 Hit@5（2/105 题从 miss 翻转为 hit，0 题回退）**、+0.0191 Recall@5、+0.0071 MRR——增益全部来自图谱通道把图命中文档带入 top-5（如"Transformer Self-Attention"经图通道命中 4-RoPE 文档翻转为 hit；"RocketMQ vs Kafka"图通道带入 RocketMQ 文档）
- 加权两组与基线完全持平：图谱权重 0.1/0.25 不足以改变 top-5 排序（FTS+向量 0.75-0.9 权重主导），三通道加权在本场景无增益——**RRF 是"排名无关分数量纲"的融合，对图通道这种离散计数天然适配，优于加权**
- **口径声明（新旧对比前提）**：golden 评估路径直调 `hybrid_retriever.retrieve()`，**不含引擎层 round 0 图谱并行**（引擎层图追加不在评估路径）——历史 0.9714（eval_runs id=13，module-047）与本次基线 id=17 均为**纯两通道口径**，RRF id=18 为**三通道口径**；本表所有数字同集同脚本同表，delta 有效。引擎层口径（round 0 图谱追加 vs retriever 三通道融合）见 §3.3
- **否决加权、放行 RRF 的理由**：① 唯一 ≥ 基线的方案（加权 = 基线无增益）② 0 回退（无损失题）③ k=60 业界默认，k 扫描留后续 ④ hybrid 回退开关保留（`PW_RETRIEVAL_FUSION_MODE=hybrid` 一键回退）
- **为何默认保持 hybrid（AC 零回归契约）**：① AC §3 明示"默认 hybrid 时行为与现状零回归（存量测试全绿证明）"+ 红线"全量 614 全绿保持、不改存量测试"——rrf 若作代码默认会改变引擎 round 0 降级语义，2 项存量降级用例（test_engine_latency.py TestRound0Degradation，断言引擎层向量失败→图回退）将失败（实测 2 failed / 11 passed），不满足红线 ② 评估为 retriever 直调口径，引擎 chat 路径 rrf 分支仅经真实 DB 冒烟（§5），未做真实 HTTP E2E ③ rrf 每次知识库查询 +1 次 LLM 实体提取调用。**上线方式：`PW_RETRIEVAL_FUSION_MODE=rrf` 一键开启（配置/代码/评估全部就绪），后续真实 E2E 复核后可将默认切 rrf（1 行 config）**

## 1. WP-0 DB 修复（环境欠账）

- `scripts/migrate_module053.py`（新建，幂等可重跑）：① documents 表补 `last_mentioned_at`（TIMESTAMPTZ）/`mention_count`（INTEGER NOT NULL DEFAULT 0）两列——module-046 ORM 字段本地库缺列，导致 `graph_store.search_related` 的 `select(Document)` 全列查询报 "column does not exist"（module-047 实测报错点）；幂等实现=查 information_schema 已存在跳过 ② feedback 表建表——复用 `src.database.ensure_feedback_table()`（module-048 FEEDBACK_DDL，'；' 拆分逐条执行 + init_db 自愈同款）
- 验证：脚本二次运行跳过（幂等 ✅）；`graph_store.search_related(["Java","JVM"])` 真实返回 5 篇（graph_score 0.14-1.0，**不再报 last_mentioned_at 错误** ✅）；documents 7506 行不受影响

## 2. WP-A 基线复测 + 口径钉死

- 实测：**Hit@5=0.9714 / Recall@5=0.9571 / MRR=0.9270**（105/112 题评估，7 题无 gold 跳过），eval_runs **id=17**（commit 1076d413）——与历史 id=13（0.9714）完全一致，基线可复现
- **前置修复（module-050 目录细分引发的回归）**：`rag/retrieval/embeddings.py` 的 `_LOCAL_MODEL_DIR` 仍用二级 `dirname(__file__)`，module-050 把文件从 `rag/embeddings.py` 移到 `rag/retrieval/` 后路径解析到 `rag/models/...`（不存在）→ 向量通道全线不可用（首次复测退化 FTS-only 0.0381，eval_runs id=16 为环境故障记录，无效，勿对比）；修复为三级 dirname（对齐 module-051 `factcheck_judge._HHEM_MODEL_DIR` 范式）→ 模型路径回归 `ai_service/models/bge-m3-gguf/` ✅
- **口径声明（已写入 eval 脚本 + 本 changelog）**：`eval/golden_retrieval.py` 的 `_eval_question` 直调 `hybrid_retriever.retrieve(mode="hybrid")`——评估路径 = **纯两通道（FTS+向量）**，引擎层 round 0 的图谱并行/追加**不在评估路径**。历史 0.9714（id=13）与本次 id=17 同口径（纯两通道）；RRF/加权数字为三通道口径。新旧对比必须同口径，已通过 eval_runs scores 增加 `fusion_mode`/`fusion_weights` 字段落地（脚本 `run_eval`/`print_report`/`compare_runs` 同步展示，compare 输出新增口径警告行）
- **id=17 字段口径（minor 修复记录）**：id=17 基线运行在 fusion_mode 落库改造之前，其 scores **无 `fusion_mode` 字段**——`compare_runs` 对缺失字段按 hybrid 兜底（`.get('fusion_mode', 'hybrid')`），**id=17 即为 hybrid 两通道口径**（与 id=13 同口径，可放心对比）

## 3. WP-B RRF 三通道融合

### 3.1 实现（`rag/retrieval/retriever.py` + `src/config.py` + `rag/engine.py`）

- **开关**：`settings.retrieval_fusion_mode`（PW_RETRIEVAL_FUSION_MODE）取值 `hybrid`（默认）/`rrf`/`weighted`；`rrf_constant_k=60`（PW_RRF_CONSTANT_K，本次不做 k 扫描）；`retrieval_fusion_weights="0.3,0.6,0.1"`（PW_RETRIEVAL_FUSION_WEIGHTS，weighted 模式用）
- **RRF 公式**：`score(d) = Σ 1/(k + rank_i(d))`，k=60，rank 为三路各自 1-based 排名（通道内按自身分数降序：FTS ts_rank / 向量 cosine / 图谱实体命中数）；`_fuse_rrf` 纯函数实现，缺路不贡献分
- **接入点**：`retrieve()` 新增 `round_num: int = 0` 参数——fusion 模式仅 `round_num==0` 走 `_execute_fusion`（三路并行 + 融合），round 1/2（round_num>0）保持单路混合（FTS+向量，无图谱），与引擎层"图谱仅 round 0 查询一次"语义一致；hybrid 模式忽略 round_num（零回归）
- **并行**：FTS/向量各开独立 session（module-026 并发修复同款）+ 图谱通道 `_retrieve_graph_only`（LLM 抽实体 10s 超时 + `search_related` 15s 超时，失败降级空）三路 `asyncio.gather(return_exceptions=True)`
- **红线**：① abs_cosine 在归一化/融合前存档（`_execute_fusion` 对 vector_results 先 `r["abs_cosine"] = r["score"]`，双命中透传，仅 FTS 命中文档无该字段由下游 0.0 保守处理）——L3 反证依赖未破坏 ✅ ② reranker.py 未动（RRF 粗排 vs CE 细排两阶段共存）✅
- **引擎适配（`rag/engine.py`）**：round 0 在 fusion 模式下改由 retriever 内部完成三通道（图谱不再重复查图——避免双倍 LLM 实体提取），round 1/2 的 retrieve 调用传 `round_num`；hybrid 默认走原分支（diff 仅条件分支 + 参数透传，零回归，203 项引擎/记忆相关测试全绿）
- **兼容**：融合结果 hybrid_score 为 min-max 归一化后的融合分（RRF 原始分保留在 `rrf_score` 字段）——**解决 module-035 记录的"RRF 原始分 0.017-0.033 与引擎 min_score=0.6 过滤硬不兼容"问题**（归一化后 top=1.0，过滤语义与现状一致）

### 3.2 降级

- 单路失败 → 该路不参与融合（缺路退化为两通道/单通道 RRF），不崩；三路全空 → 空列表
- 融合计算异常 → 回退 `_execute`（hybrid 单路混合，保守降级，与 query_rewrite 同哲学）
- 图谱 LLM 提取超时 → 图通道空，RRF 退化为两通道（实测 105 题仅 1 题超时："Agent 评估怎么做"，日志可见）

### 3.3 口径差异（引擎 vs 评估，面试必答）

- **评估口径（本模块所有数字）**：`retrieve()` 直调——rrf = FTS/向量/图谱三通道 RRF；hybrid = 纯两通道
- **引擎口径（生产 chat 路径）**：hybrid 模式下 round 0 = 两通道 + 引擎层图并行追加去重（历史行为，图文档以 graph_score 独立存在）；rrf 模式下 round 0 = retriever 内三通道 RRF（图实体提取基于 HyDE 查询而非原 query，已知差异）
- 对比声明：id=17 基线（两通道）vs id=18 RRF（三通道）的 delta 是"加图通道 + 换融合公式"的合并效果——单独归因需补跑"两通道 RRF"消融（后续可选）

## 4. WP-C 加权三通道对照（2 组权重）

- 实现：`_fuse_weighted`——三路各自 min-max 归一化 + 权重加权（默认 0.3/0.6/0.1，解析失败回退默认并告警）
- 实测：**0.3/0.6/0.1 → 0.9714/0.9571/0.9270（id=19）**——与基线完全持平，图通道在低权重下不改变 top-5 排序；**0.25/0.5/0.25 → 0.9714/0.9619/0.9246（id=20）**——Recall 微升（0.9619 vs 0.9571，图文档进入候选）但 MRR 微降（0.9246 vs 0.9270，图文档排位拉低首个命中），Hit@5 持平
- 结论：本项目场景 **RRF（0.9905）> 加权（0.9714）= 基线（0.9714）**——RRF 对"分数量纲不可比"的通道（离散计数 vs 连续相似度）天然鲁棒；加权需先校准图分数量纲（module-021 保底 0.6 等）才可能生效，0.25 图权重已有 Recall 增益迹象但不足以命中翻盘

## 5. 测试

- `tests/test_rrf_fusion.py` 新建 **16 用例**：RRF 公式已知值（单通道 rank1=1/61 / 三通道已知排名精确断言 / 缺路不贡献 / 归一化）、加权融合（加权和 / 权重覆盖 / 非法权重回退）、开关语义（默认 hybrid 走 _execute 零回归 / rrf round 0 走融合 / round 1/2 单路混合）、三通道融合全流程（三路合并排序 / 向量失败降级 / 三路全空 / **abs_cosine 保留断言** / 融合异常回退 hybrid / 图-only 结果保留）
- 全量 `python -m pytest tests/ -q` → **645 passed / 0 failed**（614 基线 + module-052 并行新增 15 + 本模块新增 16，零回归；未改任何存量测试）。注：全量含并行 module-052 的 test_compare_nli.py，共享 worktree 口径，645 全绿即双方互不回归

## 6. 已知边界（诚实记录）

- 评估为 retriever 直调口径，引擎 chat 路径 rrf 未做真实 HTTP E2E（引擎 round 0 融合分支经真实 DB 冒烟验证 + 203 引擎相关单测覆盖）；上线后建议真实对话冒烟
- rrf 默认后每次知识库查询 +1 次 LLM 实体提取调用（≤10s 超时），成本/延迟增量见 §0；`PW_RETRIEVAL_FUSION_MODE=hybrid` 一键回退
- **rrf 模式 embedding 故障降级不对称（minor 修复记录，属该模式固有语义，不改代码行为）**：rrf 模式向量通道故障时融合退化为 FTS+图谱两路 RRF，**无 hybrid 模式的图结果兜底**（hybrid 模式向量故障由引擎层 round 0 图并行追加兜底，rrf 模式引擎层不再重复查图、无该兜底）；embedding 故障期间建议切 `PW_RETRIEVAL_FUSION_MODE=hybrid` 恢复图兜底
- reranker.py 的 `_LOCAL_MODEL_DIR` 存在与 embeddings.py 同款 module-050 路径回归（rag/models/ 不存在），**未修**（红线：本模块不动 reranker.py）——影响真实 chat 路径重排（测试全 mock 不暴露），建议后续模块修复（与 embeddings.py 同款三级 dirname）
- k 值扫描（60 是否最优）未做，留后续；"两通道 RRF"归因消融未做（见 §3.3）
- eval_runs id=16 为嵌入路径回归期间的环境故障记录（FTS-only 降级 0.0381），无效数据，对比请用 id=17 起

---

## 8. Minor 修复记录（Reviewer 5 条，2026-08-12）

| # | 文件 | 修复内容 |
|---|------|---------|
| 1 | `src/config.py`（+ `tests/test_rrf_fusion.py` 2 用例） | `retrieval_fusion_mode` 加 `Literal["hybrid","rrf","weighted"]` 枚举校验——非法字符串（拼写错误）启动即抛 ValidationError（fail-fast），防静默落入 rrf 分支；新增 TestFusionModeValidation（非法值拒绝/合法值接受） |
| 2 | `tests/test_rrf_fusion.py` | 补 weighted 经 `_execute_fusion` 的端到端用例（此前仅 `_fuse_weighted` 纯函数覆盖）：三路各单文档 → 归一化 1.0 → 加权分 = 权重 0.3/0.6/0.1，断言排序与权重生效 |
| 3 | `specs/module-053-rrf-fusion/changelog.md` §2 | 补 id=17 口径说明：基线运行在 fusion_mode 落库改造之前、scores 无该字段，compare_runs 按 hybrid 兜底（`.get('fusion_mode','hybrid')`），id=17 即为 hybrid 两通道口径 |
| 4 | `specs/module-053-rrf-fusion/changelog.md` §6 | 补已知边界：rrf 模式 embedding 故障时融合退化为 FTS+图谱两路、无 hybrid 的图结果兜底（属该模式固有语义，不改代码行为），切 hybrid 可恢复 |
| 5 | `specs/module-053-rrf-fusion/changelog.md` §6 | 确认已含（无需补充）：reranker.py `_LOCAL_MODEL_DIR` 同款 module-050 路径回归"未修 + 建议后续模块修复"条目已在已知边界中 |
