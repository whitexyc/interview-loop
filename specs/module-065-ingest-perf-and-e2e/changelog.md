# Module-065 变更日志 — 入库性能验证 + E2E 复测 + 公开基准 + minor 清理

> 实施：Developer（2026-08-15）| 计划：`plan.md` | 验收：`acceptance-criteria.md`
> 范围：能本地闭环的合并批（WP1 探路证伪固化 / WP2 E2E 复测 / WP3 公开基准首跑 /
> WP4 module-064 两 minor）。全量 pytest 基线 1036/0（module-064 验收数）。

## 一、WP1 写入侧嵌入性能验证（探路证伪 → 可复跑验证脚本）

**背景**：module-064 真实文档插入实测暴露 CSV 大数据集入库慢（7231 块 50 分钟）；
2026-08-15 探路实测两条优化路径均已证伪。本 WP 把探路结论固化为可复跑脚本
+ 文档记录（防未来重复踩坑），**生产代码零改动**（无可行优化，不做投机改动）。

**产出**：`ai_service/eval/benchmarks/benchmark_embed_write.py`（新建，可复跑；
同 2026-08-15 探路口径：循环 vs List 批量 10/50/200 + 串行 vs 多进程 2/4×200 条；
`--quick` 冒烟 / `--no-mp` 跳进程档）。

**本机实测（2026-08-15，bge-m3 Q8 GGUF 605MB 本地单实例）**：

| 档位 | 循环 | 批量（List[str]） | 倍率 |
|------|------|-------------------|------|
| 10 条 | 2.05s（205ms/条） | 2.03s（203ms/条） | 1.0x |
| 50 条 | 9.59s（192ms/条） | 10.19s（204ms/条） | 0.9x |
| 200 条 | 42.29s（211ms/条） | 40.92s（205ms/条） | 1.0x |

| 档位（200 条） | 耗时 | ms/条 | 相对串行 |
|----------------|------|-------|----------|
| 串行 | 34.60s | 173 | 1.0x |
| 多进程 2 | 88.10s | 441 | **0.4x** |
| 多进程 4 | 99.73s | 499 | **0.3x** |

> 注：两表中"循环 200 条"（表一 42.29s / 表二串行 34.60s）为**两次独立测量**
> （批量对比段与多进程段各自计时），绝对值差异来自测量时段 CPU 状态/热状态
> 波动，非同一测量矛盾；同段内相对比较（倍率）稳定。

**结论（与探路口径一致）**：① 批量无稳定加速（探路 0.8-1.3x / 本机安静态
0.9-1.0x；Reviewer 争用态复跑 1.6-2.0x 为瞬时现象不可重现——llama.cpp 内部
非真 batch decode，倍率随文本长度与 CPU 争用波动，无稳定收益）；② 多进程
负优化（Windows spawn 重 import + 内存带宽竞争）；③ 写入吞吐 ~110-210ms/块
（随文本长度波动：探路短文本 110-160 / 复测 141 字符 173-211）为 bge-m3 Q8
单核推理**固有成本**，无廉价优化路径。METRICS.md 待办⑥ 已更新为"实测证伪"
结论（见 METRICS.md）。

## 二、WP2 E2E 复测（reranker 优化 P0-P3 落地值）

**背景**：reranker 优化批（int8 量化 + 粗筛 + 200 截断 + 启动预热）已提交但服务
未重启，E2E 未复测（优化前 2026-08-14 实测 TTFT 25.3s / 完整 28.1s，rerank
8.5-13.5s）。

**实施**：
- 重启 AI 服务（uvicorn 8001 后台常驻，复用项目启动方式 `python -m uvicorn
  main:app --host 0.0.0.0 --port 8001`）；启动日志确认 HHEM 预热 + **reranker
  int8 量化 + 预热**（P0/P3 生效）。
- 复用探路脚本 `e2e_latency_probe.py` 测"什么是G1 GC" 6 次（同口径）。
- 真实文档生产链路命中验证 + request_logs 分段复核。

**实测结果（6 次，"什么是G1 GC"，优化后）**：

| 指标 | 优化前（2026-08-14） | 优化后（2026-08-15） | 变化 |
|------|---------------------|---------------------|------|
| TTFT 平均 / 中位 / 最小 / 最大 | 25.3 / 23.0 / 19.8 / 38.3 s | **15.4 / 14.0 / 10.2 / 20.9 s** | **-39%** |
| 完整 平均 / 中位 / 最小 / 最大 | 28.1 / 25.8 / 22.6 / 40.9 s | **18.9 / 16.8 / 13.1 / 28.0 s** | **-33%** |

- 实测 TTFT 15.4s 落在优化批预估区间（15-19s）。
- **request_logs 分段（6 次）**：rerank **1.9-3.3s（平均 ~2.4s）**（优化前
  8.5-13.5s，~4-5x 提速）；图谱 0.9-1.4s；反思 1.4-2.6s；生成 4.5-14s（LLM
  外部波动）。剩余大头 = LLM 生成 + 图谱。
- **真实文档生产链路命中**："What are the three paradigms of RAG?" 走完整
  chat → HTTP 200 / message=ok / 答案 1022 字符引用 [2][5] / **5 sources 中 3 个
  为 rag_survey.pdf 块**（id=8282/8284/8304，标题 `[实测]rag_survey.pdf > ...`）
  ——RRF → 粗筛 → rerank 后论文块仍命中，P0-P3 优化未牺牲真实文档召回。
- 6 次探针全部 done 事件带 verify_task_id（verify 异步后台不阻塞主链路，
  module-060 行为保持）。

**降级声明**：本次 6 次无 deepseek 429/网络故障（生成段 4.5-14s 波动为正常
外部抖动）；服务一次启动成功，无端口占用。

## 三、WP3 公开基准检索评测（测通用泛化，首跑）

**背景**：自建 golden 集（112 题）"自己考自己"存在乐观偏差（Hit@5 0.9905），
用公开标准数据集测 bge-m3 通用泛化。**数据源探测（2026-08-15）**：
huggingface.co **502 不可达**（与 module-050 一致）、hf-mirror.com **可达**、
ModelScope 可达 → 下载走 hf-mirror 直链 resolve URL（qrels 首次下载 502 为
瞬时抖动，重试成功）。

**产出**：`ai_service/eval/benchmarks/benchmark_public_retrieval.py`（新建）：
数据下载（缓存 eval/datasets/public/，gitignored）+ 加载适配（BEIR nfcorpus
corpus/queries/test.tsv；C-MTEB EcomRetrieval + qrels）+ bge-m3 嵌入 + 余弦
暴力检索 + Hit@5 / MRR / nDCG@10（trec 口径：nDCG gain=qrels 分数）+ eval_runs
落库（eval_type='public_retrieval'，失败仅警告）。`--corpus-sample` 固定种子
抽样（全量 0）/ `--limit` 冒烟 / `--no-save`。

**环境约束（如实声明）**：C-MTEB 各检索子集 corpus 均 ~10 万篇，本机 CPU
单篇嵌入 1.7-2.2s（~1,800 字符长文），全量嵌入 ~2 小时不现实 → 抽样代理口径。
nfcorpus 全量 3,633 篇同样 ~2 小时 → 抽样 1,200 篇。

**实测结果（2026-08-15）**：

| 数据集 | 语种 | 口径 | 有效查询（跳过） | Hit@5 | MRR | nDCG@10 |
|--------|------|------|------------------|-------|-----|---------|
| C-MTEB EcomRetrieval | 中文 | corpus 抽样 3,000/100,902（固定种子） | 26（跳过 974） | 0.9231 | 0.9231 | 0.9231 |
| BEIR nfcorpus | 英文 | corpus 抽样 1,200/3,633（固定种子） | 292（跳过 31） | 0.5685 | 0.4630 | 0.4853 |

eval_runs 已落库（ecom id=44 / nfcorpus id=45，eval_type='public_retrieval'；
**最终口径 = 余弦（L2 归一化）+ 真跳过语义**，见 §九/§十口径演进）。

> **口径演进（三轮修正，旧记录已落库标注，各 id 口径不同不可直接比）**：
> id=40/41 = 点积口径（未 L2 归一化，Review MAJOR-1）；id=42/43 = 余弦但
> 全查询计入（相关文档不在抽样内的查询按 0 分稀释，Tester 修复轮）；
> **id=44/45 = 余弦 + 真跳过（本表为准）**。

**解读（诚实）**：
- **ecom-zh**：1,000 查询中仅 26 条（2.6%）的相关文档落在 3% 抽样内（qrels
  每查询仅 1 条相关，非假设的 ~5 条）——**有效查询仅 26 条，统计证据薄**；
  该 26 条上 0.9231 说明"答案在 corpus 内时 bge-m3 找回能力高"，但**不能与
  官方 leaderboard 直接比**（抽样 + 小基数双代理）。
- **nfcorpus**：292/323 有效（跳过 31，即 9.6% 查询的相关文档全部落在抽样
  外），nDCG@10 0.4853 **落在官方全量口径 bge-m3 参考值（~0.45-0.5）区间内**
  ——抽样代理下与官方水平一致，是三个数字中最有信息量的。
- 两公开集与自建集（Hit@5 0.9905）的差异（ecom 0.92 基数薄 / nfcorpus
  0.57）印证自建集"自己考自己"的乐观偏差存在（语料/口径不同：自建集 RRF
  三通道+重排且文档即源文档，公开集单通道余弦暴力检索，仅方向性对比）；
  精确泛化水平需全量 corpus（GPU/集群 `--corpus-sample 0` 可跑，脚本已就绪）。

## 四、WP4 module-064 minor 清理

**minor-1（代码）**：`find_semantic_duplicate` 候选查询过滤
`Document.is_canonical.is_(True)`（非 canonical 重复副本虽存文档级 embedding，
但检索侧已抑制只出 canonical——候选比对语义对齐，防低概率过度折叠进簇）。
新增单测 `test_semantic_duplicate_query_filters_non_canonical`（编译捕获断言
`is_canonical IS true` 真实存在于查询，对齐既有 memory 排除测试模式）；
**存量测试零改动**，test_document_dedup.py 15 → 16 项。

**minor-2（文档口径）**：三处测试数口径统一修正为 **85 / 1036**（66/64 系
module-064 交付快照，Review 修复轮 +19 项后未回写）：
- `memory/project-context.md` module-064 行：66 项 → 85 项（含补 test_document_
  ingest 5 + test_document_image 18 明细）+ 1017/0 → 1036/0；
- `memory/project-context.md` ADR-0014 状态行：64 新增 → 85 新增（1036/0）；
- `CONTEXT.md` module-064 执行简报行：64 新增 → 85 新增（1036/0，**段内修订
  不删行**，附更正说明，遵守 CONTEXT.md 只增不删）。

## 五、测试

- 新增单测 **1 项**（test_document_dedup.py `test_semantic_duplicate_query_
  filters_non_canonical`，SQL 编译捕获断言）。
- 单文件验证：test_document_dedup.py **16/16 通过**。
- 全量 pytest：**1037 passed / 0 failed（167.24s）= 1036 基线 + 1 新增**，
  存量零改动，42 warnings 与基线同源（Redis setex 弃用等，非本模块引入）。
- WP1/WP3 脚本运行验证：benchmark_embed_write.py 全档位输出与探路口径一致；
  benchmark_public_retrieval.py ecom-zh + nfcorpus 真实跑通三轮（点积 id=40/41
  → 余弦 id=42/43 → 余弦+真跳过 id=44/45，口径演进见 §九/§十，最终以 id=44/45 为准）。

## 六、实现决策与取舍

1. **WP1 不做生产优化**（关键决策）：探路已证伪批量/多进程两条路径，按
   "简单至上 + 不做投机改动"原则生产代码零改动，只固化验证脚本 + 文档。
2. **WP3 抽样代理口径**（诚实决策）：全量 corpus 本机 ~2 小时不可行 → 固定
   种子抽样 + 如实声明"不可直接比"；脚本保留 `--corpus-sample 0` 全量入口
   （环境升级后可复跑补全量数字）。
3. **WP4 minor-1 只加 SQL 过滤**（精准修改）：不加 Python 层双保险、不改
   document_ingest 非 canonical 不存向量（超出需求；Reviewer 第 2 轮建议的
   两个方案取改动最小者）。
4. **数据落 gitignored 缓存**：公开数据可重下（url 固定），不提交二进制。

## 七、已知边界与诚实声明

- WP1 是**证伪记录**：数字只说明"这两条路走不通"，不说明"没有其他优化"
  （未来方向：GPU 推理 / 批量服务化，超出本机环境）。
- WP3 受**数据源可达性与算力制约**：ecom 数字受抽样支配（已声明）；nfcorpus
  同口径；全量数字待 GPU/集群环境补跑（脚本入口就绪）。
- WP2 受 **LLM 外部抖动**制约：生成段 4.5-14s 波动；本次无 429，若遇 429 属
  外部抖动不属本模块回归。
- 已修正口径（minor-2）不修改 module-064 历史活动日志行（只改 3 处指定位置）。
- 公开基准为单通道余弦暴力检索，与生产 RRF 三通道 + 重排链路不同构
  （对比自建集仅为方向性结论）。

## 八、交付物

- `ai_service/eval/benchmarks/benchmark_embed_write.py`（WP1，新建）
- `ai_service/eval/benchmarks/benchmark_public_retrieval.py`（WP3，新建）
- `ai_service/rag/retrieval/document_dedup.py`（WP4 minor-1，+1 行过滤）
- `ai_service/tests/core/test_document_dedup.py`（+1 单测）
- METRICS.md（待办⑤⑥⑦ + E2E 段 + 公开基准段）
- `memory/project-context.md` / `CONTEXT.md`（minor-2 口径修正）
- `.gitignore`（+eval/datasets/public/ 缓存）
- `specs/module-065-ingest-perf-and-e2e/`：plan / acceptance-criteria / changelog
  （本文件）/ review-report / test-report（Reviewer/Tester 产出）
- memory 三件套（project-context 追加行 / agent-activity-log / file-index）

## 九、Review 修复轮（2026-08-15，Reviewer Conditional → 修复后复审）

**MAJOR-1：benchmark_public_retrieval.py 标称"余弦"实为点积**——bge-m3 Q8
llama.cpp 原始输出未 L2 归一化（embeddings.py:13 明确"输出未 L2 归一化需
_normalize"；Reviewer 实测单条 norm=26.68），旧版 `docs_vec @ q_vec` 直接用
原始向量点积，模长∝文本长度参与排名。
- **修复**：corpus 矩阵逐行 L2 归一化 + 查询向量归一化（对齐
  embeddings._normalize：norm<1e-9 置 1 防除零），归一化后点积=余弦；脚本
  落库 caliber_note 标注"L2 归一化（Review MAJOR-1 修复）"。
- **重跑结果**（同抽样种子同口径）：ecom-zh id=42 0.0240/0.0240/0.0240
  （旧 id=40 0.0240/0.0233/0.0235，基本不变——电商文档长度均匀，归一化
  影响小）；nfcorpus id=43 **0.5139/0.4185/0.4387**（旧 id=41
  0.4923/0.4152/0.4329，Hit@5 +0.0216 / nDCG@10 +0.0058——长文模长偏置
  确实存在，修复后更贴近官方参考值）。旧记录 id=40/41 已落库标注
  "旧版点积口径…由新 eval_runs 取代"（数据更正）。
- 同步：METRICS 公开基准段 + 待办⑤、changelog WP3 段更新为新 id 数字。

**minor-①**：METRICS 待办⑤ 残留"nfcorpus 抽样待跑"（已跑）→ 已更新为
"首跑 + MAJOR-1 修复重跑"表述，引新 id。
**minor-②**：WP1 脚本结论行写死 → 改为本次实测数据驱动（批量/多进程倍率、
ms/块范围均取自当次运行）；110-160 vs 实测 173-211ms/块口径统一为
"~110-210ms/块（随文本长度波动：探路短文本 110-160 / 复测 141 字符 173-211）"
（METRICS 待办⑥ + changelog WP1 段同步）。Reviewer 争用态复跑批量 1.6-2.0x
为瞬时现象不可重现——结论修正为"无稳定可复现的批量加速"（探路 0.8-1.3x /
本机安静态 0.9-1.0x / 争用态 1.6-2.0x 波动）。
**minor-③**：scripts/test_models.py 裸 pytest 收集报错为 module-050 既有
遗留，不动（Reviewer 认可）。
**minor-④**：changelog WP1 两表"循环 200 条"（42.29s vs 34.60s）为两次独立
测量 → 已加注说明（测量时段 CPU/热状态波动，非同一测量矛盾，同段内倍率稳定）。

**测试影响**：脚本改动不影响测试套件（基准脚本不被测试导入），全量仍为
1037/0；eval_runs 新旧记录并存（旧标注更正，新记录为准）。

## 十、Tester 修复轮（2026-08-15，抽样口径三处修正）

Tester 独立复算发现 WP3 抽样口径文档/实现不符，修复如下：

**① 跳过语义未实现（核心）**：脚本 qids 按 qrels 预过滤 → `relevant` 恒非空 →
`n_skip` 恒 0，"323/323 有效 0 跳过"是设计使然而非"相关文档全在抽样内"；
实际抽样下 nfcorpus 31/323（9.6%）查询的相关文档全部落在抽样外（按构造得
0 分，计入稀释指标）。
- **修复**：实现真跳过——有效查询 = 相关文档 ∩ 抽样 corpus 非空者，空者
  跳过不计并计数（纯集合运算，且省去被跳过查询的嵌入成本）；
- **重跑结果（最终版）**：ecom-zh **有效 26（跳过 974，即 97.4%）→
  id=44 Hit@5/MRR/nDCG@10 均 0.9231**（旧全计入口径 id=42 为 0.0240——
  稀释移除后指标本质变化）；nfcorpus **有效 292（跳过 31）→ id=45
  Hit@5 0.5685 / MRR 0.4630 / nDCG@10 0.4853**（旧 id=43 0.5139/0.4185/
  0.4387，稀释移除后提升）；跳过计数与 Tester 独立复算完全一致（26/31）。
- 旧口径数字（id=40-43）全部按"全查询计入"语义，新数字（id=44/45）按
  "有效查询"语义，两者口径不同不可直接比；id=42/43 已落库标注
  "全查询计入口径…由 id=44/45 取代"。

**② ecom "~86% 查询相关文档落抽样外"估算有误**：实际 qrels 每查询仅 1 条
相关（mean=1.0），落抽样外比例 ≈ 97%（非假设 ~5 条/查询的 86%）。
- **修复**：文档不再写估算百分比，直接引用脚本实打印的跳过计数
  （ecom 跳过 974 / 有效 26；nfcorpus 跳过 31 / 有效 292）。

**③ 注释与代码不符**：旧 L227 注释"抽样后相关文档不在 corpus → 跳过不计"
描述的是未实现语义（实现是不跳过）。
- **修复**：注释改为描述真实跳过语义（见 ①），口径声明打印同步。

**测试影响**：脚本改动不影响测试套件（不被测试导入），全量仍 1037/0；
ecom/nfcorpus 最终数字与 eval_runs id 见 §三。
