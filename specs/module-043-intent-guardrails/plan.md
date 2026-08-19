# 功能规格说明书 — Module-043: 输入防护 + Intent 校验体系

> Planner | 2026-08-09

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-043 |
| 模块名称 | 输入防护 + Intent 校验体系（三端点加固 + L1-L4） |
| 版本号 | 0.43.0-module-043 |
| 优先级 | P1（校验只覆盖 ChatRequest，其余端点裸奔；intent 只有值合法性无类正确性） |
| 预估代码量 | 5 个工作包，≤ 500 行 + 评测数据 + 训练脚本 |

---

## 2. 需求

### 2.1 现状缺口

| 缺口 | 现状 | 出处 |
|------|------|------|
| 三端点无输入校验 | `SearchRequest.query` / `MemorySaveRequest.content` / `MemoryRecallRequest.query` 无长度约束，`/ai/memory/save` 直接落库 | ADR-0001 Q3（已拍板：全加） |
| intent 只有"值合法" | `router.py` 只校验 intent ∈ 白名单，不校验"类正确"（该不该走 knowledge） | ADR-0003 |
| 无度量手段 | 不知道 intent 误判率现状，无法量化改进收益 | ADR-0003 L1 |
| 无前置/后置校验 | 漏检（答非所问）与多检（白跑检索）均无拦截 | ADR-0003 L2/L3 |
| 分类器不可换 | 分类决策主体固定为 LLM | ADR-0003 L4 |

### 2.2 目标（L1-L4 全部落地，按 ADR-0003 修订版）

1. **WP1 三端点加固**：search/memory-save/memory-recall 补 `max_length=2000`（与 ChatRequest 同值，同一滥用面）
2. **WP2 L1 度量**：intent 评测集（扩 golden：闲聊/实时/边界易混样本）+ 混淆矩阵输出 + eval_runs 版本化
3. **WP3 L2 前置校验（修订版）**：LLM 低置信触发 + **确定性信号确认**（FTS 术语命中 / 图谱实体命中 / 规则表）——**禁止 LLM 二次确认（同源复核已否决，ADR-0003 修订记录）**
4. **WP4 L3 后置校验**：走 knowledge 后 top-1 绝对余弦 < 0.3 → 疑似误判标记（先度量后干预，不改主路径）
5. **WP5 L4 分类器**：bge-m3 冻结特征 + 逻辑回归头（~1025 参数）+ 训练脚本 + 校准概率 + 可插拔开关（router 可注入）

### 2.3 验收场景

```
场景 1：三端点超长拒绝
  假设 POST /ai/rag/search query > 2000 字符
  那么 返回 422，不进业务逻辑（同 ChatRequest 模式）

场景 2：L2 低置信 + 术语命中 → 修正为 knowledge
  假设 "你知道 GC 是什么吗"（LLM 低置信判 casual_chat，但含知识库术语 "GC"）
  那么 FTS/图谱/规则任一信号命中 → intent 修正为 knowledge

场景 3：L2 低置信 + 信号未命中 → 保持原判
  假设 "你好呀"（低置信 casual_chat，无术语命中）
  那么 保持 casual_chat

场景 4：L2 任何环节失败 → 保守 knowledge
  假设 信号查询异常
  那么 回退 knowledge（宁多检不漏检）

场景 5：L3 后置反证
  假设 走 knowledge 检索后 top-1 绝对余弦 < 0.3
  那么 标记 suspected_misclassify（steps 可观测），不阻塞回答

场景 6：L1 混淆矩阵
  假设 跑 eval/golden_intent.py
  那么 输出 per-class 精确率/召回率/混淆矩阵 + eval_runs 落库（git_commit+配置快照）

场景 7：L4 分类器可切换
  假设 训练脚本产出模型（golden 集训练）
  那么 intent_classifier 可加载 predict 校准概率；router 配置开关可注入，默认仍用 LLM
```

---

## 3. 技术方案

### 3.1 工作包与涉及文件

| WP | 内容 | 文件 | 操作 |
|----|------|------|------|
| WP1 | 三端点 max_length=2000 | `ai_service/rag/schemas.py` | 修改（3 行 Field） |
| WP1 | 对齐 test_schemas_validation.py 风格补用例 | `ai_service/tests/test_schemas_validation.py` | 修改（+3 用例） |
| WP2 | intent 评测集 + 混淆矩阵 + eval_runs | `ai_service/eval/golden_intent.py` | 新建 |
| WP2 | 测试 | `ai_service/tests/test_golden_intent.py` | 新建 |
| WP3 | L2 前置校验（低置信触发 + 确定性信号） | `ai_service/agent/router.py` | 修改 |
| WP4 | L3 后置反证（top-1 余弦 < 0.3） | `ai_service/rag/engine.py` 或 retriever 调用点 | 修改 |
| WP5 | L4 分类器（bge-m3 冻结 + 逻辑回归） | `ai_service/agent/intent_classifier.py` | 新建 |
| WP5 | 训练脚本 | `ai_service/eval/train_intent_classifier.py` | 新建 |
| WP3+5 | L2/L4 测试 | `ai_service/tests/test_intent_validation.py` | 新建 |

### 3.2 核心逻辑

#### WP3 L2 前置校验（ADR-0003 修订版 — 关键实现约束）

```
classify() 返回后：
  if intent != "knowledge" and confidence < 0.5:
      confirmed = await deterministic_confirm(query)   # 与 LLM 完全无关
      if confirmed:  intent = "knowledge"              # 术语/实体命中 → 涉及知识库
  任何异常 → 保守 knowledge
```

确定性信号（按优先级，任一命中即确认）：
1. **FTS 术语命中**：jieba 分词 query → 倒排索引（`documents.search_tokens`）快速匹配，命中 ≥1 知识库专有术语
2. **图谱实体命中**：query 提取实体 → entities 表命中
3. **规则表**：闲聊/实时特征词（"几点""天气""你是谁"）→ 命中则**不**修正

**红线**：确认动作不得再调 LLM（同源复核已否决）；信号查询失败 → 保守 knowledge。

#### WP4 L3 后置校验

- 检索精排后取 top-1，`abs_cosine < 0.3` → `suspected_misclassify = True`
- 写入 ChatSteps（可观测），不改回答路径（先度量后干预，干预留给后续模块）
- 复用 module-037 的 `abs_cosine` 字段（`d.get("abs_cosine", 0.0)`）

#### WP5 L4 分类器

- `intent_classifier.py`：bge-m3 冻结当特征提取器（复用现有嵌入通道）+ sklearn 逻辑回归头（~1025 参数）；`fit()` / `predict_proba()` 输出校准概率
- 训练脚本：从 golden_intent 评测集加载样本训练，模型落盘（如 `.ua/` 或 data 目录，按现有模型存放约定）
- router.py 增加可插拔注入（配置开关），**默认仍用 LLM**；L4 上线即替换决策主体，L2 触发门槛从此可信（ADR-0003 修订记录）
- **边界**：真实飞轮数据（👍👎 反馈）未积累，先以 golden 集训练；训练/加载失败一律回退 LLM 分类，不阻断主链路

### 3.3 降级

| 场景 | 处理 |
|------|------|
| L2 信号查询失败 | 保守 knowledge（宁多检不漏检） |
| L4 模型缺失/加载失败 | 回退 LLM 分类，零影响 |
| L3 反证逻辑异常 | 记录日志，不阻塞回答 |
| 三端点超长 | 422 + 明确错误消息（同 ChatRequest） |

---

## 4. 依赖

- module-042（ChatRequest 校验模式，WP1 对齐其风格）
- module-039（reflector 反思逻辑，L3 镜像 check_sufficiency）
- module-037（abs_cosine 字段，L3 复用）
- module-038（golden 评测集结构与扩展工具，WP2 对齐）
- ADR-0001（Q3 决策）、ADR-0003（L1-L4 方案 + L2 修订记录）

## 5. 已知边界（写入验收）

- **L4 数据约束**：无真实飞轮数据，训练用 golden 集；飞轮接口预留，数据到位后重训
- **预存失败**：`test_identity.py` top_k 3 个失败为环境既有问题，不计入本模块
- **worktree 未提交改动**（react.py/main.py 等，来自其他会话）：**不得 stage**，提交只含本模块文件
