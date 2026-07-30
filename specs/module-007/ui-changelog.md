# Changelog — Module-007 前端页面美化

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v6 | 2026-07-30 | 简历编辑功能（后端 PUT + 前端编辑页面 + 密码保护） | Developer-Frontend |
| v5 | 2026-07-30 | 提示词按钮 + 导航居中 + 风格统一 | Developer-Frontend |
| v4 | 2026-07-30 | UI/UX Pro Max 系统性美化收尾 — 卡片 hover 统一 + DocumentPage 重构 | Developer-Frontend |
| v3 | 2026-07-30 | UI/UX Pro Max 全面可访问性 & UX 审查修复 | Developer-Frontend |
| v2 | 2026-07-30 | 基于 frontend-design skill 应用统一设计 Token 系统 | Developer-Frontend |
| v1 | 2026-07-30 | 全页面 UI 美化 | Developer-Frontend |

## v6 — 简历编辑功能

### 后端
- `ResumeController.java` 已存在 `PUT /api/v1/resume` 端点（复用 `ResumeService.updateResume()`）
- 接收完整 ResumeDTO JSON，更新后返回最新数据

### 前端
- **新增** `frontend/src/pages/EditResumePage.tsx`
- **新增** `frontend/src/services/resumeService.ts` 中 `updateResume()` 函数
- **修改** `frontend/src/App.tsx` — 添加 `/edit-resume` 路由
- **修改** `frontend/src/components/AppLayout.tsx` — 导航栏右侧添加编辑按钮（`EditOutlined`）

### 编辑页面功能
- **密码保护** — 页面加载时弹出密码验证（默认密码 `admin123`），通过 sessionStorage 记录状态
- **全表单编辑** — 6 个分区 Card：
  - 个人信息（姓名/性别/电话/邮箱/求职意向/GitHub）
  - 教育背景（动态 Form.List：学校/专业/届别/排名/核心课程）
  - 荣誉证书（动态字符串列表）
  - 专业技能（动态分类：分类名称 + 技能项）
  - 项目经历（动态列表：项目名/角色/时间/描述/关键成果）
  - 自我评价（TextArea）
- 数组字段使用逗号分隔输入，自动解析为数组
- 保存后自动刷新数据，3 秒成功提示

### 验证
- `npx tsc --noEmit` — 通过（零错误）
- `npx vitest run` — 通过（3 test files, 20 tests, 0 warnings）

---

## v5 — 提示词按钮 + 导航居中 + 风格统一

### 变更
- **ChatPage** — 空状态新增 3 个提示词按钮（"什么是G1 GC""Java线程池原理""什么是MoE"），圆角药丸形状，灰色背景，点击直接发送消息
- **AppLayout** — 导航栏水平居中（Header `justifyContent: center`，Logo `position: absolute` 固定左侧），Menu 内 `justifyContent: center`
- **DocumentPage** — 确认与 ResumePage 风格统一（cardHoverStyle / `.resume-card` / 圆角 16 / 阴影一致）

### 验证
- `npx tsc --noEmit` — 通过（零错误）
- `npx vitest run` — 通过（3 test files, 20 tests, 0 warnings）

---

## v4 — UI/UX Pro Max 系统性美化收尾

### 修复
- **DocumentPage**: 完全重写（编码损坏修复），新增卡片 hover 效果（`.resume-card:hover` + `transition`），与 ResumePage 风格统一
- **所有页面卡片**: DocumentPage 主 Card 添加 `className="resume-card"`，与 ResumePage 共享 hover 阴影过渡效果

### 当前设计系统状态

| 属性 | 值 | 状态 |
|------|-----|------|
| 主色 | `#1e40af` (deep blue) | ✅ ConfigProvider |
| 强调色 | `#0891b2` (cyan) | ✅ ConfigProvider |
| 背景色 | `#f0f5f9` | ✅ ConfigProvider |
| 基础字号 | 16px | ✅ ConfigProvider |
| 行高 | 1.5 | ✅ ConfigProvider |
| 卡片圆角 | 16px | ✅ 所有页面 |
| 卡片阴影 | `0 1px 3px rgba(0,0,0,0.05)` | ✅ 所有页面 |
| 卡片 hover | 阴影提升 + translateY(-1px) | ✅ 所有页面 |
| 触摸目标 | ≥ 44×44px | ✅ Logo / 引用标签 / 按钮 |

### 验证
- `npx tsc --noEmit` — 通过（零错误）
- `npx vitest run` — 通过（3 test files, 20 tests, 0 warnings）

---

## v3 — UI/UX Pro Max 审查修复

基于 UI/UX Pro Max skill 的优先级规则（Priority 1→10）进行系统性审查，修复以下类别的问题：

### Priority 1: 可访问性 (Critical)
- **触摸目标** — 修复 2 处 < 44×44px 的交互元素：
  - `ChatMessage.tsx`: 引用 `[n]` 标签 padding 从 `0 6px` 增至 `8px 10px`（lineHeight 20→28px），确保可点击区域 ≥ 44px
  - `AppLayout.tsx`: Logo 头像从 32×32 增至 44×44，文字 14→18px
- **颜色对比度** — 关键前景/背景配对验证通过：
  - `#0f172a` on `#ffffff` = ~15:1 ✓
  - `#475569` on `#ffffff` = ~5.4:1 ✓ (≥ AA 4.5:1)
  - `#1e40af` on `#eff6ff` = ~5:1 ✓

### Priority 5: 布局 & 响应式 (High)
- **最小 16px 正文** — 全局 `fontSize: 16` 通过 ConfigProvider 设置，避免 iOS 自动缩放
- **行高 1.5** — 全局 `lineHeight: 1.5` 设置，正文段落额外提升至 1.7
- **间距系统** — 所有间距遵循 4pt/8dp 增量（卡片 24/32px，间隙 28/16px，内容区 32px）

### Priority 6: 排版 & 颜色 (Medium)
- **层级结构** — 姓名标题从 `Title level={3}` 提至 `level={2}`（h3→h2）
- **正文尺寸** — 统一提升：
  - 项目描述/自我评价: 15→16px
  - 标签标题("核心课程"/"关键成果"): 13→15px
  - 搜索结果标题: 13→14px, 内容预览: 12→13px
  - 引用原文: 标题 14→15px, 正文 13→14px
- **语义 Token** — App.tsx 新增 `colorBgElevated`/`colorLink` token

### 其他修复
- `CitationModal`: `destroyOnClose` → `destroyOnHidden`（Ant Design 5 deprecation）
- SearchPanel/ChatPage: 移除硬编码小字号，使用全局 16px 继承

## 验证
- `npx tsc --noEmit` — 通过（零错误）
- `npx vitest run` — 通过（3 test files, 20 tests, 0 warnings）

---

## v2 — 设计 Token 系统应用

基于 `frontend-design` skill 的设计方法，创建并应用统一设计 Token 系统到所有页面/组件。

### 设计 Token 系统

```
Subject: 张三 personal website — developer portfolio + knowledge hub
Audience: technical peers, potential employers
Signature: gradient avatar (deep blue→cyan) + section icons + left-border project cards

Color:
  Primary:    #1e40af (deep blue)     — authoritative, technical
  Accent:     #0891b2 (cyan-600)      — fresh, complementary
  Surface:    #f0f5f9 (cool gray)     — restful background
  Card:       #ffffff
  Text:       #0f172a (near-black)
  TextSec:    #475569 (slate-600)
  Border:     #e2e8f0
  Highlight:  #d97706 (amber)

Typography: Inter / system stack, h3=22px h4=18px h5=15px body=14px
Layout:     max-width 900px, gap 28px, radius 12/16
Shadow:     0 1px 3px rgba(0,0,0,0.05), hover: 0 8px 24px rgba(0,0,0,0.08)
```

### 颜色变更（所有组件）

| 旧值 | 新值 | 用途 |
|------|------|------|
| `#4f46e5` | `#1e40af` | 主色（indigo → deep blue） |
| `#6366f1` | `#2563eb` | 用户气泡渐变 |
| `#06b6d4` | `#0891b2` | 强调色/cyan |
| `#1e293b` | `#0f172a` | 正文主色 |
| `#64748b` | `#475569` | 次要文字 |
| `#f8fafc` | `#f0f5f9` | 页面背景 |
| `#eef2ff` | `#eff6ff` | 图标背景 |
| `#c7d2fe` | `#bfdbfe` | 标签边框 |
| `#4338ca` | `#1e40af` | 标签文字 |
| `#e0e7ff` | `#dbeafe` | 空状态图标 |
| `rgba(79,70,229,..)` | `rgba(30,64,175,..)` | 阴影色 |

### 文件变更（v2）

- `frontend/src/App.tsx` — 更新主题 Token：colorPrimary `#1e40af`、colorInfo `#0891b2`、borderRadius 12、colorBgLayout `#f0f5f9`、colorText `#0f172a` 等
- `frontend/src/pages/ResumePage.tsx` — 所有颜色值更新对齐新 Token，修复中文编码损坏
- `frontend/src/pages/ChatPage.tsx` — 颜色值更新，阴影色更新
- `frontend/src/pages/DocumentPage.tsx` — 颜色值更新，阴影更新
- `frontend/src/components/AppLayout.tsx` — 颜色值更新，渐变更新，maxWidth 1060→900
- `frontend/src/components/ChatMessage.tsx` — 气泡渐变/阴影/文字颜色更新
- `frontend/src/components/CitationModal.tsx` — 文字/标签颜色更新
- `frontend/src/components/SearchPanel.tsx` — 文字/阴影/圆角更新

## 验证
- `npx tsc --noEmit` — 通过（零错误）
