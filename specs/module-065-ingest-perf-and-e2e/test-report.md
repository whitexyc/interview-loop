# Module-065 测试报告 — 入库性能验证 + E2E 复测 + 公开基准 + minor 清理

> Tester：2026-08-15 | 验收基线：plan.md / acceptance-criteria.md / changelog.md（含 §九/§十 修复轮）
> Review 结论：✅ Pass（第 2 轮复审 pass + 第 3 轮 Tester 修复确认，见 review-report.md）
> **验收结论：✅ 通过（AC 17 项全过 / 0 阻塞）**

## 一、全量测试

| 项目 | 结果 |
|------|------|
| 全量 pytest（Tester 独立复跑） | **1037 passed / 0 failed（152.78s，43 warnings）** = 1036 基线 + 1 新增 |
| 基线核对 | 开工前独立复跑 1036/0（module-064 验收数）与 plan 声明一致 |
| 新增单测 | test_document_dedup.py `test_semantic_duplicate_query_filters_non_canonical` 通过（16/16 全绿） |
| 存量改动 | 存量测试零改动（git diff tests/ 仅 +1 项） |
| warnings | 与基线同源（Redis setex 弃用 / SAWarning 连接清理，非本模块引入） |

## 二、冒烟复跑（与 changelog 数字核对）

### WP1 写入侧嵌入基准（Tester 独立复跑 `--quick`）

| 档位 | Tester 实测 | changelog 本机实测 | 一致 |
|------|------------|-------------------|------|
| 批量 10 条倍率 | 1.0x | 1.0x | ✓ |
| 批量 50 条倍率 | 0.9x | 0.9x | ✓ |
| 多进程 2 倍率 | 0.4x | 0.4x | ✓ |
| 吞吐 ms/块 | 166-194ms（141 字符） | ~110-210ms（随文本长度波动） | ✓ 量级一致 |
| 结论行 | "本次实测数据"驱动（批量无稳定加速/多进程负优化） | 同口径（minor-② 修复生效可见） | ✓ |

结论：脚本可复跑、输出与探路口径一致（批量 ~1x 无加速 / 多进程 0.4x 负优化），证伪结论成立。

### WP2 E2E 复测（Tester 直查 DB 独立核对，未采信 changelog）

| 验证项 | 证据 | 结果 |
|--------|------|------|
| request_logs id=20-25（6 次 G1 GC 探针） | rerank = 2015/1922/1921/2094/3203/3266ms → **1.9-3.3s，均值 2404ms ≈ 2.4s** | ✓ 与 changelog "1.9-3.3s（平均 ~2.4s）"逐字吻合 |
| 生成段 | 4547-14032ms = 4.5-14s | ✓ 与 changelog "生成 4.5-14s"吻合 |
| 优化前后对照 | id=14/15（08-13）rerank 13.0-13.5s vs id=20-25（08-15）1.9-3.3s | ✓ 对照成立 |
| 真实文档命中 | documents id=8282/8284/8304 存在，source=realdoc_test:2026-08-14，标题 `[实测]rag_survey.pdf > ...` | ✓（Tester 另查 8281-8286 均在） |
| TTFT/完整 15.4/18.9s | 探针真实发生（request_logs + verify_results 旁证，Reviewer 已查 id 9-13 对应） | ✓ 与 METRICS 表一致 |

### WP3 公开基准（Tester 独立复算 + 直查 DB）

| 数据集 | Tester 独立复算（固定种子） | 实际运行（eval_runs） | 一致 |
|--------|---------------------------|----------------------|------|
| ecom-zh 3,000/100,902 抽样 | 26/1,000 查询相关文档在抽样内（2.6%） | id=44 有效 26（跳过 974），Hit@5/MRR/nDCG@10 = 0.9231 | ✓ 精确一致 |
| nfcorpus 1,200/3,633 抽样 | 292/323 查询相关文档在抽样内（90.4%） | id=45 有效 292（跳过 31），Hit@5 0.5685 / MRR 0.4630 / nDCG@10 0.4853 | ✓ 精确一致 |

- 口径演进三轮（id=40/41 点积 → 42/43 余弦全计入 → **44/45 余弦+真跳过**）均落库标注，changelog/METRICS 以 id=44/45 为最终口径，数字与 DB 逐字一致。
- **Tester 发现 → 修复 → 验证闭环**：抽样覆盖率复算发现"0 跳过"系设计使然（相关集取自 qrels 恒非空），实际 31/323 nfcorpus 查询与 974/1000 ecom 查询相关文档全落抽样外被 0 分稀释；Developer 实现真跳过语义后重跑，实跑有效查询数与 Tester 独立复算**精确一致**（26/292）——验证修复正确且数字真实。
- ecom "~86%" 估算修正为实际 97%（qrels 每查询 1 条相关）；"323/323 有效"误句已删，替换为真实跳过计数。

### 服务与降级

- AI 服务重启（uvicorn 8001，01:29 启动）→ 复测完成 → 已停服（Reviewer 确认"测完停服务"；Tester 核查当前无服务进程）。
- 无 deepseek 429；WP3 数据源探测（huggingface.co 502 不可达 / hf-mirror 可达）与"全量待 GPU 环境"降级声明如实。

## 三、实现抽查（与 changelog 一致）

| 项 | 抽查结果 |
|----|----------|
| benchmark_embed_write.py 计时口径 | perf_counter 包住 create_embedding（持锁 + _lazy_load），循环 vs List 批量 10/50/200 + 进程 2/4×200，`__main__` 守卫（spawn）——与探路口径一致 ✓ |
| is_canonical 过滤 | document_dedup.py `find_semantic_duplicate` 候选查询加 `Document.is_canonical.is_(True)`（注释对齐检索抑制语义）✓ |
| WP3 归一化（Review MAJOR-1 修复） | 脚本 L217-223 corpus 矩阵逐行 L2 归一化（norm<1e-9 置 1 防除零）+ L231-233 查询向量归一化，落库标签"L2 归一化后余弦暴力检索" ✓ |
| WP3 真跳过（Tester 修复轮） | 有效查询 = 相关文档 ∩ 抽样 corpus 非空者（L226-233），n_skip 实计数，注释与实现一致 ✓ |
| minor-2 三处口径 | project-context module-064 行 66→85 + 1017/0→1036/0；ADR-0014 状态行 64→85；CONTEXT.md 段内修订附更正说明零删行（只增不删）✓ |
| .gitignore | +`ai_service/eval/datasets/public/`（公开数据缓存可重下）✓ |

## 四、记忆硬核查

| 项 | 结果 |
|----|------|
| project-context.md 头部日期 | 2026-08-15（module-065 完成）✓ |
| project-context.md module-065 行 | 存在（模块清单行 + §5 当前迭代 v0.65.0）✓ 格式对齐 |
| agent-activity-log.md | module-065 段存在：Developer 行 + Reviewer 3 轮行 ✓（Tester 行由本报告追加） |
| file-index.md | module-065 5 行（两个基准脚本 + document_dedup + 单测 + specs 目录）✓ |

## 五、AC 逐条对照（18 项）

| AC 项 | 结果 | 依据 |
|-------|------|------|
| WP1-1 脚本可复跑（三组对比+耗时倍率表） | ✅ 通过 | Tester 复跑 `--quick` 输出三组对比表 |
| WP1-2 输出与探路口径一致 | ✅ 通过 | 批量 1.0x/0.9x 无加速、MP 0.4x 负优化，同量级 |
| WP1-3 METRICS 待办⑥ 更新为证伪结论 | ✅ 通过 | METRICS 待办⑥ 已划线标注"实测证伪"+固有成本结论 |
| WP1-4 生产代码零改动 | ✅ 通过 | embeddings.py / engine.py 无 diff（git 核对） |
| WP2-1 AI 服务重启可用 | ✅ 通过 | uvicorn 8001 启动 + 6 次探针真实发生（request_logs 旁证） |
| WP2-2 "什么是G1 GC" 6 次 TTFT/完整 | ✅ 通过 | 15.4/18.9s（平均）与 METRICS 一致，DB 旁证探针真实 |
| WP2-3 真实文档生产链路命中 | ✅ 通过 | documents id=8282/8284/8304 存在（source=realdoc_test） |
| WP2-4 request_logs rerank 分段 | ✅ 通过 | id=20-25 rerank 1.9-3.3s（均 2.4s），Tester 直查 |
| WP2-5 METRICS E2E 段优化后数字含对照 | ✅ 通过 | METRICS 优化前 25.3/28.1 vs 优化后 15.4/18.9 + 分段表 |
| WP3-1 数据源可达性探测 | ✅ 通过 | hf-mirror 可达（huggingface.co 502 如实标注），下载成功 |
| WP3-2 ≥1 公开数据集真实指标 | ✅ 通过 | 两数据集真实跑通（id=44/45，实跑有效查询数与 Tester 复算精确一致） |
| WP3-3 METRICS 公开基准段 | ✅ 通过 | 新段含口径演进 + 乐观偏差解读 + 与自建集 0.9905 对比 |
| WP4-1 is_canonical 过滤 + 单测 | ✅ 通过 | SQL 编译捕获断言（16/16），存量零改动 |
| WP4-2 三处 85/1036 口径修正 | ✅ 通过 | 三处全改（CONTEXT.md 只增不删，段内修订附说明） |
| 收口-1 全量 pytest 基线+新增全绿 | ✅ 通过 | Tester 复跑 **1037/0**（1036 基线 + 1 新增，存量零改动） |
| 收口-2 文档 + memory 三件套 | ✅ 通过 | changelog/review-report 齐全；memory 三件套核查通过（Tester 行待追加） |
| 收口-3 诚实边界声明 | ✅ 通过 | WP1 证伪记录 / WP3 抽样+算力制约 / WP2 外部抖动均如实声明 |
| 降级-1 数据源不可达→脚本+待环境 | ✅ 通过 | 下载失败 sys.exit(2) 标注"待环境"；全量入口 `--corpus-sample 0` 就绪 |
| 降级-2 429→如实记录 | ✅ 通过 | 本次无 429，生成段 4.5-14s 波动如实归因外部抖动 |
| 降级-3 服务无法重启→如实记录 | ✅ 通过 | 一次启动成功无端口占用（不适用本项，如实记录） |

## 六、结论

**验收通过（20/20 项通过，0 阻塞）**。关键验证点：
1. 全量 1037/0 全绿，存量零改动；
2. WP1 证伪结论可复跑复现（批量 ~1x / 多进程 0.4x）；
3. WP2 优化落地值经 DB 独立核对（rerank 8.5-13.5s → 1.9-3.3s，TTFT -39%）；
4. WP3 数字真实（id=44/45 与 Tester 固定种子复算逐位一致），口径演进全程落库标注诚实；
5. Tester 修复轮（抽样真跳过 + 口径修正）经实跑验证正确，changelog/METRICS 最终数字与 DB 一致。

非阻塞观察（已随修复轮处理或记录）：ecom-zh 有效查询仅 26 条统计证据薄（如实标注，全量待 GPU 环境）；nfcorpus 官方参考值（~0.45-0.5）为外部引用不可本机复验（方向性解读已克制）；scripts/test_models.py 裸 pytest 收集报错为 module-050 既有遗留（项目惯例跑 `pytest tests/` 不受影响）。

**模块状态：✅ 完成（待 Developer 提交推送后 team-lead 收口）**
