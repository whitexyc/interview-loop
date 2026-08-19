# 验收标准 — Module-053: RRF 三通道融合验证

> 图例：📋 功能 / 📦 降级 / 🔌 接口 / 🧪 测试 / 📝 文档

## 1. 功能验收（WP-0 DB 修复）

- [ ] 📋 documents 表已补 `last_mentioned_at` / `mention_count` 两列（幂等：已存在不重复加）
- [ ] 📋 feedback 表已建（对齐 module-048 FEEDBACK_DDL）
- [ ] 📋 `graph_store.search_related` 不再报 `last_mentioned_at does not exist`

## 2. 功能验收（WP-A 基线复测）

- [ ] 📋 当前代码跑 golden 检索评估，基线数字落地 eval_runs（本次 commit 锚点）
- [ ] 📋 **口径已钉死并声明**：评估脚本 hybrid 是否含图谱通道已验证（历史 0.9714 口径说明写入 changelog——两通道/两通道+图谱追加差异，新旧对比前必须同口径）

## 3. 功能验收（WP-B RRF 三通道）

- [ ] 📋 RRF 融合实现：`score(d) = Σ 1/(60 + rank_i(d))`（k=60），三路排名（FTS/向量/图谱）
- [ ] 📋 `retrieval_fusion_mode` 开关存在：hybrid（默认）/ rrf；默认 hybrid 时行为与现状零回归（存量测试全绿证明）
- [ ] 📋 RRF 融合只在 round 0 生效（round 1/2 单路混合），注释写明语义
- [ ] 📋 跑 golden 与基线 `--compare`，delta 落 eval_runs

## 4. 功能验收（WP-C 加权对照，可选但推荐）

- [ ] 📋 三路 min-max 归一化 + 权重消融 ≥2 组，跑 golden 对比 RRF
- [ ] 📋 产出"本项目场景 RRF vs 加权"实测对比结论

## 5. 放行决策

- [ ] 📋 RRF 或加权 ≥ 基线（0.9714 同口径）→ 选增益最大方案（保留 hybrid 回退）；否则维持现状记录否决理由
- [ ] 📋 结论写入 changelog + `docs/简历/08-项目经历-逐词深挖.md` 2.4 节

## 6. 降级验收

- [ ] 📦 RRF 单路失败 → 该路不参与融合不崩；rrf 模式异常回退 hybrid
- [ ] 📦 DB 修复后图谱仍不可用 → 基线两通道口径跑 + 图谱 RRF 如实标"待环境"
- [ ] 📦 全量 pytest 614 全绿保持（默认 hybrid 零回归）

## 7. 接口兼容

- [ ] 🔌 abs_cosine 存档不被破坏（L3 反证依赖，归一化前存档保留）
- [ ] 🔌 reranker.py 不动（RRF 粗排 vs CE 细排两阶段共存）
- [ ] 🔌 ChatResponse / 检索返回结构不变（仅融合排序变化，rrf 模式）

## 8. 测试验收

- [ ] 🧪 tests/test_rrf_fusion.py：RRF 公式正确性（已知 rank → 已知 score）、三路融合排序、开关 hybrid 零回归（存量行为不变）、单路失败降级、abs_cosine 保留断言
- [ ] 🧪 python -m pytest tests/ -q — 全量 614+ 全绿（不改存量测试掩盖）

## 9. 文档验收（含记忆更新硬性约束）

- [ ] 📝 changelog.md / review-report.md / test-report.md（含全部实测数字 + 口径声明）
- [ ] 📝 **memory/project-context.md 模块清单追加 module-053 行** + 头部"最后更新"日期 + ADR 索引（如新增决策）
- [ ] 📝 **memory/agent-activity-log.md**：Developer/Reviewer/Tester 各追加自己的活动行
- [ ] 📝 **memory/file-index.md**：本模块新文件行（只追加）
- [ ] 📝 `docs/简历/08-项目经历-逐词深挖.md` 2.4 节更新（融合方案现状 + 实测结论）
- [ ] 📝 开工前必读 project-context.md（Developer 在 changelog 注明已读）
