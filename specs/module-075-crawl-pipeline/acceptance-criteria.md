# 验收标准 — Module-075: 知识抓取流水线（定时调度 + 源配置 + 入库闭环）

## 1. 功能验收

### 1.1 核心路径验收
- [ ] 添加抓取源配置（POST /ai/crawl/sources）后，GET /ai/crawl/sources 返回该配置
- [ ] 手动触发抓取（POST /ai/crawl/run）后，目标 URL 内容经 document_ingest 入库（documents 表新增行）
- [ ] 白名单域名（如 spring.io）的 URL 允许抓取
- [ ] 黑名单域名（如 csdn.net 纯搬运）的 URL 被跳过（日志记录，不入库）
- [ ] 审查节点：抓取内容经 reflector.check_sufficiency 检查，不通过标记 review_status="rejected"
- [ ] 审查通过的文档 review_status="approved"，可被现有 /ai/rag/search 检索到

### 1.2 边界条件验收
- [ ] 源配置 URL 为空时返回错误（code=1）
- [ ] 抓取目标返回 404/500 时跳过该 URL（fail-open，不阻断其他 URL）
- [ ] 抓取目标超时（>30s）时跳过（fail-open）
- [ ] 抓取目标返回非 HTML 内容（如 PDF 二进制）时，走 document_parser 解析

### 1.3 异常场景验收
- [ ] httpx 网络异常时，单页失败不阻断整批抓取
- [ ] reflector 审查调用失败时，默认 approved（fail-open，不误杀）
- [ ] factcheck_judge 不可用时（HHEM 缺失），审查跳过（fail-open）

## 2. 非功能验收

### 2.1 性能验收
- [ ] 单页抓取 + 审查 + 入库 ≤ 60s（含网络延迟）
- [ ] 批量抓取（10 页）串行执行，总耗时 ≤ 10 分钟

### 2.2 安全验收
- [ ] 抓取 URL 仅允许 http/https 协议（防 file:///etc/passwd）
- [ ] 抓取内容不包含敏感信息（.env / credentials 等路径过滤）

### 2.3 代码质量验收
- [ ] 生产代码合计 ≤ 200 行（铁律 2）
- [ ] 所有公开方法有 docstring（铁律 4）
- [ ] 无空 catch / 吞异常（铁律 5）

## 3. 可运行验证命令

| 验收项 | 验证命令 | 预期输出 |
|--------|----------|----------|
| 单测全绿 | `cd ai_service && python -m pytest tests/crawl/ -v` | `X passed, 0 failed` |
| 全量回归 | `cd ai_service && python -m pytest tests/ -q` | `Y passed, 0 failed`（含基线） |
| 添加源配置 | `curl -X POST http://localhost:8001/ai/crawl/sources -H "Content-Type: application/json" -d '{"url_pattern":"https://spring.io/docs","name":"Spring Docs"}'` | `{"code":0, ...}` |
| 查询源配置 | `curl http://localhost:8001/ai/crawl/sources` | `{"code":0, "data":{"sources":[...]}}` |
| 手动触发抓取 | `curl -X POST http://localhost:8001/ai/crawl/run` | `{"code":0, "data":{"crawled":N, "rejected":M, ...}}` |
| 查看入库文档 | `curl http://localhost:8001/ai/documents?page=1` | 新抓取文档出现在列表中 |
| 黑名单过滤 | 添加 csdn.net 源 → 触发抓取 → 查看日志 | 日志含 "黑名单域名跳过" |
| 审查标记 | 查询 review_status 列 | approved/rejected 值存在 |
| py_compile | `cd ai_service && python -c "import py_compile; py_compile.compile('rag/crawl/crawler.py')"` | 无报错 |
| conftest 钉住 | `cd ai_service && python -m pytest tests/ -q --co | grep crawl` | crawl 测试被收集且 crawl_enabled=false |

## 4. 验收结论
- 审查人: Reviewer (module-075, 重审轮 2)
- 测试人: Tester (module-075, 最终全量验收)
- 验收时间: 2026-08-26
- 结论: [ ] 通过 / [x] 不通过
- 备注: 单测 30/30 全绿；全量 1277/4 环境性/3 跳过；关键测试 test_stream_truncation_marker_emitted 2/2 通过（截断标记修复属实）；HTML 入库修复属实（.txt 路由 + html 回退实测通过）。**不通过原因**：新发现阻塞——审查节点 review_status 落库断链（_review_content 判定的 rejected 只存在于内存，ingest_document/add_document 调用链均不接收该参数，全项目无任何 DB 写入路径，documents.review_status 恒为 DEFAULT 'approved'），验收项 1.1「审查不通过标记 review_status='rejected'」与 §3「查询 review_status 列 → approved/rejected 值存在」不满足。详见 test-report.md §4。
