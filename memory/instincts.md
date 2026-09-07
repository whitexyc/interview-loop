# 经验台账（instinct 层 · rules-distill Phase 1.5）

> 格式：日期 | 触发场景 | 动作 | 置信度 | 证据 | 范围。升铁律门槛：同一原则多源命中（见 docs/rules/rules-distill.md）。
> 首战来源：module-016 铁律蒸馏（2026-09-06，数据=违规台账 283 条 + module-085~088 实战教训）。

| 日期 | 触发场景 | 动作 | 置信度 | 证据 | 范围 |
|------|----------|------|--------|------|------|
| 2026-09-06 | 写确定性脚本/闸门时 | 先写夹具再写实现 | 0.9 | module-001/004/005 夹具先行均抓真 bug；module-013/014 开发中夹具抓出 5 处脚本/用例错误 | global |
| 2026-09-06 | asyncpg 写 JSONB 列时 | 参数必须先 JSON 字符串化；dict 直传必败，且 fail-open 路径必须配「真实表零行」断言 | 0.7 | module-087：begin_task checkpoint dict 直传被 fail-open 吞，mock 全绿漏过，Tester 真实环境对账抓出 | global |
| 2026-09-06 | 写环境变量开关时 | 文档/.env 口径必须与 config.py 实名 grep 对账后方可发布 | 0.6 | module-088：文档误名 PW_TRACE_SPANS（实际 PW_TRACE_SPANS_ENABLED），.env 写旧名启动崩 | global |
| 2026-09-06 | 造测试夹具/沙盒数据时 | 先算数据长度是否越过被测阈值（如 >500 字符行、>400 字符历史条目），再写用例 | 0.7 | module-012 与 module-017 同款错误各犯一次：夹具长行 366/381 字符未过 500/400 阈值致用例空转 | global |
