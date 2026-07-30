# Review Report — Module-004: Python AI 层基础架构

- **Reviewer**: reviewer-001 | 2026-07-29
- **Scope**: `ai_service/` 全部 6 个文件 + `specs/module-004-ai-foundation/` 验收标准/计划
- **Review method**: 逐文件静态审查

---

## 结论

**有条件通过（Blocking 项修复后可合并）。**

整体代码质量良好，分层清晰，适配器模式使用得当，骨架与实现分离明确。但存在 **1 个 Blocking 问题**（运行时 import 路径冲突）和 **1 个技术债务项**（同步 LLM 调用阻塞事件循环）。修复 Blocking 项后即可合并，不影响 module-005 开发。

---

## Blocking Issues（阻塞合并）

### B1. main.py 的 import 路径与 `__main__` 入口不兼容

**严重性**: 高 | **文件**: `ai_service/main.py`

`main.py` 中的模块级 import 使用 **绝对包路径**（`from ai_service.src.config import settings`），这种写法要求 Python 能够将 `ai_service` 识别为一个包。但 `__main__` 块调用的是 `uvicorn.run("main:app")`，这表示运行时应从 `ai_service/` 目录执行 `python main.py`——此时 `ai_service` 不在 `sys.path` 中，绝对导入将报 `ModuleNotFoundError`。

**复现方式**:
```bash
cd ai_service && python main.py
# → ModuleNotFoundError: No module named 'ai_service'
```

**推荐的修复方案**（三选一）:

| 方案 | 改动量 | 复杂度 |
|------|--------|--------|
| A. 使用 `python -m ai_service.main` 方式运行，并修正 `uvicorn.run` | 修改 `uvicorn.run` 调用 | 低 |
| B. 将模块内 import 改为相对路径（`from .config import settings`） | 修改全部 4 个文件的 import | 中 |
| C. 在 `__main__` 块中添加 `sys.path` 修正 | 1 行 | 低（但不够规范） |

**推荐方案 A**：将 `__main__` 块改为：
```python
uvicorn.run("ai_service.main:app", host="0.0.0.0", port=8000, reload=True)
```
并建议从项目根目录执行 `python -m ai_service.main`。

---

## Non-Blocking Issues（建议修复）

### N1. LLM 同步调用阻塞事件循环

**严重性**: 中 | **文件**: `llm/client.py`

`LLMClient.generate()` 和 `LLMClient.chat()` 均为 **同步** 方法，并通过 `self._llm.invoke()` 直接阻塞。在 FastAPI async 端点中调用时会阻塞事件循环（Uvicorn 工作线程数 =1 时尤其严重）。

**建议**:
- 在本模块合入前：添加文档标注，说明在 module-005 中需要替换为 `async` 版本。
- 在 module-005 中：路由改为同步端点（FastAPI 会自动在线程池中运行），或改用 `langchain` 的异步调用（`ChatAnthropic().agenerate()` / `ChatOpenAI().agenerate()`，注意 LangChain 异步 API 在 v0.3 后有变化）。

当前作为骨架可接受，但应如实记录在技术债务中。

### N2. `database.py` 的 `get_db` 未被使用

**严重性**: 低 | **文件**: `src/database.py`

`get_db()` 是 FastAPI 依赖注入函数，定义了如何获取和关闭数据库会话。当前没有任何路由使用它。这属于 **预置代码**，不是当前模块的职责。不删除，但需要确认是否应在验收清单中标记。

**建议**: 在验收标准备注中标注此函数为 module-005 预留。

### N3. CORS `allow_origins=["*"]`

**严重性**: 低 | **文件**: `ai_service/main.py:41`

生产环境中不应允许所有来源。当前为开发阶段可接受。建议在 module-005 或上线前通过环境变量配置允许的来源列表。

---

## 验收标准核对表

| # | 验收项 | 状态 | 备注 |
|---|--------|------|------|
| 1 | `/ai/health` 返回健康状态 | ✅ 通过 | 路由注册正确，返回格式符合预期 |
| 2 | 连接 PostgreSQL 启用 pgvector | ✅ 通过 | `init_db()` 执行 `CREATE EXTENSION IF NOT EXISTS vector` |
| 3 | LLM 支持 Claude + DeepSeek 切换 | ✅ 通过 | `LLMFactory` 工厂模式，通过 `PW_LLM_PROVIDER` 切换 |
| 4 | `/ai/rag/search` 和 `/ai/rag/chat` 路由注册 | ✅ 通过 | 路由注册到 FastAPI 实例，返回骨架响应 |
| 5 | `/ai/config` 返回配置（不含密钥） | ✅ 通过 | 返回 provider/model/debug，无 API Key |
| 6 | Python snake_case 命名 | ✅ 通过 | 所有变量/函数符合规范；Pydantic Model 使用 PascalCase 正确 |
| 7 | async/await 使用 | ⚠️ 有条件通过 | RAG 端点为 async，但 LLM 调用为同步（见 N1） |
| 8 | 环境变量管理 | ✅ 通过 | 全部通过 `Settings` + `PW_` 前缀加载，`env_file` 支持 `.env` |
| 9 | LLM 异常处理 | ✅ 通过 | `LLMException` 封装，含 provider 信息和原始异常链 |
| 10 | `python main.py` 启动后 curl 验证 | ❌ 阻塞 | 见 B1，import 路径冲突导致 `ModuleNotFoundError` |

---

## 架构评估

### 分层结构

```
main.py (FastAPI 入口 / 路由)
  ├── src/config.py      (配置管理)
  ├── src/database.py     (数据库连接)
  ├── llm/client.py       (LLM 适配器)
  └── rag/
        ├── engine.py     (RAG 引擎骨架)
        └── schemas.py    (请求/响应 Pydantic 模型)
```

分层清晰，职责分明。各层之间只通过模块 import 耦合，没有循环依赖。

### 设计模式使用

| 模式 | 位置 | 说明 |
|------|------|------|
| **适配器模式** | `llm/client.py` | `LLMClient(ABC)` → `ClaudeClient` / `DeepSeekClient`，隔离供应商 SDK 细节 |
| **工厂模式** | `LLMFactory` | 单例缓存 + 配置驱动选择，`clear_cache()` 支持运行时切换 |
| **依赖注入** | `src/database.py` | `get_db()` 为 FastAPI DI 准备，当前 module 未使用 |
| **骨架模式** | `rag/engine.py` | 返回占位结果，明确标注 module-005 实现 |

### 依赖关系

```
main.py
  ├── src.config         (pydantic-settings)
  ├── src.database       (SQLAlchemy async + asyncpg)
  ├── rag.engine         (RAGEngine 单例)
  │     └── rag.schemas  (Pydantic models)
  └── (通过 RAGEngine 间接依赖 llm.client)
```

注意 `main.py` 不直接依赖 `llm/client.py`——RAG 引擎在 module-005 中调用 LLM 客户端即可。

### 数据流

```
外部请求
  → FastAPI 路由（async）
    → RAGEngine.search() / chat()  [skeleton → module-005]
      → (未来) LLMClient.generate()
        → Claude / DeepSeek API
```

---

## 安全性评估

| 检查项 | 结果 | 说明 |
|--------|------|------|
| API Key 不硬编码 | ✅ | 通过 `PW_CLAUDE_API_KEY` / `PW_DEEPSEEK_API_KEY` 环境变量 |
| 配置端点不暴露密钥 | ✅ | `/ai/config` 只返回 provider/model 名称 |
| CORS 配置 | ⚠️ | `allow_origins=["*"]` 开发阶段可接受，上线前需收紧 |
| 默认密码 | ⚠️ | `database_url` 默认密码 `postgres123`，应在 `.env` 中覆盖 |

---

## 总结

代码质量上乘——抽象层次恰到好处，没有过度工程，也没有过早优化。唯一的 **Blocking 问题（B1）** 是入口模块的 import 路径与运行方式不匹配，修复成本极低。**建议修复 B1 后合并**，N1 和 N2 作为技术债务记录，在 module-005 中一并解决。
