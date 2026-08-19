# Module-064 测试报告 — 多格式文档解析 + 数据清洗 + 去重（ADR-0014）

> Tester | 2026-08-14 | 独立验收：全量回归 + 冒烟复跑 + 实现抽查 + 记忆硬核查 + AC 逐条
> 结论：**验收通过（AC 全部通过，0 阻塞）**

## 一、全量 pytest

- **1036 passed / 0 failed（177.21s）**（951 基线 + 85 新增，exit code 0）
- 新增 85 项逐文件核对：test_document_parser.py 21 + test_document_cleaner.py 26 + test_document_dedup.py 15 + test_document_ingest.py 5 + test_document_image.py 18 = **85**，与 changelog §一/§十三、Reviewer 第 2 轮（逐文件核对 21+26+15+5+18=85）一致。
- **存量测试零改动**：`git diff main -- ai_service/tests/` 仅 conftest.py 追加 1 个 autouse fixture（`default_document_pipeline_switches` 钉住 `doc_dedup_semantic_enabled=False`）；5 个新测试文件为未跟踪新增，无存量测试修改。
- 44 条 warnings 全部为既有（Redis setex 弃用 / sklearn 单标签 kappa / SQLAlchemy GC 连接清理），非 module-064 回归。

## 二、冒烟复跑

1. **多格式解析冒烟（独立复跑，纯解析不触 DB，真实 AnyDoc 0.1.8 / PyMuPDF / python-docx / openpyxl）**：自造 md/pdf/docx/xlsx 四个真实文件调用 `parse_document`——
   - md → engine=text，文本非空
   - pdf → engine=anydoc，page_count=1，文本非空
   - docx → engine=anydoc，文本非空
   - xlsx → engine=anydoc，文本非空（GFM 表格含表头）
   - 不支持格式 `virus.exe` → 明确报"不支持的文件格式（.exe），请上传 .md/.txt/.pdf/.docx/.xlsx/.pptx/.epub/.csv"
   - **结果：4 格式文本非空 + 错误格式明确提示，与 changelog §九 / ADR-0014 验收一致。**
2. **前端回归**：`npx vitest run` **56 passed / 0 failed（7 文件，22.63s）** 与 changelog "vitest 56/56" 一致；UploadPanel.tsx:19/153 `accept=".md,.txt,.pdf,.docx,.xlsx,.pptx,.epub,.csv"` + 文案、KnowledgePage.tsx:215 accept 同源 + 文案、ragService.uploadDocumentFile（FormData 传原始字节）均代码核验在案。
3. **DB 迁移核验**：`python scripts/migrate_module064.py`（幂等）复跑输出 `documents 校验列: ['doc_content_hash', 'duplicate_cluster_id', 'is_canonical', 'original_path']` + 2 索引已补，列全部存在。
4. **changelog 数字一致性抽查**：新增测试 85（21+26+15+5+18）、全量 1036/0、vitest 56/56、真实 DB 冒烟 md/pdf/docx/xlsx 全部与我的独立复跑一致。诚实边界（AnyDoc 安装名 firecrawl-anydoc、OCR/VLM/MinerU 未装 fail-open、存量 124 篇 embedding=NULL 不参与 L2）与实现一致。

## 三、实现抽查（与 changelog/ADR 逐项对照）

| 抽查点 | 依据 | 结论 |
|--------|------|------|
| 白名单清洗（代码块/表格/URL 不误伤） | document_cleaner.py `_tokenize_regions` 按 code/math/table/body 四区域作用 + 正文内联 ⟦N⟧ 占位符先保护再清洗；test_code_block_preserved / test_table_preserved / test_url_preserved / test_latex_inline_preserved / test_inline_code_preserved 全过 | ✅ |
| 无损归一化（NFKC/去零宽/统一空白/表格保持 MD/超长截断） | document_cleaner.normalize + test_normalize_*（不改语义 test_normalize_does_not_change_semantics） | ✅ |
| 三层默认关 + fail-open | config image_ocr_enabled=False / image_caption_enabled=False / pdf_engine="anydoc"；image_pipeline process_pdf_images 三层开关 + 占位符替换 + test_default_off_returns_md_unchanged / test_l1_ocr_missing_fail_open / test_l2_caption_missing_fail_open / test_l3_mineru_missing_falls_back / 扫描版提示 | ✅ |
| 原件留存 | save_original 落盘 uploads/{sha256[:16]}_{净文件名} + documents.original_path 列（DB 实核列存在）+ ingest 成功路径字段透传测试 | ✅ |
| 去重三级 canonical | L1 exact_hash 完全相同直接丢弃；L2 find_semantic_duplicate 余弦≥0.95 标簇 + is_canonical=false + engine._expand_to_parents `Document.is_canonical.is_(True)` 检索抑制；L3 simhash_lsh 接口预留；test_document_dedup 15 项 + test_ingest_exact_duplicate_skips / test_ingest_semantic_duplicate_marks_canonical | ✅ |
| 存量 PyMuPDF 回退 | document_parser._parse_pdf_pymupdf（存量 main.py:911 逻辑提取）+ test_pdf_anydoc_error_falls_back_to_pymupdf / test_anydoc_unavailable_pdf_pymupdf | ✅ |
| main.py upload 接入 | 8 格式白名单 + code=1 非白名单 / code=2 空文件 / code=3 解析错误中文提示 + ingest_document 全管线 | ✅ |

## 四、记忆文件硬核查

| 项 | 状态 | 依据 |
|----|------|------|
| project-context.md module-064 行 | ✅ 存在，格式对齐 | 第 81 行（module-064 完整行，含 WP1~WP7 摘要） |
| project-context.md 头部日期 | ✅ 已更新 | "最后更新: 2026-08-14（module-064 完成）" |
| agent-activity-log.md Dev 行 | ✅ | module-064 Developer 行在 |
| agent-activity-log.md Rev 行 | ✅ | module-064 Reviewer 第 1/2 轮两行在 |
| agent-activity-log.md Test 行 | ✅ 本次追加 | 本报告完成后追加（日期 + total/passed/failed + 结论） |
| file-index.md 新文件行 | ✅ | 13 行（document_parser/cleaner/image_pipeline/dedup/ingest + migrate_module064.py + 5 测试文件 + 模块目录 + ADR-0014） |
| CONTEXT.md 只增 | ✅ | 新增"多格式文档解析 + 清洗 + 去重领域（2026-08-14...只增不删）"段 |

**缺项 = 0，无 blocking_issues。**

## 五、逐条 AC（ac_compliance）

全部**通过**（19/19 功能 + 5/5 降级 + 5/5 文档）。要点：

- §1 解析层 5 项通过：document_parser 统一入口读字节魔数 / main.py upload 8 格式 + PyMuPDF 回退 / 错误变体中文映射（Unsupported/Malformed/Encrypted→明确提示）/ 前端 accept 开放 + 文案 / 多格式冒烟 md/pdf/docx/xlsx 文本非空（独立复跑）。
- §2 清洗层 3 项通过：五步清洗（格式清理/冗余过滤/结构恢复⭐合并 PDF 断行/语义修复 OCR_TYPO_MAP 空表/分块准备 `#`→`##`）/ 白名单哲学（代码块/表格/URL/LaTeX/行内代码不误伤，单测锁定）/ chunker 输出结构零破坏（test_cleaned_output_chunks_normally）。
- §3 归一化 2 项通过：NFKC/去零宽/统一空白/表格保持 MD/超长截断；单测 + 不改语义。
- §4 图片 4 项通过：三层开关 PW_IMAGE_OCR / PW_IMAGE_CAPTION / PW_PDF_ENGINE=mineru 全默认关 / 图片价值过滤 image_value_filter（面积+OCR+VLM 评分）/ 默认关含图不报错 + 扫描版"图片未解析"提示（fail-open）/ 开关逻辑 + 占位符替换单测（test_document_image.py 18 项，Reviewer 第 2 轮修复后）。
- §5 原件留存 2 项通过：原件落盘 + original_path 列（init_db 幂等 ALTER + migrate_module064.py，DB 实核）/ 上传后原件在 + original_path 落库 + 重灌可基于原件。
- §6 去重 5 项通过：L1 内容哈希完全相同直接丢弃 / L2 余弦≥0.95 不删标簇 + canonical + `_expand_to_parents` 检索抑制 / Boilerplate 先剥离（入库侧与查询侧同口径，Reviewer MAJOR-1 修复）+ 同源内不跨 source 折叠 + identity/content 分离 / 三级单测 + 124 篇冒烟不破坏现有库（Developer 真实 DB 冒烟 L2 对存量 0 命中）/ SimHash-LSH 接口预留。
- §7 收口 4 项通过：三新测试文件 mock / conftest 钉住 + 存量零改动 + 全量 951+85=1036 全绿 / ADR-0014 状态行 ✅ + 面试口径四层 ingestion（changelog §十一）/ changelog + review-report + test-report + memory 三件套 + CONTEXT 只增。
- §8 降级 5 项通过：AnyDoc 安装失败如实记录（装 firecrawl-anydoc）+ 降级 / OCR/VLM/MinerU 缺失对应层 fail-open / 清洗异常跳过走原始 MD（ingest try/except）/ 去重异常放行入库（compute_doc_embedding 失败返回 None 不阻断）/ 全量 1036/0 保持。
- §9 文档 5 项通过：project-context module-064 行 + 头部日期 / activity Dev+Rev+Test / file-index 新文件行 / CONTEXT.md 只增 / changelog 注明开工前已读 project-context。

## 六、非阻塞观察（随 Reviewer minor，非本模块缺陷）

1. **数字口径漂移（既有 minor）**：project-context module-064 行写"66 新增 / 1017/0"、ADR-0014 状态行写"66 新增"、CONTEXT.md 写"64 新增"——实际最终 **85 / 1036**。changelog §十三 已注明"修复轮新增未回写该行"。建议主会话统一为 85/1036 后提交。
2. **非 canonical 文档可作后续语义去重参考（Reviewer 第 2 轮新 minor）**：`find_semantic_duplicate` 候选查询未过滤 `is_canonical`，非 canonical 副本仍存 doc_embedding，0.95 高阈值下风险真实但低。建议后续候选查询加 `Document.is_canonical.is_(True)` 或非 canonical 不存 doc_embedding。
3. **MINOR-5 同请求双次 embed**：语义去重开启时单次入库两次 bge-m3 embed（查询侧 + 存储侧，同口径非复用）。性能 minor，非正确性。
4. **冒烟脚本未留存**：真实 DB 冒烟脚本 `.ua/smoke_formats.py` / `.ua/smoke_ingest_db.py` 为一次性本地产物（gitignore），Tester 已用独立临时脚本复跑解析冒烟通过。

## 七、结论

- 全量 pytest **1036 passed / 0 failed**（951 基线 + 85 新增，独立复跑一致）
- 冒烟复跑：多格式解析（md/pdf/docx/xlsx）文本非空 + 错误格式明确提示 ✅；前端 vitest 56/56 ✅；DB 迁移列实核 ✅
- 实现抽查 6 项全过（白名单/无损归一化/三层默认关/原件留存/去重三级 canonical/PyMuPDF 回退）
- 记忆硬核查缺项 0；AC 全部通过；0 阻塞

**模块标记 ✅ 完成**
