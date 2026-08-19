# Module-062 变更日志 — 记忆进化 2（类型化衰减 + 冷记忆降权，ADR-0007 P2+P3）

> Developer 产出 | 2026-08-13 | 中文，含双方案对比数字 + 达标判定 + 已知边界/口径声明
> 开工前已读 memory/project-context.md 全文（模块清单/ADR 索引/迭代状态）

## 一、实现总览

本模块落地 ADR-0007 P2（类型化衰减，A-MAC 参考）+ P3（冷记忆降权，Memory Decay）。四个工作包：

| WP | 内容 | 产出 |
|----|------|------|
| WP1 | 类型判断双方案对比（分类模型 vs LLM，谁达标谁上） | build/train/eval 三脚本 + memory_type_clf.joblib + extract_facts type |
| WP2 | 类型化衰减（documents.type + _evolve_recall 按 type 半衰期） | config 开关 + 半衰期映射 |
| WP3 | 冷记忆降权（documents.last_recalled_at + recall 长期层加权 + 刷新） | config 开关 + _apply_cold_decay |
| WP4 | 矛盾检测分类器训练启用（自建 142 案例 vs mDeBERTa 对比，Precision≥0.8 启用） | build/train 脚本 + memory_conflict_clf.joblib + 裁判切换 |

全量 pytest **895 passed / 0 failed**（825 基线 + 70 新增 test_memory_evolution2.py；3 处存量 test_memory_extractor.py 精确结构断言按验收许可补 type 字段——见 §6）。

## 二、WP1 类型判断双方案对比（数据说话，谁达标谁上）

### 2.1 方案 A 分类模型（bge-m3 + 逻辑回归，复用 module-056 intent 基建）

- 训练集：`eval/build_memory_type_dataset.py` 人造 **120 条**（preference 40 / fact 40 / event 40），与评测集**字符串零重叠**（build 校验强制，实测 0 重叠）。
- 训练：`scripts/train_memory_type_clf.py` → 落盘 `models/memory_type_clf.joblib`。bge-m3 冻结特征（1024 维）+ `LogisticRegression(class_weight="balanced")`。**test split Accuracy 1.0000**（24 条，三类别全 1.0，混淆矩阵对角全满）。
- 评测：`eval/memory_type_dataset.py`（30 条：preference 10 / fact 10 / event 10，与训练集零重叠）——clf 同集 Accuracy **1.0000**（eval_runs **id=32**）。

### 2.2 方案 B LLM（extract_facts 输出 type）

- `_EXTRACT_PROMPT` 加 type few-shot（preference=偏好/习惯、fact=客观事实、event=带时间临时事件），输出 `{"content", "importance", "type"}`；缺失/非法/超时 → 默认 `"fact"`（fail-open，向后兼容——旧调用方取 content/importance 不受影响）。
- 评测：同 30 条评测集（对话注入 content → extract_facts 提取 → 匹配事实取 type），Accuracy **1.0000**（eval_runs **id=33**，真实 deepseek 运行，30/30 全对）。

### 2.3 对比与判定

| 方案 | Accuracy | 达标(≥0.8) | 备注 |
|------|----------|------------|------|
| clf（bge-m3+LR） | **1.0000** | ✅ | 零成本/确定性/离线，推理毫秒级 |
| LLM（extract_facts） | **1.0000** | ✅ | 每次提取一次 LLM 调用，有成本与限流风险 |

**判定：双达标且同分（1.0000）→ 取 clf**（`memory_type_mode="clf"`）。理由：零成本、确定性、离线无限流，对齐 module-056 L4"分类器替代 LLM"哲学；LLM 输出仍作为 clf 推理失败的兜底（`resolve_memory_type`：clf 加载/推理失败 → 回退 extract_facts 的 type → 再回退 fact）。生产注入点 `engine._persist_memory`（每条事实 resolve_memory_type → save/save_short 带 memory_type）。

**诚实边界（口径声明）**：评测集 30 条与训练集同为"用户喜欢/偏好/明天/下周"句式，属**同分布**——1.0000 含一定"同分布偏乐观"成分，不代表真实用户记忆的泛化能力；真实分布以飞轮数据积累后重训为准（MemoryTypeClassifier.fit 接口已预留）。**50/50 双 1.0 均在 30 条小集上，量级声明**：趋势可信（偏好/事实/事件在 bge-m3 空间分群明显），绝对 1.0 不可外推到真实分布。

## 三、WP2 类型化衰减（P2，A-MAC 参考）

- **documents 加 `type` 列**（VARCHAR(16) NOT NULL DEFAULT 'fact'，init_db 幂等 ALTER `MEMORY_TYPE_COLUMNS_DDL` + `scripts/migrate_module062.py` 本地先决**已执行**——本地库 documents.type/last_recalled_at 两列已补，校验通过）。
- `_evolve_recall` 按 type 差异化半衰期（`_type_half_life`）：**preference=30 天（慢，偏好长期有效）/ event=1 天（快，临时事件迅速过期）/ 其余（fact/未知/存量无 type）→ `memory_short_half_life`=3 天（现状，存量零回归口径）**——采用 plan 推荐的"只区分 preference/event/其余"简化，避免存量差异。
- 开关 `PW_MEMORY_TYPE_DECAY` 默认 **true**；false 回退全局 half_life（现状行为）。单测：同 age 5 天 preference decay≈0.89 vs event decay≈0.03（系数不同）；存量无 type → 3 天半衰期零回归；开关关 → 全局 half_life。
- 升级逻辑**不动**（≥2 次/7 天，未按类型区分——如实声明，plan 优先只做衰减率区分）。

## 四、WP3 冷记忆降权（P3，Memory Decay）

- **documents 加 `last_recalled_at` 列**（TIMESTAMP，同批 ALTER，可空）。
- `recall`（长期层）检索命中后 `_apply_cold_decay`：按距上次召回（`last_recalled_at or created_at`）天数加权——
  `cold_factor = 1.0`（< `memory_cold_decay_days`=30 天，最近召回）/ `max(memory_cold_decay_min=0.3, 1.0-(days-30)/100)`（平滑渐降，30→100 天 1.0→0.3）。**最终分 = 语义分 × cold_factor；不删除旧记忆（可回溯）**。
- 召回命中 → fire-and-forget 刷新 `last_recalled_at=now`（`_refresh_last_recalled`，冷记忆升温，对齐 module-046 提及刷新模式）。
- **顺序声明**：检索 → 降权 → 动态 K 截断（降权影响排序后截断，久未召回可能被挤出前 K）。
- **短期层不降权**（已有衰减），如实声明；开关 `PW_MEMORY_COLD_DECAY` 默认 **true**；false 回退。
- 降级（fail-open）：参考文档加载失败/参考时间缺失/计算异常 → cold_factor=1.0 不降权，不影响召回主链路；存量无 last_recalled_at → 按 created_at 计算（零迁移）。
- 单测：90 天 → ×0.4、最近 1 天 → ×1.0、200 天 → ×0.3（下限）、存量无时间字段 → ×1.0、开关关 → ×1.0、DB 失败 → 保持原分、降权后按新分重排、recall 集成调用。

## 五、WP4 矛盾检测分类器训练启用（用户决策：自建 100+ 案例，Precision≥0.8 启用）

### 5.1 数据 + 训练

- 训练集：`eval/build_memory_conflict_train.py` 自建 **142 条**（contradiction 82：改口 30/迁移 20/过时 12/升级冲突 10/其它互斥 10；non_conflict 60：entailment 30/neutral 30），与评测集（memory_conflict_dataset 30 条）**字符串零重叠**（build 校验强制，实测 0 重叠——初版发现 22 处复用评测集措辞已全部改写）。
- 训练：`scripts/train_memory_conflict_clf.py` → `models/memory_conflict_clf.joblib`。特征 = bge-m3 分别嵌入新旧两条记忆 → 拼接 + 差值 + 绝对差值（4096 维，编码"关系位移"）→ `LogisticRegression(class_weight="balanced")`。**test split：Accuracy 0.8966 / contradiction Precision 0.9000 / Recall 0.9500**。

### 5.2 同集对比（eval/memory_conflict_dataset.py，30 条评测集）

| 判定器 | Accuracy(3类) | contradiction Precision | Recall | F1 | eval_runs |
|--------|---------------|------------------------|--------|-----|-----------|
| **clf**（bge-m3+LR，142 案例） | 0.7333 | **0.9048**（tp=19/fp=2） | **0.9500** | 0.9268 | id=34 |
| **nli**（mDeBERTa，module-061 复现） | 0.6000 | **1.0000**（tp=10/fp=0） | 0.5000 | 0.6667 | id=35 |

### 5.3 达标判定（用户决策规则）

- 用户规则：**Precision≥0.8 者启用**（Recall 后续提升不阻塞，保守方向：宁可漏检也不错标）；双达标取 **Precision 高者**。
- 两者 Precision 均 ≥0.8；**nli Precision 1.0000 > clf 0.9048 → nli 启用**（`PW_MEMORY_CONFLICT=true` + `PW_MEMORY_CONFLICT_JUDGE=nli`）。
- 这**覆盖/反转了 module-061 的默认关**（旧双门槛 Recall≥0.8 且 Precision≥0.8 未达标）——module-062 用户决策把门槛改为 Precision-only，mDeBERTa（Precision 1.0）达标。
- **口径声明**：clf 实际 Recall 更高（0.95 vs 0.5），但用户规则取 Precision 高者；mDeBERTa 漏判（Recall 0.5）= 无害降级（旧记忆仍拼接共存，不误标过期），正是"保守方向"。产品如需更全召回，`PW_MEMORY_CONFLICT_JUDGE=clf` 一键切换（config 已预置）。**clf 实测也有一处冒烟中性对误判**（"喜欢喝咖啡" vs "养猫" 判 contradiction——恰为其 2 个 fp 之一），如实标注。
- 启用后 `_merge_duplicate` 矛盾分流真实生效（NLI 判 contradiction → 旧父块 superseded + 新内容正常新增）；NLI 不可用/超时 → None → 旧行为（追加拼接，零回归）。
- **Recall 后续提升方向（入 backlog）**：扩充矛盾样本（真实改口数据）、调阈值/置信度校准、更强中文 NLI。

## 六、测试与存量兼容

- 新增 `tests/test_memory_evolution2.py` **70 用例**：extract_facts type / MemoryTypeClassifier / resolve_memory_type 三模式 / _type_half_life / _evolve_recall 类型化衰减 / _apply_cold_decay（系数/下限/存量/开关/DB 失败/重排/刷新）/ _refresh_last_recalled / recall 集成 / save 写 type / _persist_memory 类型注入 / _judge_conflict 裁判切换 / MemoryConflictClassifier / 评测集与指标纯函数 / 训练集零重叠 / DDL 幂等 / 配置默认值。
- **conftest autouse 钉住**：`memory_type_mode='none'`（类型注入 hermetic）、`memory_cold_decay_enabled=False`（存量 recall 测试零触发冷降权）、`memory_conflict_judge='nli'`（module-061 NLI 测试语义保持）；`memory_conflict_enabled=False`（module-061 既有钉住）。测试体内显式 setattr 覆盖验证各开关。
- **存量测试改动（验收许可）**：`tests/test_memory_extractor.py` 3 处精确结构断言补 `type: "fact"` 字段（extract_facts 返回结构加 type 为**增量**，AC §6 明确"旧调用方取 content/importance 不受影响"——这 3 处是断言整个返回 dict 的精确相等，需反映新字段）。其余存量测试零改动（documents 新列默认值兜底 / conftest 钉住开关）。
- 全量 pytest **895 passed / 0 failed**。

## 七、已知边界 / 口径声明

1. **类型判断 1.0 属同分布小集**：30 条评测集与训练集同句式，1.0 不代表真实泛化；真实分布以飞轮重训为准。
2. **clf 推理冒烟误判**：矛盾分类器对个别中性对误判（Precision 0.9048 即含 2 fp）；nli 为生产 winner（Precision 1.0），误判面不影响生产。
3. **WP2 升级阈值未按类型区分**（保持 ≥2/7 天）；P3 仅长期层降权（短期已有衰减）。
4. **P3 冷降权不删除旧记忆**（×0.3 下限保留可回溯）；长期层每召回多一次参考文档 SELECT + fire-and-forget UPDATE（O(n)，对齐 module-046 进化模式）。
5. **类型注入依赖分类器模型部署**：`models/memory_type_clf.joblib` 为新环境部署产物（gitignored），缺失时 `resolve_memory_type` 自动回退 LLM type → fact（fail-open，零影响）。
6. **矛盾消解启用后写路径成本**：PW_MEMORY_CONFLICT=true 后每次去重命中跑一次 mDeBERTa 推理（20s 超时 + 失败回退旧行为）；模型缺失环境自动 fail-open。
7. **eval_runs 落库**：id=32（type clf）/ 33（type llm）/ 34（conflict clf）/ 35（conflict nli），git_commit=8e014907。

## 八、面试口径更新点

- **记忆类型化衰减（A-MAC 参考）**：偏好/事实/事件三类半衰期（30/1/3 天），偏好慢衰减事件快过期——从"一刀切 3 天"到按记忆类型区分新鲜度；类型来源用 bge-m3+LR 分类器（0 成本）实测与 LLM 同 1.0。
- **冷记忆降权不删旧（Memory Decay）**：长期层久未召回 ×0.3 降权不删除（可回溯），召回命中刷新 last_recalled_at 升温——对比"一刀切 TTL 悬崖式过期"。
- **矛盾检测 Precision 达标启用**：自建 142 案例训练分类器（Precision 0.90/Recall 0.95）与 mDeBERTa（Precision 1.0/Recall 0.5）同集对比，按用户规则取 Precision 高者启用 mDeBERTa——"数据说话、保守方向宁可漏检也不错标、Recall 提升留 backlog"。

---

## 九、修复记录（Review 第 1 轮，P3 冷降权真实 DB 下静默失效）

**问题**：冷记忆降权在真实 DB 下静默失效（`memory.py::_apply_cold_decay` + `_cold_ref_time` + `_refresh_last_recalled`）。

- `now = datetime.now(timezone.utc)`（aware）与 `ref = _cold_ref_time(doc)` 相减；`documents.last_recalled_at` 列 DDL 为 `TIMESTAMP`（无 tz），`_refresh_last_recalled` 写入 aware UTC 后 PG 落库丢弃 tz、读回 naive。
- `now - ref` 抛 `TypeError: can't subtract offset-naive and offset-aware datetimes`，被 `except (TypeError, ValueError): factor = 1.0` 吞掉 → **任何被召回过一次（last_recalled_at 已写）的记忆后续每次冷降权都恒 ×1.0**——刷新机制（召回即升温）把降权算术毒化，WP3 生产功能不成立。真实 DB 写读往返已实测复现（写 90 天前时间 → 读回 tzinfo=None → 减法 TypeError）。
- 单测全用 tz-aware mock 父块，未覆盖 DB 往返 naive 形态，故 895 全绿也掩盖该缺陷。

**修复（`_cold_ref_time` 源头规范化，单点）**：`_cold_ref_time` 返回前对 naive 时间戳补 `if ref.tzinfo is None: ref = ref.replace(tzinfo=timezone.utc)`——**直接对齐 `_evolve_recall`（memory.py:810-811）既有同款规范化模式**（module-046 已用同法解决同一问题）。返回值恒为 tz-aware，`_apply_cold_decay` 的 aware-aware 减法不再抛 TypeError；`except` 降级路径恢复为只兜真正异常的 fail-open。

**DDL 处理（如实声明取舍）**：`last_recalled_at` 列保持 `TIMESTAMP`（未改 `TIMESTAMPTZ`），理由：① 代码层规范化已完整修复，module-046 处理 `last_mentioned_at`（同为无 tz 列）就是纯代码方案且长期稳定；② 本地库该列已按 `TIMESTAMP` 建好，改 DDL 需 ALTER COLUMN TYPE 迁移存量列（PG 会按会话时区重解释存量值，存在时区偏移风险），收益不抵风险——"双保险"取舍为代码规范化 + naive 按 UTC 解释这一确定性语义（`_refresh_last_recalled` 写入的本就是 UTC 值，读回 naive 补 UTC 语义无损）。

**新增测试（2 条，锁定修复）**：
- `TestColdDecay::test_naive_db_roundtrip_still_decays`：输入 naive（tzinfo=None）90 天前时间 → 仍按 UTC 解释降权 ×0.4 → 0.36（修复前被 TypeError 吞掉恒 ×1.0）。
- `TestColdRefTime::test_naive_ref_normalized_to_utc`：`_cold_ref_time` 对 naive 输入返回 tz-aware（tzinfo=utc）且墙钟时间不变。

**自测**：`tests/test_memory_evolution2.py -k "ColdDecay or ColdRefTime"` 15 passed；全量 pytest **897 passed / 0 failed**（895 基线 + 2 新增）。

**涉及文件**：`ai_service/rag/memory/memory.py`（`_cold_ref_time` 规范化）、`ai_service/tests/test_memory_evolution2.py`（2 条新测试）。无新文件，memory/file-index.md 无需更新。
