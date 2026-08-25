# 变更日志 — Module-076: 递归爬取 + 链接跟踪 + 深度控制 + 去重 URL 池

## 变更概述

将 module-075 的单页爬取升级为**受控递归爬取**：从种子 URL 出发，提取页面内 `<a href>` 链接 → 递归跟踪（深度限制 + URL 规范化去重 + 白/黑名单过滤）→ 总页数上限防爆。新增配置项 3 个、数据库列 1 个、测试文件 1 个，生产代码新增 ~195 行。

## 文件变更列表

| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| `ai_service/rag/crawl/crawler.py` | 修改（+~195 行） | 新增 `_normalize_url`(L79)、`_extract_links`(L100)、`_is_blacklisted_url`(L142)、`_crawl_filename`(L129)、`_blacklist_patterns`(L136)、`_crawl_page_and_store`(L247)、`_recursive_crawl`(L294)；改造 `run_crawl`(L333) 为递归入口；扩展 `_load_sources_from_db`(L405) 读取 max_depth |
| `ai_service/src/config.py` | 修改 | 新增 3 配置项：`crawl_max_depth=2` / `crawl_blacklist_patterns=""` / `crawl_max_links_per_page=20`（L349-351） |
| `ai_service/src/database.py` | 修改 | 新增 `CRAWL_DEPTH_DDL`(L325) + `ensure_max_depth_column`(L331) + init_db 挂接(L271) |
| `ai_service/main.py` | 修改 | POST/GET `/ai/crawl/sources` 端点支持 `max_depth` 字段（0-5，默认 1；L1056-1067） |
| `ai_service/tests/crawl/test_recursive_crawl.py` | 新增 | 递归爬取单元测试（与原有 test_crawler.py 合计 63 项） |

## 关键设计说明

### 设计决策 1: 递归架构
- 决策: `run_crawl` → `_recursive_crawl(url, depth, max_depth, visited, summary)` → `_crawl_page_and_store`（fetch→review→ingest→提取子链接）→ 对子链接递归；`visited: set[str]` 全树共享去重防环
- 原因: 深度优先遍历 + 内存级去重池，单次 run_crawl 生命周期内有效，循环 A→B→A 自断

### 设计决策 2: 双重深度约束
- 决策: `effective_depth = min(source.max_depth, settings.crawl_max_depth=2)`；source.max_depth 默认 1（种子+一层）
- 原因: 单源可配（0=仅种子页等价 module-075 单页，1=种子+一层默认），全局上限防用户误配过深

### 设计决策 3: URL 规范化
- 决策: `_normalize_url` 去 fragment / scheme+host 小写 / 去尾斜杠（`urllib.parse.urlparse` 纯函数）
- 原因: 规范化后判重，同一 URL 不同写法（如 `HTTPS://Example.COM/path/#frag`）统一为一条

### 设计决策 4: 链接提取
- 决策: `_extract_links` 标准库 `re` 正则提取 href + `urljoin` 绝对化 + 仅 http/https + `max_links_per_page=20` 截断
- 原因: 零新依赖，不引 BeautifulSoup；无 DOM/XML 解析器天然防 XXE；截断防导航页/页脚爆量

### 设计决策 5: 白名单 / 黑名单
- 决策: 白名单 `_matches_any` 在主链路生效（种子与递归链接都校验，递归边界 = 本源 `url_pattern` 前缀）；黑名单 `_is_blacklisted_url` 域名级前缀匹配（config `PW_CRAWL_BLACKLIST_PATTERNS` 逗号分隔）
- 原因: 落实 module-075 遗留「黑名单未接线」+ `_matches_any` 不再为死代码

### 设计决策 6: max_depth 演进
- 决策: max_depth 直接加在 source_configs 表（DDL 幂等 ALTER），不新建独立 ORM 文件
- 原因: 轻量内聚，init_db 可重复执行，存量行自动取 DEFAULT 1

### 设计决策 7: 设计取舍
- 决策: robots.txt 遵循留 module-077（反爬代理）；动态渲染不做（静态 HTML 单机）
- 原因: 模块边界清晰，如实声明

## 验证命令

| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| 模块单测全绿 | `cd ai_service && .venv\Scripts\python.exe -m pytest tests/crawl -q` | 63 passed, 2 warnings in 30.58s |
| import 冒烟 | `cd ai_service && .venv\Scripts\python.exe -c "import main; print('IMPORT_OK')"` | IMPORT_OK |
| 语法验证 | `ast.parse` 四文件 | SYNTAX_OK |
| 生产行数 | AST 精确计数 | ~195 行 ≤ 200（铁律 2） |
| 最大方法行 | 逐方法统计 | ~45 行 ≤ 50（铁律 3） |

## 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-26 | 递归爬取核心实现 + 深度控制 + URL 去重 + 黑白名单接线 | Developer |
