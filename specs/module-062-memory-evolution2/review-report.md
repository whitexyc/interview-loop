# Module-062 审查报告 — 记忆进化 2（类型化衰减 + 冷记忆降权）

> Reviewer 产出 | 2026-08-13 | **第 2 轮** verdict：**pass**（MAJOR-1 已修复，无新引入问题；6 项 minor 保持非阻塞）
> 对照 `specs/module-062-memory-evolution2/acceptance-criteria.md` 8 维逐条核查

## 一、第 2 轮核查范围

本轮为 **conditional → 复审**：只核查上轮 MAJOR-1 是否修复、修复是否引入新问题，并对 AC 其余项做复核确认（上轮已逐条核实的项不重复展开，仅确认无回退）。

**上轮 MAJOR-1（阻塞）**：`_apply_cold_decay` naive/aware 时间差——`last_recalled_at` 列 DDL 为 `TIMESTAMP`（无 tz），`_refresh_last_recalled` 写入 aware UTC 后 PG 落库丢弃 tz、读回 naive，`now(aware)-ref(naive)` 抛 TypeError 被 fail-open 吞成 ×1.0 → 被召回过一次的记忆后续冷降权恒不生效，WP3 生产功能不成立。

## 二、MAJOR-1 修复核查（独立验证）

| 核查项 | 结果 |
|--------|------|
| 修复落地位置 | `_cold_ref_time`（memory.py:156-157）返回前对 naive 补 `ref.replace(tzinfo=timezone.utc)`——**对齐 `_evolve_recall`（memory.py:818-819）既有 module-046 同款规范化模式**，单点源头修复，`_apply_cold_decay` 的 aware-aware 减法不再抛 TypeError |
| 修复正确性 | `_cold_ref_time` 返回恒为 tz-aware（naive 按 UTC 解释）或 None；`_apply_cold_decay`（memory.py:959-976）`now(aware)-ref(aware)` 正常；`except (TypeError, ValueError): factor=1.0` 降级恢复为只兜真正异常的 fail-open |
| 测试锁定 | `TestColdDecay::test_naive_db_roundtrip_still_decays`（输入 naive tzinfo=None 90 天前 → 仍按 UTC 解释降权 ×0.4 → 0.36，修复前被吞恒 ×1.0）+ `TestColdRefTime::test_naive_ref_normalized_to_utc`（naive 输入返回 tz-aware 且墙钟时间不变）——**恰好补上上轮指出的测试缺口** |
| 全量回归 | 复跑 **897 passed / 0 failed（185s）**（895 基线 + 2 新增），test_memory_evolution2.py 72 项 collect 确认，与 changelog §9 一致 |
| DDL 取舍 | 保持 `TIMESTAMP` 未改 `TIMESTAMPTZ`——changelog §9 如实声明取舍：代码层规范化已完整修复 + module-046 同款长期稳定先例 + ALTER COLUMN TYPE 会对存量值按会话时区重解释存在偏移风险，收益不抵风险。**可接受**（上轮建议中 TIMESTAMPTZ 为"可选双保险"） |
| 无新引入 | `_cold_ref_time` 逻辑变更仅影响 `_apply_cold_decay`（唯一调用方）；`_refresh_last_recalled` 写入路径不变；其余 module-062 代码与上轮逐字一致（无 diff） |

**结论：MAJOR-1 已正确修复并锁定，修复无新引入问题。**

## 三、8 维逐条复核

### 1. 方法学
- ✅ WP1 双方案对比 / WP2 类型化半衰期 / WP4 矛盾 Precision 启用——均与上轮一致，无回退。
- ⚠️ MINOR-3 保持：`memory_conflict_dataset.py` `gate_passed` 仍是旧双门槛（Recall AND Precision），启用 nli id=35 落库 gate_passed=false（changelog 已解释，非本模块引入）。

### 2. 正确性
- ✅ MAJOR-1 修复后 `_apply_cold_decay` 真实 DB 往返语义成立（naive 按 UTC 解释，刷新机制不再毒化降权算术）。
- ✅ `_type_half_life` / `_memory_type_of` / `_merge_duplicate` 矛盾分流均与上轮一致。

### 3. 降级链
- ✅ 冷降权计算异常（真正异常）仍 fail-open ×1.0 不影响召回；开关 false 回退；LLM 类型判断失败 → 默认 fact；矛盾判定器不可用 → 旧行为。全部与上轮一致。
- ✅ documents 缺列 → init_db 幂等 ALTER + migrate_module062.py（DB 实查列在）。

### 4. 诚实性
- ✅ changelog §9 新增"修复记录"节：如实记载 MAJOR-1 复现、修复方案、DDL 取舍理由、2 条新测试、897 全绿——诚实边界保持。

### 5. 测试
- ✅ 70 → 72 项（+2 naive 用例锁定修复）；全量 897 全绿复跑确认。
- ✅ conftest autouse 钉住保持（mode none / cold off / judge nli / conflict off）。
- ✅ 存量零改动保持（3 处 test_memory_extractor.py 精确结构断言补 type 字段为上轮已许可）。

### 6. 结果解读
- ✅ clf/LLM 双 1.0 → 取 clf；矛盾 nli Precision 1.0 > clf 0.9048 → 取 nli；量级声明充分。无回退。

### 7. 风格与最小改动
- ✅ 修复为单点（`_cold_ref_time` 内 1 行 + 注释），对齐既有 `_evolve_recall` 模式，最小改动原则。
- ✅ 其余代码与上轮逐字一致，未因修复引入无关改动。

### 8. 记忆核查（硬性约束）
- ✅ 上轮已验证：project-context module-062 行 + 头部日期、activity Developer/Reviewer 行、file-index、ADR-0007 状态行、CONTEXT 只增。本轮 Reviewer 活动行由本报告追加。
- ⚠️ 见 MINOR-7：修复新增 2 测试后，project-context/file-index 的测试计数（895/70 项）未同步为 897/72（changelog §9 明示"无新文件，file-index 无需更新"，但计数属同一文件内的过时数字）。

## 四、Minor Findings（非阻塞，6 项上轮保持 + 1 项新观察）

1. **MINOR-1（保持）**：env 名与文档不一致——文档通篇写 `PW_MEMORY_TYPE_DECAY`/`PW_MEMORY_COLD_DECAY`/`PW_MEMORY_CONFLICT`，实际 env 变量名是 `PW_MEMORY_TYPE_DECAY_ENABLED`/`PW_MEMORY_COLD_DECAY_ENABLED`/`PW_MEMORY_CONFLICT_ENABLED`（config.py:131 注释仍写短名）。开关可经 config 字段生效，但操作者照文档设 env 关不掉。
2. **MINOR-2（保持）**：`_promote_memory` 长期副本 type 丢失（默认 'fact'）。当前长期层不按 type 衰减（仅短期 recall_short 走 `_evolve_recall`），无行为影响，属口径瑕疵。
3. **MINOR-3（保持）**：`memory_conflict_dataset.py` `gate_passed` 仍为旧双门槛（Recall AND Precision），启用 nli id=35 落库 gate_passed=false，判定依据与落库口径不一致（changelog 已解释）。
4. **MINOR-4（保持）**：memory_type_clf.load()/memory_conflict_clf.load() 每次调用重载磁盘模型（无"已加载"缓存守卫）。模型极小，影响可忽略。
5. **MINOR-5（保持）**：preference 半衰期 30 天 vs 短期硬上限 30 天交互——差异化只在 0-30 天窗口生效（设计交互，非缺陷，建议口径声明）。
6. **MINOR-6（保持）**：`_apply_cold_decay` 的 `identity` 参数未使用（仅签名一致性保留）。
7. **MINOR-7（本轮新观察，非阻塞）**：修复新增 2 测试后，memory/project-context.md（"全量 pytest 895/0"）与 memory/file-index.md（"70 项"）的测试计数未同步为 897/72——changelog §9 声明"无新文件 file-index 无需更新"正确（不新增文件行），但既有行内的计数数字已过时，属轻微文档漂移。

## 五、AC 对照摘要（复核结论）

- §1 WP1 / §2 WP2 / §3 WP3 / §4 WP4：**通过**（WP3 上轮因 MAJOR-1 实质不成立，本轮已修复，可判定通过）
- §5 降级：**通过**；§6 接口兼容：**通过**（加列增量/返回结构增量/公式结构不变）
- §7 测试：**通过**（897 全绿复跑，naive 缺口已补，存量零改动保持）
- §8 文档 + 记忆：**通过**（changelog §9 修复记录 + 本轮 Reviewer 活动行追加；MINOR-7 计数漂移非阻塞）

## 六、结论

**verdict：pass**。上轮唯一阻塞项 MAJOR-1（P3 冷降权真实 DB 下 naive/aware 时间差致恒 ×1.0）已按建议修复（`_cold_ref_time` 源头规范化，对齐 `_evolve_recall` 既有模式），并新增 2 条 naive 输入单测锁定；全量 pytest 复跑 897 passed 全绿，修复为单点最小改动、无新引入问题，DDL 保持 TIMESTAMP 的取舍已如实声明（可接受）。6 项上轮 minor 全部保持非阻塞（无一项需阻塞合入），新增 1 项观察（记忆文件计数漂移，非阻塞）。**建议进入 Tester 验收。**
