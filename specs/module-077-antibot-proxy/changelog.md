# 变更日志 — Module-077: 反爬绕过 + 代理池

## 变更概述
在现有 httpx fetch 链路上增强反爬能力：robots.txt 遵循（标准库 RobotFileParser + 按域名 TTL 缓存 + fail-open）+ UA 轮换（内置 ~10 个浏览器 UA 池 + 请求头增强）+ 限速与重试退避（per-source 请求间隔 1s + 429/5xx 指数退避+jitter 最多 3 次）+ 代理配置化轮换 + 失败切换（round-robin HTTP 代理，空列表直连）。仅使用标准库 + 已有 httpx，零新依赖。

## 文件变更列表
| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| ai_service/src/config.py | 修改 | 新增 6 项反爬配置（delay/retry_max/retry_base/proxies/robots_ttl/user_agents） |
| ai_service/rag/crawl/crawler.py | 修改 | 新增 robots 检查 + UA 轮换 + 限速延迟 + 代理轮换 + fetch_page 重试循环 |
| ai_service/tests/crawl/test_crawler.py | 修改 | fetch_page mock 补 status_code=200 兼容重试逻辑 |
| ai_service/tests/crawl/test_antibot.py | 新增 | 28 项反爬 mock 单测（robots/UA/限速重试/代理轮换/配置） |
| specs/module-077-antibot-proxy/changelog.md | 修改 | 本变更日志 |

## 关键设计说明

### 设计决策 1: robots.txt 遵循（fail-open）
- 决策: `urllib.robotparser.RobotFileParser` + httpx 拉取 + 按域名缓存 TTL
- 原因: 标准库零新依赖；fail-open（robots.txt 不存在/超时 = 允许抓取）不阻塞主链路；固定 UA "PersonalKB-Crawler" 做 robots 检查（与 fetch 随机 UA 解耦，避免 robots 规则不一致）

### 设计决策 2: UA 轮换 + 请求头增强
- 决策: 内置 ~10 个主流浏览器 UA（Chrome/Edge/Firefox/Safari 桌面+移动）+ Accept/Accept-Language/Accept-Encoding 头
- 原因: 降低被识别为爬虫概率；随机选择简单高效；配置 `crawl_user_agents` 可扩展

### 设计决策 3: 限速 + 重试退避
- 决策: per-source 请求间隔 1s（time.monotonic 单调时钟）；429/5xx 指数退避（base × 2^attempt + jitter ±20%，最多 3 次）；超时直接重试无额外延迟
- 原因: 防频率封禁；指数退避+jitter 防惊群效应；超时=网络不稳，快试快判

### 设计决策 4: 代理配置化轮换
- 决策: 配置 `crawl_proxies` 逗号分隔 HTTP 代理列表；round-robin 轮换；失败自动切下一个；空列表直连
- 原因: 简单可靠；集成在重试循环中自然切换；不引入 SOCKS5（需额外依赖）

## 验证命令
| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| 语法 | `python -c "import ast; ast.parse(open('rag/crawl/crawler.py',encoding='utf-8').read()); print('SYNTAX_OK')"` | SYNTAX_OK |
| import | `python -c "from rag.crawl.crawler import _check_robots_allowed, _pick_ua, _random_headers, _next_proxy"` | CRAWLER_IMPORT_OK |
| config | `python -c "from src.config import settings; print(settings.crawl_request_delay_seconds, settings.crawl_retry_max)"` | 1.0 3 |
| 新增单测 | `cd ai_service && python -m pytest tests/crawl/test_antibot.py -v` | 28/28 passed |
| 全量回归 | `cd ai_service && python -m pytest tests/crawl -q` | 119 passed (91 baseline + 28 new) |

### 子任务 5 测试覆盖矩阵

| AC 编号 | 测试方法 | 状态 |
|---------|----------|------|
| AC-1.1.1 | test_robots_allow | ✅ |
| AC-1.1.2 | test_robots_disallow | ✅ |
| AC-1.1.3 | test_robots_cache_hit | ✅ |
| AC-1.1.4 | test_robots_fail_open | ✅ |
| AC-1.1.5 | test_robots_uses_fixed_ua | ✅ |
| AC-1.2.1 | test_ua_pool_size | ✅ |
| AC-1.2.2 | test_random_headers_keys | ✅ |
| AC-1.2.3 | test_ua_randomness | ✅ |
| AC-1.2.4 | test_fetch_uses_random_headers | ✅ |
| AC-1.3.1 | test_429_triggers_retry_then_success | ✅ |
| AC-1.3.2 | test_500_triggers_retry_then_success | ✅ |
| AC-1.3.3 | test_exponential_backoff_delays | ✅ |
| AC-1.3.4 | test_max_retries_exceeded_returns_failure | ✅ |
| AC-1.3.5 | test_timeout_retries_no_extra_delay | ✅ |
| AC-1.3.6 | test_non_retryable_error_no_retry | ✅ |
| AC-1.3.7 | test_delay_injected_between_requests | ✅ |
| AC-1.4.1 | test_empty_proxy_list_returns_none / test_no_proxy_when_empty | ✅ |
| AC-1.4.2 | test_round_robin_rotation | ✅ |
| AC-1.4.3 | test_proxy_switch_on_retry | ✅ |
| AC-1.4.4 | test_all_proxies_fail_returns_failure | ✅ |
| AC-2.1 | test_robots_empty_content_fail_open | ✅ |
| AC-2.2 | test_robots_wildcard_rules | ✅ |
| AC-2.3 | test_max_retries_zero_no_retry | ✅ |
| AC-2.4 | test_no_delay_when_config_zero | ✅ |
| AC-2.5 | test_proxy_with_spaces_parsed | ✅ |
| AC-3.1 | test_robots_fail_open | ✅ (fail-open 同 1.1.4) |
| AC-3.4 | test_error_message_truncated | ✅ |
| AC-4.2.5 | conftest default_antibot_mocks | ✅ (已存在于 conftest.py) |

## 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-26 | 初始实现（子任务 1-4） | Developer |
| v2 | 2026-08-26 | 子任务 5：28 项反爬 mock 单测 + changelog 更新 | Developer |
