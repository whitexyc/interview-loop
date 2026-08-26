# ADR-0019：知识库 × 面试系统闭环对接（RAG→SAG 演进方向）

## 元信息

- 状态：🔵 **规划中（2026-08-24 用户拍板方向，未动手改代码）**
- 日期：2026-08-24
- 关联：ai-meeting-project（面试系统，Spring Boot 3 + Java 17）、Agentic RAG（FastAPI 8001）、ADR-0008（数据飞轮）、ADR-0016（架构定位）、04 意图路由 / 05 查询改写 / 08 反思充分性 / 11 记忆机制、Zleap SAG（arXiv 2606.15971）
- 工具：双向 CodeGraph 索引已建（ai-meeting-project 567 文件 / interview-personal 已有 .codegraph）

## 背景：现状（代码实测）

### 面试系统侧（ai-meeting-project）
- 技术栈：Spring Boot 3 + Java 17 + Spring AI + LiteFlow + MyBatis-Plus + Redisson + MongoDB + Redis + MySQL；包名 `com.hewei.hzyjy.xunzhi`
- 出题核心：`InterviewQuestionExtractionService.extractInterviewQuestions`（interview/flow/extraction/InterviewQuestionExtractionService.java:47）
  - 出题 prompt：`EXTRACTION_PROMPT`（34-37 行），目前**只基于简历**
  - 真正调 LLM：`interviewAiInvoker.callAiSyncWithFile(...)`（75-82 行）→ **注入知识库上下文的精确插入点**
  - LLM 场景配置：`BusinessAgentScene.INTERVIEW_QUESTION_EXTRACTION`（52-53 行，星辰大模型 XingChenAIClient）
- 已有能力可复用：OkHttp3 客户端（讯飞 XunfeiAudioService）、`@Scheduled` 定时器（InterviewTurnRepairService）、ai_properties 表（外部服务配置化）

### 知识库侧（Agentic RAG，interview-personal）
- 检索接口**已存在**：`POST /ai/rag/search`（`ai_service/main.py:452` → `rag_engine.search`）
- 启动端口：**8001**（`uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)`，main.py:1110）
- 检索核心：`retriever.py:93` `retrieve(query, top_k=5, mode="hybrid", source_pattern, round_num)`（三通道 RRF，Hit@5 0.9905）
- 请求 `SearchRequest`（`rag/schemas.py:8`）：`{query:str, top_k:int=5}`
- 响应 `SearchResponse`（`schemas.py:13`）：`{results:list[dict], message:str}`，每项为 `{content, source, score, ...}`

**结论**：知识库侧零后端改动，Java 侧只需新建 OkHttp client 调 8001。

## 业界方案（2026 调研）

### 闭环架构（Self-Improving KB）
- inferensys 给出"自改进知识库"触发-动作表：低置信度→重分块/重写；过期>30天→重嵌 upsert；矛盾→激活消解；多跳失败→调查询改写
- 本项目已有 70% 零件：反思充分性（L1-L2，module-08）、矛盾 dual 双判（NLI+clf 0.9412，module-070）、记忆进化（11）、查询改写（05）——"审查改写机制"是把这些串成自动化任务的回调，非从零造

### SAG（SQL-Retrieval Augmented Generation，Zleap arXiv 2606.15971）
- 离线只抽"事件+实体"（11 类），**查询时 SQL join 动态连边**，不预建全局图
- 省"图谱构建 + 重建"的 LLM 钱；**不省嵌入（向量化）钱**
- MuSiQue Recall@5 80%（多跳最强），已部署数百亿条、秒级延迟
- 对比 GraphRAG：增量 append-only，无级联抽取、无全局重算

## 决策 1：闭环形态（检索→学习→面试→待学，自动回流）

```
自动化任务(定时/触发) → [抓取新资料] → [审查改写:复用反思+双判]
   → 知识库(增量 append) → [学习Agent:消化成记忆点,复用11三层]
   → [面试系统:检索上下文出题+追问+评分] → [薄弱点] → 自动生成待学任务 → 回到顶部
```

- 类比：私人助教——每日收资料、审质量（差丢）、整理进笔记本；照笔记本考题，考不过记下来，次日补材料
- 反向链路：面试评分/薄弱点已落 `InterviewQuestion` + `InterviewSession`（Mongo），新增 `@Scheduled` 扫描低分题→调记忆层写入待学笔记→自动任务次日优先抓相关材料

## 决策 2：出题注入（Java 侧 3 处，零侵入）

1. 新增 `KnowledgeBaseClient`（OkHttp3，`@Value` 注入 `kb.base-url`，默认 `http://localhost:8001`）
   - 调 `POST /ai/rag/search`，请求 `{query, top_k}`，取 `results` 拼文本
2. 在 `InterviewQuestionExtractionService.extractInterviewQuestions` 第 75 行前注入：
   ```java
   String kbContext = knowledgeBaseClient.retrieve(buildQueryFromResume(reqDTO));
   String prompt = EXTRACTION_PROMPT + "\n参考知识点：\n" + kbContext;
   ```
3. `application.yaml` 加 `kb.base-url: ${KB_BASE_URL:http://localhost:8001}`

## 决策 3：RAG→SAG 演进（先做增量，SQL 连边留作演进）

- **先做增量 append 不重建索引**（用户 2026-08-24 拍板）：复用 documents 表 upsert 路径，新增语料直接追加，不做全量重嵌/重建图——立刻省钱
- SQL 连边（事件+实体、查询时 join）列为 WP 演进项，不为了用而用（语料以单跳技术笔记为主，连边收益有限）
- 诚实边界：SAG 完整 SQL 连边本项目未在生产跑过，属规划方向；当前落地的是增量 upsert + 三通道 RRF

## 决策 4：自动化任务数据源白名单（用户要求扩大，2026-08-24）

- **官方一手文档优先**（无二手偏差）：Spring / Spring Boot / MyBatis-Plus / Redis / MongoDB / FastAPI / LangChain / LangGraph 官网
- 中文社区（实战向）：掘金 juejin.cn、思否 segmentfault.com
- 查坑查报错：Stack Overflow、GitHub Issues、V2EX
- 前沿：arXiv、Google Scholar
- 预习（仅预习不入库）：B 站技术区
- **黑名单明确排除**：营销号、CSDN 纯搬运、SEO 标题党、无出处面经搬运——抓到直接丢
- 分层原则：结构化（GitHub / Obsidian / 本地 md）走 Connector 或本地读，质量最高；开放网页走联网搜索 + 白名单，质量靠审查节点兜底
- WorkBuddy 自动化本质 = 定时执行 prompt，数据源靠 Agent 在 prompt 内调工具（Connector + WebSearch/WebFetch + 本地文件），需在 prompt 写明"去哪抓"

## 诚实边界（面试防御）

1. 闭环架构是**规划**，阶段1对接代码未写、未联调；可讲"接口契约已双向 CodeGraph 核实、插入点精确到行"
2. SAG 完整 SQL 连边未在生产验证，诚实归为"架构演进方向"；已落地的是增量 upsert + 三通道 RRF（Hit@5 0.9905 实测）
3. 知识库 `/ai/rag/search` 是真实存在的生产接口（端口 8001），对接无需后端改动——这是确定的，不是设想

## 面试话术

> "我做了一个'检索-学习-面试'闭环：自动化任务定时抓资料（白名单+黑名单审查），进自研 Agentic RAG 知识库（增量 append 不重建），学习 Agent 消化成记忆点，再喂给我的 Spring Boot 面试平台——在抽题服务调 LLM 之前先打一轮知识库检索（三通道 RRF），把知识点拼进出题 prompt，题目从纯简历驱动变简历+知识库深度关联。知识库是 FastAPI 跑在 8001，已有 `/ai/rag/search` 接口，Java 侧用 OkHttp 客户端零侵入接了 3 处。RAG→SAG 我先做增量 append 省建图钱，SQL 连边留作演进——诚实讲我单跳笔记为主，连边收益有限，不为了用而用。"

**追问预案**：被问"你真跑过 SAG 吗？" → "完整 SQL 连边没在生产跑，是规划方向；已落地的是增量 upsert 不重建 + 三通道 RRF，这部分有实测数据。"

## 验收标准（规划，待实施）

- [x] 阶段1：KnowledgeBaseClient + 出题注入 3 处改动完成（2026-08-25，feature/module-074-knowledge-base-injection @ d56d9a1）。**真实联调 PASS**：真实 RAG 服务（uvicorn 8001 + WSL PostgreSQL personal_website 15637 文档 + bge-m3 本地嵌入）实测 /ai/rag/search 命中（top1「Redis 持久化机制」score=1.0）；Java 侧 E2E（真实 PDF→关键词→8001→prompt 含「参考知识点」+ 真实 KB 内容，fail-open 实测）
- [x] 阶段2 第一片：APScheduler + source_configs 表驱动白/黑名单 + httpx fetch + reflector/factcheck_judge 审查 + review_status 落库闭环。30 单测，真实冒烟 6/6。已推 knowledge-interview @ f143c80（含 3 轮修复）
- [x] 阶段2 第二片：递归爬取 + 链接跟踪 + 深度控制 + 去重 URL 池 + 黑名单接入主链路。63 单测（075 30+076 33），全量 1310/4 基线遗留，AST 129 行 ≤200。已推 knowledge-interview @ fd34ede
- [x] 阶段2 审查增强：阈值配置化 + 矛盾检测（memory_conflict_judge dual 双确认）+ 策略三档 + review_score 四层透传。91 单测（075 30+076 33+078 28），全量 1338/4 基线遗留，AST ~122 行 ≤200。真实冒烟 559/413ms。已推 knowledge-interview @ 7a69110
- [x] 阶段2 反爬代理：robots.txt 遵循 + UA 轮换 + 限速重试退避（429/5xx 指数退避+jitter）+ 代理轮换。119 crawl 测试（075 30+076 33+078 28+077 28），全量 1366/4 基线遗留，AST ~140 行 ≤200。已推 knowledge-interview @ 待提交
- [x] 阶段3：增量 append 不重建验证 + find_semantic_duplicate 性能加固（O(N)→O(K) pgvector SQL top-K + ndarray bug 结构性根除）。91 定向测试，全量 1396/4 基线遗留，生产代码 50 行 ≤200。Reviewer 真实 PG 只读冒烟通过。已推 knowledge-interview @ 待提交
- [x] 反向闭环：低分题→待学笔记→自动任务优先抓取 链路打通（module-080-reverse-feedback，2026-08-26，Tester 27/27）。RAG 侧 feedback_scanner（httpx 拉 Java weak-points + 待学笔记 memory_service.save）+ priority_crawl（drain_priority_seeds → Bing 搜索 → _recursive_crawl）+ crawl_priority 表；Java 侧 WeakPointController（GET /api/xunzhi/v1/interview/weak-points，内部 token fail-closed）。全量 1449/4 基线遗留，Java BUILD SUCCESS。ADR-0019 **全量闭环**。
