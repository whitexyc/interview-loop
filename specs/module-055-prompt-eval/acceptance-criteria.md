# 验收标准 — Module-055: 提示词评估优化 + E2E 待办修复

> 图例：📋 功能 / 📦 降级 / 🔌 接口 / 🧪 测试 / 📝 文档

## 1. 功能验收（WP-1 变体测试）

- [ ] 📋 `eval/prompt_variants.py` 存在：N 个 prompt 变体 → 逐个跑 golden 评测 → 对比表（Accuracy/kappa/耗时）
- [ ] 📋 reflector prompt 常量可注入参数（`check_sufficiency(prompt=...)`），**默认值不变零回归**
- [ ] 📋 支持 `--variant` 选择 / `--no-save` / 可选落 eval_runs（eval_type='prompt_variant'）
- [ ] 📋 只度量不替换生产 prompt（变体不改变默认行为）

## 2. 功能验收（WP-2 intent 漏检）

- [ ] 📋 诊断记录（该 query 的 classify 输出/confidence/L2 触发情况/L4 状态）入 changelog
- [ ] 📋 "G1垃圾收集器的核心创新是什么？"类 query 走 knowledge（不再闲聊）
- [ ] 📋 修复有测试覆盖（专有术语 + 疑问句边界样本）

## 3. 功能验收（WP-3 HHEM 验证）

- [ ] 📋 诊断 verified_claims=0 根因（超时/降级链）入 changelog
- [ ] 📋 非流式 chat 正常回答时 verified_claims 非空（不再超时降级为空）
- [ ] 📋 方案取舍有数据支撑（实测耗时对比），changelog 记录

## 4. 功能验收（WP-4 RRF abs_cosine）

- [ ] 📋 诊断 rrf 融合路径 abs_cosine 丢失原因入 changelog
- [ ] 📋 rrf 模式 retrieval step top_abs_cosine 为真实值（非恒 0.0）
- [ ] 📋 suspected_misclassify 不再误触发（真实低分才触发）

## 5. 功能验收（WP-5 rrf 默认）

- [ ] 📋 `retrieval_fusion_mode` 默认 hybrid→rrf（保留 hybrid 回退开关）
- [ ] 📋 全量 pytest 全绿；存量测试若更新断言（rrf 降级语义升级）须注明理由
- [ ] 📋 真实 E2E 冒烟（chat + stream）rrf 默认模式正常（module-054 已验证，本次确认默认值生效）

## 6. 降级验收

- [ ] 📦 WP-2 根因复杂 → 一层兜底修复 + 深层待办记录（如实）
- [ ] 📦 WP-5 切默认后存量失败 → 核对是否行为升级所致；回归则回退排查
- [ ] 📦 全量 pytest 667 全绿保持

## 7. 接口兼容

- [ ] 🔌 ChatResponse / 前端零改动（verified_claims 恢复后前端正常渲染）
- [ ] 🔌 retrieval 返回结构不变（abs_cosine 透传为修复，不改变其他字段）
- [ ] 🔌 reflector prompt 注入参数向后兼容（默认值不变）

## 8. 测试验收

- [ ] 🧪 tests/test_prompt_variants.py：变体定义/对比表/参数注入零回归
- [ ] 🧪 WP-2/3/4 各修复回归测试（覆盖 E2E 场景 query）
- [ ] 🧪 python -m pytest tests/ -q — 全量 667+ 全绿

## 9. 文档验收（含记忆硬性约束）

- [ ] 📝 changelog.md / review-report.md / test-report.md（含诊断记录 + 实测数据）
- [ ] 📝 **memory/project-context.md 模块清单追加 module-055 行** + 头部"最后更新"日期
- [ ] 📝 **memory/agent-activity-log.md**：Developer/Reviewer/Tester 各追加自己的活动行
- [ ] 📝 **memory/file-index.md**：本模块新文件行（只追加）
- [ ] 📝 ADR-0011 状态更新（第一步变体测试已完成；第二步/第三步按数据决定）
- [ ] 📝 开工前必读 project-context.md（Developer 在 changelog 注明已读）
- [ ] 📝 文档类（简历/弹药）**不改**（用户指示：等优化完成后进行）
