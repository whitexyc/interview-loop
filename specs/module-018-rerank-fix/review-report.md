# 审查报告 — Module-018: Rerank 重排修复（切换 Qwen3-Reranker）

## 1. 审查结论

- 结论: **通过**（附 3 项非阻塞改进建议）
- 审查时间: 2026-08-01
- 审查人: Reviewer
- 审查耗时: 约 25 分钟

> 说明：本次审查已读取变更文件完整内容（非仅 diff），并实测验证异常路径（缺权重 / 缺目录均正确抛出 RerankerException，不回退 HF）、`py_compile` 语法检查通过、模型目录 `ai_service/models/Qwen3-Reranker-0.6B/model.safetensors`（1.19GB）存在。验收标准逐项核对通过。3 项建议改进（见 2.2）不影响本模块验收，建议在后续迭代处理。

## 2. 问题列表

### 2.1 阻塞问题（必须修复才能通过）

无。

### 2.2 建议改进（不阻塞但建议修复）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | `ai_service/rag/reranker.py` | L137-139（触发源 L82-89） | `rerank()` 的 `except Exception` 会把 `_validate_model_dir()` 已抛出的 RerankerException 二次包装成 `RerankerException("重排服务暂时不可用", cause=e)`，丢失"缺少权重文件/目录不存在"的具体原因（详情仅保留在日志与 `__cause__` 中）。外部调用方拿到的是通用文案，难以定位。 | 中 | 在 except 中先判 `except RerankerException: raise`（透传），仅对非 RerankerException 做包装，保持具体诊断信息 |
| 2 | `ai_service/rag/reranker.py` | L85 | `_validate_model_dir()` 只校验权重文件"存在"，不校验文件大小；若 `model.safetensors` 是 0 字节/截断下载，校验会通过，直到 CrossEncoder 加载才报（且被通用文案掩盖）。 | 低 | 校验时追加 `os.path.getsize(...) > 0` 条件，截断文件也走"缺少权重"明确报错 |
| 3 | `ai_service/create_metadata_tables.py` | L15 | `DSN = "postgresql://postgres:123456@localhost:5432/..."` 为硬编码本地库口令（属既有代码，本次未改动）。本地开发脚本风险可接受，但建议读取环境变量 `PG_DSN`/`POSTGRES_PASSWORD` 以便复用与巡检。 | 低 | 由环境变量注入 DSN，缺省回退本地值；另建议将该脚本纳入 `.gitignore` 或使用占位口令 |

## 3. 验收标准核对

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| 模型路径指向 `models/Qwen3-Reranker-0.6B` | reranker.py L30-33 `_LOCAL_MODEL_DIR` | ✅ 通过 | 实测目录存在且含 model.safetensors |
| rerank() 返回带 rerank_score 降序结果 | reranker.py L128-135 | ✅ 通过 | test_m18.py Test2/Test3 覆盖 |
| 相关文档排前 | reranker.py chat 消息 + LogitScore 打分 | ✅ 通过 | Developer 实测 `1 0.0237 > 3 0.0179 > 2 0.0041` |
| 模型加载成功无异常 | reranker.py L91-97 | ✅ 通过 | 正常路径不抛异常 |
| 空 documents 返回 [] | reranker.py L105-106 | ✅ 通过 | test_m18 Test3 |
| 单个文档带 rerank_score | reranker.py L129-131 | ✅ 通过 | test_m18 Test3 |
| top_k 大于文档数返回全部 | reranker.py L135 `ranked[:top_k]` | ✅ 通过 | test_m18 Test3 |
| 缺 content 不抛异常 | reranker.py L117 `d.get('content','')` | ✅ 通过 | test_m18 Test3 |
| 目录不存在 → RerankerException（不回退 HF） | reranker.py L81-84 | ✅ 通过 | 实测验证（Test1 场景） |
| 权重文件缺失 → RerankerException 且日志明确 | reranker.py L85-89 + L138 | ✅ 通过 | 实测验证（Test0 场景），日志含具体缺失原因 |
| CrossEncoder 加载失败 → 包装 RerankerException | reranker.py L96 + L139 | ✅ 通过 | 结构满足 |
| predict 推理失败 → 包装 RerankerException | reranker.py L122-125 + L139 | ✅ 通过 | 结构满足 |
| rerank 签名/返回结构不变、rerank_score 为 float | reranker.py L99-135 | ✅ 通过 | 与 engine.py/graph.py 调用一致 |
| 返回数量 = min(top_k, len(documents)) | reranker.py L135 | ✅ 通过 | |
| 保留原字段 | reranker.py L130 | ✅ 通过 | 原地追加 rerank_score，id/title/content 保留 |
| rag_config / SQL / INITIAL_CONFIG 三处同步 | create_metadata_tables.py L24、rag_metadata_tables.sql L40、DB 实值 | ✅ 通过 | 均为 `Qwen/Qwen3-Reranker-0.6B`，DB UPDATE 已执行 |
| public 方法 Docstring | reranker.py L50/L72/L99 | ✅ 通过 | |
| top_k 默认值 5 | reranker.py L50/L99 默认参数 | ✅ 通过 | 无魔法数字 |
| 权重校验有行内注释 | reranker.py L93 | ✅ 通过 | |
| 命名规范 snake_case/PascalCase | 全部 | ✅ 通过 | |
| reranker.py 保持独立服务模块 | `from rag.reranker import reranker`（engine/graph/main） | ✅ 通过 | 无反向依赖、无侵入 retriever |
| 异常类型统一 RerankerException | reranker.py L39/L139 | ✅ 通过 | |
| 单个方法 ≤ 50 行 | rerank L99-139（约 41 行）、_validate_model_dir（19 行） | ✅ 通过 | |
| 新增代码 ≤ 200 行 | diff +72/-21，新增约 60 行 | ✅ 通过 | |
| Python 语法通过 / 无未使用 import | py_compile 通过；logging/os/Optional/CrossEncoder 均使用 | ✅ 通过 | |
| 单元/边界/缺权重测试覆盖 | test_m18.py | ✅ 通过 | 沿用 test_m17.py 约定 |
| 回归（schemas / m17） | Developer 报告 4 passed + m17 PASSED | ✅ 通过 | 交 Tester 复核 |
| changelog 如实反映变更 | changelog.md | ✅ 通过 | 含版本/日期/内容/变更人 |

## 4. 架构评估

- 分层正确性: **通过** — reranker.py 保持独立重排服务模块，由 engine.py / graph.py 通过 `from rag.reranker import reranker` 注入，无侵入 retriever。
- 依赖方向: **正确** — 仅上层依赖 reranker，无反向/跨层依赖。
- DTO 约束: **N/A（Python 内部服务）** — rerank 返回 list[dict]，与上下游契约一致。
- 新增依赖: **无** — 复用已安装的 sentence-transformers 5.6.1，本地模型推理，无新外部依赖，无需 ADR。

## 5. 安全评估

- [x] SQL 注入防护: 通过（create_metadata_tables.py 使用参数化查询 $1/$2；SQL 脚本为运维定值脚本，非用户输入）
- [x] XSS 防护: 通过 / N/A（无前端输出，content 截断在 engine.py 处理）
- [x] 密码安全（BCrypt）: N/A（本模块不涉及）
- [x] API Key 安全: 通过（无任何 API Key 硬编码；本地模型，无外部 API 调用）
- [x] 敏感信息日志处理: 通过（日志仅记录模型路径/数量，无敏感信息）
- 备注: create_metadata_tables.py L15 硬编码本地库口令属既有代码（见 2.2-3），本次未新增。

## 6. 架构决策记录（ADR）

- 本次审查是否产生 ADR: 否
- 说明: module-018 的"缺权重不回退 HF"与"Qwen3 生成式重排需 chat 消息格式"两项决策已由 Developer 在 changelog.md 记录，且与 plan.md 一致，无需新增 ADR。建议后续在 project-context.md 补记"Qwen3-Reranker 生成式重排需 chat 消息 + add_generation_prompt"这一技术约束（当前已记录模型选择，未记录调用格式约束）。

## 7. 审查检查清单

- [x] 已读取 changelog.md 了解变更范围
- [x] 已读取 plan.md 和 acceptance-criteria.md
- [x] 已阅读全部变更文件的完整内容（非仅 diff）
- [x] 命名符合规范（snake_case / PascalCase）
- [x] 异常处理无空 catch
- [x] 关键操作有日志记录（加载/排序/失败）
- [x] 敏感信息处理正确
- [x] 代码长度在限制内（方法 ≤ 50 行，新增 ≤ 200 行）
- [x] 接口签名/字段（rerank、rerank_score）不回归
- [x] 配置三处同步（代码/SQL/DB）
- [x] 无硬编码 API Key / 密钥（新增代码）
- [x] 验收标准逐项核对
- [x] 架构分层检查完成
- [x] 安全性检查完成
- [x] 语法检查（py_compile）通过
- [x] 异常路径实测验证通过

---

> 下一环节：审查通过，通知 Tester 进入测试阶段。建议 Tester 重点验证：Test 2 真实模型排序（确认 id=1 排最前）、回归 pytest tests/、rag_config 查询确认。
