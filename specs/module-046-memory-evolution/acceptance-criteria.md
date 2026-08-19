# 验收标准 — Module-046: 记忆进化机制

> 依据 ADR-0007。图例：📋 功能 / 📦 降级 / 🔌 接口 / 🧪 测试 / 📝 文档

## 1. 功能验收（WP1 进化核心）

- [ ] 📋 Document 模型含 last_mentioned_at（nullable）+ mention_count（默认 0）
- [ ] 📋 save_short 去重命中（status="updated"）→ mention_count+1 + last_mentioned_at 刷新
- [ ] 📋 recall_short：平滑衰减（decay = 0.5^(age/half_life)，半衰期 3 天可配）替代一刀切 TTL
- [ ] 📋 召回加权：最终分 = 语义分 × decay × (1 + α×mention_count)（α=0.2 可配）
- [ ] 📋 硬上限：超过 memory_short_max_days（默认 30 天）不参与召回
- [ ] 📋 升级：mention_count ≥2 且最近提及 7 天内 → 复制到长期 + 删除短期副本（幂等）
- [ ] 📋 用户"记住"（query 含"记住"）→ 直接沉淀长期层

## 2. 功能验收（WP2 会话摘要）

- [ ] 📋 会话超限滚动删除前：旧消息段 LLM 压缩成摘要（递归公式：新摘要=摘要(旧摘要+新对话)）
- [ ] 📋 摘要存 documents 表（source='memory:<id>:session_summary:'，仅顺序读最新一条）
- [ ] 📋 分层注入：history = 早期摘要段 + 最近 20 条原样
- [ ] 📋 会话 ≤20 条时行为与旧版一致（零回归）

## 3. 功能验收（WP3 提取评测闭环）

- [ ] 📋 eval/golden_memory.py：标注集 ≥20 条（含"不应提取"防过度提取样本）
- [ ] 📋 输出 extract_facts 的 Precision/Recall/F1 + eval_runs eval_type='memory_extraction' 落库
- [ ] 📋 --fixture 模式不依赖 LLM

## 4. 降级验收

- [ ] 📦 存量短期记忆无新字段 → NULL/0 兼容（按 created_at 衰减），零迁移
- [ ] 📦 摘要 LLM 失败 → 跳过摘要段，不阻塞对话
- [ ] 📦 升级/衰减异常 → 不抛异常，logger 记录
- [ ] 📦 全量 pytest 428+ 全绿（0 失败）

## 5. 接口兼容

- [ ] 🔌 save/recall/recall_short 签名不变（返回结构兼容）
- [ ] 🔌 长期层行为完全不变（进化只作用于短期层）
- [ ] 🔌 10 个 Agent 工具不受影响

## 6. 测试验收

- [ ] 🧪 test_memory.py 追加：提及刷新/衰减计算/硬上限/升级幂等/记住检测
- [ ] 🧪 test_session_memory.py 追加：摘要维护/分层注入/≤20 条零回归
- [ ] 🧪 test_golden_memory.py：标注集结构/P-R 计算/eval_runs 契约/fixture
- [ ] 🧪 python -m pytest tests/ -q — 全量全绿

## 7. 文档验收

- [ ] 📝 changelog.md / review-report.md / test-report.md
- [ ] 📝 记忆文件更新（rag-architecture.md / rag-agent-roadmap.md / MEMORY.md）
- [ ] 📝 ADR-0007 状态更新（已实施 + 实现记录）
