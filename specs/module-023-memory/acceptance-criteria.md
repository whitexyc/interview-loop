# 验收标准 — Module-023: 长期记忆

> 本文件由 **Planner** 在输出开发计划时同步编写，由 **Tester** 在测试阶段执行验收。
> 所有检查项使用 `- [ ]` 复选框格式，验收时勾选。

---

## 验收元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-023 |
| 模块名称 | 长期记忆（跨会话记忆沉淀） |
| 关联 plan.md | `specs/module-023-memory/plan.md` |
| 验收日期 | 2026-08-01 |
| 验收人 | Tester |
| 验收版本 | 0.23.0-module-023 |

---

## 1. 功能验收

### 1.1 核心功能验收

- [x] 📋 保存记忆入库 — 验证方式：POST /ai/memory/save 后 documents 表有 source='memory:...' 记录
- [x] 📋 检索记忆 — 验证方式：POST /ai/memory/recall 返回相关记忆
- [x] 📋 记忆向量化 — 验证方式：记忆文档有 1024 维 embedding
- [x] 📋 按 IP 隔离 — 验证方式：不同 ip 检索互不干扰
- [x] 📋 无记忆时零回归 — 验证方式：无记忆时 chat 行为不变

### 1.2 边界条件验收

- [x] 🔲 空 content 保存：返回错误
- [x] 🔲 空 ip：默认 'unknown'
- [x] 🔲 无匹配记忆：recall 返回空列表
- [x] 🔲 检索 query 为空：返回空

### 1.3 异常场景验收

- [x] ⚡ embedding 不可用：保存失败返回错误码（不崩）
- [x] ⚡ 检索失败：返回空记忆，回答照常
- [x] ⚡ 数据库不可用：返回错误

---

## 2. 接口验收

### 2.1 保存记忆

- [x] 📦 POST /ai/memory/save 请求 {content, ip}
- [x] 📦 返回 {code, data:{id, status}}
- [x] 📦 content 为空返回错误

### 2.2 检索记忆

- [x] 📦 POST /ai/memory/recall 请求 {query, ip}
- [x] 📦 返回 {code, data:{memories:[{content, score}]}}
- [x] 📦 memories 按 score 降序

### 2.3 记忆存储

- [x] 📦 documents 表 source='memory:<ip>'
- [x] 📦 记忆文档有 embedding（1024 维）
- [x] 📦 检索只查记忆（source 过滤），不污染知识库检索

---

## 3. 代码质量验收

### 3.1 注释覆盖率

- [x] 💻 所有 public 方法有 Docstring
- [x] 💻 记忆注入逻辑有行内注释

### 3.2 命名规范

- [x] 💻 函数/变量符合 snake_case
- [x] 💻 无无意义命名

### 3.3 代码长度

- [x] 💻 单个方法 ≤ 50 行
- [x] 💻 本模块新增代码 ≤ 300 行（plan.md 已申请调整）

### 3.4 编译检查

- [x] 💻 Python 语法通过
- [x] 💻 无未使用 import

---

## 4. 测试验收

### 4.1 单元测试

- [x] 🧪 MemoryService save/recall 单测
- [x] 🧪 source 过滤逻辑

### 4.2 集成测试

- [x] 🧪 真实保存记忆到 documents
- [x] 🧪 真实检索记忆返回相关
- [x] 🧪 按 IP 隔离

### 4.3 回归测试

- [x] 🧪 `python -m pytest ai_service/tests/ -x` 无新增失败
- [x] 🧪 chat 无记忆时行为不变

### 4.4 测试命令

```bash
cd ai_service
# 保存记忆（需服务运行）
curl -X POST http://localhost:8000/ai/memory/save \
  -H "Content-Type: application/json" \
  -d '{"content": "用户偏好简洁回答", "ip": "192.168.1.1"}'

# 检索记忆
curl -X POST http://localhost:8000/ai/memory/recall \
  -H "Content-Type: application/json" \
  -d '{"query": "回答风格", "ip": "192.168.1.1"}'

# 回归
python -m pytest ai_service/tests/ -x
```

**预期输出**：
```
保存: {"code":0, "data":{"id":1, "status":"saved"}}
检索: {"code":0, "data":{"memories":[{"content":"用户偏好简洁回答","score":0.85}]}}
回归: 0 failed
```

---

## 5. 文档验收

### 5.1 变更记录

- [x] 📝 changelog.md 已更新
- [x] 📝 包含版本号/日期/变更内容/变更人

### 5.2 设计说明

- [x] 📝 存储方案（复用 documents + source 隔离）记录在 plan.md
- [x] 📝 注入方案（生成前 recall）记录在 plan.md

---

## 验收执行结果

### 分项统计

| 验收类别 | 总项数 | 通过 | 失败 | 未执行 |
|----------|--------|------|------|--------|
| 功能验收 | 12 | 12 | 0 | 0 |
| 接口验收 | 9 | 9 | 0 | 0 |
| 代码质量验收 | 8 | 8 | 0 | 0 |
| 测试验收 | 7 | 7 | 0 | 0 |
| 文档验收 | 4 | 4 | 0 | 0 |
| **合计** | **40** | **40** | **0** | **0** |

### 失败详情

无。上轮 Tester 阻塞项（`_next_title` date=varchar 类型不匹配致真实 save 崩溃）已由 Developer v4 修复（`save` 改传 `date.today()` date 对象），本轮真实 DB + HTTP 复测通过。其余建议项（chat_stream 记忆注入 / message 键统一）均为计划范围决策，见 changelog 记录。

### 验收结论

- 审查人: Reviewer（第 3 轮通过）
- 测试人: Tester
- 验收时间: 2026-08-01
- 结论:
  - [x] ✅ **通过**
  - [ ] ❌ **不通过**
  - [ ] ⚠️ **有条件通过**
- 备注: 40/40 验收项通过。单元测试 29/29 通过；全量回归 83 passed / 2 既有环境失败（test_engine async 缺 pytest-asyncio，非本模块回归）；真实 DB 冒烟（save → recall 命中 → IP 隔离 → 1024 维向量 → 序号递增 → 清理）与 HTTP 端点验证（save/recall/空 content/空 query/通配符 ip 不绕过）全部通过。详见 `test-report.md`。

---

> **下一步**：
> - 通过：更新 `memory/project-context.md`，模块标记 ✅
> - 不通过：通知 Developer 修复后重新验收
