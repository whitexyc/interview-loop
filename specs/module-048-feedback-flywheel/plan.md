# 功能规格说明书 — Module-048: 反馈飞轮 + 前端防护 + 硬闸门阈值落地

> Planner | 2026-08-10

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-048 |
| 模块名称 | 👍👎 反馈飞轮（层 4 数据源）+ 前端 maxlength + 硬闸门阈值 0.55 |
| 版本号 | 0.48.0-module-048 |
| 优先级 | P1（飞轮解锁两个层 4 分类器再训练；阈值改动有数据证据） |
| 预估代码量 | 后端表+端点 + 前端按钮 + 3 处小改，≤ 350 行 |

---

## 2. 需求

| WP | 内容 | 来源 |
|----|------|------|
| WP1 后端反馈 | 新建 feedback 表（id, message_id, rating ±1, comment, identity, created_at）+ `POST /ai/feedback` 端点（落库，Pydantic 校验 rating ∈ {1,-1}，comment ≤500）——**两个层 4 分类器（intent/充分性）的飞轮数据源** | 未解决清单 #10/11 |
| WP2 前端反馈 | ChatMessage 每条 AI 回复下方 👍👎 按钮 → 调 API → Toast 确认；飞轮数据开始积累 | 同上 |
| WP3 前端 maxlength | 输入框 `maxLength={2000}`（前端防输入、后端 422 防绕过，Q4 拍板） | ADR-0001 Q4 |
| WP4 硬闸门阈值 | `config.py` 硬闸门阈值默认 0.4 → **0.55**（module-047 实测：0.4 漏判 60% 不充分、0.55 F1=0.98 且误杀与 0.5 相同 1/50，切在分布间隙上缘） | module-047 WP2 |
| WP5 白名单防御 | L4 分类器置信度 `probs.get(intent, 0.0)`（reviewer minor：真实分类器缺键 KeyError 防御） | 045 minor |

### 验收场景

```
场景 1：反馈落库
  假设 POST /ai/feedback {"message_id": 1, "rating": 1, "comment": "很好"}
  那么 返回 200 + feedback 表新增记录；rating=0 或 2 → 422

场景 2：前端点赞
  假设 用户在 AI 回复下点 👍
  那么 调 API 成功 + Toast "感谢反馈"；重复点击不重复提交（已反馈态）

场景 3：输入框限长
  假设 输入 >2000 字符
  那么 输入框阻止继续输入（maxLength 生效）

场景 4：硬闸门 0.55
  假设 top-1 abs_cosine = 0.45
  那么 直接判不充分（< 0.55）——旧阈值 0.4 会漏判进 LLM

场景 5：白名单防御
  假设 分类器 probs 缺 knowledge 键
  那么 不抛 KeyError，回退默认置信度
```

---

## 3. 技术方案

### 3.1 工作包与涉及文件

| WP | 文件 | 操作 |
|----|------|------|
| WP1 后端 | `ai_service/rag/models.py`（Feedback 模型）+ `ai_service/src/database.py`（建表，对齐现有 Base.metadata 模式）+ `ai_service/main.py`（POST /ai/feedback 端点）+ `ai_service/rag/schemas.py`（FeedbackRequest） | 修改 |
| WP1 测试 | `ai_service/tests/test_feedback.py` | 新建 |
| WP2 前端 | `frontend/src/components/ChatMessage.tsx`（👍👎 按钮 + 已反馈态）+ `frontend/src/services/ragService.ts`（submitFeedback）+ `frontend/src/types/rag.ts`（FeedbackRequest 类型） | 修改 |
| WP3 前端 | `frontend/src/pages/ChatPage.tsx`（输入框 maxLength={2000}） | 修改 |
| WP4 | `ai_service/src/config.py`（memory 旁新增 sufficiency 硬闸门阈值项，默认 0.55；若现有常量硬编码在 reflector.py 则改配置读取）+ `ai_service/agent/reflector.py`（读配置） | 修改 |
| WP5 | `ai_service/agent/router.py`（probs.get 防御一行） | 修改 |

### 3.2 关键实现约束

- **WP1**：Feedback 表独立新表（feedback 与 documents 表无关）；端点从 request.state 取 identity（user_id 优先 client_ip，对齐现有中间件注入）；rating 校验 ±1；comment 可选 ≤500；落库失败返回 500 但前端降级静默（不阻塞聊天）
- **WP2**：按钮状态（未评/已评）存组件本地 state + zustand 或 localStorage（简单：组件 state + 按 message_id 记录已评）；Toast 用 antd message
- **WP4**：模块-047 结论——0.55 切在分布间隙上缘（充分 min 0.490 / 不充分 max 0.550），F1=0.98 最优；config 新增 `sufficiency_gate_threshold: float = 0.55`（PW_ 前缀），reflector.py 硬编码 0.4 改为读配置
- **WP5**：一行 `confidence = probs.get(intent, 0.0)` 或等价防御

### 3.3 降级

| 场景 | 处理 |
|------|------|
| feedback 落库失败 | 端点返回 500 + 前端 Toast 失败提示（聊天不受影响） |
| 前端无 message_id（历史消息） | 按钮隐藏或禁用 |
| 0.55 上线后误杀增加 | 标注集可继续校准（阈值扫描工具已就绪） |

---

## 4. 依赖

- module-047（阈值 0.55 数据证据）、module-043（L4 分类器）、ADR-0001 Q4（maxlength）
- 前端：antd 5 + axios + zustand（现有技术栈）

## 5. 已知边界

- 前端构建验证（npm run build / tsc）为 Tester 必查项；前端单测若已有框架则补，无则不强制
- feedback 表建表：对齐现有 schema 管理方式（若项目是 create_all 则自动建，无需手动迁移）
- 全量 pytest 525 全绿保持
