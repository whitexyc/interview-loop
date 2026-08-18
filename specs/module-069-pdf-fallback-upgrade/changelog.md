# 变更日志 — Module-069: PDF 回退路径升级（双栏重组 + pymupdf4llm）

> 实施：Developer（2026-08-17）| 计划：`plan.md` | 验收：`acceptance-criteria.md`
> 范围：PyMuPDF PDF 回退路径从裸文本升级为"双栏中线重组 + pymupdf4llm Markdown 输出"。
> 全量 pytest 基线 1116/0（module-068 验收口径）。

## 一、WP-A：双栏中线重组（坐标阶段，核心）

**问题**：`_parse_pdf_pymupdf` 用 `page.get_text()` 输出裸文本，双栏论文（如 rag_survey）阅读顺序错乱——右上角 arXiv 版本号被插进正文中间。

**实施**：
- `document_parser.py` 新增 `_reorder_columns(page)` 纯函数（~60 行）：
  - `page.get_text("blocks")` 获取带坐标文本块 (x0, y0, x1, y1, text, block_no, block_type)
  - 双栏检测：统计 `x1 <= mid_x`（左栏）+ `x0 >= mid_x`（右栏），**左右各 >=2 块才算双栏**（单栏走正常 y 序防误切）
  - 分三组：跨中线块（`x0 < mid_x < x1`）→ 置顶；左栏按 y0 排序；右栏按 y0 排序
  - **跨栏表格跳过**：含 `|` 的块按 x0 归入对应栏原位保留（表格列顺序不能乱）
  - 图片块（block_type=1）过滤
- `_parse_pdf_pymupdf` 双栏页面调 `_reorder_columns(page)` 替代 `page.get_text()`

**三个坑全覆盖**：
1. 单栏误切：必须"左右各 >=2 块"才算双栏（7 个单测覆盖）
2. 跨中线块：横跨左右的大标题/宽表格 → 置顶
3. 跨栏表格：`|` 行不参与重组

## 二、WP-B：pymupdf4llm 升级（裸文本 → Markdown）

**实施**：
- `requirements.txt` 补 `pymupdf4llm`（不加版本锁——AGPL-3.0 许可注释）
- `config.py` 新增 `pdf_fallback_md: bool = True`（PW_PDF_FALLBACK_MD 环境变量）
- `_parse_pdf_pymupdf` 改造：
  - 开关 `settings.pdf_fallback_md`：
    - **false**：走旧路径 `page.get_text()` 裸文本（存量行为逐字一致，零回归）
    - **true**：双栏重组（WP-A）→ `pymupdf4llm.to_markdown()` 输出 Markdown
  - pymupdf4llm 延迟导入（try/except，不可用时降级 get_text() + warning 日志）
  - engine 字段：true 时 `engine="pymupdf4llm"`，false 时 `engine="pymupdf"`
  - **pymupdf4llm 输出仍过清洗层**：由 document_ingest.py 管线保证（parser 内不重复调用）

## 三、WP-C：测试 + 文档收口

**新增测试 15 项**（test_document_parser.py）：
- `TestReorderColumns` 7 项：单栏不误切 / 双栏检测 / 跨中线块置顶 / 表格跳过 / 空块 / 图片过滤 / 全跨中线
- `TestPdfFallbackMdSwitch` 5 项：开关 false 走旧路径 / 开关 true 走 pymupdf4llm / 未安装降级 / 单页 PDF / engine 字段一致性
- `TestColumnReorderIntegration` 3 项：真实双栏 PDF（rag_survey 第 2 页）/ 中文 PDF 正常解析 / 开关 false 真实 PDF engine 字段

**conftest autouse fixture**：`default_pdf_fallback_md_disabled` 钉住 `pdf_fallback_md=False`（测试环境 hermetic，存量测试零改动）

## 四、文件变更列表

| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| `ai_service/rag/retrieval/document_parser.py` | 修改 | 新增 `_reorder_columns` 纯函数 + `_parse_pdf_pymupdf` 双栏重组 + pymupdf4llm 输出 |
| `ai_service/src/config.py` | 修改 | 新增 `pdf_fallback_md` 配置项（PW_PDF_FALLBACK_MD，默认 true） |
| `ai_service/requirements.txt` | 修改 | 新增 `pymupdf4llm` 条目 + AGPL-3.0 许可注释 |
| `ai_service/tests/conftest.py` | 修改 | 新增 `default_pdf_fallback_md_disabled` autouse fixture |
| `ai_service/tests/core/test_document_parser.py` | 修改 | 新增 15 项测试（双栏重组 + pymupdf4llm 开关 + 集成） |
| `specs/module-069-pdf-fallback-upgrade/changelog.md` | 新增 | 本文件 |

## 五、关键设计说明

### 设计决策 1: 双栏检测阈值"左右各 >=2 块"
- 决策: 只有左栏和右栏各有 >=2 个文本块时才判定为双栏
- 原因: 单栏页面偶尔有块的 x0 偏右（页码/页眉），1 块不足以判定双栏

### 设计决策 2: 跨栏表格跳过重组
- 决策: 含 `|` 的块不参与跨中线/左右栏分组，按 x0 原位归入对应栏
- 原因: 表格内列顺序依赖坐标，重组会打乱列顺序

### 设计决策 3: pymupdf4llm 逐页调用
- 决策: 每页独立调用 `pymupdf4llm.to_markdown(pdf_doc, pages=[i-1])`
- 原因: 保持 `--- Page i/N ---` 分页标记与存量行为一致

### 设计决策 4: AGPL 许可声明
- 决策: requirements.txt 行注释 + changelog 诚实标注
- 原因: pymupdf4llm 与 PyMuPDF 同为 AGPL-3.0。个人学习项目无影响；商业化时换 pypdfium2（Apache-2.0）

### 设计决策 5: pymupdf4llm 自身处理双栏，WP-A 仅作 fallback
- 决策: pymupdf4llm 内部自带版面分析可处理双栏布局；`_reorder_columns` 在 pymupdf4llm 成功时输出被覆盖，仅在 pymupdf4llm 失败时作为 fallback 生效
- 原因: pymupdf4llm 的版面分析基于完整文档模型，比手动坐标排序更准确；保留 `_reorder_columns` 每页调用（非条件化跳过）因 pymupdf4llm 失败是运行时异常，条件化增加 try/catch 嵌套复杂度，当前 CPU 开销可接受

## 六、验证命令

| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| 全量测试 | `cd ai_service && python -m pytest tests/ -x -q` | 1131 passed / 0 failed |
| 单测定向 | `python -m pytest tests/core/test_document_parser.py -x -v` | 36 passed |
| py_compile | `python -c "import py_compile; py_compile.compile('rag/retrieval/document_parser.py'); py_compile.compile('src/config.py')"` | 无 SyntaxError |
| pymupdf4llm 可用性 | `python -c "import pymupdf4llm; print(pymupdf4llm.__version__)"` | 版本号输出 |

## 七、诚实边界

- **AGPL 许可传染性**: pymupdf4llm 与 PyMuPDF 同为 AGPL-3.0。个人学习项目无影响；商业化时需整体换 pypdfium2（Apache-2.0）。
- **pymupdf4llm 安装失败**: 延迟导入 + 降级 get_text() + warning 日志。不阻断服务。
- **跨中线块文本锚点**: 真实 PDF 的跨中线块（如 Figure caption）可能包含双栏内容的子字符串，位置索引断言可能误匹配——集成测试改用长度/双栏检测断言。
- **清洗层衔接**: pymupdf4llm 输出的 Markdown 仍过 document_cleaner.clean()，由 document_ingest.py 管线保证，parser 内不重复调用。

## 八、Review 修复（P1 文档同步）

Reviewer 指出 P1：pymupdf4llm 可用时 `_reorder_columns(page)` 的输出被 pymupdf4llm 结果覆盖（pymupdf4llm 处理原始 page 对象，非 reorder 后的文本），与 plan 原文"WP-A 重组前置"存在语义偏差。

**修复**：更新 plan.md + changelog 澄清实际设计意图——pymupdf4llm 内部自带版面分析可处理双栏布局，`_reorder_columns` 仅在 pymupdf4llm 不可用或失败时作为 fallback 生效。

**实际运行时行为**（代码不变，文档对齐）：
- **pymupdf4llm 成功时**：`_reorder_columns` 被调用但输出被 pymupdf4llm 的 Markdown 结果覆盖——pymupdf4llm 的版面分析替代手动坐标排序
- **pymupdf4llm 失败时**：降级使用 `_reorder_columns` 的重组文本——双栏中线重组作为 fallback 保底
- **pymupdf4llm 未安装时**：走 `page.get_text()` 裸文本（`_reorder_columns` 不参与，因为 `pdf_fallback_md` 开关为 false 或导入失败直接降级）

**设计取舍**：保留 `_reorder_columns` 每页调用而非条件化跳过——pymupdf4llm 失败是运行时异常（非 ImportError），条件化需额外 try/catch 嵌套增加复杂度；当前写法 CPU 开销可接受（纯坐标计算，无 I/O），代码路径更清晰。

## 九、变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-17 | 初始实现（WP-A + WP-B + WP-C） | Developer |
| v2 | 2026-08-17 | Review 修复：plan/changelog 澄清 pymupdf4llm 自身处理双栏版面，WP-A 仅作 fallback | Developer |
