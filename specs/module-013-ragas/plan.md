# M13: RAGAS 评估系统 — 项目计划

## 元信息

| 字段 | 值 |
|------|-----|
| 模块编号 | M13 |
| 模块名称 | RAGAS Evaluation System |
| 版本号 | 0.13.0-module-013 |
| 创建日期 | 2026-07-30 |
| 前置模块 | M5, M17 |
| 范围 | ai_service only |
| 目标 | 建立 RAG 量化评估：30 题测试集 + RAGAS 4 指标 + 评分报告 |

---

## 1. 需求概述

### 1.1 当前状态
- 零评估能力，无法衡量检索和生成质量

### 1.2 目标
1. 30 题 QA 数据集（6 类别 × 5 题）
2. 评估脚本：调用 `_retrieve()` + `generate_answer()` → RAGAS 打分
3. 评分报告：控制台 + `eval/results.json`

### 1.3 非目标
- 不修改 `engine.py` 等生产代码
- 不暴露 HTTP API
- 不做 CI/CD 集成

---

## 2. 技术方案

### 2.1 数据集 (`eval/dataset.json`)
- 6 类别：java_gc, java_concurrency, ai_llm, kafka, resume, comprehensive
- 每条含 `question`, `ground_truth`, `category`
- ground_truth 标注为"示例参考值，需人工审核"

### 2.2 评估脚本 (`eval/evaluate.py`)
```
for each question:
  docs = rag_engine._retrieve(question)
  answer = reflector.generate_answer(question, docs)
  collect {question, answer, contexts, ground_truth}
→ RAGAS evaluate() → console report + results.json
```

### 2.3 指标
- faithfulness / answer_relevancy / context_precision / context_recall
- Judge LLM 使用项目默认 DeepSeek（temperature=0）

---

## 3. 文件清单

| # | 文件 | 操作 |
|---|------|------|
| 1 | `ai_service/eval/__init__.py` | 新建（空） |
| 2 | `ai_service/eval/dataset.json` | 新建（30 题） |
| 3 | `ai_service/eval/evaluate.py` | 新建（评估主脚本） |
| 4 | `ai_service/requirements.txt` | 追加 ragas + datasets |

---

## 4. 风险

| 风险 | 应对 |
|------|------|
| 知识库部分问题无匹配文档 | 跳过该题或打分 0 |
| RAGAS LLM Judge 耗时 | 预期 5-10 分钟 |
| ground_truth 不准确 | 标注"示例值，需人工审核" |
