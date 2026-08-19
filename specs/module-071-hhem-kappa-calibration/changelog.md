# Module-071 变更日志 — 幻觉检测 kappa 校准（阈值扫描 + 标注集扩充 + 达标决策）

> 实施：Developer（2026-08-18）| 计划：`plan.md` | 验收：`acceptance-criteria.md`
> 范围：METRICS 待办 #2（HHEM 裁判 kappa 0.3252 < 0.7 未达标）——25 组阈值网格扫描
> （分数只算一次）+ 标注集 50→136 扩充 + inferred"部分覆盖"口径重写 + 达标才改生产
> 配置。**决策：重跑三态 kappa 0.2981 < 0.7 → 不达标，不改生产配置，如实标注。**
> 全量 pytest 基线 1152/0（module-070 验收数；实跑以 WP-D 收集为准）。

## 一、WP-A：阈值校准扫描（先量尺子——旧 50 条旧标注上找最优）

**产出**（`ai_service/eval/golden/golden_factcheck.py`）：
- `max_score_to_verdict(max_score, high, low)` 纯函数——三态映射**唯一实现**
  （`>= high → supported / >= low → inferred / else → unsupported`，含等号边界，
  与生产 reflector.py `_judge_by_hhem` 逐字同口径）；`judge_factcheck` 重构为引用之，
  行为零变化（存量测试逐字全绿）。
- `scan_thresholds(per_question, highs, lows)` 纯函数——25 组 (high, low) 纯后处理，
  只消费 per_question 的 `label + max_score`（max_score=None 跳过，与 kappa_metrics
  只算 evaluated 同口径）；排序规则写死：三态 kappa 降序 → 二值 kappa 降序 →
  贴近生产 0.7/0.3；无可评估样本 → []。
- CLI：`--scan-thresholds`（run_eval 一次 → 25 行对照表 → 最优组合 → 落库 **1 行**
  eval_type='factcheck_scan'，对照表内嵌 scores，不落 25 行噪音；`--no-save` 生效；
  `--fixture + --scan-thresholds` 显式报错——启发式判官不产生 max_score）；
  `--threshold-high X --threshold-low Y`（启动时覆盖 settings，judge 每次调用读
  settings 即时生效，单进程 CLI 无需还原）。

**真实扫描（旧 50 条，eval_runs id=49 'factcheck_scan'）**——HHEM 分数只算一次
（50 条推理 + 25 组纯后处理 <1s）：

| high | low | 三态 kappa | 二值 kappa | Acc | high | low | 三态 kappa | 二值 kappa | Acc |
|------|-----|-----------|-----------|-----|------|-----|-----------|-----------|-----|
| 0.65 | 0.35 | **0.3711** | 0.3697 | 0.60 | 0.60 | 0.35 | 0.3312 | 0.2975 | 0.58 |
| 0.65 | 0.40 | 0.3590 | 0.3697 | 0.60 | 0.65 | 0.20 | 0.3252 | 0.3697 | 0.56 |
| 0.55 | 0.35 | 0.3590 | 0.3443 | 0.60 | 0.70 | 0.30 | 0.3252 | 0.3220 | 0.56 |
| 0.50 | 0.35 | 0.3590 | 0.3443 | 0.60 | 0.70 | 0.25 | 0.3252 | 0.3220 | 0.56 |
| 0.65 | 0.30 | 0.3519 | 0.3697 | 0.58 | 0.60 | 0.40 | 0.3182 | 0.2975 | 0.58 |
| 0.65 | 0.25 | 0.3519 | 0.3697 | 0.58 | 0.55 | 0.20 | 0.3125 | 0.3443 | 0.56 |
| 0.55 | 0.40 | 0.3464 | 0.3443 | 0.60 | 0.50 | 0.20 | 0.3125 | 0.3443 | 0.56 |
| 0.50 | 0.40 | 0.3464 | 0.3443 | 0.60 | 0.60 | 0.30 | 0.3125 | 0.2975 | 0.56 |
| 0.70 | 0.35 | 0.3438 | 0.3220 | 0.58 | 0.60 | 0.25 | 0.3125 | 0.2975 | 0.56 |
| 0.55 | 0.30 | 0.3396 | 0.3443 | 0.58 | 0.70 | 0.20 | 0.2988 | 0.3220 | 0.54 |
| 0.55 | 0.25 | 0.3396 | 0.3443 | 0.58 | 0.60 | 0.20 | 0.2857 | 0.2975 | 0.54 |
| 0.50 | 0.30 | 0.3396 | 0.3443 | 0.58 | | | | | |
| 0.50 | 0.25 | 0.3396 | 0.3443 | 0.58 | | | | | |
| 0.70 | 0.40 | 0.3312 | 0.3220 | 0.58 | | | | | |

- **最优组合：high=0.65 low=0.35（三态 kappa 0.3711）**——较生产 0.7/0.3（0.3252，
  与 module-051 基线逐字一致）**+0.0459**；high 下探 0.65 有效（0.7 上界偏严），
  low 上探 0.35 有效（中文分数压缩致低分误判 inferred）。
- **方向性结论：阈值校准天花板已见——最优 0.3711 仍 < 0.7**，单靠阈值无法达标；
  且 0.3252（生产）→ 0.3711（最优）提升有限，确认 module-051 归因（中文分数压缩
  + inferred 标注口径）需修尺子（标注集）而非只调阈值。
- **不改生产配置**（等 WP-C 新集复扫确认）。

## 二、WP-B：标注集扩充 + inferred 口径重写（修尺子）

**产出**：
- `ai_service/eval/datasets/factcheck_real_samples.json`（**新增**，32 条）：
  24 条 real_retrieval_pairs.json 转换（to_factcheck_item 口径：
  entailment→supported 9 / neutral→inferred 10 / contradiction→unsupported 2 +
  neutral 口径复核改判 unsupported 3；part=real_retrieval，claim=真实 LLM 答案
  句子 + doc=DB golden 检索片段）+ 8 条新构造"部分覆盖"样本（part=constructed，
  文档取知识库真实段落，note 含核心断言拆解）。
- `ai_service/eval/datasets/factcheck_annotation_guide.md`（**新增**，对齐
  contradiction_annotation_guide.md 位置与命名）：三态定义写死——supported（文档
  直接支持 claim 全部核心断言）/ **inferred（部分覆盖：至少一个核心断言被文档直接
  支持 + 至少一个未被覆盖且无冲突，边界写死）** / unsupported（不包含支持任何核心
  断言的内容，含矛盾）；**"直接被支持" ≠ "主题相关"**（相关背景不支撑任何核心断言
  落 unsupported）；每条标注须在 note 给出核心断言拆解依据。
- `build_factcheck_dataset()` 50 → **136 条**（supported 57 / inferred 20 /
  unsupported 59）：SUFFICIENCY_DATASET 充分/不充分各取前 50（原 20）+ INFERRED
  SAMPLES + factcheck_real_samples.json；**按 question 去重**（保留 part 优先级
  real_retrieval > constructed > sufficiency，同级保留先出现者）。
- `load_factcheck_dataset()` 校验升级：≥100 / question 唯一 / keywords 非空 /
  三类齐全 / JSON 缺失明确 ValueError（不走静默降级）。

**标注变更清单（可审计）**：

| 样本（question） | 旧 → 新 | 理由（核心断言拆解） |
|------------------|---------|----------------------|
| G1 垃圾收集器的调优参数怎么设置？ | inferred → unsupported | doc 仅讲 G1 机制（相关背景），不支撑"调优参数"任何核心断言 |
| Kafka 生产者端怎么配置才能保证消息不丢失？ | inferred → unsupported | doc 讲 ISR 副本机制，与"生产者端配置"无直接对应 |
| 联合索引的最左前缀原则是什么？ | inferred → unsupported | doc 仅讲 B+树结构，不支撑匹配规则断言（**该 question 与 real 样本重复，去重时保留 real supported 版本，本样本被移除**） |
| Spring AOP 的代理失效场景有哪些？ | inferred → unsupported | doc 仅讲代理实现原理，无失效场景 |
| Netty 是怎么解决粘包问题的？ | inferred → unsupported | doc 仅讲 Reactor 线程模型，不支撑粘包成因/解法断言 |
| JWT 的刷新机制是怎么设计的？ | inferred → unsupported | doc 仅讲认证流程，无 refresh token 内容 |
| CAS 的 ABA 问题是怎么产生的？ | inferred → unsupported | doc 仅讲 CAS 原理，无 ABA 内容 |
| HashMap 的扩容时机是怎么决定的？ | inferred → unsupported | doc 仅讲结构与树化（树化≠扩容），不支撑扩容时机断言 |
| 张三的主要技术方向是什么？ | neutral(inferred) → unsupported | 检索片段与 claim 完全无关（真实检索命中不相关片段），0 核心断言被支持 |
| 张三的个人网站项目包含哪些技术栈？ | neutral(inferred) → unsupported | 同上（类加载插件系统 vs 网站技术栈完全无关） |
| 什么是微服务架构？与单体架构相比有哪些优缺点？ | neutral(inferred) → unsupported | doc 仅提及"微服务架构"概念与 Nacos/AP-CP，不支撑定义与优缺点断言 |
| 线程池的四种拒绝策略分别是什么？ | inferred 保持 | doc 直接提到 handler（拒绝策略）支撑"存在拒绝策略"，四种策略未覆盖且无冲突 |
| Redis 哨兵触发故障转移的流程是怎样的？ | inferred 保持 | doc 直接支撑"客观下线判定"（流程触发前置），选举与切换未覆盖且无冲突 |
| real neutral 其余 10 条（FullGC/AQS/Kafka Rebalance/G1 停顿/ConcurrentHashMap 扩容/MyBatis/Seata/Kafka ISR/RocketMQ/TLS） | neutral(inferred) 保持 | note 均含"doc 覆盖 X 子断言 + Y 未覆盖且无冲突"拆解，与新口径逐条一致 |

**去重移除清单（question 唯一强制）**：G1（sufficiency 充分+不充分两版 → 保留 real
supported 版）、AQS（sufficiency 充分版 → 保留 real inferred 版）、联合索引（INFERRED
构造版 → 保留 real supported 版）、synchronized / ZGC（sufficiency 内部同 question
充分/不充分重复 → 同级保留先出现 supported 版）。

## 三、WP-C：重跑验证 + 决策（**不达标 → 不改配置**）

**重跑**（新 136 条标注集 + WP-A 最优阈值 high=0.65 low=0.35，eval_runs **id=50**
（同数字复跑 id=51 确认确定性，无差异），eval_type='factcheck'）：

| 指标 | module-051 基线（旧 50 条，0.7/0.3） | WP-A 旧 50 条最优（0.65/0.35） | **WP-C 新 136 条（0.65/0.35）** |
|------|--------------------------------------|-------------------------------|-------------------------------|
| 三态 kappa | 0.3252 | 0.3711（+0.0459） | **0.2981（-0.0271 vs 旧集最优）** |
| 二值 kappa | 0.3220 | 0.3697 | 0.3701 |
| Accuracy | 0.56 | 0.60 | 0.5515 |

**新集复扫**（eval_runs **id=52** 'factcheck_scan'，136 条 25 组）：最优组合移动为
**high=0.65 low=0.40（三态 kappa 0.3309）**，全网格最优仍 < 0.7 且低于旧集最优——
**阈值最优随标注集移动（0.65/0.35 → 0.65/0.40），阈值对标注集敏感，校准收益天花板
已见（约 0.33-0.37），单靠阈值无法达标**。

**决策（规则写死：三态 kappa ≥ 0.7 才改 config 默认值，Developer 无自由裁量）**：
**0.2981 < 0.7 → 不达标 → 不改生产配置**（`verify_hhem_threshold_high=0.7 / low=0.3`
保持；PW_VERIFY_HHEM_THRESHOLD_* 逃生口保持）；conftest 无需钉旧值（配置未变）。

**失败模式分类（per_question 误判明细统计，共 61 条误判）**：
- **supported 误杀 24/57**（判对 33）：多篇文档样本中文分数压缩严重（如 RDB/AOF
  0.334、MySQL B+树 0.061、哨兵高可用 0.109 被判 unsupported/inferred）——
  module-051 归因① 实证（0.7 上界偏严，但 0.65 也救不回压缩分）；
- **inferred 混淆 15/20**（判对 5，按 eval_runs id=50 per_question 明细核对）：
  HHEM 把"部分覆盖"判成 supported 10 条（Kafka ISR 0.964 / RocketMQ 0.924 /
  ConcurrentHashMap 1.7vs1.8 0.930 / AOF 重写 0.920 / EventLoop 0.876 /
  redo log 0.924 / Docker 0.917 / RSet 0.841 / Redis 哨兵 0.822 /
  ConcurrentHashMap 扩容 0.653）+ 判 unsupported 5 条（MyBatis 0.059 /
  Seata 0.057 / Kafka 消费者组分配 0.070 / JWT vs Session 0.071 /
  Kafka Rebalance 0.286）——**module-051 归因② 实证：HHEM 无法区分
  "部分覆盖"与"完全支持"**；
- **unsupported 漏判 22/59**（判对 37）：其中 8 条为 module-071 口径复核改判样本
  ——**HHEM 对"相关背景但答非所问"的文档打 0.79-0.90 高分**（G1 调优 0.815 /
  Kafka 生产者 0.867 / Spring AOP 0.896 / Netty 粘包 0.847 / JWT 刷新 0.904 /
  HashMap 扩容 0.842 / 雪花 0.793）——口径重写把归因②从"标注争议"变成"可测失败"。

**入 backlog（不隐藏）**：HHEM 中文场景"相关背景/部分覆盖"区分是核心短板（乐观偏差
+ 分数压缩共存）；阈值校准方向已证伪（0.33-0.37 天花板）——下一步方向与 module-057
结论汇合：中文专用/更大 NLI 或针对性微调（HHEM 或 mDeBERTa）、两阶段 LLM 拆句 +
保守矛盾门控、标注集再扩充（飞轮数据积累后按 module-051 归因定向补样本）。

**诚实边界**：
- 136 集为混合口径（sufficiency 代理 95 + 人工 41），kappa 是方向性指标；
- 阈值最优随标注集移动（0.65/0.35 → 0.65/0.40）——**标注集扩充后需复扫**，
  本次最优组合仅作参考记录，未写入生产；
- 8 条 constructed inferred 与 11 条改判样本为 Developer 单方标注（Reviewer 抽查），
  非多人独立标注；
- 复跑 id=50/51 数字一致（HHEM 确定性模型，无 LLM 波动）。

## 四、WP-D：回归 + 文档收口

- **红线零改动**：`factcheck_judge.py`（HHEM 推理路径）/ `reflector.py` / 其他模块
  git diff 为空；config.py 未动（不达标分支无默认值变更）。
- **存量测试例外（验收许可，module-061/062 先例）**：`test_dataset_structure_50_three_classes`
  → `test_dataset_structure_100_three_classes`（≥100 + 实际类分布 57/20/59 +
  question 唯一 + keywords 非空 + part 字段）；`test_dataset_borrows_from_sufficiency`
  不改且验证仍绿（G1 question 由 real 版本保留在集内）。
- **新增单测 19 项**（test_factcheck_judge.py 38 → 57，全 mock 零真实模型）：
  TestMaxScoreToVerdict 7（边界 ==high/==low/区间/低于 low + judge_factcheck 引用
  唯一实现 + settings 覆盖即时生效）+ TestScanThresholds 8（25 组全输出/最优规则
  写死/mock judge 调用次数==样本数回归锁/空输入/全 None/apply_threshold_overrides/
  --fixture+--scan-thresholds 显式报错/record_scan_run 契约 eval_type='factcheck_scan'
  单行）+ TestGoldenFactcheck 数据集校验 4（JSON 缺失/过小/重复 question/空 keywords
  → ValueError）。
- **全量回归**：实跑数字见 WP-D 实测（`pytest tests/ -q`）。

## 五、验证命令（ai_service 目录）

| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| 单测 | `python -m pytest tests/eval/test_factcheck_judge.py -q` | 57 passed |
| 数据集校验 | `python -c "from eval.golden.golden_factcheck import load_factcheck_dataset; print(len(load_factcheck_dataset()))"` | 136 |
| 真实扫描 | `python -m eval.golden.golden_factcheck --scan-thresholds` | 25 行对照表 + 最优组合 + 落库 1 行 factcheck_scan |
| 阈值覆盖重跑 | `python -m eval.golden.golden_factcheck --threshold-high 0.65 --threshold-low 0.35` | kappa 0.2981 + eval_runs 落库 |
| 配置未变 | `python -c "from src.config import settings; print(settings.verify_hhem_threshold_high, settings.verify_hhem_threshold_low)"` | 0.7 0.3 |
| 全量回归 | `python -m pytest tests/ -q` | 基线 + 19 新增全绿 |

## 六、Review 修复（CONDITIONAL 回修，2026-08-18）

**修复 1（changelog §三 + METRICS/CONTEXT 同步）**：失败模式 inferred 混淆分解
12/3 → **10/5**——按 eval_runs id=50 per_question 明细逐条核对（10 条判 supported：
Kafka ISR 0.964 / RocketMQ 0.924 / ConcurrentHashMap 1.7vs1.8 0.930 / AOF 重写
0.920 / EventLoop 0.876 / redo log 0.924 / Docker 0.917 / RSet 0.841 / **Redis 哨兵
0.822** / **ConcurrentHashMap 扩容 0.653**；5 条判 unsupported：MyBatis 0.059 /
Seata 0.057 / Kafka 消费者组分配 0.070 / **JWT vs Session 0.071** / **Kafka
Rebalance 0.286**）；原 12/3 漏计 4 条。同步 METRICS.md（幻觉检测节失败模式行）与
CONTEXT.md（module-071 追加节失败模式行）为 10/5。

**修复 2（golden_factcheck.py 模块 docstring）**：数据集构成改**实际 57/20/59**
（原 docstring 55/24 为过期数字，与代码 59/20 不符）：
- unsupported 59 = SUFFICIENCY 不充分前 50 去重 3（G1/synchronized/ZGC 与充分版
  同题、保留 supported 版）实入 47 + contradiction 2 + INFERRED 改判 8（其中
  "联合索引"与 real supported 版同题被去重，实入 7）+ neutral 改判 3
  （47+2+7+3 = 59；Review 记账 50-4+2+8+3 同总数，去重 4 = 不充分 3 + 联合索引 1）
- inferred 20 = 保持 2 + neutral 保持 10 + 构造 8（2+10+8 = 20）
- supported 57 = 充分前 50 去重 2（G1/AQS 由 real 版接管）实入 48 + entailment 9

**验证**：`test_factcheck_judge.py` 57 项全绿；`load_factcheck_dataset()` 仍返回
136 条（57/20/59）；红线文件零改动（本次仅文档/数字修正）。

## 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-18 | 初始实现（WP-A 扫描 + WP-B 数据集/口径 + WP-C 决策不达标 + WP-D 回归文档） | Developer |
| v2 | 2026-08-18 | Review 修复：inferred 混淆 12/3 → 10/5 + 补全 4 条具名样本（METRICS/CONTEXT 同步）；docstring 数据集构成改实际 57/20/59 | Developer |
