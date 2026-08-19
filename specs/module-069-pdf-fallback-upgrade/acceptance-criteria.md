# 验收标准 — Module-069: PDF 回退路径升级（双栏重组 + pymupdf4llm）

## 1. 功能验收

### 1.1 核心路径验收

- [ ] **WP-A 双栏检测**: `_reorder_columns(page)` 对双栏页面（左右各 >=2 块）正确检测为双栏
- [ ] **WP-A 中线重组**: 双栏页面输出顺序为 跨中线块 → 左栏 y 序 → 右栏 y 序（rag_survey 第 2 页不再左右交错）
- [ ] **WP-A 单栏不误切**: 单栏页面走正常 y 序，不触发重组（左右块数不满足 >=2 阈值）
- [ ] **WP-A 跨中线块置顶**: 横跨中线的大标题/宽表格排在最前
- [ ] **WP-A 跨栏表格跳过**: 含 `|` 的块不参与重组，原位保留
- [ ] **WP-B pymupdf4llm 输出**: 开关 true 时输出包含 Markdown 标题/列表/表格结构（比裸文本 `get_text()` 结构更丰富）
- [ ] **WP-B 开关 false 回退**: `PW_PDF_FALLBACK_MD=false` 时走旧路径 `page.get_text()` 裸文本，行为逐字一致
- [ ] **WP-B pymupdf4llm 不可用降级**: pymupdf4llm 未安装时降级 `get_text()` + warning 日志，不抛异常
- [ ] **WP-B 清洗层衔接**: pymupdf4llm 输出的 Markdown 经 `document_cleaner.clean()` 清洗（由 document_ingest.py 管线保证）

### 1.2 边界条件验收

- [ ] 空 PDF（零页）不抛未处理异常
- [ ] 扫描版 PDF（无文本层）与现有一致（如实提示"图片未解析"）
- [ ] 加密 PDF 错误映射与现有一致
- [ ] 单页 PDF 正常处理（单页不可能双栏）
- [ ] 全跨中线页面（所有块横跨中线）正常处理（left/right 为空，只输出跨中线块）

### 1.3 异常场景验收

- [ ] pymupdf4llm 导入失败时降级 get_text() + 日志 warning
- [ ] PyMuPDF 本身不可用时抛 `DocumentParseError`（与现有一致）
- [ ] 页面 get_text("blocks") 返回空列表时不崩溃

## 2. 非功能验收

### 2.1 性能验收

- [ ] pymupdf4llm 单页解析耗时 < 200ms（实测基线 ~55ms，留余量）
- [ ] 双栏检测 + 重组额外开销 < 10ms/页（纯 CPU 坐标排序）

### 2.2 代码质量验收

- [ ] `_reorder_columns` 为纯函数（输入 page 对象，输出 str），可独立测试
- [ ] 存量测试零改动（conftest autouse fixture 钉住 `pdf_fallback_md=False`）
- [ ] 全量 pytest 基线 1116 + 新增全绿（零回归）
- [ ] `py_compile` 变更文件 OK
- [ ] 无跨层调用（document_cleaner.py / document_ingest.py / document_dedup.py / image_pipeline.py 零改动）

### 2.3 合规验收

- [ ] requirements.txt 有 pymupdf4llm 条目 + AGPL-3.0 许可注释
- [ ] changelog 诚实标注 AGPL 许可 + 商业化时换 pypdfium2 Apache-2.0 替代方案

## 3. 可运行验证命令

| 验收项 | 验证命令 | 预期输出 |
|--------|----------|----------|
| 全量测试 | `cd ai_service && python -m pytest tests/ -x -q` | 1116+N passed / 0 failed |
| 单测定向 | `python -m pytest tests/core/test_document_parser.py -x -v` | 双栏重组 + pymupdf4llm 开关测试全绿 |
| py_compile | `python -c "import py_compile; py_compile.compile('rag/retrieval/document_parser.py'); py_compile.compile('src/config.py')"` | 无 SyntaxError |
| pymupdf4llm 可用性 | `python -c "import pymupdf4llm; print(pymupdf4llm.__version__)"` | 版本号输出 |
| 真实 PDF E2E | `python -c "from rag.retrieval.document_parser import parse_document; data=open('docs/项目深挖/原PDF-rag_survey.pdf','rb').read(); r=parse_document(data,'rag_survey.pdf'); print(r.engine, len(r.text))"` | engine=pymupdf4llm, text 非空 |

## 4. 验收结论

- 审查人: <Reviewer 签名>
- 测试人: <Tester 签名>
- 验收时间: YYYY-MM-DD
- 结论: [ ] 通过 / [ ] 不通过
- 备注: <说明>
