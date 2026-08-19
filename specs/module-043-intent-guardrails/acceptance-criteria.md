# 验收标准 — Module-043: 输入防护 + Intent 校验体系

> 依据 ADR-0001 Q3 + ADR-0003（含 L2 修订版）。图例：📋 功能 / 📦 降级 / 🔌 接口 / 🧪 测试 / 📝 文档

## 1. 功能验收（WP1 三端点加固）

- [ ] 📋 SearchRequest.query 有 max_length=2000 — 超长返回 422
- [ ] 📋 MemorySaveRequest.content 有 max_length=2000 — 超长返回 422（落库防污染）
- [ ] 📋 MemoryRecallRequest.query 有 max_length=2000 — 超长返回 422
- [ ] 📋 与 ChatRequest 模式一致（Field 声明式约束，不进业务逻辑）

## 2. 功能验收（WP3 L2 前置校验 — 修订版）

- [ ] 📋 intent≠knowledge 且 confidence<0.5 才触发确认（低置信触发）
- [ ] 📋 确认动作是确定性信号（FTS 术语命中 / 图谱实体命中 / 规则表），**不含任何 LLM 调用**
- [ ] 📋 信号命中 → intent 修正为 knowledge
- [ ] 📋 信号未命中 → 保持原判（casual_chat 放行）
- [ ] 📋 确认结果写入日志/返回结构（可观测）

## 3. 功能验收（WP4 L3 后置校验）

- [ ] 📋 走 knowledge 后 top-1 abs_cosine < 0.3 → suspected_misclassify 标记
- [ ] 📋 标记写入 ChatSteps（前端管线面板可见）
- [ ] 📋 不阻塞、不改变回答路径（先度量后干预）

## 4. 功能验收（WP2 L1 度量 + WP5 L4 分类器）

- [ ] 📋 golden_intent.py 跑通：per-class 精确率/召回率/混淆矩阵输出
- [ ] 📋 eval_runs 落库（git_commit + 配置快照，对齐 golden_retrieval.py）
- [ ] 📋 intent 评测集含闲聊/实时/边界易混样本（如"你们网站有什么功能"）
- [ ] 📋 intent_classifier 可 fit / predict_proba（校准概率）
- [ ] 📋 router 可注入分类器（配置开关），默认仍用 LLM
- [ ] 📋 训练脚本可用（golden 集训练，模型落盘）

## 5. 降级验收

- [ ] 📦 L2 信号查询失败 → 保守 knowledge（宁多检不漏检）
- [ ] 📦 L4 模型缺失/加载失败 → 回退 LLM 分类，零影响
- [ ] 📦 L3 反证异常 → 记日志不阻塞
- [ ] 📦 三端点正常请求（短 query）行为不变 — 零回归

## 6. 接口兼容

- [ ] 🔌 ChatRequest / ChatResponse / ChatSteps 旧字段不变
- [ ] 🔌 router.classify() 返回结构不变（intent/confidence/reason）
- [ ] 🔌 现有 10 个 Agent 工具不受影响
- [ ] 🔌 无 LLM 二次确认调用（红线核查：grep router.py 确认确认路径无 LLM）

## 7. 测试验收

- [ ] 🧪 test_schemas_validation.py +3 用例（三端点 422）
- [ ] 🧪 test_intent_validation.py：L2 触发/命中/未命中/降级 + L3 反证 + L4 分类器（mock 特征）
- [ ] 🧪 test_golden_intent.py：混淆矩阵计算 + eval_runs 记录
- [ ] 🧪 python -m pytest tests/ -q — 全量 + 新增 / 仅 3 个预存失败（test_identity.py，环境问题不计入）

## 8. 文档验收

- [ ] 📝 changelog.md / review-report.md / test-report.md（含与 ADR-0003 修订版一致性说明）
- [ ] 📝 记忆文件更新（rag-architecture.md / rag-agent-roadmap.md / MEMORY.md）
- [ ] 📝 L4 数据约束与飞轮接口说明
