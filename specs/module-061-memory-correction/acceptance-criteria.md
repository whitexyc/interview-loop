# 验收标准 — Module-061: 记忆纠错（升级留后悔药 + 冲突消解）

> 图例：📋 功能 / 📦 降级 / 🔌 接口 / 🧪 测试 / 📝 文档
> 用户决策（已确认）：范围 = P0（升级留后悔药）+ P1（mDeBERTa NLI 冲突消解 SUPERSEDED）+ 评测闭环

## 1. 功能验收（WP1 评测闭环）

- [ ] 📋 `eval/memory_conflict_dataset.py`：记忆矛盾标注集（20-30 条，含改口/迁移/过时/升级冲突/正例中性五类）
- [ ] 📋 NLI baseline 数字如实记录（复用 retest_nli 逻辑，P/R/F1 三口径）
- [ ] 📋 达标线明确声明（建议 contradiction Recall≥0.8 且 Precision≥0.8）；**不达标如实标注"未达门槛"，开关保持默认关（不预设成功）**

## 2. 功能验收（WP2 P0 升级留后悔药）

- [ ] 📋 `_promote_memory`：升级到长期后**不删除短期副本**（后悔药）；长期新条目 `superseded=false` + `updated_at=now`
- [ ] 📋 `Document` 加 `superseded`/`updated_at` 字段；documents 表加列走 init_db 幂等 ALTER（本地库 ALTER 先决，module-046 经验）
- [ ] 📋 重复升级幂等（content_hash 检查保留，不产生垃圾行）
- [ ] 📋 召回/检索侧过滤 `superseded=true`（`_evolve_recall` + 检索查询 + 注入路径统一口径）
- [ ] 📋 升级失败降级不丢数据（现有"先复制后删除"语义保留——本次改为不删除，更安全）

## 3. 功能验收（WP3 P1 冲突消解）

- [ ] 📋 `rag/memory/nli_judge.py` 生产封装：延迟加载 + `threading.Lock` + `asyncio.to_thread` + 超时/异常/缺失 → None（对齐 hhem_judge 模式）；加载复用 eval/retest_nli.py 路径
- [ ] 📋 `_merge_duplicate` 分流：NLI 判 **contradiction** → 旧父块 `superseded=true` + `updated_at=now` + 新内容按正常新增入库（**不拼接共存**）
- [ ] 📋 NLI 判 **entailment/neutral** → 保持现行为（追加拼接 content）
- [ ] 📋 NLI 不可用（None）/超时 → 保持现行为（追加，零回归）
- [ ] 📋 开关 `PW_MEMORY_CONFLICT` 默认 false（启用由评测达标驱动）；false 时 `_merge_duplicate` 完全旧行为

## 4. 验收（WP4 收口）

- [ ] 📋 `tests/test_memory_correction.py`（新）：P0（升级留副本/superseded 标记/幂等/召回过滤）+ P1（NLI 封装三分类/矛盾分流/一致追加/降级/开关 false）+ 评测基线一致性
- [ ] 📋 conftest autouse fixture 钉住 `memory_conflict_enabled=False`（对齐 module-056/058/060 开关模式）；新测试显式开 true
- [ ] 📋 ADR-0007 状态行更新（P0+P1 已实施，注明并入 module-061）
- [ ] 📋 面试口径更新点落盘（记忆纠错：升级留后悔药 + 写路径矛盾消解 SUPERSEDED，复用 mDeBERTa 零新依赖，评测驱动启用）

## 5. 降级验收

- [ ] 📦 NLI 不可用/加载失败/超时 → predict 返回 None → `_merge_duplicate` 走旧行为（追加拼接，零回归）
- [ ] 📦 SUPERSEDED 标记写库失败 → 日志告警 + 按旧行为追加（fail-open 不阻断写入）
- [ ] 📦 **SUPERSEDED 不删除**用户记忆（标记后保留可审计可回溯，Zep 模式）
- [ ] 📦 `PW_MEMORY_CONFLICT=false` → 记忆写入行为与 module-046 完全一致（逃生口留证）
- [ ] 📦 全量 pytest 797+N 全绿保持

## 6. 接口兼容

- [ ] 🔌 三层记忆存储结构不变（documents 表 + source 前缀隔离）
- [ ] 🔌 无新 HTTP 端点；`_merge_duplicate` 返回结构不变（{"id","title","status"}）
- [ ] 🔌 documents 表加列为**增量**（superseded/updated_at 默认值兜底存量行）；init_db 幂等（重复启动不报错）
- [ ] 🔌 检索/召回对外行为：superseded 过滤仅在标记存在时生效（存量行 superseded=false 不受影响）

## 7. 测试验收

- [ ] 🧪 `tests/test_memory_correction.py`（新）：升级留副本 / superseded 标记与幂等 / 召回过滤 / NLI 三分类判定（mock）/ 矛盾分流（SUPERSEDED+新增）/ 一致追加 / NLI None 降级 / 开关 false 零回归 / 评测基线一致性
- [ ] 🧪 mock NLI（不依赖真实 557MB 模型跑全量）；并发/事务一致性（标记+新增同一事务）
- [ ] 🧪 存量记忆测试（module-033/034/035/046 相关）零改动全绿
- [ ] 🧪 `python -m pytest tests/ -q` — 全量 797+N 全绿（**不改存量测试掩盖**）

## 8. 文档验收（含记忆硬性约束）

- [ ] 📝 changelog.md / review-report.md / test-report.md（含评测 baseline 数字 + 达标判定 + 降级声明 + 口径变化）
- [ ] 📝 **memory/project-context.md 模块清单追加 module-061 行** + 头部"最后更新"日期改为当天
- [ ] 📝 **memory/agent-activity-log.md**：Developer/Reviewer/Tester 各追加自己的活动行
- [ ] 📝 **memory/file-index.md**：本模块新文件行（只追加）
- [ ] 📝 ADR-0007 状态行更新（P0+P1 已实施）
- [ ] 📝 **CONTEXT.md 只增不删**（记忆纠错术语追加；同步/合并永远取更全一侧）
- [ ] 📝 开工前必读 project-context.md（Developer 在 changelog 注明已读）
