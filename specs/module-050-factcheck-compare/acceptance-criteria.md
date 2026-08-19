# 验收标准 — Module-050: 幻觉检测模型真实对比（HHEM vs MiniCheck）

> 图例：📋 功能 / 📦 降级 / 🔌 接口 / 🧪 测试 / 📝 文档

## 1. 功能验收（WP1 环境前置）

- [ ] 📋 HHEM-2.1-Open 下载到 `models/hhem-2.1-open/`（config.json + 权重文件完整可加载）
- [ ] 📋 MiniCheck-RoBERTa-Large 下载到 `models/minicheck-roberta-large/`（完整可加载）
- [ ] 📋 minicheck 用 GitHub 源码（非 PyPI 程序验证工具）；nltk punkt 可用

## 2. 功能验收（WP2 对比脚本）

- [ ] 📋 `eval/compare_factcheck_models.py` 存在，可 `--limit 5` 冒烟跑通（两模型加载 + 打分）
- [ ] 📋 build_pairs 从 SUFFICIENCY_DATASET 构造 100 对（claim=问题、doc=中文句切拼接、label=人工标注）
- [ ] 📋 全量运行输出：两模型各自 Accuracy/F1/Prec/Rec/P(support) 中位 + Cohen's kappa + 二值一致率 + P 平均绝对差 + 不一致样本前 5 条 + 每对耗时
- [ ] 📋 `--skip-hhem` / `--skip-minicheck` 单侧可跑；模型缺失报错清晰（指出路径）

## 3. 功能验收（WP3 指标口径）

- [ ] 📋 指标与 ADR-0010 口径一致（F1 正类=supported，漏抓比误判严重）
- [ ] 📋 两模型间 Cohen's kappa 计算正确（sklearn cohen_kappa_score）
- [ ] 📋 输出含诚实边界声明（中文跨语言、claim=问题代理度量、注入文档非真实检索）

## 4. 降级验收

- [ ] 📦 模型下载失败/不完整 → 明确报错不静默通过，如实标注不伪造数字
- [ ] 📦 单模型不可用 → 另一侧可独立跑
- [ ] 📦 全量 pytest 567 全绿保持（新增测试 +N）

## 5. 接口兼容

- [ ] 🔌 不改 verify_answer / 生产链路（本模块只做数据验证）
- [ ] 🔌 eval/golden_sufficiency.py 不动（import 只读）

## 6. 测试验收

- [ ] 🧪 tests/test_compare_factcheck.py：build_pairs（100 对/标注映射/中文句切）、指标函数（Accuracy/F1/kappa）、模型缺失报错（mock）
- [ ] 🧪 python -m pytest tests/ -q — 全量 567+ 全绿

## 7. 目录细分验收（WP5）

- [ ] 📋 `ai_service/scripts/` 存在，12 个一次性脚本已移入（main.py 留在根目录）
- [ ] 📋 rag/ 拆三子包：retrieval/（retriever/reranker/chunker/embeddings/text_tokenizer/query_rewrite）+ graph/（graph/graph_extractor/graph_store）+ memory/（memory/memory_extractor/session_memory）
- [ ] 📋 子包 `__init__.py` import 兼容：旧路径 `from rag.memory import X` 不破（存量 tests 用例不动）
- [ ] 📋 代码内 import 迁移到新路径（grep 验证无残留旧引用，除 re-export 兜底）
- [ ] 📋 根目录脚本移动后从 ai_service 可运行（或脚本头已加 sys.path 注入，最小改）
- [ ] 📋 全量 pytest 567 全绿（迁移后复跑）

## 8. 文档验收

- [ ] 📝 changelog.md / review-report.md / test-report.md（含全部实测数字）
- [ ] 📝 memory/ 三记忆文件更新：Developer 写 project-context.md（追加 module-050 记录）+ agent-activity-log.md（本模块活动）；Reviewer/Tester 各追加自己的 activity 行；file-index.md 由 Developer 重扫补全
- [ ] 📝 ADR-0010 状态更新（P0-② 数据验证完成/待实施裁判切换）
