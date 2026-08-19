# ADR-0014：多格式文档解析 + 数据清洗 + 去重（四层 ingestion 能力补齐）

## 元信息

- 状态：✅ **已实施 module-064**（2026-08-14：AnyDoc 统一解析层（firecrawl-anydoc 0.1.8，格式识别读字节魔数 + PyMuPDF/轻量回退）+ 五步清洗层（白名单哲学）+ 无损归一化 + PDF 图片三层开关（PW_IMAGE_OCR/PW_IMAGE_CAPTION/PW_PDF_ENGINE 全默认关）+ 原件留存（original_path 列）+ 文档去重三级（doc_content_hash / embedding 余弦≥0.95 标簇 + canonical 抑制 / SimHash 接口预留）；真实 DB 冒烟 md/pdf/docx/xlsx 全管线入库通过；前端 accept 开放 8 格式；全量 pytest 951 基线 + 66 新增全绿（1017/0）；详见 specs/module-064-document-parsing-cleaning/changelog.md）
- 日期：2026-08-14（本 ADR 由 module-064 实施时按 task-brief 六项决策补建，决策内容与 task-brief §二 一致）
- 关联：module-064（执行简报）、rag/retrieval/document_parser.py（解析层）、document_cleaner.py（清洗层）、image_pipeline.py（图片三层）、document_dedup.py（去重三级）、document_ingest.py（管线编排）、main.py（上传端点）、frontend UploadPanel/KnowledgePage（accept 开放）

## 背景：现状（代码实测，2026-08-14）

- **前端** `frontend/src/components/UploadPanel.tsx:149`：`accept=".md,.txt"`——只开放 md/txt；`KnowledgePage.tsx` 同
- **后端** `ai_service/main.py:911` `POST /ai/rag/documents/upload`：只认 `.pdf`（`file.filename.endswith(".pdf")`），PyMuPDF（fitz）提取，每页加分隔后 `add_document` 入库
- **前后端割裂**：后端有 PDF 上传端点但前端未接（前端走 `/rag/documents` JSON 文本通道）；Word/Excel/PPT/EPUB/CSV 完全无支持
- 入库链路：解析 → `chunker.chunk`（标题父块 + 300 字子块）→ embedding → documents 表；**无独立数据清洗层**
- PDF 内嵌图片（流程图/截图）当前信息完全丢失

**目标（本 ADR 六项决策落地）**：① AnyDoc 统一解析层（多格式转 Markdown）② 五步数据清洗层（chunk 前）③ 嵌入前无损归一化 ④ PDF 内嵌图片三层方案（默认关 + 分层路由）⑤ 原始文件留存 original_path ⑥ 文档去重三级处理。

## 决策 1：解析层选型 —— AnyDoc（Firecrawl 开源）+ PyMuPDF 回退

- **AnyDoc**（Firecrawl 开源，Rust 实现）：14 格式统一 GFM Markdown 输出，中位 4.4ms，质量 81 分全格式第一，零系统依赖无模型；Python 绑定释放 GIL
- **格式识别读字节内容标记**（`anydoc.format_from_bytes` 魔数探测：PDF 的 `%PDF`、zip 类 docx/xlsx 的 `PK\x03\x04`），md/txt/csv 无魔数用扩展名兜底——不靠扩展名一刀切
- **PyMuPDF 保留 PDF 回退**：AnyDoc 失败/不可用 → 存量 `main.py:911` 逻辑提取为可复用函数（存量行为兼容）
- docx/xlsx/csv 提供轻量回退（python-docx/openpyxl/csv 标准库）；pptx/epub 无轻量回退时如实报"需 AnyDoc 解析引擎"
- 错误变体映射用户提示：Unsupported/Malformed/Encrypted/ResourceLimit/MissingPart → 明确中文提示

## 决策 2：五步数据清洗层（chunk 前）—— 白名单哲学

| 步 | 内容 | 关键点 |
|---|---|---|
| ① 格式清理 | 去页眉页脚/页码/水印残留/乱码/控制字符，Unicode NFKC 统一标点 | 页码行（第 N 页 / Page N of M）正则移除 |
| ② 冗余过滤 | 无意义短段落/纯符号段落过滤 | 可配置长度下限；纯符号/噪声段丢弃 |
| ③ 结构恢复 ⭐ | 合并 PDF 断行切碎的段落、还原标题层级、表格结构化 | 段落内连续行按 CJK/连字符规则并入；标题行不与正文粘连；`#`→`##` 对齐 chunker |
| ④ 语义修复 | 可选，规则级先做（OCR 常见错字表留空待补） | OCR_TYPO_MAP 空表诚实声明 |
| ⑤ 分块准备 | 标题层级规范化对齐 MarkdownHeaderTextSplitter | `#`(H1)→`##`(section 级)，标题/表格前补空行 |

- **白名单哲学（关键纪律）**：清洗规则按块类型作用（正文/表格/代码块/行内代码分开）——代码块符号不清、表格合并单元格不拆、URL/LaTeX/行内代码原样保留；正文内联元素用占位符（⟦N⟧）先保护再清洗，防 NFKC/空格折叠误伤

## 决策 3：嵌入前无损归一化

- 无损：NFKC、去零宽/不可见控制符（Cf/Cc）、统一空白（块外折叠多空格 + 去行尾空白）、UTF-8
- **表格保持 Markdown 表格**（不转纯文本）；代码块缩进不被空白折叠破坏（白名单）
- 超长截断（防 embedding 截断）：chunker 已把父块限制 4000 / 子块 300（嵌入输入有界），`normalize(max_chars)` 为病态超长文档的兜底，默认不截
- **改词/换词/总结不做**（伤语义）

## 决策 4：PDF 内嵌图片三层方案 —— 全默认关 + 分层路由

| 层 | 开关 | 内容 |
|---|---|---|
| L1 | `PW_IMAGE_OCR` | PaddleOCR/RapidOCR 图内文字 OCR，图内文字插回 MD |
| L2 | `PW_IMAGE_CAPTION` | 本地轻量 VLM 图片描述插回 MD（显式占位符替换） |
| L3 | `PW_PDF_ENGINE=mineru` | MinerU 独立通道（复杂版面整体重解析） |

- **三层全默认关**（重工具不默认启用，只路由复杂文档）；模型/组件缺失 → 对应层降级关（fail-open）
- **图片价值过滤**（只留流程图/架构图/UML/产品截图/表格截图）：面积占比 + OCR 质量 + VLM 评分（`image_value_filter` 接口，真实评分需模型可用后回填）
- **诚实边界**：默认关时 PDF 含图不报错（走文本部分）；扫描版 PDF 无 OCR 时如实返回"图片未解析"提示

## 决策 5：原始文件留存（original_path）

- 上传解析后**原始文件落盘**（`ai_service/uploads/`，`PW_UPLOAD_DIR` 可配），documents 表加 `original_path` 列（init_db 幂等 ALTER + `scripts/migrate_module064.py` 本地先决）
- 重灌（reindex）/改分块策略必须有原件——原件是重灌依赖

## 决策 6：文档去重三级

| 级 | 方案 | 行为 |
|---|---|---|
| L1 | 内容哈希（sha256，文档级 `doc_content_hash` 列） | 完全相同 → **直接丢弃**（不落原件不入库） |
| L2 | 文档级 embedding 余弦（bge-m3 + 绝对余弦口径，复用 module-035 同款）≥0.95 | **不删**，标 `duplicate_cluster_id` + canonical 选择（留最新/结构完整），检索抑制只出 canonical（engine._expand_to_parents 过滤） |
| L3 | 结构指纹/SimHash-LSH | 文档量几千+ 才上（当前 O(N²) 够用），接口预留标注"待规模" |

- **三个坑**：① Boilerplate 先剥离（共同页脚/免责声明主导相似度前先扒）② 同源内语义去重（不跨 source 折叠，identity 与 content 分离，版本化兼容）③ 文档级 embedding 存于文档根父块（parent_id IS NULL 首父块）的既有 embedding 列——父块不参与向量检索（retriever 只查 parent_id IS NOT NULL 子块），复用零新增 Vector 列
- 存量 124 篇旧文档 embedding=NULL（不参与 L2 语义比较，靠 L1/title），如实声明

## 实施顺序（module-064 WP1→WP7，已完成）

| WP | 内容 | 通过标准 |
|---|---|---|
| WP1 | AnyDoc 解析层集成 + main.py upload 接入 + 前端 accept 开放 | 多格式上传冒烟 md/pdf/docx/xlsx 文本非空；错误格式明确提示 |
| WP2 | 五步清洗层（白名单哲学） | 清洗单测含代码块/表格/URL 不误伤；chunker 输出结构零破坏 |
| WP3 | 无损归一化 | 归一化单测；不改语义 |
| WP4 | PDF 图片三层开关 + 占位符替换 | 开关逻辑 + 占位符替换单测；默认关不报错 |
| WP5 | 原件落盘 + original_path 列 | 原件在 + original_path 落库；重灌可用 |
| WP6 | 去重三级 + canonical 抑制 | 三级单测；124 篇冒烟报告命中量不破坏现有库 |
| WP7 | 测试 + 文档 + 记忆 | 全量 pytest 951+N 全绿 |

## 面试话术（30 秒）

> "知识库 ingestion 原来是单格式（PDF）+ 无清洗的：前端只开放 md/txt、后端只认 pdf，Word/Excel/PPT 完全进不来，PDF 里的流程图信息全丢。我按 ADR-0014 补齐四层 ingestion：第一，AnyDoc 统一解析层——Firecrawl 开源的 Rust 文档解析引擎，14 种格式统一转 GFM Markdown，格式识别读字节魔数而不是靠扩展名，PDF 保留 PyMuPDF 回退；第二，五步数据清洗层，核心是白名单哲学——按块类型作用，代码块、表格、URL、LaTeX 一律不误伤，重点解决 PDF 断行把段落切碎的问题；第三，嵌入前无损归一化，只改格式不改语义（NFKC、去零宽、统一空白）；第四，三级去重——内容哈希完全相同直接丢弃、文档级 embedding 余弦 0.95 以上的语义重复不删但标簇抑制检索、SimHash 大规模才上。另外 PDF 内嵌图片做了三层开关（OCR/VLM/MinerU）但默认全关，重工具只路由复杂文档，扫描版 PDF 无 OCR 时如实提示而不是假装支持。原始文件落盘 original_path，改分块策略能重灌。"

## 验收标准（已实施，module-064 全过）

- [x] 多格式上传冒烟（md/pdf/docx/xlsx）解析文本非空入库；错误格式明确提示
- [x] 清洗白名单单测：代码块/表格/URL/LaTeX/行内代码不误伤；chunker 输出结构零破坏
- [x] 归一化单测：NFKC/去零宽/统一空白/表格保持 MD/超长截断；不改语义
- [x] 三层开关默认关；默认关 PDF 含图不报错；扫描版无 OCR 返回"图片未解析"提示（fail-open）
- [x] 原件落盘 + original_path 落库；migrate_module064.py 本地先决已执行
- [x] 三级去重单测；真实 DB 冒烟 md/pdf/docx/xlsx 全管线入库 + 清理不破坏现有库
- [x] 前端 accept 开放 8 格式 + 文案更新；前端 build + vitest 56/56
- [x] 全量 pytest 951 基线 + 64 新增全绿
