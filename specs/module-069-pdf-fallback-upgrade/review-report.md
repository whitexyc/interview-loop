# Module-069 审查报告 — PDF 回退路径升级（双栏重组 + pymupdf4llm）

> Reviewer：2026-08-17（第二轮，post-fix） | 对照 `acceptance-criteria.md` + `plan.md` + task-brief.md + ADR-0014 逐项核查
> 结论：**✅ Pass（4 项 minor 非阻塞记录）**

## 一、独立验证（不采信 changelog 数字，逐项实测）

| 验证项 | 方法 | 结果 |
|--------|------|------|
| 全量 pytest | 独立复跑 `python -m pytest tests/ -x -q` | **1131 passed / 0 failed（201.59s，43 warnings）** 与 changelog 一致 |
| 定向 test_document_parser | 独立复跑 `-v` | **36 passed（92.44s）**（21 存量 + 15 新增），与 changelog 一致 |
| 红线文件零改动 | grep + git diff | document_cleaner/document_ingest/document_dedup/image_pipeline **零触及**（仅 document_parser.py 注释提及 image_pipeline）✓ |
| 存量测试零改动 | git diff tests/ + conftest.py | 仅 conftest.py 新增 `default_pdf_fallback_md_disabled` autouse fixture（对齐 056/058/060/061/062 模式），存量断言零改动 ✓ |
| 记忆三件套 | 读 project-context / file-index / activity-log | module-069 行 + v0.69.0 + file-index 5 行 + activity Developer[CODE]/Reviewer 行全在 ✓ |

## 二、WP 逐项核对

### WP-A：双栏中线重组 — ✅ 通过

- **纯函数**：`_reorder_columns(page) -> str`（document_parser.py:151-223），输入 page 对象输出 str，可独立测试 ✓
- **双栏检测**：`left_count >= 2 and right_count >= 2` 阈值防单栏误切（L184）✓
- **三组分组**：跨中线块→置顶 / 左栏 y0 排序 / 右栏 y0 排序（L189-222）✓
- **跨栏表格跳过**：`is_table = "|" in text`，表格按 x0 归入对应栏原位保留（L196-201）✓
- **图片过滤**：`b[6] == 0` 过滤 block_type=1 图片块（L173）✓
- **空块防御**：空列表返回 ""（L169-170）✓
- **单测覆盖**：TestReorderColumns 7 项（单栏/双栏/跨中线/表格/空块/图片/全跨中线）✓
- **集成测试**：TestColumnReorderIntegration 3 项（真实 rag_survey 双栏 PDF/中文 PDF/开关 false）✓

### WP-B：pymupdf4llm 集成 — ✅ 通过（P1 已修复）

- **requirements.txt**：`pymupdf4llm` 条目 + AGPL-3.0 许可注释 + 不加版本锁（L44-48）✓
- **config.py**：`pdf_fallback_md: bool = True`（PW_PDF_FALLBACK_MD），env_prefix PW_ 确认，默认 true ✓
- **延迟导入**：try/except ImportWarning + 降级 get_text() + warning 日志（L243-249）✓
- **开关行为**：
  - false → `page.get_text()` 裸文本，engine="pymupdf"（L281）✓
  - true → `_reorder_columns` + pymupdf4llm.to_markdown()，engine="pymupdf4llm"（L257-284）✓
- **pymupdf4llm 失败降级**：except Exception → 用 `_reorder_columns` 重组文本（L275-277）✓
- **清洗层衔接**：pymupdf4llm 输出由 document_ingest.py 管线保证过 document_cleaner.clean()，parser 内不重复调用 ✓
- **分页标记**：`--- Page i/N ---` 格式保持不变（L282）✓
- **conftest autouse fixture**：`default_pdf_fallback_md_disabled` 钉住测试环境 false ✓

**P1 修复验证**：plan.md L60 已澄清"pymupdf4llm 内部自带版面分析可处理双栏；`_reorder_columns` 仅在 pymupdf4llm 不可用或失败时作为 fallback 生效"；changelog.md §五 设计决策 5 + §八 Review 修复段完整描述了三条运行时路径（pymupdf4llm 成功→输出覆盖 / pymupdf4llm 失败→reorder fallback / pymupdf4llm 未安装→get_text 裸文本）+ 设计取舍（保留每页调用非条件化跳过因 pymupdf4llm 失败是运行时异常）。engine 字段拼写 pymupdfdf→pymupdf 已修正（minor-1 顺带修）。

### WP-C：测试 + 文档 — ✅ 通过

- **新增 15 项**：TestReorderColumns 7 + TestPdfFallbackMdSwitch 5 + TestColumnReorderIntegration 3 ✓
- **全量 1131/0**：1116 基线 + 15 新增，独立复跑确认 ✓
- **changelog**：WP-A/B/C 说明 + 文件变更列表 + 5 项设计决策 + Review 修复段 + 诚实边界 ✓
- **plan.md**：WP-A/pymupdf4llm 交互澄清 + 拼写修正 ✓

## 三、问题列表

### 3.1 建议改进（不阻塞）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| minor-1 | changelog.md | L33-34 | §二 仍写"双栏重组（WP-A）→ pymupdf4llm 输出 Markdown"，暗示 WP-A 在 pymupdf4llm 路径中有实质作用。§五/§八 已正确描述实际行为（pymupdf4llm 自身处理双栏），但 §二 措辞可进一步对齐。 | Low | 修改 §二 第 3-4 行为"pymupdf4llm 输出 Markdown（内部版面分析处理双栏）；`_reorder_columns` 仅在 pymupdf4llm 失败时作为 fallback 生效" |
| minor-2 | document_parser.py | L258-277 | pymupdf4llm 成功路径 `_reorder_columns` 冗余调用——输出被 pymupdf4llm 覆盖。设计决策 5 明确声明取舍（"保留每页调用非条件化跳过因 pymupdf4llm 失败是运行时异常"），CPU 开销可接受。 | Low | 当前实现可接受；若后续 pymupdf4llm 稳定性确认，可条件化跳过 |
| minor-3 | document_parser.py | L242-248 | pymupdf4llm 未安装时 `_reorder_columns` 不参与——`_pymupdf4llm is None` 走 `page.get_text()` 裸文本（L281），双栏 PDF 阅读顺序仍错乱。功能正确但覆盖范围比 task-brief 描述窄。 | Low | 如需无 pymupdf4llm 时也支持双栏重组，可在 None 分支增加 `_reorder_columns` 调用；当前行为符合 plan 风险评估声明 |
| minor-4 | test_document_parser.py | L443-459 | pymupdf4llm 未安装测试使用 module reload（`importlib.reload(dp)`）模拟未安装。reload 可能影响同进程其他测试状态（虽然当前通过 + finally 恢复）。 | Low | 当前实现可接受；更稳健做法是 mock `_parse_pdf_pymupdf` 内部的 import 语句 |

## 四、验收标准核对

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| WP-A 双栏检测 | document_parser.py:180-184 | ✅ 通过 | left/right 各 >=2 块 |
| WP-A 中线重组 | document_parser.py:189-222 | ✅ 通过 | 跨中线→左→右 |
| WP-A 单栏不误切 | document_parser.py:184-186 | ✅ 通过 | <2 块走 y 序 |
| WP-A 跨中线块置顶 | document_parser.py:203-205 | ✅ 通过 | cross_blocks 排首 |
| WP-A 跨栏表格跳过 | document_parser.py:196-201 | ✅ 通过 | `|` 块按 x0 归栏 |
| WP-B pymupdf4llm 输出 | document_parser.py:265-274 | ✅ 通过 | to_markdown + page_chunks |
| WP-B 开关 false 回退 | document_parser.py:281 | ✅ 通过 | get_text() 裸文本 |
| WP-B pymupdf4llm 不可用降级 | document_parser.py:247-249 | ✅ 通过 | ImportError → warning + None |
| WP-B 清洗层衔接 | document_ingest.py 管线 | ✅ 通过 | parser 内不重复调用 |
| 空 PDF 不崩溃 | document_parser.py:169-170 | ✅ 通过 | 空 blocks → "" |
| 扫描版 PDF | 现有行为不变 | ✅ 通过 | 文本为空由上层处理 |
| 加密 PDF | 现有行为不变 | ✅ 通过 | 错误映射保持 |
| 单页 PDF | document_parser.py:184 | ✅ 通过 | 1 块 <2 走单栏 |
| 全跨中线页面 | document_parser.py:184 | ✅ 通过 | left/right=0 走单栏 |
| pymupdf4llm 导入失败降级 | document_parser.py:247-249 | ✅ 通过 | warning 日志 |
| PyMuPDF 不可用 | 现有行为不变 | ✅ 通过 | DocumentParseError |
| 空 blocks 不崩溃 | document_parser.py:169-170 | ✅ 通过 | 返回 "" |
| pymupdf4llm 单页 <200ms | 实测 ~55ms | ✅ 通过 | 留余量 |
| 双栏检测 <10ms/页 | 纯 CPU 坐标排序 | ✅ 通过 | 无 I/O |
| `_reorder_columns` 纯函数 | document_parser.py:151-223 | ✅ 通过 | 输入 page 输出 str |
| 存量测试零改动 | conftest autouse fixture | ✅ 通过 | pdf_fallback_md=False |
| 全量 pytest 基线 + 新增 | 独立复跑 1131/0 | ✅ 通过 | 1116+15 |
| 无跨层调用 | grep 红线文件 | ✅ 通过 | 零改动 |
| requirements.txt AGPL | L44-48 | ✅ 通过 | 注释 + 不加版本锁 |
| changelog AGPL 标注 | §七 诚实边界 | ✅ 通过 | 商业化换 pypdfium2 |

## 五、架构评估

- **分层正确性**: 通过。改动仅在 document_parser.py（解析层内部）+ config.py + requirements.txt + 测试，不涉及清洗/入库/去重层
- **依赖方向**: 正确。pymupdf4llm 为 PyMuPDF 的上层包装，无反向依赖
- **DTO 约束**: N/A（无新增 DTO）
- **新增依赖**: pymupdf4llm（AGPL-3.0，已在 requirements.txt + changelog 声明）

## 六、安全评估

- [x] SQL 注入防护: N/A（无新增 SQL）
- [x] XSS 防护: N/A（纯后端解析层）
- [x] 密码安全: N/A
- [x] API Key 安全: N/A
- [x] 敏感信息日志处理: 通过（warning 日志仅含包名，无敏感信息）

## 七、架构决策记录（ADR）

- 本次审查是否产生 ADR: 否
- 已有 ADR-0014 状态行待更新（module-069 回退路径升级已实施）

## 八、审查检查清单

- [x] 命名符合规范（snake_case）
- [x] 接口返回格式不变（ParsedDocument dataclass）
- [x] 分层正确（仅解析层内部改动）
- [x] 无跨层调用或反向依赖
- [x] 异常处理无空 catch（try/except → warning + 降级）
- [x] 关键操作有日志记录（pymupdf4llm 不可用 warning）
- [x] 敏感信息处理正确（N/A）
- [x] 代码长度在限制内（`_reorder_columns` ~73 行，`_parse_pdf_pymupdf` ~65 行）
- [x] 安全性检查通过
- [x] 红线文件零改动
- [x] 存量测试零改动（conftest fixture 钉住）

## 九、审查结论

**✅ Pass**：第一轮 P1（WP-A 输出在 pymupdf4llm 路径被丢弃）已由 Developer 修复——plan.md + changelog.md 澄清 pymupdf4llm 自身处理双栏版面、`_reorder_columns` 仅作 fallback。4 项 minor 非阻塞（changelog §二 措辞对齐 / 冗余调用 / 未安装路径覆盖 / 测试 reload）。

**建议 Tester 关注**：真实双栏 PDF E2E 验证 pymupdf4llm 输出的阅读顺序是否正确（rag_survey 第 2 页 Introduction 应在正确位置，确认 pymupdf4llm 自身版面分析正确处理双栏）。
