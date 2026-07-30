# 开发计划 — Module-003: 简历展示前端页面

> Planner: Claude (编排角色) | 日期: 2026-07-29 | 版本: v1

## 0. Agent 配置清单

- **Developer-Frontend ×1**（flash 模型）：React 简历展示页面
- **Reviewer ×1**：审查前端代码
- **Tester ×1**：前端组件测试

---

## 1. 需求描述

- **需求来源**: 个人信息.md（张三简历数据）
- **功能描述**: 创建 React 简历展示页面，调用 `/api/v1/resume` 接口渲染完整简历
- **页面结构**: 顶部导航 + 个人信息卡片 + 教育背景 + 荣誉证书 + 专业技能 + 项目经历 + 自我评价
- **优先级**: P0

---

## 2. 模块拆分

### 子任务 1: API 服务层
- **描述**: 在 `frontend/src/services/resumeService.ts` 封装 `GET /api/v1/resume` 的 Axios 调用
- **预估代码量**: ~30 行
- **涉及文件**:
  - `frontend/src/services/resumeService.ts` (新增)

### 子任务 2: 类型定义
- **描述**: 定义 ResumeDTO TypeScript 接口，与后端返回结构对齐
- **预估代码量**: ~40 行
- **涉及文件**:
  - `frontend/src/types/resume.ts` (新增)

### 子任务 3: 简历展示页面
- **描述**: 创建 ResumePage 页面，包含：个人信息卡片、教育背景、荣誉证书、专业技能标签、项目经历卡片、自我评价。使用 Ant Design Card/Tag/List/Timeline 组件
- **代码量**: ~130 行
- **涉及文件**:
  - `frontend/src/pages/ResumePage.tsx` (新增)

### 子任务 4: 路由与布局
- **描述**: 更新 App.tsx 路由，添加 ResumePage；创建 Layout 组件（导航栏 + 内容区）
- **代码量**: ~50 行
- **涉及文件**:
  - `frontend/src/App.tsx` (修改)
  - `frontend/src/components/AppLayout.tsx` (新增)

---

## 3. 技术方案

### API 依赖
- `/api/v1/resume` → GET（后端 module-002 已实现）
- Vite 代理 `/api` → `http://localhost:8080`

### 数据结构
前端 TypeScript 类型完全对应后端 ResumeDTO（见 module-002 ResumeEntity 内部类）。

### UI 组件
- Ant Design: Card, Tag, List, Descriptions, Timeline, Typography
- 响应式布局: 双栏或居中单栏

---

## 4. 验收标准
见同目录 `acceptance-criteria.md`

## 5. 风险评估
- 依赖 module-002 API（已完成，无阻塞）
- React + Ant Design 无额外学习成本

## 6. 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-07-29 | 初始版本 | Planner |
