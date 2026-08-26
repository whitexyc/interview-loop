# Module 074 测试报告（module-074：知识库出题注入）

> Tester 独立验收 | 执行方式：后台 subagent fresh-context 独立复跑（非 Developer 自验）

## 验收表

| # | 验收项 | 结果 | 证据 |
|---|--------|------|------|
| 1 | 新增单测全绿 | ✅ | `mvn test -Dtest=KnowledgeBaseClientTest,ResumeKeywordExtractorTest -DforkCount=0` → `Tests run: 12, Failures: 0, Errors: 0`，BUILD SUCCESS（KnowledgeBaseClientTest 6/6 + ResumeKeywordExtractorTest 6/6，6.9s） |
| 2 | kb 配置段存在 | ✅ | application.yaml 尾部 L246-247：`kb:` → `base-url: ${KB_BASE_URL:http://localhost:8001}` |
| 3 | kb 包两个主类存在且非空 | ✅ | KnowledgeBaseClient.java 3496B/90 行；ResumeKeywordExtractor.java 4368B/103 行 |
| 4 | @Value 配置注入 | ✅ | KnowledgeBaseClient.java L42 构造参数注解 grep 直接命中 |

## 附注

- fail-open 行为实证：无 8001 服务时日志输出 `KB search unavailable, fail-open` 降级为 WARN 而非报错，与 ADR-0019 设计一致
- 运行方式说明：本机 surefire `@{argLine}` 未配置 JaCoCo，须加 `-DforkCount=0` 进程内跑测试

## 结论
**验收通过 4/4**。无阻塞项。

## 第二轮回归（审查 8 项修复后，2026-08-25）

- module-074 相关单测全绿：`KnowledgeBaseClientTest` 9/9（新增缓存命中、非数组解析、超大响应 fail-open 三例）+ `ResumeKeywordExtractorTest` 6/6 + `InterviewQuestionExtractionServiceTest` 1/1，共 16/16。
- 全量回归 106 测试：104 通过 / 2 失败，2 个失败均为基线遗留（`InterviewRecordServiceImplTest` finalize 交互期望过期、`XunfeiAudioServiceAssemblerTest` media 行为不符），与 module-074 无关，已记入 review-report.md 待另开模块。
- 环境性修复：5 个测试类 11 处构造调用补 runtime 服务 mock（原 `null, null` 占位 → 消除 9 NPE + 1 并发计数失败）。
- 结论维持：**验收通过 4/4**。
