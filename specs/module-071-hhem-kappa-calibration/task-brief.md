# Module-071 Task Brief：幻觉检测 kappa 校准（METRICS 待办 #2）

> 自包含执行简报（待办 #2"幻觉检测 kappa 校准（<0.7 未达标）"落地）。接手方不需要额外对话上下文，按步骤执行即可。所有"已知事实"均已确认（代码已读 + 历史模块结论），无需重新调研。

## 事实（代码实测 + 历史模块结论，2026-08-18）

1. **现状**：golden_factcheck.py 50 条三态标注（supported/inferred/unsupported），HHEM 裁判实测 kappa 三态 0.3252 / 二值 0.3220（module-051）——**< 0.7 未达门槛**，裁判已接入生产（HHEM→LLM→空降级链），未达标如实标注。
2. **阈值**：`verify_hhem_threshold_high=0.7` / `verify_hhem_threshold_low=0.3`（config，PW_ 可配）；映射逻辑 reflector.py:518-525（max_score ≥0.7→supported / 0.3-0.7→inferred / <0.3→unsupported）。**0.7/0.3 是英文经验值，未经中文场景校准**。
3. **根因（module-051 归因）**：① 中文分数压缩——9/20 本该 supported 的句子 HHEM 得分落 0.33-0.67（0.7 上界太严）② HHEM 对"部分覆盖"判一致偏乐观——7/10 该 inferred 的句子得分 0.8+（该降级没降）。
4. **裁判模型层面已穷尽**：mDeBERTa 复测 kappa 0.5167（module-054）< 0.7；句级拆解+阈值校准+86 条样本证伪 0.3754（module-057，改进不成立如实放弃）——**剩余优化空间 = 阈值校准 + 标注口径 + 标注集扩充**。
5. **评测脚本**：`python -m eval.golden.golden_factcheck`（真实 HHEM + 落库 eval_runs eval_type='factcheck'）；--fixture 模式不依赖模型。历史 eval_runs：module-051 id 有基线记录。
6. **基线**：全量 1163/0（module-070 后）。
7. **HHEM 模型**：本地 models/hhem-2.1-open（438MB），hhem_loader 共享加载器；CPU 推理。

## WP-A：阈值校准（先量尺子——在现有 50 条上扫最优阈值）

- 阈值网格扫描：high ∈ {0.5, 0.55, 0.6, 0.65, 0.7} × low ∈ {0.2, 0.25, 0.3, 0.35, 0.4}（25 组），HHEM 分数**只算一次**（每条 claim×doc 的 max_score 缓存），阈值只是后处理映射——成本可控
- 产出：阈值-kappa 对照表（三态 kappa + 二值 kappa + Accuracy），找最优组合
- **预期**：high 下调到 0.5-0.6 区间 kappa 应显著提升（module-051 归因：0.7 上界太严误杀 supported）
- 诚实边界：50 条小样本的阈值最优是"方向性"的，标注集扩充后需复扫
- 通过标准：25 组扫描跑完 + 对照表入 changelog + 最优组合记录（不改生产配置，等 WP-C 数据）

## WP-B：标注集扩充 + inferred 口径（修尺子）

- golden_factcheck 50 → 100+ 条：新增 50+ 条真实 claim 样本（来源：真实 E2E 回答句子 + 检索片段组合——参考 module-070 用真实信息造样本的先例）
- **inferred 标注口径重写**（module-051 归因②：HHEM 对"部分覆盖"判一致偏乐观——标注指南里"部分覆盖"的边界定义要写死）：标注指南更新 + 存量 50 条中 inferred 相关样本复核（标注变更需记录变更清单）
- 通过标准：100+ 条结构校验过（load 校验）+ 标注指南更新 + 变更清单

## WP-C：重跑验证 + 决策

- 新标注集 + WP-A 最优阈值 → 重跑 HHEM kappa
- 达标（≥0.7）→ 生产阈值改最优值（config + 注释 + 降级链不变）
- 不达标 → 如实标注新数字 + 失败模式分类（supported 误杀 / inferred 混淆 / unsupported 漏判各多少），入 backlog 不隐藏
- 通过标准：重跑数字落库 eval_runs + 决策（达标改配置 / 不达标如实标注）

## WP-D：回归 + 文档收口

- 全量 1163 基线 + 新增单测全绿（存量测试零改动红线；阈值改动若影响存量测试需 conftest 钉住旧值）
- changelog（阈值对照表/标注变更清单/重跑数字/决策）+ CONTEXT.md（只增不删先备份）+ METRICS.md 待办 #2 标记（达标完成 / 不达标如实更新）+ 三记忆文件

## 纪律项

1. 只动 `golden_factcheck.py`（标注集+阈值扫描）+ 标注指南 + `reflector.py` 阈值读取（若达标改默认值）+ config + 相关单测——**factcheck_judge.py（HHEM 推理路径）零改动**（裁判模型不重训不替换，本轮只校准阈值和尺子）
2. 阈值网格扫描是"后处理映射"，**HHEM 推理分数只算一次**（性能纪律）
3. 标注变更必须记录变更清单（哪些样本改了 verdict、为什么）——可审计
4. 判定器确定性优先；不引入 LLM-as-judge
5. 编码调 ponytail skill（最简可行：阈值扫描脚本 + 标注集扩展，不重写评测框架）
6. 存量测试零改动（改了=FAIL）
