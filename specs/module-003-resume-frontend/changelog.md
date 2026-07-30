# 变更日志 — Module-003: 简历展示前端页面

## 变更概述
创建简历展示前端页面，包含类型定义、API 服务层、简历展示页面、布局组件和路由配置。

## 文件变更列表

| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| frontend/src/types/resume.ts | 新增 | ResumeDTO 和嵌套接口定义 |
| frontend/src/services/resumeService.ts | 新增 | Axios 封装的 getResume()，解析 CommonResult |
| frontend/src/pages/ResumePage.tsx | 新增 | 简历完整展示页面（7 个区块：个人信息/教育/荣誉/技能/项目/评价） |
| frontend/src/components/AppLayout.tsx | 新增 | 导航栏 + 内容区布局 |
| frontend/src/App.tsx | 修改 | 添加 ResumePage 路由 |
| frontend/vite.config.ts | 修改 | 添加 vitest 测试配置（jsdom, globals） |
| frontend/tsconfig.json | 修改 | 添加 vitest/globals 类型 |

## 设计说明
- 类型定义严格对齐后端 ResumeDTO
- API 调用解析 `CommonResult<T>` 包裹，检查 `code === 0` 后提取 `data`
- 加载态使用 Spin，错误态使用 Alert + 重试按钮
- 每个简历区块独立 Card，使用 Ant Design 语义组件

## 验证命令

| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| 类型检查 | `cd frontend && npx tsc --noEmit` | ✅ 零错误 |
| 构建 | `cd frontend && npm run build` | BUILD SUCCESS |

## 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-07-29 | 初始实现 | Developer-Frontend |
| v2 | 2026-07-30 | 修复类型错误、添加 vitest 支持、axios 错误处理、document.title | Developer-Frontend |
