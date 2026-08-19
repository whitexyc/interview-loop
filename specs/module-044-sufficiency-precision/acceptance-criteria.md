# 验收标准 — Module-044: Rerank 截断验证 + 反思充分性精确化

> 依据 ADR-0004 TODO + ADR-0005 层 0-3。图例：📋 功能 / 📦 降级 / 🔌 接口 / 🧪 测试 / 📝 文档

## 1. 功能验收（WP3+5 层 1+3：分数/数量硬闸门 + 多信号融合）

- [ ] 📋 docs 为空 → 不充分（现有行为保留）
- [ ] 📋 文档数 < 2 → 直接判不充分，零 LLM 调用
- [ ] 📋 top-1 abs_cosine < 0.4 → 直接判不充分 + rewritten_query，零 LLM 调用
- [ ] 📋 分数达标（≥0.4）→ 才进 LLM 判断（模糊地带）
- [ ] 📋 LLM 判不充分 → 尊重语义走 rewritten_query（不因分数高而强制充分）
- [ ] 📋 返回结构不变（sufficient/reason/rewritten_query）

## 2. 功能验收（WP4 层 2：prompt 强化）

- [ ] 📋 _CHECK_PROMPT 含 few-shot 正反例（充分/不充分各 ≥1）
- [ ] 📋 _CHECK_PROMPT 含 CoT 信息点比对步骤（先列所需信息点，再逐点比对）
- [ ] 📋 自洽性检查为配置开关（默认 False），开启时两温度各判一次、不一致 → 保守充分
- [ ] 📋 prompt 变更向后兼容（输出 JSON 结构不变）

## 3. 功能验收（WP2 层 0：评测闭环）

- [ ] 📋 eval/golden_sufficiency.py 跑通：Accuracy + per-class P/R/F1 + 混淆矩阵输出
- [ ] 📋 eval_runs 落库（eval_type='sufficiency'，git_commit+配置快照，对齐 golden_retrieval.py）
- [ ] 📋 标注集含充分/不充分两类样本（fixture 模式可用，不硬依赖 DB/LLM）
- [ ] 📋 报告重点标出 Recall（漏判"不充分"最致命）

## 4. 功能验收（WP1 ADR-0004 验证）

- [ ] 📋 eval/benchmark_rerank.py 可配截断参数（--max-chars）+ 2 pair/6 pair 计时 + 分数输出
- [ ] 📋 实测 250 vs 500（模型在 worktree 本地）→ 数据记录
- [ ] 📋 四档选数表（250/500/1000/2000）补齐 → 数据驱动决策（采纳 250 或保持 500，如实记录）

## 5. 降级验收

- [ ] 📦 abs_cosine 字段缺失/异常 → 不误杀，继续走 LLM
- [ ] 📦 闸门/LLM 异常 → 默认充分（防死循环，现有哲学）
- [ ] 📦 自洽性开启时 LLM 异常 → 保守充分
- [ ] 📦 现有 check_sufficiency 正常路径（文档非空且分数达标）行为与旧版一致 — 零回归

## 6. 接口兼容

- [ ] 🔌 check_sufficiency 返回结构不变（sufficient/reason/rewritten_query）
- [ ] 🔌 generate_answer / generate_answer_stream / verify_answer 不受影响
- [ ] 🔌 engine.py 调用点无需改动（除非确认 abs_cosine 缺失时补充透传，最小改动）

## 7. 测试验收

- [ ] 🧪 test_reflector.py 追加：硬闸门 3 例（<0.4 不调 LLM / <2 篇不调 LLM / 达标走 LLM）+ 零 LLM 调用断言（mock）+ prompt 结构断言（few-shot/CoT 存在）+ 自洽开关 2 例 + 降级 2 例
- [ ] 🧪 test_golden_sufficiency.py：混淆矩阵/指标计算 + eval_runs 记录 + fixture 模式
- [ ] 🧪 python -m pytest tests/ -q — 全量 + 新增 / 仅 3 个预存环境失败（test_identity top_k + test_rerank_langgraph 429）

## 8. 文档验收

- [ ] 📝 changelog.md / review-report.md / test-report.md（含 WP1 实测数据与决策）
- [ ] 📝 ADR-0004 TODO 状态更新（验证结果 + 四档选数表）；ADR-0005 状态更新（层 0-3 已实现，层 4 留待数据）
- [ ] 📝 记忆文件更新（rag-architecture.md / rag-agent-roadmap.md / MEMORY.md）
- [ ] 📝 层 4 明确说明"本模块不做"及理由
