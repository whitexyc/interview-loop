# Module-046 审查报告（Reviewer）

> 审查对象：Dev-A（WP1 短期记忆进化）+ Dev-B（WP2 会话摘要 + WP3 提取评测闭环）
> 审查日期：2026-08-10 | 结论：**changes_requested**（2 个行为缺陷，均需修复后复核）

---

## 1. 审查方法

- 逐文件阅读实际改动 diff（非仅信 Dev 自述）：`git diff` 全量核对 engine.py / memory.py / models.py / config.py / session_memory.py / test_memory.py / test_session_memory.py，通读新建 `eval/golden_memory.py` + `tests/test_golden_memory.py`
- 对照规格逐条验收：`plan.md`（3.1/3.2/3.3）+ `acceptance-criteria.md`（§1-§7）+ `adr/0007-memory-evolution.md`
- **全量测试亲跑**：`python -m pytest tests/ -q` → **500 passed / 0 failed**（123.75s；基线 448 + 新增 52）
- **行为实证探针**：写一次性 mock 脚本（已删除，未入库）验证 `_evolve_recall` 两个疑点，均复现

---

## 2. 验收标准对照

### §1 WP1 进化核心（Dev-A）

| 验收项 | 结论 | 证据 |
|---|---|---|
| Document 两列（nullable + default 0） | ✅ | models.py L44-49，注释标明仅短期层 |
| save_short 去重命中刷新提及 | ✅ | `_merge_duplicate` layer="short" → count+1 + last_mentioned_at=now；测试 3 例 |
| 平滑衰减替代一刀切 TTL | ⚠️ | 公式正确（0.5^(age/3)），但加权后**未重排**（见缺陷 1），"衰减后排后"不成立 |
| 召回加权最终分 | ⚠️ | 分数计算正确，但分数不驱动排序/截取（见缺陷 1） |
| 硬上限 30 天不参与召回 | ⚠️ | 过滤正确，但过滤项仍被提及刷新"复活"（见缺陷 2） |
| 升级（count≥2 且 7 天内，幂等） | ✅ | `_promote_memory` 复制+删短期副本，content_hash 幂等；4 例测试全过 |
| 用户"记住"直达长期 | ✅ | `_REMEMBER_RE` 正则 + `_persist_memory` 分支，测试 4 例全过 |

### §2 WP2 会话摘要（Dev-B）

| 验收项 | 结论 | 证据 |
|---|---|---|
| 超限滚动删除前 LLM 压缩成摘要 | ✅ | `_trim` → `_summarize_oldest_segment`，增量 MemGPT 递归公式（prompt 含旧摘要+新段） |
| 摘要存 documents（session_summary source，仅顺序读最新） | ✅ | `_session_summary_source` + 写前删旧行（至多一条）+ `get_session_summary` id DESC LIMIT 1 |
| 分层注入 = 摘要段 + 最近 20 条原样 | ✅ | `_resolve_session_history`：摘要段前置（role='assistant' + '[早期会话摘要]' 前缀）+ persisted（limit=20） |
| ≤20 条零回归 | ✅ | 无摘要 → 返回 persisted 原样；`test_no_summary_byte_identical` 逐字节断言 |

### §3 WP3 提取评测闭环（Dev-B）

| 验收项 | 结论 | 证据 |
|---|---|---|
| 标注集 ≥20 条含"不应提取" | ✅ | 28 条（22 应提取 + 6 不应提取），`load_memory_golden` 结构校验 + 非法结构 ValueError |
| P/R/F1 + eval_runs 落库 | ✅ | micro 口径 tp/fp/fn 汇总；`eval_type='memory_extraction'` 复用 golden_retrieval save_eval_run 契约（签名核对一致）；已知值测试 3/4→0.75 |
| --fixture 不依赖 LLM | ✅ | 关键词启发式切句，确定性测试覆盖；冒烟 28/28 评估 0 跳过 |

### §4 降级 / §5 接口 / §6 测试 / §7 文档

- ✅ 存量 NULL/0 fail-open（`(count or 0)` / `func.coalesce` / created_at 衰减，测试覆盖）
- ✅ 摘要 LLM 失败/超时/空输出 → 跳过摘要，滚动删除照常（3 例测试）
- ✅ 进化/升级异常 → logger 降级走原逻辑（`test_evolve_failure_falls_back_to_original`）
- ✅ save/recall/recall_short 签名与返回结构不变（content/score/title/created_at）
- ✅ 长期层行为不变：`_merge_duplicate` layer="" 分支零触碰；recall 长期路径零改动；升级仅复制新增+删短期
- ✅ 10 个 Agent 工具未触碰（本模块文件清单外零改动）
- ✅ test_memory +13 / test_session_memory +12 / test_golden_memory 新建 22
- ⚠️ 文档：changelog.md ✅、ADR-0007 状态+实现记录 ✅（决策正文未重写）、三个记忆文件 ✅；**test-report.md 缺失**（验收 §7 要求，Dev 未产出，需补充）

---

## 3. 红线核查

| 红线 | 结论 | 说明 |
|---|---|---|
| ① 只动自己文件 | ✅ | 改动文件均在工作包清单内；`specs/module-033-long-term-memory/changelog.md` 有未提交改动，但为 2026-08-08 上一审查周期 Reviewer 遗留（非本模块 Dev 所为），备注不追责 |
| ② 零迁移 | ✅ | 无迁移脚本；存量 NULL/0 按 created_at 衰减、count=0 加权（代码 + 测试双重 fail-open） |
| ③ 长期层完全不变 | ✅ | 见 §2 验收证据；升级为长期层**新增**写入，不改既有行为 |
| ④ 全量 pytest 448 全绿保持 | ✅ | 亲跑 500 passed / 0 failed，零新失败 |
| ⑤ 不跑 git commit | ✅ | git log 无本模块提交；所有改动仅工作区 |
| 两 Dev engine.py 改动无冲突 | ✅ | Dev-A 在 `_recall_memory`（注释）/`_persist_memory`（"记住"分支），Dev-B 在 `_resolve_session_history`；实际合并共存，全量绿 |

---

## 4. 缺陷发现（实证）

### 缺陷 1 [major] 衰减/加权后结果未按新分数重排 —— 场景 1"加权排前"/场景 2"衰减后排后"不成立

`rag/memory.py` `_evolve_recall`（L628-674）：遍历 `memories`（`_expand_to_parents` 输出的**原始语义分降序**）逐条改写 `m["score"]` 后**按原顺序** append 到 result，无重排；`recall_short` 随后按原顺序 `memories[:dynamic_k]` 截取。

**实证探针**（mock 会话，动态 K 降级路径）：候选 A 语义分 0.9、20 天前（decay≈0.5^(20/3)≈0.0098 → 加权后 0.0089），候选 B 语义分 0.7、今天（加权后 0.7）。平均分 0.733 < 0.75 → dynamic_k=1 → **返回 A（0.0089），新鲜 B（0.7）被丢弃**，返回顺序也不符合 recall_short docstring 自述的"按 score 降序"。

后果：dynamic_k=1 是最常见档位（平均绝对余弦 <0.75），此时最该被召回的"新鲜/高提及"记忆反而可能被衰减到近零的旧记忆挤出，WP1 核心价值（进化影响召回排序）在主要路径上失效。plan 场景 2 明确"分数 × 衰减系数后排后"、场景 1 明确"召回加权排前"。

**修复建议**：`_evolve_recall` 返回前按新 score 降序重排（或 recall_short 在进化后 `sorted(..., key=score, reverse=True)` 再截取）。

### 缺陷 2 [minor] 硬上限过滤掉的记忆仍被提及刷新 —— "超硬上限不参与召回"被击穿

`rag/memory.py` `_evolve_recall` L668-670：`if refs: asyncio.create_task(self._refresh_mentions(list(refs.keys())))`——`refs` 是**全部**加载的参考文档（含循环内 `continue` 过滤掉的超硬上限项）。

**实证探针**：3 条候选（含 40 天前超硬上限的 C），UPDATE 语句 `WHERE documents.id IN (1, 2, 3)` 含 C——C 被置 last_mentioned_at=now + count+1，下次召回 age≈0 重新进池，"30 天硬上限"退化为"检索命中一次即复活"。

**修复建议**：循环内收集**通过硬上限过滤**的 doc id 列表，仅刷新这些项。

### 文档 [minor] test-report.md 缺失

验收 §7 要求 changelog/review-report/test-report 三件套；changelog 与 review-report 已产出，test-report.md 未创建（Dev 自述亦未提及）。

---

## 5. 其他观察（非缺陷，如实记录）

- 召回侧提及刷新（fire-and-forget `asyncio.create_task`）超出 plan 3.2 召回侧 ①②③ 的写法（plan 仅写入侧刷新），但符合 ADR 问题 2 ①"每次提及刷新"，且不影响契约——维持现状即可（与缺陷 2 合并修复）
- 摘要生成同步阻塞写路径最多 10s（`_SUMMARY_TIMEOUT_SECONDS`）；但 `_schedule_session_persist` 本身 fire-and-forget，不阻塞对话响应，可接受
- "记住"正则对"记住吗？"类疑问句会误存"吗？"为长期记忆——plan 3.3 已声明"误命中只影响保存层，无副作用"，属既定边界
- 本地开发库 documents 表无两新列（`select(Document)` UndefinedColumnError），测试全 mock 不受影响；部署前需 ALTER TABLE（ADR 实现记录已注明，与零迁移不冲突）
- 摘要段在 reflector 纯反射路径可能被 `lines[-6:]` 截断（module-005 遗留，reflector 不在本模块文件清单，未越线改动；ReAct 路径透传完整 history）

---

## 6. 结论

**verdict: changes_requested**

红线全部通过、测试全绿（500/0）、文档交接完整。但 WP1 核心行为存在 2 个实证缺陷：缺陷 1（加权后不重排，major）直接违背 plan 场景 1/2 的排序语义并在最常见 dynamic_k=1 路径产生错误召回选择；缺陷 2（硬上限项被刷新复活，minor）击穿硬上限语义。修复点均小（重排 + 过滤刷新集合），修复后需补对应单测（多候选排序用例 + 硬上限项不刷新用例）并全量回归复核。
