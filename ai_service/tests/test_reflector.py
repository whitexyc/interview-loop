"""Module-039 证据链幻觉检测 Reflector 单元测试

覆盖（验收 §5.1）：
- verify_answer 正常返回测试（supported 文档 + 预期 claims）
- verify_answer 空文档降级测试（空 docs → 返回空 claims）
- verify_answer 异常降级测试（LLM 错误 → 返回空 claims，不抛异常）
- _parse_verification JSON 解析健壮性
- evidence 引用号越界降级

实现说明：
- 用 mock 打桩 LLMFactory.get_client，不依赖真实 LLM
- 同步用例内 asyncio.run 执行，不依赖 pytest-asyncio（沿用既有模式）
"""
import asyncio
import json
from unittest import mock

import pytest

from agent.reflector import Reflector


class TestVerifyAnswer:
    """Reflector.verify_answer 证据链验证"""

    @staticmethod
    def _sample_docs():
        return [
            {"id": 1, "title": "线程池基础", "source": "test",
             "content": "线程池核心参数包括核心线程数、最大线程数、队列容量。"},
            {"id": 2, "title": "线程池配置", "source": "test",
             "content": "最大线程数根据CPU密集型任务设置为核心数的2倍。"},
        ]

    @staticmethod
    def _valid_json_response():
        return json.dumps([
            {"claim": "线程池核心参数包括核心线程数、最大线程数、队列容量",
             "verdict": "supported", "evidence": "[1]"},
            {"claim": "最大线程数根据CPU密集型任务设置为核心数的2倍",
             "verdict": "supported", "evidence": "[2]"},
            {"claim": "建议使用无界队列避免任务丢失",
             "verdict": "unsupported", "evidence": "N/A"},
        ], ensure_ascii=False)

    def test_verify_answer_returns_claims(self):
        """正常路径：LLM 返回合法 JSON → 完整验证结果含 claims / overall_confidence"""
        async def run():
            r = Reflector()
            docs = self._sample_docs()
            client = mock.MagicMock()
            client.generate = mock.AsyncMock(return_value=self._valid_json_response())
            with mock.patch("llm.client.LLMFactory.get_client", return_value=client):
                result = await r.verify_answer(
                    "线程池核心参数包括核心线程数、最大线程数、队列容量[1]。"
                    "最大线程数根据CPU密集型任务设置[2]。建议使用无界队列。",
                    docs,
                )
            return result

        result = asyncio.run(run())
        assert result["total_claims"] == 3
        assert result["supported"] == 2
        assert result["inferred"] == 0
        assert result["unsupported"] == 1
        assert result["overall_confidence"] == pytest.approx(0.6667, abs=0.01)
        assert result["claims"][0]["verdict"] == "supported"
        assert result["claims"][0]["evidence"] == "[1]"
        assert result["claims"][2]["verdict"] == "unsupported"
        assert result["claims"][2]["evidence"] == "N/A"

    def test_verify_answer_empty_docs(self):
        """空文档降级：docs 为空 → 返回空 claims（零回归）"""
        async def run():
            r = Reflector()
            result = await r.verify_answer("任意答案", [])
            return result

        result = asyncio.run(run())
        assert result["claims"] == []
        assert result["total_claims"] == 0
        assert result["supported"] == 0
        assert result["inferred"] == 0
        assert result["unsupported"] == 0
        assert result["overall_confidence"] == 0.0

    def test_verify_answer_handles_llm_error(self):
        """LLM 调用异常 → 返回空 claims，不抛异常"""
        async def run():
            r = Reflector()
            docs = self._sample_docs()
            client = mock.MagicMock()
            client.generate = mock.AsyncMock(side_effect=RuntimeError("LLM 服务不可用"))
            with mock.patch("llm.client.LLMFactory.get_client", return_value=client):
                result = await r.verify_answer("线程池很强大[1]", docs)
            return result

        result = asyncio.run(run())
        assert result["claims"] == []
        assert result["overall_confidence"] == 0.0

    def test_verify_answer_empty_answer_text(self):
        """空答案文本 → 返回空 claims"""
        async def run():
            r = Reflector()
            docs = self._sample_docs()
            result = await r.verify_answer("", docs)
            return result

        result = asyncio.run(run())
        assert result["claims"] == []
        assert result["total_claims"] == 0

    def test_verify_answer_evidence_out_of_bounds(self):
        """evidence 引用号越界 → 对应的 claim verdict 降级为 unsupported"""
        async def run():
            r = Reflector()
            docs = self._sample_docs()  # 只有 2 篇文档
            # LLM 返回的证据引用号 [5] 超出 docs 数量 → 应为 unsupported
            response = json.dumps([
                {"claim": "c1", "verdict": "supported", "evidence": "[1]"},
                {"claim": "c2", "verdict": "supported", "evidence": "[5]"},
            ], ensure_ascii=False)
            client = mock.MagicMock()
            client.generate = mock.AsyncMock(return_value=response)
            with mock.patch("llm.client.LLMFactory.get_client", return_value=client):
                result = await r.verify_answer("a[1] b[5]", docs)
            return result

        result = asyncio.run(run())
        assert result["total_claims"] == 2
        # c1 保持 supported；c2 被降级为 unsupported（证据号越界）
        assert result["claims"][0]["verdict"] == "supported"
        assert result["claims"][1]["verdict"] == "unsupported"
        assert result["claims"][1]["evidence"] == "N/A"
        assert result["supported"] == 1
        assert result["unsupported"] == 1

    def test_verify_answer_all_supported(self):
        """全部 supported 的正常答案 → overall_confidence == 1.0"""
        async def run():
            r = Reflector()
            docs = self._sample_docs()
            response = json.dumps([
                {"claim": "全部正确", "verdict": "supported", "evidence": "[1]"},
            ], ensure_ascii=False)
            client = mock.MagicMock()
            client.generate = mock.AsyncMock(return_value=response)
            with mock.patch("llm.client.LLMFactory.get_client", return_value=client):
                result = await r.verify_answer("全部正确[1]", docs)
            return result

        result = asyncio.run(run())
        assert result["supported"] == 1
        assert result["unsupported"] == 0
        assert result["overall_confidence"] == 1.0


class TestGenerateAnswerWithScratchpad:
    """module-041: generate_answer 读取 scratchpad 工作笔记

    覆盖验收 4.1:
    - scratchpad 非空时 generate_answer prompt 注入工作笔记段
    - 空 scratchpad 零回归（prompt 不含工作笔记段）
    """

    @staticmethod
    def _sample_docs():
        return [
            {"id": 1, "title": "线程池基础", "source": "test",
             "content": "线程池核心参数包括核心线程数、最大线程数、队列容量。"},
        ]

    def test_generate_answer_includes_scratchpad(self):
        """scratchpad 非空时 generate_answer prompt 注入工作笔记段"""
        async def run():
            r = Reflector()
            docs = self._sample_docs()
            client = mock.MagicMock()
            client.generate = mock.AsyncMock(return_value="含笔记的答案")
            with mock.patch("llm.client.LLMFactory.get_client", return_value=client):
                result = await r.generate_answer(
                    "测试问题", docs,
                    scratchpad=["发现1", "发现2"],
                )
                prompt_arg = client.generate.call_args[0][0]
            return result, prompt_arg

        result, prompt = asyncio.run(run())
        assert result == "含笔记的答案"
        assert "[工作笔记" in prompt
        assert "发现1" in prompt
        assert "发现2" in prompt

    def test_generate_answer_no_scratchpad_zero_regression(self):
        """空 scratchpad 时 generate_answer 零回归（prompt 不含工作笔记段）"""
        async def run():
            r = Reflector()
            docs = self._sample_docs()
            client = mock.MagicMock()
            client.generate = mock.AsyncMock(return_value="正常答案")
            with mock.patch("llm.client.LLMFactory.get_client", return_value=client):
                result = await r.generate_answer("测试问题", docs)
                prompt_arg = client.generate.call_args[0][0]
            return result, prompt_arg

        result, prompt = asyncio.run(run())
        assert result == "正常答案"
        assert "[工作笔记" not in prompt


class TestParseVerification:
    """_parse_verification JSON 解析健壮性"""

    def test_valid_json_array(self):
        """合法 JSON 数组 → 正确解析为 claims"""
        response = '[{"claim": "c1", "verdict": "supported", "evidence": "[1]"}]'
        claims = Reflector._parse_verification(response)
        assert len(claims) == 1
        assert claims[0]["claim"] == "c1"
        assert claims[0]["verdict"] == "supported"

    def test_markdown_wrapped_json(self):
        """LLM 在 markdown 代码块中包裹 JSON → 成功解析"""
        response = '```json\n[{"claim": "c1", "verdict": "inferred", "evidence": "[1]"}]\n```'
        claims = Reflector._parse_verification(response)
        assert len(claims) == 1
        assert claims[0]["verdict"] == "inferred"

    def test_extra_text_before_json(self):
        """LLM 在 JSON 前加解释文字 → 仍成功提取"""
        response = '以下是验证结果：\n[{"claim": "c1", "verdict": "supported", "evidence": "[1]"}]'
        claims = Reflector._parse_verification(response)
        assert len(claims) == 1
        assert claims[0]["verdict"] == "supported"

    def test_invalid_json_returns_empty(self):
        """完全无法解析的响应 → 返回空列表"""
        claims = Reflector._parse_verification("纯文本无JSON结构！")
        assert claims == []

    def test_empty_claims_filtered_out(self):
        """JSON 中空 claim 条目被过滤"""
        response = '[{"claim": "", "verdict": "supported", "evidence": "[1]"}, {"claim": "有效", "verdict": "inferred", "evidence": "[2]"}]'
        claims = Reflector._parse_verification(response)
        assert len(claims) == 1
        assert claims[0]["claim"] == "有效"

    def test_missing_verdict_defaults_to_unsupported(self):
        """缺少 verdict 字段 → 默认 unsupported"""
        response = '[{"claim": "c1", "evidence": "[1]"}]'
        claims = Reflector._parse_verification(response)
        assert len(claims) == 1
        assert claims[0]["verdict"] == "unsupported"

    def test_missing_evidence_defaults_to_na(self):
        """缺少 evidence 字段 → 默认 N/A"""
        response = '[{"claim": "c1", "verdict": "supported"}]'
        claims = Reflector._parse_verification(response)
        assert len(claims) == 1
        assert claims[0]["evidence"] == "N/A"
