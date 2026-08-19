# Module-064 变更日志 — 多格式文档解析 + 数据清洗 + 去重（ADR-0014 实施）

> Developer 产出 | 2026-08-14 | 中文，含实现决策/取舍/测试结果/诚实边界/口径声明
> 开工前已读 memory/project-context.md 全文（模块清单/ADR 索引/迭代状态，含 951 基线）
> 决策依据：specs/module-064-document-parsing-cleaning/task-brief.md（WP1~WP7）
> 注：ADR-0014 文件原本缺失（Planner 未产出），本模块按 task-brief §二 六项决策补建
> `specs/adr/0014-document-parsing-cleaning.md` 并标 ✅ 已实施，决策内容与 task-brief 一致

## 一、实现总览

落地 ADR-0014 六项决策，补齐知识库 ingestion 前两层（解析→清洗），多格式（md/txt/pdf/docx/xlsx/pptx/epub/csv）统一接入。七个工作包：

| WP | 内容 | 产出 |
|----|------|------|
| WP1 | AnyDoc 统一解析层（格式识别读字节 + PyMuPDF/轻量回退 + 错误映射）+ main.py upload 接入 + 前端 accept 开放 | rag/retrieval/document_parser.py / main.py / frontend |
| WP2 | 五步清洗层（白名单哲学：按块类型作用） | rag/retrieval/document_cleaner.py |
| WP3 | 无损归一化（NFKC/去零宽/统一空白/表格保持/超长截断） | document_cleaner.normalize |
| WP4 | PDF 图片三层开关（PW_IMAGE_OCR/PW_IMAGE_CAPTION/PW_PDF_ENGINE 全默认关 + 占位符替换 + 价值过滤 + fail-open） | rag/retrieval/image_pipeline.py |
| WP5 | 原件留存（落盘 + documents.original_path 列 init_db 幂等 ALTER + migrate_module064.py） | rag/engine.py / src/database.py / scripts/ |
| WP6 | 去重三级（doc_content_hash / embedding 余弦≥0.95 标簇 + canonical 抑制 / SimHash 接口预留 + Boilerplate 先剥离） | rag/retrieval/document_dedup.py / engine._expand_to_parents |
| WP7 | 管线编排 + 测试 + 文档 + 记忆 | rag/retrieval/document_ingest.py / tests / changelog / ADR / memory / CONTEXT |

**新增测试 85 项**（tests/core/：test_document_parser.py 21 + test_document_cleaner.py 26 + test_document_dedup.py 15 + test_document_ingest.py 5 + test_document_image.py 18）。**全量 pytest 951 基线 + 85 新增全绿（1036 passed / 0 failed）**（存量测试零改动，详见 §八；Review 修复轮补充 test_document_image.py 直接单测 + ingest Boilerplate 口径测试，见 §十三）。前端 build PASS + vitest **56/56**。真实 DB 冒烟 md/pdf/docx/xlsx 全管线入库通过（详见 §九）。

## 二、WP1 AnyDoc 解析层集成（核心）

- **AnyDoc 安装**：`pip install anydoc` → PyPI 无此包；改装 **`firecrawl-anydoc==0.1.8`**（Firecrawl 开源 AnyDoc 引擎的 PyPI 绑定，3.6MB cp310-abi3-win_amd64 wheel）成功——14 格式统一 GFM Markdown、零系统依赖无模型。同时装 python-docx/openpyxl/python-pptx 作轻量回退与测试 fixture。**如实记录**：`anydoc` 包名不可用，`firecrawl-anydoc` 是真实可达的安装名（ADR §"零系统依赖"验证成立：无需模型/系统依赖）。
- **`rag/retrieval/document_parser.py`（统一解析入口）**：
  - `parse_document(data, filename) -> ParsedDocument(text, format, engine, page_count)`——字节 + 原始文件名 → Markdown。
  - **格式识别读字节内容标记**：`anydoc.format_from_bytes`（魔数探测：PDF `%PDF`、zip 类 docx/xlsx `PK\x03\x04`）；md/txt/csv 无魔数 → 扩展名兜底（`_EXTENSION_FORMATS`）；最终未知 → `DocumentParseError("不支持的文件格式...")`。**不靠扩展名一刀切**（决策 1）。
  - **PDF 回退**：AnyDoc 失败 → PyMuPDF（存量 main.py:911 逻辑提取为 `_parse_pdf_pymupdf`，每页 `--- Page i/N ---` 分隔，page_count 透传）；AnyDoc 整体不可用 → pdf 走 PyMuPDF、docx/xlsx/csv 走轻量回退（python-docx/openpyxl/csv）、pptx/epub 明确报"需 AnyDoc 解析引擎"（诚实降级，不假装支持）。
  - **错误变体映射**：Unsupported→"不支持的文件格式" / Malformed→"文件已损坏" / Encrypted→"文件已加密" / ResourceLimit→"文件过大" / MissingPart→"文件不完整"（中文提示直接透出上传端点）。
- **main.py:914 upload 端点重写**：只认 `.pdf` → 白名单 `SUPPORTED_EXTENSIONS` 8 格式；校验→读字节→`ingest_document` 全管线；DocumentParseError/IngestError → code=3 + 中文提示；非白名单扩展名 → code=1 明确提示；标题/来源推导保留（`{ext}_upload:{filename}`）。
- **前端 accept 开放**：UploadPanel.tsx + KnowledgePage.tsx Dragger `accept=".md,.txt,.pdf,.docx,.xlsx,.pptx,.epub,.csv"` + 文案更新（"支持 Markdown / 文本 / PDF / Word / Excel / PPT / EPUB / CSV"）；新增 `ragService.uploadDocumentFile(file, title, source?)`（**FormData 传原始文件字节** → POST /ai/rag/documents/upload；二进制格式不能走旧 JSON 文本通道）。旧 `uploadDocument`（JSON）保留兼容（存量调用方零回归）。
- **通过标准**：多格式冒烟 md/pdf/docx/xlsx 文本非空（§九）✓ / 错误格式明确提示 ✓ / 前端 accept 开放 ✓。

## 三、WP2 五步清洗层（白名单哲学）

- **`rag/retrieval/document_cleaner.py` `clean(markdown, source_format)`**：把 Markdown 先切成 **code / math / table / body 四类区域**（`_tokenize_regions`），规则按区域类型作用：
  - **code（```/~~~ 围栏）**：只去控制符 + 行尾空白（不 NFKC、不剥行首缩进——代码缩进语义关键）。
  - **math（$$ 显示数学 / \begin{env} LaTeX 块）**：同上原样保留。
  - **table（连续 | 行）**：NFKC + 控制符 + 行尾空白；**结构保留、合并单元格不拆**。
  - **body（正文）**：全部规则。
- **五步**：① 格式清理——页眉页脚/页码行（第 N 页 / Page N of M / `--- Page i/N ---`）正则移除、控制字符去除、Unicode NFKC 统一标点；② 冗余过滤——纯符号/噪声短段（`_is_noise`：无 CJK/字母/数字 或 全噪声符号）丢弃，有意义短文本（"你好"）保留；③ 结构恢复 ⭐——**合并 PDF 断行切碎的段落**（`_merge_paragraph_lines`：空行分段，段落内连续行按"前一行连字符→无空格并入 / CJK 相邻→无空格 / 否则单空格"流动拼接；行首块级信号=标题/列表/引用/表格/围栏→不合并）；④ 语义修复——`OCR_TYPO_MAP` 错字表**留空待补**（诚实声明：OCR 组件默认关暂无错字语料，空表零生效）；⑤ 分块准备——`#`(H1)→`##`(section 级) 对齐 chunker 的 MarkdownHeaderTextSplitter、标题/表格前补空行。
- **白名单哲学落地（关键纪律）**：正文内联元素（行内代码 `` `..` `` / URL / 行内数学 `$..$`）用占位符 **`⟦N⟧`（U+27E6/27E7 非控制符）先保护再清洗**——防 NFKC 把代码里全角括号改写、防空格折叠破坏 URL。**实测踩坑修正**：占位符必须用非控制符（初版 `\x00` 会被 `_strip_control` 抹掉）；保护必须先于 NFKC（否则行内代码全角字符仍被改写）。
- **通过标准**：清洗单测含代码块/表格/URL/LaTeX/行内代码不误伤用例 ✓；`chunker.chunk` 输出结构零破坏（test_cleaned_output_chunks_normally 断言 2 父块标题正确）✓。

## 四、WP3 无损归一化

- **`document_cleaner.normalize(text, max_chars=None)`**（嵌入前）：NFKC（全角→半角）/ 去零宽与不可见控制符（Cf/Cc 类）/ 统一空白（块外折叠 2+ 空格 + 去行尾，**保留行首缩进**防坏代码块）/ 表格保持 Markdown 表格（不转纯文本）。
- **超长截断**：chunker 已把父块限制 4000 / 子块 300（嵌入输入有界，防 embedding 截断），`normalize(max_chars)` 为病态超长文档的**兜底**（默认 None 不截，避免丢内容），截断在段落/行边界。
- **只改格式不改语义**（改词/换词/总结不做）；单测断言不改变语义。
- 通过标准：归一化单测 ✓。

## 五、WP4 PDF 内嵌图片三层开关

- **`rag/retrieval/image_pipeline.py`**：`process_pdf_images(md, ocr_enabled=None, caption_enabled=None, pdf_engine=None, page_count=None)`——三层开关路由，**全默认关**（读 settings：`PW_IMAGE_OCR` / `PW_IMAGE_CAPTION` / `PW_PDF_ENGINE`，默认 anydoc）：
  - L1 OCR（图内文字）：PaddleOCR/RapidOCR 未安装 → `_ocr_available()=False` → 占位符替换"图内文字未解析（L1 OCR 组件缺失）"+ 附注（fail-open）。
  - L2 VLM 图片描述（显式占位符替换）：本地 VLM 未接入 → `_vlm_available()=False` → 占位符替换"图片未解析（L2 VLM 模型缺失）"（fail-open）。
  - L3 MinerU 独立通道：`PW_PDF_ENGINE=mineru` 但未安装 → 日志降级回默认解析（fail-open）。
  - **默认（三层全关）**：图片占位符原样保留（**PDF 含图不报错，走文本部分**）；扫描版 PDF（无文本层：有效文本 <50 字且 page_count≥1）→ 如实附"本 PDF 为扫描版（无文本层），图片三层解析默认关闭，图片内容未解析"提示。
- **图片价值过滤**：`image_value_filter(area_ratio, ocr_quality, vlm_score)`——面积占比 + OCR 质量 + VLM 评分，任一维度达标才判"有价值图"（只留流程图/架构图/UML/产品截图/表格截图）；**接口预留**，真实评分需 L1/L2 模型可用后回填（默认全 0 → 判装饰图丢弃，防无模型时把图片当证据——诚实保守）。
- **诚实边界**：三层默认关（重工具不默认启用，只路由复杂文档）；OCR/VLM/MinerU 均未安装三层恒走 fail-open；扫描版无 OCR 如实提示。
- 通过标准：开关逻辑 + 占位符替换单测 ✓（Review 修复轮补齐 tests/core/test_document_image.py 直接单测 18 项——**初版此声明过早**，实际仅 test_document_ingest.py 用 lambda 打桩 process_pdf_images 恒返回 md，见 §十三 修复记录）；默认关 PDF 含图不报错 ✓。

## 六、WP5 原始文件留存

- **原件落盘**：`document_ingest.save_original(data, filename)` → `uploads/{sha256[:16]}_{净文件名}`（`PW_UPLOAD_DIR` 可配，相对 ai_service 运行目录；文件名净化防路径穿越）。落盘失败 → 日志降级继续入库（fail-open，不阻断）。
- **`documents.original_path` 列**：Document ORM 新列 + `src/database.py` `DOCUMENT_PARSING_COLUMNS_DDL`（init_db 幂等 ALTER `ADD COLUMN IF NOT EXISTS` + 索引）+ **`scripts/migrate_module064.py` 本地先决已执行**（4 列 + 2 索引全部就绪，校验输出通过）。
- **add_document 扩展**：新参 `original_path/doc_content_hash/duplicate_cluster_id/is_canonical/doc_embedding`（全默认值，存量调用方零回归）；父块/子块都写 original_path 等四列（文档属性全行可追踪）。
- 通过标准：上传后原件在 + original_path 落库（真实 DB 冒烟 DB 校验 original_path=Y）✓；重灌可基于原件（落盘路径即重灌依赖）✓。

## 七、WP6 文档去重三级

- **L1 内容哈希（doc_content_hash 列）**：`exact_hash(normalized)` 文档级全文本 sha256；`ingest_document` 先查现有文档根父块（parent_id IS NULL）同 hash → **完全相同直接丢弃**（不落原件不入库，返回 `dup_kind="exact"`）。复用 `content_hash` 列思想但粒度=整篇文档（存全部行便于按文档定位），不重载原列语义。
- **L2 文档级 embedding 余弦（bge-m3 绝对余弦口径）**：`document_dedup.find_semantic_duplicate`——新文档全文先 `strip_boilerplate`（页脚/免责声明正则剥离，防套话主导相似度）→ `compute_doc_embedding`（复用 `embedding_service.embed_text` 已 L2 归一化，**async await——真实 DB 冒烟暴露初版返回协程对象落库报错，已修**）→ 对现有"文档根父块且 embedding 非空"比对 cosine≥`doc_dedup_threshold`(0.95) → 命中**不删**，标 `duplicate_cluster_id`（沿用已有簇，无则用根 id）+ `is_canonical=false`，入库但**检索抑制**（`engine._expand_to_parents` 加 `Document.is_canonical.is_(True)` 过滤——存量行默认 TRUE 零回归）。
- **文档级 embedding 存储复用**：存于**文档根父块（parent_id IS NULL 首父块）的既有 embedding 列**——父块不参与向量检索（retriever 只查 `parent_id IS NOT NULL` 子块），复用零新增 Vector 列（诚实声明此语义复用）。
- **L3 SimHash-LSH 接口预留**：`simhash_lsh()` 返回 None + 日志"文档量几千+ 才启用（当前 O(N²) 够用）"——不实现不假装（当前 124 篇量级线性比对足够）。
- **三个坑落地**：① Boilerplate 先剥离（`strip_boilerplate` 正则清单，可关）② 同源内语义去重——`find_semantic_duplicate` 查询不含 `memory:%`（父块 embedding 只在知识库文档写入，天然同源）③ identity 与 content 分离——hash/embedding 基于 normalized 内容，与 title/source（identity）无关，历史版本不折叠（跨 source 不做折叠）。
- **存量边界（如实声明）**：存量 124 篇旧文档根父块 embedding=NULL → 不参与 L2 语义比较（靠 L1 exact/title 兜底）；语义去重对新格式文档生效。
- 通过标准：三级单测（exact 丢弃 / 近似标 cluster+canonical / 语义抑制）✓；124 篇去重冒烟——真实 DB 冒烟 4 篇新文档 L1 未命中（无重复）、L2 对存量 0 命中（存量无 doc embedding）✓ 不破坏现有库 ✓。

## 八、WP7 测试 + 回归

- **新测试 66 项**（全部 mock AnyDoc/embedding/DB，hermetic；Review 修复轮另 +19 项：test_document_image.py 18 + test_document_ingest 1，见 §十三，共 85 项）：
  - `tests/core/test_document_parser.py`（21）：格式识别读字节 / md/txt 解码（UTF-8+GBK 兜底）/ AnyDoc 主解析 mock（pdf+page_count）/ 错误变体映射（Unsupported/Encrypted/Malformed）/ AnyDoc 不可用分层回退（pdf→pymupdf、docx/xlsx 真实解析、pptx 明确报错）/ 上传端点接线（非白名单 code=1、成功调 ingest、解析错误 code=3）。
  - `tests/core/test_document_cleaner.py`（26）：白名单不误伤（代码块/表格/URL/LaTeX/行内代码）/ 页码移除（含 `--- Page i/N ---` PyMuPDF 分页标记）/ 控制符 / NFKC 标点 / 噪声过滤（保留"你好"）/ PDF 断行合并 / 标题不粘连正文 / 列表不合并 / `#`→`##` / 深层标题不动 / 归一化（NFKC+去零宽 / 表格保持 / 代码缩进保留 / 不改语义 / 超长截断 / 不截断）/ chunker 输出结构零破坏。
  - `tests/core/test_document_dedup.py`（15）：exact_hash / boilerplate 剥离（开/关/读配置）/ 余弦 / compute_doc_embedding（成功/fail-open）/ 语义命中（cluster 选择/沿用已有簇）/ 未达阈值 miss / embedding 失败 fail-open / 存量 embedding=NULL 跳过 / **SQL 排除 source='memory:%'（不跨源折叠）** / SimHash 接口预留。
  - `tests/core/test_document_ingest.py`（4）：成功路径（字段透传 + 原件落盘）/ L1 exact 丢弃（不落原件不入库）/ L2 语义标簇 canonical=false / 无有效文本报错。
- **conftest autouse 钉住**：新增 `default_document_pipeline_switches` 钉住 `doc_dedup_semantic_enabled=False`（对齐 056/058/060/061/062 模式，防单测意外触发真实 bge-m3/DB）；图片三层默认已关无需钉住。
- **存量测试零改动**（951 基线全绿验证）；`rag/retrieval/__init__.py` **不修改**（避免 `import *` 污染命名空间，新模块走直接导入路径）。
- **前端回归**：`npm run build`（tsc strict + vite）PASS；vitest **56/56**（module-029 记录的 3 项 ChatPage 环境性失败已在后续模块修复，现全绿）。

## 九、真实 DB 冒烟（2026-08-14）

- **多格式解析冒烟**（`.ua/smoke_formats.py`，真实 AnyDoc）：md→text 引擎、pdf→anydoc（page_count=1）、docx→anydoc（标题+加粗 Markdown）、xlsx→anydoc（GFM 表格）——**四格式解析文本非空 PASS**。
- **真实 DB 全管线 ingestion 冒烟**（`.ua/smoke_ingest_db.py`，真实 PG + bge-m3 + AnyDoc）：md/pdf/docx/xlsx 各一 → `ingest_document` 全管线（解析→图片→清洗→归一化→L1 去重→原件落盘→L2 去重→add_document 分块嵌入落库）：
  - 四篇全部入库 chunks=2、`dup=False`、`original=True`（原件落盘）、pdf `page_count=1`；
  - DB 校验：根父块 `original_path=Y / doc_content_hash=Y / is_canonical=True`；
  - **测试文档已清理**（按 source 前缀删除，不污染现有 124 篇知识库）。
  - 冒烟过程中**真实暴露并修复 2 个 bug**：① `compute_doc_embedding` 未 await（embed_text 是 async，返回协程对象落库报 "expected list or ndarray"）→ 改 async；② 占位符 `\x00` 被控制符过滤抹掉 → 换非控制符 `⟦N⟧`。
- **migrate_module064.py 已执行**：documents 表补 original_path/doc_content_hash/duplicate_cluster_id/is_canonical 四列 + 2 索引（校验输出通过）。

## 十、诚实边界与已知问题

1. **AnyDoc 安装名**：`pip install anydoc` 无此包，真实安装名 `firecrawl-anydoc==0.1.8`（PyPI 可达）；若未来环境无法安装 → 自动降级（PDF→PyMuPDF、docx/xlsx/csv→轻量回退、pptx/epub 明确报错），如实降级不假装支持。
2. **扫描版 PDF 无 OCR**：三层默认关 + OCR 组件未安装，扫描件只提取文本层；无文本层时如实返回"图片未解析"提示（不硬解析）。
3. **OCR/VLM/MinerU 未安装**：L1/L2/L3 全部 fail-open（占位符替换 + 附注），图片价值过滤接口预留（真实评分需模型可用后回填）。
4. **清洗规则是启发式**：PDF 断行合并可能过/欠合并（保守：有块级信号/空行不合并）；水印因语境相关不做自动删（诚实声明）；NFKC 会把正文全角标点转半角（表示层归一，不改语义）。
5. **存量文档语义去重冷启动**：存量 124 篇根父块 embedding=NULL 不参与 L2；新文档入库后成为候选（doc embedding 落根父块）。若要存量全量语义去重需先回填根父块 doc embedding（脚本未做，待按需）。
6. **`#`→`##` 标题规范化**：对上传文档的顶层 H1 提升为 section 级（对齐 chunker）；`####`+ 深层级保留不动（原样不识别，属该 ### 父块内容）。
7. **前端旧 `uploadDocument` JSON 通道保留**：多格式走新 `uploadDocumentFile`（FormData）；旧通道兼容存量调用方。
8. **原件目录**：`uploads/` 已加入 `.gitignore`（`ai_service/uploads/`——原始文件含用户内容，不入库 git，落盘为本地持久化）；冒烟测试的原件已清理。

## 十一、面试口径更新点（四层 ingestion）

> "知识库 ingestion 原来是单格式（PDF）+ 无清洗的：前端只开放 md/txt、后端只认 pdf，Word/Excel/PPT 完全进不来，PDF 里的流程图信息全丢。我按 ADR-0014 补齐**四层 ingestion：解析→清洗→分块→嵌入**——第一，AnyDoc 统一解析层（Firecrawl 开源的 Rust 文档解析引擎，14 种格式统一转 GFM Markdown，格式识别读字节魔数而不是靠扩展名，PDF 保留 PyMuPDF 回退）；第二，五步数据清洗层，核心是**白名单哲学**——规则按块类型作用，代码块、表格、URL、LaTeX 一律不误伤，重点解决 PDF 断行把段落切碎的问题；第三，嵌入前无损归一化，只改格式不改语义（NFKC、去零宽、统一空白）；第四，**三级去重**——内容哈希完全相同直接丢弃、文档级 embedding 余弦 0.95 以上的语义重复不删但标簇抑制检索、SimHash 大规模才上。另外 PDF 内嵌图片做了三层开关（OCR/VLM/MinerU）但**默认全关**，重工具只路由复杂文档，扫描版 PDF 无 OCR 时如实提示而不是假装支持。原始文件落盘 original_path，改分块策略能重灌。"

## 十二、后续 backlog（非本模块范围）

- 存量 124 篇根父块 doc embedding 回填脚本（存量语义去重冷启动）。
- L1 OCR / L2 VLM 模型接入后图片价值过滤真实评分接线。
- AnyDoc 对 epub/pptx 的解析质量抽检（当前走 AnyDoc 原生，未逐格式冒烟）。
- 清洗语义修复错字表 `OCR_TYPO_MAP` 语料积累。

## 十三、Review 修复记录（第 1 轮 conditional，2026-08-14）

Reviewer 判定 conditional，两项意见均已修复：

### 修复 1：入库侧文档向量与查询侧同口径剥离 Boilerplate（document_ingest.py:173）

- **问题**：`ingest_document` 步骤 8 存储的候选侧文档向量直接 `compute_doc_embedding(normalized)` 未剥离套话；而查询侧 `find_semantic_duplicate`（document_dedup.py:127）先 `strip_boilerplate` 再 embed——ADR-0014 决策 6 坑①"Boilerplate 先剥离"只对查询侧生效。候选侧向量被共同页脚/免责声明污染：同套话不同内容的文档可能被误判语义重复（标 `is_canonical=false` → 检索抑制误隐藏），或真实重复因套话差异漏判，且随文档积累逐篇放大。
- **修复**：`document_ingest.py:173` 改为 `compute_doc_embedding(strip_boilerplate(normalized))`，与查询侧完全同口径（读同一 `doc_dedup_boilerplate_enabled` 开关，开/关两侧行为一致）。
- **取舍**：采用 Reviewer 建议的方案 A（入库侧剥离）。方案 B（`find_semantic_duplicate` 返回剥离后向量复用，顺带消除同请求双次 embed 的 MINOR-5）会改动函数返回契约（影响 test_document_dedup 断言）——按"精准修改"原则不做，双次 embed 仅性能 minor 保留为已知问题。
- **测试**：test_document_ingest.py 新增 `test_ingest_doc_embedding_strips_boilerplate`（语义去重开启、normalized 含"第 3 页"套话行 → 断言 `compute_doc_embedding` 收到的文本已剥离套话、正文保留）。

### 修复 2：image_pipeline 直接单测补齐 + changelog §五 声明修正

- **问题**：WP4 `image_pipeline` 零直接单测——AC §4 四项（三层开关默认关 / 图片价值过滤 / 默认关含图不报错 + 扫描版"图片未解析"提示 / §4.4 明文要求的"开关逻辑 + 占位符替换单测"）全未覆盖；现有测试仅 test_document_ingest.py 用 lambda 打桩 `process_pdf_images` 恒返回 md；changelog §五"开关逻辑 + 占位符替换单测 ✓"声明与事实不符（**初版声明过早，如实修正**）。
- **修复**：新增 `tests/core/test_document_image.py` **18 项**全 hermetic（开关显式传参 + 组件可用性 monkeypatch）：
  - `extract_image_refs`：Markdown / 裸 `<img>` / title 语法 / 混合去重 / 无图（5 项）
  - `image_value_filter`：三阈值判定含边界（全 0 拒绝 / 面积 / OCR / VLM / 全低于拒绝）（5 项）
  - 三层默认关：含图 md 原样返回 + 多页不误判 + 无图返回（2 项）
  - L1 OCR 缺失 → 占位符替换 + 附注 fail-open（1 项）
  - L2 VLM 缺失 → 占位符替换 + 附注 fail-open（1 项）
  - L3 MinerU 未装 → 降级回默认解析不改动（1 项）
  - 扫描版（<50 字且 page_count≥1）追加"图片未解析"提示 / 无 page_count 不判 / 有文本层不判（3 项）
- **文档**：changelog §五"通过标准"与 §一"新增测试数"同步修正为事实（85 项 / 1036 全绿）；file-index.md 追加 test_document_image.py 行。

### 自测结果

- 相关测试：`pytest tests/core/test_document_image.py tests/core/test_document_ingest.py tests/core/test_document_dedup.py -q` 全绿。
- 全量 `pytest tests/ -q`：**951 基线 + 85 新增全绿（1036 passed / 0 failed）**（存量测试零改动）。

### 已知问题（修复后仍保留）

- **MINOR-5 同请求双次 embed**：语义去重开启时单次入库仍触发两次 bge-m3 embed（`find_semantic_duplicate` 查询向量 + `compute_doc_embedding` 存储向量，同口径但非复用）。性能 minor，非正确性问题；消除需改 `find_semantic_duplicate` 返回契约（方案 B），按需再做。
- ADR-0014 状态行测试数（66 新增）为本模块交付快照，修复轮新增未回写该行（changelog §一/§十三 为准）。
