# 功能规格说明书 — Module-061: 记忆纠错（升级留后悔药 + 冲突消解）

> 本文件由 **Planner** 输出，作为模块开发的唯一权威规格文档。
> Developer 严格按本文件编码，Reviewer 和 Tester 按本文件验收。
> 详细执行简报见同目录 `task-brief.md`（已探明事实，勿重复调研）。

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-061 |
| 模块名称 | 记忆纠错（ADR-0007 P0+P1：升级留后悔药 + 写路径冲突消解） |
| 优先级 | P1（改坏记忆风险最高的部分先治，ADR-0007 明确"先做 P0 撤销能力 + 评测"） |
| 预估代码量 | 功能代码（不含注释/测试）约 200-250 行（NLI 封装 + 冲突分流 + superseded 标记）；含注释/测试约 600-700 行——按含注释/测试口径预估，豁免默认 ≤200 功能代码上限 |
| 创建日期 | 2026-08-13 |
| 最后更新 | 2026-08-13 |
| 负责人 | Planner: 主会话, Developer: vibe-coding-workflow |

---

## 2. 需求描述

### 2.1 需求来源

- 来源类型：用户输入（"后续任务是记忆机制的优化"）+ ADR-0007（P0/P1 待实施清单）+ 范围确认（用户选 P0+P1）
- 原始描述：记忆系统两个真实软肋——升级单向不可逆（`_promote_memory` 复制后删短期副本）、去重是追加不是替换（`_merge_duplicate` 拼接共存"讨厌咖啡\n喜欢咖啡"）。需纠错能力 + 写路径冲突消解。

### 2.2 用户故事

```
作为 知识库问答的使用者
我想要 记忆被"记错/改口"时能纠正（升级留后悔药 + 新旧说法冲突时旧说法标记过期而非拼接共存）
以便 召回时不会把过时说法和最新说法混在一起让系统猜
```

### 2.3 验收场景（BDD 格式）

```
场景 1：升级留后悔药
  假设 短期记忆"用户喜欢咖啡"提及≥2 次触发升级长期
  当 _promote_memory 执行
  那么 长期层新增该记忆（superseded=false + updated_at）；短期副本保留（不删除）；重复升级幂等

场景 2：改口冲突消解（写路径）
  假设 长期已有记忆"用户讨厌咖啡"，新事实"用户喜欢咖啡"去重命中该记忆（cosine>阈值）
  当 _merge_duplicate 走 NLI 冲突检测
  那么 NLI 判 contradiction → 旧父块标 superseded=true + updated_at；新内容按正常新增入库（两条共存但旧的可追溯）

场景 3：一致追加零回归
  假设 新事实与既有记忆 NLI 判 entailment/neutral，或 NLI 不可用（None）
  当 _merge_duplicate
  那么 保持现行为（追加拼接 content），库内行为与 module-046 完全一致

场景 4：评测驱动启用
  假设 记忆矛盾标注集评测 NLI 判定准确率
  当 评估 baseline
  那么 达标（contradiction Recall/Precision ≥ 0.8）→ 开关默认可开；不达标 → 如实标注，开关保持默认关
```

### 2.4 非功能需求

| 类别 | 要求 |
|------|------|
| 响应时间 | 写入路径 NLI 检测有预算（超时降级旧行为）；CPU 推理 to_thread 不阻塞事件循环 |
| 可用性 | fail-open：NLI 不可用/超时 → None → 旧行为；superseded 标记失败 → 日志告警不阻断写入 |
| 兼容性 | 开关默认 false 完全旧行为零回归；存量记忆测试零改动 |
| 数据安全 | SUPERSEDED **不删除**用户记忆（可审计可回溯，Zep 模式） |

---

## 3. 技术方案

### 3.1 涉及文件

| 文件路径 | 操作类型 | 说明 |
|----------|----------|------|
| `ai_service/rag/memory/nli_judge.py` | 新增 | mDeBERTa NLI 生产封装（延迟加载 + to_thread + 失败 None，对齐 factcheck_judge 模式） |
| `ai_service/rag/memory/memory.py` | 修改 | `_promote_memory`（升级不删短期 + superseded/updated_at）、`_merge_duplicate`（NLI 冲突分流）、`_evolve_recall`（过滤 superseded） |
| `ai_service/rag/models.py` | 修改 | `Document` 加 `superseded`/`updated_at` 字段 |
| `ai_service/src/database.py` | 修改 | documents 表加列（init_db 幂等 ALTER，对齐项目模式；本地库先 ALTER 先决） |
| `ai_service/src/config.py` | 修改 | `memory_conflict_enabled`（PW_MEMORY_CONFLICT 默认 false）+ superseded 召回策略 |
| `ai_service/eval/memory_conflict_dataset.py` | 新增 | 记忆矛盾标注集（20-30 条）+ NLI baseline 脚本 |
| `ai_service/tests/test_memory_correction.py` | 新增 | P0+P1 测试 |
| `ai_service/tests/conftest.py` | 修改 | autouse 钉住 memory_conflict_enabled=false |
| `specs/module-061-memory-correction/{changelog,review-report,test-report}.md` | 新增 | Developer/Reviewer/Tester 产出 |
| `specs/adr/0007-memory-evolution.md` | 修改 | 状态行更新（P0+P1 已实施） |

### 3.2 数据库变更

```sql
-- documents 表加列（module-061 P0，init_db 幂等 ALTER；本地库先 ALTER 先决）
ALTER TABLE documents ADD COLUMN IF NOT EXISTS superseded  BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;
COMMENT ON COLUMN documents.superseded IS '记忆是否已被新说法取代（true=SUPERSEDED，不删除可审计，Zep 模式）';
COMMENT ON COLUMN documents.updated_at IS '记忆最近更新（升级/冲突标记/去重追加时刷新）';
```

**不新建表**（三层记忆仍复用 documents 表 + source 前缀隔离）。

### 3.3 接口定义

无新 HTTP 端点（纯内部逻辑改造）。新增配置开关：

```
PW_MEMORY_CONFLICT  默认 false（评测达标后才启用，对齐 ADR-0003 L4 放行模式）
```

### 3.4 业务逻辑说明

#### WP2 P0 升级留后悔药（`_promote_memory`）

```
改前：复制长期（无向量父块+有向量子块，content_hash 幂等检查）→ 删除短期副本（父块+子块）
改后：复制长期（同上 + superseded=false + updated_at=now）→ 短期副本【保留】（转标记或直接留）
      ——"抄进笔记本不撕草稿纸"，后悔药=短期层仍可衰减淘汰、长期层新条目可审计
幂等：长期层已有同 content_hash → 不重复复制（现有逻辑保留）；重复升级不产生垃圾
召回：_evolve_recall 与检索查询过滤 superseded=true（用户最新说法优先，旧说法不参与召回）
```

#### WP3 P1 冲突消解（`_merge_duplicate` 分流）

```
去重命中（cosine>memory_dedup_threshold）后：
  若 memory_conflict_enabled 且 NLI 可用：
    verdict = nli_judge.predict(新事实, 旧父块content)
    contradiction → 旧父块 superseded=true + updated_at=now；新内容按正常新增入库（不拼接共存）
    entailment/neutral → 保持现行为（追加拼接 content）
  否则（开关关 / NLI None / 超时）→ 保持现行为（追加，零回归）
```

#### NLI 生产封装（`rag/memory/nli_judge.py`）

对齐 module-050/051 `hhem_loader` + `factcheck_judge` 模式：共享加载器（`nli_loader.py` 或内联）+ 延迟加载（首次调用才加载 557MB）+ `threading.Lock` + `asyncio.to_thread` + 超时/异常/缺失 → 返回 None（上层降级旧行为）。加载逻辑复用 `eval/retest_nli.py`（勿重写加载路径）。

### 3.5 异常处理

| 异常场景 | 处理方式 |
|----------|----------|
| NLI 不可用/加载失败/超时 | predict 返回 None → `_merge_duplicate` 走旧行为（追加拼接，零回归） |
| superseded 标记写库失败 | 日志告警，按旧行为追加（fail-open 不阻断写入） |
| documents 表缺 superseded 列（未 ALTER） | init_db 幂等 ALTER 自动补；本地库手动 ALTER 先决（module-046 经验） |

---

## 4. WP 拆解与通过标准

### WP1 评测闭环（先度量）

- `eval/memory_conflict_dataset.py`：记忆矛盾标注集（20-30 条：改口/迁移/过时/升级冲突/正例）+ NLI baseline（复用 retest_nli 逻辑）
- **通过标准**：标注集落盘 + baseline 数字（P/R/F1）如实记录；达标线 contradiction Recall≥0.8 且 Precision≥0.8（建议值，可微调但如实声明）

### WP2 P0 升级留后悔药

- `_promote_memory` 不删短期副本 + 长期 superseded=false/updated_at=now；`Document` 加字段；documents 表加列；召回/检索过滤 superseded
- **通过标准**：升级后短期副本保留、长期新条目标记正确、重复升级幂等、superseded 不参与召回；全量回归

### WP3 P1 冲突消解

- `nli_judge.py` 生产封装 + `_merge_duplicate` 分流（矛盾→SUPERSEDED+新增 / 一致→追加 / 降级→旧行为）
- **通过标准**：三路径单测覆盖（mock NLI）；NLI None 降级零回归；开关 false 完全旧行为

### WP4 测试 + 文档 + 记忆

- `test_memory_correction.py` + conftest 钉住 false + changelog/review/test + ADR-0007 状态行 + memory 三件套 + CONTEXT 只增
- **通过标准**：全量 797+新增全绿；记忆硬性约束满足

---

## 5. 验收概述

> 详细验收标准见同目录 `acceptance-criteria.md`。

核心验收项：
1. P0：升级不删短期副本 + superseded/updated_at 标记 + 召回过滤
2. P1：NLI 生产封装 + `_merge_duplicate` 冲突分流（矛盾→SUPERSEDED+新增，一致→追加）
3. 降级：NLI 不可用/开关关 → 完全旧行为零回归；SUPERSEDED 不删除
4. 评测：标注集 baseline 如实记录，达标才启用（不预设成功）
5. 全量 797+新增全绿；存量记忆测试零改动

---

## 6. 风险点与注意事项

### 6.1 已知风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| mDeBERTa 矛盾判别短板（历史 kappa<0.7） | NLI 判定不达标 → 冲突消解误标 | 中 | 评测驱动：达标才启用（默认关）；记忆级场景（短句偏好/事件）比 claim_vs_doc 聚焦，仍以数据验证 |
| NLI 557MB 模型加载拖慢首次写入 | 首次写入延迟 | 低 | 延迟加载 + 降级旧行为（不阻塞写入主链路） |
| superseded 列未迁移 | 查询报错 | 中 | init_db 幂等 ALTER + 本地库手动 ALTER 先决（module-046 经验） |
| 升级不再删短期副本 | 短期层条数增长 | 低 | 短期层本来有 30 天硬上限 + 衰减 + 提及刷新（module-046），保留副本会被自然淘汰；如实记录口径 |
| 存量记忆测试漂移 | 默认开影响 module-033/046 测试 | 高 | conftest autouse 钉住 memory_conflict_enabled=false（对齐 056/058/060 成熟模式） |

### 6.2 技术注意事项

- [ ] NLI 封装延迟加载：模型 557MB，首次加载秒级；加载失败记 flag 不重试（对齐 hhem_judge）
- [ ] `_merge_duplicate` 分流要保持事务一致性（标记+新增同一事务）
- [ ] superseded 过滤要覆盖 `_evolve_recall` + 检索查询 + 注入路径（三层记忆统一口径）
- [ ] 评测标注集要包含"正例/中性"（不能全是矛盾，防止 Recall 虚高）

### 6.3 开发建议

- 先 WP1 评测（用数据定 P1 是否启用），再 WP2 P0（独立可交付），最后 WP3 P1
- NLI 加载复用 `eval/retest_nli.py` 既有路径，不重写（对齐 hhem_loader 单一来源原则）
- 测试 mock NLI（`mock.patch("rag.memory.nli_judge...")`），不依赖真实 557MB 模型跑全量

---

## 7. 依赖关系

### 7.1 上游依赖（已完成）

| 依赖模块 | 依赖内容 |
|----------|----------|
| module-033/034/035/046 | 三层记忆架构、进化机制（提及/衰减/升级）、去重阈值 0.85 |
| module-052/054/057 | mDeBERTa NLI 模型部署 + 评测基建（build_contradiction_dataset 模式） |
| module-050/051 | 共享加载器模式（hhem_loader/hhem_judge）——NLI 封装对齐 |

### 7.2 外部依赖

| 外部服务 | 用途 | 可用性要求 |
|----------|------|------------|
| PostgreSQL | documents 表 superseded/updated_at 列 | 同现有（写库失败 fail-open） |
| mDeBERTa NLI 模型（本地 557MB） | 冲突判定 | 不可用降级旧行为（零回归） |

---

## 8. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-13 | 初始版本（用户范围确认：P0+P1 记忆纠错 + 评测闭环） | Planner |
