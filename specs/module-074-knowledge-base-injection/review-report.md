# module-074 Knowledge-Base Injection — 审查报告

- 审查人：Reviewer（后台子代理，fresh-context 独立视角）
- 审查对象：`ai-meeting-project`（main e5346a5 + develop）中的 module-074 变更
  - `InterviewQuestionExtractionService.java`（KB 注入）
  - `kb/KnowledgeBaseClient.java`
  - `kb/ResumeKeywordExtractor.java`
- 审查基准：`plan.md` + `acceptance-criteria.md` + `changelog.md`
- 结论：**有条件通过**（8 项发现，全部已修复并回归验证）

## 审查发现与修复状态

| # | 严重度 | 发现 | 修复方式 | 状态 |
|---|--------|------|----------|------|
| 1 | 高 | KB 原始内容直接拼进 prompt，存在提示注入面（KB 是不可信数据） | 内容包裹 `<kb_reference>` 数据块 + 显式声明「仅数据、无指令」守卫句；`sanitizeKbContext()` 清洗控制字符/折叠空行/截断 2000 字符 | ✅ 已修复 |
| 2 | 中 | 同步检索无缓存：同一次提取流程对同一简历可能重复同步调用 KB（实测 rerank 延迟 1.9-3.3s，锁内等待放大） | `KnowledgeBaseClient.retrieveContextCached(cacheKey, ...)`，按 resumeContentHash 缓存（上限 500 条，超限整体清空）；保留 callTimeout 8s 不压缩（避免误杀真实检索） | ✅ 已修复 |
| 3 | 中 | `MultipartFile.getBytes()` 被读取两次（哈希一次、抽取一次），重复读临时文件 | 入口一次性 `readResumeBytes()` 后传字节数组给哈希与抽取两条链路 | ✅ 已修复 |
| 4 | 中 | KB 响应无大小上限，超大/畸形响应可拖垮内存 | 先查 `Content-Length` 头（>64KB 拒绝），再流式读取并硬性限制读取量（64KB+1），超限 fail-open | ✅ 已修复 |
| 5 | 低 | `parseResults` 未校验 `results` 是否为数组，畸形 JSON 可能抛异常 | 增加 `isArray()` 检查，非数组返回空串 | ✅ 已修复 |
| 6 | 低 | `MIN_TOKEN_LENGTH` 常量（2）与实际过滤条件（+1 → 实际 3）不一致；debug 日志打印的 count 恒为 MAX_KEYWORDS | 常量改为 3 与实际行为一致；日志改打印实际关键词数 | ✅ 已修复 |
| 7 | 低 | `MIN_FREQUENCY=2` 严重损失召回：重要技术词常只出现一次 | 降为 1（Top-8 截断兜底精度） | ✅ 已修复 |
| 8 | 低 | 失败 warn 日志打印原始 query，可能泄露简历个人信息 | 改为只记录 `queryChars`（长度） | ✅ 已修复 |

## 回归验证

- 编译：`mvn -DforkCount=0 test-compile` 通过（surefire `@{argLine}` 未解析，须 `-DforkCount=0`）
- 单测（module-074 相关）：`KnowledgeBaseClientTest`（9，含 3 个新增：非数组解析 / 缓存命中 / 超大响应 fail-open）、
  `ResumeKeywordExtractorTest`（6）、`InterviewQuestionExtractionServiceTest`（1）全绿
- 全量回归：106 测试中 104 通过；2 个失败均为**基线遗留问题**（module-074 未触碰的模块）：
  ① `InterviewRecordServiceImplTest.shouldFinishInterviewSessionBeforePersistingRecordFromRedis` —
     测试交互期望与 finalize 重构（PR #13/#14 引入重试 + runtime 服务）不一致，需按新流程重写测试（另开模块）；
  ② `XunfeiAudioServiceAssemblerTest.noPgsPartial_ShouldReplaceCurrentLiveSnapshot` —
     media 组装器行为与测试期望不符（expected AB / actual AAB），与 KB 注入无关（另开模块）。
  本轮同时修复了基线编译断裂：5 个测试类 11 处构造调用由 `null, null` 占位补齐为 runtime 服务 mock
  （消除 9 个 NPE + 1 个并发计数失败），基线编译错误 → 104/106 通过。
- 修复未改变 fail-open 契约：KB 不可用时出题仍退化为纯简历模式
