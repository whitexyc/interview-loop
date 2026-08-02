# 变更日志 — Module-030: 重排性能优化 + LangGraph 实验端点

## 变更概述
① 重排模型由 Qwen3-Reranker-0.6B（生成式，CPU 每对 ~6s）切换为 bge-reranker-v2-m3
（分类式 CrossEncoder，实测 5 pair 热推理 1.27s，快约 12 倍），根治真实链路被重排阻塞的问题。
② 新增 LangGraph 版 ReAct 循环（StateGraph 编排）并暴露实验端点 /ai/rag/chat/agent-lg（SSE），
与手写 react.py 并存（不动手写循环，零回归），坐实 LangGraph 技术栈。

## 文件变更列表
| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| `ai_service/rag/reranker.py` | 修改 | 模型路径 → bge-reranker-v2-m3；predict 传 (query, doc) 裸 pair；移除 Qwen3 chat message 适配；保留缺权重校验（module-018） |
| `ai_service/rag_metadata_tables.sql` | 修改 | rag_config.reranker_model → BAAI/bge-reranker-v2-m3 |
| `ai_service/create_metadata_tables.py` | 修改 | INITIAL_CONFIG.reranker_model 同步 |
| `ai_service/agent/langgraph_react.py` | 新增 | LangGraph StateGraph 版 ReAct 循环（llm_call / execute_tools / finalize / fallback 节点 + 条件路由） |
| `ai_service/main.py` | 修改 | 新增 POST /ai/rag/chat/agent-lg（SSE，事件与 agent 一致） |
| `ai_service/tests/test_rerank_langgraph.py` | 新增 | module-030 单测 17 个（重排模型/裸 pair/排序 + LangGraph 预算/工具/路由 + SSE 端点） |

## 关键设计说明
### 设计决策 1: 重排模型切换为 bge-reranker-v2-m3
- 决策: `_LOCAL_MODEL_DIR` → `models/bge-reranker-v2-m3`；加载 `CrossEncoder(model_dir)`；
  `predict` 直接传 `(query, doc)` 裸 pair；删除 Qwen3 的 chat message +
  `add_generation_prompt=True` 适配代码。
- 原因: bge 是标准分类式 CrossEncoder，sentence-transformers 原生支持裸 pair；实测
  5 pair 热推理 1.273s（Qwen3 需 30s），12 倍提升。缺权重校验（module-018 设计）保留：
  `_validate_model_dir` 缺失目录/权重时抛 RerankerException（不回退 HF 在线加载）。
- 注意: bge 分数接近 1.0（sigmoid 饱和，实测 0.95-0.97），排序仍正确、区分度低是已知特性，
  校准留待后续（不阻塞）。

### 设计决策 2: LangGraph 版 ReAct 并存
- 决策: 新增独立 `agent/langgraph_react.py`，用 StateGraph 编排 ReAct：
  `llm_call`（调 chat_with_tools）→ 条件路由（有 tool_call → execute_tools，无 → finalize）
  → `execute_tools`（执行工具 + 结果追加）→ 条件路由（工具数 < budget → 回 llm_call，
  否则 → fallback 兜底）；预算=0 直接 LLM chat 回答。
- 原因: 不与现有手写 while 循环（react.py）耦合，零回归；复用现有 ReactContext /
  _build_messages / _assistant_message / ToolRegistry（不重复实现工具逻辑），行为与手写版
  对齐（预算截断、reasoning_content 回传、docs 累积、工具失败返回空串）。

### 设计决策 3: SSE 事件收集器（events sink）
- 决策: 节点把 token/tool_call/tool_result/done 事件追加到 `state["events"]` 列表，
  `langgraph_react_loop` 在 `ainvoke` 结束后按序产出。
- 原因: 图内单次 ainvoke 执行，无法直接对 SSE 流 yield；事件顺序由节点追加顺序保证
  （token → tool_call/tool_result → done），与手写 react_loop 完全一致。已验证
  langgraph 1.2.10 的 ainvoke 返回最终 state 含完整 events 列表。

### 设计决策 4: plan.md 文件清单中 graph.py 的调整
- 决策: 未改动 `ai_service/rag/graph.py`（固定流水线 LangGraph，职责不同），改为新增
  独立 `agent/langgraph_react.py`。
- 原因: 与任务指令一致（新增 langgraph_react.py 而非向 graph.py 补节点）；graph.py 是
  意图→检索→反思→生成的固定 RAG 流水线，向其中补 ReAct 节点会混入不相关职责、增加回归风险。

## 验证命令
| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| 新增单测 | `python -m pytest tests/test_rerank_langgraph.py` | 17 passed |
| 全量回归 | `python -m pytest tests/` | 180 passed / 2 既有 async 技术债务失败（test_engine.py 缺 pytest-asyncio，module-018 起备案，无新增失败） |
| 语法检查 | `python -m py_compile rag/reranker.py agent/langgraph_react.py main.py create_metadata_tables.py tests/test_rerank_langgraph.py` | OK |
| 真实重排性能 | 见 `_m030_rerank_test.py`（已清理） | 5 pair 热推理 1.273s < 3s；冷启动（含 2.17GB 加载）5.6s 一次性 |
| LangGraph 端点真实调用 | 见 `_m030_lg_endpoint_test.py`（已清理） | HTTP 200，事件 tool_call×4/tool_result×4/token×2/done，answer 真实（Java 线程池），sources 5，0 error |

## 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-02 | 初始实现 | Developer |
