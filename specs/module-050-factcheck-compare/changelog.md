# Changelog — Module-050: 幻觉检测模型真实对比（HHEM vs MiniCheck，ADR-0010 数据验证）

> Developer | 2026-08-10/11
> 全量基线 567 passed → 新增 12 tests → **579 passed / 0 failed**

---

## 1. WP1 环境前置（模型下载 + 加载验证）

### 1.1 网络环境实测（与 Planner 探查一致并补充）

- huggingface.co **不可达**：不仅 502，本机 hosts 还把 `huggingface.co` 映射到 `127.0.0.1:443`
  （本地 443 有服务监听），Python httpx/urllib 直接请求全部失败。
- hf-mirror.com **可达但行为分客户端**：curl 正常（API 200 / resolve 307→resolve-cache 200），
  Python httpx 对 `/api/` 路径返回 **308 重定向到 huggingface.co**（部分调用链缓存 HIT 才 200）。
  → **结论：Python 侧 huggingface_hub 下载不可用，改用 curl 直下文件**（写入下载脚本不入仓库）。

### 1.2 模型下载（curl + hf-mirror resolve 直链）

| 模型 | 仓库 | 文件 | 大小 | 落盘位置 |
|------|------|------|------|----------|
| HHEM-2.1-Open | vectara/hallucination_evaluation_model | model.safetensors + config/modeling/configuration/README | 438,535,352 B (~418MB) | `models/hhem-2.1-open/` |
| MiniCheck-RoBERTa-Large | lytang/MiniCheck-RoBERTa-Large | pytorch_model.bin + tokenizer 全家桶 | 1,421,577,710 B (~1.36GB) | `models/minicheck-roberta-large/` |
| flan-t5-base（HHEM 基础模型 tokenizer） | google/flan-t5-base | config/tokenizer/spiece.model | ~3.2MB | `models/flan-t5-base/` |

- HHEM 下载中断过一次（curl 18，166MB 处断流）→ `-C -` 断点续传完成。
- 中途补装 `accelerate 1.14.0`（MiniCheck 的 `device_map="auto"` 需要）。

### 1.3 加载验证（两模型均离线可加载，分数有基准对照）

**MiniCheck**（transformers 5.x + CPU 适配）：
- 按 HF cache 布局落盘 `models--lytang--MiniCheck-RoBERTa-Large/snapshots/<commit>/` + `refs/main`
  （注意：`refs/main` 不能带 BOM——PowerShell `Set-Content -Encoding utf8` 写入的 BOM 会被
  huggingface_hub `open().read()` 用 GBK 解码炸掉，改用 `[IO.File]::WriteAllText` UTF8 无 BOM）。
- `HF_HUB_OFFLINE=1` + `cache_dir=models/minicheck-roberta-large` 离线加载（snapshot_download
  对不可达 hub 自动回退 cache，见 huggingface_hub `_snapshot_download.py` 的 HfHubHTTPError 分支）。
- **transformers 5.x 兼容坑**：MiniCheck 源码硬编码 `device_map="auto"`，CPU 上 accelerate
  磁盘卸载报错 → 加载前剥掉该参数（脚本内 monkeypatch `from_pretrained`）。
- 冒烟验证：G1 支持对 `max_support_prob≈0.29-0.33`、英文 README 参考对 `0.098/0.365/0.054`，
  分数量纲与模型行为吻合（中文整体压缩、英文可判别）。

**HHEM-2.1-Open**（自定义远程代码 + transformers 5.x 兼容）：
- 官方 `AutoModelForSequenceClassification.from_pretrained(trust_remote_code=True)` 在 5.x 崩
  （`all_tied_weights_keys` 属性缺失 + `t5.transformer.shared.weight` 与 5.x 的
  `t5.transformer.encoder.embed_tokens.weight` 绑定键不匹配）→ 改走：
  `get_class_from_dynamic_module` 加载自定义类 + `safetensors` 手动 load_state_dict
  （先展开 `embed_tokens = shared` 键）+ 本地 `config.json` 补 `foundation=models/flan-t5-base`。
- **分数与官方 README 参考值逐一吻合**：`[0.0111, 0.6474, 0.1290, 0.8969, 0.1846, 0.0050, 0.0543]`
  全对 → 权重加载正确性有外部基准背书。
- 注意：HHEM-2.1-Open 是 **T5 架构 + 自带 prompt 模板**（`<pad> Determine if the hypothesis
  is true given the premise?...`），必须走官方 `model.predict(pairs)`（内部拼 prompt），
  **不能**用骨架里 `"premise: {doc} hypothesis: {claim}"` 的老式拼接（那是 HHEM-2.1 时代的格式）。

### 1.4 下载脚本处置

- `download_factcheck_models.py`（snapshot_download + endpoint=hf-mirror）已实测 **不可用**
  （Python httpx 308 → huggingface.co），实际下载用 curl resolve 直链；脚本不入仓库。

---

## 2. WP2+WP3 对比脚本

文件：`ai_service/eval/compare_factcheck_models.py`（在 Planner 骨架上完善，未推倒重写）

| 项 | 实现 |
|----|------|
| 数据构造 | `build_pairs()`：SUFFICIENCY_DATASET 100 条 → (doc=两篇文档中文句切拼接, claim=问题, label=充分性) |
| 中文句切 | `_pre_chunk`：按 `[。！？；!?]` 切句 + `\n` 连接（MiniCheck 内部 nltk 英文标点切，中文预切防吞句） |
| HHEM 打分 | 官方 `predict(pairs)`（内部 prompt 模板 + softmax class 1 = consistent），离线加载 + embed_tokens 展开 |
| MiniCheck 打分 | `score()` 取 `max_support_prob`，chunk_size=400（官方默认），离线 + device_map 剥离 |
| 指标 | 每模型 vs 标注：Accuracy/F1/Precision/Recall（正类=supported）+ P(support) 中位 + 每对耗时；两模型间 Cohen's kappa + 二值一致率 + P 平均绝对差 + 不一致样本前 5 |
| 降级 | `--limit N` 冒烟；`--skip-hhem` / `--skip-minicheck` 单侧；模型缺失报错指出缺失路径（`_require_model` 双布局探测） |
| 顺序加载 | MiniCheck 先推理完释放（`_mc = None`）再加载 HHEM，避免两模型同时驻留内存 |

### 2.1 全量对比实测结果（100 对：supported 50 / unsupported 50）

```
模型                  Accuracy      F1   Prec    Rec  P(support)中位     s/对
MiniCheck             0.5100  0.0392  1.000  0.020         0.162   2.855
HHEM                  0.7700  0.7527  0.814  0.700         0.359   0.364

-- 两模型对比 --
Cohen's kappa: 0.0264（>0.7 视为可互信；一致性≠正确性）
二值一致率: 58.0%
P(support) 平均绝对差: 0.2392
不一致样本 42 条（前 5 条）:
  [1] 标注=support doc=5-Kafka消息可靠性与高吞吐设计_2026-07-15...
      claim=Kafka的ISR机制是如何保证消息可靠性的？...
      MiniCheck=0.294 HHEM=0.907
  [3] 标注=support doc=16-volatile与Java内存模型JMM_2026-0...
      claim=volatile关键字的作用和实现原理是什么？...
      MiniCheck=0.326 HHEM=0.680
  [6] 标注=support doc=2-ZGC超低停顿垃圾收集器原理_2026-07-12...
      claim=ZGC的特点和适用场景是什么？...
      MiniCheck=0.406 HHEM=0.805
  [7] 标注=support doc=3-CMS垃圾收集器原理与缺陷分析_2026-07-13...
      claim=CMS垃圾收集器的原理和缺陷是什么？...
      MiniCheck=0.219 HHEM=0.667
  [8] 标注=support doc=6-Java线程池ThreadPoolExecutor核心参...
      claim=ThreadPoolExecutor的核心参数和工作流程是什么？...
      MiniCheck=0.344 HHEM=0.834
```

冒烟（--limit 5）与全量管线一致（MiniCheck ~4.4-5.2s/对、HHEM ~0.4s/对）。

### 2.2 结论解读（供 ADR-0010 P0-② 裁判选型）

1. **HHEM-2.1-Open 显著优于 MiniCheck-RoBERTa-Large（中文场景）**：
   - Accuracy 0.77 vs 0.51；F1 0.75 vs 0.04（正类=supported）。
   - MiniCheck **Recall 0.020**：50 条 supported 只抓回 1 条——中文输入下几乎全判 unsupported
     （P(support) 中位 0.162 且整体压缩），漏抓幻觉语义上"全漏"。
   - MiniCheck 的 Accuracy 0.51 靠 50 条 unsupported 全对撑起（Prec 1.000 是"从不正判"的伪高），
     **对 supported 判定完全失效**——这正是 ADR 引的 Reliability without Validity 反例。
2. **两模型一致性极低（kappa 0.0264，一致率 58%）**：MiniCheck 的分数几乎不带中文语义信息，
   与 HHEM 的判定趋近无关——进一步佐证 MiniCheck 中文退化而非"保守但有用"。
3. **CPU 在线可行性**：HHEM 0.364 s/对 vs MiniCheck 2.855 s/对（~8 倍差距）。
   HHEM 在 CPU 上可作在线裁判；MiniCheck 即使忽略准确度也不适合在线。
4. **数据结论倾向**：中文 RAG 幻觉检测裁判选 **HHEM-2.1-Open**（或同族 T5-based），
   MiniCheck-RoBERTa-Large 需英文/双语能力才可用。最终选型与 P0-② 实施由主会话/ADR 决策。

### 2.3 诚实边界（脚本输出与本文档同步声明）

- 两模型均为英文训练数据，中文输入属**跨语言泛化表现**；绝对分数会偏低，对比结论看相对差异。
- claim 用**问题代答句**（本题集只有问题，真实 verify_answer 用答案句子）——代理度量，
  结论需后续用真实答案句子复核。
- 文档为**注入的代表性文档**（相关/不相关），非真实检索结果——同 module-044 数据源；
  真实检索文档受 topic 漂移影响可能更难判。
- HHEM 预训练序列长度有限（T5 512 token），`predict()` 未设截断，超长输入超出分布范围的表现未验证（本题集文档最长 528 字符，影响有限）。
- MiniCheck 中文退化是本实验的**核心发现**而非 bug：英文参考对判别正常
  （0.098 不支持 / 0.365 边缘 / 0.054 不支持），中文同类对全部压缩到 0.5 以下。

---

## 3. WP4 测试

文件：`ai_service/tests/test_compare_factcheck.py`（12 项，全部通过）

| 类 | 覆盖 |
|----|------|
| TestBuildPairs | 100 对 / 同一问题充分+不充分各一条映射 [0,1] / claim=问题 doc=拼接 / 中文句切（。？！；） |
| TestMetrics | Accuracy/F1/Precision/Recall 完美与部分口径 / 正类=supported / cohen_kappa 一致与相反 |
| TestRequireModel | 缺失目录/缺失文件报错含路径 / 完整目录通过 / HF cache 布局（snapshots/<commit>/）探测 |

对齐既有 eval 测试模式：纯单元、不加载真实模型（模型加载留给 `--limit` 冒烟）、不打真实 DB。

---

## 4. WP5 目录细分

### 4.1 目标结构

```
ai_service/
  main.py                  # 留根目录（FastAPI 入口）
  scripts/                 # 12 个一次性脚本（backfill_*/create_*/migrate_*/download_model/
                           #   do_all/reindex_knowledge_base/test_embedding/test_m17/
                           #   test_m18/test_models）——命令式入口，从 ai_service 可运行
  rag/
    state.py / models.py / schemas.py / engine.py / migrate_parent_child.py   # 跨领域共享，留根
    retrieval/   retriever.py / reranker.py / chunker.py / embeddings.py
                 text_tokenizer.py / query_rewrite.py
    graph/       graph.py / graph_extractor.py / graph_store.py
    memory/      memory.py / memory_extractor.py / session_memory.py
  eval/          # 不动（命令式入口，含 compare_factcheck_models.py）
```

### 4.2 import 兼容策略（红线：存量 tests 用例不动 + mock.patch 不破）

- **关键约束**：tests 大量 `mock.patch("rag.memory.hybrid_retriever")`、
  `mock.patch("rag.graph_store.async_session_factory")` 等——mock.patch 按字符串解析
  `rag.memory` 模块对象再打属性。**re-export 只能保证 `from rag.memory import X` 可导入，
  不能让 patch 打到真实模块**。因此旧路径必须注册为**同一模块对象**（sys.modules 别名 +
  rag 包属性双注册，见 `rag/__init__.py`）。
- 实现：`rag/__init__.py` 主动导入三个子包，并把 12 个旧模块名
  （rag.retriever / rag.reranker / ... / rag.memory / rag.memory_extractor / rag.session_memory）
  在 `sys.modules` 和包属性上指向新模块对象。注意**不能用 `retrieval.xxx` 属性取模块**
  （子包 `__init__` 的 `import *` 会把同名单例如 `reranker = CrossEncoderReranker(...)`
  覆盖为属性）——一律走 `sys.modules["rag.retrieval.xxx"]`。
- 生产代码（rag/、agent/、eval/、scripts/、main.py）一律迁移到新路径
  （`from rag.retrieval.retriever import ...`）；grep 验证无残留旧引用（仅 `rag/__init__.py`
  兼容层注释命中）。tests/ 保持旧路径不动（经别名命中同一对象）。

### 4.3 脚本移动

- 12 个一次性脚本移入 `scripts/`（`__init__.py` 空文件使其可 `python -m scripts.xxx`）。
- 运行方式验证：`python scripts/backfill_search_tokens.py --dry-run` 与
  `python -m scripts.backfill_search_tokens --dry-run` 均从 ai_service 可运行
  （脚本头加 `sys.path.insert(0, 父目录)`——`python scripts/xxx.py` 时 sys.path[0]=scripts/，
  不加会 `ModuleNotFoundError: No module named 'src'`；test_m17.py 原本的 `sys.path.insert(0,'.')`
  一并改为 `__file__` 定位）。test_m17 全项 PASS（5 项全过）。

### 4.4 WP5 验证

- 子包迁移后：`python -m pytest tests/ -q` → **579 passed / 0 failed**（含新增 12）。
- 脚本移动后复跑：**579 passed / 0 failed**。
- 别名/mock 兼容专项验证：`mock.patch("rag.memory.hybrid_retriever")`、
  `mock.patch("rag.retriever.hybrid_retriever.retrieve")`、
  `mock.patch("rag.memory_extractor.LLMFactory.get_client")`、
  `mock.patch("rag.graph_store.async_session_factory")` 均命中真实模块（脚本实测断言通过）。
- **.gitignore 修复**：原规则 `memory/`（未锚定）会吞掉新目录 `ai_service/rag/memory/`
  （git check-ignore 实测命中——整个子包会被漏提交）→ 改为锚定 `/memory/`（只忽略根目录
  共享记忆库；其已跟踪文件不受影响，git ls-files 验证仍在跟踪）。顺带移除失效的
  `ai_service/test_m17.py` 规则（文件已移入 scripts/，新路径不再命中）。
- 未修改任何存量测试来掩盖。

### 4.5 测试顺序说明（非本模块缺陷）

`pytest tests/test_query_rewrite.py tests/test_memory_extractor.py` 子集组合存在 5 项
既有失败（test_query_rewrite 的 mock 泄漏到 test_memory_extractor）——在**基线提交
db9b6d7（本模块改动前）原样复现**（独立 detached worktree 实测 5 failed / 68 passed 完全一致），
与目录细分无关。规范命令 `python -m pytest tests/ -q`（验收口径）全量 **579 passed / 0 failed**。

---

## 5. 变更文件清单

| 文件 | 操作 |
|------|------|
| `eval/compare_factcheck_models.py` | 完善（离线加载/device_map 剥离/embed_tokens 展开/指标表/诚实边界） |
| `tests/test_compare_factcheck.py` | 新建（12 tests） |
| `rag/__init__.py` | 改（子包导入 + 旧路径 sys.modules/属性双注册兼容层） |
| `rag/retrieval/{__init__,retriever,reranker,chunker,embeddings,text_tokenizer,query_rewrite}.py` | 移动/import 迁移 |
| `rag/graph/{__init__,graph,graph_extractor,graph_store}.py` | 移动/import 迁移 |
| `rag/memory/{__init__,memory,memory_extractor,session_memory}.py` | 移动/import 迁移 |
| `rag/engine.py` | import 迁移到新路径 |
| `agent/{tool_registry,intent_classifier,router}.py` | import 迁移（router 含一处函数内懒加载） |
| `main.py` | import 迁移 |
| `eval/{golden_memory,golden_query_rewrite,golden_retrieval,threshold_scan,train_sufficiency_classifier}.py` | import 迁移 |
| `scripts/`（12 脚本 + `__init__.py`） | 新建目录/移动/sys.path 注入/import 迁移 |
| `models/hhem-2.1-open/config.json` | 本地补 `foundation=models/flan-t5-base`（gitignored 环境文件） |
| `models/{hhem-2.1-open,minicheck-roberta-large,flan-t5-base}/` | 模型下载（gitignored） |
| 环境 | pip 补装 `accelerate` |

## 6. 已知边界 / 待办

- MiniCheck 中文退化结论基于 100 条注入文档集；真实检索文档（golden 112 题 DB）不在本模块能力内
  （同 module-047 图谱消融"待环境"哲学）。
- P0-② 裁判切换（verify_answer 接入 HHEM）未实施——本模块只做数据验证，实施留后续模块。
- 若结论被采纳换 HHEM，真实答案句子级验证（claim=答案句子）需在实施时逐句跑。

---

## 7. Minor 修复记录（Review 后）

- Minor-1（fixed）：`main.py` 启动预热懒加载残留旧路径 `from rag.embeddings import ...` → 迁移到
  `from rag.retrieval.embeddings import embedding_service`；grep 复核生产代码（rag/agent/eval/scripts/main.py）
  无残留旧路径引用（`rag/retrieval/text_tokenizer.py` 模块 docstring 使用示例一并改为新路径；
  剩余命中仅为兼容层 `__init__.py` 文档注释与 tests/ 的旧路径导入——后者为兼容策略红线，有意保留）。
- Minor-2（fixed）：`eval/compare_factcheck_models.py` 诚实边界第 4 条与实际代码不符——官方
  `predict()` 调 tokenizer 未传 `max_length`/`truncation`，不存在"截断"行为 → 改为
  "预训练序列长度有限（T5 512 token），超长输入超出分布范围的表现未验证"；本 changelog 2.3 节同步。
