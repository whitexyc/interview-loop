# Module-050 测试报告 — HHEM vs MiniCheck 真实对比（ADR-0010 数据验证）+ WP5 目录细分

> Tester | 2026-08-11 | 结论：**通过**（无阻塞问题；2 项附条件非阻塞）

## 1. 全量测试

```
python -m pytest tests/ -q
→ 579 passed, 4 warnings in 104.30s（EXIT_CODE=0）
```

- 579 = 567 存量基线全绿 + 12 新增（`tests/test_compare_factcheck.py`：TestBuildPairs 4 + TestMetrics 4 + TestRequireModel 4，独立复跑确认）
- 无存量用例失败；`git status` 确认未修改任何存量测试（tests/ 仅有 `test_compare_factcheck.py` 新增）
- 4 个 warning 均为既有用例（cache setex 弃用、asyncpg 连接池告警），非本模块引入
- 与 changelog 声明（567 基线 + 12 新增 = 579/0）一致

## 2. 冒烟评测（AC-2 场景 3）

```
python -m eval.compare_factcheck_models --limit 5
→ EXIT_CODE=0
```

| 项 | 实测 |
|----|------|
| 数据头 | `== 数据: 5 对 (supported 标注 5 / unsupported 0)` |
| MiniCheck | 加载成功（393 权重块），5 对 22.1s，4.415s/对 |
| HHEM | 加载成功，5 对 2.1s，0.411s/对 |
| 指标表 | 两模型 Accuracy/F1/Prec/Rec/P(support)中位/s每对 全部输出 |
| 两模型对比 | kappa 0.0000（首 5 对全 supported，二值结果歧义区间）、一致率 60.0%、P 平均绝对差 0.2742 |
| 不一致样本 | 2 条：[1] Kafka ISR MiniCheck=0.294 HHEM=0.907、[3] volatile 0.326/0.680 —— **与 changelog §2.1 全量前 5 条的取值逐对相同**，数字一致性确认 |
| 诚实边界 | 4 条声明全部打印（跨语言/claim=问题代理/注入文档/512 截断） |

- 每对耗时与 changelog §2.1 冒烟备注一致（MiniCheck ~4.4-5.2s/对、HHEM ~0.4s/对）
- 加载顺序符合 plan §3.3：MiniCheck 推理完释放（`_mc = None`）再加载 HHEM，峰值内存单模型
- transformers 一条 benign 提示（HHEMv2Config 实例化警告）非错误

## 3. 关键实现点抽查（与 changelog/review-report 一致）

| 要点 | 位置 | 验证结果 |
|------|------|----------|
| build_pairs | `eval/compare_factcheck_models.py:67` | 实测 100 对 / label=1 共 50 条，与 SUFFICIENCY_DATASET（100 条、sufficient=50）一致；claim=question、doc=两篇 content 拼接；`_pre_chunk` 中文句切（。！？；）实测正确 |
| 标注映射 | 同一问题充分/不充分各一条 → [0,1] | test_count_and_label_mapping：G1 问题两条 label [0,1] 通过 |
| 指标口径 | model_metrics（L177）/ cohen_kappa（L172） | F1 正类=supported（f1_score 默认 pos_label=1）；kappa 用 sklearn cohen_kappa_score 对 >0.5 二值判定 |
| HHEM 打分 | load_hhem/hhem_score（L143/L166） | 离线 + get_class_from_dynamic_module + embed_tokens 展开 + 官方 predict()（内部 prompt 模板）；README 参考值 0.0111/0.6474/... 存在于 `models/hhem-2.1-open/README.md` L87 |
| MiniCheck 打分 | load_minicheck/minicheck_score（L108/L134） | sys.path 引 GitHub 源码 `minicheck-src/minicheck/minicheck.py`（非 PyPI 工具）；取 max_support_prob；device_map 剥离；chunk_size=400 |
| 模型缺失报错 | `_require_model`（L82） | FileNotFoundError 含绝对路径 + 缺失文件列表；双布局探测（平铺 + HF cache snapshots/）测试覆盖 |
| 诚实边界 | main() L269-277 | 4 条声明输出；第 4 条"512 截断"表述与 predict() 实际行为精度不符（review minor #3，保守声明无危害） |

### WP5 迁移抽查（AC-7）

| 项 | 验证结果 |
|----|----------|
| scripts/ 结构 | 12 个一次性脚本 + `__init__.py`（backfill_*/create_*/migrate_*/download_model/do_all/reindex/test_embedding/test_m17/test_m18/test_models）；main.py 留根 ✓ |
| rag 三子包 | retrieval/（6 文件）+ graph/（3）+ memory/（3）；state/models/schemas/engine/migrate_parent_child 留 rag 根 ✓ |
| 旧路径兼容 | 实测 `rag.retriever is sys.modules['rag.retrieval.retriever']`（同对象）；12 个旧模块名 sys.modules+包属性双注册 ✓ |
| 脚本可运行 | `python scripts/backfill_search_tokens.py` 与 `python -m scripts.backfill_search_tokens` 均从 ai_service 执行成功（迁移完成/回填 total=0，幂等）✓ |
| 生产代码 diff | engine/agent/{tool_registry,router,intent_classifier}/eval 5 文件/main.py 的 diff 全部为 import 迁移（无逻辑变更）✓ |
| 存量测试未改 | git status 无任何 tests/ 存量文件变更 ✓ |
| golden_sufficiency.py | 未在 git status 变更列表，脚本只读 import ✓ |
| .gitignore | `memory/` → `/memory/` 锚定已生效 ✓ |
| 残留旧引用 | 全仓库 grep（排除 tests/ 与兼容层注释）：仅 `main.py:100` 一处函数内懒加载 `from rag.embeddings import embedding_service`（review minor #1，经兼容层可用，非阻塞） |

## 4. AC 对照表（acceptance-criteria.md 逐条，共 26 项）

### §1 功能验收 WP1 环境前置 — 全部通过
- [x] 1.1 HHEM-2.1-Open 下载完整可加载：model.safetensors 438,535,352 B + config.json + 自定义代码 + README，冒烟实测加载成功
- [x] 1.2 MiniCheck-RoBERTa-Large 完整可加载：pytorch_model.bin 1,421,577,710 B + tokenizer 全家桶（HF cache 布局），冒烟实测加载成功
- [x] 1.3 minicheck 用 GitHub 源码（sys.path 引 `<home>\AppData\Local\Temp\minicheck-src`，非 PyPI 工具）；nltk punkt 就绪（`<home>\nltk_data\tokenizers\punkt` 存在）

### §2 功能验收 WP2 对比脚本 — 全部通过
- [x] 2.1 `eval/compare_factcheck_models.py` 存在，`--limit 5` 冒烟两模型加载 + 打分跑通（exit 0）
- [x] 2.2 build_pairs 100 对（claim=问题、doc=中文句切拼接、label=人工标注）：实测 100 对 / 50 标注 supported，测试覆盖映射与句切
- [x] 2.3 全量输出含全部指标项：各自 Accuracy/F1/Prec/Rec/P(support)中位 + kappa + 二值一致率 + P 平均绝对差 + 不一致样本前 5 + 每对耗时（changelog §2.1 全量实测 + Reviewer 独立复现 + 本冒烟逐对吻合）
- [x] 2.4 `--skip-hhem`/`--skip-minicheck` 单侧可跑（argparse 支持 + Reviewer 双侧冒烟实测）；模型缺失报错清晰（`_require_model` 报错含绝对路径与缺失文件）

### §3 功能验收 WP3 指标口径 — 全部通过
- [x] 3.1 F1 正类=supported（f1_score 默认 pos_label=1；测试 test_model_metrics_recall_emphasized 验证漏抓口径）
- [x] 3.2 Cohen's kappa 用 sklearn cohen_kappa_score（测试 test_cohen_kappa 完全一致=1.0 / 完全相反<0）
- [x] 3.3 诚实边界声明输出（4 条：跨语言泛化/claim=问题代理度量/注入文档非真实检索/512 截断——冒烟输出逐条可见）

### §4 降级验收 — 全部通过
- [x] 4.1 模型下载失败/不完整 → FileNotFoundError 明确报错不静默（4 项测试：缺失目录/缺失文件/完整通过/HF cache 布局探测）
- [x] 4.2 单模型不可用 → 另一侧 `--skip-*` 独立可跑
- [x] 4.3 全量 pytest 579 全绿保持（新增 12 通过）

### §5 接口兼容 — 全部通过
- [x] 5.1 verify_answer/生产链路不改：git diff 显示 engine/agent/main/eval 改动全部为 import 路径迁移，无逻辑变更
- [x] 5.2 eval/golden_sufficiency.py 未动（git status 无变更，脚本只读 import SUFFICIENCY_DATASET）

### §6 测试验收 — 全部通过
- [x] 6.1 tests/test_compare_factcheck.py 12 项：build_pairs（100 对/标注映射/中文句切/空文档）、指标（完美/全反/部分口径 + kappa 一致/相反）、模型缺失报错（mock，不加载真实模型）
- [x] 6.2 `python -m pytest tests/ -q` — 579 passed / 0 failed

### §7 目录细分验收（WP5）— 6/6 通过（7.4 附条件）
- [x] 7.1 `ai_service/scripts/` 12 个一次性脚本 + main.py 留根
- [x] 7.2 rag 三子包齐全（retrieval 6 + graph 3 + memory 3）
- [x] 7.3 旧路径 import 兼容：sys.modules + 包属性双注册实测同一对象；存量 tests 的 mock.patch 经别名命中真实模块，全量 579 绿证明
- [x] 7.4 新路径迁移 grep 无残留：✅（附条件）生产代码仅 `main.py:100` 一处函数内懒加载残留旧路径（`from rag.embeddings import embedding_service`），经兼容层可用、不阻塞；建议后续模块顺手改新路径并修正 changelog"grep 无残留"表述
- [x] 7.5 根目录脚本从 ai_service 可运行：`python scripts/xxx.py` 与 `python -m scripts.xxx` 双方式实测（sys.path 注入已加）
- [x] 7.6 迁移后全量 pytest 579 全绿

### §8 文档验收 — 2/3 通过 + 1 附条件
- [x] 8.1 changelog.md（全数字复现）/ review-report.md（verdict pass）/ test-report.md（本文件）
- [x] 8.2 memory 三记忆文件：project-context.md（module-050 行）+ agent-activity-log.md（Developer/Reviewer/Tester 三行）+ file-index.md（scripts/rag 子包/对比脚本条目）
- [x] 8.3 ADR-0010 状态更新：（附条件）ADR-0010 文件在主 checkout `specs/adr/0010-hallucination-detection-upgrade.md`（worktree 无此文件，specs/ 未纳入），状态行由主会话合并时追加（changelog §2.2/§6 已书面记录 P0-② 数据验证完成/裁判切换待实施）

## 5. Review Minor 复核（均不阻塞）

1. **main.py:100 残留旧路径懒加载** — 属实，经兼容层可用；全量 579 绿 + 冒烟正常证明无功能影响；已列入 AC-7.4 附条件
2. **ADR-0010 状态未更新** — 属实，文件在主 checkout 非 worktree；changelog 已书面记录，合并时主会话追加
3. **诚实边界第 4 条"512 截断"表述精度** — 属实（predict() 未显式传 max_length）；保守声明无实际危害，建议措辞改为"超出预训练分布"

## 6. 结论

**通过**。全量 579 passed / 0 failed（567 基线 + 12 新增）、`--limit 5` 冒烟双侧模型加载 + 打分 + 指标表 + 诚实边界全部输出、不一致样本与 changelog 全量数字逐对吻合、WP5 迁移（rag 三子包 + scripts/）结构/兼容/可运行性全部验证、存量测试零改动。26 项 AC：24 通过 + 2 附条件（AC-7.4 一处旧路径残留、AC-8.3 ADR-0010 状态行待主会话合并时追加），均非阻塞。
