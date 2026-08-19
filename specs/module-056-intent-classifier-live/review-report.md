# Review Report — Module-056: L4 意图分类器上岗（人造标注扩充 → 重训 → 真实评测达标 → 启用）

> Reviewer | 2026-08-12 | 第一轮审查
> 结论：**⚠️ conditional（附条件通过）** — 1 项 P1 必修（eval 对比脚本在启用默认下自我污染）+ 4 项 minor 非阻塞

---

## 1. 审查范围与方法

独立核对（非仅采信 changelog）：

1. 通读 plan.md / acceptance-criteria.md / changelog.md 全部 + 变更文件 diff（`agent/intent_classifier.py`、`eval/golden_intent.py`、`eval/train_intent_classifier.py`、`src/config.py`、`tests/conftest.py`）+ 新增文件全文（`eval/build_intent_dataset.py`、`eval/intent_train_dataset.json`、`tests/test_intent_dataset.py`）
2. 数据实查：337 条结构/平衡/边界/术语/口语化/E2E query/无重复/与评测集字符串零重叠
3. 训练复现：`python -m eval.train_intent_classifier --no-save` 独立重跑 → Accuracy 1.0000 复现一致
4. 真实对比：eval_runs id=23/24 实查 DB（scores/per_question/混淆矩阵/commit 齐全，双 1.0000）
5. **执行序还原（关键诚实性验证）**：config.py mtime 15:43:49 > eval_runs created_at 07:43 UTC（=15:43 本地）——对比运行发生在启用开关翻转**之前**，"LLM 侧"确为真 LLM 运行
6. 进程内实测分类器：G1 E2E bug query → knowledge 0.9159（与 changelog 冒烟数字逐位一致）、你好呀 → casual 0.9414、现在几点了 → realtime 0.8231
7. 语义重叠量化：评测集 knowledge 50 题对训练 knowledge 集余弦分布 >0.95: 23/50、>0.9: 35/50、仅 1 题字符串完全一致
8. 全量 pytest 独立复跑：**699 passed / 0 failed**（688 基线 + 11 新增，178.87s）
9. 记忆硬核查：project-context 行 74 + 头部日期、activity-log Developer 行、file-index 5 新行、ADR-0003 L4 状态更新

---

## 2. AC 逐条核查

| AC | 内容 | 判定 |
|----|------|------|
| §1 数据 | 337 条 ≥300 ✓；knowledge 132 / casual 105 / realtime 100 三类各 ≥80 ✓；边界易混 32（含 E2E bug 类 G1 query 标注 knowledge）✓；专有术语 40 ✓；口语化 24 ✓；JSON `[{"query","intent","note"?}]` 可被训练脚本加载（实查 337 条全加载）✓；构造脚本 docstring 含完整标注指南 ✓；人造数据声明入 changelog ✓ | ✅ |
| §2 重训 | 训练源改为 人造集→golden.json，`load_golden_intent_samples` 已移除（分离口径成立，测试断言 + 代码核对）✓；输出 Accuracy/混淆矩阵/每类 P/R/F1 ✓；与旧 0.89 对比（changelog 表）✓；模型落盘 models/intent_clf.joblib（gitignored，实查）✓；**复现 Accuracy 1.0000（90 条 test split 全对角）与 changelog 逐位一致** ✓ | ✅ |
| §3 真实对比 | 同 100 条、同评测函数 run_eval；LLM 侧=router_agent（含 L2）、分类器侧=裸 max 概率（决策口径与 router L4 一致）✓；knowledge Recall 重点（双 1.0）✓；eval_runs 落库 id=23（eval_type='intent'）/id=24（'intent_classifier'）实查 ✓；LLM 不可用 → skipped 单侧声明（代码含启发式）✓ | ✅（见 P1） |
| §4 启用判定 | 达标线三条件全过（1.0000 / 1.0000 / 1.0000）→ 默认开 ✓；PW_ 开关保留（env_prefix=PW_ 实查）✓；回退三路径测试断言 ✓；真实 HTTP 冒烟 changelog 记录 + 进程内复验（conf 0.9159 一致）✓ | ✅ |
| §5 降级 | 分类器不可用 → LLM 回退零影响（TestL4Fallback 3 用例）✓；重训不达标保持关闭为设计分支（本模块达标，如实声明）✓；全量 699/0 全绿 ✓ | ✅ |
| §6 接口 | classify 返回 {intent, confidence, reason} 结构不变（L4 路径同构）✓；ChatResponse/前端零改动（diff 确认无前端文件）✓；LLM 路径保留（回退用）✓ | ✅ |
| §7 测试 | test_intent_dataset.py 11 项（结构/平衡/边界/E2E/分离/回退三路径）全部通过 ✓；conftest autouse fixture 钉住测试环境关闭（hermetic，存量用例零改动）✓；全量 699/0 ✓ | ✅ |
| §8 文档记忆 | changelog ✓；review-report（本报告）；test-report（Tester 待产出）；project-context 行 + 头部日期 ✓；activity-log Developer 行 ✓（Reviewer 行见 §4）；file-index 5 新行 ✓；ADR-0003 L4 已启用 + 数据量 ✓；开工前必读 project-context（changelog 注明）✓；简历/弹药/前端零改动 ✓ | ✅ |

---

## 3. 关键诚实性验证结论（重点核对项）

1. **数据真实性**：337 条全部为脚本内嵌定义，无 AI 生成幻觉；标注抽查与标注指南一致（边界易混=闲聊/系统外壳+知识库内核，口语化=无术语技术问题，realtime=时间/天气/新闻/行情类）。个别 realtime 样本（"现在几点下班合适""今天会议几点开始"）为时间外壳但不可由实时数据回答——与 module-043/055 L2 规则表"几点"触发语义同口径，作为训练噪声可接受。
2. **防泄漏红线**：训练/评测字符串零重叠（build 强制校验 + 测试断言 + 实查 0 重叠）；仅 1 条评测 knowledge 题（"什么是G1垃圾收集器？…"）与训练集字符串完全一致——该题源自 golden.json（计划内天然标注），changelog 已声明。
3. **"LLM 1.0000" 真实性**：通过文件 mtime 与 eval_runs created_at 还原执行序，对比运行（15:43:19）早于 config 默认翻转（15:43:49），LLM 侧确为 LLM+L2 路径，非分类器自我对比。数字可信。
4. **语义重叠如实度**：评测 knowledge 50 题中 23 题与训练集余弦 >0.95（近重复）、35 题 >0.9——"knowledge 50/50"有显著相似度记忆成分；changelog §2.3/§5.2 已声明"计划内重叠"并把结论锚定在 casual/realtime 30+20 零重叠纯泛化（实测真实，20/20+30/30 全对）。声明方向保守、无隐瞒，仅建议量化（见 minor #4）。

---

## 4. 发现清单

### P1 必修（放行条件）

**#1 `ai_service/eval/golden_intent.py::run_compare_classifier` — "LLM 侧"在启用默认下自我污染**
- 问题：LLM 侧走 `router_agent.classify`。本模块将 `intent_classifier_enabled` 默认翻转为 true 后，只要模型文件在位，router 会静默走 L4 分类器路径（进程内实测：reason="L4 classifier {...}"）——`--compare-classifier` 重跑时"LLM 侧"实际是分类器，"LLM vs 分类器对比"退化为"分类器 vs 分类器"，双 1.0000 恒成立、对比失去意义。本次记录的数字不受影响（执行序还原证明运行于翻转前，且逐项复验一致），但 **Tester 验收重跑、后续任何回归重跑都会产出污染数据**，且污染态数字与真实数字无法凭结果区分（均为 1.0000）。
- 建议：在 `run_compare_classifier` 进入 LLM 侧前显式钉住 `settings.intent_classifier_enabled = False`（若 `router_agent` 单例已缓存分类器则重置 `_classifier_tried/_intent_classifier`），并在 changelog 注明该钉住口径；可选：`load_rag_config` 快照补 `intent_classifier_enabled` 字段，使 eval_runs 可回溯区分两侧运行态。

### Minor（非阻塞）

**#2 `ai_service/agent/router.py` 模块 docstring（~L46）**："L4 分类器…默认仍用 LLM" — 启用后过时（默认已为 L4）。建议同步为"默认启用，失败回退 LLM"。

**#3 `ai_service/agent/intent_classifier.py` docstring（L17）与 fit() docstring（L76）**："先以 golden 评测集训练" / "来源 golden_intent 评测集 + 手工闲聊/实时样本" — 与 module-056 分离口径（人造标注集 + golden.json）矛盾，建议更新。

**#4 `specs/module-056-intent-classifier-live/changelog.md` §2.3/§4 重叠口径精确化**：声明"评测集 knowledge 题源自 golden.json（由此获得记忆是计划内口径）"——实测仅 1/50 字符串完全一致，但 23/50 余弦 >0.95（近重复）。建议补一句量化（"50 题中 23 题与训练集余弦 >0.95"），使声明更精确（当前方向保守，非缺陷）。

**#5 `ai_service/eval/train_intent_classifier.py` L144 打印提示**："上线：设置 PW_INTENT_CLASSIFIER_ENABLED=true" — 默认已 true，提示过时；建议改为"默认已启用；回退可用 PW_INTENT_CLASSIFIER_ENABLED=false"。

### 观察（非缺陷）

- `specs/module-033-long-term-memory/changelog.md` +47 行"附属发现"为工作树遗留物（module-055 审查已记录 minor #5），非本模块写入。
- 数据集 realtime 类少量"时间外壳但不可回答"样本（见 §3.1），与 L2 规则表同口径，训练噪声可接受。

---

## 5. Reviewer 独立复现记录

| 项目 | 结果 |
|------|------|
| `python -m pytest tests/test_intent_dataset.py -q` | 11 passed（55.35s） |
| 全量 `python -m pytest tests/ -q` | **699 passed / 0 failed**（178.87s） |
| 重训复现 `python -m eval.train_intent_classifier --no-save` | Accuracy 1.0000，90 条全对角（casual 13/knowledge 57/realtime 20），与 changelog 一致 |
| eval_runs 实查 | id=23 intent 1.0000（100 条 per_question 齐全）/ id=24 intent_classifier 1.0000，commit=eb40e165 |
| 进程内分类器实测 | G1 E2E query → knowledge 0.9159；你好呀 → casual 0.9414；现在几点了 → realtime 0.8231；你们网站都有哪些功能？→ knowledge 0.6184；内存老是溢出咋办 → knowledge 0.7351 |
| 数据实查 | 337 条 / 三类 132/105/100 / 边界 32（含 E2E） / 术语 40 / 口语化 24 / 无重复 / 评测集零重叠 |
| 语义重叠量化 | 评测 knowledge 50 题：余弦 >0.95 共 23 题、>0.9 共 35 题、字符串全等 1 题 |
| 默认配置路径 | `settings.intent_classifier_enabled=True` 时 router.classify 走 L4（reason="L4 classifier …"）——P1 依据 |

---

## 6. 结论

模块交付物完整、数字真实（执行序还原 + 独立复现双重确认）、诚实性达标（人造数据声明/防泄漏/未达标不硬切的机制均在），AC §1-8 除 test-report 外全部核验通过。

**放行条件**：修复 P1 #1（`run_compare_classifier` LLM 侧钉住 `intent_classifier_enabled=False`），确保 Tester 验收重跑产出的是真 LLM vs 真分类器对比；修复后无需重跑全量测试（纯脚本改动，不触产品代码路径），但 Tester 验收时须在**启用默认下**重跑 `--compare-classifier` 以验证钉住生效。

---

## 7. 第二轮审查（2026-08-12）

> 结论：**✅ 通过（pass）** — P1 + 4 项 minor 全部修复核验通过，无新引入问题

### 7.1 P1 修复核验（`run_compare_classifier` 自污染）

1. **代码级**：`eval/golden_intent.py` L394-400 —— LLM 侧运行前显式钉住 `settings.intent_classifier_enabled=False` + 重置 `router_agent._intent_classifier=None` / `_classifier_tried=False`（防同进程早前按启用态加载）；L439-442 `finally` 恢复原开关值与原缓存。docstring（L382-388）记录钉住口径与动机。
2. **真实进程验证（关键）**：启用默认态 `router.classify("什么是G1垃圾收集器？")` → intent=knowledge、reason=`L4 classifier {...}`（走 L4 路径）；模拟钉住（开关=False + 缓存重置）后再调 → intent=knowledge、reason=LLM 生成语义理由（"询问G1垃圾收集器的定义，属于专业知识需要检索"）——钉住后确为真 LLM 路径，**"LLM vs 分类器"对比不再自我污染**。
3. **可回溯性**：`record_eval_run` 配置快照补运行时字段 `intent_classifier_enabled`（L296-300，rag_config 表无此键）——eval_runs 可区分两侧运行态，LLM 侧钉住时如实记录 False。
4. **单测**：`tests/test_golden_intent.py::TestRunCompareClassifier`（新增 1 项）：断言 LLM 侧与分类器侧两次 run_eval 均观察到钉住态 False + 结束后恢复调用前原值（模拟启用默认态 True）——通过。`test_eval_runs_contract` 快照断言随契约演进更新（新增字段，非掩盖）。
5. **Tester 放行提示**：验收时在启用默认下重跑 `python -m eval.golden_intent --compare-classifier`，LLM 侧 eval_runs 快照应含 `intent_classifier_enabled: "False"`（钉住态证据），且 LLM 侧 reason 应为 LLM 生成理由而非 "L4 classifier"。

### 7.2 Minor 修复核验（4/4）

| # | 位置 | 修复内容 | 核验 |
|---|------|----------|------|
| #2 | `agent/router.py` 模块 + RouterAgent 类 docstring | "默认仍用 LLM" → "module-056 起默认启用（L4 为决策主体），失败回退 LLM；PW_INTENT_CLASSIFIER_ENABLED=false 保持纯 LLM 路径" | ✅ L44-48 + L168-171 |
| #3 | `agent/intent_classifier.py` 模块 + fit() docstring | 训练源改"人造标注集 + golden.json 天然样本；golden_intent 评测集只作评测不进训练（防泄漏）" | ✅ L17-19 + L79-82 |
| #4 | changelog §2.3/§5.2 | 重叠量化补全：评测 knowledge 50 题对训练集 449 条仅 1/50 字符串全等、23/50 余弦>0.95（bge-m3 实测） | ✅ §2.3 末段 + §5.2 |
| #5 | `eval/train_intent_classifier.py` | 落盘打印"设置 PW_=true"→"默认已启用；回退可用 PW_INTENT_CLASSIFIER_ENABLED=false"；docstring"上线流程"→"启用现状" | ✅ L24-27 + L144-145 |

### 7.3 无新引入问题核查

- 钉住逻辑 finally 双恢复（开关 + 缓存）完备，无泄漏；分类器侧用独立 `IntentClassifier()` 实例不受钉住影响（对比口径不变）。
- `run_compare_classifier` 内访问 `router_agent` 私有属性有 docstring 说明，评估脚本场景可接受。
- config.py `intent_classifier_enabled: bool = True`（L115）+ 达标依据注释（L110-114）——未被动摇。
- 训练/评测分离红线保持：训练管线仅 人造集 + golden.json（load_training_samples 实测去重后 449 条：casual 105/knowledge 244/realtime 100）；golden_intent casual/realtime 30+20 零混入（测试断言 + 实查）。
- 数据完整性与标注一致性复验：337 条（132/105/100）、边界 32（含 E2E G1 query note="边界易混 E2E bug 类"）、术语 40、口语化 24、query 全唯一、与评测集字符串零重叠；全部分型 note 样本均标 knowledge（无错标）；10 条随机抽查标注合理。
- 全量 pytest 独立复跑：**700 passed / 0 failed**（175.81s，与 changelog §9 声明一致）；定向两文件 23/23 通过。
- 记忆硬核查：project-context 行 74（含 Review 修复说明）+ 头部日期"2026-08-12（module-056 完成 + Review 修复）"✅；activity-log Developer[CODE]/Reviewer/FIX 三行 ✅（本行 Reviewer-2 追加）；file-index 3 新行 ✅；ADR-0003 状态/L4 节/修订行 ✅（实查 specs/adr/0003-intent-validation.md L3/L6/L69-76）。
- 简历/弹药/前端零改动 ✅；未 git commit ✅（HEAD 仍 eb40e16）。
- 观察（非本模块写入，沿用首轮记录）：specs/module-033 changelog +47 行遗留物、eval/faithfulness.json 与 golden_expanded.json 未跟踪（历史模块数据产物）；test-report.md 归 Tester 产出。

### 7.4 结论

P1 及 4 项 minor 修复全部核验通过，修复为纯脚本/docstring 改动未触产品代码路径，全量 700/0 无回归，无新引入缺陷。**判定：pass**，可移交 Tester 验收（验收要点见 7.1-5）。
