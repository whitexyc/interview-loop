# 功能规格说明书 — Module-057: mDeBERTa 矛盾判别改进（句级拆解 + 置信度校准 + 标注扩充）

> Planner | 2026-08-12

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-057 |
| 模块名称 | mDeBERTa 矛盾判别短板改进：复测未达门槛后的第二轮迭代 |
| 版本号 | 0.57.0-module-057 |
| 优先级 | P0（module-054 复测 kappa 0.5167 < 0.7 未达放行门槛；矛盾判别是 P1-③ 矛盾扫描的核心能力，短板不补无法放行） |
| 预估代码量 | 拆解/校准逻辑 + 标注扩充 + 复测适配 + 测试，≤ 400 行 |

---

## 2. 需求

| WP | 内容 | 来源 |
|----|------|------|
| WP-1 句级拆解 | claim 级矛盾判别升级为**句级拆解**：claim 先按句拆成子句 → 每个子句与文档分别判 → 任一子句 contradiction → 该 claim 判 contradiction（internal 矛盾同理：子句间互相判）。module-054 失败模式 11/32 internal 判 neutral 的根因是"多句混合 claim 让 NLI 判中性"——拆句后逐句判应能抓到矛盾 | module-054 复测失败模式 |
| WP-2 置信度校准 | softmax 置信度阈值校准（对齐 module-047 threshold_scan 思路）：扫描 contradiction 判定阈值（如 0.5-0.9）→ 选 kappa 最优；低置信候选（max prob < 阈值）→ 判 neutral 不硬判 | module-054 changelog 校准方向 |
| WP-3 标注扩充 | 矛盾样本从 31 条扩充（用户指示"多一些"）：internal_contradiction 重点扩充（当前最弱类）——多句混合 claim 的 internal 矛盾样本 + claim_vs_doc 反转样本 + 正例对照；目标 ≥50 条矛盾 | module-054 复测计划 |
| WP-4 复测 | 用扩充后样本集 + 句级拆解 + 校准阈值重跑 `retest_nli.py` → kappa 三分类对比（0.5167 → 新值）→ 达标（≥0.7）→ 放行矛盾扫描实施；未达标 → 如实标注 + 下一轮方向 | module-054 放行条件 |
| WP-5 测试 + 回归 | tests/test_nli_improve.py（拆解逻辑/校准扫描/标注结构）；全量 pytest 700+ 全绿 | AC |

### 验收场景

```
场景 1：句级拆解
  假设 claim = "G1 是 JDK9 默认收集器，采用 Region 分区，并且完全不需要调优"（3 句，第 3 句是编的）
  那么 拆成 3 个子句逐句判 → 第 3 句 contradiction → 整个 claim 判 contradiction（旧逻辑整句判可能 neutral）

场景 2：阈值校准
  假设 扫描 contradiction 阈值 0.5-0.9
  那么 输出 kappa vs 阈值曲线，选最优阈值写入配置

场景 3：标注扩充
  假设 跑扩充脚本
  那么 矛盾样本 ≥50 条（internal 重点扩充 ≥20 条多句混合样本），与旧样本集合并，JSON 结构不变

场景 4：复测
  假设 扩充样本 + 句级拆解 + 校准阈值重跑
  那么 输出新 kappa 三分类（对比 0.5167）；≥0.7 → 放行矛盾扫描；未达 → 如实标注 + 下一轮方向
```

---

## 3. 技术方案

### 3.1 涉及文件

| WP | 文件 | 操作 |
|----|------|------|
| WP-1 | `ai_service/eval/retest_nli.py`（句级拆解逻辑：claim 切子句 → 逐子句判 → 聚合）+ 或独立 `rag/retrieval/factcheck_judge.py` 复用 | 修改 |
| WP-2 | `ai_service/eval/retest_nli.py`（阈值扫描，复用 threshold_scan 思路）或独立脚本 | 修改 |
| WP-3 | `ai_service/eval/contradiction_dataset.json`（扩充至 ≥50 条矛盾 + 正例对照）+ `build_contradiction_dataset.py`（扩充脚本 + 标注指南更新） | 修改 |
| WP-4 | `ai_service/eval/retest_nli.py`（复测模式，eval_runs 落库 eval_type='nli_retest_v2'）+ `specs/adr/0010`（结论更新） | 修改 |
| WP-5 | `ai_service/tests/test_nli_improve.py` | 新建 |
| 文档 | changelog / review-report / test-report + memory/ 三文件 | 修改 |

### 3.2 关键实现约束

- **WP-1 句级拆解**：中文句切复用 `_pre_chunk` 模式（按 `。！？；` 切）；**聚合规则**：任一子句 contradiction → claim 判 contradiction（最严）；无矛盾但任一子句 entailment → entailment；全 neutral → neutral；**内部矛盾**：子句两两互判（claim 内部子句 A vs 子句 B），任一矛盾 → internal contradiction；拆句失败（无标点）→ 回退整句判（零回归）
- **WP-2 阈值校准**：扫描 contradiction 判定阈值（0.5-0.9 步长 0.05）+ 低置信处理（max prob < 阈值 → neutral）；输出 kappa vs 阈值表；最优阈值配置化（如 `nli_contradiction_threshold`）；校准方法学可复现（步长入 changelog）
- **WP-3 标注扩充**：internal 重点（多句混合 claim 的"前真后假"样本——旧样本的弱项）；claim_vs_doc 反转补充；正例对照按比例；JSON 结构不变（question/claim/doc/doc_title/verdict/contradiction_type/note/part）；标注指南同步更新（含多句 claim 拆解口径）；Reviewer 抽查一致性
- **WP-4 复测**：同 80+ 新样本集跑三分类 kappa + 二值；对比 0.5167；eval_runs 落库（eval_type='nli_retest_v2'）；结论写回 ADR-0010（放行矛盾扫描实施 / 未达 + 下一轮方向）；**放行条件 = kappa 三分类 ≥0.7**（ADR 既定）
- **诚实边界**：人工构造样本方向性验证；拆解聚合规则是最严语义（可能引入误杀，kappa 数据说话）；阈值校准是经验扫描（真实分布待飞轮）
- **不改生产 verify_answer 行为**（本模块只做评估侧改进 + 数据扩充；矛盾扫描实施是放行后的后续模块）
- 全量 pytest 700+ 全绿；不改存量测试掩盖

### 3.3 降级

| 场景 | 处理 |
|------|------|
| 拆句失败 | 回退整句判（零回归） |
| 复测 kappa 仍 < 0.7 | 如实标注 + 记录下一轮方向（如换模型/更多标注/两阶段） |
| 阈值扫描无最优（曲线平坦） | 用 0.5 保守默认 + 如实记录 |
| 标注扩充超预期 | 目标 ≥50 条矛盾（internal ≥20）；标注指南先行 |

---

## 4. 依赖

- module-054（矛盾样本集 + 复测脚本 + 失败模式定位）、module-047（threshold_scan 方法学）、module-050/052（mDeBERTa 模型 + NLI 判定链路）
- 环境：mDeBERTa 模型本地就绪（models/mdeberta-nli/）

## 5. 已知边界

- 本模块是评估侧改进（句级拆解 + 校准 + 数据扩充），不实施矛盾扫描生产代码（放行后另行模块）
- 句级拆解聚合"任一矛盾即 contradiction"是最严语义——可能把"部分矛盾"误判为"整体矛盾"，kappa 数据说话，若误杀严重可调为"多数矛盾才判"
- 文档类（简历/弹药）不改（用户指示：等优化完成后进行）
- 全量 pytest 700 全绿保持（本模块新增 +N）
