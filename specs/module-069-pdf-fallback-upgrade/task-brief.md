# Module-069 Task Brief：PDF 回退路径升级（双栏重组 + pymupdf4llm）

> 自包含执行简报（01-文档解析与数据清洗.md 2.1.2/2.2.1 决策落地）。接手方不需要额外对话上下文，按步骤执行即可。所有"已知事实"均已确认（代码已读 + 文档实测），无需重新调研。

## 事实（代码实测 + 文档调研，2026-08-17）

1. **`_parse_pdf_pymupdf` 现状**（document_parser.py:151-169）：用 `page.get_text()` 输出裸文本，每页 `--- Page i/N ---` 分隔；**无坐标信息**（get_text() 直接丢弃坐标）、**无结构**（表格/列表糊掉）、**无双栏处理**。
2. **双栏问题实测**（01 深挖文档 2.2.1）：rag_survey（21 页英文双栏论文）第 2 页 Introduction 左右栏交错——右上角 arXiv 版本号被插进正文中间。根因：PDF 不存阅读顺序只存坐标，双栏时按坐标排序必然出错。
3. **pymupdf4llm 决策**（01 深挖文档 2.1.2 B 档）：PyMuPDF 官方 MD 生成器（内部用 dict 模式字号/加粗 + 版面规则推断标题层级），一行出 MD——替代当前 `page.get_text()` 裸文本输出。依赖：独立包 `pymupdf4llm`（非 PyMuPDF 内置），AGPL-3.0 许可。实测 55.5ms vs get_text 4.6ms（~12 倍）——回退路径不在乎。
4. **WP-A 必须在 WP-B 前**：双栏重组必须在坐标阶段做（`get_text("blocks")` 返回块坐标），pymupdf4llm 出 MD 后坐标已丢——所以先做坐标级重组，再换 pymupdf4llm 输出。
5. **测试基线**：全量 1116/0（module-068 验收口径）；scripts/test_models.py 1 项 module-050 遗留收集 ERROR 未触碰。
6. **测试 PDF 文件**：`docs/项目深挖/原PDF-rag_survey.pdf`（21 页英文双栏，1.66MB，第 2 页双栏交错验证点）+ `docs/项目深挖/原PDF-图检索增强生成研究综述.pdf`（12 页中文，3.1MB）—— Tester E2E 必须用这两个文件。
7. **requirements.txt** 为准（== 锁定，无 pyproject/uv.lock）；当前无 pymupdf4llm 条目。
8. **清洗层衔接**：pymupdf4llm 输出的 MD **仍要过 document_cleaner.clean()**——它解决结构，清洗层解决格式噪声（NFKC/断行合并/页眉清理），两层互补。

## WP-A：双栏中线重组（坐标阶段，核心）

- `_parse_pdf_pymupdf` 改 `page.get_text()` → `page.get_text("blocks")`（每块 = (x0, y0, x1, y1, text, ...)，坐标信息保留）
- **双栏检测**：统计页面 `x0 >= 页面宽/2` 的块数（右栏）+ `x1 <= 页面宽/2` 的块数（左栏）——**左右各 ≥2 块才算双栏**（单栏走正常 y 序防误切）
- **中线重组**：跨中线块（横跨左右的大标题/宽表格）→ 置顶；左栏按 y0 排序；右栏按 y0 排序；文本拼接 = 跨中线块 + 左栏 + 右栏
- **跨栏表格跳过**：`|` 行不参与重组（表格内列顺序不能乱）
- **实现位置**：`document_parser.py::_parse_pdf_pymupdf` 内部，新增 `_reorder_columns(page)` 纯函数（可测试）
- **通过标准**：单测（双栏检测/跨中线块/单栏不误切/跨栏表格跳过）+ rag_survey 第 2 页真实 PDF E2E 不再左右交错

## WP-B：pymupdf4llm 升级（裸文本 → Markdown）

- `requirements.txt` 补 `pymupdf4llm`（不加版本锁——AGPL 许可注释）
- `_parse_pdf_pymupdf` 输出改为 `pymupdf4llm.to_markdown(page)` 替代 `page.get_text()`——出 Markdown（标题/列表/表格恢复）
- **WP-A 重组前置**：双栏检测 → 中线重组 → pymupdf4llm 输出（重组在坐标阶段做，pymupdf4llm 最后出 MD）
- **开关 `PW_PDF_FALLBACK_MD`**（config.py，默认 true）：false 时走旧路径 get_text()（保存量行为零回归，复用 Agent 的 config fixture 钉开关）
- **pymupdf4llm 输出仍过清洗层**（document_cleaner.clean()）——它解决结构，清洗层解决格式噪声（NFKC/断行合并/页眉清理），两层互补
- **通过标准**：单测（开关行为/pymupdf4llm 输出格式/清洗层衔接）+ E2E（rag_survey + 中文综述真实 PDF 解析）

## WP-C：测试 + 文档收口

- 全量 1116 基线 + 新增单测全绿（存量测试零改动红线；conftest autouse fixture 若需钉开关对齐 056/058/066/068 模式）
- changelog（项目模板，参考 specs/module-066-agent-evaluation/changelog.md）+ CONTEXT.md（只增不删，先备份）+ 三记忆文件
- **AGPL 许可声明**：requirements.txt 行注释 + changelog 诚实标注（个人学习项目无影响，商业化时换 pypdfium2 Apache-2.0 替代）
- 01-深挖文档 2.1.2 / 2.2.1 里"已决策"但未落地 → 改为"已实现"

## 纪律项

1. 只动 `document_parser.py::_parse_pdf_pymupdf` + `config.py` + `requirements.txt` + 相关单测——**document_cleaner.py / document_ingest.py / document_dedup.py / image_pipeline.py 一律不碰**
2. pymupdf4llm 输出格式（Markdown）必须走清洗层——不跳过不绕过
3. 编码调 ponytail skill（最简可行：`_reorder_columns` 一个纯函数 + pymupdf4llm 一行替换，不重写解析管线）
4. 存量测试零改动（改了=FAIL；conftest autouse fixture 钉开关是唯一例外）
5. 文档"已决策"→"已实现"只改措辞，不新增内容
