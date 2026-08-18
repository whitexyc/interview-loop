# 开发计划 — Module-069: PDF 回退路径升级（双栏重组 + pymupdf4llm）

## Agent 配置

- Developer x1（后端 Python，改动集中在 document_parser.py + config.py + requirements.txt + 单测）
- Reviewer x1
- Tester x1

## 1. 需求描述

- 需求来源: 01-文档解析与数据清洗.md 2.1.2 / 2.2.1 决策落地（ADR-0014 回退路径升级）
- 功能描述: PyMuPDF PDF 回退路径从裸文本升级为"双栏中线重组 + pymupdf4llm Markdown 输出"，解决双栏论文阅读顺序错乱问题并恢复标题/列表/表格结构
- 优先级: P1

## 2. 模块拆分

### WP-A: 双栏中线重组（坐标阶段，核心）

**描述**: `_parse_pdf_pymupdf` 内部从 `page.get_text()` 改为 `page.get_text("blocks")` 获取带坐标的文本块，检测双栏页面并按中线重组阅读顺序。

**预估代码量**: 功能代码 ~80 行（`_reorder_columns` 纯函数 ~50 行 + `_parse_pdf_pymupdf` 调用改造 ~30 行）

**涉及文件**:
- `ai_service/rag/retrieval/document_parser.py` — `_reorder_columns(page)` 新增纯函数 + `_parse_pdf_pymupdf` 调用改造

**依赖**: 无（WP-A 是起点）

**实现要点**:

1. **新增 `_reorder_columns(page) -> str` 纯函数**（可独立测试）:
   - `blocks = page.get_text("blocks")` — 每块 = (x0, y0, x1, y1, text, block_no, block_type)
   - `mid_x = page.rect.width / 2` — 中线
   - 双栏检测: 统计 `x0 >= mid_x` 的块数（右栏）+ `x1 <= mid_x` 的块数（左栏），**左右各 >=2 块才算双栏**（单栏走正常 y 序防误切）
   - 分三组: 跨中线块（`x0 < mid_x < x1`）→ 置顶; 左栏（`x1 <= mid_x`）按 y0 排序; 右栏（`x0 >= mid_x`）按 y0 排序
   - **跨栏表格跳过**: 含 `|` 的块不参与重组（表格内列顺序不能乱），原位保留在 left/right 中
   - 拼接: 跨中线块 + 左栏 + 右栏，块间 `\n` 连接
   - 单栏页面: 直接按 y0 排序返回（零重组，零回归）

2. **`_parse_pdf_pymupdf` 调用改造**:
   - 双栏页面: 调 `_reorder_columns(page)` 替代 `page.get_text()`
   - 单栏页面: 仍走 `page.get_text()` （保持存量行为零回归）
   - 分页标记 `--- Page i/N ---` 保持不变

**三个坑（必须覆盖的测试场景）**:
1. 单栏误切 — 必须"左右各 >=2 块"才算双栏，单栏走正常 y 序
2. 跨中线块 — 横跨左右的大标题/宽表格 → 置顶
3. 跨栏表格 — `|` 行不参与重组（表格内列顺序不能乱）

### WP-B: pymupdf4llm 升级（裸文本 → Markdown）

**描述**: 引入 pymupdf4llm 包，将 PDF 回退路径输出从裸文本升级为 Markdown（标题/列表/表格恢复），并提供开关回退。

**预估代码量**: 功能代码 ~30 行（config 1 行 + document_parser 调用 ~15 行 + requirements 1 行注释）

**涉及文件**:
- `ai_service/rag/retrieval/document_parser.py` — `_parse_pdf_pymupdf` 输出改造
- `ai_service/src/config.py` — 新增 `pdf_fallback_md` 配置项
- `ai_service/requirements.txt` — 新增 `pymupdf4llm` 条目 + AGPL 许可注释

**依赖**: WP-A（pymupdf4llm 内部自带版面分析可处理双栏；`_reorder_columns` 仅在 pymupdf4llm 不可用或失败时作为 fallback 生效——详见 changelog 设计决策 5）

**实现要点**:

1. **requirements.txt** 补 `pymupdf4llm`（不加版本锁 — AGPL 许可注释说明）

2. **config.py** 新增:
   ```python
   # PDF 回退路径 Markdown 升级（module-069）：
   #   true（默认）—— PyMuPDF 回退路径用 pymupdf4llm.to_markdown() 输出
   #     Markdown（标题/列表/表格恢复），pymupdf4llm 内部处理双栏版面；
   #   false —— 走旧路径 page.get_text() 裸文本（存量行为零回归，逃生口）。
   #   pymupdf4llm 仍 AGPL-3.0（与 PyMuPDF 同许可），输出仍过清洗层
   #   （document_cleaner.clean()）——pymupdf4llm 解决结构，清洗层解决格式噪声。
   pdf_fallback_md: bool = True
   ```

3. **document_parser.py `_parse_pdf_pymupdf` 改造**:
   - 开关 `settings.pdf_fallback_md`:
     - **false**: 走旧路径 `page.get_text()` 裸文本（存量行为逐字一致，零回归）
     - **true**: `pymupdf4llm.to_markdown()` 替代 `page.get_text()`（pymupdf4llm 内部自带版面分析，可处理双栏布局）
   - pymupdf4llm 导入延迟（try/except，不可用时降级 get_text() + warning）
   - **WP-A 作为 fallback**: `_reorder_columns` 在 pymupdf4llm 路径中每页调用一次；pymupdf4llm 成功时使用其自身版面分析结果（更优），pymupdf4llm 失败时降级使用 `_reorder_columns` 重组文本
   - **pymupdf4llm 输出仍过清洗层**: 由 document_ingest.py 管线保证（document_parser → document_cleaner.clean()），不在 parser 内重复调用
   - engine 字段: 开关 true 时 engine="pymupdf4llm"，false 时 engine="pymupdf"（与现有一致）

### WP-C: 测试 + 文档收口

**描述**: 单测覆盖 + changelog + 记忆文件更新 + AGPL 许可声明。

**预估代码量**: 测试 ~120 行

**涉及文件**:
- `ai_service/tests/core/test_document_parser.py` — 新增双栏重组 + pymupdf4llm 开关测试
- `ai_service/tests/conftest.py` — autouse fixture 钉住 `pdf_fallback_md=False`（测试环境 hermetic）
- `specs/module-069-pdf-fallback-upgrade/changelog.md`
- `memory/project-context.md`、`memory/file-index.md`、`memory/agent-activity-log.md`

**依赖**: WP-A + WP-B

## 3. 技术方案

- 涉及数据表: 无（不新增表，不改 schema）
- API 端点: 无（改解析层内部实现，upload 端点零改动）
- 外部依赖: `pymupdf4llm`（新增，AGPL-3.0）
- 环境变量: `PW_PDF_FALLBACK_MD`（默认 true，false 回退旧 get_text()）
- 测试 PDF 文件: `docs/项目深挖/原PDF-rag_survey.pdf`（英文双栏 21 页）+ `docs/项目深挖/原PDF-图检索增强生成研究综述.pdf`（中文 12 页）— **位于主 checkout，worktree 内需复制或引用主 checkout 路径**

## 4. 验收标准

见同目录下的 `acceptance-criteria.md`

## 5. 风险评估

- **AGPL 许可传染性**: pymupdf4llm 与 PyMuPDF 同为 AGPL-3.0。个人学习项目无影响；商业化时需整体换 pypdfium2（Apache-2.0）。requirements.txt 行注释 + changelog 诚实标注。
- **pymupdf4llm 安装失败**: 延迟导入 + 降级 get_text() + warning 日志。不阻断服务。
- **双栏误切**: "左右各 >=2 块"阈值防误切。单栏文档走正常 y 序零重组。
- **跨栏表格**: `|` 行跳过重组。表格内列顺序不乱。
- **存量测试零改动纪律**: conftest autouse fixture 钉住 `pdf_fallback_md=False`，存量 `_parse_pdf_pymupdf` 测试零改动（开关 false 逐字走旧路径）。
- **WP-A/pymupdf4llm 交互**: pymupdf4llm 内部自带版面分析可处理双栏，`_reorder_columns` 仅在 pymupdf4llm 不可用或失败时作为 fallback 生效（pymupdf4llm 成功时 `_reorder_columns` 虽被调用但输出被 pymupdf4llm 结果覆盖）。

## 6. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-17 | 初始版本 | Planner |
