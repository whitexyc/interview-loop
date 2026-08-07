package com.personalwebsite.service;

import com.personalwebsite.model.ResumeEntity;
import com.personalwebsite.repository.ResumeRepository;
import com.personalwebsite.service.dto.ResumeDTO;
import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 简历业务逻辑
 * <p>系统启动时自动从数据库读取简历数据，如不存在则初始化 seed 数据</p>
 */
@Service
public class ResumeService {

    private static final Logger log = LoggerFactory.getLogger(ResumeService.class);

    private final ResumeRepository resumeRepository;

    public ResumeService(ResumeRepository resumeRepository) {
        this.resumeRepository = resumeRepository;
    }

    /**
     * 获取简历（当前只支持单份简历，取 id=1）
     */
    public ResumeDTO getResume() {
        ResumeEntity entity = resumeRepository.selectById(1L);
        return ResumeDTO.fromEntity(entity);
    }

    /**
     * 更新简历数据
     */
    public ResumeDTO updateResume(ResumeDTO dto) {
        ResumeEntity entity = resumeRepository.selectById(1L);
        if (entity == null) {
            return null;
        }
        entity.setName(dto.getName());
        entity.setGender(dto.getGender());
        entity.setPhone(dto.getPhone());
        entity.setEmail(dto.getEmail());
        entity.setJobIntent(dto.getJobIntent());
        entity.setGithub(dto.getGithub());
        entity.setEducation(dto.getEducation());
        entity.setHonors(dto.getHonors());
        entity.setSkills(dto.getSkills());
        entity.setProjects(dto.getProjects());
        entity.setSelfEvaluation(dto.getSelfEvaluation());
        resumeRepository.updateById(entity);
        log.info("简历已更新: id={}", entity.getId());
        return ResumeDTO.fromEntity(entity);
    }

    /**
     * 系统启动时初始化种子数据（如数据库为空）
     */
    @PostConstruct
    public void initSeedData() {
        if (resumeRepository.selectById(1L) != null) {
            log.info("简历数据已存在，跳过初始化");
            return;
        }

        ResumeEntity entity = buildSeedResume();
        resumeRepository.insert(entity);
        log.info("简历种子数据初始化完成");
    }

    private ResumeEntity buildSeedResume() {
        ResumeEntity entity = new ResumeEntity();

        entity.setName("张三");
        entity.setGender("男");
        entity.setPhone("13800138000");
        entity.setEmail("zhangsan@example.com");
        entity.setJobIntent("Agent/Java开发工程师（可随时到岗）");
        entity.setGithub("https://github.com/whitexyc");
        entity.setSelfEvaluation(
                "技术热忱：熟练掌握 Java/Python，能够熟练使用 Claude code 搭建长时间运行的工作流。" +
                "经常了解前沿知识，善于将当前问题与新技术结合思考解决思路。" +
                "工程实践：具备 Linux 部署服务与 bug 修复的经验，参与过多个项目的全流程开发与维护，注重代码健壮性与生产环境稳定性。" +
                "探索精神：热衷于深入理解原理，喜欢从底层剖析问题。从不锈钢防锈的化学原理到 DSpark 推测解码的并行推理机制，" +
                "各类技术原理均有涉猎，追求知其然更知其所以然。"
        );

        // Education
        ResumeEntity.EducationItem edu = new ResumeEntity.EducationItem();
        edu.setSchool("赣南科技学院");
        edu.setMajor("信息工程学院 - 物联网工程");
        edu.setGradeYear("2027届");
        edu.setRank("专业综合排名前 5%");
        edu.setCourses(List.of("数据结构与算法", "计算机网络", "操作系统", "Java高级程序设计", "openEuler", "openGauss"));
        entity.setEducation(List.of(edu));

        // Honors
        entity.setHonors(List.of(
                "全国大学生物联网设计竞赛全国一等奖",
                "大学英语四级（CET-4，544分，具备良好的英文文献阅读能力）",
                "校级奖学金（四次）"
        ));

        // Skills
        entity.setSkills(List.of(
                skill("Java 核心技术", "集合框架", "高并发 JUC 编程", "JVM 内存模型及 GC 调优", "OOM 诊断"),
                skill("Python 核心技术", "Pandas", "NumPy", "FastAPI", "数据处理与 AI 模型构建"),
                skill("后端架构能力", "Spring Boot/Cloud 微服务", "Spring IoC/AOP", "高可用分布式系统"),
                skill("数据库与中间件", "MySQL 设计与优化", "Redis 分布式缓存与锁", "RocketMQ"),
                skill("Agent 与大模型工程", "LangChain4j", "Agentic Workflow", "Claude 模型", "RAG 全流程", "Milvus/pgvector", "Neo4j"),
                skill("工程化工具", "Git", "Maven", "Docker/K8s", "Linux/Shell", "CI/CD")
        ));

        // Projects（时间倒序：最新在前）
        entity.setProjects(List.of(
                project(
                        "Agentic RAG 技术文档知识库问答系统",
                        "大模型应用开发工程师（全栈）",
                        "2026.07 - 至今",
                        "面向技术笔记分散、无法直接交互问答的痛点，将 124 篇技术笔记（累计约 156 万字、平均每篇 1.3 万字，覆盖 JVM、并发、分布式等领域）转化为可交互、引用可溯源的 Agentic RAG 技术文档知识库，支持任意用户以自然语言问答，覆盖文档管理、混合检索、Agent 智能问答、多层记忆完整链路，采用三层架构（Spring Boot 业务层 + FastAPI AI 推理层 + React 前端）。主导整体架构设计、检索质量与系统稳定性的持续优化，并建立可量化、可回归的评估体系驱动每一轮改进。",
                        List.of(
                                "Agent 能力链路：落地 Agentic Self-RAG 流水线（意图路由 → 混合检索 → 语义重排 → 自我反思纠错 → 流式生成）；LLM-as-Classifier 零样本意图路由，JSON 解析回退 + 值白名单兜底，分类失败保守走知识库；检索不充分自动改写重查；Agent 工具化（ReAct 循环 + ToolRegistry 7 工具），SSE 工具轨迹前端实时展示 + 引用溯源。",
                                "检索架构与评估体系：设计三通道混合检索架构（jieba 中文全文 + pgvector 语义向量 + Apache AGE 图谱）加权融合，解决中文默认分词空召回与语义失准问题；父子两级分块（章节级父块 + 300 字子块）兼顾召回精度与回答完整性；自建 30 题 golden 评测集 + Hit@k/MRR + 版本化回归，三通道融合 Top-5 命中率 0.96（23 题有效口径）。",
                                "并发稳定性、缓存与本地化推理：定位 asyncpg 单连接并发限制，拆分双连接并行检索，16 路并发与串行结果完全一致；Redis 参数化 key 缓存 + 数据变更自动失效（命中 3ms）；30s 整链路 deadline + 每步级联超时 + 多供应商 LLM 降级链；本地部署 bge-m3 嵌入与 bge-reranker 重排，完全离线推理、单家 API 故障不中断。",
                                "多层记忆与用户上下文隔离：构建长期/短期/会话三层记忆（LLM 自动抽取 + TTL 滚动 + content_hash 幂等落库），面向多用户开放、每个用户独立记忆上下文互不串扰，双向隔离（记忆不污染知识库、只查本用户记忆）；普通聊天/流式/Agent 全链路接入，会话恢复无重复、异步落库不阻塞回答。",
                                "工程质量：配套 298 个 pytest 用例全通过；36 个模块经 Planner→Developer→Reviewer→Tester 四角色 AI 协作闭环迭代交付，语义化版本与共享记忆库管理。"
                        )
                ),
                project(
                        "企业级 AI 智能业务编排平台",
                        "后端/Agent 开发工程师",
                        "2025.10 - 2026.02",
                        "主导设计并研发了一套多租户 AI 业务赋能平台，集成 RAG 知识库、工作流引擎及多模型调度，旨在实现 LLM 能力的低代码化封装与业务解耦。",
                        List.of(
                                "模型接入适配：针对不同 LLM 厂商的 API 差异，设计了策略模式驱动的统一适配层。通过标准化接口封装 DeepSeek、OpenAI 等 7 种主流模型，利用熔断降级机制，使系统在高并发调用下的稳定性达 99.9%。",
                                "可视化任务编排：基于状态机模型构建工作流引擎，支持 17 种逻辑节点（如 HTTP 调用、条件分支、人机交互）。通过引入运行时任务挂起与动态恢复机制，成功处理复杂多轮异步对话，开发效率提升 40%。",
                                "混合推理引擎：为解决 RAG 语义失准问题，创新部署\"向量+图谱\"双检索路径。利用 PostgreSQL pgvector 结合 Neo4j 实体关联，将复杂查询的准确率提升 35%，有效填补了多跳推理的空白。",
                                "流式响应架构：通过 SSE 协议结合 Redis 原子计数器实现流式数据传输，确保在单机万级 QPS 下 Agent 响应流畅，并引入递归监控有效规避了 Agent 死循环风险。"
                        )
                )
        ));

        return entity;
    }

    private ResumeEntity.SkillItem skill(String category, String... items) {
        ResumeEntity.SkillItem s = new ResumeEntity.SkillItem();
        s.setCategory(category);
        s.setItems(List.of(items));
        return s;
    }

    private ResumeEntity.ProjectItem project(String name, String role, String time,
                                              String description, List<String> highlights) {
        ResumeEntity.ProjectItem p = new ResumeEntity.ProjectItem();
        p.setName(name);
        p.setRole(role);
        p.setTime(time);
        p.setDescription(description);
        p.setHighlights(highlights);
        return p;
    }
}
