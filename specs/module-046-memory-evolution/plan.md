# 功能规格说明书 — Module-046: 记忆进化机制（ADR-0007 实施）

> Planner | 2026-08-10

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-046 |
| 模块名称 | 记忆进化：强化/衰减/升级 + 会话摘要 + 提取评测闭环 |
| 版本号 | 0.46.0-module-046 |
| 优先级 | P1（用户决议：现有记忆数据少，直接实施 ADR-0007） |
| 预估代码量 | 3 个工作包，≤ 500 行 + 评测数据 |

---

## 2. 需求（依据 ADR-0007 三问题）

### 2.1 现状缺口

| 缺口 | 现状（代码事实） | ADR 章节 |
|------|------|------|
| 短期一刀切 TTL | 7 天 TTL 惰性过滤（created_at 早于 cutoff 直接丢弃）——"悬崖式"过期，无平滑衰减、无提及强化 | 问题 2 ①② |
| 无短期→长期升级 | 只有层内语义去重（cosine>0.85 合并），短期不会沉淀为长期 | 问题 2 ③ |
| 会话失忆 | 注入最近 20 条（≈10 轮），早期对话全部截断 | 问题 3 |
| 记忆提取无评测 | 无 ground truth 标注集，LLM 提取准不准无法量化（对比检索有 golden 集） | 问题 1 |

### 2.2 目标（用户决议：直接实施，不设"暂不实施"）

1. **WP1 短期记忆进化**（人脑类比）：
   - 反复提及 → 强化（last_mentioned_at + mention_count 字段，召回/写入命中刷新）
   - 长期未提 → 指数衰减替代一刀切 TTL（半衰期 ~3 天平滑衰减；保留硬上限防堆积）
   - 短期 → 长期升级（7 天内提及 ≥2 次 → 升级；用户明确"记住" → 强制沉淀；升级后删短期副本）
2. **WP2 会话摘要**（MemGPT 递归摘要公式）：早期对话压缩成摘要 + 最近 20 条原样分层注入
3. **WP3 记忆提取评测闭环**：标注集 + extract_facts P/R 量化 + eval_runs 版本化

### 2.3 验收场景

```
场景 1：提及强化
  假设 用户第二次提到相似内容（去重命中）
  那么 该短期记忆 mention_count+1、last_mentioned_at 刷新，召回加权排前

场景 2：平滑衰减
  假设 短期记忆 7 天未被提及（created_at/last_mentioned_at = 7 天前）
  那么 不被直接丢弃，分数 × 衰减系数（0.5^(7/3) ≈ 0.2）后排后；
       超过硬上限（30 天）不参与召回

场景 3：短期→长期升级
  假设 某短期记忆 7 天内提及 ≥2 次
  那么 自动升级为长期（source 变 memory:<id>:），短期副本删除

场景 4：用户"记住"
  假设 对话中用户说"记住……"
  那么 该内容直接沉淀长期记忆

场景 5：会话摘要分层注入
  假设 会话超过 20 条（10 轮）
  那么 生成 prompt 注入 = 早期摘要（LLM 压缩）+ 最近 20 条原样

场景 6：提取评测闭环
  假设 跑 eval/golden_memory.py
  那么 输出 extract_facts 的 P/R + eval_runs eval_type='memory_extraction' 落库
```

---

## 3. 技术方案

### 3.1 工作包与涉及文件

| WP | 内容 | 文件 | 操作 |
|----|------|------|------|
| WP1 | 进化核心（强化/衰减/升级/记住） | `rag/models.py`（Document 加 last_mentioned_at/mention_count）`rag/memory.py`（save_short 提及刷新 + recall_short 衰减加权 + 升级逻辑 + 硬上限）`rag/engine.py`（"记住"检测 + 升级触发接线）`src/config.py`（half_life/硬上限/升级阈值可配） | 修改 |
| WP2 | 会话摘要 | `rag/session_memory.py`（摘要维护：超限滚动前先摘要，复用 documents 表存摘要行）+ `rag/engine.py`（分层注入接线）+ 摘要 LLM 调用 | 修改 |
| WP3 | 提取评测闭环 | `eval/golden_memory.py`（标注集 ~30 条：对话 → 应提取事实）+ `tests/test_golden_memory.py` | 新建 |
| 测试 | | `tests/test_memory.py` / `test_session_memory.py` 追加 | 修改 |

### 3.2 核心逻辑（关键实现约束）

#### WP1 进化核心

```
字段（documents 表，仅短期层使用，长期/会话不受影响）：
  last_mentioned_at  DateTime nullable      # 最近提及时间
  mention_count      Integer default 0      # 提及次数

写入侧（save_short → _save dedup 命中分支）：
  status="updated" 时 → mention_count+1 + last_mentioned_at=now（语义去重命中 = 再次提及）

召回侧（recall_short）：
  ① 硬上限过滤：last_mentioned_at/created_at 超过 memory_short_max_days（默认 30）→ 不参与召回
  ② 平滑衰减：age_days = today - (last_mentioned_at or created_at)
     decay = 0.5 ** (age_days / memory_short_half_life)   # 半衰期默认 3 天
     最终分 = 语义分 × decay × (1 + α×mention_count)      # α 默认 0.2，settings 可配
  ③ 升级检测：mention_count ≥ 2 且最近提及在 7 天内 → 升级长期
     （复制父块+子块到 memory:<identity>: source，删除短期副本；幂等——已升级的跳过）

"记住"（engine.chat 对话写入路径）：
  query/content 含"记住"（正则：记住[这个|一下]?）→ 直接 save 到长期层（跳过短期）

兼容性：无 last_mentioned_at/mention_count 的存量短期记忆（列 NULL/0）→
  按 created_at 计算衰减、count=0 加权——零迁移、fail-open
```

#### WP2 会话摘要（MemGPT 递归摘要公式）

```
摘要维护（session_memory 写入时）：
  会话条数 > memory_session_max_messages（50）触发滚动删除前：
    旧消息段 → LLM 压缩 → 摘要行（documents 表 source='memory:<id>:session_summary:'，
    title=摘要, content=摘要文本, 无向量——仅顺序读最新一条）
  增量更新：新摘要 = 摘要(旧摘要 + 新对话段)（递归摘要公式，MemGPT 同款）

分层注入（engine 组装 history 时）：
  history 注入 = [早期摘要段] + 最近 20 条原样
  摘要为空（早期无对话）→ 与旧行为逐字节一致（零回归）
  摘要 LLM 失败 → 跳过摘要段（fail-open，不阻塞对话）
```

#### WP3 提取评测闭环

```
eval/golden_memory.py：
  标注集 ~30 条：{dialogue: 对话片段, facts: [应提取的事实] }（含"不应提取"样本防过度提取）
  指标：extract_facts 输出 vs 标注 → Precision / Recall / F1
  eval_runs eval_type='memory_extraction' 版本化（对齐 golden_retrieval 模式）
  --fixture 模式（启发式关键词匹配）不依赖 LLM
```

### 3.3 降级

| 场景 | 处理 |
|------|------|
| 存量记忆无新字段 | NULL/0 fail-open 兼容（按 created_at 衰减） |
| 摘要 LLM 失败 | 跳过摘要段，不阻塞对话 |
| 升级/衰减计算异常 | 走原逻辑（不抛异常，logger 记录） |
| "记住"检测误命中 | 只影响保存层（长期 vs 短期），无副作用 |

---

## 4. 依赖

- module-034（三层 source 分层）、module-035（绝对余弦口径）、module-033（语义去重）
- ADR-0007（进化机制方案 + 业界对标公式）
- 提取评测（WP3）依赖 memory_extractor.extract_facts 现有实现

## 5. 已知边界

- **零迁移**：存量短期记忆无新字段直接兼容，不写迁移脚本
- **测试保持全绿**：全量 428+ 不得引入新失败
- 摘要行为在会话 ≤20 条时不生效（与旧版一致，零回归）
