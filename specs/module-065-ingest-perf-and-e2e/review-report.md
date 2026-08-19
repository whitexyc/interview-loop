# Module-065 审查报告 — 入库性能验证 + E2E 复测 + 公开基准 + minor 清理

> Reviewer：2026-08-15 | 对照 `acceptance-criteria.md` 8 维逐条核查
> 结论：**⚠️ Conditional（1 项 major → 回 Developer 修复后重审；4 项 minor 非阻塞）**

## 一、独立验证（不采信 changelog 数字，逐项实测/查库）

| 验证项 | 方法 | 结果 |
|--------|------|------|
| 全量 pytest | 独立复跑 `pytest tests/ -q` | **1037 passed / 0 failed（135.35s，42 warnings）** 与 changelog 167.24s/42 warnings 一致 |
| WP4 单测 | 独立复跑 test_document_dedup.py | **16/16 通过** |
| WP3 eval_runs | 直查 DB | **id=40 ecom-zh（0.0240/0.0233/0.0235, n=1000）+ id=41 nfcorpus（0.4923/0.4152/0.4329, n=323）** 真实落库，与 changelog/METRICS 逐字一致 |
| WP2 六次探针 | 直查 request_logs id 20-25（2026-08-14 18:00 UTC ≈ 08-15 02:00 本地） | rerank 1.9-3.3s（均 2403ms≈2.4s）/ 图谱 0.9-1.4s / 反思 1.4-2.6s / 生成 4.5-14s / HyDE 仅首次（id=20 2566ms，后续无）——与 changelog 分段**逐项吻合** |
| WP2 探针旁证 | 直查 verify_results id 9-13（G1 GC claims，与 request_logs 20-25 一一对应；id=9 拆句 15s 超时空 claims） | 6 次探针真实发生过 |
| WP2 真实文档命中 | 直查 documents id=8282/8284/8304 | 存在，source=realdoc_test:2026-08-14，标题 `[实测]rag_survey.pdf > ...` ✓ |
| WP2 服务重启 | 复测期间 port 8001 监听（python，01:29 启动） | 重启声明成立；Developer 已按"测完停服务"收尾 |
| WP1 脚本可复跑 | 独立复跑 `--quick` | 可运行（本机 CPU 争用致绝对值放大 3-4x，方向一致） |
| 存量测试零改动 | git diff tests/ | 仅 test_document_dedup.py +1 项，无存量断言改动 |
| memory 硬约束 | project-context 头部 2026-08-15 + module-065 行 + v0.65.0 + activity Dev 行 + file-index 6 行 + changelog 注明已读 | 全在（本条为 Reviewer 行） |
| CONTEXT.md 只增不删 | diff 核查 | 段内修订附更正说明，零删行 ✓ |

## 二、AC 逐条对照

- **WP1**（4 项）：脚本可复跑 ✓；输出与探路口径一致 ✓（批量 1.0x/0.9x/1.0x 无加速、多进程 0.4x/0.3x 负优化）；METRICS 待办⑥ 更新为证伪结论 ✓；生产代码零改动 ✓（embeddings.py/engine.py 无 diff）。
- **WP2**（5 项）：服务重启 ✓；6 次实测 TTFT/完整 ✓（15.4/18.9s，DB 旁证）；真实文档命中 ✓（chunk id 实证）；request_logs rerank 分段 ✓；METRICS 更新含优化前对照 ✓。
- **WP3**（3 项）：数据源探测 ✓（hf-mirror 可达）；**两个数据集真实数字 + 落库 ✓（但指标口径有误，见 MAJOR-1）**；METRICS 公开基准段 + 乐观偏差解读 ✓。
- **WP4**（2 项）：is_canonical 过滤 + 单测 ✓；三处 85/1036 口径修正 ✓。
- **收口**：全量 1037/0 ✓；changelog/review/test-report + memory 三件套 ✓（本报告产出中）；诚实边界 ✓。
- **降级**：nfcorpus 首跑进程异常退出无产出，重跑成功补数（过程如实）✓；无 429；服务重启无端口占用 ✓。

## 三、MAJOR（必须修复）

### MAJOR-1：benchmark_public_retrieval.py 标称"余弦"实为点积（未归一化），eval_runs id=40/41 标签错误

**文件**：`ai_service/eval/benchmarks/benchmark_public_retrieval.py`（L209-223 嵌入、L223 `docs_vec @ np.array(q_vec)`）

**问题**：bge-m3 Q8 的 llama.cpp 原始输出**未 L2 归一化**（本机实测单条向量 L2 norm = **26.68**；项目约定 embeddings.py:13 明确"输出未 L2 归一化，需 _normalize()"，L97/L109 生产路径均先归一化）。脚本直接用原始向量做点积，向量模长（∝ 文本长度）参与排名，**不是余弦相似度**。但：
- 脚本 docstring L21 与输出 L239 声明"余弦暴力检索"；
- eval_runs id=40/41 落库 `"embedding": "bge-m3 Q8 本地 + 余弦暴力检索"`；
- METRICS 公开基准段、changelog WP3 段沿用"余弦"表述。

**影响**：指标值非真余弦口径（长文档被模长抬升，排名与真余弦有偏）；nfcorpus 与官方 bge-m3 参考值同量级属近似方向正确，但数字本身未经正确口径测量。本模块立身之本是"口径声明完整、数据说话"，落库记录长期被引用，错标签会误导后续。

**建议（可执行）**：
1. 脚本嵌入后归一化：`docs_vec = docs_vec / np.linalg.norm(docs_vec, axis=1, keepdims=True)`（行内零向量防御），query 向量同理（对齐 embeddings.py `_normalize` 约定）；
2. 重跑 ecom-zh（--corpus-sample 3000）与 nfcorpus（--corpus-sample 1200）→ 新 eval_runs 记录（或同 id 更新），同步 METRICS 公开基准段/待办⑤ 与 changelog WP3 段数字；
3. 若坚持不归一化，则必须改标签为"点积（未归一化）"——但建议走方案 1（修复成本 ~15 分钟 + 重跑）。

## 四、MINOR（非阻塞）

1. **METRICS 待办⑤ 残留旧文案**：公开基准段已更新为 id=41，但待办⑤ 仍写"nfcorpus 抽样待跑"——与 id=41 矛盾，需同步（改待办⑤ 为"两数据集已跑首轮 + 全量待 GPU"）。
2. **WP1 脚本结论行为 + 数字口径**：结论行写死"批量无加速/多进程负优化"，与实测倍率解耦——我在 CPU 争用（AI 服务运行中）下复跑 `--quick` 出现批量 1.6-2.0x 快于循环（绝对值放大 3-4x），结论方向依赖环境；建议结论行附"本机实测倍率见上表"或按实测方向输出。另口径不一致：METRICS 待办⑥/脚本 docstring 写 ~110-160ms/块，本批实测 173-211ms/块（changelog 110-210 覆盖，METRICS 未覆盖）。
3. **scripts/test_models.py 被 pytest 收集**：裸 `python -m pytest -q`（ai_service 根）会收集 scripts/test_models.py 报 `fixture 'label' not found` collection error（1037 passed + 1 error，44 warnings）。**既有问题（module-050 遗留，本模块零改动）**，项目惯例跑 `pytest tests/` 不受影响——建议后续模块在 tests/conftest.py 加 `collect_ignore = ["../scripts"]` 或脚本改名。
4. **WP1 循环档两表数值不一致**：批量对比表"循环 200 条 42.29s" vs 进程对比表"串行 200 条 34.60s"——同一操作两次测量差 22%（机器态波动），建议 changelog 注明两表为独立测量（或合并口径）。

## 五、审查要点覆盖说明

- 方法学：WP1/WP2 口径与 plan/探路一致 ✓；WP3 抽样代理口径声明完整 ✓（ecom 受抽样支配 ~86% 相关文档落抽样外，0.97^5≈0.859 数学自洽）；**但"余弦"标签错误（MAJOR-1）**。
- 正确性：rerank 平均 2403ms 与"平均 ~2.4s"吻合；nDCG trec 口径实现正确（dcg/idcg 公式、gain=qrels 分数）；Hit@5/MRR 语义正确。
- 降级链：WP3 下载失败 sys.exit(2) 标注"待环境"；单查询无标注跳过计数 ✓；WP2 无 429 如实声明 ✓。
- 诚实性：nfcorpus 首跑失败重跑补数；ecom 数字"不可与官方比"如实；无伪造数字。
- 测试：AC 覆盖（WP4 单测 16/16；存量零改动实证）；mock 合理（SQL 编译捕获对齐既有模式）。
- 结果解读：ecom 受抽样支配、nfcorpus 同量级略低、两数仅方向性对比——解读克制未过度外推 ✓。
- 风格与最小改动：WP1 生产零改动 ✓；WP4 单行过滤 + 注释 ✓；脚本风格对齐既有 benchmark 脚本 ✓。
- 记忆核查：全在 ✓。

## 六、结论

**Conditional（第 1 轮）**：MAJOR-1（余弦/点积口径）修复 + 重跑两数据集更新数字后重审。修复范围小（脚本 2 行归一化 + 重跑 ~20 分钟 + 文档同步），不涉及生产代码。

## 七、第 2 轮复审（2026-08-15，修复后）→ ✅ Pass

Developer 修复轮（changelog §九）逐项核验：

| 项 | 修复核验 | 结果 |
|----|----------|------|
| MAJOR-1 脚本 | L217-223 corpus 矩阵逐行 L2 归一化（norm<1e-9 置 1 防除零）+ L231-233 查询向量归一化；落库标签"L2 归一化后余弦暴力检索" + caliber_note 注明旧 id=40/41 为点积口径 | ✓ |
| MAJOR-1 重跑 | 直查 DB：**id=42 ecom-zh 0.0240/0.0240/0.0240**（旧 0.0240/0.0233/0.0235 基本不变——文档长度均匀，归一化影响小）+ **id=43 nfcorpus 0.5139/0.4185/0.4387**（旧 0.4923/0.4152/0.4329，Hit@5 +0.0216 / nDCG@10 +0.0058——长文模长偏置确实存在）；旧 id=40/41 已落库 correction 标注；changelog/METRICS 数字与 DB 逐字一致，口径更正 delta 数学自洽（0.5139-0.4923=0.0216 / 0.4387-0.4329=0.0058） | ✓ |
| minor-① | METRICS 待办⑤ 更新为"首跑 + MAJOR-1 修复重跑"表述引新 id，残留"待跑"清除 | ✓ |
| minor-② | 脚本结论行改**本次实测数据驱动**（批量/多进程倍率取自当次运行）；ms/块口径统一"~110-210ms/块（探路短文本 110-160 / 本脚本 141 字符实测 173-211）"；Reviewer 争用态 1.6-2.0x 如实记录为瞬时现象不可重现，结论修正为"无稳定可复现的批量加速"（诚实口径更严谨） | ✓ |
| minor-③ | 既有 module-050 遗留，不动（认可） | ✓ |
| minor-④ | changelog WP1 两表差异注明为两次独立测量（时段 CPU/热状态波动） | ✓ |

**结论：✅ Pass（无 major → 进 Tester）**。全量 pytest 1037/0（第 1 轮已独立复跑）+ WP1/WP2/WP4 证据链不变；WP3 数字现为真余弦口径（id=42/43）。

## 八、第 3 轮复审（2026-08-15，Tester 发现 → Developer 修复轮）→ ✅ Pass（最终）

Tester 独立复算发现 WP3 抽样口径两处文档/实现不符，Reviewer 从本地 qrels 数据独立复核**全部证实**，Developer 第三轮修复（changelog §十）后逐项核验：

| Tester 发现（Reviewer 独立复核） | 复核数据 | 修复核验 |
|----------------------------------|----------|----------|
| ① "0 跳过"系设计使然：qids 按 qrels 预过滤 → relevant 恒非空，"323/323 有效 0 跳过——所有测试查询的相关文档均落在抽样内"推断不成立 | nfcorpus qrels 均值 38.2 条相关/查询（中位 16），抽样 33% 下 **31/323（9.6%）查询相关文档全部落抽样外**（按构造得 0 分稀释指标） | 脚本实现真跳过（`qids_effective = 相关文档 ∩ 抽样 corpus 非空`，n_skip 计数打印，跳过查询省嵌入成本）——最终代码核验正确；changelog/METRICS 改引实际跳过计数（ecom 跳过 974 / nfcorpus 跳过 31） |
| ② ecom "~86% 落抽样外"估算有误：非假设 ~5 条/查询 | qrels 每查询**恰好 1 条**相关（mean=1.0, std=0），3% 抽样下 **97.4%**（仅 26/1,000）查询相关文档在抽样内 | 文档不再写估算百分比，直接引用脚本实打印计数（26 有效 / 974 跳过） |
| ③ 旧 L227 注释描述未实现语义 | — | 注释改为真实跳过语义，口径声明打印同步 |

**重跑最终数字（DB 直查）**：
- **id=44 ecom-zh：有效查询 26，Hit@5/MRR/nDCG@10 均 0.9231**——解读修正为"答案在 corpus 内时 bge-m3 找回能力高，但 26 条基数统计证据薄，不可与官方比"（比旧"0.024 受抽样支配"更准确）；
- **id=45 nfcorpus：有效查询 292，0.5685 / 0.4630 / 0.4853**——nDCG@10 落在官方全量口径 bge-m3 参考值（~0.45-0.5）**区间内**（旧 0.4387 略低）；
- 口径演进三段明确标注（id=40/41 点积 → 42/43 余弦全查询计入 → 44/45 余弦+真跳过），各 id 不可直接比，旧记录均落库标注；changelog §三/METRICS 公开基准段/待办⑤/project-context module-065 行全部同步为最终口径。
- 测试影响：脚本不被测试导入（`--co` 1037 项收集不变），全量仍 1037/0。

**结论：✅ Pass（最终）**。三轮修正后 WP3 口径为"余弦（L2 归一化）+ 真跳过语义"——方法与标准 IR 评测实践对齐（无相关在库查询剔除），解读诚实（ecom 基数薄/nfcorpus 有效信息量），无剩余 major。残留 1 处措辞微瑕（非阻塞）：METRICS L224-226 旧 blockquote"性能大幅下降这一普遍预期被证实"未随 ecom 0.92 更新——与上方修正后解读不冲突，可后续顺手润色。
