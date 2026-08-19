# Module-064 审查报告（第 2 轮）— 多格式文档解析 + 数据清洗 + 去重

> Reviewer | 2026-08-14 | 第 2 轮复审：核查上轮 2 项 major 修复 + 复查 acceptance-criteria.md
> 独立验证：全量 pytest 复跑 **1036 passed / 0 failed（169.97s）**，与 changelog 一致（951 基线 + 85 新增，逐文件核对 21+26+15+5+18=85）
> 上轮基线：1017 passed（951+66）→ 修复轮 +19（test_document_image 18 + test_document_ingest 1）→ 1036，计数自洽
> 存量测试零改动：`git diff main -- ai_service/tests/` 仅 conftest.py 追加 1 个 autouse fixture，无存量测试改动

## 一、verdict：pass（2 项 major 已全部修复，无新引入 major）

| # | 上轮 major | 修复状态 | 核实 |
|---|-----------|---------|------|
| MAJOR-1 | L2 语义去重 Boilerplate 剥离不对称（document_ingest.py:173 vs document_dedup.py:127） | ✅ 已修复 | 入库侧改为 `compute_doc_embedding(strip_boilerplate(normalized))`，与查询侧 find_semantic_duplicate 内部 `compute_doc_embedding(strip_boilerplate(doc_text))` 完全同口径，两侧读同一 `doc_dedup_boilerplate_enabled` 开关；新测试 `test_ingest_doc_embedding_strips_boilerplate` 锁定（断言 compute_doc_embedding 收到已剥离套话的文本） |
| MAJOR-2 | WP4 image_pipeline 零直接单测 + changelog §五"单测 ✓"声明不实 | ✅ 已修复 | 新增 `tests/core/test_document_image.py` **18 项**（extract_image_refs 5 + image_value_filter 5 + 三层默认关 2 + L1 fail-open 1 + L2 fail-open 1 + L3 MinerU 降级 1 + 扫描版 3），AC §4 四项全覆盖，断言与实现逐字核对一致；changelog §一/§五/§十三 已如实修正（85 项 / 1036 全绿） |

## 二、修复核验细节

### MAJOR-1 修复：document_ingest.py:176-178
- 现状：`doc_embedding = await document_dedup.compute_doc_embedding(document_dedup.strip_boilerplate(normalized))` —— 与 `find_semantic_duplicate`（document_dedup.py:127 `compute_doc_embedding(strip_boilerplate(doc_text))`）同输入（normalized）、同剥离函数、同开关。开/关 `doc_dedup_boilerplate_enabled` 两侧行为一致（False 时 strip_boilerplate 直接返回原文）。
- 取舍：采用 Reviewer 建议方案 A（入库侧剥离），方案 B（find_semantic_duplicate 返回剥离后向量复用，消除 MINOR-5 双次 embed）改动函数返回契约影响存量测试断言，按"精准修改"原则不做——MINOR-5 保留为已声明的性能 minor，可接受。
- 测试：`test_ingest_doc_embedding_strips_boilerplate`（doc_dedup_semantic_enabled=True，normalized 含"第 3 页"套话行 → 断言 compute_doc_embedding 实参已剥离套话、正文保留）。**注意**：该测试未 mock `strip_boilerplate`，走真实剥离逻辑，有效锁定修复。

### MAJOR-2 修复：tests/core/test_document_image.py（18 项）
- 断言与 image_pipeline.py 实现逐条核对：
  - `test_l1_ocr_missing_fail_open`：断言"图内文字未解析"+"图内文字未提取：L1 OCR 组件未安装"——实现 `_replace_with_placeholder(md, refs, "图内文字未解析（L1 OCR 组件缺失...）")` + `_append_note(..., "图内文字未提取：L1 OCR 组件未安装...")` ✓
  - `test_l2_caption_missing_fail_open`：断言"图片未解析（L2 VLM 模型缺失"+"图片描述未生成：L2 VLM 模型缺失" ✓
  - `test_l3_mineru_missing_falls_back`：engine=mineru + _mineru_available False → 日志降级走默认路径 → 长文本非扫描版 → 原样返回 ✓
  - `test_scan_only_append_unparsed_note`：md="![图](img/x.png)"（16 字 <50）+ page_count=3 → 追加"扫描版...图片内容未解析"提示，原占位符保留 ✓
  - `image_value_filter` 三阈值边界（area 0.05 / ocr 0.3 / vlm 0.3）✓
- 诚实声明修正：changelog §五"通过标准"与 §一"新增测试数"已从"初版过早声明"如实改为 85 项 / 1036 全绿，并在 §十三 修复记录中注明初版声明不当。

## 三、新引入问题检查（无 major，2 项 minor）

1. **非 canonical 文档可作后续去重参考（新发现，minor）**：`find_semantic_duplicate`（document_dedup.py:131-141）候选查询仅过滤 parent_id IS NULL / embedding 非空 / source≠memory:%，**未过滤 is_canonical.is_(True)**；而 `document_ingest.py` 步骤 8 对语义重复文档（is_canonical=False）**仍会**计算并存储 doc_embedding。→ 非 canonical 副本成为后续上传的语义比对参考：若未来文档与副本余弦≥0.95 但与 canonical 原件不足阈值，会被过度折叠进簇（检索抑制误隐藏其独有信息）。余弦不传递，风险真实但低（0.95 高阈值）。建议二选一：候选查询加 `Document.is_canonical.is_(True)`，或步骤 8 对非 canonical 文档不存 doc_embedding。非阻塞。
2. **测试数口径漂移持续（上轮 minor-1 未清，minor）**：CONTEXT.md 与 project-context ADR 索引行仍写"951 基线 + **64** 新增"、ADR-0014 状态行写"66 新增"、实际已 **85**（1036/0）。changelog §十三 注明"修复轮新增未回写该行"。文档数字滞后于实现，建议统一为 85。非阻塞。

## 四、八维逐条核查（第 2 轮重点复核）

### 1. 方法学
- 修复轮与 plan/AC 一致：MAJOR-1 采用建议方案 A 并说明取舍，MAJOR-2 补齐 AC §4.4 明文单测要求，未改动现有实现契约（存量测试零改动）。

### 2. 正确性
- MAJOR-1 修复后入库侧/查询侧 embedding 口径统一，ADR-0014 决策 6 坑①"Boilerplate 先剥离"双侧生效；其余（magic 识别/五步清洗白名单/无损归一化/去重三级/canonical 检索抑制）第 1 轮已核正确，未随修复轮变动。

### 3. 降级链
- 修复轮未触碰降级逻辑；MAJOR-1 修复路径本身 fail-open（compute_doc_embedding 异常返回 None → 不阻断入库）；image_pipeline 三层 fail-open 语义由新测试锁定（L1/L2 组件缺失占位符替换+附注、L3 MinerU 未装降级、扫描版如实提示）。

### 4. 诚实性
- 修复轮对"初版单测声明过早"如实修正（changelog §五 + §十三），MINOR-5 双次 embed 保留并声明为非正确性性能 minor，ADR 状态行/验收节数字滞后如实标注（changelog §十三"已知问题"节）。声明与实现一致（除上轮 minor-1 数字滞后，见 §三.2）。

### 5. 测试
- 修复轮新增 19 项（test_document_image 18 + test_document_ingest 1），全 hermetic（开关显式传参 + 组件可用性 monkeypatch）；conftest autouse 钉住 doc_dedup_semantic_enabled=False 保 hermetic；全量 1036/0 独立复现，逐文件核对 85 项。

### 6. 结果解读
- changelog §十三 自测结果（相关测试全绿 + 全量 1036/0）与独立复跑一致；无过度外推。

### 7. 风格与最小改动
- 修复改动最小化：仅 document_ingest.py 步骤 8 一行口径调整 + 新增测试文件 + 文档/记忆修正；`rag/retrieval/__init__.py` 仍不修改；`find_semantic_duplicate` 返回契约未动（对应取舍声明）。

### 8. 记忆核查
- 修复轮新增 test_document_image.py 已入 file-index（模块 064 条目 13 行）；changelog §十三 注明修复记录；其余（project-context module-064 行 + 头部日期 8-14 / activity Developer + Reviewer 行 / ADR-0014 ✅ / CONTEXT 只增零删）第 1 轮已核在，未因修复轮破坏。

## 五、验收标准逐条对照（ac_check，第 2 轮）

| AC | 第 1 轮 | 第 2 轮 | 依据 |
|----|--------|--------|------|
| §1 解析层 | 通过 | 通过 | 未变（21 测试 + 冒烟） |
| §2 清洗五步+白名单+单测/chunker 零破坏 | 通过 | 通过 | 未变（26 测试） |
| §3 无损归一化+单测+不改语义 | 通过 | 通过 | 未变 |
| §4 图片三层默认关/价值过滤/含图不报错/开关+占位符单测 | **不通过**（零直接测试） | **通过** | test_document_image.py 18 项全命中（MAJOR-2 修复） |
| §5 原件留存 original_path + migrate | 通过 | 通过 | 未变 |
| §6 去重三级/canonical 抑制/Boilerplate/同源内/单测/冒烟/SimHash 预留 | 部分通过（Boilerplate 不对称） | **通过** | document_ingest.py:176 同口径剥离（MAJOR-1 修复）+ 新测试锁定；**新 minor**：非 canonical 作参考（§三.1） |
| §7 测试/AC 收口/ADR ✅/面试口径/文档 | 通过 | 通过 | 85 测试、ADR-0014 ✅、changelog 声明已如实 |
| §8 降级验收 | 通过 | 通过 | 未变；全量 1036/0 独立复现 |
| §9 文档验收（记忆三件套/CONTEXT 只增/changelog 注明已读） | 通过 | 通过 | 全在（§四.8） |

## 六、结论

第 2 轮复审：上轮 2 项 major 全部修复且经独立验证——
- **MAJOR-1**（Boilerplate 剥离不对称）：入库侧与查询侧完全同口径，测试锁定，AC §6.4 生效。
- **MAJOR-2**（image_pipeline 零单测）：18 项直接单测补齐，AC §4 四项全覆盖，changelog 声明已如实修正。
- 全量 pytest **1036 passed / 0 failed（169.97s）**独立复现，与 changelog 逐字一致（951+85，逐文件核对）；存量测试零改动。

无新引入 major。2 项 minor 非阻塞（新发现：非 canonical 文档可作语义去重参考，建议候选查询加 is_canonical 过滤或非 canonical 不存 doc_embedding；上轮 minor-1 文档数字滞后 64/66→实际 85，建议统一）。**verdict = pass**，可进 Tester。
