# 验收标准 — Module-051: verify_answer 接入 HHEM 专职裁判

> 图例：📋 功能 / 📦 降级 / 🔌 接口 / 🧪 测试 / 📝 文档

## 1. 功能验收（WP1 裁判封装）

- [ ] 📋 `factcheck_judge.py` 存在：延迟加载 HHEM（首次调用时加载，对齐 embeddings 模式）
- [ ] 📋 加载复用 module-050 已验证路径（get_class_from_dynamic_module + safetensors + embed_tokens 展开 + HF_HUB_OFFLINE + flan-t5-base tokenizer）——单一来源（共享 loader 或注明取舍）
- [ ] 📋 `predict(docs, claims)` 批量打分，CPU 推理经 `asyncio.to_thread` 不阻塞事件循环
- [ ] 📋 模型缺失/加载失败/推理异常 → 返回 None（不抛异常）

## 2. 功能验收（WP2 verify_answer 拆分）

- [ ] 📋 `_VERIFY_PROMPT` 精简为纯拆句（输出 claim 数组，不再判 verdict/填 evidence）
- [ ] 📋 verdict 由 HHEM 判定：每 claim 对每文档打分 → max 分映射三态（≥0.7 supported / 0.3-0.7 inferred / <0.3 unsupported，阈值读配置）
- [ ] 📋 evidence = max 分对应文档号（1-based），unsupported 填 "N/A"
- [ ] 📋 返回结构不变（claims/overall_confidence/total_claims/supported/inferred/unsupported，前端零改动）
- [ ] 📋 overall_confidence 口径不变（1 - unsupported/total）

## 3. 功能验收（WP3 配置）

- [ ] 📋 config：`verify_judge_model` 默认 "hhem"（PW_ 前缀）+ `verify_hhem_threshold_high=0.7` / `verify_hhem_threshold_low=0.3`
- [ ] 📋 开关 "llm" 时完全不加载 HHEM，走旧逻辑

## 4. 降级验收

- [ ] 📦 HHEM 缺失/加载失败/推理异常 → 回退 LLM 判分（保留旧全量 prompt），行为与 module-039 一致
- [ ] 📦 LLM 拆句失败/超时 → 空 claims
- [ ] 📦 LLM 判分也失败 → 空 claims（overall_confidence=0.0）
- [ ] 📦 全量 pytest 579 全绿保持

## 5. 接口兼容

- [ ] 🔌 ChatResponse.verified_claims 结构与前端渲染零改动（claims 数组逐条渲染色标已存在）
- [ ] 🔌 verify_answer 签名与返回结构不变（调用方 engine.py / 工具 verify_answer 不感知）
- [ ] 🔌 `--skip-*` 评测脚本单侧可跑

## 6. 测试验收

- [ ] 🧪 tests/test_factcheck_judge.py：加载降级（mock 缺失路径）、批量打分（mock 分数）、三态映射边界（0.7/0.3 恰好值）、evidence 取 max 文档、verify_answer 拆分集成、降级链三层、开关 "llm" 零回归
- [ ] 🧪 python -m pytest tests/ -q — 全量 579+ 全绿（不改存量测试掩盖）

## 7. 评测验收（WP5）

- [ ] 📋 `eval/golden_factcheck.py`：50 条人工标注 claims → HHEM vs 人工 Cohen's kappa（三态 + 二值两种口径）
- [ ] 📋 eval_runs 落库 `eval_type='factcheck'`（复用 golden_retrieval 落库函数）
- [ ] 📋 `--fixture` 启发式不依赖模型；模型缺失/失败 → 记 skipped 不中断
- [ ] 📋 kappa < 0.7 → 如实标注"未达门槛"不伪造数字

## 8. 文档验收

- [ ] 📝 changelog.md / review-report.md / test-report.md（含全部实测数字）
- [ ] 📝 memory/ 三记忆文件更新（各 agent 写自己的）
- [ ] 📝 ADR-0010 状态更新（P0-② 已实施：裁判切换完成）
