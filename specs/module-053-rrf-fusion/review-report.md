# 审查报告 — Module-053: 检索融合升级（RRF 三通道消融验证）

> Reviewer | 2026-08-12 | 第一轮审查
> **结论：✅ PASS（0 阻塞，6 项 minor 非阻塞）**

---

## 0. 审查结论

**verdict: pass。** 实现与验收标准逐条吻合；评估数字经 eval_runs 表独立核验逐位一致（含逐题翻转明细）；全量 pytest 645/0 独立复跑一致；零回归与红线（abs_cosine / reranker / round 0 语义）代码级核对通过；记忆更新硬性约束满足。

**放行决策认可**：RRF 三通道（0.9905）> 基线两通道（0.9714，+0.0191 Hit@5，2 题翻盘 0 回退）> 加权两组（= 基线）——决策与数据一致，未过度外推（k 扫描、引擎真实 E2E、两通道 RRF 归因消融均如实列为后续项，112 题量级声明到位）。

---

## 1. 独立复现与核验（全部通过）

| 核验项 | 方法 | 结果 |
|------|------|------|
| 全量测试 | `python -m pytest tests/ -q` 独立复跑 | **645 passed / 0 failed（118.90s）**，与 changelog 一致 |
| 基线复测 | eval_runs 表查询 id=13/17 | id=17 = 0.9714/0.9571/0.9270 与 id=13 完全一致，105/112 题 |
| RRF 实测 | eval_runs id=18 | 0.9905/0.9762/0.9341，scores 含 `fusion_mode="rrf"`，与 changelog 一致 |
| 加权对照 | eval_runs id=19/20 | id=19 权重 0.3,0.6,0.1 = 基线；id=20 权重 0.25,0.5,0.25 = 0.9714/0.9619/0.9246，与 changelog 一致 |
| 环境故障记录 | eval_runs id=16 | 0.0381（FTS-only 降级），git_commit 与前不同（96058d07），"无效勿对比"声明正确 |
| **逐题翻转核验** | id=17 vs id=18 per_question 逐题对比 | **恰好 2 题 miss→hit**（"Transformer模型的Self-Attention机制是如何工作的？"、"RocketMQ 和 Kafka 的选型怎么考虑？"），**0 题 hit→miss**——与 changelog "+2 题 / 0 回退"逐字吻合 |
| 数据真实性 | id=13/17/18/19/20 全部 105 题 `degraded=0` | 无静默降级污染，向量通道全程可用 |
| DB 修复 | information_schema 实查 | documents 表含 last_mentioned_at/mention_count；feedback 表存在（6 列：id/message_id/rating/comment/identity/created_at） |
| golden 集 | eval/golden.json | 112 题（105 评估 + 7 无 gold 跳过，与 DB `skipped=7` 一致） |
| 编译 | py_compile 7 文件（config/retriever/engine/embeddings/golden_retrieval/migrate/test） | OK |

---

## 2. 验收标准逐条核查（AC 9 节）

| 节 | 标准 | 结果 | 依据 |
|----|------|------|------|
| §1 | documents 补两列幂等 + feedback 表 + search_related 不再报错 | ✅ | 列/表实查存在；迁移脚本查 information_schema 跳过已存在列（幂等）；DSN 硬编码与 scripts/ 既有脚本（create_metadata_tables.py/do_all.py）同款惯例 |
| §2 | 基线复测落地 eval_runs + 口径钉死声明 | ✅ | id=17 复现 0.9714；`_eval_question` 直调 `retrieve(mode=...)` 无引擎图谱并行（代码核实）；口径声明在 changelog §0/§2 + eval 脚本 scores + compare_runs 警告行 + 简历 2.4 四处同步 |
| §3 | RRF 公式 k=60 1-based + 开关 hybrid/rrf + round 0 语义 + --compare | ✅ | `_fuse_rrf`：`Σ 1/(60+rank)`、`_channel_ranks` 1-based（enumerate start=1）、通道内按分降序重排；开关默认 hybrid；round_num 参数 + 引擎 round 1/2 传 round_num>0 + 注释；eval_runs 17-20 同 commit 锚点（1076d413） |
| §4 | 加权对照 ≥2 组 + 对比结论 | ✅ | 0.3/0.6/0.1 与 0.25/0.5/0.25 两组实测（id=19/20）；结论"加权无增益、RRF 适配离散计数通道"有数据支撑 |
| §5 | 放行决策（≥基线选增益最大 + 保留 hybrid 回退）+ 写入 changelog/简历 | ✅ | RRF 唯一增益（+0.0191，0 回退）；否决加权理由明确；`PW_RETRIEVAL_FUSION_MODE=rrf` 一键启用，默认 hybrid 保留；changelog §0 + 简历 2.4 对比表/决策/面试话术齐 |
| §6 | 单路失败不参与融合不崩 + rrf 异常回退 hybrid + 图谱不可用如实标注 + 全量绿 | ✅ | 三路 gather(return_exceptions=True) + 逐路 Exception 转空；融合异常 try/except 回退 `_execute`；DB 修复后图谱真实可用（无需"待环境"标注）；645/0 独立复跑 |
| §7 | abs_cosine 不破坏 + reranker.py 不动 + 返回结构不变 | ✅ | `_execute_fusion` 归一化/融合前 `r["abs_cosine"] = r.get("score", 0.0)` 存档 + 双命中透传（与 `_execute` 同款）；git status 确认 reranker.py 未触碰；返回结构仅追加 graph_score/rrf_score 字段 |
| §8 | test_rrf_fusion.py 覆盖点 + 全量 614+ 全绿 | ✅ | 16 用例逐项核对（公式已知值/三路排序/开关零回归/单路降级/全空/abs_cosine 保留/异常回退/加权和/权重覆盖/非法权重回退）；存量测试零改动（git status 仅新增 test_rrf_fusion.py） |
| §9 | changelog/review-report/test-report + 三记忆文件 + 简历 2.4 + 开工前读 project-context | ✅（test-report 移交 Tester） | changelog 注"开工前已读 project-context.md"；三记忆文件已更新（见 §4）；简历 2.4 已更新；**test-report.md 尚未产出——模块 053 Tester 未单独验收，移交 Tester** |

---

## 3. 红线与代码级核对

1. **零回归**：`_execute` 与 engine hybrid 分支 diff 逐行核对——`_execute` 零改动；`retrieve()` 仅加 `round_num` 尾参（位置兼容）+ fusion 条件分支；engine hybrid 分支为原代码原样（仅补 `round_num=0` 显式传参，hybrid 忽略）。下游 `_map_to_parent` 用 `doc.get("hybrid_score", doc.get("score", 0.0))` 兜底读取，graph-only 文档缺 score 键不会 KeyError。
2. **RRF 公式**：`_channel_ranks` 通道内 `sorted(..., reverse=True)` 后 enumerate(start=1) 取 1-based 排名；`1.0/(k+rank)` 贡献分；三路贡献求和；缺路 `.get(doc_id, 0.0)` 不贡献。已知值测试（1/61、三通道组合、缺路）精确断言通过。
3. **排序稳定性**：平分时依赖 Python 稳定排序 + dict 插入序（FTS 优先），测试已断言 [1,3,2] 顺序。
4. **归一化兼容**：rrf 原始分 min-max 归一化为 hybrid_score（top=1.0），解决 module-035 记录的"RRF 原始分与引擎 min_score=0.6 过滤硬不兼容"——单文档全同分保底 1.0 分支有测试。
5. **图谱通道排名口径**：graph 通道按 `hybrid_score`（命中实体数 min-max 归一化，单调保序）排 1-based——与命中数降序等价，无排序失真。

---

## 4. 记忆更新硬性约束核查

| 项 | 结果 |
|----|------|
| project-context.md 模块清单追加 module-053 行（格式对齐、含数字） | ✅ |
| project-context.md 头部"最后更新"→ 2026-08-12 | ✅ |
| agent-activity-log.md Developer 活动行（module-053，内容完整） | ✅ |
| agent-activity-log.md Reviewer 活动行 | ✅（本报告同步追加） |
| file-index.md 新文件行（migrate_module053.py + test_rrf_fusion.py，只追加） | ✅ |
| 未修改其他模块历史记录行 | ✅（module-033 changelog 的改动为其他并行会话产物，见 minor#5） |

---

## 5. Minor 发现（非阻塞，6 项）

1. **[健壮性] `retrieval_fusion_mode` 无枚举校验**（`ai_service/src/config.py` / `ai_service/rag/retrieval/retriever.py:119`）——任意非法字符串（如拼写错误）会静默落入 rrf 分支（`!= "hybrid"` → `_execute_fusion` → 非 weighted → `_fuse_rrf`），而非保守回退 hybrid。建议 pydantic `Literal["hybrid","rrf","weighted"]` 或 retrieve() 内显式白名单校验，未知值回退 hybrid。
2. **[降级不对称] 引擎 rrf 分支 embedding 故障无图兜底**（`ai_service/rag/engine.py:725-739`）——rrf 模式下 `retrieve()` 内向量化失败抛 RetrievalException → 引擎 catch-all 得空列表；而 hybrid 分支图通道独立于 retriever，向量失败仍可图兜底。属 rrf 模式固有语义（融合需三路），changelog 已声明引擎 rrf 分支未真实 HTTP E2E；建议上线前补一次 embedding 故障场景验证（或真实对话冒烟时覆盖）。
3. **[口径记录] 基线 id=17 scores 无 fusion_mode 字段**——运行顺序所致（fusion_mode 落库改造在基线跑之后），compare_runs 靠 `.get('fusion_mode','hybrid')` 兜底显示。当前无实际影响（基线即 hybrid），但严格同口径对比依赖该默认值；可选：后续重跑一次基线让字段齐全。
4. **[测试覆盖] weighted 模式全流程未直测**——`_execute_fusion` 全流程测试只覆盖 rrf 分支（`test_fusion_exception_falls_back_to_hybrid` 等），weighted 只测了 `_fuse_weighted` 纯函数。建议补 1 例 weighted 经 `_execute_fusion` 的端到端用例（当前由 golden id=19/20 实测兜底，非缺陷）。
5. **[共享 worktree 脏状态] `specs/module-033-long-term-memory/changelog.md` 有未提交改动**（6 项跨模块缺陷记录，属其他并行会话产物）——非 module-053 范围，提醒主会话提交时区分文件归属，勿混入本模块 commit。
6. **[边界说明] engine 口径差异已在 changelog §3.3 如实声明**（rrf 引擎 round 0 图实体提取基于 HyDE 查询 vs 评估路径基于原 query；"两通道 RRF"归因消融留后续）——无问题，仅确认面试口径材料完整。

---

## 6. 移交项

- **Tester**：产出 `specs/module-053-rrf-fusion/test-report.md` + agent-activity-log.md Tester 行（全量 645/0 已由 Reviewer 独立复跑确认，可直接引用）。
- **主会话（提交时）**：注意 module-033 changelog 的并行会话改动不混入本模块 commit；`ai_service/.ua/`、`module-033-loop.js` 等并行产物按归属处理。
