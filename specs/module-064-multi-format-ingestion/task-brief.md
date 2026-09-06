# Module-064 任务简报：多格式文档解析与数据清洗入库

> 自包含执行简报（ADR-0014 落地）。接手方不需要额外对话上下文，按步骤执行即可。所有"已知事实"均已确认（代码已读），无需重新调研。

## 一、任务背景

**项目**：Agentic RAG 技术文档知识库（`ai_service`，FastAPI + asyncpg + pgvector；执行路径参考 module-058：`.claude/worktrees/m8-knowledge-panel/ai_service`）。

**现状（代码实测，勿改口径）**：
- 前端 `frontend/src/components/UploadPanel.tsx:149`：`accept=".md,.txt"`，文案"支持 .md / .txt"——只开放 md/txt
- 后端 `ai_service/main.py:911 POST /ai/rag/documents/upload`：只认 `.pdf`（扩展名校验），PyMuPDF（fitz）`page.get_text()` 提取 + `--- Page i/N ---` 分隔 → `add_document` 入库
- **前后端割裂**：后端有 PDF 端点前端未接；Word/Excel/PPT/EPUB/CSV 无支持
- 入库链路：解析 → `chunker.chunk`（标题父块 + 300 字子块，chunker.py:160 全局单例）→ embedding → documents 表；**无独立清洗层**
- 测试 824 passed / 0 failed（module-061 验收基线）

**目标**：多格式（md/txt/pdf/doc/docx/xls/xlsx/ppt/pptx/csv/epub）统一上传 → AnyDoc 解析 → 清洗层 → 复用现有分块/向量化入库；PDF 内嵌图片走可选通道；MinerU 独立路由默认关。

## 二、已知事实（勿重新调查）

| # | 事实 |
| - | ----------------------------------------------------------------------------------------------------------------- |
| 1 | AnyDoc：`pip install firecrawl-anydoc`；`anydoc.to_markdown(path)` / `to_markdown_bytes(data, fmt)` / `to_document(data)`（可取内嵌图片资产）；错误变体：Unsupported / Malformed / Encrypted / ResourceLimit / MissingPart / Io（Python 抛 `anydoc.ConvertError` 子类或 OSError） |
| 2 | AnyDoc 速度中位 4.4ms、零系统依赖、Python 释放 GIL（`to_thread` 包装不阻塞事件循环）；**扫描版 PDF 不 OCR**（图片型返回 Unsupported） |
| 3 | 现有 `add_document(title, content, source)`（rag_engine，main.py:907 附近调用）是入库唯一入口——解析/清洗输出喂它即可，下游零改动 |
| 4 | chunker 输入是 Markdown（MarkdownHeaderTextSplitter 按 ##/###）——AnyDoc 的 GFM 输出直接兼容，**清洗层注意保标题层级** |
| 5 | 格式识别：AnyDoc 读字节内容标记不靠扩展名；后端仍保留扩展名白名单（防伪造） |
| 6 | 配置开关模式（对齐既有）：`PW_IMAGE_OCR` / `PW_IMAGE_CAPTION` / `PW_PDF_ENGINE`（anydoc 默认 / mineru），conftest autouse 钉住测试环境关 |
| 7 | 原始文件留存：上传后落盘 `ai_service/uploads/<sha256前16>.<ext>`，documents 表加 `original_path` 列（`ORIGINAL_PATH_DDL` init_db 幂等，对齐 048/058 模式） |

## 三、任务步骤（按序，每步有通过标准）

### WP-A 上传链路扩展（🟢 半天）

- **前端** `UploadPanel.tsx`：`accept=".md,.txt,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.csv,.epub"`；文案更新"支持 Markdown / PDF / Office / CSV / EPUB"
- **后端** `upload_document`（main.py:911）重写：扩展名白名单校验 → 读取 bytes → 按格式路由：
  - `.md/.txt` → 原样（现状）
  - `.pdf/.doc*/.xls*/.ppt*/.csv/.epub` → AnyDoc 解析（见 WP-B）
  - 保留 PyMuPDF 分支作 PDF 回退（AnyDoc 失败时，仅文本型 PDF）
- **通过标准**：前端可传全部白名单格式；后端拒绝白名单外（返回明确 message）；md/txt 路径零回归

### WP-B AnyDoc 接入（🔴 核心，半天）

- 新建 `rag/parsing.py`：`parse_to_markdown(filename, data) -> (markdown, meta)`——格式路由 + `asyncio.to_thread(anydoc.to_markdown_bytes, ...)` + 错误变体映射（Unsupported→"扫描版/不支持的格式"、Encrypted→"文件加密或密码保护"、Malformed→"文件结构损坏"、其余→通用失败，全部返回中文可读提示）
- AnyDoc 失败 → PDF 走 PyMuPDF 回退；Office 失败 → 明确报错不回退（避免假成功）
- **通过标准**：单测覆盖——md/txt 直读 / Office 转 MD / 文本 PDF 转 MD / 图片型 PDF Unsupported 提示 / 加密文件 Encrypted 提示 / 白名单外拒绝（fixture 用最小样例文件：docx 带表格、pptx 带标题、xlsx 单表、csv、epub 可选）

### WP-C 清洗层五步（🔴 核心，1 天）

- 新建 `rag/cleaning.py`：`clean_markdown(md) -> md`，五步（ADR-0014 决策 2）：
  1. **格式清理**：去页眉页脚（可配正则，如页码行）、去控制字符、Unicode NFKC、统一换行
  2. **冗余过滤**：哈希去重（重复段落）+ 语义去重（cosine>0.85，复用 `memory.py` 绝对余弦口径）+ 去无意义短段落（<min_chars 且无标题）
  3. **结构恢复**：合并 PDF 断行（行尾无标点且下行为小写/续接 → 并段）、标题层级规范化（`#` 连续降级收敛）、表格前导/尾随空白清理
  4. **语义修复**：可选开关 `PW_CLEAN_LLM_FIX`（默认关）——LLM 修 OCR 错误成本高，本期不做，留规则兜底（常见错别字表可选）
  5. **分块准备**：输出保证喂 chunker 可用（标题层级合法、无孤孤立行）
- **文档级去重（ADR-0014 决策 6，本 WP 实现）**：L0 内容哈希（documents 表 content_hash 列复用，完全相同跳过）→ L1 结构指纹（标题路径+章节数判近似）→ L2 文档级 embedding 余弦 ≥0.95 判语义近似（124 篇 O(N²) 本地秒级）→ **canonical 保留**（最新 + 结构更完整，可配）+ 其余标 `duplicate_cluster_id` 关联不删除 + 检索抑制；块级重复段降权（清洗步骤 2 覆盖）；**boilerplate 先剥离再判相似**
- **白名单哲学（纪律）**：规则**按块类型作用**——先按 Markdown 块切分（标题/正文/表格/代码块/行内代码），规则只作用对应块；**代码块内任何符号不清、表格结构不拆**
- **通过标准**：单测覆盖五步各规则（断行合并/页码清理/重复段去重/代码块保护/表格保留）+ 文档去重三级（精确跳过/结构近似/canonical 保留/duplicate_cluster_id 关联/检索抑制）；对 058 的 `_GENERATE_PROMPT` 无影响（只动入库链路）

### WP-D 图片通道（🟡 按需，默认关）

- `PW_IMAGE_OCR`（默认 false）：PaddleOCR 或 RapidOCR（选轻量者）对 AnyDoc 无法处理的图片型 PDF / 提取的内嵌图片做 OCR → 文本插回 MD
- `PW_IMAGE_CAPTION`（默认 false）：本地 VLM（Qwen2-VL 或 256M 小模型）生成图片描述 → **显式替换占位符**（`![图](path)` 或 `[图片]` 标记 → `[图片描述：...]`，保证下游确定文本，对齐 Docling 管线做法）
- 图片价值过滤：面积占比（过小丢弃）+ OCR 质量（乱码丢弃）+ VLM 评分（装饰图丢弃）——先实现前两档，VLM 评分留 `PW_IMAGE_FILTER=strict` 可选
- **通过标准**：开关关时零调用零依赖（默认路径无任何新增 import）；开关开时单测覆盖（OCR 文本注入 / 占位符替换 / 面积过滤）
- **注意**：本期默认关——图片是少数文档场景，不拖慢主链路

### WP-E MinerU 独立通道路由（🟢 可选，默认关）

- `PW_PDF_ENGINE=mineru`（默认 `anydoc`）：仅当用户显式开启且本机有 MinerU 时，复杂版面 PDF（扫描件/公式/跨页表格）走 `mineru` CLI/API → Markdown 入库
- 默认不启用（重、慢）；开关开启但 MinerU 不可用 → 明确报错提示安装，不回退假成功
- **通过标准**：默认路径无 MinerU 依赖；开关开启的代码路径存在且错误处理正确（单测 mock）

### WP-F 原始文件留存（🟢 半天）

- 上传后落盘 `ai_service/uploads/`（sha256 前 16 位命名 + 原扩展名）；documents 表加 `original_path` 列（`ORIGINAL_PATH_DDL` init_db 幂等，对齐 048/058）
- `add_document` 签名兼容（新参数默认 None，存量调用零改动）
- **通过标准**：上传 → 落盘成功 → 入库文档可查 original_path → 重放同文件幂等（同名覆盖/去重策略声明）

### WP-G 验收（🔴 收尾）

- 全量 824 基线全绿 + 新增测试（WP-A~F 各对应单测，预计 30-40 项）
- 真实 E2E（uvicorn 8001）：上传一个真实 docx（带表格/标题）+ 一个文本型 PDF → 入库 → 检索命中（Hit 到上传文档内容）
- ADR-0014 状态行更新"✅ 已实施" + 记忆三件套 + CONTEXT.md 只增不删
- 面试口径：解析 AnyDoc 4.4ms / 清洗五步 / 图片三层 / MinerU 路由

## 四、纪律项（违反 = 返工）

1. **下游零改动**：只动解析/清洗层，`chunker` / `add_document` / 检索链路不改（add_document 仅加可选参数）
2. **默认路径零新增依赖**：AnyDoc 是主依赖；PaddleOCR/VLM/MinerU 全部开关默认关，关闭时零 import 零调用（懒加载）
3. **清洗白名单哲学**：规则按块类型作用，代码块/表格/URL/LaTeX 保护，不全文正则一刀切
4. **不假成功**：扫描版 PDF / 加密文件 / 解析失败 → 明确中文提示，绝不留"传了但没内容"的假入库
5. **原始文件必留**：uploads 落盘 + original_path 落库，保证后续重灌可行
6. **conftest 钉住**：新开关 autouse 钉 false（对齐 056/058/060 模式）

## 五、交付物

1. 代码：`rag/parsing.py` + `rag/cleaning.py` + upload_document 重写 + UploadPanel accept + config 新开关 + original_path 迁移
2. 单测：格式路由/AnyDoc 错误映射/清洗五步/图片通道（关）/MinerU 路由（mock）/落盘幂等
3. 真实 E2E 冒烟记录（docx + 文本 PDF 上传 → 入库 → 检索命中）
4. ADR-0014 状态更新 + 记忆三件套 + CONTEXT.md 追加 + 面试口径更新点
