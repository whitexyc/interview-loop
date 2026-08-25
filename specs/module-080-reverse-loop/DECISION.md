# Module-080 编排者合并决策（2026-08-26）

## 结论
- **主实现采用 specs/module-080-reverse-loop/（DSH 会话，feedback 表驱动）**：已完成开发 + 22 单元测试 + 全量 1449 绿，闭环链路（低分题→待学笔记→抓取优先级）已打通。
- specs/module-080-reverse-feedback/（并行会话设计，Java InterviewTurnLog 每题评分 + crawl_priority 表 + Bing 种子）**归档为增强方向**：待 Java 侧新增弱题端点后，可将其作为更真实的数据源接入（后续模块/扩展，不阻塞当前闭环）。

## 协调说明
- 两方案差异：数据源（feedback vs Java 评分）、存储（documents 前缀 vs memory_service）、优先级（source_configs.priority 动态加权 vs crawl_priority 表）。
- 决策理由：reverse-loop 已实现且全绿、自包含零跨系统依赖；reverse-feedback 设计更贴近真实低分题但需跨系统集成，作为增量演进保留。

