# Module 074 变更日志（知识库出题注入 / ADR-0019 阶段 1）

## 变更内容

| 文件 | 变更 |
|------|------|
| `kb/KnowledgeBaseClient.java`（新增） | OkHttp3 fail-open 调 8001 `POST /ai/rag/search`；resumeContentHash 缓存（500 上限）；64KB 响应上限（Content-Length 预检 + 流式限读）；日志去 PII（queryChars） |
| `kb/ResumeKeywordExtractor.java`（新增） | PDFBox 2.0.31 PDF 文本提取；中英关键词 Top-8（MIN_FREQUENCY=1 保召回；MIN_TOKEN_LENGTH=3 常量与过滤一致） |
| `flow/extraction/InterviewQuestionExtractionService.java` | 出题 prompt 注入「参考知识点」段（`<kb_reference>` 数据块 + 防提示注入守卫 + 2000 字符截断）；简历字节只读一次（`readResumeBytes`）；KB 检索按 resumeContentHash 走缓存 |
| `pom.xml` | 新增 pdfbox 2.0.31 |
| `application.yaml` | `kb.base-url: ${KB_BASE_URL:http://localhost:8001}` |
| 5 个存量测试类 | 11 处构造调用补 runtime 服务 mock（基线编译断裂修复：消除 9 NPE + 1 并发失败） |

## 验证命令与输出

### 1. module-074 相关单测（16/16 全绿）

```
mvn -DforkCount=0 -Dtest='KnowledgeBaseClientTest,ResumeKeywordExtractorTest,InterviewQuestionExtractionServiceTest' test
→ Tests run: 16, Failures: 0, Errors: 0（surefire @{argLine} 未配置 JaCoCo，须 -DforkCount=0）
```

### 2. 全量回归（104/106）

```
mvn -DforkCount=0 test
→ Tests run: 106, Failures: 2, Errors: 0
```
2 个失败均为基线遗留、与 module-074 无关，另开模块处理（详见 review-report.md）：
- `InterviewRecordServiceImplTest.shouldFinishInterviewSessionBeforePersistingRecordFromRedis`（finalize 重构后交互期望过期）
- `XunfeiAudioServiceAssemblerTest.noPgsPartial_ShouldReplaceCurrentLiveSnapshot`（media 组装行为 expected AB / actual AAB）

### 3. 阶段1 联调（真实 RAG 服务，2026-08-25 环境恢复后）

**服务侧**：`uvicorn main:app`（ai_service/.venv，python 3.11）连 WSL PostgreSQL（personal_website，documents 15637 行，pgvector） + 本地 bge-m3-q8_0.gguf（634MB）；llama_cpp CPU wheel + torch CPU 安装；`POST /ai/rag/search` 实测命中（`{"query":"Redis 持久化 高并发 分布式锁"}` → top1「Redis 持久化机制（RDB + AOF + 混合持久化）」score=1.0）。

**Java 侧 E2E**（`<repo-root>\it-harness\LianDiaoReal.java`，真实 8001）：

```
[1] PDF generated, bytes=983
[3] QUERY=java redis distributed zhang san engineer kafka high
[4] REAL_KB 检索 costMs=432, contextChars=4030, injected=true
[5] PROMPT_HAS_MARKER(参考知识点)=true
[6] PROMPT_HAS_REAL_KB_CONTENT(Redis)=true
[7] FAIL_OPEN(down -> empty)=true
LIANDIAO_REAL_RESULT=PASS（exit 0）
```

最终 prompt 的 `<kb_reference>` 段含 8 条真实知识库内容（Redis 持久化/分布式限流 Lua/TCC 事务/Redis 高可用等）。

**环境恢复期间的依赖修复**（interview-personal/ai_service，已提交）：
- `requirements.txt`：langchain-text-splitters 漂移钉修正（>=1.1.0 → >=0.2.0,<0.3.0）；langchain-anthropic 0.1.8 → 0.2.4（与 langchain-core 0.2 兼容的说明，实际 0.2.x 均不兼容，改懒加载见下）
- `llm/client.py`：ChatAnthropic 改为懒加载（langchain-anthropic 全系与 langchain-core 0.2 无兼容版本，deepseek 链路不应背负 claude provider 的启动硬依赖）
- 安装策略：torch 走 PyPI CPU 源、mcp==1.26.0 钉回（新版无 fastmcp 路径）、langchain-core 钉 <0.3（1.x 移除 pydantic_v1 兼容层）、fastapi 钉回 0.111.0（新版移除 on_startup）、pydantic 放开 <3 且实际 2.13
- `.env` 补充：PW_JWT_SECRET（与 Java Sa-Token jwt-secret-key 同值）、PW_MCP_TOKEN（MCP HTTP fail-closed 必需）
