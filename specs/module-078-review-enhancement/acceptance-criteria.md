# 验收标准 — Module-078: 审查节点增强（质量评分阈值校准 + 矛盾检测 + 审查策略强化）

## 1. 功能验收

### 1.1 阈值配置化
- [ ] config `crawl_hhem_threshold` 默认 0.3（= module-075 硬编码值，零回归），可被 `PW_CRAWL_HHEM_THRESHOLD` 环境变量覆盖；进程内 `settings` 修改即时生效（动态调整）
- [ ] HHEM score < 当前策略阈值 → `review_status="rejected"`；score ≥ 阈值 → 不因分数拒绝
- [ ] 阈值调高（如 0.5）后 score=0.4 的文档由 approved 变 rejected（单测锁定）

### 1.2 审查策略三档
- [ ] fail-open（默认）：审查环节异常（reflector / hhem / 矛盾检测全部失败）→ approved（与 module-075 行为逐字一致，零回归）
- [ ] lenient：矛盾命中 → rejected；审查异常仍 approved（放行）
- [ ] strict：矛盾命中 → rejected；审查异常 → rejected（fail-closed）；阈值使用 `crawl_hhem_threshold_strict`（更严）
- [ ] 三档经 `PW_CRAWL_REVIEW_POLICY` 切换；非法策略值启动即抛 ValidationError（fail-fast，不静默落入某档）

### 1.3 矛盾检测
- [ ] 新抓取文档与库中候选文档判定矛盾（nli/clf/dual）→ lenient/strict 档 rejected；fail-open 档仅记录（日志 + conflict_count），不改变 status
- [ ] 判定器复用 `memory_conflict_judge` 选型：nli / clf / dual 三模式各走对应判定器（不重写 nli_judge / memory_conflict_clf）
- [ ] dual 双确认：nli 与 clf 同时 contradiction 才判矛盾；单判 contradiction → 不判矛盾（宁漏检也不错标，对齐用户哲学）
- [ ] 对称回退：nli 不可用 → clf 单判；clf 不可用 → nli 单判；双不可用 → 跳过矛盾检测（fail-open 回退基础审查）
- [ ] 候选获取仅取根父块（parent_id IS NULL）+ embedding 非空 + cosine ≥ `crawl_conflict_min_cosine`（默认 0.6）的文档，top-K = `crawl_conflict_top_k`（默认 3）
- [ ] 判定器模型缺失 / 返回 None / 嵌入失败 / 推理异常 → 不阻断入库主链路

### 1.4 review_score 入库
- [ ] documents 表新增 `review_score FLOAT` 列（init_db 幂等 ALTER，存量行 NULL 兼容，无迁移脚本）
- [ ] 抓取入库文档 review_score = HHEM score（0-1）；HHEM 不可用 → NULL（诚实不编造）
- [ ] 透传链路完整：`_crawl_page_and_store` → `ingest_document` → `add_document` → Document ORM 四层，默认值 None 向后兼容（存量调用零回归）
- [ ] POST /ai/crawl/run 响应 data 含 `conflict` 计数；summary.details 项含 review_score / conflict

### 1.5 审查日志增强
- [ ] 每次审查一行结构化日志：url / status / score / sufficient / conflict / policy / elapsed_ms
- [ ] 矛盾命中时日志含候选文档 id / 标题 / 判定器

## 2. 非功能验收

### 2.1 性能
- [ ] 单页审查（充分性 + HHEM + 矛盾检测）额外耗时 ≤ 10s（模型热态；冷启动加载除外）
- [ ] 单页抓取 + 审查 + 入库总耗时 ≤ 60s（含网络，与 module-075 一致）
- [ ] 单次 run_crawl 总页数上限不变（默认 10），矛盾检测不扩大抓取量

### 2.2 安全 / 健壮性
- [ ] 矛盾检测任何异常不阻断入库主链路（fail-open）
- [ ] 向量候选查询对 embedding 为 NULL 的行不报错（WHERE embedding IS NOT NULL）
- [ ] strict 档异常拒绝仅在显式切换时生效（默认 fail-open 不误杀）

### 2.3 代码质量
- [ ] 本模块新增生产代码合计 ≤ 200 行（铁律 2，AST 口径，对齐 module-076 先例）
- [ ] 单方法 ≤ 50 行（铁律 3：`_review_content` / `_check_conflict`）
- [ ] 所有新公开方法有 docstring（铁律 4）
- [ ] 无空 catch / 吞异常（铁律 5）
- [ ] 复用 reflector / hhem_judge / nli_judge / memory_conflict_clf / embedding_service，无重写

## 3. 可运行验证命令

| 验收项 | 验证命令 | 预期输出 |
|--------|----------|----------|
| 新增单测 | `cd ai_service && python -m pytest tests/crawl/test_review_enhancement.py -v` | X passed, 0 failed |
| crawl 全量 | `cd ai_service && python -m pytest tests/crawl/ -v` | 63+X passed, 0 failed |
| 全量回归 | `cd ai_service && python -m pytest tests/ -q` | Y passed（基线 1310+ 不降，4 环境性遗留） |
| 策略配置 | `$env:PW_CRAWL_REVIEW_POLICY="strict"; python -c "from src.config import settings; print(settings.crawl_review_policy)"` | strict |
| 阈值配置 | `$env:PW_CRAWL_HHEM_THRESHOLD="0.5"; python -c "from src.config import settings; print(settings.crawl_hhem_threshold)"` | 0.5 |
| 手动触发 | `curl -X POST http://localhost:8001/ai/crawl/run` | data 含 conflict 字段 |
| review_score 列 | init_db 启动日志 / psql `\d documents` | review_score FLOAT 存在 |
| 审查日志 | 触发抓取后查看服务日志 | 一行含 score=… conflict=… elapsed_ms=… |
| py_compile | `cd ai_service && python -m py_compile rag/crawl/crawler.py src/config.py src/database.py rag/models.py rag/retrieval/document_ingest.py rag/engine.py main.py` | 无报错 |
| AST 行数 | REVIEW 阶段口径核对 | 本模块新增生产代码 ≤ 200 行 |

## 4. 验收结论
- 审查人: Reviewer (module-078)
- 测试人: Tester (module-078)
- 验收时间: 待定
- 结论: [ ] 通过 / [ ] 不通过
- 备注: （待 REVIEW/TEST 阶段填写；不通过时注明阻塞项与行号证据）
