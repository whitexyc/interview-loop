# Changelog — Module-056: L4 意图分类器上岗（人造标注扩充 → 重训 → 真实评测达标 → 启用）

> Developer | 2026-08-12
> 开工前已读 `memory/project-context.md` 全文（module-001~055 清单与迭代状态，避免重复/冲突）✅

---

## 1. 模块目标与结果

| WP | 内容 | 结果 |
|----|------|------|
| WP-1 | 人造标注集 300+ 条（三类平衡 + 边界易混 + 专有术语 + 口语化） | ✅ 337 条 |
| WP-2 | 重训（接入新数据集，训练/评测分离）+ Accuracy/混淆矩阵对比旧 0.89 | ✅ 1.0000 |
| WP-3 | golden_intent 真实模式 LLM vs 分类器同 100 条对比 | ✅ 双 1.0000（eval_runs id=23/24） |
| WP-4 | 达标启用：PW_INTENT_CLASSIFIER_ENABLED 默认开 | ✅ 启用（数据达标） |
| WP-5 | 测试 + 全量回归 + 真实 HTTP 冒烟 | ✅ 699/0（688 基线 + 11 新增） |

---

## 2. WP-1 人造标注集（数据声明）

### 2.1 交付物

- **`ai_service/eval/build_intent_dataset.py`（新）**：构造脚本，docstring 含完整标注指南（knowledge 四子型判定口径：边界易混/专有术语/口语化/常规；casual_chat/realtime 判定边界）；build 时强制校验（总样本 ≥300 / 每类 ≥80 / 边界易混 ≥30 / 专有术语 ≥30 / 口语化 ≥20 / E2E bug 类样本存在 / query 唯一 / 与 golden_intent 评测集字符串零重叠），不满足报错退出。
- **`ai_service/eval/intent_train_dataset.json`（新，337 条）**：`[{"query", "intent", "note"?}, ...]`。

### 2.2 数据构成（337 条）

| 类别 | 数量 | 子型 |
|------|------|------|
| knowledge | 132 | 边界易混 32（含 E2E bug 类 1）+ 专有术语 40 + 口语化 24 + 常规 36 |
| casual_chat | 105 | 问候/情绪/夸赞/机器人自身话题 |
| realtime | 100 | 时间/日期/天气/新闻/行情/票务 |

### 2.3 人造数据声明（诚实边界）

1. **本数据集为人工构造（非真实用户对话）**，用于方向性验证分类器能力；真实用户分布以 golden_intent 100 条真实评测为外部队列。
2. 真实飞轮数据（前端 👍/👎，module-048）积累后仍可并入重训（`IntentClassifier.fit()` 接口已预留），届时以真实数据为准、人造数据退居补充。
3. **训练/评测分离防泄漏**：golden_intent 评测集 100 条不进入训练（`load_golden_intent_samples` 已从训练管线移除）；本数据集所有 query 与评测集字符串零重复（build 时校验强制）。**计划内重叠**：评测集 knowledge 题源自 golden.json（天然标注），golden.json 112 题作为训练源属既有设计（评测集 knowledge 题由此获得记忆是计划内口径，casual/realtime 评测样本零混入，泛化结论不受影响）。**重叠量化（Review 补测，bge-m3 余弦）**：评测集 knowledge 50 题对训练集 449 条仅 **1/50 字符串全等**（"什么是G1垃圾收集器？它的核心创新是什么？"，系 golden.json 天然样本同源）、**23/50 余弦>0.95（近重复）**——"由此获得记忆"精确口径是语义近邻记忆而非字符串级重叠。

---

## 3. WP-2 重训

### 3.1 变更

- **`ai_service/eval/train_intent_classifier.py`**：训练源优先级改为 ① `intent_train_dataset.json`（337 条）→ ② `golden.json`（knowledge 112 题）；移除 golden_intent 评测集（防泄漏）与内置样本（被 337 条数据集取代，且其 casual/realtime 与评测集字符串重复，移除后分离口径成立）。
- **`ai_service/agent/intent_classifier.py`**：`fit()` 返回新增 `confusion_matrix`（additive 键，旧调用方兼容）；训练脚本新增混淆矩阵打印。

### 3.2 训练结果（bge-m3 冻结 + LogisticRegression class_weight=balanced, random_state=42, test_size=0.2）

| 指标 | 旧（module-043/045，golden 集） | 新（module-056，449 条 = 337 人造 + 112 golden） |
|------|------|------|
| 训练样本 | ~124 条 | 449 条（casual 105 / knowledge 244 / realtime 100） |
| test split Accuracy | **0.89** | **1.0000**（90 条：casual 13 / knowledge 57 / realtime 20） |
| 每类 P/R/F1 | — | 全部 1.00 |

```
Confusion matrix (row=label, col=predicted):
              casual_cha   knowledge    realtime
casual_chat           13           0           0
knowledge              0          57           0
realtime               0           0          20
```

- 模型落盘 `ai_service/models/intent_clf.joblib`（训练产物不进仓库，gitignored）。
- 注意：test split 属"训练集内"评估（同分布抽样），真实外部队列为 WP-3 golden_intent。

---

## 4. WP-3 真实评测对比（golden_intent 100 条，deepseek 真实模式）

运行：`python -m eval.golden_intent --compare-classifier`（新增模式；分类器侧 eval_type='intent_classifier' 落库）。
LLM 侧 = `router_agent.classify`（生产管线，含 L2 确定性信号确认）；分类器侧 = 裸分类器 max 概率（与 router L4 路径决策口径一致）。

| 指标 | LLM（+L2） | 分类器 |
|------|------|------|
| Accuracy | **1.0000** | **1.0000** |
| casual_chat P/R/F1 | 1.0000 / 1.0000 / 1.0000 | 1.0000 / 1.0000 / 1.0000 |
| knowledge P/R/F1 | 1.0000 / 1.0000 / 1.0000 | 1.0000 / 1.0000 / 1.0000 |
| realtime P/R/F1 | 1.0000 / 1.0000 / 1.0000 | 1.0000 / 1.0000 / 1.0000 |
| **knowledge Recall（漏检率）** | **1.0000** | **1.0000** |

混淆矩阵双方均为全对角（casual 30 / knowledge 50 / realtime 20，0 误判）。
落库：**eval_runs id=23（eval_type='intent'，LLM）/ id=24（eval_type='intent_classifier'）**，commit=eb40e165，scores/per_question 齐全（DB 实查确认）。

口径声明：LLM 侧含 L2 确定性信号确认（module-055 起无条件触发），分类器侧为纯分类器——对比的是「生产 LLM 管线 vs 纯分类器」，两方独立达标。

---

## 5. WP-4 启用判定（数据决定）

### 5.1 达标线核对

| 达标线（plan/AC） | 实测 | 判定 |
|------|------|------|
| Accuracy ≥0.95 | 1.0000 | ✅ |
| knowledge Recall ≥0.95 | 1.0000 | ✅ |
| casual / realtime F1 ≥0.9 | 1.0000 / 1.0000 | ✅ |

→ **启用：`PW_INTENT_CLASSIFIER_ENABLED` 默认开**（`src/config.py` `intent_classifier_enabled: bool = True`），保留开关可回退（PW_INTENT_CLASSIFIER_ENABLED=false 恢复 LLM 路径）。

### 5.2 诚实边界（为何 1.0000 不盲目乐观）

- 分类器侧评测集 knowledge 50 题与训练集 449 条有重叠（量化：**1/50 字符串全等、23/50 余弦>0.95 近重复**——计划内，见 §2.3）；**casual/realtime 30+20 条为零重叠的纯泛化验证**，全对才是真实力。
- LLM 侧同批 1.0000 亦为真实（历史 module-047/055 实测 0.98~1.0 区间内波动，本次同批 100 条恰好全对，属正常上沿）。
- 启用后 LLM 退居兜底（加载/推理失败自动回退），不丢原有护栏；分类器是确定性本地毫秒级决策，从根上消除 LLM 分类的"贵/慢/不稳定"（E2E bug 根因）。

### 5.3 回退机制（既有设计 + 本模块验证）

- `router._get_classifier`：模型缺失/损坏 → load False → LLM 兜底（零影响）。
- 推理异常 → except → LLM 兜底。
- 测试断言：`tests/test_intent_dataset.py::TestL4Fallback`（配置开启 + load 失败 → LLM；配置开启 + 推理失败 → LLM；配置开启 + 可用 → 分类器路径不调 LLM）。

---

## 6. 真实 HTTP 冒烟（uvicorn 8001 真实栈：PG/Redis/bge-m3/deepseek）

### 6.1 分类器路径（默认模式 + 模型在位）

- `POST /ai/rag/chat` "G1垃圾收集器的核心创新是什么？"（**E2E bug 类，module-054/055 曾 LLM 高置信误判 casual_chat**）→ HTTP 200 / message=ok / steps.intent=knowledge（**confidence 0.9159**，分类器概率签名）/ sources=3 / verified_claims 8 条非空。日志：`L4 意图分类器已加载` + `意图识别(L4): ... intent=knowledge, confidence=0.92`。
- `POST /ai/rag/chat` "你好呀" → HTTP 200 / message=casual_chat / sources=[]（分类器正确路由闲聊，零检索开销）。

### 6.2 失败回退路径（模型改名模拟加载失败）

- 改名 `models/intent_clf.joblib` → 重启 → 同 G1 查询 → HTTP 200 / message=ok / steps.intent=knowledge（conf 1.0）/ sources=3。日志：`L4 分类器模型加载失败（回退 LLM 分类）: [Errno 2] No such file` + `意图识别: ...（无 L4 标记，LLM 路径）`。
- 冒烟后模型文件已恢复原位。

---

## 7. 测试

- **`ai_service/tests/test_intent_dataset.py`（新，11 项）**：AC §1 数据集结构（JSON list/dict 结构、≥300、三类各 ≥80、边界易混 ≥30/专有术语 ≥30/口语化 ≥20、E2E bug query 存在、query 唯一）+ AC §2 训练/评测分离（训练管线加载新数据集优先、golden.json 全量进入、评测集 casual/realtime 零泄漏、训练脚本无 load_golden_intent_samples/_BUILTIN_SAMPLES）+ AC §5 L4 回退（配置开启三种路径：load 失败→LLM / 推理失败→LLM / 可用→分类器不调 LLM）。
- **`ai_service/tests/conftest.py`**：新增 autouse fixture 钉住测试环境 `intent_classifier_enabled=False`（生产默认已开，单测需 hermetic 不依赖真实模型文件；显式置 True 的用例后写覆盖）。
- **`ai_service/src/config.py`**：默认值 false→true + 注释说明达标依据与回退开关。
- **全量 pytest：699 passed / 0 failed**（688 基线 + 11 新增；存量测试零改动）。

---

## 8. 文档

- ADR-0003 L4 状态更新（本 changelog §5 数字；specs/adr/0003 为 gitignored 本地文件，worktree 副本已就地更新，主 checkout 副本由主会话合并时追加）
- memory/project-context.md（module-056 行 + 头部日期 + ADR 索引行）、memory/agent-activity-log.md（Developer 行）、memory/file-index.md（新文件行）
- 前端/简历/弹药类文档零改动（用户指示：等优化完成后进行）
- 未 git commit（主会话统一提交）

---

## 9. 修复记录（Reviewer conditional，2026-08-12）

Reviewer 判定 conditional（1 项 P1 + 4 项 minor），逐条修复：

**P1 `eval/golden_intent.py::run_compare_classifier` 自污染**：本模块将
`intent_classifier_enabled` 默认翻转为 true 后，router 在模型在位时静默走
L4 路径——任何重跑 --compare-classifier 会使「LLM 侧」退化为分类器、
「LLM vs 分类器」对比恒双 1.0000 失去意义。修复：LLM 侧运行前显式钉住
`settings.intent_classifier_enabled=False` + 重置 `router_agent` 已缓存的
`_intent_classifier`/`_classifier_tried`（防同一进程内早前按启用态加载过
模型），`finally` 恢复原开关值与缓存；**钉住口径**：LLM 侧永远是
「LLM+L2 真实管线」，分类器侧为独立实例不受影响。本次记录数字（id=23/24）
经 Reviewer 执行序还原（config 翻转 mtime 15:43:49 晚于 eval_runs 落库
15:43:19）确认真实，未受影响。另：`record_eval_run` 配置快照补
`intent_classifier_enabled` 运行时字段（rag_config 表无此键），eval_runs
可回溯本次评估的 L4 启用态。

**minor 1 `agent/router.py` docstring**：「默认仍用 LLM」→「module-056 起
默认启用（L4 为决策主体），失败回退 LLM；PW_INTENT_CLASSIFIER_ENABLED=false
保持纯 LLM 路径」（模块 docstring + RouterAgent 类 docstring 同步）。

**minor 2 `agent/intent_classifier.py` docstring**：训练源描述与 module-056
训练/评测分离口径对齐——人造标注集 + golden.json 天然样本、golden_intent
评测集不进训练（"golden 集即训练集"移除；fit() docstring 同步）。

**minor 3 changelog 重叠口径量化**：§2.3/§5.2 补量化——评测 knowledge 50
题对训练集 449 条仅 **1/50 字符串全等、23/50 余弦>0.95（近重复）**
（bge-m3 实测复现 Reviewer 数字）。

**minor 4 `eval/train_intent_classifier.py`**：落盘打印「设置 PW_=true」→
「默认已启用；回退可用 PW_INTENT_CLASSIFIER_ENABLED=false」+ docstring
「L4 上线流程」改为「L4 启用现状」。

**验证**：新增单测（test_golden_intent.py：--compare-classifier LLM 侧钉住
+ 恢复断言；record_eval_run 快照字段断言随契约演进更新——非掩盖）；全量
`python -m pytest tests/ -q` **700 passed / 0 failed**（699 基线 + 1 新增，
存量测试零改动，152.12s）。环境备注：从仓库根 `python -m pytest -q` 会
额外收集 `scripts/test_models.py`（module-004 遗留手动脚本，`test_model
(label, model_id)` 辅助函数被 pytest 当作测试收集 → fixture 'label' not
found 集合错误）——既有环境性产物非本模块回归，本模块全量口径沿用
`tests/` 目录（与 module-056 基线一致）。修复为纯脚本/docstring 改动，
不触产品代码路径；Tester 验收在启用默认下重跑 --compare-classifier
可验证钉住生效。
