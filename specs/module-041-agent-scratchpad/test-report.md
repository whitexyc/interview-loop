# Test Report — Module-041: Agent 工作记忆 Scratchpad

## 测试范围

针对 `note_to_self` 工具注册与执行、`generate_answer` scratchpad 注入的单元测试。

## 测试文件

| 文件 | 新增测试 | 说明 |
|------|---------|------|
| `ai_service/tests/test_agent_tools.py` | 0 (已有 10 个) | TestNoteToSelf / TestNoteToSelfCoexistence 包含 10 个用例，覆盖工具注册、写入 scratchpad、空笔记、截断、累积、与 verify_answer 共存 |
| `ai_service/tests/test_reflector.py` | 2 | TestGenerateAnswerWithScratchpad 新增 2 个用例 |

## 新增测试用例

### test_reflector.py

| 测试方法 | 覆盖验收 | 描述 |
|----------|---------|------|
| `test_generate_answer_includes_scratchpad` | 4.1 | scratchpad 非空时 prompt 注入 `[工作笔记]` 段，包含笔记内容 |
| `test_generate_answer_no_scratchpad_zero_regression` | 4.1 | 空 scratchpad 时 prompt 不含 `[工作笔记]`，零回归 |

### test_agent_tools.py（已有，确认通过）

| 测试方法 | 覆盖验收 | 描述 |
|----------|---------|------|
| `test_note_to_self_tool_registered` | 4.1 | note_to_self 已注册，schema 含 note 必填字段 |
| `test_note_to_self_writes_to_scratchpad` | 4.1 | 工具执行后 ctx.scratchpad 追加笔记 |
| `test_note_to_self_empty_note` | 4.1 | 空内容返回提示，不写入 |
| `test_note_to_self_whitespace_only_note` | 4.1 | 纯空白返回提示，不写入 |
| `test_note_to_self_truncates_long_note` | 4.1 | 超过 500 字自动截断 |
| `test_note_to_self_multi_note_accumulates` | 4.1 | 多次调用累积多条笔记 |
| `test_generate_answer_reads_scratchpad` | 4.1 | _generate_answer 传入 scratchpad 到 reflector |
| `test_generate_answer_empty_scratchpad_zero_regression` | 4.1 | 空 scratchpad 行为不变 |
| `test_scratchpad_injection_in_reflector_generate_answer` | 4.1 | reflector.generate_answer prompt 含工作笔记段 |
| `test_scratchpad_none_zero_regression` | 4.1 | scratchpad=None 零回归 |
| `test_both_tools_registered` | 4.2 | note_to_self 与 verify_answer 共存 |
| `test_note_to_self_then_verify_answer_in_react_loop` | 4.2 | 同一循环中先后调用两者 |
| `test_verify_answer_register_unchanged` | 4.2 | verify_answer 注册不受影响 |

## 测试执行结果

### 目标文件测试

```
$ cd ai_service && python -m pytest tests/test_agent_tools.py tests/test_reflector.py -q
66 passed in 51.31s
```

### 全量回归测试

```
$ cd ai_service && python -m pytest tests/ -q
336 passed, 1 failed in 90.02s
```

唯一的失败 `test_identity.py::TestEngineRecallIdentity::test_identity_passed_to_service` 是预存问题（`top_k` 期望 3 实际 5，memory recall 参数变更导致），与 module-041 无关。

## 结论

- 新增 2 个测试用例，全部通过
- 已有 10 个 NoteToSelf 相关测试全部通过
- 全量 337 个测试中 336 通过，1 个失败的预存问题与本次变更无关
- 零回归
