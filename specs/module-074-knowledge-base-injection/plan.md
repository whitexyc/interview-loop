# Module 074: 知识库出题注入（ADR-0019 阶段 1）— 开发计划

> Planner 输出 | Vibe Coding 闭环工作流
> 来源：specs/adr/0019-knowledge-interview-closed-loop.md 决策 2（阶段 1）
> 实施位置：ai-meeting-project/AI-Meeting/admin（Java 侧）；模块记录归 interview-personal（ADR 所在 hub）

## 需求（ADR 决策 2 原文）

出题服务调 LLM 前，先打知识库检索（`POST /ai/rag/search`，8001），把知识点拼进出题 prompt——题目从纯简历驱动变「简历 + 知识库」双驱动。零侵入：知识库侧零改动。

## 设计决策（含 ADR 未覆盖点）

### D1 检索 query 来源（本模块最大设计决策）

**问题**：`InterviewQuestionReqDTO` 只有 userName/agentId/sessionId/resumePdf(MultipartFile)/resumeFileUrl——**Java 侧拿不到简历文本**（PDF 直接传给星辰 LLM 远端解析），且全工程无 PDF 解析库。

**选型**：引入 **Apache PDFBox 2.0.31**（新依赖，超出 ADR 字面「3 处改动」，在此显式标注）：
- 简历文本提取 → 关键词抽取（英文技术词频次 + 中文 2-gram 词频，停用词过滤，Top 8）→ 拼 KB query
- 备选方案 B（userName+固定词表查询）被否决：检索个性化失效，违背 ADR「简历+知识库深度关联」初衷

### D2 fail-open 熔断（对齐项目既有决策）

KB 不可达 / 非 200 / 解析失败 → 一律返回空串继续纯简历出题。依据 project-context §7 既有决策「Java 端实现熔断降级（Python 服务超时后走兜底逻辑）」。超时 3s 连接 / 8s 调用。

### D3 包位置

外部服务客户端 → `com.hewei.hzyjy.xunzhi.interview.kb`（新包，贴近消费方；区别于 vendor SDK 的 toolkit.xunfei）。

## 文件变更清单

| 文件 | 动作 | 说明 |
|------|------|------|
| `admin/src/main/java/com/hewei/hzyjy/xunzhi/interview/kb/KnowledgeBaseClient.java` | 新增 | OkHttp3 POST /ai/rag/search，fail-open 返回空串 |
| `admin/src/main/java/com/hewei/hzyjy/xunzhi/interview/kb/ResumeKeywordExtractor.java` | 新增 | PDFBox 文本提取 + 中英关键词 Top8 |
| `admin/src/main/java/com/hewei/hzyjy/xunzhi/interview/flow/extraction/InterviewQuestionExtractionService.java` | 修改 | 注入 2 个依赖 + callAiSyncWithFile 前 6 行检索拼接 |
| `admin/src/main/resources/application.yaml` | 修改 | 加 `kb.base-url` |
| `AI-Meeting/admin/pom.xml` | 修改 | 加 pdfbox 2.0.31 |
| `admin/src/test/java/com/hewei/hzyjy/xunzhi/interview/kb/*.java` | 新增 | 关键词抽取单测 + KB client fail-open 单测 |

## 验收标准

见同目录 acceptance-criteria.md。

## 风险

- PDFBox 版本选 2.0.31（2.x API 稳定；3.x 改 Loader.loadPDF 不必要）
- 关键词抽取是启发式（无分词器依赖），中文 2-gram 召回质量有限——但只影响检索 query 质量，不影响主链路正确性
- KB 服务未启动时每次出题多一次 3s 连接超时等待 → 文档注明可设 KB_BASE_URL 指向占位端口或后续加开关
