"""Module-023 长期记忆单元测试

覆盖（验收 §4.1 单元测试 + §1.2 边界 + §1.3 异常）：
- MemoryService.save：分块+向量化+入库（source='memory:<ip>:'）、空 content 报错、
  空 ip 默认 'unknown'、非法 ip（含 LIKE 通配符）降级 'unknown'
- MemoryService.recall：空 query 返回空、source_pattern 按 IP 隔离透传、
  检索失败返回空（不崩）、子块映射回父块完整内容、通配符 ip 不能绕过隔离
- retriever._source_condition：默认排除 'memory:%'；记忆检索 LIKE 过滤
- retriever._fts_search：source_pattern 拼入 SQL 与参数
- engine._recall_memory：无 IP/无记忆/失败返回空串（chat 零回归前提）；
  realtime 意图跳过记忆召回（review #5）
- reflector._GENERATE_PROMPT：空 sections 与旧版逐字节一致（review #2）
- main.list_documents：列表查询排除记忆文档（review #7）

实现说明：
- 用 mock.AsyncMock 打桩 AsyncSession / hybrid_retriever / embedding_service，
  不依赖真实数据库（与 test_fts_search.py / test_golden_retrieval.py 同款模式）
- 同步用例内 asyncio.run 执行，不依赖 pytest-asyncio（规避既有环境问题）
"""
import asyncio
from datetime import date, datetime, timedelta
from unittest import mock

from rag.memory import memory_service, _escape_like, _layer_pattern, _memory_source, format_memory_line
from rag.retriever import HybridRetriever
from rag.engine import rag_engine
from rag.schemas import ChatRequest
from src.config import settings


class _FakeSession:
    """假 AsyncSession：记录 add 的对象 + 可配置 execute 结果"""

    def __init__(self, scalar=None, scalars=None, all_rows=None):
        self.added: list = []
        self._scalar = scalar
        self._scalars = scalars or []
        self._all = all_rows or []
        self.rolled_back = False

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        # 给父块分配假 DB ID（子块引用的 parent.id）
        for i, obj in enumerate(self.added):
            if getattr(obj, "parent_id", None) is None:
                obj.id = i + 1

    async def commit(self):
        pass

    async def rollback(self):
        self.rolled_back = True

    async def execute(self, stmt):
        result = mock.MagicMock()
        result.scalar.return_value = self._scalar
        result.scalars.return_value = mock.MagicMock(
            all=mock.MagicMock(return_value=self._scalars),
        )
        result.all.return_value = self._all  # module-035：_child_embeddings 列选择查询
        return result


def _fake_factory(session):
    """把 async_session_factory 打桩成返回 session 的异步上下文管理器

    factory 本身是同步可调用（async_session_factory() 立即返回 CM 对象），
    只有 __aenter__/__aexit__ 是异步的，故用 MagicMock 而非 AsyncMock。
    """
    cm = mock.MagicMock()
    cm.__aenter__ = mock.AsyncMock(return_value=session)
    cm.__aexit__ = mock.AsyncMock(return_value=False)
    return mock.MagicMock(return_value=cm)


def _chunk_single(content):
    """短记忆分块桩：单个父块 + 单个子块"""
    return {
        "parents": [{"title": "记忆", "content": content}],
        "children": [{"title": "记忆", "content": content, "parent_index": 0}],
    }


class TestSave:
    """MemoryService.save"""

    def test_save_writes_documents_with_memory_source(self):
        async def run():
            fs = _FakeSession(scalar=0)
            with mock.patch("rag.memory.async_session_factory", _fake_factory(fs)):
                with mock.patch("rag.memory.chunker") as chunker_mock:
                    with mock.patch("rag.memory.embedding_service") as emb_mock:
                        chunker_mock.chunk.return_value = _chunk_single("用户偏好简短 Java 回答")
                        emb_mock.embed_documents = mock.AsyncMock(return_value=[[0.1, 0.2]])
                        result = await memory_service.save("用户偏好简短 Java 回答", "192.168.1.1")

            assert result["status"] == "saved"
            assert result["title"].startswith("记忆-")
            assert result["id"] == 1
            # 父块 + 子块均写入，source='memory:192.168.1.1:'（尾冒号分隔符，保证 IP 隔离）
            assert {getattr(d, "source", None) for d in fs.added} == {"memory:192.168.1.1:"}
            # 子块带 embedding 且指向父块；父块无向量
            embedded = [d for d in fs.added if d.embedding is not None]
            parents = [d for d in fs.added if d.embedding is None]
            assert len(embedded) == 1 and embedded[0].parent_id == 1
            assert len(parents) == 1 and parents[0].parent_id is None
            assert embedded[0].search_tokens is not None  # 中文 FTS 预分词已写入
        asyncio.run(run())

    def test_save_empty_content_raises(self):
        try:
            asyncio.run(memory_service.save("   ", "ip"))
            raise AssertionError("应抛出 ValueError")
        except ValueError:
            pass

    def test_save_empty_ip_defaults_unknown(self):
        async def run():
            fs = _FakeSession(scalar=0)
            with mock.patch("rag.memory.async_session_factory", _fake_factory(fs)):
                with mock.patch("rag.memory.chunker") as chunker_mock:
                    with mock.patch("rag.memory.embedding_service") as emb_mock:
                        chunker_mock.chunk.return_value = {"parents": [], "children": []}
                        emb_mock.embed_documents = mock.AsyncMock(return_value=[[0.1]])
                        await memory_service.save("abc", "")

            assert {getattr(d, "source", None) for d in fs.added} == {"memory:unknown:"}
        asyncio.run(run())

    def test_save_ip_wildcard_normalized_to_unknown(self):
        """save 的 ip 通配符/非法值降级 'unknown'（回归 review #1）

        传 ip="%" 若直接拼 source 会产生 'memory:%:'，配合 recall 的
        'memory:%:%' 模式可跨 IP 匹配全部记忆；规范化后只写 'unknown' 桶。
        """
        async def run():
            fs = _FakeSession(scalar=0)
            with mock.patch("rag.memory.async_session_factory", _fake_factory(fs)):
                with mock.patch("rag.memory.chunker") as chunker_mock:
                    with mock.patch("rag.memory.embedding_service") as emb_mock:
                        chunker_mock.chunk.return_value = _chunk_single("用户偏好简短回答")
                        emb_mock.embed_documents = mock.AsyncMock(return_value=[[0.1]])
                        await memory_service.save("abc", "%")
            assert {getattr(d, "source", None) for d in fs.added} == {"memory:unknown:"}
        asyncio.run(run())

    def test_save_embedding_failure_raises(self):
        async def run():
            fs = _FakeSession(scalar=0)
            with mock.patch("rag.memory.async_session_factory", _fake_factory(fs)):
                with mock.patch("rag.memory.chunker") as chunker_mock:
                    with mock.patch("rag.memory.embedding_service") as emb_mock:
                        chunker_mock.chunk.return_value = _chunk_single("用户偏好简短回答")
                        emb_mock.embed_documents = mock.AsyncMock(side_effect=RuntimeError("embedding down"))
                        try:
                            await memory_service.save("用户偏好简短回答", "ip")
                            raise AssertionError("应抛出 RuntimeError")
                        except RuntimeError:
                            pass
            assert fs.rolled_back is True  # embedding 失败 → 事务回滚，不留残缺记录
        asyncio.run(run())


class TestRecall:
    """MemoryService.recall"""

    def test_recall_empty_query_returns_empty(self):
        async def run():
            with mock.patch("rag.memory.hybrid_retriever") as ret:
                ret.retrieve = mock.AsyncMock()
                assert await memory_service.recall("  ", "ip") == []
                ret.retrieve.assert_not_called()
        asyncio.run(run())

    def test_recall_passes_source_pattern_and_expands_to_parent(self):
        # module-035：query 嵌入失败 → 降级用原 hybrid_score（不回退失败）。
        # 本用例覆盖降级路径（score 取 hybrid_score=0.8），source_pattern 透传不变
        child = {"id": 2, "content": "子块", "parent_id": 1, "hybrid_score": 0.8}
        parent = mock.MagicMock(id=1, content="完整记忆：上次结论是 X",
                                title="记忆-2026-08-01-01",
                                created_at=datetime(2026, 8, 1))

        async def run():
            with mock.patch("rag.memory.hybrid_retriever") as ret:
                with mock.patch("rag.memory.async_session_factory", _fake_factory(_FakeSession(scalars=[parent]))):
                    with mock.patch("rag.memory.embedding_service") as emb:
                        emb.embed_text = mock.AsyncMock(side_effect=RuntimeError("embed down"))
                        ret.retrieve = mock.AsyncMock(return_value=[child])
                        memories = await memory_service.recall("线程池", "192.168.1.1", top_k=3)

            ret.retrieve.assert_awaited_once_with(
                "线程池", top_k=3, source_pattern="memory:192.168.1.1:",
            )
            assert memories == [{
                "content": "完整记忆：上次结论是 X",
                "score": 0.8,
                "title": "记忆-2026-08-01-01",
                "created_at": "2026-08-01",
            }]
        asyncio.run(run())

    def test_recall_isolated_by_ip(self):
        calls = []

        async def run():
            with mock.patch("rag.memory.hybrid_retriever") as ret:
                async def fake_retrieve(query, top_k=5, source_pattern=None):
                    calls.append(source_pattern)
                    return []
                ret.retrieve = mock.AsyncMock(side_effect=fake_retrieve)
                await memory_service.recall("q", "1.1.1.1")
                await memory_service.recall("q", "2.2.2.2")

        asyncio.run(run())
        assert calls == ["memory:1.1.1.1:", "memory:2.2.2.2:"]

    def test_recall_ip_prefix_overlap_no_cross_match(self):
        """前缀重叠 IP（192.168.1.1 vs 192.168.1.10）隔离不泄漏（回归 #1）

        source 带尾冒号分隔符后，模式 'memory:192.168.1.1:%' 不会匹配
        'memory:192.168.1.10:...'。LIKE 模式无通配符的逐字前缀部分与
        Python str.startswith 语义一致，此处以 startswith 镜像 SQL LIKE。
        """
        calls = []

        async def run():
            with mock.patch("rag.memory.hybrid_retriever") as ret:
                async def fake_retrieve(query, top_k=5, source_pattern=None):
                    calls.append(source_pattern)
                    return []
                ret.retrieve = mock.AsyncMock(side_effect=fake_retrieve)
                await memory_service.recall("q", "192.168.1.1")
                await memory_service.recall("q", "192.168.1.10")

        asyncio.run(run())
        assert calls == ["memory:192.168.1.1:", "memory:192.168.1.10:"]
        # LIKE 语义镜像：1.1 的检索模式不得匹配 1.10 的记忆 source，反之亦然
        assert not "memory:192.168.1.10:xyz".startswith("memory:192.168.1.1:")
        assert not "memory:192.168.1.1:xyz".startswith("memory:192.168.1.10:")

    def test_recall_ip_wildcard_cannot_bypass(self):
        """LIKE 通配符注入不能绕过按 IP 隔离（回归 review #1 阻塞项）

        客户端传 ip="%" 时旧实现构造 'memory:%:%' 匹配全部记忆 source，
        可跨 IP 读取所有用户记忆；ip="_" 匹配单个任意字符同理。
        修复后 ip 必须通过 IPv4 校验（通配符降级 'unknown'）+ LIKE 转义，
        recall 只能命中 'unknown' 桶，无法命中任意 IP 的记忆。
        """
        calls = []

        async def run():
            with mock.patch("rag.memory.hybrid_retriever") as ret:
                async def fake_retrieve(query, top_k=5, source_pattern=None):
                    calls.append(source_pattern)
                    return []
                ret.retrieve = mock.AsyncMock(side_effect=fake_retrieve)
                await memory_service.recall("q", "%")
                await memory_service.recall("q", "_")
                await memory_service.recall("q", "\\")
                await memory_service.recall("q", "1.1.1.1")

        asyncio.run(run())
        # 通配符 ip 全部降级为 'unknown' 桶，合法 IPv4 原样保留
        assert calls == ["memory:unknown:"] * 3 + ["memory:1.1.1.1:"]
        # LIKE 语义镜像：'memory:unknown:%' 不得匹配任意 IP 的记忆 source
        assert "memory:1.1.1.1:xyz".startswith("memory:unknown:") is False

    def test_escape_like_escapes_metacharacters(self):
        """_escape_like 转义 %/_/\\（双保险：校验之外再防一层注入）"""
        assert _escape_like("%") == "\\%"
        assert _escape_like("_") == "\\_"
        assert _escape_like("\\") == "\\\\"
        assert _escape_like("%_\\") == "\\%\\_\\\\"
        assert _escape_like("1.1.1.1") == "1.1.1.1"  # 合法 IPv4 无元字符，原样

    def test_recall_retrieval_failure_returns_empty(self):
        async def run():
            with mock.patch("rag.memory.hybrid_retriever") as ret:
                ret.retrieve = mock.AsyncMock(side_effect=RuntimeError("db down"))
                assert await memory_service.recall("q", "ip") == []
        asyncio.run(run())

    def test_recall_dedup_same_parent_take_highest_score(self):
        # module-035：query 嵌入失败 → 降级 hybrid_score 路径（同父块去重取最高分语义不变）
        parent = mock.MagicMock(id=1, content="完整记忆内容", title="记忆-2026-08-01-01",
                                created_at=datetime(2026, 8, 1))
        child_low = {"id": 2, "content": "子块1", "parent_id": 1, "hybrid_score": 0.5}
        child_high = {"id": 3, "content": "子块2", "parent_id": 1, "hybrid_score": 0.9}

        async def run():
            with mock.patch("rag.memory.hybrid_retriever") as ret:
                with mock.patch("rag.memory.async_session_factory", _fake_factory(_FakeSession(scalars=[parent]))):
                    with mock.patch("rag.memory.embedding_service") as emb:
                        emb.embed_text = mock.AsyncMock(side_effect=RuntimeError("embed down"))
                        ret.retrieve = mock.AsyncMock(return_value=[child_low, child_high])
                        memories = await memory_service.recall("q", "ip")

            assert len(memories) == 1
            assert memories[0]["content"] == "完整记忆内容"
            assert memories[0]["score"] == 0.9  # 同父块多子块命中取最高分
        asyncio.run(run())


class TestNextTitle:
    """_next_title 标题序号生成（回归 #5 按 source 计数；回归 #4 本 IP + 当日过滤）"""

    def test_counts_memory_parents_by_source_not_title(self):
        captured = {}

        class _CaptureSession(_FakeSession):
            async def execute(self, stmt):
                captured["stmt"] = stmt
                return await super().execute(stmt)

        async def run():
            # scalar=2：已存在 2 个记忆父块（其中可能含 markdown 标题父块，标题非'记忆-...'）
            with mock.patch("rag.memory.async_session_factory",
                            _fake_factory(_CaptureSession(scalar=2))):
                captured["title"] = await memory_service._next_title(date(2026, 8, 1), "192.168.1.1")

        asyncio.run(run())
        # literal_binds 把绑定参数内联进 SQL，便于断言过滤条件的具体值
        sql = str(captured["stmt"].compile(compile_kwargs={"literal_binds": True}))
        # 计数按 source 前缀过滤记忆文档 + 只统计父块，不依赖 title LIKE 前缀
        assert "source LIKE" in sql
        assert "parent_id IS NULL" in sql
        # review #4：计数限定本 IP + 当日（created_at），避免序号跨日期/IP 累计
        assert "memory:192.168.1.1:" in sql
        assert "2026-08-01" in sql
        assert captured["title"] == "记忆-2026-08-01-03"

    def test_next_title_scoped_to_ip_not_global(self):
        """不同 IP 的计数互不混用：SQL 必须按本 IP 的 source 模式过滤"""
        captured = {}

        class _CaptureSession(_FakeSession):
            async def execute(self, stmt):
                captured["stmt"] = stmt
                return await super().execute(stmt)

        async def run():
            with mock.patch("rag.memory.async_session_factory",
                            _fake_factory(_CaptureSession(scalar=5))):
                captured["title"] = await memory_service._next_title(date(2026, 8, 1), "2.2.2.2")

        asyncio.run(run())
        sql = str(captured["stmt"].compile(compile_kwargs={"literal_binds": True}))
        assert "memory:2.2.2.2:" in sql
        assert "memory:%" not in sql  # 非全量前缀（module-034 各层精确匹配，不用 % 通配）
        assert captured["title"] == "记忆-2026-08-01-06"

    def test_save_passes_date_object_to_next_title(self):
        """回归 tester #1：save 传给 _next_title 的当日参数必须是 date 对象

        旧实现传 date.today().isoformat()（字符串），经 asyncpg 绑定为
        $n::VARCHAR，PostgreSQL 无 date = character varying 运算符 → 真实
        save 恒抛 ProgrammingError（端点恒 code:2，记忆永远无法入库）。
        修复后传 date.today()（date 对象，SQLAlchemy 绑定为 DATE）。
        """
        async def run():
            fs = _FakeSession(scalar=0)
            with mock.patch("rag.memory.async_session_factory", _fake_factory(fs)):
                with mock.patch("rag.memory.chunker") as chunker_mock:
                    with mock.patch("rag.memory.embedding_service") as emb_mock:
                        with mock.patch.object(
                            memory_service, "_next_title",
                            new=mock.AsyncMock(return_value="记忆-2026-08-01-01"),
                        ) as nt:
                            chunker_mock.chunk.return_value = _chunk_single("用户偏好简短回答")
                            emb_mock.embed_documents = mock.AsyncMock(return_value=[[0.1]])
                            await memory_service.save("用户偏好简短回答", "192.168.1.1")
            assert isinstance(nt.call_args.args[0], date)  # date 对象（DATE 绑定），非 str
            assert nt.call_args.args[1] == "192.168.1.1"
        asyncio.run(run())

    def test_next_title_binds_date_not_string(self):
        """回归 tester #1：_next_title 当日参数必须绑定为 DATE（date 对象）

        func.date(created_at) == day 的 day 若为字符串，asyncpg 绑定为
        VARCHAR，PG 无 date=varchar 运算符 → 真实查询崩溃。本测试断言编译后
        绑定参数含 date 类型值（SQLAlchemy 依 Python 类型绑定），若改回
        ISO 字符串将断言失败。
        """
        captured = {}

        class _CaptureSession(_FakeSession):
            async def execute(self, stmt):
                captured["params"] = stmt.compile().params
                return await super().execute(stmt)

        async def run():
            with mock.patch("rag.memory.async_session_factory",
                            _fake_factory(_CaptureSession(scalar=0))):
                await memory_service._next_title(date(2026, 8, 1), "192.168.1.1")

        asyncio.run(run())
        assert any(isinstance(v, date) for v in captured["params"].values())


class TestSourceFilter:
    """retriever._source_condition（记忆隔离 SQL 片段）"""

    def test_default_excludes_memory_prefix(self):
        clause = HybridRetriever._source_condition(None)
        assert "NOT LIKE 'memory:%'" in clause
        assert "LIKE :source_pattern" not in clause

    def test_memory_pattern_filters_by_like(self):
        clause = HybridRetriever._source_condition("memory:192.168.1.1:%")
        assert "LIKE :source_pattern" in clause
        assert "NOT LIKE 'memory:%'" not in clause

    def test_fts_search_source_pattern_in_sql_and_params(self):
        async def run():
            retriever = HybridRetriever(embedding_service=mock.MagicMock(), alpha=0.3)
            session = mock.AsyncMock()
            session.execute = mock.AsyncMock(
                return_value=mock.MagicMock(mappings=mock.MagicMock(return_value=[])),
            )
            await retriever._fts_search("线程池", 10, session, source_pattern="memory:192.168.1.1:%")
            sql = session.execute.call_args.args[0].text
            params = session.execute.call_args.args[1]
            assert "source LIKE :source_pattern" in sql
            assert params["source_pattern"] == "memory:192.168.1.1:%"
        asyncio.run(run())

    def test_fts_search_default_excludes_memory_and_no_param(self):
        async def run():
            retriever = HybridRetriever(embedding_service=mock.MagicMock(), alpha=0.3)
            session = mock.AsyncMock()
            session.execute = mock.AsyncMock(
                return_value=mock.MagicMock(mappings=mock.MagicMock(return_value=[])),
            )
            await retriever._fts_search("线程池", 10, session)
            sql = session.execute.call_args.args[0].text
            params = session.execute.call_args.args[1]
            assert "NOT LIKE 'memory:%'" in sql
            assert "source_pattern" not in params
        asyncio.run(run())


class TestEngineMemoryInjection:
    """engine._recall_memory（chat 记忆注入的零回归前提）"""

    def test_no_ip_returns_empty_without_calling_service(self):
        async def run():
            with mock.patch("rag.engine.memory_service.recall", new=mock.AsyncMock()) as recall:
                assert await rag_engine._recall_memory("q", "") == ""
                recall.assert_not_called()
        asyncio.run(run())

    def test_no_memories_returns_empty(self):
        async def run():
            with mock.patch("rag.engine.memory_service.recall", new=mock.AsyncMock(return_value=[])):
                with mock.patch("rag.engine.memory_service.recall_short", new=mock.AsyncMock(return_value=[])):
                    assert await rag_engine._recall_memory("q", "ip") == ""
        asyncio.run(run())

    def test_failure_returns_empty(self):
        async def run():
            with mock.patch("rag.engine.memory_service.recall",
                            new=mock.AsyncMock(side_effect=RuntimeError("down"))):
                with mock.patch("rag.engine.memory_service.recall_short", new=mock.AsyncMock(return_value=[])):
                    assert await rag_engine._recall_memory("q", "ip") == ""
        asyncio.run(run())

    def test_formats_memory_section(self):
        async def run():
            with mock.patch("rag.engine.memory_service.recall",
                            new=mock.AsyncMock(return_value=[
                                {"content": "用户偏好简短 Java 回答", "score": 0.9},
                            ])):
                with mock.patch("rag.engine.memory_service.recall_short", new=mock.AsyncMock(return_value=[])):
                    text = await rag_engine._recall_memory("回答风格", "ip", top_k=3)
            assert text.startswith("历史记忆:")
            assert "用户偏好简短 Java 回答" in text
        asyncio.run(run())


class TestEngineRealtimeSkipsMemory:
    """engine.chat 意图分支（回归 review #5：realtime 跳过记忆召回）"""

    def test_chat_realtime_skips_memory_recall(self):
        async def run():
            with mock.patch("rag.engine.router_agent.classify",
                            new=mock.AsyncMock(return_value={"intent": "realtime"})):
                with mock.patch("rag.engine.memory_service.recall", new=mock.AsyncMock()) as recall:
                    result = await rag_engine.chat(ChatRequest(query="现在几点"), identity="1.2.3.4")
            recall.assert_not_called()  # realtime 不触发记忆召回（避免 5s 无谓延迟）
            assert "开发中" in result.answer
        asyncio.run(run())

    def test_chat_casual_still_recalls_memory(self):
        """reorder 后闲聊路径仍召回记忆并注入 system prompt（防回归）"""
        async def run():
            with mock.patch("rag.engine.router_agent.classify",
                            new=mock.AsyncMock(return_value={"intent": "casual_chat"})):
                with mock.patch("rag.engine.memory_service.recall",
                                new=mock.AsyncMock(return_value=[
                                    {"content": "用户偏好简洁回答", "score": 1.0},
                                ])):
                    with mock.patch("rag.engine.memory_service.recall_short",
                                    new=mock.AsyncMock(return_value=[])):
                        with mock.patch("rag.engine.LLMFactory.get_client") as gc:
                            fake = mock.MagicMock()
                            fake.chat = mock.AsyncMock(return_value="好的")
                            gc.return_value = fake
                            result = await rag_engine.chat(ChatRequest(query="你好"), identity="1.2.3.4")
            assert result.message == "casual_chat"
            sys_prompt = fake.chat.call_args.args[0][0]["content"]
            assert "用户偏好简洁回答" in sys_prompt  # 记忆仍注入闲聊 system prompt
        asyncio.run(run())


class TestPromptZeroRegression:
    """prompt 零回归（review #2：空 sections 时与旧版逐字节一致）"""

    def test_empty_sections_byte_identical_to_old(self):
        from agent.reflector import _GENERATE_PROMPT
        query = "什么是G1 GC"
        docs_detail = "[1] 标题\n来源: 知识库\n内容: 内容"
        # 旧模板（module-023 之前）结构：{history_section}\n用户问题，
        # history 为空时「列表」与「用户问题」之间是 2 个空行
        old_prompt = (
            "你是一个知识库问答助手。基于检索到的文档回答用户问题。\n\n"
            "要求：\n"
            "1. 引用文档原文进行回答，用 [1][2] 标注引用来源\n"
            "2. 如果文档信息不足以回答问题，如实告知\n"
            "3. 回答后附带引用文档列表\n"
            "\n"
            "\n"
            f"用户问题: {query}\n"
            "\n"
            "检索到的文档:\n"
            f"{docs_detail}\n"
            "\n"
            "回答："
        )
        new_prompt = _GENERATE_PROMPT.format(
            query=query, docs_detail=docs_detail, sections="",
        )
        assert new_prompt == old_prompt


class TestListDocumentsExcludesMemory:
    """/ai/documents 列表排除记忆文档（回归 review #7）"""

    def test_list_documents_excludes_memory_source(self):
        from main import list_documents
        captured = []

        class _CaptureSession(_FakeSession):
            async def execute(self, stmt):
                # literal_binds 内联绑定参数，便于断言过滤条件的具体值
                captured.append(str(stmt.compile(compile_kwargs={"literal_binds": True})))
                result = mock.MagicMock()
                result.scalar.return_value = 0
                return result

        async def run():
            with mock.patch("main.async_session_factory", _fake_factory(_CaptureSession())):
                return await list_documents()

        resp = asyncio.run(run())
        assert len(captured) >= 1
        # 列表查询（含分组子查询）必须排除记忆文档（source='memory:%'）
        assert "NOT LIKE 'memory:%'" in captured[0]
        assert resp["code"] == 0


# ─── module-034：三层 source 分层 ───


class TestSourceLayering:
    """_memory_source / _layer_pattern：长/短/会话三层 source 互不混淆"""

    def test_memory_source_long_short_session(self):
        assert _memory_source("42") == "memory:42:"
        assert _memory_source("42", "short") == "memory:42:short:"
        assert _memory_source("42", "session") == "memory:42:session:"
        assert _memory_source("1.1.1.1") == "memory:1.1.1.1:"

    def test_layer_pattern_exact_no_wildcard(self):
        # 长期层不再用 ':%' 通配（避免命中 short/session 层），各层精确匹配
        assert _layer_pattern("42") == "memory:42:"
        assert _layer_pattern("42", "short") == "memory:42:short:"
        assert _layer_pattern("42", "session") == "memory:42:session:"
        assert "%" not in _layer_pattern("42")
        assert "%" not in _layer_pattern("42", "short")

    def test_long_pattern_does_not_match_short_source(self):
        # 长期层 source 精确匹配（等值），短/会话层 source 不同 → 等值不命中
        assert _layer_pattern("42") == "memory:42:"
        assert _layer_pattern("42") != "memory:42:short:"
        assert _layer_pattern("42") != "memory:42:session:"
        # 短/会话层各自精确匹配，互不命中
        assert _layer_pattern("42", "short") != "memory:42:session:"
        assert _layer_pattern("42", "session") != "memory:42:short:"

    def test_format_memory_line_short_label(self):
        line = format_memory_line(
            {"content": "最近在学 Java 并发", "created_at": "2026-08-05"}, label="短期记忆")
        assert line == "[短期记忆 - 2026-08-05]：最近在学 Java 并发"
        # 默认 label 保持长期记忆（module-033 兼容）
        assert format_memory_line({"content": "x"}) == "[长期记忆]：x"


class TestSaveShort:
    """MemoryService.save_short（module-034）"""

    def test_save_short_writes_short_source(self):
        async def run():
            fs = _FakeSession(scalar=0)
            with mock.patch("rag.memory.async_session_factory", _fake_factory(fs)):
                with mock.patch("rag.memory.chunker") as chunker_mock:
                    with mock.patch("rag.memory.embedding_service") as emb_mock:
                        chunker_mock.chunk.return_value = _chunk_single("最近在学 Java 并发")
                        emb_mock.embed_documents = mock.AsyncMock(return_value=[[0.1]])
                        result = await memory_service.save_short("最近在学 Java 并发", "42")

            assert result["status"] == "saved"
            assert result["title"].startswith("记忆-")
            # 父块 + 子块均写入，source='memory:42:short:'（与长期 'memory:42:' 区分）
            assert {getattr(d, "source", None) for d in fs.added} == {"memory:42:short:"}
            embedded = [d for d in fs.added if d.embedding is not None]
            assert len(embedded) == 1 and embedded[0].parent_id == 1
        asyncio.run(run())

    def test_save_short_empty_content_raises(self):
        try:
            asyncio.run(memory_service.save_short("   ", "ip"))
            raise AssertionError("应抛出 ValueError")
        except ValueError:
            pass

    def test_save_short_dedup_scoped_to_short_layer(self):
        """短期去重只查 short 层（_find_duplicate layer='short'），不与长期混查"""
        async def run():
            fs = _FakeSession(scalar=0)
            with mock.patch("rag.memory.async_session_factory", _fake_factory(fs)):
                with mock.patch("rag.memory.chunker") as chunker_mock:
                    with mock.patch("rag.memory.embedding_service") as emb_mock:
                        with mock.patch.object(memory_service, "_find_duplicate",
                                               new=mock.AsyncMock(return_value=None)) as find:
                            chunker_mock.chunk.return_value = _chunk_single("事实")
                            emb_mock.embed_documents = mock.AsyncMock(return_value=[[0.1]])
                            await memory_service.save_short("事实", "42")
            assert find.call_args.kwargs.get("layer") == "short"  # layer='short'
        asyncio.run(run())

    def test_save_short_title_count_scoped_to_short(self):
        """_next_title 计数按 short 层（不混入长期父块数）"""
        captured = {}

        class _CaptureSession(_FakeSession):
            async def execute(self, stmt):
                captured["stmt"] = stmt
                return await super().execute(stmt)

        async def run():
            with mock.patch("rag.memory.async_session_factory",
                            _fake_factory(_CaptureSession(scalar=3))):
                captured["title"] = await memory_service._next_title(date(2026, 8, 1), "42", layer="short")

        asyncio.run(run())
        sql = str(captured["stmt"].compile(compile_kwargs={"literal_binds": True}))
        assert "memory:42:short:" in sql  # 只统计短期层父块
        assert captured["title"] == "记忆-2026-08-01-04"


class TestRecallShort:
    """MemoryService.recall_short（module-034：动态 K + TTL 过滤）"""

    def test_recall_short_empty_query_returns_empty(self):
        async def run():
            with mock.patch("rag.memory.hybrid_retriever") as ret:
                ret.retrieve = mock.AsyncMock()
                assert await memory_service.recall_short("  ", "ip") == []
                ret.retrieve.assert_not_called()
        asyncio.run(run())

    def test_recall_short_passes_short_source_pattern(self):
        async def run():
            with mock.patch("rag.memory.hybrid_retriever") as ret:
                ret.retrieve = mock.AsyncMock(return_value=[])
                await memory_service.recall_short("q", "42")
            ret.retrieve.assert_awaited_once_with("q", top_k=5, source_pattern="memory:42:short:")
        asyncio.run(run())

    def test_recall_short_retrieval_failure_returns_empty(self):
        async def run():
            with mock.patch("rag.memory.hybrid_retriever") as ret:
                ret.retrieve = mock.AsyncMock(side_effect=RuntimeError("db down"))
                assert await memory_service.recall_short("q", "ip") == []
        asyncio.run(run())

    def test_recall_short_filters_expired_by_ttl(self):
        """超 memory_short_ttl_days 的短期记忆召回时被过滤（惰性过期）"""
        today = date.today()
        recent = today.isoformat()
        expired = (today - timedelta(days=settings.memory_short_ttl_days + 1)).isoformat()
        expanded = [
            {"content": "最近主题", "score": 0.9, "created_at": recent},
            {"content": "过期主题", "score": 0.9, "created_at": expired},
            {"content": "无日期", "score": 0.9, "created_at": None},
        ]
        child = {"id": 2, "content": "子块", "parent_id": 1, "hybrid_score": 0.9}
        out = {}

        async def run():
            with mock.patch("rag.memory.hybrid_retriever") as ret:
                ret.retrieve = mock.AsyncMock(return_value=[child])
                # module-035：query 嵌入失败 → 降级 hybrid_score 路径（TTL 过滤逻辑不变）
                with mock.patch("rag.memory.embedding_service") as emb:
                    emb.embed_text = mock.AsyncMock(side_effect=RuntimeError("embed down"))
                    with mock.patch.object(memory_service, "_expand_to_parents",
                                           new=mock.AsyncMock(return_value=expanded)):
                        out["memories"] = await memory_service.recall_short(
                            "最近聊了什么", "42", top_k=5)

        asyncio.run(run())
        contents = [m["content"] for m in out["memories"]]
        assert "过期主题" not in contents       # 超 TTL 被过滤
        assert "最近主题" in contents          # 未过期保留
        assert "无日期" in contents            # 无 created_at fail-open 保留

    def test_recall_short_isolated_by_identity(self):
        calls = []

        async def run():
            with mock.patch("rag.memory.hybrid_retriever") as ret:
                async def fake_retrieve(query, top_k=5, source_pattern=None):
                    calls.append(source_pattern)
                    return []
                ret.retrieve = mock.AsyncMock(side_effect=fake_retrieve)
                await memory_service.recall_short("q", "1.1.1.1")
                await memory_service.recall_short("q", "2.2.2.2")

        asyncio.run(run())
        assert calls == ["memory:1.1.1.1:short:", "memory:2.2.2.2:short:"]


# ─── module-035：动态 K 绝对余弦口径 ───


class TestRecallDynamicKAbsCosine:
    """module-035 动态 K 绝对余弦口径：三档真实可达 + 低分过滤 + 空候选 + 嵌入失败降级"""

    @staticmethod
    def _children(cosines):
        """子块候选：id/parent_id 一一对应（从 1 起，避免 parent_id=0 被 when 视为空），
        embedding 由 mock 提供 → 绝对余弦"""
        return [
            {"id": i + 1, "content": f"子{i}", "parent_id": i + 1, "hybrid_score": 0.5}
            for i in range(len(cosines))
        ]

    @staticmethod
    def _parents(n):
        return [
            mock.MagicMock(id=i + 1, content=f"记忆{i}", title=f"记忆-2026-08-01-0{i + 1}",
                           created_at=datetime(2026, 8, 1))
            for i in range(n)
        ]

    def _recall(self, children, emb_by_id, query_emb, parents):
        async def run():
            with mock.patch("rag.memory.hybrid_retriever") as ret:
                ret.retrieve = mock.AsyncMock(return_value=children)
                with mock.patch("rag.memory.embedding_service") as emb:
                    emb.embed_text = mock.AsyncMock(return_value=query_emb)
                    with mock.patch.object(memory_service, "_child_embeddings",
                                           new=mock.AsyncMock(return_value=emb_by_id)):
                        with mock.patch("rag.memory.async_session_factory",
                                        _fake_factory(_FakeSession(scalars=parents))):
                            return await memory_service.recall("q", "42", top_k=5)
        return asyncio.run(run())

    def test_high_quality_recalls_five(self):
        cosines = [0.9] * 5
        children = self._children(cosines)
        emb_by_id = {i + 1: [c, 0.0] for i, c in enumerate(cosines)}
        memories = self._recall(children, emb_by_id, [1.0, 0.0], self._parents(5))
        assert len(memories) == 5  # 绝对余弦均值 0.9 > 0.85 → K=5 真实可达（不再恒 1）
        assert all(m["score"] == 0.9 for m in memories)

    def test_mid_quality_recalls_three(self):
        cosines = [0.78] * 5
        children = self._children(cosines)
        emb_by_id = {i + 1: [c, 0.0] for i, c in enumerate(cosines)}
        memories = self._recall(children, emb_by_id, [1.0, 0.0], self._parents(5))
        assert len(memories) == 3  # 绝对余弦均值 0.78 ∈ [0.75,0.85) → K=3

    def test_low_quality_recalls_one(self):
        cosines = [0.5] * 5
        children = self._children(cosines)
        emb_by_id = {i + 1: [c, 0.0] for i, c in enumerate(cosines)}
        memories = self._recall(children, emb_by_id, [1.0, 0.0], self._parents(5))
        assert len(memories) == 1  # 绝对余弦均值 0.5 < 0.75 → K=1（宁缺毋滥）

    def test_low_score_candidates_filtered_out(self):
        # 第二条候选绝对余弦 0.3 < memory_recall_min_score(0.4) → 丢弃
        children = self._children([0.9, 0.3])
        emb_by_id = {1: [0.9, 0.0], 2: [0.3, 0.0]}
        memories = self._recall(children, emb_by_id, [1.0, 0.0], self._parents(5))
        contents = [m["content"] for m in memories]
        assert len(memories) == 1
        assert memories[0]["content"] == "记忆0"
        assert "记忆1" not in contents  # 不注入"本批相对高但绝对烂"的低分记忆

    def test_all_candidates_low_score_returns_empty(self):
        children = self._children([0.2, 0.3])
        emb_by_id = {1: [0.2, 0.0], 2: [0.3, 0.0]}
        memories = self._recall(children, emb_by_id, [1.0, 0.0], self._parents(5))
        assert memories == []  # 全部低于 min_score → 空（不崩）

    def test_empty_candidates_returns_empty(self):
        async def run():
            with mock.patch("rag.memory.hybrid_retriever") as ret:
                ret.retrieve = mock.AsyncMock(return_value=[])
                with mock.patch.object(memory_service, "_expand_to_parents",
                                       new=mock.AsyncMock()) as expand:
                    assert await memory_service.recall("q", "42") == []
                    expand.assert_not_called()
        asyncio.run(run())

    def test_embedding_failure_degrades_to_hybrid_score(self):
        children = self._children([0.5] * 5)

        async def run():
            with mock.patch("rag.memory.hybrid_retriever") as ret:
                ret.retrieve = mock.AsyncMock(return_value=children)
                with mock.patch("rag.memory.embedding_service") as emb:
                    emb.embed_text = mock.AsyncMock(side_effect=RuntimeError("embed down"))
                    with mock.patch("rag.memory.async_session_factory",
                                    _fake_factory(_FakeSession(scalars=self._parents(5)))):
                        return await memory_service.recall("q", "42", top_k=5)
        memories = asyncio.run(run())
        # 降级不回退失败：用原 hybrid_score 均值（0.5 < 0.75 → K=1）
        assert len(memories) == 1
        assert memories[0]["score"] == 0.5


class TestRecallShortAbsCosine:
    """module-035：recall_short 动态 K 绝对余弦口径（与长期 recall 一致）"""

    def test_recall_short_abs_cosine_reaches_three(self):
        children = [
            {"id": i + 1, "content": f"子{i}", "parent_id": i + 1, "hybrid_score": 0.5}
            for i in range(5)
        ]
        emb_by_id = {i + 1: [0.78, 0.0] for i in range(5)}
        parents = [
            mock.MagicMock(id=i + 1, content=f"短记忆{i}", title=f"t{i}",
                           created_at=datetime.now())
            for i in range(5)
        ]

        async def run():
            with mock.patch("rag.memory.hybrid_retriever") as ret:
                ret.retrieve = mock.AsyncMock(return_value=children)
                with mock.patch("rag.memory.embedding_service") as emb:
                    emb.embed_text = mock.AsyncMock(return_value=[1.0, 0.0])
                    with mock.patch.object(memory_service, "_child_embeddings",
                                           new=mock.AsyncMock(return_value=emb_by_id)):
                        with mock.patch("rag.memory.async_session_factory",
                                        _fake_factory(_FakeSession(scalars=parents))):
                            return await memory_service.recall_short("q", "42", top_k=5)
        memories = asyncio.run(run())
        # 绝对余弦均值 0.78 ∈ [0.75,0.85) → K=3（created_at=now 未超 TTL，全部保留）
        assert len(memories) == 3


class TestChildEmbeddings:
    """module-035：_child_embeddings 按子块 id 批量取存储 embedding"""

    def test_fetches_embeddings_by_child_ids(self):
        row1 = mock.MagicMock(id=1, embedding=[0.9, 0.0])
        row2 = mock.MagicMock(id=2, embedding=[0.8, 0.0])
        captured = {}

        class _CaptureSession(_FakeSession):
            async def execute(self, stmt):
                captured["stmt"] = stmt
                return await super().execute(stmt)

        async def run():
            with mock.patch("rag.memory.async_session_factory",
                            _fake_factory(_CaptureSession(all_rows=[row1, row2]))):
                return await memory_service._child_embeddings([{"id": 1}, {"id": 2}])

        emb_map = asyncio.run(run())
        sql = str(captured["stmt"].compile(compile_kwargs={"literal_binds": True}))
        assert "IN (1, 2)" in sql or "IN (2, 1)" in sql
        assert emb_map == {1: [0.9, 0.0], 2: [0.8, 0.0]}

    def test_no_ids_returns_empty_without_db(self):
        async def run():
            with mock.patch("rag.memory.async_session_factory") as fac:
                assert await memory_service._child_embeddings([]) == {}
                fac.assert_not_called()
        asyncio.run(run())

    def test_db_failure_returns_empty(self):
        async def run():
            with mock.patch("rag.memory.async_session_factory",
                            mock.MagicMock(side_effect=RuntimeError("db down"))):
                assert await memory_service._child_embeddings([{"id": 1}]) == {}
        asyncio.run(run())


class TestDedupThreshold035:
    """module-035：去重阈值 0.85 校准（同义改写触发 / 不同事实不触发）"""

    def test_synonym_paraphrase_cosine_088_triggers_dedup(self):
        # 真实 bge-m3 同义改写 cosine≈0.88 > 0.85 → 触发去重（更新而非新增，条数不涨）
        existing = mock.MagicMock(id=7, parent_id=5, embedding=[0.88, 0.0, 0.0])

        async def run():
            with mock.patch("rag.memory.embedding_service") as emb:
                emb.embed_text = mock.AsyncMock(return_value=[1.0, 0.0, 0.0])
                with mock.patch("rag.memory.async_session_factory",
                                _fake_factory(_FakeSession(scalars=[existing]))):
                    dup = await memory_service._find_duplicate("同义新措辞", "42")
            assert dup is not None  # 0.88 > 0.85 → 命中重复
        asyncio.run(run())

    def test_distinct_fact_cosine_080_no_dedup(self):
        existing = mock.MagicMock(id=7, parent_id=5, embedding=[0.80, 0.0, 0.0])

        async def run():
            with mock.patch("rag.memory.embedding_service") as emb:
                emb.embed_text = mock.AsyncMock(return_value=[1.0, 0.0, 0.0])
                with mock.patch("rag.memory.async_session_factory",
                                _fake_factory(_FakeSession(scalars=[existing]))):
                    dup = await memory_service._find_duplicate("不同事实", "42")
            assert dup is None  # 0.80 ≤ 0.85 → 不同事实，正常新增
        asyncio.run(run())


class TestConfig035:
    """module-035：分数口径配置默认值"""

    def test_dedup_threshold_and_min_score_defaults(self):
        assert settings.memory_dedup_threshold == 0.85   # 0.95 → 0.85（真实同义改写可触发）
        assert settings.memory_recall_min_score == 0.4   # 低分过滤阈值（绝对余弦口径）
        assert settings.memory_recall_high_threshold == 0.85  # 动态 K 档位阈值不变
        assert settings.memory_recall_mid_threshold == 0.75
