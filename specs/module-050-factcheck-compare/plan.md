# 功能规格说明书 — Module-050: 幻觉检测模型真实对比（HHEM vs MiniCheck，ADR-0010 数据验证）

> Planner | 2026-08-10

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-050 |
| 模块名称 | HHEM-2.1-Open vs MiniCheck-RoBERTa-Large 真实对比（裁判选型数据验证） |
| 版本号 | 0.50.0-module-050 |
| 优先级 | P0（ADR-0010 P0-② 换专职裁判的前置数据验证；模型选型不能拍脑袋） |
| 预估代码量 | 对比脚本 + 测试，≤ 350 行（模型下载为环境前置，不计代码量） |

---

## 2. 需求

| WP | 内容 | 来源 |
|----|------|------|
| WP1 环境前置 | 下载 HHEM-2.1-Open（`vectara/hallucination_evaluation_model`，~600MB）+ MiniCheck-RoBERTa-Large（`lytang/MiniCheck-RoBERTa-Large`，~1.5GB）到 `ai_service/models/`（走 hf-mirror 镜像，显式 `endpoint` 参数）；装 minicheck（GitHub 源码 `Liyan06/MiniCheck`，**PyPI 的 minicheck 是程序验证工具，勿装错**）+ nltk punkt | ADR-0010 §HHEM 实测参数 + 环境探查结论 |
| WP2 对比脚本 | `eval/compare_factcheck_models.py`：加载 SUFFICIENCY_DATASET 100 条（真实题目 + 注入文档 + 人工标注充分/不充分）→ 构造 (claim=问题, doc) 对 → 两模型各自打分 → 指标表 | ADR-0010 模型选型章节 |
| WP3 指标口径 | 每模型 vs 人工标注：Accuracy / F1 / Precision / Recall；两模型间：Cohen's kappa（一致性≠正确性，ADR 引 Reliability without Validity）+ 二值一致率 + P(support) 平均绝对差 + 不一致样本抽查；每对耗时（CPU 在线可行性） | ADR-0010 §P1-④ 与 §对比口径 |
| WP4 测试 | tests/test_compare_factcheck.py：build_pairs 构造正确性（条数/标注映射/中文句切）、指标计算函数（Accuracy/F1/kappa）、降级（模型缺失时报错清晰） | 对齐既有 eval 测试模式 |
| WP5 目录细分 | 根目录 12 个一次性脚本（backfill_*/create_*/migrate_*/download_model/do_all/reindex/test_m17/test_m18/test_embedding/test_models）移入 `scripts/`；rag/ 按职责拆 retrieval/graph/memory 三子包（import 兼容策略）；main.py 留根目录；eval/ 不动（命令式入口） | 用户要求（文件过多细分） |

### 验收场景

```
场景 1：数据构造
  假设 跑 build_pairs()
  那么 100 对，每对 doc 为中文句切后的拼接文档、claim 为问题、
       label=1 当且仅当 sufficient=True

场景 2：全量对比
  假设 两模型均就绪，python -m eval.compare_factcheck_models
  那么 输出：各自 Accuracy/F1/Prec/Rec + P(support) 中位 +
       Cohen's kappa + 一致率 + 不一致样本前 5 条 + 每对耗时

场景 3：快速冒烟
  假设 python -m eval.compare_factcheck_models --limit 5
  那么 5 条跑通，管线正确（含模型加载）

场景 4：模型缺失
  假设 models/ 下模型不完整
  那么 报错信息指出缺失路径，不静默通过
```

---

## 3. 技术方案

### 3.1 工作包与涉及文件

| WP | 文件 | 操作 |
|----|------|------|
| WP1 | `ai_service/models/hhem-2.1-open/` + `ai_service/models/minicheck-roberta-large/`（hf-mirror 下载，~2GB） | 下载 |
| WP2+3 | `ai_service/eval/compare_factcheck_models.py`（初稿已由 Planner 提供骨架：build_pairs/_pre_chunk 中文句切/HHEM load+score/MiniCheck load+score/指标表/不一致样本） | 完善 |
| WP4 | `ai_service/tests/test_compare_factcheck.py` | 新建 |
| WP5 | ① 新建 `ai_service/scripts/`，移入根目录 12 个一次性脚本（backfill_graph/backfill_search_tokens/create_eval_runs_table/create_metadata_tables/download_model/do_all/migrate_embedding_1024/reindex_knowledge_base/test_embedding/test_m17/test_m18/test_models）；main.py 留根。② rag/ 拆三子包：`rag/retrieval/`（retriever/reranker/chunker/embeddings/text_tokenizer/query_rewrite）+ `rag/graph/`（graph/graph_extractor/graph_store）+ `rag/memory/`（memory/memory_extractor/session_memory）；子包 `__init__.py` 做 import 兼容 re-export（如 `rag/memory/__init__.py: from rag.memory.memory import memory_service`），代码内 `from rag.retriever import` → `from rag.retrieval.retriever import`（grep 全量改，全量 pytest 兜底） | 修改 |
| 文档 | changelog / review-report / test-report + **memory/ 三记忆文件**（project-context/agent-activity-log/file-index，各 agent 写自己的）+ ADR-0010 状态更新 | 修改 |

### 3.3 WP5 目录细分约束（import 兼容红线）

- 先动 rag 子包（高风险），全量 pytest 通过后再移根目录脚本（低风险）；两步分开提交验证
- 兼容策略：旧路径 import（`from rag.memory import X`）经 `__init__.py` re-export 不破；新路径（`from rag.memory.memory import X`）为规范写法——**迁移优先改新路径**，re-export 只兜底存量引用（tests/ 存量用例不动）
- `rag/graph.py` 保留原文件名移入 `rag/graph/` 子包（内部 `from rag.state import RAGState` 不改）；`rag/state.py`/`models.py`/`schemas.py`/`engine.py` 留在 rag/ 根（跨领域共享）
- 根目录脚本移动后运行方式注明：`python -m scripts.backfill_search_tokens` 或 `python scripts/backfill_search_tokens.py`（脚本内部 `from rag...` 依赖 cwd=ai_service 的 sys.path——验证 `python scripts/xxx.py` 从 ai_service 运行可 import；若不行则脚本头加 sys.path 注入，最小改）
- 全量 pytest 567 必须全绿（改 import 后新增/存量用例都要过）；不修改存量测试来掩盖

### 3.2 关键实现约束

- **WP1 下载**：`snapshot_download(..., endpoint="https://hf-mirror.com")` **显式传参**（环境变量在部分调用链不生效，已实测）；`HF_ENDPOINT` env 同时设置双保险；下载脚本放 job tmp 目录，不入仓库
- **WP2 数据**：SUFFICIENCY_DATASET 从 `eval.golden_sufficiency` 导入（不复制）；claim=question（**代理度量**：真实 verify_answer 用答案句子，本题集只有问题——局限如实注明）；doc=两篇文档 content 拼接，**中文句切**（`_pre_chunk` 按 `[。！？；!?]` 切句 + `\n` 连接——MiniCheck 内部 nltk 按英文标点切，中文整块会被吞）
- **WP2 HHEM**：`AutoModelForSequenceClassification` + `AutoTokenizer`，输入 `f"premise: {doc} hypothesis: {claim}"`，softmax 取 label 1 概率；`max_length=512` 截断
- **WP2 MiniCheck**：`minicheck.minicheck.MiniCheck(model_name="roberta-large", cache_dir=models/minicheck-roberta-large)`，`score(docs, claims)` 返回 `(pred_label, max_support_prob, used_chunk, support_prob_per_chunk)`，取 max_support_prob；`sys.path.insert` minicheck 源码目录（`<home>\AppData\Local\Temp\minicheck-src`）——**不要 pip 安装**（PyPI 包是程序验证工具；GitHub 包 pip 构建在 py3.11 失败）
- **WP3 指标**：阈值 0.5 二值化；`cohen_kappa_score`（sklearn 已有依赖）；F1 用 macro/二元 supported 类（正类=supported，漏抓幻觉比误判严重，重点看 F1/Recall）；不一致样本打印 doc 标题+claim 前 40 字+两模型分数
- **WP4 测试**：不加载真实模型（mock 分数数组）——只测数据构造与指标函数，模型加载留给冒烟；对齐 tests 现有模式（纯单元、不打真实 DB）
- **诚实边界**（写进脚本输出与报告）：模型英文训练，中文输入为跨语言泛化表现；claim=问题非答案句子（代理度量）；HHEM 512 token 截断；100 条为注入文档非真实检索结果（与 module-044 同源）

### 3.3 降级

| 场景 | 处理 |
|------|------|
| 模型下载失败/不完整 | 脚本报错指出缺失路径（`--limit` 冒烟前置检查）；如实标注"待环境"不伪造数字 |
| 单模型加载失败 | `--skip-hhem` / `--skip-minicheck` 可单独跑另一侧 |
| 内存不足（两模型同时加载 ~2GB） | 依次加载：先 MiniCheck 推理完再加载 HHEM（脚本内顺序加载不共存） |
| nltk punkt 缺失 | MiniCheck 内部 sent_tokenize 会崩——`_pre_chunk` 已按句切好，且 punkt 数据放 `~/nltk_data/tokenizers/punkt`（已下载） |

---

## 4. 依赖

- ADR-0010（选型依据）、module-044 SUFFICIENCY_DATASET（数据源）、module-038/047 eval 模式（sklearn 指标）
- 环境：minicheck（GitHub 源码）、nltk+punkt、transformers 5.14.1、torch 2.13.0+cpu、hf-mirror 可达（huggingface.co 502 不可达）

## 5. 已知边界

- 本模块**只做数据验证**（裁判对比），不改 `verify_answer` 生产代码——换裁判是 ADR-0010 P0-②，数据结论出来后才实施（后续模块）
- 真实答案句子级验证（claim=答案句子）不在本题集能力内——若结论支持 MiniCheck，P0-② 实施时用真实答案逐句跑
- golden 112 题真实检索文档（DB）不可用，用 SUFFICIENCY_DATASET 注入文档代替（同 module-047 图谱消融"待环境"哲学）
- 全量 pytest 567 全绿保持（本模块新增测试 +N）
