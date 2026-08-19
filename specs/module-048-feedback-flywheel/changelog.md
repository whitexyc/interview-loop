# Module-048 反馈飞轮 + 前端防护 + 硬闸门阈值 — 变更记录

## 2026-08-10（Dev-A 交付）

### WP1 后端反馈（✅）

- `rag/models.py`：新建 `Feedback` 模型（`feedback` 表）——`id` / `message_id`（index）/ `rating`（1 赞 -1 踩）/ `comment`（Text 可空）/ `identity`（String(256)，user_id 优先 client_ip 兜底）/ `created_at`（server_default now）。与 documents 表无关的独立新表，message_id 先落前端消息 ID，飞轮回填脚本再关联 query/answer（本模块不建外键）。
- `src/database.py`：建表对齐项目现有 schema 管理方式——项目无 create_all/无 alembic，采用**幂等 DDL 迁移脚本**模式（同 eval_runs）。新增 `FEEDBACK_DDL` + `ensure_feedback_table()`（'；' 拆分逐条执行，CREATE TABLE IF NOT EXISTS + COMMENT），并接入 `init_db()` 启动自愈建表（等价 create_all 自动建，无需手动迁移）。
- `rag/schemas.py`：新增 `FeedbackRequest`（message_id int / rating int 校验 ∈{1,-1}（field_validator，0/2 → 422）/ comment Optional ≤500）。
- `main.py`：新增 `POST /ai/feedback` 端点——identity 从 request.state 取（`resolve_identity`：user_id 优先 client_ip 兜底，对齐现有中间件注入与 /ai/rag/chat 口径）；Pydantic 校验非法值 422 拦截；落库失败 catch → 500 `{"message": "反馈保存失败"}`（前端降级 Toast，不阻塞聊天）；成功返回 `{"status": "ok"}`。
- `tests/test_feedback.py` 新建（6 用例）：落库成功（字段完整 + 匿名 identity=client_ip）/ rating=-1 + comment 缺省 / rating 0、2 → 422 / comment 501 → 422 / identity user_id 优先 / 落库失败 → 500。httpx.ASGITransport 打真实 app + main.async_session_factory 假会话打桩（不依赖真实 DB）。

### WP4 硬闸门阈值 0.55（✅）

- `src/config.py`：新增 `sufficiency_gate_threshold: float = 0.55`（PW_ 前缀自动生效，注释标注 module-047 实测结论：0.4 漏判 60% 不充分、0.55 F1=0.98 切在分布间隙上缘，不得改回 0.4）。
- `agent/reflector.py`：`check_sufficiency` 层 1 分数闸门由硬编码 `_SUFFICIENCY_MIN_ABS_COSINE = 0.4` 改为读 `settings.sufficiency_gate_threshold`（常量删除，docstring/注释同步）；数量闸门 `_SUFFICIENCY_MIN_DOCS = 2` 不变；返回结构不变。
- `tests/test_reflector.py` 适配：0.4 语义用例更新为 0.55（reason 断言 "0.4"→"0.55"）；新增 AC 场景 4 用例——abs_cosine 0.45 → 直接判不充分 + 零 LLM（旧阈值 0.4 会漏判进 LLM）；达标用例 docstring 同步 0.7 ≥ 0.55。

### WP5 白名单防御（✅）

- `agent/router.py`：L4 分类器置信度 `probs[intent]` → `probs.get(intent, 0.0)`——真实分类器缺键（如缺 knowledge 键，bogus 最高分被白名单修正为 knowledge 后索引原键会 KeyError）时回退默认置信度 0.0，不抛 KeyError、不静默回退 LLM。
- `tests/test_intent_validation.py`：新增缺键用例——probs 缺 knowledge 键 + bogus 最高分 → intent=knowledge、confidence=0.0，LLM 打桩断言零调用。

### 验证

- 相关测试：`tests/test_feedback.py + test_reflector.py + test_intent_validation.py + test_schemas_validation.py` → **77 passed**。
- 全量 `python -m pytest tests/ -q` → **533 passed / 0 failed**（基线 525 + 新增 8，零回归）。

### 已知边界

- feedback 建表走 init_db 启动自愈（CREATE TABLE IF NOT EXISTS），本地开发库重启 AI 服务后自动建表；不重启也可手动执行 `ensure_feedback_table()`。
- 飞轮数据说明：feedback 表是层 4 分类器（intent/充分性）重训数据源——数据积累到一定量后用 message_id 关联 query/answer 生成标注集（eval/golden_intent.py、eval/golden_sufficiency.py 口径），再增量重训 intent_clf / sufficiency_clj（module-045 已建训练脚本）。本模块只落库不消费。
- 阈值 0.55 上线后误杀若增加：标注集可继续校准（eval/threshold_scan.py 阈值扫描工具已就绪），分数源为 module-047 标注集注入文档实测余弦，生产真实检索分布上线前建议抽样复核。

## 2026-08-10（Dev-B 交付）

### WP2 前端反馈（✅）

- `frontend/src/components/ChatMessage.tsx`：Props 替换（`messageIndex`/`feedbackRating`/`onFeedback` → `messageId`）；新增 `handleRate`（👍→rating=1 / 👎→rating=-1，调 submitFeedback，成功 `message.success('感谢反馈')`，失败 `message.error('反馈提交失败，请重试')` 且不置已评态可重试）；已评态记录——模块级 `ratedMessages: Map<message_id, 'up'|'down'>` + localStorage（key `rag_feedback_rated`，切会话/刷新均不丢，防重复/冲突提交污染飞轮）；反馈块改为 antd Button（size=small，`LikeOutlined`/`DislikeOutlined`，已评态 `disabled` + 选中 `type="primary"` 高亮）；仅 `!isUser && !isStreaming && messageId !== undefined` 展示。
- `frontend/src/services/ragService.ts`：新增 `submitFeedback(payload: FeedbackRequest)` → `POST /ai/feedback`（axios 非 2xx 自动抛错，调用方降级 Toast，不阻塞聊天）。
- `frontend/src/types/rag.ts`：新增 `FeedbackRequest`（`message_id: number` / `rating: 1 | -1` / `comment?: string`），与后端 `rag/schemas.py::FeedbackRequest` 对齐。
- `frontend/src/pages/ChatPage.tsx`：移除 M10 本地装饰性反馈（feedbackMap/handleFeedback/localStorage `rag_feedback`）；消息渲染传 `messageId={msg.id}`（Java 后端持久化消息主键；流式新消息无 id → 按钮隐藏，会话重载后展示）；**WP3** 输入框加 `maxLength={2000}`（前端防输入，后端 422 防绕过，ADR-0001 Q4）。
- 说明：规格中的 ThumbUpOutlined/ThumbDownOutlined 在本仓库锁定版本 @ant-design/icons@5.6.1 不存在（实测 undefined），改用同形 👍👎 的 LikeOutlined/DislikeOutlined，零新依赖。

### 验证（Dev-B）

- 前端单测：新增 `frontend/src/__tests__/ChatMessage.test.tsx`（7 用例全过：隐藏/展示/用户消息不展示/👍rating=1 已评态/👎rating=-1/不重复提交/失败可重试）；`ChatPage.test.tsx` 补 maxLength=2000 断言 + ragService mock 补 submitFeedback。全量 `npx vitest run` → **39 passed / 3 failed**（3 failed 为 ChatPage 预存环境问题，git HEAD 基线复跑同 3 项失败，非本模块引入）。
- 构建：`npm run build`（tsc + vite build）→ PASS（3102 modules, built in 20.01s）。

## 2026-08-10（Tester 全量回归）

- 全量 `python -m pytest tests/ -q` 独立复跑 → **533 passed / 0 failed**（121.56s，基线 525 + 新增 8 零回归，5 warnings 为预存）。
- 新增测试逐项核对：`tests/test_feedback.py` 6 用例（落库/±1/422 校验/identity 优先级/落库失败 500）、`test_reflector.py` 阈值适配（AC 场景 4：abs_cosine 0.45 → 直接不充分零 LLM）、`test_intent_validation.py` 缺键回退（LLM 零调用断言）。
- 源码级抽查：`config.py:99` sufficiency_gate_threshold=0.55（PW_ 前缀生效）；`reflector.py:195` 读配置，0.4 常量已删；`router.py:176` probs.get 防御。
- 前端 `npm run build` → PASS（tsc + vite，3102 modules，18.09s）；`npx vitest run` → 39 passed / 3 failed，module-048 新增 8 用例全过，3 failed 经 HEAD 基线 worktree 双跑确认与基线逐项一致（预存环境问题，非本模块引入）；package.json 零 diff。
- 交付物：`test-report.md` 产出，验收 §9 文档三件套齐全。
