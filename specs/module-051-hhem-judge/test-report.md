# Test Report — Module-051: verify_answer 接入 HHEM 专职裁判（ADR-0010 P0-②）

> Tester | 2026-08-11 | 全量基线 579 passed → **611 passed / 0 failed**（新增 32）

---

## 1. 全量测试

| 项 | 结果 |
|----|------|
| `python -m pytest tests/ -q` | **611 passed, 0 failed**（4 warnings 均为存量：redis setex Deprecation + asyncpg 连接清理警告） |
| 基线保持 | 579 存量全绿（changelog 宣称一致） |
| 新增 | `tests/test_factcheck_judge.py` 32 项全过 |
| 存量测试 | 未修改（git status 确认无 `M ai_service/tests/` 文件） |

## 2. 冒烟实测

### 2.1 HHEM 接入冒烟（真实模型 + 真实 LLM 拆句）

`verify_answer` 端到端真跑（deepseek 拆句 + HHEM-2.1-Open 判分，G1 文档场景，答案含 1 句编造参数）：

- LLM 拆出 5 句 claims；文档内有依据的 4 句 → **supported / evidence=[1]**
- 编造的"-XX:G1HeapRegionSize 设置为 16MB"（文档无此内容）→ **unsupported / evidence=N/A**（HHEM 正确捕获幻觉）
- `overall_confidence=0.8`（= 1 - 1/5，口径不变）；返回键集合与前端契约零改动

### 2.2 跨文档 max 分证据选择冒烟（真实模型）

三 claim × 两文档（Redis 持久化 / G1 GC）：

- "G1 把堆划分为 Region" → **supported / evidence=[2]**（G1 文档，非 [1]）
- "Redis AOF 可配置 everysec" → **supported / evidence=[1]**
- "Kafka ISR 机制"（两文档均无）→ **unsupported / evidence=N/A**

→ max 分对应文档号取值正确，三态映射正确。

### 2.3 kappa 复跑（真实模式，`--no-save` 避免重复落库）

```
Dataset: 50 | Evaluated: 50 | Skipped: 0
Thresholds: high=0.7 low=0.3
Cohen's kappa (三态): 0.3252
Cohen's kappa (二值 supported-vs-rest): 0.3220
Accuracy (三态精确一致): 0.5600
==> 门槛判定: 三态 kappa 0.3252 < 0.7 未达门槛，如实标注
Class distribution: supported 11/20 | inferred 2/10 | unsupported 15/20
```

**与 Developer changelog 完全一致**（0.3252 / 0.3220 / 0.5600，分布 11/2/15；Developer 已落库 id=15, commit=36d3606b，本次 --no-save 复跑验证可复现）。

## 3. 实现抽查（对照 changelog）

| 项 | 依据 | 结论 |
|----|------|------|
| WP1 单一来源 | `rag/retrieval/hhem_loader.py` 提取共享加载；`eval/compare_factcheck_models.py:151-153` 已改引用 `load_hhem_model`；grep 无第二份生产加载实现 | 通过 |
| WP1 裁判封装 | `HHEMJudge`：延迟加载（`_lazy_load`）+ `threading.Lock` + `asyncio.to_thread` + 任何失败返回 None；空输入不加载 | 通过 |
| WP2 拆分 | `_VERIFY_PROMPT` 纯拆句（92-101 行）；`_VERIFY_LLM_PROMPT` 旧全量逐字节保留（106-124 行）；`_judge_by_hhem`（490-547）三态映射读配置、evidence 取 max 文档号 1-based、分数数量异常→None；`_parse_claims` 字符串/dict/markdown 容错 | 通过 |
| WP2 返回结构 | 冒烟实测键集合 = {claims, overall_confidence, total_claims, supported, inferred, unsupported}；overall_confidence = 1 - unsupported/total | 通过 |
| WP3 配置 | `verify_judge_model="hhem"` + `verify_hhem_threshold_high=0.7` + `low=0.3`（PW_ 前缀，config.py:116-120） | 通过 |
| WP4 降级链 | ① HHEM None→`_judge_by_llm`（旧全量 prompt）② LLM 失败→空 claims（外层 except 兜底）③ 开关 "llm"→`_judge_by_llm` 直走（import 在 `_judge_by_hhem` 内，零加载） | 通过 |
| WP5 评测 | `eval/golden_factcheck.py`：50 条三态（supported 20 继承 SUFFICIENCY 充分样本 + unsupported 20 不充分样本 + inferred 10 人工构造）；kappa 两口径；`eval_type='factcheck'` 落库（复用 golden_retrieval）；`--fixture`/`--no-save`；模型不可用记 skipped 不中断 | 通过 |
| WP6 测试 | 32 项全部 mock 模型（`mock.patch` load_hhem_model / predict），不加载真实模型 | 通过 |
| 文档 | ADR-0010 状态已更新"P0-② 已实施，裁判切换完成"；memory 三文件已改（agent-activity-log / file-index / project-context，未 stage）；无 git 提交 | 通过 |

## 4. 验收标准逐条对照

| AC | 判定 | 依据 |
|----|------|------|
| §1-1 factcheck_judge.py 延迟加载 | 通过 | `_lazy_load` 首次 predict 才加载；空输入不加载 |
| §1-2 复用 module-050 路径单一来源 | 通过 | hhem_loader.py 提取（取了共享 loader 分支），compare 脚本引用；HHEM_REQUIRED_FILES 缺失报错指出路径 |
| §1-3 predict 批量 + to_thread | 通过 | `_predict_sync` 整批持锁 + `asyncio.to_thread`；测试 mock 分数断言批调 |
| §1-4 失败→None 不抛 | 通过 | predict except 返回 None；`_load_failed` flag 短路重试 |
| §2-1 _VERIFY_PROMPT 纯拆句 | 通过 | 92-101 行：只拆句不判 verdict；旧全量保留为 _VERIFY_LLM_PROMPT |
| §2-2 HHEM 判三态 + 阈值读配置 | 通过 | _judge_by_hhem 每 claim×每 doc 打分 → max 映射；冒烟实测 0.7/0.3 生效 |
| §2-3 evidence=max 分文档号，unsupported N/A | 通过 | 冒烟 2.2：G1→[2]、Redis→[1]、Kafka→N/A |
| §2-4 返回结构不变 | 通过 | 冒烟 2.1 键集合核对 |
| §2-5 overall_confidence 口径不变 | 通过 | 0.8 = 1-1/5 实测 |
| §3-1 config 默认 hhem + 0.7/0.3 | 通过 | config.py 三配置项（PW_ 前缀） |
| §3-2 开关 "llm" 零加载 | 通过 | 测试覆盖 HHEM 零调用；import 位置在 _judge_by_hhem 内 |
| §4-1 HHEM 失败→LLM 判分行为一致 | 通过 | 降级链测试① + _VERIFY_LLM_PROMPT 保留 |
| §4-2 拆句失败→空 claims | 通过 | 测试覆盖；外层 except 兜底 |
| §4-3 LLM 判分失败→空 claims 0.0 | 通过 | 测试覆盖 |
| §4-4 全量 579 全绿 | 通过 | 611 passed（579 存量 + 32 新增） |
| §5-1 verified_claims 前端零改动 | 通过 | 返回结构不变（实测）；review 确认前端文件未触碰 |
| §5-2 verify_answer 签名不变 | 通过 | 冒烟直接以原签名调用成功；engine/main/tool_registry 未改 |
| §5-3 --skip-* 单侧可跑 | 通过 | golden_factcheck --fixture / --no-save 支持；compare 脚本 --skip-* 存量 |
| §6-1 test_factcheck_judge.py 覆盖 | 通过 | 32 项：加载降级 mock / 批量打分 mock / 三态边界 0.7、0.3 恰好值 / evidence max / 集成 / 降级链三层 / 开关 llm / 拆句解析 |
| §6-2 全量 579+ 全绿不改存量 | 通过 | 611/0；git status 无存量测试改动 |
| §7-1 50 条 + kappa 两口径 | 通过 | 复跑 0.3252（三态）/ 0.3220（二值） |
| §7-2 eval_runs eval_type='factcheck' | 通过 | record_eval_run 复用 golden_retrieval；Developer 落库 id=15 |
| §7-3 --fixture 不依赖模型 / 失败 skipped | 通过 | fixture 关键词启发式（Developer 冒烟 0.9375 管线演示）；run_eval 记 model_unavailable 不中断 |
| §7-4 kappa<0.7 如实标注 | 通过 | 真实模式输出"未达门槛，如实标注"，无伪造 |
| §8-1 changelog/review-report/test-report | 通过 | 三者齐备含实测数字 |
| §8-2 memory 三文件更新 | 通过 | agent-activity-log / file-index / project-context 已改（未 stage） |
| §8-3 ADR-0010 状态更新 | 通过 | "P0-② 已实施，裁判切换完成"（含 kappa 0.3252 未达门槛诚实标注） |

**AC 汇总：25 项全部通过 / 0 项失败。**

## 5. 阻塞项

无。唯一非阻塞关注点：kappa 0.3252 未达 0.7 门槛——属 ADR-0010 既定诚实边界（阈值 0.7 对中文分数压缩偏严 + inferred 标注口径与 HHEM 分数语义不一致），已在 changelog/ADR 如实标注并给出校准方向，不构成交付阻塞。
