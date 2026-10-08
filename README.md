<div align="center">

# interview-loop

**笔记 → 出题 → 面试 → 学习**

把个人知识库变成一条可持续的面试训练闭环。

[English](README_en.md) · [系统架构](#系统架构) · [快速开始](#快速开始)

你写的笔记被检索增强的 RAG 吃进去 → 系统据此生成**针对你知识结构**的面试题 →
面试结果回流成薄弱点 → 薄弱点决定下一轮出题。

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-1876%20%2B%2063%20%2B%20106-brightgreen.svg)](#测试与工程质量)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](ai_service/)
[![Java](https://img.shields.io/badge/Java-17%2B-orange?logo=openjdk)](interview-admin/)
[![Spring Boot](https://img.shields.io/badge/Spring%20Boot-3.2-6DB33F?logo=springboot)](interview-admin/)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)](frontend/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%20%2B%20pgvector%20%2B%20AGE-4169E1?logo=postgresql)](docker/postgres/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

</div>

---

## 为什么做这个

市面上的「AI 面试」大多是通用题库套壳：题目与你的知识结构无关，答完也不知道弱在哪。

这个项目反过来 —— **以你自己的笔记为唯一事实源**：

- 题目从你的笔记里检索出来，问的是你真写过、也真可能被问的东西
- 每道题都能溯源到你笔记里的原文（`[N]` 引用，点击弹出出处）
- 答得不好的知识点沉淀为**薄弱点**，下一轮出题优先打这些点

所以闭环不是「问答机器人 + 题库」，而是四段互相咬合的链路：

```mermaid
flowchart LR
    A["📝 笔记<br/>Markdown vault"] -->|sync_notes.py| B["🔍 RAG 知识库<br/>三通道检索 + 重排"]
    B -->|KnowledgeBaseClient| C["🎯 出题<br/>按简历关键词检索知识点"]
    C --> D["🎙️ 面试<br/>追问 / 语音 / 仪态评估"]
    D -->|答题结果| E["📉 薄弱点<br/>weak_topics"]
    E -->|优先出题| C
    E -->|补笔记| A
```

---

## 效果展示

### 面试链路

| 面试入口 | 上传简历 | 在线解析并出题 |
|---|---|---|
| ![面试入口](interview-admin/docs/assets/面试入口.png) | ![上传简历](interview-admin/docs/assets/上传简历.png) | ![在线解析并出题](interview-admin/docs/assets/在线解析并出题.png) |

| 提问环节 | 追问环节 | 面试结果分析 |
|---|---|---|
| ![提问环节](interview-admin/docs/assets/提问环节.png) | ![追问环节](interview-admin/docs/assets/追问环节.png) | ![面试结果分析](interview-admin/docs/assets/面试结果分析.png) |

### 知识库与问答

| 文档首页 | 文档管理 | 登录 |
|---|---|---|
| ![文档首页](interview-admin/docs/assets/文档首页截图.png) | ![文档截图](interview-admin/docs/assets/文档截图.png) | ![首页登录](interview-admin/docs/assets/首页登陆.png) |

### 闭环实测（本机运行截图）

以下是**真实运行时**的抓图（非设计稿）：提问「G1 垃圾收集器的 Region 分区机制是什么」，
左侧实时展示 Agentic 执行流程，右侧回答带逐句引用溯源。

| 执行流程（实时） | 管线完成 | 检索命中与引用溯源 |
|---|---|---|
| ![执行流程](images/demo/demo-01-pipeline-idle.png) | ![管线完成](images/demo/demo-02-pipeline-done.png) | ![检索与引用](images/demo/demo-03-retrieval-and-citations.png) |

可直接观测到的中间态：**混合检索召回 11 条 → Rerank 保留 5 条（过滤 6 条）→
自我反思判定「不充分」触发二次检索 → 生成回答并标注来源**（来源精确到笔记的板块与题目编号）。

---

## 系统架构

```
                    ┌──────────────────────────────────────────┐
   浏览器 ──────────▶│  React 18 + Vite  (3001)                 │
                    └───────────────┬──────────────────────────┘
                                    │ Vite 代理
                    ┌───────────────┴───────────────┐
                    │ /api/*                        │ /ai/*
                    ▼                               ▼
    ┌───────────────────────────┐   ┌────────────────────────────────────┐
    │ Spring Boot 3.2  (8081)   │   │ FastAPI AI 层  (8001)              │
    │ 会话 / JWT / 简历 / 文档  │   │ RAG 流水线 / Agent / 记忆 / MCP     │
    └───────────┬───────────────┘   └──────────┬─────────────────────────┘
                │                              │
                │              ┌───────────────┼───────────────┐
                │              ▼               ▼               ▼
                │   PostgreSQL 16          Redis         本地模型（离线）
                │   pgvector + AGE                      bge-m3 嵌入
                │                                       bge-reranker 重排
                │                                       HHEM 幻觉裁判
                │
                │        ┌────────────────────────────────────────────┐
                └───────▶│ Spring Boot 3.2 出题/面试平台  (8002)      │
                         │ interview-admin/  MySQL 8 + MongoDB 7      │
                         │ 出题 · 追问 · 语音转写 · 仪态评估 · 复盘   │
                         └────────────────────────────────────────────┘
                                        │
                                        │ POST /ai/rag/search
                                        └──▶ 回到 AI 层取知识点（fail-open 熔断）
```

`interview-admin` 通过 `KnowledgeBaseClient` 调用 AI 层的 `POST /ai/rag/search`，
把检索到的知识点注入出题 prompt。任何失败（连接拒绝 / 超时 / 非 200）一律返回空串，
出题退化为纯简历出题 —— **绝不因知识库故障阻断面试流程**。

---

## 核心能力

### 检索（三通道融合 + 本地重排）

- **三通道并行**：关键词全文 + 语义向量 + 知识图谱（Apache AGE），RRF 融合
- **父子两级分块**：按章节切父块（完整语义）+ 约 300 字子块（重叠 50 字符）—— 小块检索精准、大块回答完整
- **本地重排**：`bge-reranker-v2-m3` 精排 Top-5，截断超长文档防推理卡顿
- **全部离线**：嵌入 / 重排 / 幻觉裁判三个模型本地推理，零外部依赖

### Agent 与记忆

- **手写 ReAct 循环**：10 个工具按执行阶段分组暴露，检索命中即切生成阶段（避免死锁、省 token）
- **自我反思纠错**：检索不充分时改写查询重检（最多 3 轮），新旧结果合并
- **多层记忆**：长期偏好（永久）/ 短期内容（30 天衰减，反复提及自动升级）/ 会话上下文；按用户隔离
- **记忆纠错**：双判共识冲突检测（nli + clf 都判矛盾才标废弃，Precision 0.94，宁可漏检不错标）

### 幻觉检测

逐句验证答案是否被检索文档支持（有依据 / 可推断 / 无依据三档），前端逐句色标；
验证**异步进行** —— 答案先返回，验证结果后台补充，不阻塞阅读。

### MCP 标准工具服务

10 个工具经官方 MCP SDK（FastMCP）暴露为标准 MCP Server，**6 个只读检索工具**双传输对外：

- **stdio** —— 本地 Cursor / Claude Code / Claude Desktop 即插即用
- **Streamable HTTP** —— 挂载 `/ai/mcp`，Bearer token 认证（未配置 token 拒绝启动，fail-closed）

---

## 测试与工程质量

| 层 | 测试数 | 状态 |
|---|---|---|
| AI 层（Python / pytest） | **1876** | 全绿 |
| 前端（React / Vitest） | **63** | 全绿 |
| 出题面试平台（Java / JUnit） | **106** | 104 通过（2 项已知红测试，见下） |

工程化程度是这个项目最有区分度的部分：

- **模块制交付**：90+ 个模块规格目录，每个含 plan / acceptance-criteria / changelog / review-report / test-report 五件套
- **23 份 ADR**：检索、分块、记忆、幻觉检测、工具治理、Agent 评估、MCP 集成、框架对比、上下文压缩等关键选型全部留档
- **四阶段闭环**：Planner → Developer → Reviewer → Tester，单模块生产代码红线 AST ≤ 200 行，改前报影响面、改后全量回归
- **判定不用 LLM 评 LLM**：所有评测结论均为确定性判定

### 三次数据化架构裁定

这是项目里我最有底气讲的部分 —— **判据事前定死，不利结论照实记**：

| 轮次 | 议题 | 结论 |
|---|---|---|
| 091 | 手写 ReAct vs LangGraph StateGraph 双环路对拍 | 等价性夹具 **36/36 逐字等价** → 维持自研 |
| 092 | 多批次采样验证 | 发现**批次间漂移 65%** 的方法论问题，暴露单次采样判据的不可靠 |
| 093 | 上下文压缩三臂对拍（off / clearing / clearing+compaction） | **clearing 单独用是负收益**（history tokens 反升 31.6%）—— 与 Anthropic「最安全的压缩」直觉相反 |

093 的归因是「每调用视图膨胀 +36% → 失锚 → 长答案复利」，而非 re-invoke 循环。
完整数据见 [`METRICS.md`](METRICS.md) 与 [`specs/module-091/092/093`](specs/) 及 ADR-0020~0023。

---

## 快速开始

### 前置依赖

- Docker（用于起 PostgreSQL 16 + pgvector + Apache AGE、Redis）
- Python 3.11+ · Node.js 18+ · JDK 17+

### 1. 起依赖服务

```bash
docker compose up -d
docker compose ps          # 等 postgres / redis 变 healthy
python scripts/doctor.py   # 环境自检：21 项检查，附修复建议
```

首次会编译 Apache AGE（约 3–8 分钟，之后走镜像缓存）。

> **先跑 `doctor.py`**。它覆盖的都是真实踩过的坑，其中几条的报错极具误导性 ——
> 例如 `no_proxy` 含 `[::1]` 会让 httpx 崩溃，表现为「检索正常但回答生成失败」；
> JWT 密钥两侧不一致不会报错，而是**静默**把所有请求按 IP 隔离。
> 完整速查见 **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)**（8 类真实故障：症状 → 根因 → 修复）。

> 这个镜像不是官方现成的：没有任何官方镜像同时提供 pgvector 与 Apache AGE，
> 而本项目检索的图谱通道依赖 AGE、向量通道依赖 pgvector，所以基于
> `pgvector/pgvector:pg16` 补编了 AGE。见 [`docker/postgres/Dockerfile`](docker/postgres/Dockerfile)。

### 2. 下载本地模型（约 3.2 GB，不随仓库分发）

| 模型 | 目录 | 用途 | 大小 |
|---|---|---|---|
| bge-m3（GGUF q8_0） | `ai_service/models/bge-m3-gguf/` | 语义嵌入 | 606 MB |
| bge-reranker-v2-m3 | `ai_service/models/bge-reranker-v2-m3/` | 检索重排 | 2.17 GB |
| HHEM-2.1-Open | `ai_service/models/hhem-2.1-open/` | 幻觉检测裁判 | 418 MB |

```bash
# 国内网络建议走镜像
HF_ENDPOINT=https://hf-mirror.com huggingface-cli download BAAI/bge-reranker-v2-m3 \
  --local-dir ai_service/models/bge-reranker-v2-m3
```

### 3. 配置并启动

```bash
cp ai_service/.env.example ai_service/.env
# 填入 LLM API Key，并保证 PW_JWT_SECRET 与 backend/application.yml 的 jwt.secret 同值

# AI 层（8001）
cd ai_service && pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8001

# Java 后端（8081）
cd backend && mvn spring-boot:run

# 前端（3001）
cd frontend && npm install && npm run dev
```

访问 <http://localhost:3001>。

### 4. 把你的笔记灌进去

```bash
# 预演：只列出将要上传的文件
python scripts/sync_notes.py --dry-run --vault llm-push=/path/to/notes/llm-push

# 实际同步（可重复 --vault）
python scripts/sync_notes.py \
    --vault llm-push=/path/to/notes/llm-push \
    --vault python-push=/path/to/notes/python-push \
    --vault backend-push=/path/to/notes/backend-push
```

走 `/ai/rag/documents/upload` 管线（解析 → 清洗 → 三级去重 → 父子分块 → 本地嵌入 → 入库），
**幂等可重复执行** —— 已入库的笔记按内容哈希去重，只补新增与改动。

> 批量灌库会撞上服务的 IP 限流（默认 20 次/60 秒）：脚本已按 `retry_after` 自动退避，
> 但灌几百篇时建议临时调高阈值 —— 在 `ai_service/.env` 设
> `PW_RATE_LIMIT_MAX_REQUESTS=200` 后重启 AI 层。

### 5. 出题 / 面试平台（可选）

```bash
cd interview-admin
docker compose up -d          # MySQL 8 + MongoDB 7 + Redis
./mvnw spring-boot:run        # 8002
```

---

## 目录结构

```
interview-loop/
├── ai_service/            # Python AI 推理层
│   ├── rag/               #   检索 / 分块 / 重排 / 记忆 / 图谱 / 文档解析与清洗
│   ├── agent/             #   ReAct 循环 / 工具注册表 / 意图路由 / 反思
│   ├── eval/              #   评测：golden 集 / 消融 / 公开基准 / 版本化回归
│   ├── tests/             #   1876 项自动化测试
│   ├── scripts/           #   重建 / 图谱补跑 / 迁移等运维脚本
│   └── mcp_server.py      #   MCP 标准工具服务（FastMCP，6 只读工具 + 双传输）
├── backend/               # Java 业务层（会话 · JWT · 简历 · 文档）
├── frontend/              # React 前端（问答 · 知识库管理 · 简历 · 反馈）
├── interview-admin/       # Spring Boot 出题/面试平台（含自带 compose 与 Dockerfile）
├── scripts/               # sync_notes.py（笔记入库）+ doctor.py（环境自检）
├── docker/postgres/       # pgvector + Apache AGE 自建镜像
├── specs/                 # 90+ 模块文档 + 23 份 ADR
├── images/                # 机制图解 + 闭环实测截图
└── METRICS.md             # 全部量化指标（单一事实源）
```

---

## 环境变量

主要项（完整见 [`ai_service/.env.example`](ai_service/.env.example)）：

| 变量 | 说明 | 默认值 |
|---|---|---|
| `PW_DATABASE_URL` | PostgreSQL 连接 | `postgresql+asyncpg://postgres:123456@localhost:5432/personal_website` |
| `PW_REDIS_URL` | Redis 连接 | `redis://localhost:6379/0` |
| `PW_LLM_PROVIDER` | LLM 供应商（`fallback` = 按链降级） | `fallback` |
| `PW_FALLBACK_CHAIN` | 降级链 | `qwen,zhipu,opencode,deepseek` |
| `PW_JWT_SECRET` | JWT 共享密钥（HS256，**须 ≥32 字节且与 Java 侧同值**） | — |
| `PW_MCP_TOKEN` | MCP HTTP 模式 token（未设置拒绝启动） | — |
| `PW_RETRIEVAL_FUSION_MODE` | 检索融合：`rrf` / `hybrid` / `weighted` | `rrf` |
| `PW_VERIFY_ASYNC` | 幻觉验证异步化 | `true` |
| `PW_RATE_LIMIT_MAX_REQUESTS` | IP 限流阈值（批量灌笔记时调高） | `20`（次/60 秒）|
| `PW_FEEDBACK_INTERNAL_TOKEN` | 反向闭环扫描器访问 Java 低分题端点的内部 token | — |

> ⚠️ `PW_JWT_SECRET` 与 Java 侧不一致时**不会报错**，而是静默把所有请求按匿名（client_ip）
> 处理 —— 表现为「登录了但长期记忆不按用户隔离」。这是最容易踩的坑。

> ⚠️ 降级链首位建议放 **flash 档模型**：自我反思的充分性判定用 15s 硬超时包住**整条链**，
> 推理模型（长上下文下 reasoning 可达数千字符）会让整条链被 `asyncio.wait_for` 取消，
> 连降级到下一个供应商的机会都没有。实测 `deepseek-v4.1-flash`（opencode Go）2.8s 返回。

---

## 已知问题

> 部署类故障（检索正常但回答失败、限流、模型缺失、图谱为空等 8 类）见
> **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** —— 每条都是真实踩坑记录，
> 且大多伪装成代码/API 故障。

- `interview-admin` 有 **2 项自导入起就未通过的测试**，它们描述的是期望行为而实现不符，
  需要产品侧判定「是实现有 bug 还是断言需修正」：
  1. `XunfeiAudioServiceAssemblerTest` —— 无 `pgs` 分段时期望实时快照被**替换**，实现为**追加**
     （`"AAB"` vs 期望 `"AB"`），表现为实时字幕重复片段
  2. `InterviewRecordServiceImplTest` —— Mockito in-order 校验失败（「先结束会话再落库」顺序不符）
- AI 层测试需要本机具备 PostgreSQL + Redis 与三个本地模型权重（CI 未覆盖全量 AI 层测试）

---

## 致谢与第三方代码

`interview-admin/`（出题 / 面试平台）来自第三方开源项目 **「码上面试平台」**：

| | |
|---|---|
| 后端 | <https://github.com/lishuangqiang/AI-Meeting> |
| 前端 | <https://github.com/lishuangqiang/AI-Meeting-Frontend> |
| 许可 | MIT License, Copyright (c) 2026 xunzhi-agent-team |

原文保留在 [`interview-admin/LICENSE`](interview-admin/LICENSE)（MIT 要求保留版权声明）。
本仓库在其基础上做了接入改造：`KnowledgeBaseClient` 对接本仓库 AI 层的
`POST /ai/rag/search`、monorepo 路径适配、凭据全部外置为环境变量。

## 开源协作

欢迎 Issue / PR，详见 [CONTRIBUTING.md](CONTRIBUTING.md) 与 [SECURITY.md](SECURITY.md)。

## License

[MIT](LICENSE)
