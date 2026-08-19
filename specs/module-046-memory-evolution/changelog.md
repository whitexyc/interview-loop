# Module-046 changelog

> 记忆进化：强化/衰减/升级 + 会话摘要 + 提取评测闭环（ADR-0007 实施）
> Developer: dev-A（WP1）/ dev-B（WP2）/ dev-C（WP3）| 2026-08-10 | 全量 pytest 全绿

## WP1 短期记忆进化（Dev-A，本文件首段）

### 1. Document 模型新增两列（仅短期层使用）

- `rag/models.py` `Document` 新增 `last_mentioned_at`（`DateTime(timezone=True)` nullable，
  最近提及时间）+ `mention_count`（`Integer` nullable=False default=0，提及次数）。
  长期层/会话层完全不受影响（plan 3.2 字段定义，仅短期层消费）。
- 零迁移：存量短期记忆无新字段（NULL/0）→ 按 created_at 衰减、count=0 加权
  （fail-open），不写迁移脚本。

### 2. 写入侧提及强化（save_short 去重命中）

- `rag/memory.py` `_merge_duplicate` 增加 `layer` 参数（默认 ""，长期层行为不变）：
  `layer="short"` 时去重命中（status="updated"）→ `mention_count+1` +
  `last_mentioned_at=now(timezone.utc)`。语义去重命中 = 再次提及（场景 1）。
- 存量行 mention_count=None → `(None or 0) + 1`，fail-open。

### 3. 召回侧进化（recall_short，替代 7 天一刀切 TTL）

- `recall_short` 的 TTL 惰性过滤替换为 `_evolve_recall`（新方法）：
  1. **硬上限**：参考时间（`last_mentioned_at or created_at`）超
     `memory_short_max_days`（默认 30 天）→ 不参与召回
  2. **平滑衰减**：`decay = 0.5 ** (age_days / memory_short_half_life)`（半衰期默认
     3 天）；7 天未提分数 ×≈0.2 排后但不过期（场景 2，替代"悬崖式" TTL）
  3. **提及加权**：最终分 = 语义分 × decay × (1 + α×mention_count)（α=0.2 可配）
  4. **召回命中刷新提及**：fire-and-forget `_refresh_mentions`（UPDATE
     last_mentioned_at=now + mention_count=coalesce(count,0)+1，按参考文档 id）
  5. **短期→长期升级**：mention_count ≥ `memory_promote_mentions`（默认 2）且最近
     提及在 `memory_promote_window_days`（默认 7）内 → `_promote_memory` 复制
     父块+子块到长期 source（'memory:<identity>:'）+ 删除短期副本；**幂等**——长期层
     已存在同 content_hash 父块则跳过复制仅清理短期副本；旧格式单文档整体复制
     （保留向量）
- 降级（plan 3.3）：参考文档加载失败/异常 → 返回原 memories（走原逻辑不抛）；
  提及刷新/升级异常 → 仅 logger 记录。
- 行为变更说明：`test_recall_short_filters_expired_by_ttl`（8 天 TTL 过滤语义）按
  plan 场景 2 改写为 `test_recall_short_filters_beyond_hard_cap`（30 天硬上限语义）
  ——7-30 天的记忆不再被丢弃，衰减后排后（规格明确"平滑衰减替代一刀切 TTL"）。

### 4. 配置（src/config.py）

- 新增 `memory_short_half_life=3.0` / `memory_short_max_days=30` /
  `memory_mention_boost_alpha=0.2` / `memory_promote_mentions=2` /
  `memory_promote_window_days=7`（env 前缀 PW_，可配）。
- `memory_short_ttl_days` 保留（标注"module-046 起由衰减+硬上限替代"），兼容既有 .env。

### 5. engine.py："记住"检测 + 升级接线

- `_REMEMBER_RE = 记住(?:这个|一下)?\s*(.+?)\s*$`（plan 3.2 正则"记住[这个|一下]?"，
  用分组写法修正字符类笔误，语义一致：匹配"记住/记住这个/记住一下"前缀）。
- `_persist_memory`：query 命中"记住"且后续有内容 → 直接 `memory_service.save`
  （长期层，dedup=True）并 return（跳过 extract_facts 与 save_short）——场景 4；
  保存失败仅日志降级；纯"记住"无内容 → 落回正常提取路径。
- 升级触发接线：升级检测内嵌于 `recall_short`（plan 3.2 召回侧 ③），
  `_recall_memory` 调用 recall_short 即触发点（加注释标明）。

### 6. 测试（tests/test_memory.py，+13）

- `TestMergeDuplicateMentionRefresh` 3 例：短期去重命中刷新提及 / 存量 None count
  fail-open / 长期层去重不触碰提及字段
- `TestRecallShortEvolution` 4 例：7 天衰减 0.5^(7/3)≈0.198 / 提及加权 1+0.2×2=1.4 /
  存量 NULL/0 按 created_at 衰减 / 进化异常走原逻辑
- `TestRecallHitRefreshesMention` 1 例：召回命中产生 UPDATE（last_mentioned_at +
  coalesce(mention_count,0)+1，IN 按参考文档 id）
- `TestPromotion` 4 例：升级复制长期+删短期 / 幂等跳过重复复制 / 提及阈值未达不升级 /
  提及超窗口不升级
- `TestRememberDetection` 4 例：记住直达长期 / "记住这个/记住一下"变体 / 保存失败降级 /
  不含记住走原提取路径
- `TestConfig046` 1 例：5 项进化配置默认值
- 适配：`test_recall_short_abs_cosine_reaches_three` 补显式
  `last_mentioned_at=None, mention_count=0`（MagicMock 未赋值返回真值 mock，
  会被进化逻辑当作参考时间）；`test_recall_short_filters_expired_by_ttl` 改写为
  硬上限语义（见 3 节行为变更说明）。

### 接口约定（与 Dev-B WP2）

- 两人同改 `rag/engine.py`：Dev-A 在 `_recall_memory`（记忆召回段）与 `_persist_memory`
  （写入段）；Dev-B 在生成 prompt 组装处（history 分层注入）。
- `memory_service.recall_short` 返回结构不变（content/score/title/created_at），
  score 语义变为"衰减加权后分数"——WP2 若注入该字段仅作展示，不影响契约。
- 若两段改动重叠（如都改 `_recall_memory` 函数体），由后到者在 changelog 注明合并。

## 测试与回归（WP1 部分）

- test_memory.py 60 → 73（+13），本文件 73 例全过。
- 相关文件 test_identity.py / test_memory_extractor.py 全过（engine 改动零回归）。
- 全量 `python -m pytest tests/ -q`：476 passed / 2 failed——2 失败均为
  `tests/test_session_memory.py::TestSessionSummary`（Dev-B WP2 在写中的摘要用例，
  仅涉及 session_memory.py 自身逻辑，与 WP1 无交集），待 Dev-B 完成后统一复核。
- 历史 448 基线用例全部保持绿（0 新失败）。

---

# WP2 会话摘要（Dev-B，2026-08-10）

## WP2a `rag/session_memory.py` 摘要维护

- 新增摘要层：`_session_summary_source(identity)` → source=`memory:<id>:session_summary:`
  （尾冒号隔离，与 session 层前缀不同——memory 各层 `_layer_pattern` 精确匹配不互扰，
  摘要行不会被 session/短期/长期检索误命中）
- `_trim` 超限滚动删除前：`_summarize_oldest_segment` 把最旧 excess 条消息段 LLM
  压缩成摘要行（documents 表，title='session_summary'，无 embedding、无向量，
  仅顺序读最新一条）；摘要 LLM 失败/超时/返回空 → 日志降级跳过摘要（fail-open），
  滚动删除照常执行，不阻塞对话
- **增量更新（MemGPT 递归公式）**：新摘要 = 摘要(旧摘要 + 新对话段)——prompt 同时
  携带旧摘要（`_SUMMARY_PROMPT` 会议纪要式：保留关键事实/偏好/任务状态，丢弃寒暄）
  与新段；写入前删旧摘要行（每 identity 至多一条，保持"仅顺序读最新"）
- 未超限（≤ memory_session_max_messages）→ 不触发摘要 LLM（零回归）
- `get_session_summary(identity)`：仅顺序读最新一条（id DESC LIMIT 1）；无摘要/读取
  失败 → 返回 ""（调用方跳过摘要段注入，零回归）

## WP2b `rag/engine.py` 分层注入

- `_resolve_session_history` 组装 history 时：持久化会话存在且摘要非空 →
  `[早期摘要段] + 最近 20 条原样`（摘要段 role='assistant' + content 前缀
  `[早期会话摘要]` 自描述）
- 会话 ≤20 条 / 无摘要 / 摘要读取失败 → 返回持久化会话原样，与旧行为逐字节一致
  （零回归）；无持久化会话/身份为空 → 回退当前请求 history（不变）
- 摘要段 role 选择：ReAct 路径（main.py 546/614 行）把 history 原样透传 LLM，
  system 角色中断列表会被部分供应商拒绝 → 用 assistant + 内容前缀自描述
- 已知边界：`reflector.generate_answer` / `generate_answer_stream` 仅取 history
  最后 6 条拼 prompt（module-005 遗留）——摘要段在超长 history 下可能被 [-6:]
  截断；ReAct 路径透传完整 history 不受影响。reflector 不在本 WP 文件清单内
  （红线），未改动；若需摘要段在纯反射路径也生效，需后续模块调整（记录待办）
- 与 Dev-A 的 engine 改动（`_recall_memory` 记忆召回段 / `_persist_memory`
  "记住"检测）区域不重叠；engine.py 由后到者（本会话）合并，双方改动共存验证
  （全量 500 全绿）

## WP2 测试（tests/test_session_memory.py，+12）

- `TestSessionSummary` 7 例：超限写入摘要行（source='memory:42:session_summary:' /
  title='session_summary' / content / embedding=None）/ 增量 prompt 含旧摘要+新段 /
  LLM 失败 fail-open 滚动删除照常 / LLM 空输出跳过 / 未超限不调 LLM /
  get_session_summary 最新一条 + 空/失败降级 / 摘要 source 隔离
- `TestLayeredInjection` 5 例：摘要段前置 + 最近 20 条原样 / 无摘要逐字节一致 /
  摘要读取失败跳过段 / 无持久化回退请求 history / 空身份回退
- 测试桩：`_SummaryFakeSession`（按编译后 SQL literal binds 路由：count/delete/
  session_summary 读取 first()/order by 段查询/content_hash），mock
  `LLMFactory.get_client` 打桩摘要 LLM

# WP3 提取评测闭环（Dev-B，2026-08-10）

## `eval/golden_memory.py` 新建

- 标注集 `MEMORY_GOLDEN_DATASET` 28 条：{dialogue 多轮对话文本, facts 应提取事实,
  keywords fixture 关键词}——22 条"应提取"（偏好/职业/技能栈/任务状态/明确"记住"/
  承诺）+ 6 条"不应提取"（facts=[]：一次性问答/寒暄/实时/通用知识，防过度提取）
- 指标：extract_facts 输出 vs 标注 → Precision / Recall / F1（micro 口径，汇总
  tp/fp/fn）；单样本匹配 = 归一化（去空白/标点小写）后互相包含任一方向（容忍
  措辞差异，贪心防重复计数）；空标注样本被预测 → 全 fp（过度提取惩罚）
- `_dialogue_to_extract_inputs`：dialogue → (query, answer, history) 映射
  extract_facts 公共入口（末轮 user=query、其后最近 assistant=answer、之前轮次
  =history；无 assistant 回答 → None → 样本跳过）
- eval_runs `eval_type='memory_extraction'` 版本化落库（复用 golden_retrieval 的
  save_eval_run + git_commit + rag_config 快照，record_eval_run 对齐
  golden_intent/golden_sufficiency 模式）
- `--fixture` 模式：关键词启发式提取（返回对话中含 keywords 的句子，按 。！？
  切句；无关键词返回空——"不应提取"样本 fixture 下同样不提取），不依赖 LLM/DB，
  确定性演示管线
- 降级：单条提取异常 → 跳过记录不中断；全跳过 → P/R 取 0.0 不崩溃；落库失败 →
  警告评估仍完成

## WP3 测试（tests/test_golden_memory.py 新建，22 例）

- `TestLoadMemoryGolden`：结构校验（≥20 条 / dialogue 非空 / facts 字符串列表 /
  "不应提取"样本 ≥5 且含 G1/寒暄 / 非法结构 ValueError）
- `TestDialogueMapping`：末轮 user/assistant 映射 + history / 无回答 None / 空文本
- `TestPrfMetrics`：双向包含匹配 / 基本 tp/fp/fn / 贪心防重复 / 过度提取全 fp /
  已知值 P/R/F1 / 空行 0.0
- `TestRunEval`：stub 提取器端到端（满分样本） / 过度提取惩罚（precision 1/3） /
  提取器异常跳过不崩溃
- `TestRecordEvalRun`：eval_runs 契约（eval_type='memory_extraction' + git_commit +
  配置快照，打桩 save_eval_run）/ 落库失败返回 0
- `TestFixtureExtract`：关键词命中返回句子 / 无关键词空 / 关键词未命中空 / 确定性
  无 LLM

## 测试与回归（WP2+WP3 部分）

- 新增测试共 +34：test_session_memory.py +12、test_golden_memory.py 新建 22
- 全量 `python -m pytest tests/ -q`：**500 passed / 0 failed**（基线 448 + 52
  [WP1 18 + WP2 12 + WP3 22]，全绿保持，未引入任何新失败；WP1 中途的 476/2 中
  2 个失败即本 WP 在写用例，已修复）
- 冒烟：`python -m eval.golden_memory --fixture --no-save`——28/28 评估 0 跳过，
  过度提取 0（管线验证；fixture 为启发式非真实指标，句子级关键词提取无法匹配
  改写式标注故 P/R 0.0，符合预期，真实指标需 LLM 环境补跑）

## 已知边界（WP2/WP3 补充）

- 摘要段在 reflector 纯反射路径可能被 [-6:] 截断（见 WP2b 已知边界，reflector
  不在本 WP 文件清单）
- golden_memory 真实模式（LLM）baseline 需 LLM 环境补跑；fixture 冒烟已验证管线
- 摘要仅在超限滚动删除时生成（21-50 条区间仍无摘要，与旧截断行为一致，属既有
  边界非本模块回归）

---

# Review 修复（review-report 缺陷复核，2026-08-10）

> 依据 review-report.md 缺陷 1（major）/ 缺陷 2（minor）/ 文档项（minor），
> 修复 Developer 逐项修复后复核，全量回归 503 passed / 0 failed。

## 修复 1 [major] 衰减/加权后结果未按新分数重排（`rag/memory.py` `_evolve_recall`）

- 原缺陷：`_evolve_recall` 逐条改写 `m["score"]` 但按原（语义分）顺序返回，
  `recall_short` 再按此顺序 `memories[:dynamic_k]` 截取——新分数不驱动排序与截取。
  实证：候选 A 语义分 0.9/20 天前（加权后 0.0089）与候选 B 语义分 0.7/今天（加权后
  0.7）并存，平均分 0.733 < 0.75 → dynamic_k=1 → 返回衰减到近零的 A，新鲜 B 被丢弃，
  直接违背 plan 场景 1「召回加权排前」与场景 2「分数×衰减系数后排后」及
  recall_short docstring「按 score 降序」契约（dynamic_k=1 为最常见档位）。
- 修复：`_evolve_recall` 返回前 `result.sort(key=lambda m: m["score"], reverse=True)`
  （⑤ 重排，stable 排序同分保持语义分先后）——新分数驱动召回排序与截取。
- 契约：recall_short 返回结构不变（content/score/title/created_at），score 语义
  仍为「衰减加权后分数」；排序由原始语义分序改为新分数降序，与 docstring 一致。
- 测试：`test_evolved_score_reorders_candidates_fresh_first`（K=5 两候选都返回，
  顺序断言新鲜在前）+ `test_evolved_ranking_drives_dynamic_k_truncation`
  （K=1 截取新分数最高者，旧候选被截断丢弃）。

## 修复 2 [minor] 超硬上限过滤项仍被提及刷新"复活"（`_evolve_recall` ③）

- 原缺陷：`if refs: asyncio.create_task(self._refresh_mentions(list(refs.keys())))`
  覆盖全部加载的参考文档（含循环内超硬上限 continue 过滤掉的项）——UPDATE
  IN (1,2,3) 含 40 天前超上限的 C，C 被置 last_mentioned_at=now + count+1，
  下次召回 age≈0 重新进池，30 天硬上限退化为「检索命中一次即复活」。
- 修复：循环内仅收集通过硬上限过滤（参与召回）的参考文档 id 到
  `refreshed_ids`，只对这些项 `_refresh_mentions`；超硬上限项不参与召回也不刷新。
- 测试：`test_beyond_hard_cap_not_refreshed`——断言 UPDATE 仅 `IN (1)`（硬上限内项），
  超上限项不产生 UPDATE（count 不增、不复活）。

## 文档 [minor] 补 test-report.md

- 验收 §7 三件套（changelog/review-report/test-report）补齐：
  `specs/module-046-memory-evolution/test-report.md` 新建——全量 503 passed / 0
  failed、各文件用例明细（test_memory 76 / test_session_memory 12 / golden_memory 22）、
  review 修复回归 3 例前后行为对照、冒烟与回归结论。

## 回归

- `python -m pytest tests/ -q`：**503 passed / 0 failed**（基线 448 + WP1 18 +
  review 修复 3 + WP2 12 + WP3 22），历史基线全绿 0 新失败。
- 修复范围仅在 `_evolve_recall`（排序 + 刷新集合过滤），其余逻辑（硬上限/衰减/
  加权/升级/记住）零改动；红线：只动 WP 文件、零迁移、长期层零变化、未 commit。

