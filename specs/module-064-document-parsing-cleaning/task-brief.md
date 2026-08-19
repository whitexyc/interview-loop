# Module-064 任务简报：多格式文档解析 + 数据清洗 + 去重（ADR-0014 实施）

> 自包含执行简报。接手方不需要额外对话上下文，按步骤执行即可。所有"已知事实"均已确认（代码已读），无需重新调研。
> 决策依据 `specs/adr/0014-document-parsing-cleaning.md`（选型对比/五步清洗/三层图片/去重三级，全在该文档）。全量基线 **951 passed**（module-063 后）。

## 一、任务背景（代码实测，ADR-0014 §背景）

- **前端** `frontend/src/components/UploadPanel.tsx:149`：`accept=".md,.txt"`——只开放 md/txt
- **后端** `ai_service/main.py:911 POST /ai/rag/documents/upload`：只认 `.pdf`（`file.filename.endswith(".pdf")`），PyMuPDF（fitz）提取，每页加分隔后 `add_document` 入库
- **前后端割裂**：后端有 PDF 端点但前端未接；Word/Excel/PPT/EPUB/CSV 完全无支持
- 入库链路：解析 → `chunker.chunk`（标题父块+300字子块）→ embedding → documents 表；**无独立数据清洗层**
- PDF 内嵌图片（流程图/截图）当前信息完全丢失

**目标（ADR-0014 六项决策落地）**：① AnyDoc 统一解析层（多格式转 Markdown）② 五步数据清洗层（chunk 前）③ 嵌入前无损归一化 ④ PDF 内嵌图片三层方案（默认关+分层路由）⑤ 原始文件留存 original_path ⑥ 文档去重三级处理。

## 二、决策依据速览（详见 ADR-0014）

| 决策 | 方案 | 关键点 |
|---|---|---|
| 1 解析层 | **AnyDoc**（Firecrawl 开源，Rust，14 格式统一 GFM Markdown，中位 4.4ms，质量 81 分全格式第一，零系统依赖无模型）；PyMuPDF 保留 PDF 回退 | 格式识别读字节不靠扩展名；Python 绑定释放 GIL；错误变体（Unsupported/Malformed/Encrypted）可映射用户提示；扫描版 PDF 不 OCR（诚实边界） |
| 2 清洗层 | 五步：①格式清理 ②冗余过滤 ③结构恢复（⭐合并 PDF 断行切碎的段落）④语义修复（可选）⑤分块准备 | **白名单哲学**：规则按块类型作用（正文/表格/代码块/行内代码），不能全文正则一刀切 |
| 3 归一化 | 无损：NFKC、去零宽/控制符、统一空白；表格保持 MD；超长截断 | 改词/换词/总结不做（伤语义） |
| 4 PDF 图片 | L1 PaddleOCR/RapidOCR（图内文字）L2 本地轻量 VLM（图片描述插回 MD）L3 MinerU 独立通道（复杂版面）——**三层全默认关**，`PW_IMAGE_OCR`/`PW_IMAGE_CAPTION`/`PW_PDF_ENGINE=mineru` | 图片价值过滤（面积占比+OCR 质量+VLM 评分）防装饰图污染 |
| 5 原始留存 | 上传原始文件落盘，documents 存 `original_path` | 改分块策略/重灌必须有原件 |
| 6 去重 | 三级：①内容哈希（sha256，复用 content_hash 列）②结构指纹/SimHash（大规模才上）③文档级 embedding 余弦≥0.95 | canonical 选择（留最新/结构完整/权威）；不删光标 `duplicate_cluster_id`，检索抑制；粒度两级（文档级先/块级后） |

## 三、任务步骤（WP 按序，通过标准每 WP 末尾）

### WP1 AnyDoc 解析层集成（核心）

- **安装 AnyDoc**：`pip install anydoc` 或 firecrawl/anydoc CLI（ADR 说零系统依赖无模型；安装失败如实记录，评估是否退而求其次）
- **新 `ai_service/rag/retrieval/document_parser.py`（或 rag/ 下合适位置）**：统一解析入口——输入文件字节 + 原始文件名 → 输出 Markdown 文本。格式识别读字节内容标记（非扩展名）；错误变体映射用户提示（Unsupported/Malformed/Encrypted）
- **PDF 回退**：AnyDoc 失败/扫描版 → 现有 PyMuPDF 路径保留（`main.py:911` 现有逻辑提取为可复用函数）
- **`main.py:911 POST /ai/rag/documents/upload`**：接入统一解析层，多格式（md/txt/pdf/docx/xlsx/pptx/epub/csv）不再只认 pdf；解析后走清洗层 → chunker → embedding
- **`frontend UploadPanel.tsx:149`**：`accept` 开放多格式（`.md,.txt,.pdf,.docx,.xlsx,.pptx,.epub,.csv`）+ 文案更新
- **通过标准**：多格式上传冒烟（至少 md/pdf/docx/xlsx 各一）→ 解析文本非空入库；错误格式返回明确提示；前端 accept 开放

### WP2 数据清洗层（五步，chunk 前）

- **新 `ai_service/rag/retrieval/document_cleaner.py`**：`clean(markdown_text, format) -> cleaned_md`，五步：
  ① 格式清理：去页眉页脚/页码/水印/乱码/控制字符，Unicode NFKC 统一标点
  ② 冗余过滤：无意义短段落过滤（可配置长度下限）
  ③ 结构恢复：⭐ 合并 PDF 断行切碎的段落、还原标题层级、表格结构化
  ④ 语义修复（可选，规则级先做：OCR 常见错字表留空待补）
  ⑤ 分块准备：标题层级规范化对齐 `MarkdownHeaderTextSplitter`
- **白名单哲学（关键纪律）**：清洗规则**按块类型作用**（正文/表格/代码块/行内代码分开），代码块符号不清、表格合并单元格不拆、URL/LaTeX 不动
- **通过标准**：清洗函数单测（含代码块/表格/URL 不被误伤的用例）；`chunker.chunk` 输出结构零破坏

### WP3 嵌入前归一化（无损）

- 嵌入前统一：NFKC、去零宽/不可见控制符、统一空白、UTF-8；超长截断（防 embedding 截断）；**表格保持 Markdown 表格**（不转纯文本）
- **通过标准**：归一化函数单测；不改变语义（改词/换词/总结不做）

### WP4 PDF 内嵌图片（三层，全默认关 + 分层路由）

- 实现三层开关与路由框架：`PW_IMAGE_OCR`（L1 图内文字）、`PW_IMAGE_CAPTION`（L2 本地 VLM 描述插回 MD，显式占位符替换）、`PW_PDF_ENGINE=mineru`（L3 独立通道）
- 图片价值过滤（面积占比 + OCR 质量 + VLM 评分）——只留流程图/架构图/产品截图/UML/表格截图
- **诚实边界**：三层默认关（重工具不默认启用）；扫描版 PDF 无 OCR 时如实返回"图片未解析"提示；L2/L3 模型下载依赖环境，缺失时降级关（fail-open）
- **通过标准**：开关逻辑 + 占位符替换单测；默认关时 PDF 含图不报错（走文本部分）

### WP5 原始文件留存

- 上传解析后**原始文件落盘**（`ai_service/uploads/` 或配置目录），documents 表加 `original_path` 列（init_db 幂等 ALTER + migrate_module064.py 本地先决）
- **通过标准**：上传后原始文件在 + original_path 落库；重灌（reindex）能基于原件

### WP6 文档去重三级

- **内容哈希**（sha256，复用 `documents.content_hash`）：完全相同 → 直接丢弃（第一层）
- **文档级 embedding 余弦**（bge-m3 + 绝对余弦口径，复用 module-035/记忆去重同款）：≥0.95 语义重复 → **不删**，标 `duplicate_cluster_id` + canonical 选择（留最新/结构完整/权威），检索时抑制重复（查询只出 canonical）
- 结构指纹/SimHash-LSH：**文档量几千+ 才上**（当前 124 篇 O(N²) 够用，实现接口预留/标注待规模）
- **三个坑**：Boilerplate 先剥离（共同页脚/免责声明主导相似度前先扒）；embedding 去重不跨源折叠（同源内语义去重）；identity 与 content 分离（版本化兼容，别把历史版本当重复）
- **通过标准**：三级去重单测（完全相同丢弃/近似标 cluster+canonical 选择/语义重复抑制）；现有 124 篇文档去重冒烟（报告命中量，不破坏现有库）

### WP7 测试 + 文档 + 记忆

- `tests/test_document_parser.py` + `tests/test_document_cleaner.py` + `tests/test_document_dedup.py`（新，mock AnyDoc/模型）
- conftest 相关开关钉住（对齐既有模式）；全量 pytest **951 基线 + 新增** 全绿（存量零改动）
- 文档：changelog/review-report/test-report + **ADR-0014 状态行 ✅** + memory 三件套 + CONTEXT 只增
- **通过标准**：全量 951+N 全绿；记忆硬性约束满足

## 四、纪律项（违反 = 返工）

1. **白名单哲学**：清洗按块类型作用，代码块/表格/URL/LaTeX 不被误伤（WP2 核心）
2. **无损归一化**：嵌入前只改格式不改语义；改词/换词/总结不做
3. **分层解析**：重工具（MinerU/VLM/OCR）默认关、只路由复杂文档；不默认启用
4. **存量零回归**：现有 md/txt/pdf 入库行为兼容（PyMuPDF 回退保留）；存量测试零改动（除非验收许可）
5. **原始留存**：上传原件必须落盘（重灌依赖）
6. **诚实**：AnyDoc 安装失败/模型缺失/扫描版无 OCR 如实记录降级；图片价值过滤如实标注
7. **复用**：content_hash 列、bge-m3 绝对余弦、migrate 先例、conftest 开关模式全部复用现有

## 五、交付物

1. WP1-6 代码 + 单测（解析/清洗/归一化/图片开关/原件留存/去重）
2. 多格式上传冒烟记录（md/pdf/docx/xlsx）
3. changelog.md（WP 逐项 + 测试数 951+N + 诚实边界）
4. ADR-0014 状态行 ✅ + memory 三件套 + CONTEXT 只增
5. 面试口径更新点（解析→清洗→分块→嵌入四层 ingestion）
