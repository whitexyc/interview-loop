# Review Report — Module-048 反馈飞轮 + 前端防护 + 硬闸门阈值落地

> Reviewer | 2026-08-10 | 依据 plan.md / acceptance-criteria.md / changelog.md / 实际代码审查 + 独立测试复跑
> 结论：**APPROVED（通过）** — 无 critical / major，4 项 minor（均已如实披露或纯文档层面，不阻塞验收）

---

## 1. 红线核查（全部通过）

| 红线 | 核查方式 | 结果 |
|------|----------|------|
| ① 只动 plan 3.1 列出的文件 | `git status --porcelain` + `git diff HEAD` 逐项比对：Dev-A 改动 = 后端 10 个文件（models/database/schemas/main/config/reflector/router + 3 个测试，全在 plan 3.1 WP1/WP4/WP5 清单内）；Dev-B 改动 = 前端 4 个文件 + 2 个测试（ChatMessage/ragService/types/ChatPage + 新建 ChatMessage.test.tsx + 修改 ChatPage.test.tsx，全在 WP2/WP3 清单内）；`specs/module-048-feedback-flywheel/changelog.md` 已更新（specs/ 目录被 .gitignore 忽略，故不出现在 git status，内容已核实）。另检出 `specs/module-033-long-term-memory/changelog.md` 有改动——经 diff 核实为 2026-08-08 前任 Reviewer 追加的跨模块缺陷清单，非本模块两位 Developer 所为 | ✅ 通过 |
| ② 不运行 git commit | `git log --oneline` HEAD 仍为 a6bfaea（module-047 数据实验提交），工作树零新提交 | ✅ 通过 |
| ③ 全量 pytest 525 全绿保持 | Reviewer 独立复跑 `python -m pytest tests/ -q`：**533 passed / 0 failed**（5 预存 warnings，124.25s），与 Dev-A 声明完全一致（525 基线 + 8 新增 = 533，新增 = test_feedback 6 + test_reflector 1 + test_intent_validation 1） | ✅ 通过 |
| ④ 前端零新依赖 | `git diff HEAD -- frontend/package.json` 无任何改动；ThumbUp/ThumbDown → Like/Dislike 图标属 @ant-design/icons 既有导出，零新装 | ✅ 通过 |
| ⑤ 阈值 0.55 落地且未回退 | `src/config.py:99` `sufficiency_gate_threshold: float = 0.55`（PW_ 前缀，注释标注 module-047 结论与红线）；`agent/reflector.py` 层 1 分数闸门读 `settings.sufficiency_gate_threshold`，旧常量 `_SUFFICIENCY_MIN_ABS_COSINE=0.4` 已删除；功能代码中无 0.4 残留（仅两处注释级残留，见 §4 minor 1/2） | ✅ 通过 |

## 2. 代码审查（逐文件读实际代码，非仅信自述）

### WP1 后端反馈（Dev-A）

- `rag/models.py` Feedback 模型：id / message_id（Integer NOT NULL + index）/ rating / comment（Text 可空）/ identity（String(256) 非空默认 ""）/ created_at（server_default now），字段与验收 §1 完全对齐；独立新表与 documents 无关，message_id 不做外键（回填脚本再关联，符合 plan 3.2）。
- `src/database.py`：`FEEDBACK_DDL`（CREATE TABLE IF NOT EXISTS + 5 条 COMMENT）+ `ensure_feedback_table()`（按 ';' 拆分逐条执行，规避 asyncpg 多语句限制），接入 `init_db()` 启动自愈——对齐项目既有 eval_runs 的幂等 DDL 迁移模式（项目无 create_all/无 alembic），符合 plan §5"对齐现有 schema 管理方式"。
- `rag/schemas.py` FeedbackRequest：message_id int 必填；rating `field_validator` 校验 ∈ {1,-1}（0/2 → 422）；comment Optional + max_length=500（501 → 422）。校验完整。
- `main.py` POST /ai/feedback：identity 从 `resolve_identity(fastapi_req)` 取（request.state.user_id 优先、client_ip 兜底，与 /ai/rag/chat 及中间件注入口径一致）；落库失败 catch 全部异常 → 500 `{"message": "反馈保存失败"}`（降级验收 §6.1）；成功 `{"status": "ok"}`。端点仅新增，未触碰任何既有端点（diff 核实仅 +import 两行 + 新端点块）。
- `tests/test_feedback.py` 6 用例：落库字段完整（匿名 identity=client_ip，httpx ASGITransport 默认 client=("127.0.0.1",123) 与断言自洽）/ rating=-1 缺省 comment / rating 0、2 → 422 / comment 501 → 422 / JWT user_id 优先 / 落库失败 → 500。测试用 `main.async_session_factory` 打桩假会话，不依赖真实 DB，与 test_memory.py 同款模式；conftest 已全局取消限流。

### WP4 硬闸门阈值（Dev-A）

- `config.py`：`sufficiency_gate_threshold: float = 0.55`，`model_config env_prefix="PW_"` 自动生效（PW_SUFFICIENCY_GATE_THRESHOLD 可覆盖），注释完整标注 module-047 数据结论（0.4 漏判 60% / 0.55 F1=0.98 切分布间隙上缘 0.490-0.550 / 红线不得改回 0.4）。
- `reflector.py` check_sufficiency 层 1：`top1_abs < settings.sufficiency_gate_threshold` → 直接不充分 + rewritten_query=query，零 LLM；数量闸门（<2 篇）与返回结构（sufficient/reason/rewritten_query）不变；abs_cosine 缺失或异常值仍跳过闸门走 LLM（不误杀，原行为保留）。
- `tests/test_reflector.py`：0.4 语义用例 reason 断言改 0.55；新增 `test_gate_threshold_0_55_catches_0_45`（AC 场景 4：0.45 < 0.55 → 直接不充分，零 LLM 调用断言，旧 0.4 会漏判进 LLM）；达标用例（0.7）仍走 LLM 且恰好一次调用。

### WP5 白名单防御（Dev-A）

- `router.py` L4 路径：`probs[intent]` → `probs.get(intent, 0.0)`，白名单修正为 knowledge 后缺键回退默认置信度 0.0，不抛 KeyError、不静默回退 LLM。
- `tests/test_intent_validation.py` 新增 `test_classifier_missing_knowledge_key_no_keyerror`：probs 缺 knowledge 键 + bogus 最高分 → intent=knowledge、confidence=0.0，LLM 打桩 side_effect 断言零调用。

### WP2 前端反馈（Dev-B）

- `ChatMessage.tsx`：仅 `!isUser && !isStreaming && messageId !== undefined` 时在气泡底部渲染 👍👎 antd Button（Like/Dislike 图标，已评态 disabled + 选中 type=primary）；`handleRate` 调 `submitFeedback({message_id, rating: 1|-1})`，成功 `message.success('感谢反馈')` 并写入已评态（组件 state + 模块级 Map + localStorage `rag_feedback_rated`，切会话/刷新不丢、防重复/冲突提交污染飞轮），失败 `message.error('反馈提交失败，请重试')` 且不置已评态可重试；submitting 态防连点。
- `ragService.ts` submitFeedback：`http.post('/feedback', payload)`（baseURL '/ai' 由 client.ts 统一封装附 JWT）→ POST /ai/feedback，非 2xx axios 自动抛错由调用方 Toast。
- `types/rag.ts` FeedbackRequest：`{message_id: number; rating: 1 | -1; comment?: string}`，与后端 Pydantic 模型字段名逐一对齐（见 §3 契约核查）。
- `ChatPage.tsx`：传 `messageId={msg.id}`（MessageDTO.id，Java 后端持久化消息主键）；移除 M10 本地装饰性反馈（feedbackMap/handleFeedback/localStorage rag_feedback，同 UI 槽位替换，避免双反馈 UI）；**WP3** `Input.TextArea maxLength={2000}`。

### WP3 前端 maxlength（Dev-B）

- `ChatPage.tsx:627` `maxLength={2000}` 生效；`ChatPage.test.tsx` 新增 `maxlength='2000'` 属性断言（8 行 diff：mock 补 submitFeedback + 新断言）。

## 3. 前后端接口契约核查（逐字段对齐）

| 项 | 前端（Dev-B） | 后端（Dev-A） | 结论 |
|----|---------------|---------------|------|
| 路径 | `POST /ai/feedback`（http baseURL '/ai' + '/feedback'） | `@app.post("/ai/feedback")` | ✅ 一致 |
| message_id | `message_id: number` | `message_id: int = Field(...)` | ✅ 一致 |
| rating | `rating: 1 \| -1`（👍=1 / 👎=-1） | `rating ∈ {1,-1}` field_validator（0/2 → 422） | ✅ 一致 |
| comment | `comment?: string`（当前前端不采集） | `Optional[str] max_length=500` | ✅ 一致（可选字段缺省 None） |
| 成功判定 | 仅以 2xx 判成功（不解析 body） | 200 `{"status": "ok"}` | ✅ 一致 |
| 失败降级 | 非 2xx 抛错 → Toast 失败可重试 | 落库失败 500 `{"message": "反馈保存失败"}` | ✅ 一致 |

## 4. 独立验证

- **后端全量**：`python -m pytest tests/ -q` → **533 passed / 0 failed**（124.25s，5 预存 warnings）——红线 ③ 亲自复跑确认。
- **前端构建**：`npm run build`（tsc && vite build）→ **PASS**，3102 modules，built in 20.70s，exit 0（首跑 exit 38 系命令在 ai_service 目录执行无 package.json，切到 frontend 目录后复跑通过，非代码问题）。
- **前端单测**：`npx vitest run` → **39 passed / 3 failed**（与 Dev-B 声明完全一致）。3 项失败（should show user message after sending / should render pipeline panel and upload section / should show error alert when chat API fails）经基线复核：临时将 ChatPage.tsx 与 ChatPage.test.tsx 换回 `git show HEAD` 版本复跑 → **同样 3 failed / 2 passed**，确认 3 项失败为仓库预存环境问题（jsdom + antd 渲染差异），**非 module-048 引入**（复核后已恢复工作树原状，diff 与复核前逐字节一致）。
- **WP4 语义**：`test_gate_threshold_0_55_catches_0_45`（0.45 → 直接不充分 + 零 LLM）与 `test_classifier_missing_knowledge_key_no_keyerror`（缺键 → 0.0 置信 + 零 LLM）均在全量中通过。
- **identity 口径**：test_feedback 匿名断言 "127.0.0.1" 与 httpx ASGITransport 默认 client 及 `get_client_ip` 行为自洽；user_id 优先路径 mock parse_jwt 验证。

## 5. 文档验收

- `changelog.md` 新建：Dev-A（WP1/WP4/WP5 + 验证 + 已知边界）与 Dev-B（WP2/WP3 + 验证）两段完整，与代码实测一致，飞轮数据说明（feedback 表是层 4 分类器重训数据源）符合 AC §9。
- 记忆文件 3 份均已更新：`rag-architecture.md`（两条 module-048 记录，后端 533 passed 与前端验证分别记录）、`rag-agent-roadmap.md`（module-048 条目 + 待办：回填脚本/重训管线/sufficiency_clf 推理接入）、`MEMORY.md`（module-048 完成条目）。
- ⚠️ `test-report.md` 尚未产出（AC §9 提到 changelog/review-report/test-report 三件套）——按本工作流惯例属 Tester 交付物，已在 §6 标注为 Tester 待办，不阻塞本验收。

## 6. 发现（4 项 minor，均不阻塞）

| # | 级别 | 事项 | 说明 |
|---|------|------|------|
| 1 | minor | `reflector.py` check_sufficiency 方法 docstring 仍写 "top-1 abs_cosine < 0.4"（L162） | Dev-A 自述 "docstring 同步"，实际仅模块级注释（L43-46）与内联注释（L190-192）同步，方法 docstring 残留旧阈值。纯文档层面，无功能影响（实际闸门已读配置 0.55，测试验证）。建议随手修正 |
| 2 | minor | `eval/threshold_scan.py` docstring L9 仍描述 `reflector._SUFFICIENCY_MIN_ABS_COSINE = 0.4` | module-047 扫描工具的注释残留，该文件不在本模块工作包清单（红线 ① 未动，正确处置）；运行时只用自己的 EMPIRICAL_GATE=0.4 做历史对比基线、不引用 reflector 常量，无功能影响。Dev-A 已在 issues_known 如实披露 |
| 3 | minor | 流式新生成消息无 message_id，同一会话内新回复暂不可评 | Java `saveMessages` 返回 Void，前端拿不到新 id，按钮需会话重载（getMessages 返回 MessageDTO.id）后才出现。严格符合验收"无 message_id 的历史消息按钮隐藏"，但客观上弱化了飞轮即时收集能力（用户最可能在刚收到回答时点 👍👎）。Dev-B 已在 issues_known 如实披露；建议后续模块在 saveMessages 返回值带 id 或本地生成临时 id 后回填 |
| 4 | minor | `test-report.md` 缺失 | AC §9 文档三件套之一未产出。按工作流惯例为 Tester 交付物，交 Tester 补齐（Reviewer 已在本报告中给出全部实测数字可直接引用） |

## 7. 结论

模块 5 个工作包（WP1 后端反馈 / WP2 前端反馈 / WP3 前端 maxlength / WP4 硬闸门阈值 / WP5 白名单防御）全部按验收标准交付：

- 红线 5 条全部通过（文件范围 / 无 commit / 533 全绿独立复跑 / 零新依赖 / 阈值 0.55 落地未回退）。
- 验收 AC §1-§8 逐项对照：feedback 表 6 字段齐全、端点校验（rating ±1 / comment ≤500 / identity 口径）完整、前端按钮三态（未评/已评/提交中）与已评态持久化正确、maxLength 生效、阈值 0.55 语义测试覆盖（0.45 直接不充分）、缺键防御测试覆盖、降级路径（500 + Toast 可重试）两端打通、前后端契约逐字段一致。
- 前端构建 PASS、全量 pytest 533 全绿（Reviewer 独立复跑），vitest 39 passed / 3 failed 经基线复核确认为预存环境问题。

无 critical / major。**verdict: approved**。Tester 待办：产出 test-report.md；可选复核：重启 AI 服务验证 init_db 自愈建表 + 真实落库冒烟。
