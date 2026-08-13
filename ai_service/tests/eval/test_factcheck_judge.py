"""Module-051 HHEM 专职裁判单元测试（factcheck_judge + verify_answer 拆分 + golden_factcheck）

覆盖（验收 §6 + WP1-WP5）：
- HHEMJudge：延迟加载、批量打分、推理/加载异常 → None、空输入、失败不重试
- hhem_loader：模型缺失报错指出路径
- _judge_by_hhem：三态映射（含 0.7/0.3 恰好值边界）、evidence 取 max 文档号、
  HHEM 不可用 → None、分数数量异常 → None、旧格式 claims 兼容（不重复判定）
- verify_answer 集成：HHEM 主路径（AC 场景 1）、降级链三层（HHEM 失败→LLM→空 claims）、
  开关 "llm" 零回归（AC 场景 3）、拆句失败、返回结构兼容
- _parse_claims：字符串数组 / markdown / dict 项 / 旧格式保留 / 非法 / 空白过滤
- golden_factcheck：数据集结构（50 条三态）、启发式、kappa 两种口径、run_eval、
  eval_runs 落库契约（eval_type='factcheck'）

实现说明：
- 全部 mock 模型，不加载真实 HHEM（模型加载留给 golden_factcheck 真实模式冒烟）
- 与既有模式一致：mock 打桩 LLMFactory.get_client / hhem_judge.predict，
  asyncio.run 执行，不依赖 pytest-asyncio / 数据库 / LLM
"""
import asyncio
import json
import time
from unittest import mock

import pytest

from agent.reflector import Reflector
from eval.golden import golden_factcheck
from rag.retrieval.factcheck_judge import HHEMJudge
from rag.retrieval.hhem_loader import load_hhem_model


class TestHHEMJudge:
    """HHEMJudge：延迟加载 + 批量打分 + 降级 None（不加载真实模型）"""

    @staticmethod
    def _fake_model(scores=None, exc=None):
        model = mock.MagicMock()
        if exc is not None:
            model.predict = mock.MagicMock(side_effect=exc)
        else:
            model.predict = mock.MagicMock(return_value=scores or [0.9, 0.1])
        return model

    def test_predict_batch_scores_and_lazy_load(self):
        """批量打分：首次调用才加载模型（延迟加载），返回 float 数组"""
        async def run():
            judge = HHEMJudge()
            with mock.patch("rag.retrieval.hhem_loader.load_hhem_model",
                            return_value=self._fake_model([0.9, 0.1])) as mock_load:
                scores = await judge.predict(["d1", "d2"], ["c1", "c2"])
            return scores, mock_load

        scores, mock_load = asyncio.run(run())
        assert scores == [0.9, 0.1]
        mock_load.assert_called_once()  # 首次调用才加载（对齐 embeddings 延迟加载模式）

    def test_predict_returns_none_on_inference_error(self):
        """推理异常 → 返回 None（不抛异常，上层降级 LLM）"""
        async def run():
            judge = HHEMJudge()
            with mock.patch("rag.retrieval.hhem_loader.load_hhem_model",
                            return_value=self._fake_model(exc=RuntimeError("推理失败"))):
                scores = await judge.predict(["d1"], ["c1"])
            return scores

        assert asyncio.run(run()) is None

    def test_predict_returns_none_on_timeout(self):
        """推理超时（wait_for 触发）→ 返回 None（降级 LLM，不抛异常）
        （minor#1：交叉打分 5×5≈9s 可超时，HHEM hang 时不无限阻塞；
        测试把 _PREDICT_TIMEOUT 压到 0.01s，真实走 wait_for 超时路径）"""
        def _slow_predict_sync(docs, claims):
            time.sleep(0.2)  # 模拟 HHEM 推理 hang（远超测试用 0.01s 超时）
            return [0.9]

        async def run():
            judge = HHEMJudge()
            judge._predict_sync = _slow_predict_sync
            with mock.patch("rag.retrieval.factcheck_judge._PREDICT_TIMEOUT", 0.01):
                t0 = time.monotonic()
                scores = await judge.predict(["d1"], ["c1"])
                elapsed = time.monotonic() - t0
            return scores, elapsed

        scores, elapsed = asyncio.run(run())
        assert scores is None
        assert elapsed < 0.15  # 未等 0.2s 慢推理完成即超时返回（不无限阻塞）

    def test_predict_returns_none_on_load_failure_no_retry(self):
        """加载失败 → 返回 None；失败后不再重试（避免每请求重试 438MB 加载）"""
        async def run():
            judge = HHEMJudge()
            with mock.patch("rag.retrieval.hhem_loader.load_hhem_model",
                            side_effect=FileNotFoundError("模型缺失")) as mock_load:
                first = await judge.predict(["d1"], ["c1"])
                second = await judge.predict(["d1"], ["c1"])
            return first, second, mock_load

        first, second, mock_load = asyncio.run(run())
        assert first is None
        assert second is None
        mock_load.assert_called_once()  # 只尝试加载一次，失败后短路

    def test_empty_input_returns_none_without_loading(self):
        """空 docs/claims → None，且不触发模型加载"""
        async def run():
            judge = HHEMJudge()
            with mock.patch("rag.retrieval.hhem_loader.load_hhem_model") as mock_load:
                a = await judge.predict([], ["c1"])
                b = await judge.predict(["d1"], [])
            return a, b, mock_load

        a, b, mock_load = asyncio.run(run())
        assert a is None and b is None
        mock_load.assert_not_called()


class TestHhemLoader:
    """共享加载器（module-050 已验证路径，单一来源）"""

    def test_missing_files_raise_with_path(self, tmp_path):
        """模型目录缺失/不完整 → 报错指出缺失路径（不静默通过）"""
        with pytest.raises(FileNotFoundError) as ei:
            load_hhem_model(str(tmp_path))
        assert "model.safetensors" in str(ei.value)
        assert str(tmp_path) in str(ei.value)


class TestJudgeByHhem:
    """Reflector._judge_by_hhem：三态映射 + evidence 取 max 文档 + 降级 None"""

    @staticmethod
    def _docs():
        return [
            {"id": 1, "title": "文档一", "content": "文档一内容"},
            {"id": 2, "title": "文档二", "content": "文档二内容"},
        ]

    def test_three_state_mapping_and_evidence(self):
        """AC 场景 1：2 文档 × 3 claims——c1 max 0.85→supported[1]、
        c2 max 0.45→inferred[2]、c3 max 0.15→unsupported N/A"""
        scores = [0.85, 0.30, 0.20, 0.45, 0.15, 0.10]
        async def run():
            r = Reflector()
            claims = [{"claim": "c1"}, {"claim": "c2"}, {"claim": "c3"}]
            with mock.patch("rag.retrieval.factcheck_judge.hhem_judge.predict",
                            new=mock.AsyncMock(return_value=scores)):
                judged = await r._judge_by_hhem(claims, self._docs())
            return judged

        judged = asyncio.run(run())
        assert judged[0]["verdict"] == "supported"
        assert judged[0]["evidence"] == "[1]"   # max 分对应文档号（1-based）
        assert judged[1]["verdict"] == "inferred"
        assert judged[1]["evidence"] == "[2]"
        assert judged[2]["verdict"] == "unsupported"
        assert judged[2]["evidence"] == "N/A"
        assert judged[0]["claim"] == "c1"       # 原 claim 文本保留

    def test_boundary_values_0_7_and_0_3(self):
        """三态映射边界：恰好 0.7 → supported；恰好 0.3 → inferred"""
        scores = [0.7, 0.2, 0.3, 0.1]
        async def run():
            r = Reflector()
            claims = [{"claim": "边界高"}, {"claim": "边界低"}]
            with mock.patch("rag.retrieval.factcheck_judge.hhem_judge.predict",
                            new=mock.AsyncMock(return_value=scores)):
                judged = await r._judge_by_hhem(claims, self._docs())
            return judged

        judged = asyncio.run(run())
        assert judged[0]["verdict"] == "supported"  # 0.7 恰好 ≥ high
        assert judged[1]["verdict"] == "inferred"   # 0.3 恰好 ≥ low 且 < high

    def test_returns_none_when_hhem_unavailable(self):
        """HHEM 不可用（predict 返回 None）→ 返回 None，由上层降级 LLM"""
        async def run():
            r = Reflector()
            with mock.patch("rag.retrieval.factcheck_judge.hhem_judge.predict",
                            new=mock.AsyncMock(return_value=None)):
                judged = await r._judge_by_hhem([{"claim": "c1"}], self._docs())
            return judged

        assert asyncio.run(run()) is None

    def test_scores_length_mismatch_returns_none(self):
        """HHEM 返回分数数量异常 → 返回 None（降级 LLM，不静默错判）"""
        async def run():
            r = Reflector()
            with mock.patch("rag.retrieval.factcheck_judge.hhem_judge.predict",
                            new=mock.AsyncMock(return_value=[0.5])):
                judged = await r._judge_by_hhem([{"claim": "c1"}], self._docs())
            return judged

        assert asyncio.run(run()) is None

    def test_legacy_claims_with_verdict_skip_hhem(self):
        """旧格式兼容：claims 已带 verdict（LLM 未听新 prompt）→ 直接采用，HHEM 零调用
        （module-039 存量语义，防双重判定）"""
        legacy = [{"claim": "c1", "verdict": "supported", "evidence": "[1]"}]
        async def run():
            r = Reflector()
            with mock.patch("rag.retrieval.factcheck_judge.hhem_judge.predict") as mock_pred:
                judged = await r._judge_by_hhem(legacy, self._docs())
            return judged, mock_pred

        judged, mock_pred = asyncio.run(run())
        assert judged == legacy
        mock_pred.assert_not_called()

    def test_docs_capped_to_top_two(self):
        """module-055 交叉对数上限：每 claim 只打最相关 2 篇文档（按传入顺序）

        4 docs × 2 claims → predict 收到 2×2=4 对（E2E 实测 15 对贴近超时
        致 verified_claims=0；上限后典型 10 对，冷启动 ≈6s < 20s 预算 3 倍余量）。
        """
        docs = [
            {"id": 1, "title": "d1", "content": "文档一内容"},
            {"id": 2, "title": "d2", "content": "文档二内容"},
            {"id": 3, "title": "d3", "content": "文档三内容"},
            {"id": 4, "title": "d4", "content": "文档四内容"},
        ]
        async def run():
            r = Reflector()
            with mock.patch("rag.retrieval.factcheck_judge.hhem_judge.predict",
                            new=mock.AsyncMock(return_value=[0.9, 0.1, 0.1, 0.9])) as mock_pred:
                judged = await r._judge_by_hhem([{"claim": "c1"}, {"claim": "c2"}], docs)
            return judged, mock_pred

        judged, mock_pred = asyncio.run(run())
        assert len(judged) == 2
        # 只传前 2 篇文档内容（最相关）；预测对 = 2 claims × 2 docs
        args = mock_pred.await_args[0]
        assert args[0] == ["文档一内容", "文档二内容", "文档一内容", "文档二内容"]
        assert len(args[1]) == 4
        # evidence 引用号只可能指向 1-2（封顶文档内）
        for c in judged:
            assert c["evidence"] in ("[1]", "[2]", "N/A")

    def test_claims_capped_at_max(self):
        """module-055 上限：超长答案拆句（10 claims）→ 只判前 _MAX_HHEM_CLAIMS 条"""
        from agent.reflector import _MAX_HHEM_CLAIMS, _MAX_HHEM_DOCS
        assert _MAX_HHEM_CLAIMS == 8
        assert _MAX_HHEM_DOCS == 2

        claims = [{"claim": f"c{i}"} for i in range(10)]
        scores = [0.9, 0.1] * _MAX_HHEM_CLAIMS  # 8 claims × 2 docs
        async def run():
            r = Reflector()
            with mock.patch("rag.retrieval.factcheck_judge.hhem_judge.predict",
                            new=mock.AsyncMock(return_value=scores)) as mock_pred:
                judged = await r._judge_by_hhem(claims, self._docs())
            return judged, mock_pred

        judged, mock_pred = asyncio.run(run())
        assert len(judged) == _MAX_HHEM_CLAIMS  # 尾部 2 条截断
        assert judged[0]["claim"] == "c0"
        assert mock_pred.await_args[0][1] == ["c0", "c0", "c1", "c1", "c2", "c2",
                                              "c3", "c3", "c4", "c4", "c5", "c5",
                                              "c6", "c6", "c7", "c7"]

    def test_doc_content_truncated_for_hhem(self):
        """module-055：父块全文截断（超 HHEM 512 token 上限 + 提速）

        实测：6 对全文 9.3s（含 585 token 溢出对）→ 截断 500 字符 2.4s，
        verdict 与全文口径一致（头部即答案主体）。断言传给 HHEM 的 doc
        文本 ≤ _MAX_HHEM_DOC_CHARS。
        """
        from agent.reflector import _MAX_HHEM_DOC_CHARS
        assert _MAX_HHEM_DOC_CHARS == 500

        long_docs = [
            {"id": 1, "title": "d1", "content": "长" * 2000},
            {"id": 2, "title": "d2", "content": "短内容"},
        ]
        async def run():
            r = Reflector()
            with mock.patch("rag.retrieval.factcheck_judge.hhem_judge.predict",
                            new=mock.AsyncMock(return_value=[0.9, 0.9])) as mock_pred:
                await r._judge_by_hhem([{"claim": "c1"}], long_docs)
            return mock_pred

        mock_pred = asyncio.run(run())
        flat_docs = mock_pred.await_args[0][0]
        assert len(flat_docs[0]) == 500          # 超长截断
        assert len(flat_docs[1]) == len("短内容")  # 短内容不截断
        assert "短内容" in flat_docs[1]


class TestVerifyAnswerHhem:
    """verify_answer HHEM 主路径 + 降级链三层 + 开关 llm（mock HHEM，不加载真实模型）"""

    @staticmethod
    def _docs():
        return [
            {"id": 1, "title": "线程池基础", "source": "test",
             "content": "线程池核心参数包括核心线程数、最大线程数、队列容量。"},
            {"id": 2, "title": "线程池配置", "source": "test",
             "content": "最大线程数根据CPU密集型任务设置为核心数的2倍。"},
        ]

    def test_hhem_path_scenario1(self):
        """AC 场景 1：3 句答案 + 2 文档，HHEM 给分映射三态各 1，evidence 取 max 文档"""
        scores = [0.85, 0.30, 0.20, 0.45, 0.15, 0.10]  # c1 max 0.85 / c2 max 0.45 / c3 max 0.15
        async def run():
            r = Reflector()
            client = mock.MagicMock()
            client.generate = mock.AsyncMock(
                return_value=json.dumps(["c1", "c2", "c3"], ensure_ascii=False))
            with mock.patch("llm.client.LLMFactory.get_client", return_value=client):
                with mock.patch("rag.retrieval.factcheck_judge.hhem_judge.predict",
                                new=mock.AsyncMock(return_value=scores)) as mock_pred:
                    result = await r.verify_answer("答案[1]", self._docs())
            return result, client, mock_pred

        result, client, mock_pred = asyncio.run(run())
        assert result["total_claims"] == 3
        assert result["supported"] == 1
        assert result["inferred"] == 1
        assert result["unsupported"] == 1
        assert result["overall_confidence"] == pytest.approx(0.6667, abs=0.001)
        assert result["claims"][0]["verdict"] == "supported"
        assert result["claims"][0]["evidence"] == "[1]"
        assert result["claims"][1]["verdict"] == "inferred"
        assert result["claims"][1]["evidence"] == "[2]"
        assert result["claims"][2]["verdict"] == "unsupported"
        assert result["claims"][2]["evidence"] == "N/A"
        mock_pred.assert_awaited_once()
        client.generate.assert_awaited_once()  # 主路径只拆句一次，判分交给 HHEM

    def test_hhem_unavailable_degrades_to_llm(self):
        """降级链第 1 层：HHEM 不可用 → 回退 LLM 判分（旧全量 prompt，行为与 module-039 一致）"""
        judge_response = json.dumps([
            {"claim": "c1", "verdict": "supported", "evidence": "[1]"},
            {"claim": "c2", "verdict": "unsupported", "evidence": "N/A"},
        ], ensure_ascii=False)
        async def run():
            r = Reflector()
            client = mock.MagicMock()
            client.generate = mock.AsyncMock(side_effect=[
                json.dumps(["c1", "c2"], ensure_ascii=False), judge_response])
            with mock.patch("llm.client.LLMFactory.get_client", return_value=client):
                with mock.patch("rag.retrieval.factcheck_judge.hhem_judge.predict",
                                new=mock.AsyncMock(return_value=None)):
                    result = await r.verify_answer("答案[1]", self._docs())
            return result, client

        result, client = asyncio.run(run())
        assert result["supported"] == 1
        assert result["unsupported"] == 1
        assert result["total_claims"] == 2
        assert result["claims"][0]["evidence"] == "[1]"
        # 第二次调用走旧全量 prompt（含文档上下文）
        prompt2 = client.generate.call_args_list[1][0][0]
        assert "答案验证专家" in prompt2
        assert "检索文档" in prompt2

    def test_llm_judge_fails_returns_empty(self):
        """降级链第 2 层：LLM 判分也失败 → 空 claims（overall_confidence=0.0，现有降级哲学）"""
        async def run():
            r = Reflector()
            client = mock.MagicMock()
            client.generate = mock.AsyncMock(side_effect=[
                json.dumps(["c1"], ensure_ascii=False), RuntimeError("LLM 判分失败")])
            with mock.patch("llm.client.LLMFactory.get_client", return_value=client):
                with mock.patch("rag.retrieval.factcheck_judge.hhem_judge.predict",
                                new=mock.AsyncMock(return_value=None)):
                    result = await r.verify_answer("答案[1]", self._docs())
            return result

        result = asyncio.run(run())
        assert result["claims"] == []
        assert result["overall_confidence"] == 0.0

    def test_switch_llm_zero_regression(self):
        """AC 场景 3：开关 "llm" → 完全不加载/调用 HHEM，直走旧逻辑（单次 LLM 全量调用）"""
        response = json.dumps([
            {"claim": "c1", "verdict": "supported", "evidence": "[1]"},
        ], ensure_ascii=False)
        async def run():
            r = Reflector()
            client = mock.MagicMock()
            client.generate = mock.AsyncMock(return_value=response)
            with mock.patch("agent.reflector.settings.verify_judge_model", "llm"):
                with mock.patch("llm.client.LLMFactory.get_client", return_value=client):
                    with mock.patch("rag.retrieval.factcheck_judge.hhem_judge.predict") as mock_pred:
                        result = await r.verify_answer("答案[1]", self._docs())
            return result, client, mock_pred

        result, client, mock_pred = asyncio.run(run())
        assert result["supported"] == 1
        client.generate.assert_awaited_once()   # 单次调用（不拆句再判分）
        mock_pred.assert_not_called()           # HHEM 完全不加载/调用
        prompt = client.generate.call_args[0][0]
        assert "答案验证专家" in prompt         # 旧全量 prompt

    def test_split_failure_returns_empty(self):
        """LLM 拆句失败 → 空 claims，HHEM 不调用（现有降级哲学）"""
        async def run():
            r = Reflector()
            client = mock.MagicMock()
            client.generate = mock.AsyncMock(side_effect=RuntimeError("拆句失败"))
            with mock.patch("llm.client.LLMFactory.get_client", return_value=client):
                with mock.patch("rag.retrieval.factcheck_judge.hhem_judge.predict") as mock_pred:
                    result = await r.verify_answer("答案[1]", self._docs())
            return result, mock_pred

        result, mock_pred = asyncio.run(run())
        assert result["claims"] == []
        mock_pred.assert_not_called()

    def test_return_structure_compatible(self):
        """返回结构零改动：claims/overall_confidence/total_claims/supported/inferred/unsupported"""
        async def run():
            r = Reflector()
            client = mock.MagicMock()
            client.generate = mock.AsyncMock(
                return_value=json.dumps(["c1"], ensure_ascii=False))
            with mock.patch("llm.client.LLMFactory.get_client", return_value=client):
                with mock.patch("rag.retrieval.factcheck_judge.hhem_judge.predict",
                                new=mock.AsyncMock(return_value=[0.8, 0.2])):
                    result = await r.verify_answer("答案[1]", self._docs())
            return result

        result = asyncio.run(run())
        assert set(result.keys()) == {"claims", "overall_confidence", "total_claims",
                                      "supported", "inferred", "unsupported"}
        assert isinstance(result["claims"], list)
        assert 0.0 <= result["overall_confidence"] <= 1.0


class TestParseClaims:
    """_parse_claims 拆句解析（module-051：纯拆句）"""

    def test_string_array(self):
        claims = Reflector._parse_claims('["线程池参数", "最大线程数"]')
        assert claims == [{"claim": "线程池参数"}, {"claim": "最大线程数"}]

    def test_markdown_wrapped(self):
        claims = Reflector._parse_claims('```json\n["c1", "c2"]\n```')
        assert [c["claim"] for c in claims] == ["c1", "c2"]

    def test_extra_text_before_json(self):
        claims = Reflector._parse_claims('以下是拆解结果：\n["c1"]')
        assert len(claims) == 1 and claims[0]["claim"] == "c1"

    def test_dict_items_keep_claim(self):
        """LLM 返回 dict 项 → 取 claim 字段；无 verdict → 走 HHEM 判定"""
        claims = Reflector._parse_claims('[{"claim": "c1"}, "c2"]')
        assert [c["claim"] for c in claims] == ["c1", "c2"]
        assert "verdict" not in claims[0]

    def test_dict_items_preserve_legacy_verdict(self):
        """旧格式 dict 项（带 verdict/evidence）→ 原样保留（_judge_by_hhem 据此跳过 HHEM）"""
        claims = Reflector._parse_claims(
            '[{"claim": "c1", "verdict": "supported", "evidence": "[1]"}]')
        assert claims[0]["verdict"] == "supported"
        assert claims[0]["evidence"] == "[1]"

    def test_legacy_verdict_without_evidence_gets_na(self):
        """旧格式 dict 项带 verdict 但缺 evidence → 默认补 "N/A"
        （minor#2：前端 parseEvidenceRef 不对 undefined 抛 TypeError）"""
        claims = Reflector._parse_claims('[{"claim": "c1", "verdict": "supported"}]')
        assert claims[0]["verdict"] == "supported"
        assert claims[0]["evidence"] == "N/A"

    def test_invalid_returns_empty(self):
        assert Reflector._parse_claims("纯文本无JSON结构！") == []

    def test_blank_items_filtered(self):
        claims = Reflector._parse_claims('["c1", "", "  ", "c2"]')
        assert [c["claim"] for c in claims] == ["c1", "c2"]


class TestGoldenFactcheck:
    """eval/golden_factcheck.py：数据集 / 启发式 / kappa / run_eval / 落库契约"""

    def test_dataset_structure_50_three_classes(self):
        data = golden_factcheck.build_factcheck_dataset()
        assert len(data) == 50
        counts = {c: 0 for c in golden_factcheck.FACTCHECK_CLASSES}
        for item in data:
            assert item["question"].strip()
            assert item["documents"]
            assert item["label"] in golden_factcheck.FACTCHECK_CLASSES
            counts[item["label"]] += 1
        assert counts == {"supported": 20, "inferred": 10, "unsupported": 20}

    def test_dataset_borrows_from_sufficiency(self):
        data = golden_factcheck.build_factcheck_dataset()
        questions = {d["question"] for d in data}
        assert "什么是G1垃圾收集器？它的核心创新是什么？" in questions
        # inferred 为人工构造样例（含 note 说明部分覆盖性质）
        inferred = [d for d in data if d["label"] == "inferred"]
        assert all(d.get("note") for d in inferred)

    def test_heuristic_judge_three_states(self):
        doc_hit2 = [{"title": "t", "content": "G1 使用 Region 分区实现 MixedGC"}]
        assert golden_factcheck.heuristic_judge(
            "q", doc_hit2, ["G1", "Region", "MixedGC"]) == "supported"
        doc_hit1 = [{"title": "t", "content": "G1 垃圾收集器"}]
        assert golden_factcheck.heuristic_judge(
            "q", doc_hit1, ["G1", "Region"]) == "inferred"
        doc_miss = [{"title": "t", "content": "Kafka 消息队列"}]
        assert golden_factcheck.heuristic_judge(
            "q", doc_miss, ["G1", "Region"]) == "unsupported"
        assert golden_factcheck.heuristic_judge("q", [], ["G1"]) == "unsupported"

    def test_kappa_metrics_perfect(self):
        human = ["supported"] * 2 + ["inferred"] * 2 + ["unsupported"] * 2
        m = golden_factcheck.kappa_metrics(human, human)
        assert m["kappa_three_state"] == pytest.approx(1.0)
        assert m["kappa_binary_supported_vs_rest"] == pytest.approx(1.0)
        assert m["accuracy"] == pytest.approx(1.0)

    def test_kappa_metrics_reverse_negative(self):
        human = ["supported"] * 3 + ["unsupported"] * 3
        predicted = ["unsupported"] * 3 + ["supported"] * 3
        m = golden_factcheck.kappa_metrics(human, predicted)
        assert m["kappa_three_state"] == pytest.approx(-1.0)
        assert m["kappa_binary_supported_vs_rest"] == pytest.approx(-1.0)
        assert m["accuracy"] == pytest.approx(0.0)

    def test_run_eval_end_to_end(self):
        async def _judge(question, documents):
            return {"supported": "supported", "inferred": "inferred",
                    "unsupported": "unsupported"}[question], 0.9

        dataset = [
            {"question": "supported", "documents": [{"content": "x"}],
             "label": "supported", "category": "c"},
            {"question": "inferred", "documents": [{"content": "x"}],
             "label": "inferred", "category": "c"},
            {"question": "unsupported", "documents": [{"content": "x"}],
             "label": "unsupported", "category": "c"},
        ]
        scores, per_question, skipped = asyncio.run(
            golden_factcheck.run_eval(judge=_judge, dataset=dataset))
        assert scores["evaluated"] == 3
        assert scores["skipped"] == 0
        assert scores["kappa_three_state"] == pytest.approx(1.0)
        assert scores["class_distribution"]["supported"] == 1
        assert scores["thresholds"]["high"] == 0.7
        assert all(q["correct"] for q in per_question)
        assert per_question[0]["max_score"] == pytest.approx(0.9)

    def test_run_eval_model_unavailable_skipped(self):
        """模型不可用（verdict=None）→ 记 skipped（reason=model_unavailable），不中断"""
        async def _judge(question, documents):
            return None, None

        dataset = [{"question": "q1", "documents": [{"content": "x"}],
                    "label": "supported"}]
        scores, per_question, skipped = asyncio.run(
            golden_factcheck.run_eval(judge=_judge, dataset=dataset))
        assert scores["evaluated"] == 0
        assert scores["skipped"] == 1
        assert skipped[0]["reason"] == "model_unavailable"

    def test_run_eval_judge_error_skipped(self):
        """判定异常 → 跳过并记录错误，其余继续"""
        async def _judge(question, documents):
            raise RuntimeError("down")

        dataset = [{"question": "q1", "documents": [{"content": "x"}],
                    "label": "supported"}]
        scores, per_question, skipped = asyncio.run(
            golden_factcheck.run_eval(judge=_judge, dataset=dataset))
        assert scores["evaluated"] == 0
        assert scores["skipped"] == 1
        assert skipped[0]["reason"].startswith("error:")

    def test_record_eval_run_contract(self, monkeypatch):
        """eval_runs 落库契约：eval_type='factcheck' + git_commit + 配置快照（打桩 save_eval_run）"""
        captured = {}

        async def _fake_save(eval_type, git_commit, config_snapshot, scores, per_question):
            captured.update({"eval_type": eval_type, "git_commit": git_commit,
                             "config_snapshot": config_snapshot,
                             "scores": scores, "per_question": per_question})
            return 42

        async def _fake_config():
            return {"verify_judge_model": "hhem"}

        monkeypatch.setattr(golden_factcheck, "get_git_commit", lambda: "abc123def")
        monkeypatch.setattr(golden_factcheck, "load_rag_config", _fake_config)
        monkeypatch.setattr(golden_factcheck, "save_eval_run", _fake_save)

        commit, saved_id = asyncio.run(golden_factcheck.record_eval_run(
            scores={"kappa_three_state": 0.7},
            per_question=[{"question": "q", "label": "supported", "predicted": "supported"}]))
        assert commit == "abc123def"
        assert saved_id == 42
        assert captured["eval_type"] == "factcheck"
        assert captured["git_commit"] == "abc123def"
        assert captured["config_snapshot"] == {"verify_judge_model": "hhem"}
        assert captured["scores"]["kappa_three_state"] == 0.7

    def test_print_report_fixture_gate_wording(self, capsys):
        """fixture 模式门槛行带 [fixture] 前缀且不打印"达标"
        （minor#3：启发式判断器产出非真实指标，避免误读为 ADR-0010 P1-④ 达标）"""
        scores = {
            "dataset_size": 50, "evaluated": 50, "skipped": 0,
            "kappa_three_state": 0.9375, "kappa_binary_supported_vs_rest": 0.9,
            "accuracy": 0.95,
            "class_distribution": {"supported": 20, "inferred": 10, "unsupported": 20},
            "thresholds": {"high": 0.7, "low": 0.3},
        }
        golden_factcheck.print_report(scores, [], [], saved_id=0, commit="", fixture=True)
        out = capsys.readouterr().out
        assert "[fixture]" in out
        assert "不构成 ADR-0010 P1-④ 门槛判定" in out
        assert "达标" not in out
