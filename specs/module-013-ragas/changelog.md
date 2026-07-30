# 变更日志 — Module-013: RAGAS Evaluation System

## 变更概述
建立 RAG 量化评估体系：创建 30 题 QA 测试集（覆盖 6 个类别）、RAGAS 评估脚本（4 项指标：faithfulness、answer_relevancy、context_precision、context_recall）、控制台 + JSON 评分报告。评估脚本独立运行，不修改任何生产代码。

## 文件变更列表
| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| ai_service/eval/\_\_init\_\_.py | 新增 | 空包初始化文件 |
| ai_service/eval/dataset.json | 新增 | 30 题 QA 数据集（6 类别 x 5 题），含 question/ground_truth/category |
| ai_service/eval/evaluate.py | 新增 | 评估主脚本：调用 \_retrieve() + generate_answer()，运行 RAGAS 4 指标，输出控制台报告 + results.json |
| ai_service/requirements.txt | 修改 | 追加 ragas>=0.2.0 和 datasets>=3.0.0 |

## 关键设计说明

### 设计决策 1: 数据集覆盖 6 个类别
- **决策**: java_gc、java_concurrency、ai_llm、kafka、resume、comprehensive 各 5 题
- **原因**: resume 类别测试知识库的简历查询能力，comprehensive 测试综合通用知识，其余 4 个类别对应知识库主要文档领域。ground_truth 标注为示例参考值以管理预期。

### 设计决策 2: Judge LLM 使用 DeepSeek temperature=0
- **决策**: 构建 LangChain `ChatOpenAI` 实例指向 DeepSeek API（复用 settings 中的 deepseek_model/deepseek_api_key/deepseek_base_url），temperature 设为 0
- **原因**: temperature=0 保证评估结果的一致性和可复现性；复用项目已有配置避免硬编码 API Key

### 设计决策 3: 单题失败不中断评估
- **决策**: `run_single()` 函数用 try/except 包裹检索+生成逻辑，失败时返回 error 占位结果继续下一题
- **原因**: 30 题全部执行耗时较长（LLM Judge 约 5-10 分钟），单题失败不应导致全量重跑

### 设计决策 4: 输出两层报告（控制台 + JSON）
- **决策**: 控制台输出 Metrics Summary + Per-Category Breakdown（人类可读）；`eval/results.json` 含 metadata/summary/per_category/per_question 完整结构（机器可消费）
- **原因**: 控制台适合快速查看整体质量，JSON 适合 CI/CD 集成和趋势对比

### 设计决策 5: 基于文件路径解析数据集位置
- **决策**: 使用 `Path(__file__).resolve().parent` 定位 eval/ 目录，不依赖工作目录
- **原因**: 允许从任意目录执行 `python -m eval.evaluate`，避免 cd 到特定目录的隐性依赖

## 验证命令
| 验证项 | 命令 | 结果 |
|--------|------|------|
| Python 编译检查 | `python -m py_compile eval/evaluate.py` | PASS |
| 数据集有效性 | `python -c "import json; json.load(open('eval/dataset.json'))"` | 30 questions, 6 categories |

## 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-07-30 | 初始实现：dataset.json (30题) + evaluate.py + requirements.txt | Developer |
