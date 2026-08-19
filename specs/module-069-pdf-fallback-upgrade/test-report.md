# Module-069 测试报告 — PDF 回退路径升级（双栏重组 + pymupdf4llm）

> Tester：2026-08-15 | 验收基线：plan.md / acceptance-criteria.md / changelog.md
> Review 结论：Pass（第 1 轮回环，P1 文档同步修复）
> **验收结论：✅ 通过（功能全链路独立复验 + E2E 真实 PDF 验证）**

## 一、全量测试（Tester 独立复跑）

| 项目 | 结果 |
|------|------|
| 全量 pytest（Tester 独立复跑） | **1142 passed / 0 failed（190.51s，43 warnings）** = 1131 基线 + 11 新增 |
| 新增单测 | `tests/core/test_document_parser.py` 11 项（4 个新测试类）全绿 |
| 存量测试改动 | **零改动**（存量 36 项 test_document_parser + 1095 项其他全部保持不变） |
| conftest autouse fixture | `default_pdf_fallback_md_disabled` 钉住 `pdf_fallback_md=False`（对齐 056/058/060 既有模式） |
| warnings | 与基线同源（Redis setex / SAWarning / sklearn，非本模块引入） |

## 二、新增单测覆盖（11 项，Tester 补充）

changelog 声明 15 项已由 Developer 实现（TestReorderColumns 7 + TestPdfFallbackMdSwitch 5 + TestColumnReorderIntegration 3）。Tester 补充 11 项覆盖 changelog 未显式覆盖的 AC 点：

### TestReorderColumnsExtended（4 项，全过）

| 覆盖点 | AC | 结果 | 依据 |
|--------|-----|------|------|
| 重组排序正确性 | 1.1-中线重组 | ✅ | 跨中线→左栏 y 序→右栏 y 序，五行逐序断言 |
| 表格留在原栏 | 1.1-跨栏表格跳过 | ✅ | 含 `|` 块按 x0 归入右栏，不跨栏移动 |
| 单栏+偏右块不误切 | 1.1-单栏不误切 | ✅ | 1 个右栏块（页码）< 2 阈值，走单栏路径 |
| 空白块过滤 | 1.1-双栏检测 | ✅ | block_type=0 但 text 纯空白被过滤 |

### TestPymupdf4llmOutput（2 项，全过）

| 覆盖点 | AC | 结果 | 依据 |
|--------|-----|------|------|
| Markdown 结构输出 | 1.1-pymupdf4llm 输出 | ✅ | pymupdf4llm 路径 engine=pymupdf4llm，文本含内容 |
| 清洗层衔接 | 1.1-清洗层衔接 | ✅ | parser 输出可被 `document_cleaner.clean()` 处理，清洗后非空 |

### TestPwEnvVarSwitch（2 项，全过）

| 覆盖点 | AC | 结果 | 依据 |
|--------|-----|------|------|
| 开关 false → pymupdf | 1.1-开关 false 回退 | ✅ | `settings.pdf_fallback_md=False` → engine="pymupdf" |
| 开关 true → pymupdf4llm | 1.1-pymupdf4llm 输出 | ✅ | `settings.pdf_fallback_md=True` → engine="pymupdf4llm" |

### TestEdgeCases（3 项，全过）

| 覆盖点 | AC | 结果 | 依据 |
|--------|-----|------|------|
| 空内容 PDF | 1.2-空 PDF | ✅ | 零文本层不崩溃，page_count=1，分页标记存在 |
| 扫描版 PDF | 1.2-扫描版 | ✅ | 无文本层返回空文本，不抛异常 |
| 单页 PDF | 1.2-单页 | ✅ | page_count=1，正常处理 |

## 三、E2E 真实 PDF 验证（Tester 独立执行）

### 3.1 rag_survey.pdf（英文双栏 21 页）

**Page 2 双栏检测验证：**

| 指标 | 值 |
|------|-----|
| 页面宽度 | 612.0，中线 306.0 |
| 左栏块数 (x1<=mid) | 4 |
| 右栏块数 (x0>=mid) | 7 |
| 跨中线块数 | 1 |
| 双栏判定 | **True**（左右各 >=2） |

**Page 2 阅读顺序验证：**

| 位置 | Raw y-order | Reordered (_reorder_columns) |
|------|-------------|------------------------------|
| [0] | "2"（页码，右栏 y=26） | "Fig. 1. Technology tree..."（跨中线块，置顶）|
| [1] | "Fig. 1..."（跨中线） | "advanced RAG, and modular RAG..."（左栏 y=440）|
| [2] | "faces and its future..."（右栏 y=440） | "We identify and discuss..."（左栏 y=476）|
| [3] | "advanced RAG..."（左栏 y=440） | "We have summarized..."（左栏 y=547）|

**结论：** Raw y-order 存在左右交错问题（右栏"faces and its future"插在跨中线块和左栏之间）。Reordered 输出正确：跨中线块置顶 → 左栏按 y 排序 → 右栏按 y 排序。**"左栏内容（pos 535）在右栏内容（pos 1976）之前"验证通过。**

**完整解析：**

| 引擎 | 字符数 | engine 字段 |
|------|--------|-------------|
| pymupdf4llm (true) | 113,528 | pymupdf4llm |
| pymupdf (false) | 110,148 | pymupdf |

pymupdf4llm 输出包含 Markdown 标题结构（`#` / `##`），比裸文本结构更丰富。

### 3.2 图检索增强生成研究综述.pdf（中文 12 页）

| 指标 | 值 |
|------|-----|
| 引擎 | pymupdf4llm |
| 页数 | 12 |
| 字符数 | 28,086 |
| 首页内容 | "Artificial Intelligence and Robotics Research 人工智能与机器人研究..." |

中文 PDF 正常解析，引擎字段正确。

### 3.3 开关 false 真实 PDF

| 指标 | 值 |
|------|-----|
| 引擎 | pymupdf |
| 页数 | 21 |
| 字符数 | 110,148 |

开关 false 走旧路径，engine="pymupdf"，行为与现有一致。

## 四、AC 逐条对照

### 1.1 核心路径（9 项）

| AC 项 | 结果 | 依据 |
|-------|------|------|
| WP-A 双栏检测 | ✅ | 单测 test_double_column_detected + E2E page 2 左 4 右 7 跨 1 |
| WP-A 中线重组 | ✅ | 单测 test_reorder_produces_correct_order（五行逐序）+ E2E 左栏在右栏前 |
| WP-A 单栏不误切 | ✅ | 单测 test_single_column_no_reorder + test_single_column_with_marginal_note |
| WP-A 跨中线块置顶 | ✅ | 单测 test_cross_mid_block_on_top + E2E "Fig. 1." 置顶 |
| WP-A 跨栏表格跳过 | ✅ | 单测 test_table_not_reordered + test_table_stays_in_original_column |
| WP-B pymupdf4llm 输出 | ✅ | 单测 test_switch_true_uses_pymupdf4llm + test_pymupdf4llm_output_has_markdown_structure + E2E 含 `#` 标题 |
| WP-B 开关 false 回退 | ✅ | 单测 test_switch_false_uses_get_text + test_env_var_false_forces_pymupdf_engine + E2E engine=pymupdf |
| WP-B pymupdf4llm 不可用降级 | ✅ | 单测 test_pymupdf4llm_not_installed_falls_back（降级 pymupdf + warning） |
| WP-B 清洗层衔接 | ✅ | 单测 test_cleaning_layer_integration（clean() 处理后非空） |

### 1.2 边界条件（5 项）

| AC 项 | 结果 | 依据 |
|-------|------|------|
| 空 PDF | ✅ | 单测 test_empty_pdf_no_crash（零文本层不崩溃） |
| 扫描版 PDF | ✅ | 单测 test_scanned_pdf_empty_text（无文本层返回空） |
| 加密 PDF | ⚠️ 未单独测试 | 现有 test_error_encrypted_mapping 覆盖 AnyDoc 路径；PyMuPDF 回退路径未单独构造加密 PDF |
| 单页 PDF | ✅ | 单测 test_single_page_pdf + test_single_page_cannot_be_double_column |
| 全跨中线页面 | ✅ | 单测 test_all_cross_mid_page（走单栏路径，left/right 为空） |

### 1.3 异常场景（3 项）

| AC 项 | 结果 | 依据 |
|-------|------|------|
| pymupdf4llm 导入失败降级 | ✅ | 单测 test_pymupdf4llm_not_installed_falls_back（reload 模拟） |
| PyMuPDF 不可用抛 DocumentParseError | ✅ | 代码 `raise DocumentParseError("PDF 解析库不可用")` + 现有行为一致 |
| get_text("blocks") 返回空 | ✅ | 单测 test_empty_blocks（空列表返回 ""） |

### 2.2 代码质量（5 项）

| AC 项 | 结果 | 依据 |
|-------|------|------|
| _reorder_columns 纯函数 | ✅ | 输入 page 输出 str，可独立 mock 测试 |
| 存量测试零改动 | ✅ | git diff tests/ 仅 conftest.py 新增 fixture（许可）+ test_document_parser.py 新增测试类（不改存量） |
| 全量 1116+新增全绿 | ✅ | Tester 独立复跑 1142/0 |
| py_compile 变更文件 | ✅ | document_parser.py + config.py 编译通过 |
| 无跨层调用 | ✅ | 仅改 document_parser.py + config.py + requirements.txt + conftest.py + test_document_parser.py |

### 2.3 合规（2 项）

| AC 项 | 结果 | 依据 |
|-------|------|------|
| requirements.txt pymupdf4llm + AGPL 注释 | ✅ | Developer 实现（changelog 声明） |
| changelog AGPL 标注 | ✅ | changelog §七 诚实标注 |

## 五、观察与诚实声明（非阻塞）

1. **加密 PDF 单独测试缺失**：AC 1.2 要求"加密 PDF 错误映射与现有一致"，现有测试覆盖 AnyDoc EncryptedError 路径，但 PyMuPDF 回退路径未单独构造加密 PDF 测试。PyMuPDF 对加密 PDF 会抛异常，走 `DocumentParseError` 兜底——行为与现有一致，但未独立断言。建议 backlog 补充。
2. **pymupdf4llm 输出结构丰富度**：E2E 验证 pymupdf4llm 输出含 `#` Markdown 标题，比裸文本结构更丰富。但"比裸文本结构更丰富"是定性判断，未量化度量（如标题数量/表格数量对比）。AC 1.1 WP-B 措辞为"包含 Markdown 标题/列表/表格结构"，当前验证覆盖标题，列表/表格结构在真实 PDF 中存在但未逐项断言。
3. **pymupdf4llm AGPL 许可**：requirements.txt 已有 AGPL-3.0 注释，changelog 诚实标注。个人学习项目无影响，商业化需换 pypdfium2。
4. **conftest fixture 对齐**：`default_pdf_fallback_md_disabled` 钉住 `pdf_fallback_md=False`，与 056/058/060/061/062/066 模式一致，存量测试零漂移。

## 六、结论

**验收通过。** 关键验证点：

1. 全量 1142/0 全绿（1131 基线 + 11 新增），存量测试零改动；
2. 双栏检测 + 中线重组逻辑：单测覆盖排序正确性、表格原位、单栏不误切、跨中线置顶、空白块过滤、全跨中线——全部通过；
3. pymupdf4llm 开关行为：true→pymupdf4llm / false→pymupdf / 未安装降级——全部通过；
4. E2E 真实双栏 PDF（rag_survey 第 2 页）：双栏检测正确（左 4 右 7 跨 1），重组后左栏内容在右栏内容之前，阅读顺序改善确认；
5. E2E 中文 PDF：pymupdf4llm 正常解析 12 页 28086 字符；
6. 边界条件：空 PDF / 扫描版 / 单页 / 全跨中线——全部不崩溃；
7. 清洗层衔接：parser 输出可被 document_cleaner.clean() 正常处理。

非阻塞观察：加密 PDF 单独测试缺失（现有路径行为一致但未独立断言）；pymupdf4llm 列表/表格结构未逐项量化断言。

**模块状态：✅ 验收通过**
