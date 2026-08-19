# 验收标准 — Module-064: 多格式文档解析 + 数据清洗 + 去重

> 图例：📋 功能 / 📦 降级 / 🔌 接口 / 🧪 测试 / 📝 文档
> 范围（ADR-0014 六项决策）：WP1 解析层 / WP2 清洗层 / WP3 归一化 / WP4 PDF 图片 / WP5 原件留存 / WP6 去重 / WP7 收口

## 1. 功能验收（WP1 AnyDoc 解析层）

- [ ] 📋 `document_parser.py`：统一解析入口（字节+文件名 → Markdown）；格式识别读字节内容标记（非扩展名）
- [ ] 📋 `main.py:911 upload` 接入统一解析层，多格式（md/txt/pdf/docx/xlsx/pptx/epub/csv）；PyMuPDF 保留 PDF 回退
- [ ] 📋 错误变体映射用户提示（Unsupported/Malformed/Encrypted → 明确中文提示）
- [ ] 📋 `frontend UploadPanel.tsx:149` accept 开放多格式 + 文案更新
- [ ] 📋 多格式上传冒烟：md/pdf/docx/xlsx 各一 → 文本非空入库

## 2. 功能验收（WP2 数据清洗层）

- [ ] 📋 `document_cleaner.py` 五步：格式清理（页眉页码/乱码/NFKC）/ 冗余过滤（短段落）/ 结构恢复（⭐合并 PDF 断行）/ 语义修复（规则）/ 分块准备
- [ ] 📋 **白名单哲学**：规则按块类型作用（正文/表格/代码块/行内代码）；代码块符号不清、表格合并单元格不拆、URL/LaTeX 不动
- [ ] 📋 清洗单测含"不误伤"用例；`chunker.chunk` 输出结构零破坏

## 3. 功能验收（WP3 嵌入归一化）

- [ ] 📋 无损归一化：NFKC / 去零宽控制符 / 统一空白 / 超长截断；**表格保持 Markdown 表格**
- [ ] 📋 归一化单测；不改变语义（改词/换词/总结不做）

## 4. 功能验收（WP4 PDF 内嵌图片）

- [ ] 📋 三层开关：`PW_IMAGE_OCR`（L1）/ `PW_IMAGE_CAPTION`（L2 VLM 描述显式占位符替换）/ `PW_PDF_ENGINE=mineru`（L3）——**全默认关**
- [ ] 📋 图片价值过滤（面积占比 + OCR 质量 + VLM 评分）
- [ ] 📋 默认关时 PDF 含图不报错（走文本部分）；扫描版无 OCR 返回"图片未解析"提示（fail-open）
- [ ] 📋 开关逻辑 + 占位符替换单测

## 5. 功能验收（WP5 原始文件留存）

- [ ] 📋 原件落盘 + documents 加 `original_path` 列（init_db 幂等 ALTER + migrate_module064.py 本地先决）
- [ ] 📋 上传后原件在 + original_path 落库；重灌（reindex）可基于原件

## 6. 功能验收（WP6 文档去重三级）

- [ ] 📋 内容哈希（sha256 复用 content_hash）：完全相同 → 直接丢弃
- [ ] 📋 文档级 embedding 余弦≥0.95：**不删**，标 `duplicate_cluster_id` + canonical 选择（留最新/结构完整/权威）；检索抑制（查询只出 canonical）
- [ ] 📋 Boilerplate 先剥离（页脚/免责声明）；同源内语义去重（不跨源折叠）；identity 与 content 分离（版本化）
- [ ] 📋 三级单测；现有 124 篇去重冒烟（报告命中量，不破坏现有库）
- [ ] 📋 SimHash-LSH 接口预留（标注"文档量几千+ 才启用"）

## 7. 验收（WP7 收口）

- [ ] 📋 `tests/test_document_parser.py` / `test_document_cleaner.py` / `test_document_dedup.py`（新，mock AnyDoc/模型）
- [ ] 📋 conftest 相关开关钉住；存量测试零改动；全量 **951 基线 + 新增** 全绿
- [ ] 📋 ADR-0014 状态行 ✅；面试口径更新点（四层 ingestion）
- [ ] 📋 changelog / review-report / test-report + memory 三件套 + CONTEXT 只增

## 8. 降级验收

- [ ] 📦 AnyDoc 安装失败 → 如实记录，评估降级（PyMuPDF 扩展），不硬装
- [ ] 📦 OCR/VLM/MinerU 模型缺失 → 对应层降级关（fail-open），文本部分照常入库
- [ ] 📦 清洗异常 → 跳过清洗走原始 Markdown（fail-open，不阻断入库）
- [ ] 📦 去重异常 → 放行入库（不因去重失败拒收文档）
- [ ] 📦 全量 pytest 951+N 全绿保持

## 9. 文档验收（含记忆硬性约束）

- [ ] 📝 **memory/project-context.md 追加 module-064 行** + 头部日期
- [ ] 📝 **memory/agent-activity-log.md**：Dev/Rev/Test 活动行
- [ ] 📝 **memory/file-index.md**：新文件行
- [ ] 📝 **CONTEXT.md 只增不删**（解析/清洗/去重术语）
- [ ] 📝 开工前必读 project-context.md（Developer 在 changelog 注明已读）
