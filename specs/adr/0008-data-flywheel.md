# ADR-0008 — 数据飞轮方案（模糊样本收集 → 人工标注 → 增量训练）

- 状态：📋 方案已定，**暂不实施**（2026-08-10 决议：核心缺口是前端反馈未落库；实施顺序 P0 反馈落库 → P0 误判样本池 → P1 intent/充分性闭环 → P2 记忆校准）
- 日期：2026-08-10
- 背景：用户问"有没有收集模糊数据让人工标注做增量训练"。代码实测现状盘点后，给出五环节数据飞轮全景。本 ADR 记录现状缺口 + 飞轮方案 + 实施顺序。

## 现状盘点（代码实测）

| 环节 | 现状 |
|---|---|
| 评测误判样本 | ✅ **已有**——eval_runs 表存 `per_question`（label/predicted/correct），intent/sufficiency/golden 每次评测错误样本都在表里 |
| 前端 👍/👎 反馈 | ⚠️ **UI 有但没落库**——ChatMessage.tsx `feedbackRating: 'up'/'down'` + handleFeedback，只存页面内存（feedbackMap），**后端无 feedback 端点/表**，刷新即丢 |
| 主动收集模糊样本 | ❌ 无——无"低置信/边界样本自动入池"机制 |
| 人工标注流程 | ❌ 无——标注集（intent 100 / sufficiency 100）是手工造的，非生产回流 |
| 增量训练 | ⚠️ 接口有但没数据——`IntentClassifier.fit()` 已实现（ADR-0003 L4），飞轮数据未接入 |

**核心缺口：前端反馈未落库**——👍/👎 是免费的人工标注信号，现在白白丢在页面内存里。

## 五环节飞轮全景（收集 → 标注 → 增量训练）

### A. 意图分类（intent）— ADR-0003 L4，最快闭环 ★★★★
- 收集：golden_intent 误判样本（混淆矩阵非对角线）+ 生产日志 `intent≠knowledge 且低置信` + 👎 反馈
- 标注：人工标三类意图（分类题，最简单）
- 增量：`IntentClassifier.fit()` **接口已就绪**——标注攒够（几十条边界）→ 并入重训 → 分类器从"默认关"转正

### B. 反思充分性（sufficiency）— ADR-0005 层 4 ★★★
- 收集：golden_sufficiency 误判样本（重点 insufficient 漏判=判充分但实际不充分，最致命）+ 👎 反推"检索不充分但硬答"
- 标注：人工标"这份检索结果够不够回答"
- 增量：层 4 充分性分类器（未实现），标注集即训练集

### C. 检索相关性（retrieval）— 不训练，调参 ★★★
- 收集：eval_runs correct=False + 👎 后反查检索结果
- 标注：标"这篇文档和问题相关吗"（重排/检索 ground truth）
- 用途：阈值扫描（abs_cosine 0.4 校准）、分块消融数据基础

### D. 答案可信度（faithfulness）— verify_answer ★★
- 收集：👎 反馈 + verified claims 中 unsupported 占比高的回答
- 标注：标"这条回答/引用对不对"
- 用途：答案质量评测集扩充 + 幻觉检测调优

### E. 记忆提取（extract_facts）— ADR-0007 ★★
- 收集：LLM 提取 facts 抽样 + 👎 反馈
- 标注：标"这条该不该进长期记忆"（**校准 importance**——解决 ADR-0007 问题 1"LLM 自报不可信"）
- 增量：bge-m3 + 逻辑回归 importance 分类器

## 飞轮通用流程

```
生产数据（误判/低置信/👎）
    → 收集入库（feedback 表 / 误判样本池）
    → 人工标注（定期批量，表格或标注工具）
    → 增量训练（L4 fit() / 分类器重训 / 阈值重扫）
    → 评测验证（--compare 对比提升）→ 上线
    → 新的误判/反馈 → 循环
```

## 推荐实施顺序

1. **P0 · feedback 落库**（半天）：前端已有 UI，加后端 `POST /ai/feedback`（message_id + rating + query/answer 快照）存表——启动整个飞轮的前提
2. **P0 · 误判样本自动导出"待标注池"**（半天）：从 eval_runs 拉 correct=False 生成待标注清单（intent + sufficiency 各一批）
3. **P1 · intent 闭环**：标注 → `IntentClassifier.fit()` 重训 → golden 验证 → 上线（接口现成，最快见效）
4. **P1 · 充分性闭环**：标注 → 建层 4 分类器 → 验证
5. **P2 · 记忆 importance 校准**：extract_facts 抽样标注 → importance 分类器

## 面试话术

> "我的数据飞轮现状是：评测误判样本已经在 eval_runs 里（per_question 带 correct 标记），前端也有 👍/👎 UI，但反馈没落库、没接入增量训练——这是我最想补的缺口。飞轮可以套在五个环节：意图分类最快（L4 分类器 fit() 接口已就绪，标注攒够直接重训）；反思充分性次之（标注集已有 100 条，层 4 分类器待建）；检索相关性用于阈值校准；答案可信度用于幻觉调优；记忆提取用来校准 importance。第一步是反馈落库，把 👍/👎 变成免费标注信号，之后每个环节都是'收集 → 标注 → 重训 → --compare 验证 → 上线'的闭环。"

## 与既有决策的关系

- 复用 eval_runs 版本化（--compare 验证增量训练效果）、golden 评测集（intent 100 / sufficiency 100）
- 复用 ADR-0003 L4 `IntentClassifier.fit()`（飞轮终点）、ADR-0005 层 4（充分性分类器）、ADR-0007（importance 校准）
- 方法论与 ADR-0003/0005/0006/0007 一致：先度量后干预、评测驱动、诚实交代缺口
