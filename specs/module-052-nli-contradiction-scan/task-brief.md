# Module-052 任务简报：NLI 矛盾扫描前置决策（v2）

> 📋 **复测进行中（module-057 复测 v2）**——数据集已扩充至 86 条（contradiction 53 / internal_contradiction 23 含 8 条多句混合），claim 用真实 LLM 答案句子 + DB 真实检索片段；`eval/retest_nli.py` 阈值扫描 + 句级拆解 + kappa；**门槛 kappa ≥ 0.7 放行替换 mDeBERTa，未达则降级双轨（NLI 只做矛盾扫描）**——放行判定未定论。
> 自包含执行简报。接手方不需要额外对话上下文，按步骤执行即可。所有"已知事实"均已确认，无需重新调研。
> v2 修订：补充数据源口径、指标对比口径、标注复用、替换成本、环境前置。

## 一、任务背景

**项目**：Agentic RAG 技术文档知识库（`.claude/worktrees/m8-knowledge-panel/ai_service`，FastAPI + asyncpg + pgvector + Apache AGE）。已实现意图路由/分诊改写/混合检索/反思三闸门/语义重排/流式生成/**幻觉检测**（module-050/051：LLM 拆句 + HHEM-2.1-Open 判分 + 阈值映射三态）。

**要推进的升级**（ADR-0010 P1-③）：**矛盾扫描**——用 NLI 检测①答案 claim 之间自相矛盾②claim 与"未引用文档块"矛盾（防 cherry-pick）。**上马前有 5 个未决疑问，必须先做前置决策，否则可能白做/返工。本任务 = 完成前置决策。**

## 二、已知事实（勿重新调查）

| # | 事实 |
|---|---|
| 1 | HHEM-2.1-Open 已接入 verify_answer（110M，中文 Acc 0.77，CPU ~1.5s/对） |
| 2 | HHEM kappa = 0.3252 < 0.7 未达标；原因=阈值 0.7/0.3 偏严 + 对"部分覆盖"判一致偏乐观；校准方向=阈值下调 |
| 3 | **MiniCheck 教训**：英文基准更强但中文 supported 召回仅 2%——"英文高分≠中文能用" |
| 4 | DeBERTa-v3-large-mnli 纯英文 MNLI 训练，中文未验证，不能直接上 |
| 5 | **mDeBERTa-v3 多语言 NLI**（`MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`）：训练 26 语言含中文（zh），XNLI 中文 86.4%，~276M/~1.1GB，MIT 开箱即用，有 ONNX 版 |
| 6 | **module-050 实测流程可复刻，但其数据源是 `SUFFICIENCY_DATASET`（注入的代表性文档，非真实检索结果）——当时已诚实标注为"代理度量"** |
| 7 | 环境坑：huggingface.co 本机不可达；hf-mirror 对 Python 有 308 问题；module-050 用 **curl resolve 直链 + `-C -` 续传** 下载；HHEM 4.x 检查点在 transformers 5.x 踩过 embed_tokens 键展开坑（mDeBERTa 兼容性未验证） |

## 三、任务步骤（按序，每步有通过标准）

### WP-0 环境准备（🔴 阻塞，最先做）
- **模型下载**：照 module-050 套路——curl resolve 直链 + `-C -` 续传（不要用 huggingface.co 直连，不要依赖 hf-mirror 的 Python 接口）
- **离线加载验证**：transformers 5.x 加载 mDeBERTa-v3，跑 2-3 对已知中文用例，**分数与 HF README 参考值核对**（防 embed_tokens 类兼容坑）
- **资源实测**（顺带出数据）：峰值内存 + **25 对批量 CPU 耗时**（防超 15s 超时哲学）；全机模型账确认余量：bge-m3(~1GB) + reranker(2.17GB) + HHEM(0.6GB) + mDeBERTa(1.1GB) ≈ **~5GB**
- **通过标准**：模型可加载、分数合理、耗时/内存有实测数字

### WP-A 中文实测（🔴 阻塞）
- **数据源（口径必须声明，防"看似真实"）**：
  - **主数据源 = SUFFICIENCY_DATASET（module-050 同源，注入的代表性文档）**——这是**代理度量，不是真实检索结果**；选型对比必须同口径（否则"mDeBERTa vs HHEM 谁好"无法比）
  - 真实数据（golden 112 题的检索结果 / 真实对话）作为**可选增强**，依赖 DB 环境可用（此前缺迁移列不可用）——**brief 执行时如 DB 仍不可用，如实标注，不硬造**
- **标注规范（一套两用，省一半成本）**：人工一次标**三分类**（entailment / contradiction / neutral）→ HHEM 支持度从三分类**映射**得出（entailment→supported，contradiction→unsupported，neutral→inferred）——两套标签天然对齐可比
- **指标口径（防评审扯皮）**：
  - **主对比指标 = Cohen's kappa**（天然校正随机一致：HHEM 二分类瞎猜基线 50% vs NLI 三分类基线 33%，**直接比 Accuracy 不公平**）
  - Accuracy 仅作参考，且**注明口径**：或把 NLI 二值化（entailment vs 其他）后算对齐 Acc 再比
- **通过标准**：mDeBERTa 的 **kappa 达到或接近 HHEM 水平**（主指标）；Acc 参考并注明口径

### WP-B 选型决策（🔴 阻塞，WP-A 数据出来后做）
```
mDeBERTa 中文 kappa ≥ HHEM 水平？
├─ 是 → 评估"统一换 NLI 三分类"。若选择替换，必须包含（替换不是免费的）：
│       ① 三态映射定义：entailment→supported / contradiction→unsupported / neutral→inferred
│          ⚠️ 注意语义漂移：neutral 归 inferred 会把"存疑"并入"推断"，前端色标语义改变——需确认可接受
│       ② 重跑 golden_factcheck kappa 复测（验证器评测闭环不能跳过）
│       ③ 重新校准阈值（0.7/0.3 是给 HHEM 分数校准的；NLI 概率分布不同，要重新阈值扫描）
└─ 否 → 保持双轨：HHEM 管支持度（现状不动）+ NLI 只做"矛盾扫描"这一件事
        └─ 若 NLI 中文太差 → 矛盾扫描降级为 LLM 判断，或放弃该功能（记录否决理由）
```
- **通过标准**：产出明确结论（双轨 / 替换 / 放弃），写回 ADR-0010

### 放行后实施 P1-③ 矛盾扫描（仅当前置决策通过才动代码）
- 扫描范围**必须限制**：**只扫 top-5 未引用块 × 每条 claim 最多 5 对 = 25 对上限**，批量推理（防超 15s）
- "未引用块"排序：**实施时定**（建议按检索分数取未引用 top-5），brief 只约束 25 对上限
- 实现复用 verify_answer 现有模式：`asyncio.to_thread` + `threading.Lock` + 失败静默回退
- 触发重生成的阈值 **40% 标注为经验初值，纳入阈值扫描校准**

## 四、纪律项（违反 = 返工）

1. **先完成 HHEM 校准**（threshold_scan 调阈值，目标 kappa>0.7）再叠加 NLI——守住 ADR 自定原则"kappa>0.7 才信这个裁判"
2. **重生成闭环（P2）必须等验证异步化之后**再上——否则用户等待 = 生成 + 验证 + 修订×2 轮，延迟爆炸
3. **文档状态行与正文叙事统一**：状态行已标 ✅ P0-② 已实施，正文"分阶段方案"不能还按未实施写
4. **口径声明不可省**：WP-A 报告必须写清"代理度量（非真实检索）"+"kappa 主指标、Acc 注口径"——产出可审计的数字，不产出"看似真实"的数字

## 五、交付物

1. WP-A 实测报告：**数据源声明 + 标注规范 + kappa/Acc（注口径）+ 与 HHEM 对比结论 + 耗时/内存实测**
2. WP-B 选型结论：双轨 / 替换（含三态映射+kappa 复测+阈值校准）/ 放弃，更新 ADR-0010
3. P1-③ 放行决定（通过才动代码；不通过则记录否决理由）
