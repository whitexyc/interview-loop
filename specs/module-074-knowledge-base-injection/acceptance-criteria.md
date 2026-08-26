# Module 074 验收标准

## 一、功能验收

| # | 验收项 | 验证方式 | 通过标准 |
|---|--------|----------|----------|
| F1 | KnowledgeBaseClient 正常检索 | mock/真实 8001 返回 200 | 拼接文本含 results[].content |
| F2 | fail-open：8001 不可达 | 停服或错误端口 | 返回空串、不抛异常、出题主链路继续 |
| F3 | fail-open：非 200 响应 | mock 500 | 返回空串 |
| F4 | 出题 prompt 含知识库上下文 | 代码审查 + 集成观察 | EXTRACTION_PROMPT 后拼接「参考知识点」段 |
| F5 | 简历关键词抽取 | 单测：样例 PDF 文本 → top 关键词 | 技术词保留、停用词滤除、数量 ≤N |
| F6 | 配置化 | application.yaml `kb.base-url` 可被 KB_BASE_URL 环境变量覆盖 | 存在且默认 localhost:8001 |

## 二、回归验收

| # | 验收项 | 通过标准 |
|---|--------|----------|
| R1 | 编译 | mvn compile 通过 |
| R2 | 存量测试 | 既有测试套件通过（BusinessAgentResolverTest 等） |
| R3 | 主链路不变 | KB 失败时 extractInterviewQuestions 行为与改动前一致（纯简历出题） |
| R4 | 新增代码行数 | ≤200 行生产代码（铁律 2）；方法 ≤50 行（铁律 3） |

## 三、文档验收

| # | 验收项 | 通过标准 |
|---|--------|----------|
| D1 | changelog.md 含验证命令输出 | 存在 |
| D2 | ADR-0019 验收标准阶段 1 勾选 | 更新 |
| D3 | 三件套记忆更新 | activity-log + project-context 登记 |

## 四、结论区（实施后填写）
