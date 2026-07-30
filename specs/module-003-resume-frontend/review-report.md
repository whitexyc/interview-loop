# 审查报告 — Module-003: 简历展示前端页面

## 1. 审查结论
- 结论: **不通过**

代码结构清晰、类型完备、组件拆分合理，但存在与验收标准的偏差：404 错误未按验收要求显示指定文案，且头像区域在验收标准与实现之间存在未对齐的 gap，需要确认后再合并。

---

## 2. 问题列表

### 阻塞问题

| # | 文件 | 行号 | 问题 | 修复建议 |
|---|------|------|------|----------|
| 1 | `frontend/src/pages/ResumePage.tsx` | 34-36 | **404 错误未显示"简历加载失败"**。验收标准要求 `API 返回 404 时显示"简历加载失败"`，但当前代码只显示 `err.message`（axios 默认输出 `"Request failed with status code 404"`），未做 HTTP 状态码判断。 | 在 catch 中增加 `axios.isAxiosError(err)` 判断，对 404 状态码返回 `'简历加载失败'`。示例如下： |

```typescript
} catch (err: unknown) {
  if (axios.isAxiosError(err) && err.response?.status === 404) {
    setError('简历加载失败');
  } else {
    setError(err instanceof Error ? err.message : '未知错误');
  }
}
```

> 需要额外 import `axios`（或在 service 层封装）。

| # | 文件 | 行号 | 问题 | 修复建议 |
|---|------|------|------|----------|
| 2 | `specs/module-003-resume-frontend/acceptance-criteria.md` | 5 | **头像区域未对齐**：验收标准第 5 行要求 "展示 ... 头像区域"，但 `ResumeDTO` 中无 `avatar` 字段、plan.md 未提及、UI 也未渲染任何头像。这是验收标准与数据合约之间的 gap，需确认是否移除该条或补充后端字段。 | 若后端不支持头像，则从验收标准中删除 "头像区域"；若需要，则在 `ResumeDTO` 增加 `avatar: string` 并在页面渲染。 |

### 建议改进

| # | 文件 | 行号 | 问题 | 建议 |
|---|------|------|------|------|
| 1 | `frontend/src/pages/ResumePage.tsx` | 144 | **项目经历列表 key 使用 `project.name`**，若两个项目同名会导致 React 渲染异常（key 冲突）。 | 若后端返回唯一 id，优先使用 `project.id`；否则使用 `project.name + project.time` 组合或 index 兜底。 |
| 2 | `frontend/src/pages/ResumePage.tsx` | 30-38 | **未设置页面 `<title>`**，浏览器标签页会使用默认值。 | 在 `useEffect` 中通过 `document.title = '个人简历 - 张三'` 设置标题。 |
| 3 | `frontend/src/pages/ResumePage.tsx` | -- | **超时/异常错误提示不够友好**：验收标准要求"显示友好错误提示"，但当前直接暴露 axios 原始错误消息（如 `"timeout of 10000ms exceeded"`）。 | 建议在 service 层或 catch 中做消息映射，例如 `timeout` → `'请求超时，请稍后重试'`、`Network Error` → `'网络异常，请检查连接'`。 |
| 4 | `frontend/src/services/resumeService.ts` | 14-21 | **错误消息提取不完整**：若后端在 HTTP 200 但 `code !== 0` 时返回了 `msg` 字段，当前使用了 `body.msg`，但 axios 网络错误时未提取 `error.response?.data?.msg`。 | 可在 catch 中判断是否有 `error.response?.data`，优先使用后端返回的消息。 |
| 5 | `frontend/src/pages/ResumePage.tsx` | 65 | **多余的 defensive check**：`if (!resume) return null` 行在 `loading=false`、`error=null` 且 `getResume()` 在 data 为 null 时会抛出的前提下不可达。 | 虽然无害，可移除该行以保持简洁。 |


## 3. 验收标准核对

| 验收项 | 状态 | 备注 |
|--------|------|------|
| 调用 `/api/v1/resume` 获取数据 | ✅ 通过 | `resumeService.ts` 调用 `GET /api/v1/resume` |
| 展示：姓名/电话/邮箱/求职意向 | ✅ 通过 | 个人信息卡片中全部展示 |
| 展示：头像区域 | ❌ 未实现 | `ResumeDTO` 无 `avatar` 字段，UI 未渲染 |
| 展示：教育背景（学校/专业/排名/课程） | ✅ 通过 | 含学校、专业、届别、排名、核心课程标签 |
| 展示：荣誉证书列表 | ✅ 通过 | `Flex` + `Tag` 展示 |
| 展示：专业技能分类标签 | ✅ 通过 | 按分类使用 `Card` + `Tag` 展示 |
| 展示：项目经历（名称/角色/时间/描述/亮点） | ✅ 通过 | 含名称、角色、时间、描述、关键成果列表 |
| 展示：自我评价 | ✅ 通过 | `Typography.Paragraph` 渲染，支持换行 |
| API 返回 404 时显示"简历加载失败" | ❌ 未实现 | 当前显示 axios 默认 404 消息 |
| API 超时/异常时显示友好错误提示 | ❌ 未实现 | 当前暴露原始错误消息 |
| 组件拆分合理 | ✅ 通过 | 页面/服务/类型/布局分离清晰 |
| TypeScript 类型完备 | ✅ 通过 | 所有接口和返回类型有完整定义 |
| 命名符合规范 | ✅ 通过 | PascalCase 组件，camelCase 函数/变量 |

**验收统计**：10 项通过 / 3 项未通过

---

## 4. 代码质量评估

### TypeScript 类型
- `ResumeDTO`、`ApiResponse<T>`、子类型定义完整，无 `any` 或隐式 `any`。
- 泛型 `ApiResponse<T>` 设计符合后端 `CommonResult<T>` 统一包装模式。
- ✅ 优秀

### 组件拆分
- `App.tsx` → 路由 + 全局配置
- `AppLayout.tsx` → 布局壳（Header + Content）
- `ResumePage.tsx` → 页面级数据获取 + 渲染
- `resumeService.ts` → API 服务层
- `types/resume.ts` → 类型定义
- 分层合理，职责清晰。
- ✅ 优秀

### React 最佳实践
- `useCallback` + `useEffect` 避免不必要的重新请求，依赖管理正确。
- 加载态（`Spin`）、错误态（`Alert` + 重试按钮）、空态（`null`）三态覆盖完整。
- 条件渲染顺序正确（loading → error → normal）。
- `Descriptions` 列数响应式（`column={{ xs: 1, sm: 2 }}`）。
- `project.highlights` 空数组时 List 只渲染 header，建议加 `isEmpty` 判断。
- 整体 ✅ 良好

### 命名规范
- 组件：`AppLayout`、`ResumePage` (PascalCase) ✅
- 函数：`fetchResume`、`getResume` (camelCase) ✅
- 类型：`ResumeDTO`、`ApiResponse<T>`、`EducationItem` (PascalCase) ✅
- ✅ 符合规范
