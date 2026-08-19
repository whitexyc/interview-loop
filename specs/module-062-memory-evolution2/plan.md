# 功能规格说明书 — Module-062: 记忆进化 2（类型化衰减 + 冷记忆降权）

> 本文件由 **Planner** 输出，作为模块开发的唯一权威规格文档。
> Developer 严格按本文件编码，Reviewer 和 Tester 按本文件验收。
> 详细执行简报见同目录 `task-brief.md`（已探明事实，勿重复调研）。

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-062 |
| 模块名称 | 记忆进化 2（ADR-0007 P2 类型化衰减 + P3 冷记忆降权） |
| 优先级 | P2（记忆进化自然延续，module-061 纠错之后） |
| 预估代码量 | 功能代码（不含注释/测试）约 200-250 行；含注释/测试约 600-700 行——按含注释/测试口径预估，豁免默认 ≤200 功能代码上限 |
| 创建日期 | 2026-08-13 |
| 最后更新 | 2026-08-13 |
| 负责人 | Planner: 主会话, Developer: vibe-coding-workflow |

---

## 2. 需求描述

### 2.1 需求来源

- 来源类型：用户输入（"继续优化记忆"）+ ADR-0007（P2/P3 待实施清单）
- 原始描述：记忆衰减参数一刀切（偏好和事件不该同一套）、长期层无降权/淘汰。需类型化衰减 + 冷记忆降权。

### 2.2 用户故事

```
作为 知识库问答的使用者
我想要 记忆按类型区分新鲜度（偏好慢衰减、事件快过期）、太久没用的旧记忆检索时自动降权
以便 召回时近期相关记忆优先，过时/不用的旧记忆不盖过新偏好
```

### 2.3 验收场景（BDD 格式）

```
场景 1：类型化衰减
  假设 短期记忆"用户喜欢 Python"（type=preference，5 天前）与"用户下周去北京"（type=event，5 天前）
  当 recall_short 召回
  那么 preference 半衰期 30 天衰减系数远高于 event 半衰期 1 天（preference 5 天前仍较高分、event 接近 0）——偏好类慢衰减、事件类快过期

场景 2：提取判类型
  假设 对话中用户说"我喜欢 Python"（LLM 提取事实）
  当 extract_facts 提取
  那么 返回的 fact 带 type="preference"；无法判断/无 type → 默认 "fact"

场景 3：冷记忆降权（长期层）
  假设 长期记忆 A（1 天前召回过）与记忆 B（90 天未召回）
  当 recall 长期层
  那么 B 分数 ×0.3（久未召回降权）、A 保持 ×1.0；两者都不被删除

场景 4：存量零回归
  假设 存量记忆无 type / 无 last_recalled_at 字段
  当 召回
  那么 type 按 fact（现状半衰期 3 天）、无 last_recalled_at 不降权——行为与 module-046 完全一致
```

### 2.4 非功能需求

| 类别 | 要求 |
|------|------|
| 响应时间 | 衰减/降权为纯计算（O(n)），不新增 LLM 调用（类型判断仅在提取时一次调用） |
| 可用性 | fail-open：LLM 类型判断失败默认 fact；降权计算异常 ×1.0 不降权；新列默认值兜底存量 |
| 兼容性 | 存量记忆无新字段 → 零回归；短期层公式结构不变（只换 half_life）；recall 接口/返回结构不变 |
| 数据安全 | 冷记忆降权**不删除**旧记忆（×0.3 降权保留可回溯） |

---

## 3. 技术方案

### 3.1 涉及文件

| 文件路径 | 操作类型 | 说明 |
|----------|----------|------|
| `ai_service/rag/memory/memory_extractor.py` | 修改 | `_EXTRACT_PROMPT` 加 type + `extract_facts` 输出 type |
| `ai_service/rag/memory/memory.py` | 修改 | `_evolve_recall` 按 type 半衰期、`recall` 长期层冷降权 + last_recalled_at 刷新 |
| `ai_service/rag/models.py` | 修改 | `Document` 加 `type`/`last_recalled_at` 字段 |
| `ai_service/src/database.py` | 修改 | documents 加列（init_db 幂等 ALTER） |
| `ai_service/src/config.py` | 修改 | type 半衰期 + 开关 + `memory_type_mode`（clf/llm/none 生产注入用，winner 决定） |
| `ai_service/scripts/migrate_module062.py` | 新增 | 本地库 ALTER 先决 |
| `ai_service/eval/memory_type_dataset.py` | 新增 | 记忆类型评测集（30 条）+ 分类模型 vs LLM 对比（eval_runs eval_type='memory_type'） |
| `ai_service/eval/build_memory_type_dataset.py` | 新增 | 人造记忆类型训练集（120 条，与评测集零重叠防泄漏） |
| `ai_service/scripts/train_memory_type_clf.py` | 新增 | bge-m3+LR 类型分类器训练（复用 module-056 train_intent_classifier 模式，落盘 models/memory_type_clf.joblib） |
| `ai_service/eval/build_memory_conflict_train.py` | 新增 | 记忆矛盾训练集（100+，与评测集零重叠） |
| `ai_service/scripts/train_memory_conflict_clf.py` | 新增 | 矛盾检测分类器训练（bge-m3 新旧两条嵌入 + LR 二分类，复用分类器基建，落盘 models/memory_conflict_clf.joblib） |
| `ai_service/tests/test_memory_evolution2.py` | 新增 | 类型化 + 冷降权测试 |
| `ai_service/tests/conftest.py` | 修改 | autouse 钉住新开关 false |
| `specs/module-062-memory-evolution2/{changelog,review-report,test-report}.md` | 新增 | Developer/Reviewer/Tester 产出 |
| `specs/adr/0007-memory-evolution.md` | 修改 | 状态行更新（P2+P3 已实施） |

### 3.2 数据库变更

```sql
-- documents 表加列（module-062，init_db 幂等 ALTER；本地库跑 migrate_module062.py 先决）
ALTER TABLE documents ADD COLUMN IF NOT EXISTS type            VARCHAR(16) NOT NULL DEFAULT 'fact';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS last_recalled_at TIMESTAMP;
COMMENT ON COLUMN documents.type IS '记忆类型：preference（偏好，慢衰减）/ fact（事实，中衰减）/ event（事件，快衰减）——module-062 P2 类型化衰减';
COMMENT ON COLUMN documents.last_recalled_at IS '长期层最后召回时间——module-062 P3 冷记忆降权依据（久未召回降权不删除）';
```

### 3.3 接口定义

无新 HTTP 端点。新增配置开关与参数：

```
PW_MEMORY_TYPE_DECAY   默认 true（类型化半衰期；false 回退全局 half_life）
PW_MEMORY_COLD_DECAY   默认 true（长期层冷降权；false 回退）
memory_type_half_life  类型半衰期 JSON 或分字段：preference=30 / fact=10 / event=1（天）
memory_cold_decay_days 冷降权起始天数（默认 30 天未召回 → 降权）
memory_cold_decay_min  冷降权最小系数（默认 0.3）
```

### 3.4 业务逻辑说明

#### WP1 类型判断（双方案：分类模型 vs LLM）

```
方案 A 分类模型：bge-m3 冻结特征 + 逻辑回归（复用 module-056 intent_classifier 基建，
  人造 120 条训练 → models/memory_type_clf.joblib；推理封装对齐 intent_classifier）
方案 B LLM：_EXTRACT_PROMPT 加 type few-shot，{"facts": [{content, importance, type}]}
  type ∈ {preference, fact, event}；未知/缺失/非法 → "fact"（中性兜底）
对比：同评测集（30 条，与训练集零重叠）Accuracy/P/R/F1，谁达标（≥0.8）谁上；
  都不达标 → 类型化回退（type 按默认，不预设成功）
复用已部署模型：bge-m3（嵌入）、mDeBERTa NLI（矛盾检测——module-061 已实现但评测
  Recall 0.5<0.8 默认关，本模块不重复做矛盾检测，如实说明）
```

#### WP2 类型化衰减（`_evolve_recall`）

```
改后：decay = 0.5**(age_days / type_half_life)
  type_half_life：preference=30 / fact=10 / event=1（天，config 可调）
  存量无 type（NULL/默认 fact）→ 用 fact=10？——注意：为"存量零回归"，
  fact 半衰期设为与现状 memory_short_half_life=3 的关系——设计：
  保留 memory_short_half_life=3 作为【默认/fact 之外通用值】，type 空 → 用
  memory_short_half_life（现状 3 天，零回归）；fact 类型本身半衰期 10 天
  （新提取带 type=fact 的走 10 天，存量无 type 走 3 天——如实声明此差异）
  或简化：type 空/fact 都走 memory_short_half_life=3（fact 不再单独 10 天），
  只区分 preference(30)/event(1)/其余(3)——【推荐】避免存量差异，口径清晰。
升级逻辑不动（≥2/7 天，未按类型区分，如实声明）。
```

#### WP3 冷记忆降权（`recall` 长期层）

```
改后：检索命中后加权——days_since = now - (last_recalled_at or created_at)
  cold_factor = 1.0（days_since < memory_cold_decay_days=30）
              = max(memory_cold_decay_min=0.3, 1.0 - (days_since-30)/100)（平滑渐降，30→100 天 1.0→0.3）
  最终分 = 语义分 × cold_factor
  last_recalled_at 缺失（存量）→ cold_factor=1.0（零回归）
  召回命中 → fire-and-forget 刷新 last_recalled_at=now（不阻塞）
短期层不降权（已有衰减），如实声明。
```

### 3.5 异常处理

| 异常场景 | 处理方式 |
|----------|----------|
| LLM 类型判断失败/超时 | `extract_facts` 返回 facts 无 type → 默认 fact（fail-open） |
| 类型化衰减计算异常 | 用 memory_short_half_life 兜底（现状行为，零回归） |
| 冷降权计算异常 | cold_factor=1.0 不降权（fail-open 不影响召回） |
| documents 缺新列（未迁移） | init_db 幂等 ALTER 自动补；本地 migrate_module062.py 先决 |

---

## 4. WP 拆解与通过标准

### WP1 类型判断双方案对比（分类模型 vs LLM，谁好谁上）

> 用户决策：类型判断用分类模型（bge-m3+LR，复用 module-056 intent 基建）与 LLM 实测对比，谁达标谁上，数据说话。

- **方案 A 分类模型**：`build_memory_type_dataset.py`（人造 120 条训练集）+ `train_memory_type_clf.py`（复用 train_intent_classifier 模式）→ memory_type_clf.joblib
- **方案 B LLM**：`extract_facts` 输出 type（few-shot，默认 fact）
- **对比**：`memory_type_dataset.py` 同集评测（30 条，与训练集零重叠），Accuracy/P/R/F1，eval_runs 含 model 字段
- **通过标准**：对比表如实记录；达标线 Accuracy≥0.8——谁达标谁上（双达标取高分）；都不达标 → 类型化回退；`memory_type_mode`（clf/llm/none）定生产注入

### WP2 P2 类型化衰减

- documents 加 type 列 + `_evolve_recall` 按 type 半衰期（preference 30/event 1/其余 3）+ 开关
- **通过标准**：不同 type 同 age 衰减系数不同（单测）；存量无 type → 现状 3 天半衰期零回归；开关 false 回退

### WP3 P3 冷记忆降权

- documents 加 last_recalled_at + `recall` 长期层冷降权 + 刷新 + 开关
- **通过标准**：久未召回降权（单测系数）/ 最近召回 ×1.0 / 存量无 last_recalled_at 不降权 / 刷新 fire-and-forget / 开关 false 回退

### WP4 矛盾检测分类器训练启用（用户决策：自建 100+ 案例训练，Precision 达标启用）

> 用户决策：自建 100+ 记忆矛盾案例训练矛盾检测；**Precision ≥ 0.8 就启用**（module-061 `PW_MEMORY_CONFLICT` 打开），Recall 后续提升不阻塞。module-061 已用 mDeBERTa NLI（Precision 1.0/Recall 0.5 未达原双门槛默认关）——本 WP 训练分类器对比后启用。

- 数据 `build_memory_conflict_train.py`（100+ 记忆矛盾案例，与评测集零重叠）+ 训练 `train_memory_conflict_clf.py`（bge-m3 嵌入新旧两条 → 拼接/差特征 → LR 二分类）+ clf vs mDeBERTa NLI 同集对比（Accuracy/P/R/F1）——**Precision ≥ 0.8 者启用**（clf 达标用 clf，mDeBERTa 达标用 mDeBERTa，双达标取 Precision 高者）
- 达标后 `PW_MEMORY_CONFLICT=true` 且 `_merge_duplicate` 矛盾分流真实生效；不达标保持关如实标注
- **通过标准**：训练集 100+ + 训练 + 对比表 + 启用判定明确；Recall 后续提升入 backlog

### WP5 测试 + 文档 + 记忆

- `test_memory_evolution2.py` + conftest 钉住 + changelog/review/test + ADR-0007 状态行 + memory 三件套 + CONTEXT 只增
- **通过标准**：全量 825+新增全绿；记忆硬性约束满足

---

## 5. 验收概述

> 详细验收标准见同目录 `acceptance-criteria.md`。

核心验收项：
1. extract_facts 输出 type（LLM 判类型 + 默认 fact）
2. 类型化半衰期：preference 慢 / event 快 / 其余现状
3. 冷记忆降权：长期层久未召回 ×0.3、最近 ×1.0、不删除
4. 存量零回归（无 type → 现状半衰期、无 last_recalled_at → 不降权）
5. 评测 baseline 如实记录，类型判断不达标 → 回退（不预设成功）
6. 全量 825+新增全绿；存量 test_memory 零改动

---

## 6. 风险点与注意事项

### 6.1 已知风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| LLM 类型判断不准 | 类型化衰减基于错类型 | 中 | 评测驱动：Accuracy<0.8 回退（type 按默认）；不预设成功 |
| 存量记忆零回归破 | 存量测试漂移 | 中 | 存量无 type → 现状半衰期；无 last_recalled_at → ×1.0；conftest 钉住开关 |
| 新列未迁移 | 查询报错 | 中 | init_db 幂等 ALTER + migrate_module062.py 本地先决（061 先例） |
| event 衰减太快 | 事件记忆迅速失效 | 低 | 半衰期可调（config）；1 天是参考值，按评测/实际调整 |
| 冷降权过度 | 旧记忆几乎不召回 | 低 | 温和系数 ×0.3 下限 + 不删除 + 可调参数 |

### 6.2 技术注意事项

- [ ] `_evolve_recall` 公式结构不变（只换 half_life 来源），改动最小化
- [ ] `recall` 降权在动态 K 前后？——先检索 → 降权 → 动态 K 截断（降权影响排序后截断，如实声明顺序）
- [ ] last_recalled_at 刷新 fire-and-forget（对齐提及刷新模式，不阻塞召回）
- [ ] 类型判断 few-shot 写在 `_EXTRACT_PROMPT`，格式向后兼容（无 type 容错）

### 6.3 开发建议

- 先 WP1（类型判断 + 评测）→ WP2（类型化）→ WP3（冷降权）→ WP4
- 类型化半衰期用推荐"只区分 preference/event/其余"（避免存量差异）
- 测试 mock LLM 类型判断，不依赖真实 LLM 跑全量

---

## 7. 依赖关系

### 7.1 上游依赖（已完成）

| 依赖模块 | 依赖内容 |
|----------|----------|
| module-046 | 短期进化机制（衰减/加权/升级）、_evolve_recall |
| module-035 | 动态 K、绝对余弦口径 |
| module-061 | documents 加列先例（init_db ALTER + migrate 脚本）、superseded 机制 |

### 7.2 外部依赖

| 外部服务 | 用途 | 可用性要求 |
|----------|------|------------|
| LLM | 提取时类型判断 | 失败默认 fact（fail-open） |
| PostgreSQL | type/last_recalled_at 列 | 同现有（写库失败 fail-open） |

---

## 8. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-13 | 初始版本（P2 类型化衰减 + P3 冷记忆降权 + 类型评测） | Planner |
