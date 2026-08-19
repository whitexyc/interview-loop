# Review Report — Module-050: 幻觉检测模型真实对比（HHEM vs MiniCheck）+ WP5 目录细分

> Reviewer | 2026-08-11 | 第一轮审查
> 审查对象：`ai_service/eval/compare_factcheck_models.py` + `ai_service/tests/test_compare_factcheck.py` + WP5 目录细分（rag 三子包 + scripts/）
> 验证方式：独立全量运行对比脚本（复现数字）+ 独立全量 pytest + 冒烟（--limit 2 双侧）+ 模型/README 参考值核对 + 全仓库 grep 旧引用

---

## 0. 结论

**verdict: pass**（进 Tester）

全部核心验收项已验证通过：对比脚本数字可独立复现（与 changelog 逐一吻合）、
全量 pytest 579/0、模型完整可加载、WP5 迁移 import 兼容、诚实边界完整。
3 项 minor 不阻塞测试（1 项为 AC-7.4 的残留旧 import 一行修复，2 项文档类）。

---

## 1. 验证记录（Reviewer 独立复现）

### 1.1 全量对比复现（与 changelog §2.1 完全一致）

| 指标 | changelog | Reviewer 独立运行 |
|---|---|---|
| MiniCheck Accuracy / F1 / Prec / Rec | 0.5100 / 0.0392 / 1.000 / 0.020 | **0.5100 / 0.0392 / 1.000 / 0.020** ✓ |
| MiniCheck P(support) 中位 / s每对 | 0.162 / 2.855 | 0.162 / 2.891（机器波动内）✓ |
| HHEM Accuracy / F1 / Prec / Rec | 0.7700 / 0.7527 / 0.814 / 0.700 | **0.7700 / 0.7527 / 0.814 / 0.700** ✓ |
| HHEM P(support) 中位 / s每对 | 0.359 / 0.364 | 0.359 / 0.346 ✓ |
| Cohen's kappa | 0.0264 | **0.0264** ✓ |
| 二值一致率 / P 平均绝对差 | 58.0% / 0.2392 | **58.0% / 0.2392** ✓ |
| 不一致样本 | 42 条（前 5 条一致） | **42 条**，前 5 条逐一相同 ✓ |
| 文档最长 | 528 字符 | 528 字符 ✓ |

→ **无伪造数字**，结果可复现。数字内部自洽（MiniCheck Rec 0.020=50 条 supported 只抓回 1 条，
Accuracy 0.51 靠 50 条 unsupported 全对撑起——"从不正判"的伪高，结论解读正确）。

### 1.2 冒烟验证（AC-2 场景 3）

- `--limit 2 --skip-hhem`（MiniCheck 单侧）：跑通，2 对 12.2s（6.08s/对，首次加载含冷启动）
- `--limit 2 --skip-minicheck`（HHEM 单侧）：跑通，0.484s/对
- 管线（build_pairs → 加载 → 打分 → 指标表 → 诚实边界）双侧均正确

### 1.3 模型完整性核对（AC-1）

- `models/hhem-2.1-open/`：model.safetensors 438,535,352 B + config.json + modeling/configuration 自定义代码 + README ✓
- `models/minicheck-roberta-large/`：HF cache 布局（models--lytang--MiniCheck-RoBERTa-Large/snapshots/74c8919.../pytorch_model.bin 1,421,577,710 B + tokenizer 全家桶 + refs/main）✓
- `models/flan-t5-base/`：config/tokenizer.json/spiece.model 完整 ✓
- **HHEM README 参考值核对**：README.md L87 `tensor([0.0111, 0.6474, 0.1290, 0.8969, 0.1846, 0.0050, 0.0543])` 与 changelog §1.3 声称吻合 ✓
- **MiniCheck max_support_prob 语义核对**（源码 `minicheck.py L150-151`）：
  `pred_label = [1 if prob > 0.5 else 0 for prob in max_support_prob]` — 脚本取 max_support_prob
  且阈值 0.5 二值化，与 MiniCheck 自身判定语义完全一致 ✓
- HHEM `predict()` 语义核对（modeling_hhem_v2.py L58-70）：官方 prompt 模板 + softmax 取 class 1
  （consistent，config id2label 0=hallucinated/1=consistent）✓；config.json foundation 已指向本地
  `models/flan-t5-base` ✓（changelog 诚实声明了该本地改动）
- nltk punkt：`<home>\nltk_data\tokenizers\punkt` 存在 ✓（punkt_tab 缺失不影响，
  冒烟实测 MiniCheck 内部 sent_tokenize 正常）
- 偏离 plan §3.2 的 HHEM 输入格式（plan 写 `premise: {doc} hypothesis: {claim}` 老式拼接，
  实现用官方 predict()）——**偏离有据**：HHEM-2.1-Open 为 T5 架构自带 prompt 模板，
  老式拼接是 HHEM-2.1 时代格式；changelog §1.3 已如实记录且用 README 参考值背书。

### 1.4 WP5 迁移验证（AC-7）

- 结构：`rag/{retrieval,graph,memory}/` 三子包齐全（6+3+3 文件），`state/models/schemas/engine/migrate_parent_child` 留根 ✓；`scripts/` 12 脚本 + `__init__.py` ✓；`main.py` 留根 ✓
- 兼容层：`rag/__init__.py` sys.modules + 包属性双注册（12 旧模块名）
  - 实测 `import rag.retriever` → 命中 `rag.retrieval.retriever` 同一模块对象 ✓
  - `import rag.memory` → `rag.memory.memory` ✓
  - `mock.patch("rag.memory.async_session_factory")` 等存量用例（tests/test_memory.py L101 等）经 sys.modules 别名命中真实模块，全量 pytest 通过证明 patch 兼容成立 ✓
- 新路径迁移：全仓库 grep（排除 tests/ 与 __init__ 兼容层）仅剩 1 处旧路径（见 minor #1）；`rag/retrieval/text_tokenizer.py L12` 为 docstring 提及非实际 import ✓
- 脚本可运行：`python -m scripts.backfill_search_tokens --help` 与 `python scripts/backfill_search_tokens.py --help` 均从 ai_service 正常执行（幂等，total=0）✓
- `.gitignore` 修复：`memory/` → `/memory/`（git check-ignore 实测 `ai_service/rag/memory/memory.py` 不再命中）✓；移除失效 `ai_service/test_m17.py` 规则 ✓
- 存量测试未被修改掩盖：git status 无任何 tests/ 存量文件变更 ✓

### 1.5 全量 pytest（AC-4/6/7）

`python -m pytest tests/ -q` → **579 passed / 0 failed**（567 基线 + 12 新增，Reviewer 独立运行确认）

---

## 2. 逐条 AC 核查

| # | 验收项 | 结论 |
|---|---|---|
| 1.1 | HHEM 下载完整可加载 | ✅ 文件核对 + 冒烟加载成功 |
| 1.2 | MiniCheck 下载完整可加载 | ✅ 文件核对 + 冒烟加载成功 |
| 1.3 | minicheck GitHub 源码 + punkt | ✅ sys.path 引 `minicheck-src`；punkt 就绪 |
| 2.1 | --limit 5 冒烟两模型加载+打分 | ✅ Reviewer 双侧 --limit 2 复现，管线正确 |
| 2.2 | build_pairs 100 对（claim/doc/标注映射） | ✅ 测试 TestBuildPairs + 全量运行数据行确认 |
| 2.3 | 全量输出全部指标项 | ✅ 复现输出含全部项 |
| 2.4 | --skip-* 单侧可跑 + 缺失报错清晰 | ✅ 双侧冒烟验证；`_require_model` 双布局探测 + 测试覆盖 |
| 3.1 | F1 正类=supported | ✅ `f1_score` 默认 pos_label=1 + 测试断言口径 |
| 3.2 | Cohen's kappa（sklearn） | ✅ `cohen_kappa_score` 二值化后计算 + 测试 |
| 3.3 | 诚实边界声明 | ✅ 4 条声明在脚本输出与 changelog 中均打印（见 minor #3 一处表述精度问题） |
| 4.1 | 模型缺失不静默 | ✅ `_require_model` 报错含绝对路径与缺失文件 |
| 4.2 | 单模型独立可跑 | ✅ --skip-* 实测 |
| 4.3 | 全量 pytest 579 全绿 | ✅ Reviewer 独立运行确认 |
| 5.1 | 不改 verify_answer/生产链路 | ✅ git diff 确认 engine/agent/main 仅 import 迁移，无逻辑变更 |
| 5.2 | golden_sufficiency.py 不动 | ✅ git status 无该文件变更，脚本只读 import |
| 6.1 | 测试覆盖 build_pairs/指标/kappa/缺失报错 | ✅ 12 项全部覆盖 |
| 6.2 | 全量 pytest 579 | ✅ |
| 7.1 | scripts/ 12 脚本 + main.py 留根 | ✅ |
| 7.2 | rag 三子包结构 | ✅ |
| 7.3 | 旧路径 import 兼容 | ✅ 实测 + mock.patch 用例全绿 |
| 7.4 | 新路径迁移无残留旧引用 | ⚠️ 仅 main.py:100 一处残留（minor #1） |
| 7.5 | 脚本从 ai_service 可运行 | ✅ 两种方式实测 |
| 7.6 | 迁移后全量绿 | ✅ 579/0 |
| 8.1 | changelog / review-report / test-report | ✅ changelog 全数字复现；review-report 本文档；test-report 归 Tester |
| 8.2 | memory 三记忆文件 | ✅ project-context（module-050 行）+ agent-activity-log（Developer 行）+ file-index（新条目）；Reviewer 行本次追加 |
| 8.3 | ADR-0010 状态更新 | ⚠️ 见 minor #2 |

---

## 3. Major Findings（必须修复）

无。

## 4. Minor Findings（不阻塞，建议修复）

1. **main.py:100 残留旧路径 lazy import**（`ai_service/main.py`）
   - issue：`from rag.embeddings import embedding_service` 仍是旧路径，与 changelog §4.2
     "生产代码一律迁移到新路径"及"grep 无残留旧引用"声明不符（AC-7.4 未完全满足）。
     当前经兼容层可正常跑，但按规范应改新路径。
   - suggestion：改为 `from rag.retrieval.embeddings import embedding_service`，并同步修正
     changelog 中"grep 无残留旧引用"的表述。

2. **ADR-0010 状态未更新**（AC-8.3）
   - issue：ADR-0010 文件（主 checkout `specs/adr/0010-hallucination-detection-upgrade.md`）
     状态行仍为"方案已定，P0 可先行"，未记录 module-050 数据验证结论
     （P0-② 数据验证完成/待实施裁判切换）。注意该文件不在 worktree 内（worktree
     specs/adr 无 0010），changelog §2.2/§6 已书面记录状态过渡。
   - suggestion：主会话/Developer 在合并时向 ADR-0010 追加状态行：
     "P0-② 数据验证完成（module-050）：中文场景 HHEM 0.77 vs MiniCheck 0.51，选型结论 HHEM，
     裁判切换待实施"。

3. **诚实边界第 4 条表述精度**（`ai_service/eval/compare_factcheck_models.py` L276-277）
   - issue："HHEM max_length 受 T5 512 token 限制，超长文档会被截断"——实际 `predict()`
     调 tokenizer 未传 max_length/truncation（modeling_hhem_v2.py L61-62），代码路径上
     不存在截断行为；T5 相对位置偏置可处理超长输入。本次文档最长 528 字符本就不触发，
     声明偏保守无实际危害，但机制描述与代码不符。
   - suggestion：改为"HHEM 预训练最大序列约 512 token，本题集文档最长 528 字符，
     超出部分超出预训练分布，影响有限"，或补传 max_length 使声明与行为一致。

## 5. 结果解读核对（审查要点 6）

- 选型结论与数据一致：HHEM Accuracy/F1 全面优于 MiniCheck、MiniCheck 中文输入下
  supported Recall 0.020（只抓回 1/50）→ "MiniCheck 中文退化"结论由数据直接支撑，非过度外推 ✓
- kappa 0.0264 + 一致率 58% → "两模型判定趋近无关"与数值一致 ✓
- CPU 在线可行性：HHEM 0.346 s/对 vs MiniCheck 2.891 s/对（~8 倍），与 changelog 结论一致 ✓
- 局限已如实声明：跨语言泛化、claim=问题代理度量（真实 verify_answer 用答案句子）、
  注入文档非真实检索、需后续真实答案句子复核——均未越界外推 ✓
- 英文参考对判别正常（0.098/0.365/0.054）佐证中文退化是模型行为而非加载 bug，
  该点在 changelog §2.3 声明（Reviewer 未独立复跑英文对，标注为 Developer 实测证据）

## 6. 测试审查（审查要点 5）

- 不加载真实模型（纯单元、mock 分数数组）✓；模型加载留给 --limit 冒烟 ✓
- 覆盖 AC 场景：build_pairs（条数/映射/中文句切/空文档）、指标（完美/全反/部分口径 + kappa 一致/相反）、
  _require_model（缺失目录/缺失文件/完整目录/HF cache 布局）✓
- 未改存量测试 ✓（git status 无 tests/ 存量变更）
- 新增 12 项与 changelog 声明一致 ✓

## 7. 附注

- `rag/__init__.py` 将三子包改为**急切导入**（import rag 即实例化 reranker/embedding_service
  等模块级单例）——行为变化但单例均为懒加载（_lazy_load），全量 pytest 与独立冒烟无异常，
  属兼容层必要取舍（changelog §4.2 已说明），不列缺陷。
- 测试子集 `test_query_rewrite + test_memory_extractor` 组合 5 项失败为基线可复现的既有问题
  （changelog §4.5，基线提交原样复现），与本次改动无关；验收口径 `python -m pytest tests/ -q`
  全量 579/0 不受影响。
