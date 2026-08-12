# CONTEXT.md — 术语表

> Grill with Docs 会话产物。每次讨论涉及的术语在此登记，便于跨会话续接。

## Agentic RAG 简历深挖（2026-08-08 会话）

- **Self-RAG**：论文 arXiv:2310.11511 思想的本项目实现——用 prompt engineering 让 LLM 自我评估检索结果是否充分（未训练 reflection token，`agent/reflector.py` 注释明确承认）。
- **意图路由保守策略**：`agent/router.py` 任何异常（空查询/LLM 失败/解析失败/intent 非法）一律回退 knowledge——"宁多检不漏检"。
- **ReAct 工具注册表（无状态）**：`agent/tool_registry.py` 只存工具定义，执行时 `AgentTool.run(args, ctx)` 注入会话上下文，全局单例并发安全；10 工具：search_knowledge/search_fts/search_vector/search_graph/extract_entities/recall_memory/generate_answer/verify_answer/re_search/note_to_self。
- **工具 15s 超时围栏**：`AgentTool.run` 内 `asyncio.wait_for(..., 15)`，超时返回"执行超时"、失败返回空串——工具失败由 LLM 判断继续/放弃（降级哲学）。
- **alpha=0.3 混合检索**：`rag/retriever.py`，30% FTS + 70% 向量，min-max 归一化（保持序关系）后加权融合；asyncpg 单连接禁止并发 → FTS/向量各开独立 session 再 gather 并行（module-026）。
- **三通道 vs 两通道（关键差异）**：`hybrid_retriever` 仅 FTS+向量加权融合；图谱第三路仅在流式 `engine._retrieve()` round 0 并行检索后按 id 合并去重（graph_score 独立，不参与 hybrid_score 加权）。非流式 `chat()` 不含图。
- **图谱相关度**：`graph_store.search_related` Cypher 统计每文档被「查询实体∪一跳邻居」引用次数 → min-max 归一化 → 全同分保底 0.6。
- **父子分块**：`rag/chunker.py` 父块（##/### 标题，≤4000 字符，无向量）+ 子块（~300 字符重叠 50，带向量 + jieba search_tokens）；子块命中 `_expand_to_parents` 映射回父块。
- **jieba 中文 FTS 复活**：`rag/text_tokenizer.py`，PG 'simple' 配置对连续中文按整串作单个 lexeme 必空召回（基线 Hit@5=0）→ jieba 预分词空格连接落 search_tokens 列 + 查询侧同源分词。
- **CrossEncoder 重排**：`rag/reranker.py` bge-reranker-v2-m3（分类式 ~515ms/对，替代生成式 Qwen3 的 ~6s/对）；内容截断 500 字符（防 batch 最长序列填充把 ~0.5s 拖到 ~200s）；threading.Lock 串行化；缺权重明确报错不回退在线加载。
- **逐句幻觉检测**：`reflector.verify_answer` 拆答案为 claims，标 supported/inferred/unsupported + evidence 引用号，越界引用号强制降级 unsupported；置信度 = 1 - unsupported/total；温度 0，15s 超时返回空。
- **本地嵌入**：`rag/embeddings.py` bge-m3 GGUF（llama-cpp，CLS pooling 1024 维，L2 归一化）；threading.Lock（to_thread 真线程，asyncio.Lock 无法跨线程互斥，module-027 GGML_ASSERT 坑）。
- **三层记忆**：`rag/memory.py` 长期 `memory:<id>:` / 短期 `memory:<id>:short:`（TTL 7 天惰性过期）/ `rag/session_memory.py` 会话 `memory:<id>:session:`（无向量，上限 50 滚动删除）；source 尾冒号分隔身份防前缀重叠泄漏。
- **记忆隔离双保险**：`_normalize_identity` 拒绝 LIKE 元字符（%_\）+ `_escape_like` 转义；知识库检索默认 `NOT LIKE 'memory:%'`。
- **语义去重 + 动态 K**：记忆写入前与同层现有记忆 cosine>0.85 视为重复→更新父块不新增；召回用绝对余弦（点积=cosine，embedding 已 L2 归一化），<0.4 丢弃，均值>0.85→5条 / 0.75-0.85→3条 / <0.75→1条。
- **时限预算**：`engine._retrieve()` 30s 总 deadline + 级联 wait_for（检索 15/反思 10/记忆 5/会话 3/verify 15/HyDE 10）。
- **降级链**：`llm/client.py` FallbackClient qwen→zhipu→deepseek（PW_FALLBACK_CHAIN，运行时 Redis 可调）；温度透传；DeepSeek thinking 需 reasoning_content 原样回传（走 async_client.create 而非 bind_tools）。
- **参数化缓存**：`src/cache.py` Redis 懒连接；键 = sha256(query+top_k+min_score)[:16]（防不同参数复用同键）；HyDE 独立键；TTL 300s；SCAN 分批失效；Redis 故障静默降级。
- **输入校验**：`rag/schemas.py` query max_length=2000（违反→422）；history>20 静默截断（保留最近 20）；MAX_ANSWER_LEN=10000 截断。
- **评测**：`eval/golden_retrieval.py` 30 题 golden（6 类别），Hit@k/Recall@k/MRR，eval_runs 表版本化（git_commit+配置快照），--compare/--ablate；标题层级前缀容错（"X > 板块3" split 最左段比对）。
- **0.96 口径**：30 题中 23 题有效（剔 7 无覆盖），FTS 0.43 / 向量 0.87 / 融合 0.96（简历 01 完整口径）；⚠️ 评估脚本 hybrid 模式实为两通道，与流式链路三通道需主动区分。

## intent 校验领域（2026-08-08 讨论）

- **LLM 自报 confidence（不可信，但低置信是有效信号）**：`router.py` 的 `confidence` 字段是 LLM 在 prompt 要求下自评的 0-1 数字，未经概率校准**不能当真实概率用**——但 module-043 后不再"只展示"：**低置信（<0.5）触发 L2 确定性信号确认**（`_L2_CONFIDENCE_THRESHOLD=0.5`，`intent≠knowledge 且 confidence<0.5` 时）。解析失败兜底 0.5。
- **intent 产生链路（LLM 提议 + 代码裁决）**：`router.py` prompt 要求 LLM 返回 `{"intent","confidence","reason"}` → `_parse_response` 截 `{}` 块再 json.loads → **白名单校验**（intent ∈ knowledge/casual_chat/realtime，否则回退 knowledge）→ 四个保守回退口（空查询/LLM 异常/解析失败/intent 非法）全部落 knowledge。module-043 后：L4 分类器可用时替换 LLM 决策主体，L2 确定性信号确认在 LLM 低置信时修正意图。
- **决策字段 vs 展示字段（module-043 后修订）**：intent 是路由决策依据（错了就答非所问）→ 白名单 + L2/L3/L4 四层校验；confidence 是 LLM 自评 → 低置信仅作 L2 触发信号，仍不做绝对概率解读。**决策字段要校验，展示字段低置信可当"不放心"信号**。
- **值合法 vs 类正确（✅ 已解决）**：白名单解决"值合法"，类正确性由 module-043 四层校验解决——L1 离线评测（有 ground truth）+ L2/L3 在线间接信号（无 ground truth）+ L4 分类器校准概率。
- **不对称校验（单向信任，module-043 L2 落地）**：走 knowledge 是默认低风险（多检只多 0.5s）；跳过检索才是高风险（漏检答非所问）。校验预算不对称投放：只对 intent≠knowledge 且低置信（<0.5）的结果做确认。⚠️ **修订版：确认信号是确定性信号而非 LLM 二次确认**（同源复核不可靠已否决，红线=确认路径零 LLM）——`router.py::_deterministic_confirm`：① FTS 术语命中（jieba 分词过滤功能词后匹配 search_tokens 倒排）② 图谱实体命中（Cypher 拉实体名 Python 子串匹配）③ 规则表命中（明确闲聊/实时特征词 → 保持原判，否决巧合命中）。任何异常 → 保守 knowledge。
- **检索反证（后验校验，module-043 L3 落地）**：knowledge 路径精排后 top-1 绝对余弦 < 0.3（`engine.py::_L3_ABS_COSINE_THRESHOLD`）→ 置 `suspected_misclassify` 标记写入 ChatSteps——**先度量后干预**：只可观测、不阻塞、不改回答路径。与 `check_sufficiency`（正向：够不够回答）互为镜像。
- **intent 校验四层方案（✅ 已实现，module-043 / ADR-0003）**：L1 `eval/golden_intent.py` 100 条评测集（knowledge 50/casual_chat 30/realtime 20 含 15 边界易混，Accuracy+P/R/F1+混淆矩阵，eval_runs 落库 eval_type='intent'）；L2 确定性信号确认（见上）；L3 检索反证（见上）；L4 `agent/intent_classifier.py` bge-m3 冻结 + 逻辑回归头（class_weight="balanced"，predict_proba 校准概率，构造器注入/配置开关 `intent_classifier_enabled` 惰性加载，失败回退 LLM 零影响，fit() 预留飞轮）。测试 `tests/test_intent_validation.py` 35 用例 + `tests/test_golden_intent.py` 11 用例。
- **逻辑回归（LogisticRegression）**：经典**分类**算法（名字带"回归"但做分类）。四步：bge-m3 编码 1024 维向量 → 加权求和 z = w·x + b（学一条分割线）→ sigmoid P = 1/(1+e⁻ᶻ) 压成 [0,1] → 阈值决策（P>0.5 → knowledge）。详见 ADR-0003 L4 补充。
- **冻结 vs 训练（freeze vs train）**：bge-m3 是预训练特征提取器、权重固定（冻结）；唯一被训练的是逻辑回归分类头——1025 个参数（1024 权重 + 1 偏置）。参数少、几百条标注数据、sklearn 几秒训练、无需 GPU。代码：`LogisticRegression(max_iter=500).fit(X_train, y_train)`。
- **为什么逻辑回归替代 LLM 分类**：输出**校准过的真概率**（根治 LLM 自报 confidence 不可信）、可解释（权重可分析）、推理毫秒级本地跑、省钱一个量级；代价是需标注数据（golden 集即种子）。
- **min-max 归一化**：`retriever.py::_normalize`，x' = (x-min)/(max-min) 线性映射到 [0,1]；全同分（range<1e-9）给 1.0。**保序**（映射后大小顺序不变），对分数分布无假设（对比 z-score 假设正态）。
- **为什么先归一化再融合**：FTS ts_rank 在 10⁻³ 量级、向量 cosine 在 0.x 量级，不归一化直接加权 = 大数吃小数（0.006×0.3 + 0.90×0.7 ≈ 0.63，FTS 贡献被淹没）。各自 min-max 到 [0,1] 后才可 alpha 加权。
- **为什么只关心相对排序**：检索只选 top-k，只需"谁比谁更相关"（序），不需"有多相关"（绝对分）；min-max 保序。
- **soft 归一化陷阱（module-035 真实踩坑）**：min-max 每次只归当前结果集 → **跨查询分数不可比**。记忆动态 K 旧实现用 min-max hybrid_score 套绝对阈值导致恒 K=1（"本批相对高但绝对烂"）；修复改用**绝对余弦**（embedding 已 L2 归一化，点积=cosine，跨查询可比）。面试讲"分数口径"的加分案例。
- **query 改写时序**：**初始检索用的不是改写后的 query**——非流式 `chat()` 用原始 `request.query`；流式 `_retrieve()` round 0 用 HyDE 扩展 query（扩展≠改写）。改写（rewritten_query）只发生在反思判定不充分之后（engine.py:236/641），用于二次检索，结果与首轮合并去重。链路：意图路由 → 原始检索 → 反思 → 不充分才改写重检。面试区分"HyDE 扩展（提首轮召回）vs 反思改写（补救漏检）"。
- **CrossEncoder（交叉编码器）**：重排架构——query 和 doc 拼接成一句话（`[CLS] query [SEP] doc`）喂同一 Transformer，做完整交叉注意力后直接输出相关性分数。对比 Bi-Encoder（双塔）：query/doc 独立编码成向量再算余弦——"分别看材料凭印象判断（快但粗）vs 并排仔细对比（慢但准）"。
- **为什么用 CrossEncoder 重排**：向量检索是 Bi-Encoder（快但精度有限），CrossEncoder 精度更高但慢（每对 ~0.5s），所以只对召回 Top-20 精排取 Top-5。
- **当前重排模型 = BAAI/bge-reranker-v2-m3**：本地部署（models/bge-reranker-v2-m3/，model.safetensors ~2.17GB），BGE 系列分类式 CrossEncoder，sigmoid 输出分数，CPU ~515ms/对。models/ 目录另存 Qwen3-Reranker-0.6B（生成式实验未走通，不主动讲）、all-MiniLM-L6-v2（历史 embedding，未使用）。
- **重排截断 500 字符（_MAX_PAIR_CHARS）**：CrossEncoder 按 batch 最长序列填充，超长父块（数万字符）把单次 rerank 从 ~0.5s 拖到 ~200s；截断后 2 pair ~2.1s。**选数依据**：500 字符 ≈ 中文 500 字（半页 A4、5-6 句话）；1000 字符 ≈ 1 页 A4，但实测分数 0.991 vs 0.989——精度几乎无提升耗时翻倍；2000 字符 ≈ 2 页 A4，耗时线性涨、精度增益趋零。相关信号集中在前 500 字（标题+开头），500 是"精度-成本"拐点。
- **重排分数普遍接近 1.0（分类式压缩效应）**：bge-reranker-v2-m3 是二分类器（相关/不相关），sigmoid 输出概率；且进重排的候选已被检索层筛过（都是相关的）→ 分数挤在高位（0.85~0.99）。排序只看相对大小不看绝对高低，0.991 vs 0.989 序仍正确（reranker.py:15-16"区分度低是已知特性"）。代价：将来做分数阈值过滤需先 Platt scaling 校准，当前只排序不阻塞。
- **🔬 TODO（待验证）**：重排截断测 250 字符——对比 250 vs 500 分数/耗时，补齐 250/500/1000/2000 四档选数表。见 08 文档 1.4 节。
- **类别平衡（class balance）**：训练样本各类数量需均衡，否则模型偏向多数类。golden 30 题全是 knowledge，L4 训练前必须人工补足 casual_chat/realtime/边界易混样本。
- **F1 分数**：精确率 P 与召回率 R 的调和平均 F1 = 2·P·R/(P+R)。P = TP/(TP+FP)（预测为正的里面真正为正的比例，挑得准不准）；R = TP/(TP+FN)（真正为正的里面被挑出来的比例，挑得全不全）。**P 或 R 任一低都会被惩罚**（调和平均）。
- **为什么用 F1 而不用 Accuracy**：类别不平衡时 Accuracy 骗人——90 条知识库 + 10 条闲聊，模型全猜 knowledge 也有 90% Accuracy，但闲聊全漏检。F1 能暴露"偏科"。
- **混淆矩阵（confusion matrix）**：行=真实类别、列=预测类别的 N×N 计数表；对角线是分类正确（TP/TN），非对角线是易混类对（如 knowledge↔casual_chat）。用途：看"哪两类容易混淆"。intent 评测重点盯 knowledge 的 Recall（漏检率最致命）。

## 反思充分性领域（2026-08-09 讨论）

- **充分性判断现状边界（✅ module-044 后修订）**：`reflector.py::check_sufficiency` 不再"完全由 LLM 说了算"——**层 1 硬闸门先接管"明显不充分"**（文档数 <2 或 top-1 绝对余弦 <`sufficiency_gate_threshold` 默认 0.55 → 零 LLM 直接判不充分）；分数达标才交给 LLM 判模糊地带。LLM 之外共四道非 LLM 闸门：① 空文档短路（docs=[] 不调 LLM）、② 数量硬闸门（文档数<2）、③ 分数硬闸门（abs_cosine<0.55 默认，可配）、④ 超时/失败默认充分（10s 防死循环）。准确表述："LLM 只判模糊地带，边界由代码闸门接管"。
- **充分性精确化五层方案（✅ 层 0/1/2/3 已实现，module-044 / ADR-0005；✅ 层 4 训练代码已就绪未接入）**：L0 `eval/golden_sufficiency.py` 100 条充分性标注集（充分 50+不充分 50，每条 2 篇文档兼容数量闸门，eval_runs 落库 eval_type='sufficiency'，报告大字标 insufficient Recall）；L1 分数/数量硬闸门（文档数<2 或 abs_cosine<0.55 零 LLM 判不充分）；L2 prompt 强化（`_CHECK_PROMPT` CoT 先列信息点再比对 + few-shot 正反例 + 自洽性检查开关 `sufficiency_self_check_enabled` 默认关）；L3 多信号融合（分数达标才问 LLM，LLM 判不充分尊重语义走 rewritten_query）；L4 `eval/train_sufficiency_classifier.py` 充分性分类器（SufficiencyClassifier.fit() + joblib 落盘 sufficiency_clf.joblib，LogisticRegression class_weight=balanced）——训练就绪未接入运行时（与 intent_classifier 同款模式）。方法论闭环：L1 复用 module-035 绝对余弦、L3 复用 ADR-0003 L2 不对称投放、L4 复用 ADR-0003 L4 小分类器。
- **分数硬闸门（层 1，✅ 已实现）**：`reflector.py::_SUFFICIENCY_MIN_DOCS=2` + 分数阈值读配置 `settings.sufficiency_gate_threshold`（module-048，默认 0.55）——文档数 <2 或 top-1 绝对余弦 <0.55 → 直接判不充分零 LLM。绝对余弦口径来自 module-035（L2 归一化点积=cosine，跨查询可比）；`abs_cosine` 由 retriever 归一化前存档（module-037 同名字段），仅 FTS 命中文档无该字段 → 跳过闸门走 LLM 不误杀。阈值先用经验值 0.55，后用标注集做阈值扫描校准（`eval/threshold_scan.py` 已存在）。

## 分块领域（2026-08-10 讨论，ADR-0006）

- **父子两级分块（当前实现，module-031 重建后）**：一级 `MarkdownHeaderTextSplitter` 按 ##/### 标题切父块（≤4000 字符，超限按段落二次切）；二级 `RecursiveCharacterTextSplitter` 按固定目标 300 字符（重叠 50）切子块；子块带向量+search_tokens 参与检索，命中后 `_expand_to_parents()` 映射回父块返回。**关键澄清：4000 是父块尺寸上限非固定值——返回的就是父块实际大小；子块 300 也是"目标大小"固定，切分方式本身已是递归字符（按分隔符优先级）**。
- **small-to-big（小块检索大块返回）**：检索粒度（子块 300）与回答粒度（父块）分离——小块召回精准、大块上下文完整。代价：命中单个小段返回整个父块有冗余（父块多大返多大，非 13 倍常态）。
- **分块策略变更 = 四层数据重建**：子块向量（embedding）+ FTS 倒排（search_tokens）+ 父块 + 知识图谱（实体 doc_id 指向父块 id，父块 id 变则图谱必须清空重提）。复用 `reindex_knowledge_base.py`（module-031：按 title 先删后建、幂等、--dry-run、--no-graph、--skip-import 崩溃恢复）。
- **段落级优先切分（📋 方案未实施，ADR-0006 Step 1）**：子块从固定 300 目标改为"先按段落切，段落 ≤300 整段作子块，仅超长段内部再切"——知识库是结构化笔记，段落即语义单元。
- **上下文检索 Contextual Retrieval（📋 方案未实施，ADR-0006 Step 2，最值得做）**：子块向量拼标题路径 `embed_text(f"{title}\n{content}")`——标题是最强语义锚点，零额外 LLM 调用最可能提召回（Anthropic 思路低成本版）。
- **命中窗口（📋 方案未实施，ADR-0006 Step 3）**：仅对超大父块（>1500 字）做"命中子块+相邻兄弟"窗口返回，小父块维持现状；先度量父块大小分布再定阈值。
- **重索引闭环（评估驱动）**：改分块 → `reindex_knowledge_base.py --dry-run` 看规模 → 全量重建 → `golden_retrieval --compare` 对比 Hit@5 → 有提升才留。分块参数应纳入 eval_runs config 快照。
- **分块业界共识（2026 调研，ADR-0006 业界对标节）**：production default = recursive + parent-document（sureprompts 断言"分块设天花板，其他抬地板"）；content-aware 分块显著优于固定长度（nDCG@5 ≈59% vs 24.4%）；chunk size 是超参数，256/512/1024 评测找拐点。
- **Anthropic Contextual Retrieval（硬数据）**：每 chunk 加 LLM 生成 50-100 词情境摘要 → **recall 提升 35-50%**——验证 ADR-0006 Step 2（子块向量拼标题）为"最值得做"的优化，零 LLM 成本版性价比最高。
- **overlap 2026 新发现**：overlap 常零收益还翻倍索引成本（SPLADE+Mistral on NQ）——当前 50 字符重叠需消融验证（针对 token 级，小 chunk 保护作用需实测）。
- **parent 必须 meaningful unit**：若 parent 只是"child 周围 N tokens"就退回 fixed-size——本项目父块是标题 section（meaningful）✅；超大 section 命中窗口优化仍成立。
- **late chunking（2026 前沿）**：先整篇 token 级嵌入再 pooling 成 chunk 向量，保留跨 chunk 上下文——未采用，长期方向。
- **"先修分块再换模型"（sureprompts 金句）**：更强 embedding 模型配烂 chunk 比中等模型配好 chunk 更差——分块设定检索质量天花板。排障方法论："Read the chunks, not just the metrics"（指标不诊断，失败看实际 chunk）。

## 记忆进化领域（2026-08-10 讨论，ADR-0007）

- **三层记忆基线**：长期 `memory:<identity>:`（LLM 提取 importance≥0.6，永久）；短期 `memory:<identity>:short:`（固定 7 天 TTL，惰性过期——recall_short 召回时按 created_at 过滤，无定时清理，无 created_at fail-open 保留）；会话 `memory:<identity>:session:`（持久化上限 50 条、注入取最近 20 条）。
- **LLM 提取的主观性问题**：importance 是 LLM 自报未校准（与 intent confidence 同坑）；单次调用漏提取即永久丢失；无 ground truth 评测闭环（对比检索有 golden 集）；无用户反馈纠正。改进方向：记忆提取标注集 + bge-m3/逻辑回归小分类器（复用 ADR-0003 L4 基建）。
- **短期强化机制（📋 可设计）**：反复提及 → 刷新 last_mentioned + 次数+1 → 召回加权 `语义分 × (1 + α×提及次数)`（recency/frequency boost，人脑复习巩固类比）。
- **短期衰减机制（📋 可设计）**：指数衰减替代一刀切 TTL——`分数 = 基础分 × 0.5^((today-last_mentioned)/half_life)`，半衰期 ~3 天（Ebbinghaus 遗忘曲线，连续衰减而非悬崖式过期）。
- **短期→长期升级（📋 可设计）**：7 天内提及 ≥2 次升级长期；与长期记忆去重命中（cosine>0.85）合并；用户明确"记住"强制沉淀；升级后删短期副本。类比：短期=草稿纸，反复用到的抄进笔记本（长期）。
- **会话失忆解法（📋 可设计）**：分层注入 = 早期摘要（LLM 压缩，会议纪要式）+ 最近 20 条（原样窗口）；摘要增量更新 `新摘要=摘要(旧摘要+新对话)` 异步不阻塞；关键结论同时被 extract_facts 沉淀长期层双保险。
- **MemGPT / Letta（业界对标，2023）**：上下文当"内存"、外部存储当"硬盘"，LLM 自主管理换入换出（paging in/out）。主上下文 = 系统指令 + working context + FIFO 队列；外部 = recall storage（全量历史）+ archival storage（归档）。**Queue Manager 递归摘要 `新摘要=摘要(旧摘要+被驱逐消息)` = 会话失忆的业界标准解法（与本项目 ADR-0007 公式一致）**。
- **Generative Agents（业界对标，斯坦福 2023）**：记忆流打分 `分数 = recency + importance + relevance`，**recency 指数衰减 decay=0.995**（强化/衰减机制业界实现）；importance 由 LLM 打分 0-10（与 extract_facts 同构）；反思（reflection）定期抽象总结沉淀反思记忆。
- **Mem0（业界对标）**：add/update/delete 三类操作，LLM 判断冲突处理（"搬家"→覆盖旧地址）；对比本项目只有相似合并（cosine>0.85），冲突处理可借鉴。
- **"失忆"三原因排查**（业界共识）：① 被窗口挤掉（容量限制非 bug）② 没写进长期（跨会话失忆主因）③ 写了没召回（检索质量）。排查思路：聊久忘→查窗口；换会话忘→查持久化；存了答不出→查召回。

## 数据飞轮领域（2026-08-10 讨论，ADR-0008）

- **现状盘点**：✅ eval_runs 存 per_question 误判样本；⚠️ 前端 👍/👎 UI 有但**未落库**（ChatMessage.tsx feedbackRating 只在页面内存，后端无 feedback 端点）；❌ 无主动模糊样本收集/人工标注流程/增量训练数据流。核心缺口：**反馈未落库 = 免费标注信号白丢**。
- **五环节飞轮**：A intent（L4 fit() 接口现成，最快闭环 ★★★★）；B 充分性（层 4 分类器待建 ★★★）；C 检索相关性（阈值校准/消融数据 ★★★）；D 答案可信度（幻觉调优 ★★）；E 记忆 importance 校准（解决 LLM 自报不可信 ★★）。
- **飞轮通用流程**：生产数据（误判/低置信/👎）→ 收集入库 → 人工标注 → 增量训练（fit()/重训/阈值重扫）→ --compare 验证 → 上线 → 循环。
- **实施顺序**：P0 feedback 落库（POST /ai/feedback 存表）→ P0 误判样本导出待标注池 → P1 intent/充分性闭环 → P2 记忆校准。

## Query 改写领域（2026-08-10 讨论，ADR-0009）

- **现状基线（反思驱动改写）**：意图路由 → 首轮检索（原始/HyDE）→ 反思判不充分 → LLM 返回 rewritten_query → 二次检索合并 → 最多 3 轮。改写是"事后补救"非预检索优化；HyDE（流式 round 0 前）≠ 改写。
- **现状问题 8 项**：①时机晚 ②单候选无打分 ③无评测闭环 ④HyDE 与改写两套独立 ⑤依赖 LLM 主观 ⑥合并而非择优 ⑦无子查询分解 ⑧无改写路由。
- **分诊式改写方案（📋 暂不实施，ADR-0009）**：静态 FTS 分诊（`_kb_terms` 术语命中 → 精确直接检索）→ 模糊才改写 → 保真预检（改写 vs 原 query 余弦 <0.6 回退）→ 并行检索 + 绝对余弦择优（module-035 口径跨 query 可比）。解决：事后补救→事前分诊、单候选改错可回退、评测闭环量化增益。
- **分诊判断要点（面试防追问）**：①分诊是静态 FTS 术语命中，不是"检索后看拿不拿得到答案" ②"精确"判据是词表对得上（检索质量），不是"答案对不对"（生成太贵）③特征词 = 分词过滤功能词后能在 FTS 命中的专有术语（动态判定，非预定义词表）④改写后对比必须用绝对余弦，不能直接比两个 query 的分。
- **`_kb_terms`（router.py:242-259，Knowledge Base Terms）**：分诊核心，从 query 提取"知识库专有术语"。三层噪音过滤：①底层 tokenize 用 `_WORD_RE=r"[一-龥a-zA-Z0-9]"` 过滤纯标点 ②`len>=2` 过滤单字 ③`_FUNCTION_STOPWORDS`（frozenset）过滤功能词（"什么/怎么/区别/原理"等在知识库文档广泛存在、命中无判别力）。不过滤则任何 query 都命中倒排 → 分诊永远判"精确"→ 形同虚设。命名：kb=Knowledge Base（拿去找知识库对答案），terms=术语（非普通分词）。示例："G1 垃圾收集器和 CMS 的区别是什么？" → ["G1","垃圾","收集","CMS"]。
- **业界对标**：RRR（EMNLP 2023 / arXiv:2305.14283，检索前重写，HotpotQA 不重写 RAG 比不 RAG 还差）；Multi-Query + RRF 融合；改写路由（Microsoft 三分类）；子查询分解 / Step-Back；对话上下文化（Databricks）；RewriteGen（南大学报 2025 RL 统一）。
- **实施顺序**：P0 检索前主动重写 / 多候选+RRF / 改写评测闭环（Recall@K）→ P1 改写路由 / 对话上下文化 → P2 子查询分解 / 专用重写器（RL 训练，奖励连下游答案质量）。

## 幻觉检测领域（2026-08-10 讨论，ADR-0010）

- **现状基线（verify_answer，module-039）**：答案生成完 → 同 LLM（温度 0，15s 超时）拆 claims → 每条标 supported/inferred/unsupported + 证据号 [1] → 越界降级 unsupported → 置信度 = 1-unsupported/total → 前端色标。`eval/faithfulness.py`（module-038）是答案质量评测，非验证器自身评测。
- **现状问题 8 项**：①同源验证（生成者验证自己，sycophancy）②伪验证（证据号越界只防引用编造，内容无关时 LLM 说了算）③置信度平均化（5 句错 1 句压成 0.8，inferred 不扣分、无权重）④超时静默降级（长答案最需验证却最易超时）⑤无验证器评测闭环 ⑥claim 拆解不可控 ⑦只标注不修正 ⑧成本（每次完整 LLM 调用）。
- **HHEM-2.1-Open（Vectara，已验证可本地部署）**：专职幻觉检测分类模型——110M 参数（FLAN-T5）、**<600MB 内存（F32）**、**~1.5s/2k token（x86 CPU 无 GPU）**、上下文无限、Apache 2.0 开源免费、RAGTruth-QA 74.28% 平衡准确率（>GPT-3.5、≈GPT-4 74.11%）。用法：premise(文档片段)-hypothesis(claim) 对 → 0-1 分；RAGAS `FaithfulnesswithHHEM` batch_size=10。
- **业界对标**：RAGAS Faithfulness（公式同构，HHEM 版替代 LLM judge）；futureagi claim-level 深挖（**"answer-level groundedness 是 vibe check"**，平均化掩盖单 claim 幻觉，三大失败模式：multi-claim / cherry-picked context / sycophancy，解法=per-claim + 未用 chunk 矛盾扫描）；Reliability without Validity（arXiv 2606.19544，consistency-bias paradox，judge 评估用 Cohen's kappa）；生产阈值 0.95 + CI/CD gate + HITL。
- **分阶段方案（ADR-0010，P0 可先行）**：P0-① 逐句报分（纯前端，verifiedClaims 已在传，改 UI）P0-② 换 HHEM 裁判（解决同源验证+成本）P1-③ 矛盾扫描（未引用的文档片段也查，防挑樱桃）P1-④ 验证器评测闭环（50 条人工标注 + Cohen's kappa>0.7）P2-⑤ 低分拦截 + 10% 抽样监控。
- **claim（大白话）**：答案里的一句话（独立陈述）——幻觉检测 = 逐句查"文档里有没有依据"，supported(有依据)/inferred(能推断)/unsupported(编的=幻觉)。前端应逐句标色（per-claim）而非只报总分（平均化藏错误）。
- **验证位置（链路上明确）**：幻觉检测在**答案生成之后**（engine.py:338-342），**不在检索内部**——因为幻觉发生在生成阶段，检索只有素材、答案才是成品。三个"检查"各管一段：检索管召回、反思管"文档够不够"（ADR-0005）、幻觉检测管"答案真不真"（ADR-0010）——对象不同，面试别混。
- **答案冲突三类（2026-08-11 调研，业界对标见 ADR-0010）**：① 答案内部自相矛盾（claim 打架）→ **ChatProtect**（ETH Zurich arXiv:2305.15852）trigger-detect-mitigate，GPT-4 15.7%/ChatGPT 17.7% 句子含自相矛盾、**35.2% 外部验证不了** → 内部一致性检查是 RAG 必要补充，检测 F1 80-86.5%、修正消除 76-89.5%；② 检测器结果冲突 → **阈值化 NLI 三分类**（DeBERTa-v3-large-mnli，接受 P(蕴含)≥0.85 / 拒绝 P(矛盾)≥0.10 或 P(中性)≥0.70）——**中性区=存疑不硬判**；③ 检索与生成冲突（反思漏判）→ **CARE**（ACL 2026 软提示冲突审查模式）/ **TruthfulRAG**（图谱矛盾三元组）/ **ProbeRAG**（隐藏状态探测）/ kiadev evidence-layered RAG（claim 聚类 + pairwise NLI + 保守合成策略）；Datadog 区分 **Contradictions vs Unsupported Claims 两类可独立开关**。落地：矛盾扫描直接用 DeBERTa-v3-large-mnli（P0），检测器冲突三分类阈值化（P1），ChatProtect 内部一致性留 P2。
- **串行阻塞问题 + 异步化解法**：当前 verify_answer 串行 await，非流式用户要等 1.5-3s 验证；流式首字不阻塞但色标干等。解法：① 异步化后置推送（答案先回，验证后台跑，前端轮询/SSE）② 抽样验证（10% 流量）③ 分层验证（便宜信号预筛）④ 验证期间并行做记忆写入/持久化/飞轮日志。推荐 ①+③ 组合。
- **NLI 实测参数（矛盾扫描用，2026-08-11）**：DeBERTa-v3-large-mnli——**1.5GB / MNLI 90.7% / GPU ~150ms / CPU 预估几百 ms**（输入是短 claim 对，15s 超时内稳）；base 440MB/87.5%/50ms 更省；生产案例未验证 claim 12%→1.8%（-85%），延迟仅 +180-220ms/条。阈值三分类：P(蕴含)≥0.85 接受 / P(矛盾)≥0.10 拒绝 / P(中性)≥0.70 存疑。
- **验证后决策流（检测不是终点）**：支持→标绿正常展示；矛盾→标红计票，占比高（>40%）触发**重生成闭环**（验证结果喂回 LLM 修订→重新验证→还不行降级"低可信"）；中性→标黄/存疑不硬判→人工复核。**核心**：标红=给用户信号（展示层），重生成=给系统纠错（决策层）——只标红不重生成="告诉你错了但答案还是错的"（问题 7 解法）。ChatProtect 实证一轮修订消 76-89.5% 矛盾、信息保留 ~100%、perplexity +0.44；**修改粒度=精准修订矛盾句而非整篇重写**。
- **修订机制详解（"喂回去"的内部运作，需新设计——代码实测项目当前无修订/重生成逻辑）**：不是丢结果给 LLM，而是构造**修订 prompt 三段式**：① 原文照抄（要改的草稿）② 验证反馈逐条点名 verdict+理由（**要具体到句**）③ 修订指令三条规则（有依据保留/没依据改写或删除/矛盾只留文档支持那句/不新增文档外内容），文档原样拼 prompt 边看边改。**三种修订策略**：A 整篇重写（最贵，可能改坏好的）/**B 逐句修订（推荐，手术刀）**/C 删除式（最保守，宁可少说）。**轮次上限+阈值双保险**：每轮=一次 LLM 调用+一次验证=花钱，上限 2-3 轮，修不好降级标注不无限循环。
- **MiniCheck vs HHEM（模型选型详细对比，见 ADR-0010）**：基准=考卷——AggreFact-SOTA（摘要忠实度）/ **RAGTruth-Summ（最贴近真实 RAG 答案）** / TofuEval-MB（会议纪要）/ FaithBench（忠实度专项）；**Acc=及格率、F1=调和平均（惩罚偏科更看抓幻觉）**、平均 F1=4 基准综合。逐维度：HHEM 110M <600MB ~1.5s/2k 平均 F1 **62.7**（FaithBench 单科略高）；**MiniCheck-Roberta-L 355M ~1.5GB ~2-3s F1 64.9**（RAGTruth 70.5 优势明显）；**MiniCheck-FT5 770M ~3GB ≈GPT-4（<1B 最佳）**；MiniCheck-7B F1 67.3-68.5 / Lynx-8B HaluBench 77.25 / HAD-7B HaluEval 82-92 但 CPU 30-60s 在线超时。**训练差异是核心**：MiniCheck 14K 合成数据 C2D（两句合起来才支持）+ D2C hard negative（删证据后"看起来相关"）——专治"引用号存在但内容无关"的伪验证短板；生态：pip install minicheck / Ollama / prefix caching。**落地：在线实时 MiniCheck-Roberta-L 或 FT5（替换 HHEM），7B 留给离线批量评测**。

## 提示词优化领域（2026-08-11 讨论，ADR-0011）

- **判断提示词好坏 = 可量化四维（不是玄学）**：正确性（golden 跑分 Acc/F1）/ 稳定性（自洽性，同输入多次输出一致）/ 鲁棒性（边界易混样本）/ 成本延迟（token+耗时）。**"Garbage metric, garbage prompt"**——评测集质量是优化天花板。提示词好坏无法脱离"任务+评测集"单独判断。
- **四代自动优化算法**：① APE/OPRO（LLM 当优化者读历史分数迭代，GSM8K +8%、BBH 最高 +50%）② TextGrad/ProTeGi（自然语言梯度定向编辑）③ **DSPy MIPROv2**（贝叶斯搜索同时调指令+示例，实测好 10-30%）④ **GEPA**（反思+遗传演化+保留 Pareto frontier 一组互补 prompt，ICLR 2026 Oral）。
- **DSPy = Declarative Self-improving Python**（斯坦福 NLP 开源框架，**不是模型**）："Program, don't prompt"——声明 Signature（`问题->答案`），优化器自动编译 prompt；模型用现有的（`dspy.LM("openai/gpt-4o")` 一行指定，支持本地 Ollama）。原语：Signature/Module/Program/Optimizer/Metric/Trainset。MIPROv2 三阶段：Bootstrapping→Grounded Proposal→Bayesian Search。
- **DSPy 优化器选型（12 个，官方决策树）**：~10 条数据→BootstrapFewShot；50+→BootstrapFewShotWithRandomSearch；200+ 且愿多跑→MIPROv2（auto light→heavy）；只调指令 0-shot→MIPROv2 0-shot 模式；prompt 到头→BootstrapFinetune 蒸馏；有奖励无标签→GRPO；要平衡点→GEPA；组合→BetterTogether/Ensemble。核心原则："从最便宜的开始，够用就停，不行再升级"。
- **平衡点认知**：不存在"单一最优"——质量 ↑ 往往代价 ↑。工程平衡 = **分数够用（达标）+ 成本可接受 + 可复现**；GEPA 的 Pareto frontier（一簇互补 prompt 按场景路由）是学术形态。判定机制 = eval_runs --compare 提升才保留（已具备）。
- **本项目落地三步（📋 暂不实施）**：① `eval/prompt_variants.py` 变体测试脚本（消融自动化，prompt 常量改可注入，半天）② OPRO 极简循环（10 行，用现有降级链当优化者）③ 数据够才上 DSPy MIPROv2（sufficiency/intent 100 条匹配，联合优化多 prompt 时才值）。
- **业界评测工具**：Promptfoo（开源 CLI，=eval_runs --compare 的产品化）/ OpenAI Eval / Braintrust（A/B+统计显著性）/ LangSmith / PromptLayer（Prompt 的 Git）/ Helicone（成本监控）/ DeepEval。

## 工具治理领域（2026-08-12 讨论，ADR-0012）

- **全量暴露现状**：10 个工具（ToolRegistry）一次性全量暴露给 LLM（`react.py:213 tools.to_llm_schemas()`）；调用时机 = ReAct 循环 LLM 自主决策（有 tool_calls 执行、无则输出答案），预算=4，15s 超时围栏，注册表无状态。
- **function calling vs prompt 工程（互补非替代）**：工具调用走原生 function calling（结构化 tool_calls，受约束解码解析错误率 15-25%→近 0）；语义判断任务（意图/反思/验证）走 prompt 要求严格 JSON + 白名单兜底；**工具 description 本身就是给 LLM 看的关键 prompt**（情境导向"何时用">功能导向"干什么"，实测精确 description 提升参数准确率 30%+）。
- **工具数量退化（硬数据）**：~50 工具选对率 84-95%（安全区）；200 个 41-83%；740 个接近 0%；**Lost in the Middle 效应**（列表中间工具最易漏选：中间段 22-52% vs 两端 31-32%）；退化非线性有阈值突变。**"全量暴露"只在工具少时成立**。
- **分层工具选择三档（📋 待实施）**：A 阶段切分（10-20 个：检索组 7/生成组 3，防误调 generate_answer，半天可做）；B 分组路由（20-50 个：ToolRouter 先类别后工具，**可复用现有 intent 路由**分流；类别语义最大区分，路由失败 fallback 全量）；C 动态工具检索（50+：description 向量化进 pgvector，query 检索 top-k 注入；语义路由准确率 **86.4%** vs 全量 <50%；**MCP-Zero** 2797 工具 token -98%；**AutoTool** 工具惯性图结构预测成本 -30%）。

## 输入校验领域（module-042 讨论）

- **ChatRequest**：`ai_service/rag/schemas.py:18` 定义的统一请求模型，四个问答端点共用（chat / chat/stream / agent / agent-lg）。FastAPI 反序列化请求体时自动触发 Pydantic 校验。
- **Field 约束**：`Field(..., max_length=2000)` 声明式约束，违反时 Pydantic 抛 ValidationError → FastAPI 返回 **422**。
- **field_validator(mode="before")**：在校验之前处理原始值的钩子。用于 history 超条数静默截断（schemas.py:22-28）。
- **静默截断（silent truncation）**：history > 20 条时保留最近 20 条，不报错。与"拒绝（422）"相对——query 是用户当下输入所以拒绝，history 是累积旧对话所以截断。
- **422 Unprocessable Entity**：FastAPI 对请求校验失败的默认响应码，请求不进业务逻辑、不触发 LLM 调用。
- **双层防线（two-layer defense）**：入口物理校验（schemas.py，防输入不可信）+ LLM 输出校验（router.py，防 LLM 不可信）。
- **LLM 输出校验**：`agent/router.py:_parse_response` 对 LLM 返回的 JSON 做白名单校验（intent 必须 ∈ knowledge/casual_chat/realtime），非法值回退 knowledge。
- **保守路由（conservative routing）**：router.py 任何异常（LLM 失败、超时、解析失败）一律返回 knowledge 意图——"宁多检不漏检"，宁可多检索一次不放过。
- **AC 1.3 / AC 1.4**：module-042 验收标准。AC 1.3 = query>2000 字符 → 422；AC 1.4 = history>20 条 → 静默截断。测试在 `ai_service/tests/test_schemas_validation.py`。

## 相关文件索引

| 文件 | 内容 |
|---|---|
| `specs/adr/0001-two-layer-input-validation.md` | 双层防线决策记录 |
| `specs/adr/0002-agentic-rag-resume-alignment.md` | 简历表述与代码对齐决策（三通道/0.96/测试数等口径） |
| `specs/adr/0003-intent-validation.md` | intent 正确性校验四层方案决策记录 |
| `specs/adr/0004-rerank-model-truncation.md` | 重排模型选型 + 500 截断策略 + 分数压缩效应决策记录（含 250 测试 TODO） |
| `specs/adr/0005-reflection-sufficiency-precision.md` | 反思充分性判断精确化五层方案（与 ADR-0003 姊妹篇） |
| `specs/adr/0006-chunk-strategy-optimization.md` | 分块策略优化方案（段落级优先+上下文检索+评估驱动，📋 暂不实施） |
| `specs/adr/0007-memory-evolution.md` | 记忆系统进化机制（强化/衰减/升级/会话摘要，📋 暂不实施） |
| `specs/adr/0008-data-flywheel.md` | 数据飞轮方案（模糊样本收集→人工标注→增量训练，📋 暂不实施） |
| `specs/adr/0009-query-rewrite-optimization.md` | Query 改写优化方案（分诊式改写+保真校验+评测闭环，📋 暂不实施） |
| `specs/adr/0010-hallucination-detection-upgrade.md` | 幻觉检测升级方案（HHEM 专职裁判+逐句报分+矛盾扫描，P0 可先行） |
| `specs/adr/0011-prompt-eval-optimization.md` | 提示词评估与自动优化（四维判断+四代优化算法+DSPy 选型+三步落地路径，📋 暂不实施） |
| `specs/adr/0012-tool-governance.md` | 工具治理与分层工具选择（数量退化数据+A/B/C 三档方案，工具口径 10→7 已修正；📋 P1 已立项 module-059：阶段切分状态机） |
| `specs/module-052-nli-contradiction-scan/task-brief.md` | NLI 矛盾扫描前置决策任务简报（📋 复测进行中 module-057 v2，数据集 86 条，kappa 门槛判定中） |
| `specs/module-053-rrf-fusion/` | 检索融合升级（✅ RRF 三通道已实施放行：Hit@5 0.9714→0.9905，加权否决，changelog 含放行决策表；上线 `PW_RETRIEVAL_FUSION_MODE=rrf` 一键开启，默认 hybrid 零回归） |
| `specs/module-058-retrieval-chain-opt/task-brief.md` | 检索链优化+可观测性任务简报（📋 WP-A 拼标题+防扎堆 / WP-B prompt 顺序前缀缓存 / WP-C 可观测性，基线 Hit@5 0.9905 id=18） |
| `specs/module-059-tool-phase-split/task-brief.md` | 工具治理 P1 任务简报（📋 阶段切分状态机：检索组 6 / 生成组 generate_answer+search_knowledge 补检口，ctx.phase 单向前进，PW_TOOL_PHASE_SPLIT 开关） |
| `specs/module-042-harness-guardrails/test-report.md` | 校验验收测试报告 |
| `ai_service/rag/schemas.py:18-28` | ChatRequest 模型 + 截断 validator |
| `ai_service/agent/router.py:76-122` | LLM 输出校验 + 保守路由 |
