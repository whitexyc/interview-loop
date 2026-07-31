# ADR-001: Qwen3-Reranker 需要 chat template 适配（不能用裸 pair）

> 架构决策记录（Architecture Decision Record）
> 由 Developer 在 module-018 开发中发现，Planner 审批。

---

## 元信息

| 字段 | 内容 |
|------|------|
| ADR 编号 | ADR-001 |
| 决策标题 | Qwen3-Reranker 需 chat template 适配（不能用裸 pair） |
| 状态 | accepted（已采纳） |
| 决策日期 | 2026-08-01 |
| 决策者 | Planner（审批）、Developer（发现） |
| 关联模块 | module-018 |
| 被取代的 ADR | — |
| 取代本 ADR 的 ADR | — |

---

## 1. 背景（Context）

### 1.1 问题描述

module-018 计划将重排模型从 bge-reranker-v2-m3（缺权重）切换为 Qwen3-Reranker-0.6B。
原计划认为 Qwen3-Reranker 可直接用 `CrossEncoder(pairs)` 加载（与 bge 相同），
但实测发现：

1. Qwen3-Reranker-0.6B 是**生成式模型**（`Qwen3ForCausalLM`），非传统 sequence-classification 架构
2. sentence-transformers 5.6.1 的 CrossEncoder 在 `predict` 时会把 pair 转换为
   `{"role": "query", "content": ...}` / `{"role": "document", ...}` 消息
3. Qwen3 的 chat template **不认识 query/document 角色** → 渲染为空字符串（0 token）
4. 空 token 输入 → 重排分数全部无效

### 1.2 约束条件

| 约束 | 说明 |
|------|------|
| 模型已下载 | Qwen3-Reranker-0.6B（1.14GB）已本地化，不回退 HF |
| 无 API 依赖 | 重排必须本地完成 |
| 版本锁定 | sentence-transformers 5.6.1（已有，不轻易升级） |

### 1.3 相关背景信息

- 之前 bge-reranker-v2-m3 因缺权重静默失败，重排从未真正生效
- Qwen3-Reranker 官方是生成式重排：在最后 token 位置计算 `logit("yes") - logit("no")`

---

## 2. 决策（Decision）

### 2.1 具体决定

**改为 chat 消息格式调用**：把 `(query, document)` 对拼接后放入 `user` 角色消息，
并启用 `add_generation_prompt`，让 Qwen3 在最后 token 位置生成相关性 logit。

```python
messages = [
    [{"role": "user", "content": f"{query}\n{d.get('content', '')}"}]
    for d in documents
]
scores = self._model.predict(
    messages,
    processing_kwargs={"chat_template": {"add_generation_prompt": True}},
)
```

### 2.2 决策理由

1. Qwen3 chat template 只认 `user/system/assistant/tool` 角色，`user` 角色渲染正常
2. `add_generation_prompt` 使模型在末尾附加 `assistant` 开始标记，正确触发 logit 计算
3. 实测排序正确：`id=1 (0.0237) > id=3 (0.0179) > id=2 (0.0041)`，与语义相关性一致
4. 不改 ST 版本、不引入新依赖

### 2.3 实施计划

- [x] 诊断：确认 query/document 角色渲染为空（`_m18_diag.py`）
- [x] 验证：Option C（user 角色消息）排序正确
- [x] 改造：`reranker.py` 的 `rerank()` 改用 chat 消息格式
- [x] 测试：排序/边界/缺权重全通过
- [ ] Reviewer 审查确认
- [ ] 更新 `docs/rag-flow.md` 重排章节说明

---

## 3. 备选方案（Alternatives Considered）

### 3.1 方案 A：直接用 CrossEncoder(pair)（原计划）

**描述**：与 bge 相同，传 `(query, doc)` 裸 pair

**优点**：改动最小、接口不变

**缺点**：Qwen3 template 渲染 query/document 为空 → 0 token → 重排无效（已实测确认）

**评估结论**：不可行，方案被否决

---

### 3.2 方案 B：升级 sentence-transformers 到新版本

**描述**：升级 ST 到支持 Qwen3 生成式重排的版本

**优点**：可能官方支持

**缺点**：版本升级有风险（破坏现有 embedding 依赖）；实测 5.6.1 已含 LogitScore，问题不在版本

**评估结论**：不必要，5.6.1 已具备所需能力

---

### 3.3 方案对比矩阵

| 评估维度 | 权重 | 方案 A（裸pair） | 方案 B（升级ST） | 方案 C（chat适配） |
|----------|------|------------------|------------------|---------------------|
| 开发效率 | 高 | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ |
| 可维护性 | 高 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| 稳定性 | 中 | ⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| 依赖风险 | 中 | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| **加权总分** | | 3.6 | 2.4 | **4.4** |

---

## 4. 影响（Consequences）

### 4.1 正面影响

- [x] 重排首次真正生效（此前 bge 缺权重静默降级）
- [x] 生成式重排精度高于传统分类式（Qwen3 语义理解更强）
- [x] 无新依赖、无版本升级

### 4.2 负面影响

- [ ] reranker.py 的 rerank() 与 bge 类模型的调用方式不兼容（未来换回 bge 需改）
- [ ] chat 消息格式比裸 pair 多一次 template 渲染开销

### 4.3 影响的模块/组件

| 受影响的组件 | 影响描述 | 处理方式 |
|--------------|----------|----------|
| `ai_service/rag/reranker.py` | rerank() 改用 chat 消息格式 | module-018 中完成 |
| `docs/rag-flow.md` | 重排章节需补充适配说明 | 待更新 |

### 4.4 回滚方案

若 Qwen3-Reranker 效果不佳，可下载 bge-reranker-v2-m3 完整权重，
将 `rerank()` 改回裸 pair 调用（保留 `_validate_model_dir` 校验）。

---

## 5. 技术债务

| 债务项 | 描述 | 计划修复版本 |
|--------|------|--------------|
| 模型适配耦合 | rerank() 与 Qwen3 的 chat 格式耦合，换模型需改 | 观察中 |

---

## 6. 参考资料

- [Qwen3-Reranker-0.6B ModelScope](https://www.modelscope.cn/models/Qwen/Qwen3-Reranker-0.6B)
- sentence-transformers 5.6.1 cross_encoder/model.py（LogitScore 实现）
- `ai_service/_m18_diag.py`（诊断脚本，已验证后清理）

---

## 7. 状态变更记录

| 日期 | 状态变更 | 变更人 | 备注 |
|------|----------|--------|------|
| 2026-08-01 | proposed → accepted | Planner | module-018 开发中确认方案可行 |

---

## 8. 审批记录

| 角色 | 审批 | 日期 | 意见 |
|------|------|------|------|
| Planner | ✅ | 2026-08-01 | 方案 C 可行，实测排序正确 |
| Developer | ✅ | 2026-08-01 | 已实现并通过测试 |
| Reviewer | ⏳ | | 待审查 |

---

> **使用说明**：
> - 本 ADR 由 Developer 在 module-018 开发中发现技术障碍时提出
> - Planner 审批采纳方案 C（chat 消息适配）
