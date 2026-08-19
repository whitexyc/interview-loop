# ADR-0003 — Intent 正确性校验：四层方案

- 状态：已实施（L1 module-043/047/055 / L2 module-043/055 / L3 module-043/045/055 / L4 module-056 启用）
- 日期：2026-08-08
- 修订：2026-08-09 L2 由"LLM 二次确认"改为"低置信触发 + 确定性信号确认"（同源复核不可靠，见 L2）
- 修订：2026-08-12 L4 启用（module-056：人造标注集 337 条 + golden.json 112 题重训 → test split Accuracy 1.0000（旧 0.89）；golden_intent 100 条真实评测 LLM 1.0000 vs 分类器 1.0000（eval_runs id=23/24，knowledge Recall 双 1.0000，casual/realtime 30+20 条零重叠纯泛化全对）→ PW_INTENT_CLASSIFIER_ENABLED 默认开，加载/推理失败回退 LLM，保留开关）
- 背景：`agent/router.py` 的意图路由目前只有**值合法性**校验（intent 必须 ∈ knowledge/casual_chat/realtime，否则回退 knowledge）——这是"值合法"层面的兜底。用户提出：如何校验 intent **类正确**（这个 query 到底该不该走 knowledge）？本 ADR 记录讨论结论。

## 问题拆解：为什么"校验 intent 对错"难

分类任务校验分两个场景，解法完全不同：

| 场景 | 是否有 ground truth | 能校验什么 |
|---|---|---|
| 离线（评测） | 有（人工标注） | 分类器平均多准、哪两类易混淆 |
| 在线（运行时） | 无 | 只能靠间接信号发现"可疑"分类 |

现有白名单兜底只解决"值合法"，不解决"类正确"。

## 关键洞察：不对称决策代价

- 误判成 knowledge（多检）→ 只多花 ~0.5s 检索，答案还能正常回答 → **低风险**
- 误判成 casual_chat（漏检）→ 跳过检索，直接答非所问 → **高风险，体验最伤**

结论：**校验预算不对称投放**——走 knowledge 是默认低风险路径，不校验；跳过检索（casual_chat/realtime）才是高风险决策，需要校验。

## 四层方案

### L1 · 离线评测集（最便宜，必做，先量化现状）

扩展现有 golden 评测体系（`eval/golden_retrieval.py` + eval_runs 表）：
- 扩充样本：补 casual_chat（问候/寒暄/闲聊）、realtime（时间/天气）、**边界易混样本**（"你网站有什么功能"看似闲聊实为知识库）
- 指标：Accuracy + 每类 Precision/Recall/F1 + **混淆矩阵**；重点看 knowledge 的 Recall（漏检率）
- 复用 eval_runs 表 `eval_type='intent'` 版本化回归，改 prompt 后跑分对比

### L2 · 低置信触发 + 确定性信号确认（修订版，2026-08-08）

不对称投放：只对 `intent≠knowledge` 的结果做二次确认。

**【原方案：LLM 二次确认】——已否决**
- 原设计：二次 prompt"用户问题 'X' 是否可能涉及知识库内容？只回答是/否"，是 → 改判 knowledge
- **否决理由**（2026-08-08 grill 讨论）：**同源复核**——同一个 LLM 换 prompt 再问一遍，系统性误判会复现，无新信息；confidence 门槛本身来自未校准的自报分数，不可信；prompt 更简信息更少。它不是校验（verification），只是"再问一次"（re-asking）。

**【修订方案：确定性信号确认】**
- **触发条件保留**：`intent≠knowledge AND 低置信`——LLM 低置信作为"不放心"触发器（单向信任：绝对值不可信，但低置信是有效的"不放心"信号）
- **确认动作不用 LLM**，换成与 LLM 完全无关的**确定性信号**（三选一或组合）：
  - **FTS 术语命中**：query 经 jieba 分词后在知识库倒排索引（search_tokens 列）快速匹配，命中 ≥1 个知识库专有术语 → 涉及知识库（微秒级，复用现有通道）
  - **图谱实体命中**：query 提取实体后在图谱 entities 表命中（复用图谱通道）
  - **规则表**：明确闲聊/实时特征词（"几点""天气""你是谁"），几十行代码
- 任一命中 → 改判 knowledge（宁多检不漏检）；否则维持跳过
- **哲学延续 ADR-0001**：LLM 决策（软触发器）+ 确定性护栏（硬确认）正交——能自动修的交 LLM，修不了的有物理护栏兜底

**为什么比 LLM 二次确认好**：
- **独立信息来源**：检索侧事实，非模型判断——模型误判了，术语表不会误判
- **可解释**：命中哪些词一目了然，面试可讲"我不用 LLM 校验 LLM，用检索事实校验 LLM"
- **更便宜**：微秒级 vs 一次 LLM 调用
- **确定性**：可测试、可回归

**与 L3 的层次关系**：L2 用检索侧事实**前置**判断"该不该检"；L3 用检索结果质量**后置**判断"检对了没"——一前一后，方向互补不重叠。

### L3 · 检索结果反证（后验校验，设计最优雅）

走 knowledge 路径后，检索结果本身是一次免费验证：
- 检索 top-1 绝对余弦 < 阈值（如 0.3，用绝对 cosine 不用相对 min-max）→ 知识库无相关内容 → 疑似误判
- 反向反思：query + 检索摘要给 LLM，问"基于这些检索结果，这问题是闲聊还是知识库问题"
- 与 `check_sufficiency` 互为镜像：正向查"检索结果够不够回答"，反向查"检索结果该不该存在"
- 实现点：`engine.chat()` 检索完、反思前插入判断分支

### L4 · 反馈飞轮 + 终极方案（✅ 已启用，module-056 2026-08-12）

- 反馈飞轮：前端 👍/👎 → 被踩样本回流评测集增量标注 → 越用越准（module-048 落库 feedback 表，message_id 关联 query/answer；数据积累到可重训量级后并入训练集增量重训）
- 终极方案（已落地）：intent 是简单分类任务，不一定要 LLM——bge-m3 embedding（本地部署）+ 逻辑回归头：
  - 推理成本低几个数量级（毫秒级本地 vs LLM API 调用）
  - 输出经训练校准的真概率，彻底解决"LLM 自报 confidence 不可信"
  - 训练数据：`eval/intent_train_dataset.json`（337 条人造标注，三类平衡 + 边界易混 + 专有术语 + 口语化）+ `eval/golden.json`（112 题天然 knowledge）；训练/评测分离（golden_intent 100 条仅评测不训练）
  - 上线：`PW_INTENT_CLASSIFIER_ENABLED` 默认 true（router 惰性加载，缺失/推理失败回退 LLM 零影响）；重训脚本 `eval/train_intent_classifier.py`，真实对比 `eval/golden_intent.py --compare-classifier`

#### L4 补充：逻辑回归是什么（2026-08-08 讨论）

逻辑回归（Logistic Regression）是最经典、最简单的**分类**算法（名字带"回归"但做分类）。它把输入变成一个 0~1 的概率，再用阈值判类。四步：

1. **文本 → 向量**：bge-m3 把 query 编码成 1024 维向量（语义相近的文本向量相近）
2. **加权求和**：学一组权重 w，算 z = w₁x₁ + w₂x₂ + ... + w₁₀₂₄x₁₀₂₄ + b——本质是在 1024 维空间学一条分割线，权重从标注数据训练学出
3. **sigmoid 压成概率**：P = 1/(1+e⁻ᶻ)，把任意实数 z 压到 [0,1]
4. **阈值决策**：P > 0.5 → knowledge；P < 0.5 → casual_chat

**为什么用逻辑回归替代 LLM 分类**：

| 对比维度 | LLM 分类（现实现） | 逻辑回归（L4 方案） |
|---|---|---|
| 输出概率 | 自报 confidence，未校准、不可信 | **校准过的真概率**（训练学出） |
| 可解释性 | 黑盒 | 权重 w 可分析，可解释 |
| 推理成本 | LLM API 调用（几百 ms + 花钱） | 矩阵乘法（毫秒级、本地跑） |
| 训练门槛 | 无需训练（zero-shot） | 需标注数据（golden 集即种子） |
| 类别扩展 | 改 prompt 即可 | 重新训练（很快） |

#### L4 补充：训练流程（要训练吗？怎么训练？）

**训练的不是 bge-m3，是它上面的分类头**——bge-m3 冻结当特征提取器，唯一被训练的是逻辑回归的 1025 个参数（1024 权重 + 1 偏置）。参数少、数据少、不需要 GPU，普通笔记本 sklearn 几秒跑完。

```python
# ① 准备标注数据（几十~几百条，类别要平衡）
training_data = [
    ("什么是G1垃圾收集器？它的核心创新是什么？", "knowledge"),
    ("CMS和G1的主要区别是什么？",              "knowledge"),
    ("你好呀",                                  "casual_chat"),
    ("在吗？",                                  "casual_chat"),
    ("现在几点了？",                            "realtime"),
    ("你们网站有哪些功能？",                    "knowledge"),  # 边界易混样本
]
# 来源：golden 集（30 题天然 knowledge）+ 手工补闲聊/实时/边界 + 前端👍/👎飞轮
# ⚠️ 类别必须平衡——golden 全 knowledge，不补足其他类会学成"永远猜 knowledge"

# ② bge-m3 编码（冻结）：复用 rag/embeddings.py 的 embedding_service.embed_text
X, y = [], []
for query, label in training_data:
    X.append(await embedding_service.embed_text(query))  # 1024 维
    y.append(label)

# ③ 训练逻辑回归（核心就一行）
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
model = LogisticRegression(max_iter=500)
model.fit(X_train, y_train)  # 最小化交叉熵，凸优化秒级收敛

# ④ 评估 + 部署
from sklearn.metrics import classification_report, confusion_matrix
print(classification_report(y_test, model.predict(X_test)))  # 每类 P/R/F1
print(confusion_matrix(y_test, model.predict(X_test)))       # 易混类对
import joblib; joblib.dump(model, "models/intent_clf.pkl")
# 推理：vec = embed_text(query) → model.predict_proba([vec]) → 真概率
# 部署后替换 router.py 的 LLM 调用；现有白名单兜底策略原样保留作保险
```

**面试话术（L4）**："L4 方案里我用 bge-m3 + 逻辑回归替代 LLM 做 intent 分类。bge-m3 冻结当特征提取器，只训练逻辑回归头——1025 个参数、几百条标注数据、sklearn 几秒训练完，不需要 GPU。关键收益是输出经过校准的真实概率，从根上解决 LLM 自报 confidence 不可信的问题；推理毫秒级本地跑，比调 LLM 省钱一个量级。现有的白名单兜底保留，作为分类器之上的保险。"

## 推荐实施顺序

1. L1（半天）：扩充评测集 → 跑混淆矩阵 → 拿 baseline（没有它后面都是盲人摸象）
2. L2（一天）：低置信触发 + 确定性信号确认（FTS 术语命中优先，复用现有通道）→ 直接降漏检率
3. L3（半天）：检索反证，与反思逻辑复用一套
4. L4（长远）：踩数据够了之后换小模型，治本

## 面试话术（该项目价值主张延伸）

> "我现有实现只做了值合法性兜底（白名单 + 保守回退）。如果要校验类正确性，我的方案是分两层：离线扩 golden 集建 intent 评测，量化 Accuracy/每类 F1/混淆矩阵，重点盯 knowledge 的召回；在线做不对称校验——只对'跳过检索'的高风险决策校验，低置信时**用检索侧事实确认**（FTS 术语命中/图谱实体命中，不用 LLM 校验 LLM，因为同源复核不可靠），宁多检不漏检。长期可以换 bge-m3 + 逻辑回归的小分类器，输出校准后的真概率。"

## 相关文件

- `agent/router.py`（被校验对象，LLM 分类 + 白名单）
- `eval/golden_retrieval.py`（L1 复用其评测框架）
- `agent/reflector.py:check_sufficiency`（L3 镜像逻辑）
- `CONTEXT.md`「intent 校验领域」术语表
