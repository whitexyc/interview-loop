# ADR-0006 — 分块策略优化方案（段落级优先 + 上下文检索 + 评估驱动）

- 状态：📋 方案已定，**暂不实施**（2026-08-10 决议：当前 Hit@5 0.96 已达标，改动牵动四层数据回归风险高，收益未经验证；待消融实验有数据支撑再实施）
- 日期：2026-08-10
- 背景：审查 `rag/chunker.py` 父子两级分块后，结合 RAG 社区方法论（上下文检索 Contextual Retrieval / small-to-big / 评估驱动），产出一版更优的切分方案。**本 ADR 记录方案与思路，不落地实现**——作为面试弹药与后续迭代依据。

## 当前实现（基线，module-031 重建后）

- 一级：`MarkdownHeaderTextSplitter` 按 ##/### 标题切父块（≤4000 字符，二次按段落切）
- 二级：每父块用 `RecursiveCharacterTextSplitter` 按 **固定目标 300 字符**（重叠 50）切子块
- 子块携带向量 + search_tokens 参与检索，命中后 `_expand_to_parents()` 映射回父块返回
- 无标题文档 fallback：整篇单父块（靠 4000 上限兜底）
- 已知权衡：子块固定 300 目标"凑"而非"语义完整"；命中子块返回整个父块（父块多大返回多大，4000 只是上限非固定值）

## 优化方案（四步，按性价比）

### Step 1 · 子块切分升级：段落级优先（切分侧，P1）

- 现状：固定目标 300 字符，切点可能落在概念中间
- 方案：`child_splitter` 改为**段落级优先**——先按 `\n\n` 切段落，段落 ≤300 字符整段作为子块；**仅超长段落**（>300）内部再按句切
- 依据：知识库是 Markdown 结构化笔记，**段落本身就是语义单元**；"G1 的 Region 机制"往往正好一段，整段作子块语义完整
- 代价：子块大小不均（几百到上千字）——向量检索对大小不敏感，但 rerank batch 填充、嵌入截断需注意上限
- 验证：golden 集对比"300 字符 vs 段落级"Hit@5（复用 eval_runs 版本化）

### Step 2 · 上下文检索：子块向量拼标题路径（检索侧，P0 最值得做）

- 现状：子块只对 `content` 向量化，标题路径（"板块6 > 题目2"）不参与
- 方案：`embed_text(f"{title}\n{content}")`
- 依据：标题是最强语义锚点——query"G1 的 Region 机制"可能命不中只讲"Region 可扮演 Eden 角色"的子块，但标题"1-G1垃圾收集器的Region分区机制"一拼上相似度显著提升（Anthropic Contextual Retrieval 的最便宜版，零额外 LLM 调用）
- 成本：改 1 行 + 全量重嵌入（124 篇本地 bge-m3，分钟级）
- 验证：重灌后 golden Hit@5 对比——**最可能直接提指标的一项**

### Step 3 · 返回粒度：超大父块条件触发命中窗口（返回侧，P2）

- 现状：子块命中 → 返回整个父块（父块多大返回多大）
- 方案：仅对**超大父块**（如 >1500 字）做"命中子块 + 相邻兄弟块"窗口返回；小父块维持现状
- 依据：大部分父块 <4000（且多数不大），返回整块冗余不严重——**先度量分布再决定阈值**，不全局改
- 验证：人工抽检答案质量 + token 消耗对比

### Step 4 · 评估驱动闭环（前提，P0）

- 分块参数（child_chunk_size / max_parent_chars / overlap）纳入 eval_runs config 快照 → 改参数可 `--compare` 对比
- 子块大小消融：200/300/400/500 四档跑 Hit@5，用数据定最优（300 是经验值）
- 重索引复用：`reindex_knowledge_base.py`（module-031，按 title 先删后建、幂等、--dry-run、--no-graph）

## 暂不实施的理由（面试必讲）

1. **当前已达标**：Hit@5 0.96（23/30 有效），分块改动收益不确定，属"锦上添花"非"雪中送炭"
2. **牵动四层数据**：分块策略变更 = 子块向量 + FTS 倒排 + 父块 + 图谱（实体指向父块 id）全部重建，回归风险高
3. **成本不低**：重灌分钟级（嵌入）+ 图谱逐篇 LLM 提取（慢项）
4. **优先级判断**：若要提检索质量，Step 2（拼标题）性价比最高；切分侧（Step 1）必须消融验证后才动

## 业界对标（2026-08-10 调研，验证方案方向正确）

调研结论：**当前架构（标题层级 + 递归 + 父子）即业界 production default，本 ADR 优化方向有硬数据背书**。

### 业界共识（2026 多来源交叉验证）

- **核心张力**：检索要小块（聚焦）、生成要大块（完整）——相反方向；small-to-big 是标准解法
- **硬数据**：2026 跨域研究 content-aware 分块显著优于固定长度（nDCG@5 ≈ 59% vs 24.4%）；"lost in the middle" 效应（chunk 太大降性能）
- **Production default**（sureprompts 明确断言）："Recursive + parent-document 是生产默认；Fixed-size 只配周末原型；**先修分块再换 embedding/reranker——分块设定天花板，其他都是抬高地板**"
- **Chunk size 是超参数**：256/512/1024 在评测集上找拐点（viqus/sureprompts 一致）——本 ADR Step 4 消融同思路

### 关键新发现（对本 ADR 有影响）

| 发现 | 来源 | 对本 ADR 的意义 |
|---|---|---|
| **Anthropic contextual retrieval：每 chunk 加 LLM 生成 50-100 词情境摘要 → recall 提升 35-50%** | aiengineeringfromscratch | **验证 Step 2（子块向量拼标题）是"最值得做"**——业界硬数据，零 LLM 成本版已是最优性价比 |
| **2026 新发现：overlap 常零收益还翻倍索引成本**（SPLADE+Mistral on NQ） | aiengineeringfromscratch | 当前 50 字符重叠需消融验证（但该发现针对 token 级，小 chunk 保护作用需实测） |
| **parent 必须是 meaningful unit**——若只是"child 周围 N tokens"就退回 fixed-size | sureprompts | 父块是标题 section（meaningful）✅；超大 section 命中窗口优化仍成立 |
| **语义分块需 min-token floor**（防 40-token 碎片） | aiengineeringfromscratch | 若做语义分块需最小块保护 |
| **metadata 带标题层级**（"Chapter 3 > Section 3.2"）助检索与引用 | viqus | 标题路径 metadata 已是正确实践 ✅ |
| **late chunking**（2026 前沿）：先整篇 token 级嵌入再 pooling 成 chunk 向量 | dronahq | 未做，长期方向 |
| **Read the chunks, not just the metrics** | sureprompts | 排障方法论：指标聚合不诊断，失败看实际 chunk |

### 2026 决策表（aiengineeringfromscratch）

| 场景 | 推荐 |
|---|---|
| 未知语料起步 | Recursive 512 tokens，**no overlap** |
| Factoid QA | Recursive 256-512 |
| 分析/多跳 | Recursive 512-1024 + parent-document |
| 重交叉引用（合同/论文） | Late chunking 或 contextual retrieval |
| 对话语料 | Turn-level chunks + speaker metadata |

### 对照表

| 本项目实现 | 业界 | 判定 |
|---|---|---|
| 标题层级切父块（Markdown） | document-structure-aware（最适合结构化文档） | ✅ 一致 |
| 递归切子块（固定目标 300） | recursive（80% 场景起点） | ✅ 一致 |
| 父子映射（small-to-big） | parent-child = production default | ✅ 一致 |
| 标题路径 metadata | metadata enrichment（heading structure） | ✅ 已有 |
| 上下文检索（Step 2） | Anthropic contextual retrieval（**35-50% 提升**） | ✅ 方向对，硬数据背书 |
| 消融验证（Step 4） | 256/512/1024 评测找拐点 | ✅ 同思路 |
| 重叠 50 字符 | 2026 新发现 overlap 常零收益 | ⚠️ 需消融验证 |
| Late chunking | 2026 前沿 | 🔬 未做 |

## 面试话术

> "我有一版更优的分块方案但没实施：一是子块从固定 300 字符改成段落级优先——知识库是结构化笔记，段落就是语义单元，整段作子块语义更完整；二是上下文检索——子块向量拼上标题路径，标题是最强语义锚点，零额外 LLM 成本最可能提召回；三是返回粒度——超大父块才做命中窗口，小父块不动，先度量分布再定阈值。没实施的原因：当前 Hit@5 0.96 已达标，分块改动牵动向量、FTS、父块、图谱四层数据重建，回归风险高，收益未经验证；如果要做，我会先用 golden 集消融对比'300 字符 vs 段落级'，有数据支撑再动。重索引基建已经有了（module-031 reindex 脚本），改完直接跑 + --compare 验证。"
>
> 追问（业界调研）："我的分块架构——标题层级切父块、递归切子块、父子映射——正是业界 2026 的 production default：sureprompts 明确说 recursive + parent-document 是生产标配，小 chunk 检索精确、大 chunk 生成完整。优化方向也有硬数据背书：Anthropic 的 contextual retrieval（每 chunk 加情境摘要）实测 recall 提升 35-50%，所以我把'子块向量拼标题'列为最值得做；chunk size 是超参数，业界一致推荐 256/512/1024 在评测集上找拐点，我的消融方案完全一致。另外 2026 新发现 overlap 常零收益还翻倍索引成本，我的 50 字符重叠也值得重新验证。"

## 与既有决策的关系

- 复用 module-031（重索引基建）、module-035（绝对余弦口径）、eval_runs 版本化（--compare）
- 方法论与 ADR-0003/0005 一致：先度量后干预、评估驱动、不对称投放
