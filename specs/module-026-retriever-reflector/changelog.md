# 变更日志 — Module-026: 并发修复 + Reflector 改造

## 变更概述
Module-026 分两部分：① 修复 `retriever._execute` 在单 asyncpg 连接上 gather 并发跑 FTS + 向量导致的偶发 `concurrent operations are not permitted`（冷缓存结果不稳定 0 vs 2 篇）；② 改造 Reflector：反思从硬编码 `deepseek` 改为走 fallback 降级链（消除单点），并改用低温度 0.1 保证结构化 JSON 稳定，生成保持 0.7。

## 文件变更列表
| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| `ai_service/rag/retriever.py` | 修改 | `_execute` 两路独立 session 并行 + 外部 session 共享串行 + 新增 `_search_serial` 辅助方法；`retrieve` 不再预建 session（交由 `_execute` 按需创建） |
| `ai_service/llm/client.py` | 修改 | 各客户端构造器支持 `temperature` 参数（默认 0.7）；`LLMFactory.get_client(provider, temperature=None)` 按 `(provider, temperature)` 缓存；`FallbackClient` 温度透传降级链各供应商 |
| `ai_service/agent/reflector.py` | 修改 | `_provider = provider or "fallback"`；反思 `temperature=0.1`、生成 `temperature=0.7`；更新模块 docstring |
| `ai_service/tests/test_retriever_concurrency.py` | 新增 | 并发独立 session / 外部串行 / 单路降级 / session 创建失败降级单测（6 例） |
| `ai_service/tests/test_reflector_temperature.py` | 新增 | Reflector provider/温度 / LLMFactory 低温度创建 / fallback 温度贯穿单测（7 例） |

## 关键设计说明
### 设计决策 1: 并发修复 — 独立 session 并行（方案 A）
- 决策: `_execute` 未传外部 session（默认路径）时为 FTS / 向量各开独立 `async_session_factory()` session，仍用 `asyncio.gather(..., return_exceptions=True)` 并行；传外部 session 时共享连接串行；独立 session 创建失败降级为单共享 session 串行。
- 原因: asyncpg 单连接禁止并发操作，旧实现 gather 在同一 session（同一连接）上并发跑两路导致竞态。独立 session 各占独立连接，既消除竞态又保留并行性能（不串行化）。
- 单路降级语义保留：并行路径 `return_exceptions=True`、串行路径 `_search_serial` 内 try-except，一路失败不影响另一路。

### 设计决策 2: Reflector 低温度 + 走降级链
- 决策: `Reflector._provider = provider or "fallback"`；反思 `LLMFactory.get_client("fallback", temperature=0.1)`；生成/流式生成 `get_client("fallback", temperature=0.7)`。
- 原因: 反思是结构化 JSON 判断，低温度 0.1 提高输出确定性/稳定性；消除硬编码 `"deepseek"` 单点，降级链自动切换。生成保持 0.7 不受影响（主推理不变）。
- `LLMFactory.get_client` 新增 `temperature` 参数，实例按 `(provider, temperature)` 缓存；`None` = 默认 0.7，其他调用方（casual chat / HyDE / graph / router）行为不变。
- `FallbackClient(chain, temperature)` 将温度透传给链上各供应商（`get_client(provider, temperature=self._temperature)`），实现"低温度贯穿降级链"——降级到 qwen/zhipu 时反思仍用 0.1。

### 设计决策 3: 降级链序（plan 叙述与全局配置的取舍）
- 决策: 采用全局 `PW_FALLBACK_CHAIN`（当前 `qwen,zhipu,deepseek`），未改动全局默认链序。
- 原因: plan 叙述 "deepseek→qwen→zhipu（deepseek 优先）" 与全局配置 `qwen,zhipu,deepseek`（module-018 默认，Qwen 首选）矛盾，且验收标准只要求 `Reflector._provider = fallback` + 温度 0.1（不校验链序）。deepseek 当前未配置 API key（构造即抛 LLMException），实际生效主模型为 qwen，与现状一致；改动全局默认链会无谓影响 casual chat / HyDE / graph 等其他 fallback 调用方，超出本模块范围。
- 若需 deepseek 优先，可通过 `PW_FALLBACK_CHAIN=deepseek,qwen,zhipu` 配置实现（Reflector 与全链路共用同一链，行为一致）。

### 边界与降级
- 外部传入 session：共享连接串行执行（兼容，不破坏现有调用）。
- 降级链全失败：`FallbackClient.generate/chat/stream` 抛 `LLMException`，Reflector.check_sufficiency 捕获后默认 `sufficient=true`（既有行为不变）。
- 低温度客户端构造失败：`LLMFactory` 构造异常直接上抛（API key 缺失等），由调用方既有异常处理兜底。

## 验证命令
| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| 语法编译 | `python -m py_compile rag/retriever.py llm/client.py agent/reflector.py tests/test_retriever_concurrency.py tests/test_reflector_temperature.py` | COMPILE_OK |
| 新增单测 | `python -m pytest tests/test_retriever_concurrency.py tests/test_reflector_temperature.py` | 13 passed |
| 全量回归 | `python -m pytest tests/` | 114 passed, 2 failed（既有 test_engine.py async 技术债务，module-018/024/025 已记录，非本次回归） |
| 并发稳定性（真实 DB，5 次冷缓存） | `python -c "...hybrid_retriever.retrieve('Java线程池', top_k=3) ×5..."` | 5 次均 3 篇、ids 一致 [17,47,48]，无 concurrent operations |
| Reflector 温度/provider | `python -c "...reflector._provider; LLMFactory.get_client('fallback', temperature=0.1)._temperature..."` | provider=fallback, reflection=0.1, generation=0.7, default=0.7 |
| 低温度贯穿降级链 | `python -c "...LLMFactory.get_client('qwen', temperature=0.1)._llm.temperature..."` | qwen/zhipu 反思 0.1、默认 0.7 |

## 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-01 | 初始实现（并发修复 + Reflector 低温度/降级链） | Developer |
