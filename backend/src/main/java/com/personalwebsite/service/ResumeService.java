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

        // Projects
        entity.setProjects(List.of(
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
                ),
                project(
                        "Graph RAG 智能烹饪知识助手",
                        "后端开发工程师",
                        "2026.02 - 至今",
                        "利用 Neo4j 图数据库与 Milvus 向量库构建高性能推理系统，针对复杂烹饪指令进行语义解析与结构化路径推理。",
                        List.of(
                                "图数据建模优化：设计菜谱领域模型（食材-工艺-口味关系），存储超 500+ 关联节点，通过 Cypher 查询语句深度优化，将复杂逻辑请求响应耗时从 1.2s 压低至 500ms 内。",
                                "吞吐量优化：引入 Milvus 构建高维向量索引，通过对比实验证明向量检索吞吐量提升 3 倍，支持全库万级文档毫秒级召回。",
                                "智能路由系统：研发意图识别分类器，动态切换\"传统向量检索\"与\"Graph RAG 推理\"策略，路由准确率达到 95%，显著增强了系统处理推理型问题的逻辑深度。",
                                "反馈闭环机制：建立基于日志的用户反馈评价指标，动态调整权重参数，使系统推理准确率在一个月内提升 15%，覆盖了 90% 以上的复杂场景查询。"
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
