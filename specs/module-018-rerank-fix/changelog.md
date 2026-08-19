# 变更日志 — Module-018: Rerank 重排修复（切换 Qwen3-Reranker）

## 变更概述
重排模型从 `models/bge-reranker-v2-m3`（缺权重，导致 CrossEncoder 加载失败、重排静默降级为原始排序）切换为本地 `models/Qwen3-Reranker-0.6B`。新增权重文件存在性校验：本地目录不存在或缺权重文件时**明确抛 RerankerException**，不再回退 HuggingFace 在线加载。`rerank()` 接口签名不变（`query, documents, top_k=5 → list[dict]`，每项含 `rerank_score`）。同步更新 `rag_config.reranker_model` 的三处配置源（代码 INITIAL_CONFIG、SQL 脚本、数据库实际值）。

**关键发现（超出 plan 假设）**：plan §6.2 假设 "sentence-transformers 5.6.1 原生支持 Qwen3-Reranker，predict 接口直接可用"，但实测用 `(query, doc)` 裸 pair 调用 predict 时，本地 chat template 不认识 ST 的 "query"/"document" 角色，渲染为空串 → input_ids 为 0 token → 推理崩溃（`cannot reshape tensor of 0 elements`）。已改为传 user 角色 chat 消息 + `add_generation_prompt=True`，使最后 token 位置的 logits 可用于 LogitScore（yes/no）相关性打分，实测排序正确。

## 文件变更列表
| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| `ai_service/rag/reranker.py` | 修改 | `_LOCAL_MODEL_DIR` → `models/Qwen3-Reranker-0.6B`；`_DEFAULT_MODEL` 不再回退 HF；新增 `_validate_model_dir()` 权重校验；加载/推理失败统一抛 RerankerException；predict 改为 user 角色 chat 消息 + `add_generation_prompt` |
| `ai_service/create_metadata_tables.py` | 修改 | `INITIAL_CONFIG` 中 `reranker_model` → `Qwen/Qwen3-Reranker-0.6B` |
| `ai_service/rag_metadata_tables.sql` | 修改 | `rag_config.reranker_model` 默认值同步为 `Qwen/Qwen3-Reranker-0.6B` |
| `ai_service/test_m18.py` | 新增 | Rerank 自测脚本（排序、边界、缺权重报错），沿用 test_m17.py 约定 |
| `memory/project-context.md` | 修改 | module-018 状态 → 👀 待审查；记录 Qwen3-Reranker 决策 |

## 关键设计说明
### 设计决策 1: 缺权重明确报错，不回退 HuggingFace
- 决策: 本地模型目录不存在或缺权重文件（`model.safetensors` / `pytorch_model.bin`）时，`_validate_model_dir()` 直接抛 `RerankerException`；`_DEFAULT_MODEL` 恒为本地路径。
- 原因: 用户明确要求"直接本地，不回退"。此前 bge 模型缺权重时 CrossEncoder 加载失败被上层静默吞掉，重排从未真正生效。让问题可见而非静默降级。

### 设计决策 2: Qwen3-Reranker 需 chat 消息格式调用（根因修复）
- 决策: `predict` 不再传 `(query, doc)` 裸 pair，而是构造 `[{"role": "user", "content": "<query>\n<doc>"}]` 消息，并传 `processing_kwargs={"chat_template": {"add_generation_prompt": True}}`。
- 原因: Qwen3-Reranker-0.6B 是生成式重排模型（`Qwen3ForCausalLM`），ST 以 text-generation + LogitScore（`logit("yes")-logit("no")`）打分，要求最后 token 位置是 assistant 生成提示。本地 chat template 只处理 user/system/assistant/tool 角色；ST 的 query/document 角色会渲染为空串（0 token），导致 reshape 崩溃。实测排序：id=1(0.0237) > id=3(0.0179) > id=2(0.0041)，与预期一致。

### 设计决策 3: 接口保持稳定
- 决策: `rerank(query, documents, top_k=5)` 签名与返回结构不变（list[dict]，每项带 `rerank_score`，按分数降序）。
- 原因: 下游（engine._rerank、RAGAS 评估、Graph 归一化）依赖该接口与 `rerank_score` 字段名，保持不回归。

### 设计决策 4: 配置三处同步
- 决策: `rag_config.reranker_model` 同时更新代码 INITIAL_CONFIG（`create_metadata_tables.py`）、SQL 脚本（`rag_metadata_tables.sql`）与数据库实际值（UPDATE 已执行并确认）。
- 原因: 建表/刷新脚本可幂等重跑，数据库与脚本保持一致，运维查询（psql SELECT）能反映真实模型。

## 验证命令
| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| 加载 + 排序 | `cd ai_service && python test_m18.py` | `ALL TESTS PASSED`，输出 `1 0.0237 / 3 0.0179 / 2 0.0041`，id=1 排最前 |
| 缺权重报错 | `test_m18.py` Test 1（/nonexistent 路径） | `PASS: raised RerankerException` |
| 数据库更新 | psql SELECT `rag_config.reranker_model` | `Qwen/Qwen3-Reranker-0.6B`（已确认） |
| 回归 | `python -m pytest tests/test_schemas.py -q` | `4 passed` |
| 回归 | `python test_m17.py` | `ALL TESTS PASSED` |

> 注: `python -m pytest tests/ -x` 中 test_engine.py 的 async 用例因未安装 pytest-asyncio 插件而失败，属既有环境问题，与 module-018 无关。

## 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-01 | 初始实现：模型路径切换 + 缺权重报错 + 配置同步 + chat 消息格式调用修复 | Developer |
