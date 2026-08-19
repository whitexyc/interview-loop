# ADR-0007 — 记忆系统进化机制（强化/衰减/升级/会话摘要 + 记忆纠错）

- 状态：✅ **已实施（module-046，2026-08-10）**——用户 P1 决议直接实施，3 个工作包全部落地，全量 pytest 503 passed 全绿（基线 448 + 新增 55；含 review 修复回归 3 例：recall_short 按新 score 降序重排 + 提及刷新仅覆盖过硬上限项）；**P0+P1 记忆纠错已实施（module-061，2026-08-13）**——P0 升级留后悔药（升级不删短期副本 + 长期 superseded=false/updated_at + 召回过滤）+ P1 写路径冲突消解（mDeBERTa NLI 判矛盾 → 旧父块 SUPERSEDED 不删除 + 新内容正常新增），评测基线未达门槛（contradiction Recall 0.5<0.8）→ `PW_MEMORY_CONFLICT` 默认 false（不预设成功），全量 pytest 824 passed 全绿；**P2 类型化衰减 + P3 冷记忆降权已实施（module-062，2026-08-13）**——P2 documents.type 列 + `_evolve_recall` 按 type 差异化半衰期（preference 30 天慢 / event 1 天快 / 其余=现状 3 天零回归，`PW_MEMORY_TYPE_DECAY` 默认 true）+ 类型来源双方案实测（clf 1.0000 / LLM 1.0000 同分 → 取 clf，`memory_type_mode="clf"`，eval_runs id=32/33）；P3 documents.last_recalled_at 列 + 长期层冷记忆降权（久未召回 ×0.3-1.0 不删除 + 召回命中刷新升温，`PW_MEMORY_COLD_DECAY` 默认 true）；**WP4 矛盾检测对比启用（module-062）**——自建 142 案例分类器（contradiction Precision 0.9048/Recall 0.95，eval_runs id=34）vs mDeBERTa（Precision 1.0000/Recall 0.5，id=35）同集对比，按用户决策"Precision≥0.8 者启用、双达标取 Precision 高者"→ **mDeBERTa（nli）启用，`PW_MEMORY_CONFLICT=true` + `PW_MEMORY_CONFLICT_JUDGE=nli`**（覆盖 module-061 默认关；Recall 后续提升入 backlog），全量 pytest 895 passed 全绿；**P1 双判共识已实施（module-070，2026-08-18）**——nli+clf 双确认 contradiction 才标 superseded（AND 共识 Precision 极保守）+ 单判 contradiction → conflict_hint 新旧并存 + 任一裁判不可用对称回退单判（clf 缺失→nli 单判=现状零回归）；70 条真实跑分（eval_runs id=46/47/48，scores 含 judge 字段）：dual Precision 0.9412（fp=1）> nli 0.9167（30 条口径 1.0 假象证实）> clf 0.8158（人造分布缩水 fp=7）→ **`PW_MEMORY_CONFLICT_JUDGE` 默认改 `dual`**（nli/clf 一键切换保留；dual Recall 0.4 为 AND 共识数学性质=无害漏判拼接共存），全量 pytest 1152 passed 全绿
- 日期：2026-08-10（2026-08-13、2026-08-18 更新）
- 背景：用户追问记忆系统三个问题——① 长期记忆只靠 LLM 判断有没有问题；② 短期记忆能否"反复提及强化 / 长期未提衰减 / 升级为长期"；③ 会话记忆 20 条窗口失忆怎么解决。本 ADR 记录讨论结论：现状基线 + LLM 判断的问题 + 可设计的进化机制（人脑记忆类比）。

## 现状基线（代码事实，module-023/032/033/034/035）

**三层记忆**（全部复用 documents 表 + source 前缀隔离，无新表）：
- **长期** `memory:<identity>:`：LLM 提取（`extract_facts`）+ importance≥0.6 过滤，**永久**（无 TTL）
- **短期** `memory:<identity>:short:`：固定 **7 天 TTL**（`memory_short_ttl_days`），**惰性过期**（recall_short 召回时按 created_at 过滤，无定时清理；无 created_at 记录 fail-open 保留）
- **会话** `memory:<identity>:session:`：持久化上限 **50 条**（`memory_session_max_messages`，超限滚动删最旧）、注入取**最近 20 条**（`memory_session_history_limit`）
- 动态 K 召回（绝对余弦口径，module-035）、语义去重（>0.85 合并，module-035 校准）

## 问题 1 · 长期记忆只靠 LLM 判断的问题（诚实交代）

| 问题 | 说明 |
|---|---|
| 分数未校准 | LLM 自报 importance 与 intent confidence 同坑——未经概率校准，0.9 不代表 90% 值得记 |
| 一次判断定生死 | 对话结束单次调用，漏提取即永久丢失（无复核） |
| 无评测闭环 | 没有 ground truth 标注集验证提取准不准（对比：检索有 golden 集，记忆提取没有） |
| 无反馈纠正 | 用户没纠正，错记忆一直留 |

**改进方向（与 intent 校验同构）**：建"记忆提取标注集"量化 P/R；长期可换 bge-m3+逻辑回归小分类器（importance 分类），复用 ADR-0003 L4 基建。

## 问题 2 · 短期记忆进化机制（可设计，人脑类比）

现状是 7 天 TTL 一刀切。可设计：

### ① 反复提及 → 强化（recency + frequency boost）
- 每次提及刷新"最后提及时间 + 提及次数+1"
- 召回加权：`最终分 = 语义分 × (1 + α×提及次数)`，最近提过的排前面
- 类比：人脑反复复习会巩固

### ② 长期未提 → 加速衰减（遗忘曲线）
- **指数衰减替代一刀切 TTL**：`分数 = 基础分 × 0.5^((today - last_mentioned)/half_life)`，半衰期 ~3 天
- 7 天前还 100 分、第 8 天直接 0 分的"悬崖式"过期 → 连续平滑衰减（Ebbinghaus 遗忘曲线思想）
- 落地：记忆存 last_mentioned_at，召回时算衰减系数

### ③ 短期 → 长期升级（进化机制核心）
| 升级规则（可设计） | 人话 |
|---|---|
| 7 天内提及 ≥2 次 → 升级长期 | 频率=重要性信号 |
| 与长期记忆去重命中（cosine>0.85）→ 合并 | 复用现有去重机制，并入旧记忆 |
| 用户明确"记住" → 强制沉淀 | 最高优先级信号 |
| 升级后删除短期副本 | 防重复 |

类比：短期=草稿纸，反复用到的抄进笔记本（长期），抄完扔草稿纸。

## 问题 3 · 会话记忆失忆解法（可设计）

现状：注入最近 20 条（≈10 轮），早期对话截断。

**分层注入 = 早期摘要 + 最近窗口 + 长期兜底**：
```
注入 prompt = 早期摘要（LLM 压缩） + 最近 20 条（原样）
```
- 早期对话 → LLM 压缩成摘要（会议纪要式），几十轮压成几行
- 最近 20 条 → 原样保留，近期细节鲜活
- 摘要增量更新：`新摘要 = 摘要(旧摘要 + 新对话)`，异步不阻塞
- 双保险：关键结论同时被 extract_facts 沉淀长期层——摘要丢了长期层还有
- 类比：最近聊的记得清（窗口）、更早靠会议纪要（摘要）、最重要的记笔记本（长期）

## 暂不实施的理由

1. 现有三层记忆已可用（去重/动态K/TTL/身份隔离齐全），进化机制属增强
2. 记忆改动影响面大（写路径/召回路径/评测口径），无评测闭环前贸然改有"改坏记忆"风险
3. 优先级：先做记忆提取评测闭环（问题 1 的标注集），用数据决定要不要上强化/衰减

## 业界对标（2026-08-10 调研，验证方案方向正确）

调研结论：**本 ADR 的强化/衰减/升级/摘要机制，业界全部有成熟实现**——方案不是"想当然"，而是踩在主流方案上。

### MemGPT / Letta（2023 论文《MemGPT: Towards LLMs as Operating Systems》）

- 核心思想：上下文当"内存"、外部存储当"硬盘"，**LLM 自己管理换入换出**（paging in/out）
- 主上下文 = 系统指令 + working context（模型可写的事实笔记本）+ FIFO 最近消息队列
- 外部上下文 = recall storage（全量历史）+ archival storage（归档事实）
- **Queue Manager 递归摘要**：上下文接近上限 → FIFO 驱逐旧消息 → `新摘要 = 摘要(旧摘要 + 被驱逐消息)` 塞回队列——**会话失忆解法的业界标准，公式与本 ADR 一致**
- **LLM 自主管理升级**：模型通过 function call 决定"这条写入持久层"（= 短期→长期升级）——业界用 LLM 判断而非纯规则
- 已改名 Letta 框架（2024-09）

### Generative Agents（斯坦福 AI 小镇，2023）

- **记忆流打分公式**：`每条记忆分数 = recency(最近性) + importance(重要性) + relevance(相关性)`
- **recency 指数衰减**：decay factor = 0.995 按轮次衰减——**"强化/衰减"的业界实现**
- importance：LLM 打分 0-10——与本项目 extract_facts 的 importance 同构
- **反思（reflection）**：定期对记忆流做高层抽象总结沉淀"反思记忆"——摘要机制的另一种形式

### Mem0（LLM 记忆层框架）

- `add / update / delete` 三类操作：LLM 判断新信息是否值得存、是否与旧记忆**冲突**（"用户搬家了"→ 覆盖旧地址）
- 对比本项目：我们只有相似合并（cosine>0.85），Mem0 会主动更新/删除旧记忆——冲突处理可借鉴

### Elastic / MongoDB / 通用共识

- 短时记忆 = 上下文窗口（RAM 类比）、长时记忆 = 向量库（硬盘类比）——一致共识
- **"失忆"三原因**（iqilian 文章）：① 被窗口挤掉（容量限制非 bug）② 没写进长期（跨会话失忆主因）③ 写了没召回（检索质量）——排查思路可直接用
- **遗忘机制**（pmkg 文章）：时间衰减因子 + 访问频率——与本 ADR 的强化/衰减设计一字不差

### 对照表

| 本项目机制 | 业界对应 | 现状 |
|---|---|---|
| 反复提及强化 | Generative Agents recency/frequency、pmkg"访问频率" | ❌ 未实现 |
| 时间衰减 | Generative Agents decay=0.995 指数衰减 | ❌ 7 天 TTL 一刀切 |
| 短期→长期升级 | MemGPT LLM 自主 paging out、Mem0 update | ❌ 未实现（有去重合并） |
| 会话失忆→摘要 | **MemGPT 递归摘要（公式一致）**、session summaries | ❌ 只有 20 条窗口 |
| LLM 判断重要性 | Generative Agents importance（0-10） | ✅ extract_facts importance≥0.6 |
| 冲突处理 | Mem0 add/update/delete | ⚠️ 只有相似合并 |

### 可借鉴的三个升级点

1. **会话摘要直接用 MemGPT 公式**（本 ADR 已写对）：`新摘要 = 摘要(旧摘要 + 新对话)`
2. **衰减抄 Generative Agents**：decay factor=0.995 按轮次衰减，比"半衰期 3 天"更细可调
3. **升级机制混合**：规则（提及≥2 次）兜底 + LLM 判断提升（"用户明确说记住"）

## 面试话术

> "长期记忆靠 LLM 提取有主观性——importance 是自报的没校准，也没有评测闭环，改进方向是标注集+小分类器（和 intent 校验同构）。短期记忆目前是固定 7 天 TTL 一刀切，可以设计成人脑式：反复提及给新鲜度加权强化、长期未提按遗忘曲线指数衰减、提及多次或用户明确要求就升级为长期。会话记忆失忆的解法是分层注入——早期对话压缩成摘要 + 最近 20 条窗口 + 关键结论沉淀长期层，三层各管一段不丢信息。"
>
> 追问（业界调研）："我调研过业界记忆方案：MemGPT 用内存层级让 LLM 自主管理换入换出，Queue Manager 的递归摘要（旧摘要+新对话）就是长对话失忆的标准解法；Generative Agents 给每条记忆按 recency+importance+relevance 打分、recency 指数衰减（decay=0.995），这就是强化/衰减机制的业界实现；Mem0 提供 add/update/delete 做冲突处理。我的三层记忆架构和这些方案同构，但还缺 recency 加权、时间衰减和摘要压缩——这些是我标注的进化方向，业界有成熟公式可以直接借鉴。"

## 与既有决策的关系

- 复用 module-035 绝对余弦（去重/动态K口径）、module-033 语义去重（升级合并复用）
- 方法论与 ADR-0003/0005/0006 一致：先度量后干预、评测驱动、诚实交代局限

---

## 实施记录（module-046，2026-08-10）

用户 P1 决议：直接实施（推翻"暂不实施"）。3 个工作包：

- **WP1 短期记忆进化**（Dev-A）：Document 加 last_mentioned_at/mention_count（仅
  短期层）；save_short 去重命中刷新提及；recall_short 进化（30 天硬上限 +
  0.5^(age/3) 半衰期衰减替代一刀切 TTL + (1+0.2×count) 提及加权 + 召回命中刷新 +
  count≥2 且 7 天内升级长期并删短期副本，content_hash 幂等）；engine"记住"正则
  直接沉淀长期层。零迁移 fail-open：存量 NULL/0 按 created_at 衰减。
- **WP2 会话摘要**（Dev-B）：超限滚动删除前最旧消息段 LLM 压缩成摘要（documents
  表 source='memory:<id>:session_summary:'，无向量，仅顺序读最新一条）；增量更新
  新摘要=摘要(旧摘要+新对话段)（MemGPT 递归公式）；摘要失败 fail-open 不阻塞；
  engine 组装 history 分层注入 = 早期摘要段 + 最近 20 条原样（≤20 条零回归）。
- **WP3 提取评测闭环**（Dev-B）：eval/golden_memory.py——28 条标注集（22 应提取
  + 6 不应提取防过度提取），extract_facts 输出 vs 标注 P/R/F1（micro 口径，
  归一化包含匹配），eval_runs eval_type='memory_extraction' 版本化落库，
  --fixture 关键词启发式不依赖 LLM。

**实施后状态核对（与决策正文差异）**：
- 问题 1"分数未校准/一次判断定生死"：本模块落地评测闭环（P/R 可量化），
  importance 概率校准小分类器仍未实施（需标注数据积累，见 roadmap 待办）——决策
  正文"改进方向"部分兑现其一。
- 问题 2 ②衰减：采用半衰期公式 0.5^(age/3)（决策正文"业界对标"建议 decay 按轮次
  更细可调，落地取半衰期口径，plan 3.2 定稿如此）。
- 问题 2 ③升级：落地规则（提及≥2 次）兜底 + 用户"记住"最高优先级；LLM 自主
  paging out（MemGPT 方式）未引入。
- 问题 3 双保险：摘要层新增，extract_facts 沉淀长期层不变。

**已知边界（如实记录）**：
- 本地开发库 schema 未迁移（documents 表尚无两新列），部署前需 ALTER TABLE。
- 摘要段在 reflector 纯反射路径可能被最后 6 条截断（reflector 不在本模块清单）。
- golden_memory 真实模式 baseline 需 LLM 环境补跑（fixture 冒烟已验证管线）。
