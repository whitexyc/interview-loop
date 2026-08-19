# ADR-0001: 输入双层防线 —— Pydantic 物理拦截 + LLM 输出可信度校验

- **状态**: Accepted（module-042 已实现，测试全部通过）
- **日期**: 2026-08-07 实现；2026-08-08 归档为 ADR
- **关联**: `specs/module-042-harness-guardrails/test-report.md`

## 背景（Context）

RAG 问答链路需要输入防护，三个原因：

1. **防滥用**：query 无长度上限时，超长输入白嫖 LLM token 成本
2. **防异常**：超长/畸形输入进入检索→重排→反思链路，可能产出怪异结果
3. **LLM 不可信**：链路内的 LLM 输出（如意图分类）需要独立校验，不能直接信任

## 决策（Decision）

两层校验，职责分离：

### 第一层：入口物理拦截（`ai_service/rag/schemas.py:18-28` ChatRequest）

- `query: str = Field(..., max_length=2000)`：必填 + 2000 字符上限 → 超限由 FastAPI 返回 **422**，请求不进业务逻辑（不触发任何 LLM 调用）
- `history: list[dict] = Field(default_factory=list)`：**无 Field 长度约束**，可省略默认空列表
- `@field_validator("history", mode="before") truncate_history`：超 20 条时 `v[-20:]` **静默截断**保留最近 20 条，不返回 422
- 四个问答端点共用该模型：`/ai/rag/chat`（main.py:320）、`/ai/rag/chat/stream`（main.py:342）、`/ai/rag/chat/agent`（main.py:516）、`/ai/rag/chat/agent-lg`（main.py:582）

### 第二层：LLM 输出可信度校验（`ai_service/agent/router.py:76-122` RouterAgent）

- 空 query 防御：直接返回 knowledge 意图（router.py:76-77）
- JSON 块提取：`find("{") + rfind("}")` 容错 markdown 包裹/前后多余文字（router.py:104-108）
- **intent 白名单**：非法值回退 knowledge，防 LLM 编造类别（router.py:111-113）
- confidence 类型强转：`float()`，非数字抛错走兜底（router.py:116）
- 兜底 try/except：LLM 失败/超时/解析失败一律保守返回 knowledge（router.py:87-90, 119-122）——"宁多检不漏检"

## 关键取舍

- **query 超长 → 422 拒绝**（用户当下输入，拒绝最干净）；**history 超长 → 静默截断**（累积旧对话，拒绝伤正常使用）
- **演进记录**：module-033 原实现用 `Field(max_length=20)` → 超条数返回 422；module-042 按 AC 1.4"超条数截断"修正为 field_validator 静默截断（见 test-report.md"AC 1.4 对齐说明"）
- **成本**：Pydantic 校验是微秒级本地字符串检查，对比 LLM 调用数秒——在入口挡住坏请求，整条链路零负担
- **确定性**：物理护栏不依赖 LLM 判断；"确定性兜底"与"LLM 自主纠错"正交（module-042 核心思路）

## 后果（Consequences）

- 正面：确定性防护、防滥用省成本、边界测试完整（`test_schemas_validation.py` 2 用例 + `test_schemas.py::TestChatRequestValidation` 6 用例，共 8 个全 PASS）
- 代价：history 静默截断不告知客户端（消息丢失无感知）；上限数字（2000/20）无文档化推导依据；`SearchRequest`/`MemorySaveRequest` 等其它请求模型未加同等约束

## 讨论记录（Grill 会话，2026-08-08 归档）

聊天中确认的事实与修正：

- **修正点**：history 的截断不是 `Field(max_length=20)`，而是 `field_validator(mode="before")` 静默截断——早期答复把两者混淆，以代码为准（schemas.py:22-28）
- router.py 的校验对象是"LLM 输出"而非"用户输入"，与 schemas.py 是**两层不同的防御**
- 待继续讨论（后续 grill 会话逐题推进）：
  1. ✅ 2000/20 上限的推导依据 — **已定（2026-08-08）**：2000 字符 ≈ 中文 650 字问题，20 条 ≈ 10 轮对话，均远超正常使用；目的仅为防滥用，依据已补入 acceptance-criteria.md
  2. ✅ 静默截断是否应告知客户端 — **已定（2026-08-08）**：纯静默，不加响应标记/提示。理由：最近 20 条才是上下文主力，丢旧消息几乎不影响答案质量；报错打断体验
  3. ✅ `SearchRequest`/`MemorySaveRequest` 是否加同样防护 — **已定（2026-08-08）**：全加。`SearchRequest.query` 与 `MemorySaveRequest.content` 均补 `max_length=2000`（`/ai/rag/search`、`/ai/memory/save`、`/ai/memory/recall` 三个端点）；尤其 save 落库，无上限污染长期记忆库。每处一行 Field + 两个测试用例
  4. ✅ 422 错误消息是否应做前端友好化 — **已定（2026-08-08）**：不做后端 handler，前端输入框加 `maxlength=2000` 兜底。职责分工：前端防输入（用户根本输不进去）、后端 422 防绕过（恶意/异常请求）。422 是程序性错误路径，正常用户不会触发，不值得为它加 handler + 前端文案两处代码
