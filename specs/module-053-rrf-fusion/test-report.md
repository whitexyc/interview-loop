# 测试报告 — Module-053: 检索融合升级（RRF 三通道消融验证）

> Tester | 2026-08-12 | **验收通过（AC 9 节全过，0 阻塞）**
> 全量回归：**645 passed / 0 failed（119.72s）**（614 基线 + module-052 并行新增 15 + 本模块新增 16）

---

## 1. 全量回归

| 项 | 结果 |
|----|------|
| `python -m pytest tests/ -q` | **645 passed / 0 failed** in 119.72s |
| 与 changelog / Reviewer 复跑一致性 | 一致（changelog 645/0；Reviewer 独立复跑 645/0，118.90s） |
| 存量测试改动 | 零改动（git status 无 `tests/` 存量文件修改，仅新增 `test_rrf_fusion.py`） |
| 并行 module-052 互不回归 | 共享 worktree 全量 645 全绿即双向无回归 |

## 2. 新增单测（tests/test_rrf_fusion.py，16 项）

| 组 | 用例 | 结果 |
|----|------|------|
| TestRrfFormula (4) | 单通道 rank1=1/61；三通道已知排名精确断言（A=1/61+1/63+1/62 等 + 稳定排序 [1,3,2]）；缺路不贡献（1/61+1/61）；rrf_score min-max 归一化 top=1.0 保留原始分 | ✅ |
| TestWeightedFusion (3) | 加权和（单通道全 1.0 → 0.3/0.6/0.1）；权重覆盖 0.25/0.5/0.25；非法权重回退默认 | ✅ |
| TestFusionSwitch (3) | 默认 hybrid 走 `_execute` 不触图谱（零回归）；rrf round 0 走 `_execute_fusion`；rrf round 1/2 单路混合（round_num=2 → `_execute`） | ✅ |
| TestExecuteFusion (6) | 三通道合并排序 + graph_score 透传；向量失败降级不崩；三路全空返回空；**abs_cosine 保留断言 + 双命中透传 + FTS-only 无字段**；融合异常回退 hybrid；图-only 父块结果保留 | ✅ |

## 3. 冒烟复跑（基线/RRF 数字一致性，eval_runs 表实查）

同一 eval_runs 口径直接查库核验（避免重复落库），与 Developer changelog 对比表逐位一致：

| eval_runs id | Hit@5 | Recall@5 | MRR | fusion | commit | degraded |
|------|------|------|------|------|------|------|
| 13（历史基线） | 0.9714 | 0.9571 | 0.9270 | hybrid | 2eac844c | 0/105 |
| 16（环境故障记录，无效勿对比） | 0.0381 | 0.0381 | 0.0333 | hybrid | 96058d07 | 105/105 |
| 17（WP-A 基线复测） | 0.9714 | 0.9571 | 0.9270 | hybrid | 1076d413 | 0/105 |
| **18（RRF 三通道）** | **0.9905** | **0.9762** | **0.9341** | **rrf** | 1076d413 | 0/105 |
| 19（加权 0.3/0.6/0.1） | 0.9714 | 0.9571 | 0.9270 | weighted | 1076d413 | 0/105 |
| 20（加权 0.25/0.5/0.25） | 0.9714 | 0.9619 | 0.9246 | weighted | 1076d413 | 0/105 |

- **逐题翻转独立复算**（id=17 per_question vs id=18 per_question）：恰好 2 题 miss→hit（"Transformer模型的Self-Attention机制是如何工作的？"、"RocketMQ 和 Kafka 的选型怎么考虑？"），**0 题 hit→miss**——与 changelog "+2 题翻盘 / 0 回退"逐字吻合
- **数据真实性**：id=13/17/18/19/20 全部 105 题 degraded=0（无静默降级污染）；id=16 degraded=105 佐证其为嵌入路径回归期间的环境故障记录
- **口径声明核验**：id=17 scores 无 fusion_mode 字段（运行顺序所致，Reviewer minor#3，compare_runs 默认 hybrid 兜底正确）；id=18/19/20 均含 fusion_mode + weighted 组含 fusion_weights——口径字段落库生效

## 4. 实现抽查（与 changelog 一致性）

| 抽查项 | 结果 |
|--------|------|
| RRF 公式 `score(d) = Σ 1/(k + rank_i(d))`，k=60，1-based | ✅ `_fuse_rrf`（retriever.py L477-560）：k=`settings.rrf_constant_k`（默认 60）、`enumerate(start=1)`、通道内按分降序重排；缺路 `.get(doc_id, 0.0)` 不贡献 |
| 开关默认 hybrid（零回归契约） | ✅ `src/config.py` `retrieval_fusion_mode: str = "hybrid"`（PW_ 前缀三配置：PW_RETRIEVAL_FUSION_MODE / PW_RRF_CONSTANT_K / PW_RETRIEVAL_FUSION_WEIGHTS） |
| abs_cosine 红线保留 | ✅ `_execute_fusion`（L459-461）归一化/融合前 `r["abs_cosine"] = r.get("score", 0.0)` 存档，双命中透传（`_fuse_rrf` L527-528），与 `_execute` 同款 |
| RRF 融合仅 round 0 语义 | ✅ `retrieve()` `round_num: int = 0` 参数 + docstring 注释（L86-99）；engine rrf 分支（engine.py L725-739 注释"图谱通道由 retriever 内部并行完成，引擎不再重复查图"）+ round 1/2 传 `round_num=round_num`（L775 注释"单路混合，与引擎层图谱仅 round 0 查一次语义一致"） |
| reranker.py 不动（红线） | ✅ git status 无 reranker.py 变更 |
| 返回结构 / 存量测试 | ✅ 仅追加 graph_score/rrf_score 字段；存量测试零改动 |

## 5. WP-0 DB 修复验证

| 项 | 结果 |
|----|------|
| documents 两列 | ✅ `last_mentioned_at`（timestamp with time zone）、`mention_count`（integer）information_schema 实查存在 |
| feedback 表 | ✅ 6 列：id/message_id/rating/comment/identity/created_at（对齐 module-048 FEEDBACK_DDL） |
| 迁移脚本幂等 | ✅ `python scripts/migrate_module053.py` 二次运行：两列均"列已存在，跳过"、feedback 已就绪、ALL DONE（exit 0） |
| search_related 不再报错 | ✅ 根因（缺列致全列查询报 column does not exist）已消除；Developer 实测真实返回 5 篇 |

## 6. 记忆文件硬核查

| 项 | 结果 |
|----|------|
| project-context.md module-053 行 | ✅ 存在（L71），格式对齐（含版本号/日期/测试数字），头部"最后更新: 2026-08-12"（L7） |
| agent-activity-log.md Developer 行 | ✅ L122 |
| agent-activity-log.md Reviewer 行 | ✅ L124 |
| agent-activity-log.md Tester 行 | ✅ 本报告同步追加（L125） |
| file-index.md 新文件行 | ✅ migrate_module053.py（L66）+ test_rrf_fusion.py（L67），只追加 |
| 其他模块历史记录行 | ✅ 未修改（specs/module-033 changelog 的并行会话改动按归属区分，非本模块） |
| 简历 08 文档 2.4 节 | ✅ 已核：代码真相 + rrf 公式 + 对比表（0.9714/0.9905/两组加权）+ 决策 + 口径防御话术（module-053 更新标注） |

## 7. 验收标准逐条对照（AC 9 节）

| 节 | 标准 | 结果 | 依据 |
|----|------|------|------|
| §1-1 | documents 补两列（幂等） | ✅ 通过 | 实查存在 + 迁移脚本二次运行跳过 |
| §1-2 | feedback 表已建（对齐 FEEDBACK_DDL） | ✅ 通过 | 6 列实查 |
| §1-3 | search_related 不再报 last_mentioned_at 错误 | ✅ 通过 | 缺列根因消除，Developer 实测真实返回 |
| §2-1 | 基线落地 eval_runs（本次 commit 锚点） | ✅ 通过 | id=17，commit 1076d413，0.9714 复现与 id=13 一致 |
| §2-2 | 口径钉死并声明 | ✅ 通过 | 评估直调 retriever 纯两通道已核实；声明在 changelog §0/§2 + eval 脚本 scores（fusion_mode 落库）+ compare 警告行 + 简历 2.4 四处同步 |
| §3-1 | RRF 公式 k=60 1-based 三路 | ✅ 通过 | `_fuse_rrf` 代码 + 已知值测试精确断言 |
| §3-2 | 开关 hybrid（默认）/rrf + 默认零回归 | ✅ 通过 | config 默认 hybrid；全量 645/0 + 存量测试零改动 |
| §3-3 | RRF 仅 round 0 + 注释 | ✅ 通过 | round_num 参数 + engine/retriever 注释 |
| §3-4 | golden --compare delta 落 eval_runs | ✅ 通过 | id=18（fusion_mode=rrf）+ id=19/20 |
| §4-1 | 加权消融 ≥2 组 + 对比 RRF | ✅ 通过 | 0.3/0.6/0.1（id=19）+ 0.25/0.5/0.25（id=20） |
| §4-2 | "RRF vs 加权"实测对比结论 | ✅ 通过 | RRF 0.9905 > 加权 = 基线 0.9714；结论写入 changelog §4 |
| §5-1 | 放行决策：≥基线选增益最大 + 保留 hybrid 回退 | ✅ 通过 | RRF 唯一增益（+0.0191，0 回退），加权否决理由明确；PW_RETRIEVAL_FUSION_MODE 一键切换 |
| §5-2 | 结论写入 changelog + 简历 2.4 | ✅ 通过 | 已核 |
| §6-1 | 单路失败不参与融合不崩 + rrf 异常回退 hybrid | ✅ 通过 | gather(return_exceptions=True) + 逐路降级 + try/except 回退 `_execute`，测试覆盖 |
| §6-2 | 图谱不可用 → 标"待环境" | ✅ 不适用 | DB 修复后图谱真实可用（无需降级标注）；无降级场景触发 |
| §6-3 | 全量 pytest 614+ 全绿 | ✅ 通过 | 645 passed / 0 failed |
| §7-1 | abs_cosine 不破坏 | ✅ 通过 | 代码 + 测试断言 |
| §7-2 | reranker.py 不动 | ✅ 通过 | git status 无变更 |
| §7-3 | ChatResponse/返回结构不变 | ✅ 通过 | 仅追加 graph_score/rrf_score 字段，接口签名 `retrieve(query, top_k, session, mode, source_pattern, round_num=0)` 尾参位置兼容 |
| §8-1 | test_rrf_fusion.py 覆盖点 | ✅ 通过 | 16 用例全覆盖（公式/排序/开关/降级/abs_cosine） |
| §8-2 | 全量 614+ 全绿不改存量 | ✅ 通过 | 645/0 + git status 证实 |
| §9-1 | changelog/review-report/test-report | ✅ 通过 | 三件套齐全（本报告为最后一件） |
| §9-2 | project-context 行 + 头部日期 + ADR 索引 | ✅ 通过（无新增 ADR，不适用 ADR 索引追加） | 行 + 日期已核 |
| §9-3 | agent-activity-log 三条 | ✅ 通过 | Dev/Rev 已存在 + 本报告追加 Test |
| §9-4 | file-index 新文件行 | ✅ 通过 | 两新行 |
| §9-5 | 简历 2.4 节更新 | ✅ 通过 | 已核 |
| §9-6 | 开工前读 project-context | ✅ 通过 | changelog 注明"开工前已读"；本报告亦经 project-context 全文核对 |

**汇总：27 项通过 / 1 项不适用（§6-2，DB 修复后图谱真实可用）/ 0 失败 / 0 阻塞。**

## 8. 非阻塞附注（Reviewer 6 项 minor 复核）

1. `retrieval_fusion_mode` 无枚举校验（非法值静默落 rrf 分支）——非阻塞，建议后续 Literal 白名单（默认配置不受影响）
2. 引擎 rrf 分支 embedding 故障无图兜底（与 hybrid 分支不对称）——rrf 模式固有语义，changelog 已声明未真实 HTTP E2E，建议上线前真实对话冒烟时覆盖
3. 基线 id=17 scores 无 fusion_mode 字段——运行顺序所致，compare_runs 默认 hybrid 兜底正确，无实际影响
4. weighted 经 `_execute_fusion` 全流程无直测——纯函数 + golden id=19/20 实测兜底，非缺陷
5. module-033 changelog 并行会话改动——提交时按归属区分
6. engine 口径差异已声明（HyDE 图实体提取 vs 评估原 query）——材料完整

## 9. 结论

**验收通过，模块标记 ✅ 完成。** 全量 645/0、新增 16/16、基线/RRF/加权数字与 changelog 逐位一致、2 题翻盘 0 回退复算吻合、红线（abs_cosine/reranker/round 0 语义）代码级确认、记忆三文件硬核查齐备、AC 9 节全过。
