# Module-048 全量回归测试报告 — Tester

> Tester | 2026-08-10 | 独立复跑，非引用 Dev-A/Dev-B 自测数据

## 1. 结论

**verdict: PASS** — 后端 0 失败，红线全部通过，前端构建通过。

## 2. 后端全量回归（必查项）

```
python -m pytest tests/ -q（ai_service）
→ 533 passed, 0 failed, 5 warnings in 121.56s (0:02:01)
```

- 基线 525（module-047 收尾）+ 新增 8 = 533，零回归。
- 5 warnings 为预存（test_cache setex 弃用告警 + test_memory/test_memory 两处 SQLAlchemy 连接池告警），与 module-048 改动无关。

### 2.1 新增测试验证

| 文件 | 新增用例 | 验证点 |
|------|----------|--------|
| `tests/test_feedback.py`（6 用例） | 落库成功（字段完整 + 匿名 identity=client_ip） | AC §1：200 {"status":"ok"} + Feedback 记录 message_id/rating/comment/identity 完整 |
| | rating=-1 + comment 缺省 None | AC §1：±1 双侧可落库 |
| | rating=0 / 2 → 422 | AC §1：非法值校验 |
| | comment 501 字符 → 422 | AC §1：comment ≤500 |
| | JWT user_id 优先 client_ip | AC §1：identity 口径与中间件一致 |
| | 落库失败 → 500 "反馈保存失败" | AC §6：降级，前端 Toast 可重试 |
| `tests/test_reflector.py`（+1） | `test_gate_threshold_0_55_catches_0_45`：abs_cosine=0.45 → 直接判不充分 + 零 LLM 调用，reason 含 "0.55" | AC §4 场景 4：旧阈值 0.4 会漏判进 LLM；0.25 用例、0.7 ≥ 0.55 达标用例同步适配 |
| `tests/test_intent_validation.py`（+1） | `test_classifier_missing_knowledge_key_no_keyerror`：probs 缺 knowledge 键 + bogus 最高分 → intent=knowledge、confidence=0.0、LLM 打桩断言零调用 | AC §5 场景 5：probs.get 缺键回退 |

## 3. 代码级抽查（Tester 独立核实）

- **阈值 0.55（红线 5）**：`ai_service/src/config.py:99` `sufficiency_gate_threshold: float = 0.55`，`model_config` env_prefix="PW_"（L104，PW_ 前缀生效）；`ai_service/agent/reflector.py:195` `gate = settings.sufficiency_gate_threshold` — 读配置，旧硬编码 `_SUFFICIENCY_MIN_ABS_COSINE = 0.4` 常量已删除；功能代码无 0.4 残留（仅 reflector.py L162 方法 docstring 一处注释级旧值，Reviewer minor #1，无功能影响，闸门实测读 0.55）。
- **白名单防御（WP5）**：`ai_service/agent/router.py:176` `confidence = probs.get(intent, 0.0)`。
- **接口契约**：`POST /ai/feedback`（message_id int / rating ∈{1,-1} / comment Optional ≤500）与前端 `types/rag.ts::FeedbackRequest` 对齐；成功 200 / 校验 422 / 落库失败 500。

## 4. 前端验证（必查项）

### 4.1 构建

```
npm run build（frontend）
→ tsc && vite build PASS — 3102 modules transformed, built in 18.09s
```

### 4.2 单测（vitest）

```
npx vitest run → 39 passed / 3 failed（42 total）
```

- module-048 新增 8 用例**全部通过**：`ChatMessage.test.tsx` 7 用例（隐藏条件/展示/用户消息不展示/👍rating=1 已评态/👎rating=-1/不重复提交/失败可重试）+ `ChatPage.test.tsx` maxLength=2000 属性断言。
- 3 failed 为预存环境问题，**非本模块引入**——Tester 用临时 HEAD 基线 worktree（git worktree + node_modules junction）独立双跑复核：基线同样 3 项失败（31 passed / 3 failed，共 34），失败项逐名一致：
  1. ChatPage > should show user message after sending
  2. ChatPage > should render pipeline panel and upload section
  3. ChatPage > should show error alert when chat API fails
  （根因：Node 环境流式 mock 时序，发送后用户消息未及时渲染。）

### 4.3 依赖红线（红线 4）

- `frontend/package.json` 零 diff（git diff HEAD 为空），👍👎 用既有依赖 `@ant-design/icons` 的 LikeOutlined/DislikeOutlined（锁定版 5.6.1 无 ThumbUp/Down），零新依赖。

## 5. 红线与仓库状态核查

| 红线 | 核查结果 |
|------|----------|
| ① 只动工作包文件 | git diff HEAD 15 文件，后端 10 + 前端 4 测试/源码 + specs/module-033 changelog（经 diff 核实为前任 Reviewer 追加，非本模块改动）— 全在 plan 3.1 WP 清单内 |
| ② 无 git commit | HEAD 仍为 a6bfaea（module-047），零新提交 |
| ③ 全量 pytest 全绿 | 533 passed / 0 failed（本报告 §2） |
| ④ 前端零新依赖 | package.json 零 diff（§4.3） |
| ⑤ 阈值 0.55 不回改 | config.py:99 = 0.55 + reflector 读配置（§3） |

## 6. 已知问题（不阻塞，见 review-report.md §3 minor）

1. reflector.py L162 check_sufficiency 方法 docstring 残留 "top-1 abs_cosine < 0.4" 描述（纯文档，实际闸门读配置 0.55）。
2. eval/threshold_scan.py L9 docstring 引用已删除常量（该文件不在本模块工作包，运行时仅用自身 EMPIRICAL_GATE=0.4 做历史对比基线）。
3. 流式新生成消息无 message_id（Java saveMessages 返回 Void），需会话重载后才可评——符合验收降级项，飞轮即时收集能力弱化（后续模块改进）。

## 7. 交付物核对（AC §9）

- [x] changelog.md（Dev-A/Dev-B 已交付 + 本报告 §8 追加 Tester 记录）
- [x] review-report.md（Reviewer 已交付）
- [x] test-report.md（本文件）
- [x] 记忆文件（rag-architecture.md / rag-agent-roadmap.md / MEMORY.md 均已更新 module-048 条目）
- [x] 飞轮数据说明（changelog.md 已知边界：feedback 表是层 4 intent/充分性分类器重训数据源，本模块只落库不消费）

## 8. Tester 执行记录

- 全量 pytest：2026-08-10 独立复跑 533 passed / 0 failed（121.56s）。
- 前端 build：tsc + vite PASS（3102 modules，18.09s）。
- vitest：39/42 过，3 失败经 HEAD 基线双跑确认为预存环境问题。
- 阈值/配置/白名单防御逐项源码级抽查通过（§3）。
