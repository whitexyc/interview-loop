# Review Report — Module-051: verify_answer 接入 HHEM 专职裁判

> Reviewer | 2026-08-11 | 第一轮审查
> **结论：✅ 通过（pass）**——无阻塞项，4 项非阻塞建议

---

## 1. 审查范围与独立复现

完整阅读：`specs/module-051-hhem-judge/plan.md` + `acceptance-criteria.md` + 变更文件
（reflector.py / config.py / factcheck_judge.py / hhem_loader.py / golden_factcheck.py /
compare_factcheck_models.py / test_factcheck_judge.py）+ 内存三文件 + changelog。

独立复现结果（与 changelog 数字逐一吻合，无伪造）：

| 验证项 | 命令 | 结果 |
|--------|------|------|
| 全量回归 | `python -m pytest tests/ -q` | **611 passed / 0 failed**（117s；579 基线 + 新 32） |
| fixture 冒烟 | `python -m eval.golden_factcheck --fixture --no-save` | kappa 三态 **0.9375** / 二值 0.9167 / Acc 0.9600，50/50 评估 |
| 真实模式 | `python -m eval.golden_factcheck --no-save` | kappa 三态 **0.3252** / 二值 **0.3220** / Acc 0.5600；supported 11/20、inferred 2/10、unsupported 15/20；输出"kappa 0.3252 < 0.7 未达门槛，如实标注" |
| 编译检查 | `python -m py_compile` 6 个变更文件 | OK |
| 降级 prompt 无漂移 | `git show HEAD:ai_service/agent/reflector.py` 对比 | `_VERIFY_LLM_PROMPT` 与 module-039 `_VERIFY_PROMPT` **逐字节一致**（仅改名+注释） |

真实模式数字与 changelog 完全一致（0.3252/0.3220/0.5600/11-2-15），kappa<0.7 如实标注，无伪造。

## 2. 验收标准逐条核对（AC 8 节 37 项复选框）

### §1 功能（WP1 裁判封装）— 全过
- `factcheck_judge.py` 存在，延迟加载（首次 predict 才加载，`_load_failed` flag 短路重试）✅
- 加载复用 module-050 已验证路径，**提取共享 loader `rag/retrieval/hhem_loader.py`（单一来源）**，
  compare_factcheck_models.py::load_hhem 已改引用；grep 无第二份加载实现 ✅
- `predict(docs, claims)` 批量打分；CPU 推理经 `asyncio.to_thread`（threading.Lock 跨线程互斥，
  module-027 同款经验）✅
- 模型缺失/加载失败/推理异常 → 返回 None 不抛 ✅

### §2 功能（WP2 拆分）— 全过
- `_VERIFY_PROMPT` 精简为纯拆句（输出字符串数组，不再判 verdict/填 evidence）✅
- verdict 由 HHEM 判定：每 claim × 每文档交叉打分（flat 构造顺序正确：
  claim 固定外循环 × docs 内循环，段长 = n_docs）→ max 映射三态，阈值读配置 ✅
- evidence = max 分文档号（1-based），unsupported "N/A" ✅
- 返回结构零改动（claims/overall_confidence/total_claims/supported/inferred/unsupported）✅
- overall_confidence 口径不变（1 - unsupported/total）✅

### §3 功能（WP3 配置）— 全过
- `verify_judge_model="hhem"` 默认（PW_ 前缀）+ `verify_hhem_threshold_high=0.7/low=0.3` ✅
- 开关 "llm"：完全不加载 HHEM（import 只在 `_judge_by_hhem` 内、旧格式兼容分支之后）✅

### §4 降级 — 全过
- HHEM 缺失/失败 → 回退 LLM 判分（旧全量 prompt 逐字节保留，`_parse_verification` 未动）✅
- LLM 拆句失败/超时 → 空 claims（外层 except 兜底）✅
- LLM 判分也失败 → 空 claims（overall_confidence=0.0）✅
- 全量 611/0 独立复跑确认（579 基线保持，未改存量测试）✅

### §5 接口兼容 — 全过
- verified_claims 结构不变，前端零改动（ChatPage/ChatMessage/rag.ts 均未触碰）✅
- verify_answer 签名与返回不变（engine.py:342 / main.py:506 / tool_registry 未改）✅
- 评测脚本单侧可跑（--fixture / --no-save / compare 脚本 --skip-*）✅

### §6 测试 — 全过（32 项，全部 mock 不加载真实模型）
- 加载降级（mock 缺失路径 + 失败不重试）、批量打分、三态边界 0.7/0.3 恰好值、
  evidence 取 max 文档、verify_answer 集成（AC 场景 1）、降级链三层、开关 llm 零回归、
  返回结构兼容、拆句解析 7 项、golden_factcheck 评测脚本 9 项 ✅
- 全量 611/0（git status 确认无存量测试改动）✅

### §7 评测（WP5）— 全过
- 50 条三态标注（supported 20 + unsupported 20 继承 SUFFICIENCY_DATASET 人工充分性标注 +
  inferred 10 人工构造"部分覆盖"含 note）✅
- kappa 三态 + 二值（supported-vs-rest，预测侧与生产阈值同口径）两口径 ✅
- eval_runs 落库 `eval_type='factcheck'`（复用 golden_retrieval save_eval_run，
  契约经单测 test_record_eval_run_contract 验证；DB 落库 id=15 见 changelog，
  本机 DB 凭证不可用未直接查询——非阻塞）✅
- `--fixture` 启发式不依赖模型；模型不可用 → skipped（reason=model_unavailable）不中断 ✅
- kappa 0.3252 < 0.7 → 真实模式输出如实标注"未达门槛"（已独立复现）✅

### §8 文档 — 基本完成（2 项移交）
- changelog.md 含全部实测数字 ✅；memory/ 三文件已更新（project-context 追加 module-051 记录 +
  activity-log 活动行 + file-index 补 4 文件 + 模块行）✅
- review-report.md：本文 ✅
- test-report.md：Tester 产出（审查后测试阶段，符合流程）⚠️ 移交
- ADR-0010 状态：worktree CONTEXT.md 未更新（main checkout 也未更新），状态更新体现在
  memory/project-context.md ADR 索引行（"adr-010 … P0-② 已实施"）；按 module-050 先例，
  主 checkout CONTEXT.md 状态行由主会话合并时追加 ⚠️ 移交

## 3. 发现项

### 无阻塞项（major = 0）

### 非阻塞建议（minor = 4）

1. **[agent/reflector.py:439 / rag/retrieval/factcheck_judge.py:80] HHEM 判分无超时保护，主路径总耗时可能超过 module-039 的 15s 硬上限**。
   现状：LLM 拆句有 15s wait_for，但 `_judge_by_hhem` → `hhem_judge.predict` 无超时包裹；
   交叉对数 = claims × docs，5 claims × 5 docs ≈ 9s、10 × 5 ≈ 18s+，chat 端点串行等待，
   HHEM 推理 hang 时会无限阻塞（15s 超时哲学失效）。changelog 已诚实标注"偏重"但总耗时
   （拆句 + HHEM）可超 15s。建议：给 predict 调用加 `asyncio.wait_for`（如 15s，超时降级 LLM）
   或限制交叉对数量（如 claims 上限 + 每 claim 最多 5 文档）。非阻塞（CPU 推理确定性高，hang 概率低）。

2. **[agent/reflector.py:619-623] `_parse_claims` 旧格式兼容路径：dict 项带 verdict 但无 evidence 时 claim 缺 evidence 键**。
   `_judge_by_hhem` 旧格式分支直通此类 claims（不补 evidence），前端
   `ChatMessage.tsx:311 parseEvidenceRef(claim.evidence)` 对 undefined 调 `.match` 抛 TypeError。
   仅当 LLM 未听新 prompt 且返回 `{"claim": "...", "verdict": "..."}`（无 evidence）时触发，
   概率低。建议：dict 项带 verdict 时默认补 `evidence="N/A"`（与 `_parse_verification` 对齐），一行修复。

3. **[memory/ 文档] Developer 活动日志"ADR-0010 状态更新（P0-② 已实施）"表述不精确**：
   实际更新落在 memory/project-context.md ADR 索引行，worktree 与 main checkout 的
   CONTEXT.md 状态行均未动。建议主会话合并时按 module-050 先例追加 CONTEXT.md 状态行；
   活动日志可注明落点，避免误导。

4. **[eval/golden_factcheck.py:429-437] fixture 模式门槛行打印"达标（ADR-0010 P1-④）"**：
   fixture 是关键词启发式（非真实指标），虽头部标注"非真实指标"，门槛判定行措辞易误读。
   建议 fixture 模式下不打印达标判定，或加 `[fixture]` 前缀。

## 4. 设计决策复核

- **旧格式兼容（changelog 4.1）**：`_parse_claims` 保留 dict 项的 verdict/evidence →
  `_judge_by_hhem` 整体跳过 HHEM 直接采用。存量 test_reflector.py TestVerifyAnswer 25 项
  不改一字全绿（全量 611/0 实证）；生产主路径 LLM 按新 prompt 输出字符串数组正常走 HHEM。合理。
- **阈值 0.7/0.3 经验值**：真实模式实测 9/20 supported 被压入 inferred 带（0.33-0.67），
  与 module-050"中文分数压缩（中位 0.359）"结论一致；诚实标注 + 校准方向记录在 changelog，合理。
- **降级路径成本**：HHEM 不可用时拆句 + 判分两次 LLM 调用（module-039 为一次），仅降级场景发生，
  主路径一次 LLM + HHEM CPU，设计可接受。

## 5. 结论

**verdict: pass（通过）**。7/8 节 AC 全部代码/单测核验通过；真实模式与 fixture 数字独立复现一致，
kappa<0.7 如实标注无伪造；全量 611/0 复跑确认。4 项 minor 均为健壮性/文档建议，不阻塞。
待办移交：Tester 出 test-report.md；主会话合并时补 main checkout CONTEXT.md 的 ADR-0010 状态行。
