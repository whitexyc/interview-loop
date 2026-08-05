"""Module-034 会话记忆持久化单元测试

覆盖（验收 §4.1 test_session_memory.py：会话保存/恢复/隔离/TTL）：
- save_session_messages：写入 source='memory:<identity>:session:'（按身份隔离）、
  空消息/空 content 跳过、content_hash 去重幂等、超上限滚动删除最旧
- get_session_messages：恢复最近会话（时间升序、limit 截断）、按身份隔离、
  无记录返回空列表
- 身份规范化：通配符 identity 降级 'unknown'（复用 memory._normalize_identity）

实现说明：mock async_session_factory 打桩 AsyncSession（按语句类型路由结果），
不依赖真实数据库；同步用例内 asyncio.run 执行（与套件同款模式）。
"""
import asyncio
import hashlib
from unittest import mock

from rag.models import Document
from rag.session_memory import session_memory_service, _session_source
from src.config import settings


class _FakeSession:
    """假 AsyncSession：按语句类型路由 execute 结果 + 记录 add / delete"""

    def __init__(self, existing_hashes=None, session_count=0, oldest_ids=(), docs=None):
        self.added: list = []
        self.existing_hashes = list(existing_hashes or [])
        self.session_count = session_count
        self.oldest_ids = list(oldest_ids)
        self.docs = list(docs or [])
        self.deleted_stmts = []

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def execute(self, stmt):
        sql = str(stmt).lower()
        result = mock.MagicMock()
        if "count(" in sql:
            result.scalar.return_value = self.session_count
        elif "delete" in sql:
            self.deleted_stmts.append(stmt)
        elif "order by" in sql:
            # get_session_messages（全列）与 _trim 的 id 查询都带 ORDER BY；
            # 全列查询用 scalars().all()（docs），id 查询用 all()（oldest_ids）
            result.all.return_value = [(i,) for i in self.oldest_ids]
            result.scalars.return_value = mock.MagicMock(
                all=mock.MagicMock(return_value=self.docs),
            )
        elif "content_hash" in sql:
            # save 的去重幂等查询：select(Document.content_hash)，无 ORDER BY
            result.all.return_value = [(h,) for h in self.existing_hashes]
        else:
            result.all.return_value = [(i,) for i in self.oldest_ids]
        return result


def _fake_factory(session):
    """把 async_session_factory 打桩成返回 session 的异步上下文管理器"""
    cm = mock.MagicMock()
    cm.__aenter__ = mock.AsyncMock(return_value=session)
    cm.__aexit__ = mock.AsyncMock(return_value=False)
    return mock.MagicMock(return_value=cm)


class TestSessionSource:
    """_session_source：source='memory:<identity>:session:'"""

    def test_session_source_format(self):
        assert _session_source("42") == "memory:42:session:"
        assert _session_source("1.1.1.1") == "memory:1.1.1.1:session:"
        # 与长期/短期 source 互不混淆
        assert _session_source("42") != "memory:42:"
        assert _session_source("42") != "memory:42:short:"


class TestSaveSession:
    """save_session_messages：写入 / 幂等 / 上限滚动"""

    def test_save_writes_session_source_with_roles(self):
        async def run():
            fs = _FakeSession(existing_hashes=[])
            with mock.patch("rag.session_memory.async_session_factory", _fake_factory(fs)):
                n = await session_memory_service.save_session_messages("42", [
                    {"role": "user", "content": "你好"},
                    {"role": "assistant", "content": "你好！"},
                ])
            assert n == 2
            # 父/子无 embedding 平铺一条消息，source='memory:42:session:'（与长期/短期区分）
            assert {getattr(d, "source", None) for d in fs.added} == {"memory:42:session:"}
            titles = sorted(d.title for d in fs.added)
            assert titles == ["session:assistant", "session:user"]
            assert {d.content for d in fs.added} == {"你好", "你好！"}
        asyncio.run(run())

    def test_save_empty_messages_returns_zero(self):
        async def run():
            with mock.patch("rag.session_memory.async_session_factory") as fac:
                assert await session_memory_service.save_session_messages("42", []) == 0
                fac.assert_not_called()  # 空消息不碰 DB
        asyncio.run(run())

    def test_save_skips_empty_content_and_duplicate_hash(self):
        digest = hashlib.sha256("你好".encode("utf-8")).hexdigest()

        async def run():
            fs = _FakeSession(existing_hashes=[digest])
            with mock.patch("rag.session_memory.async_session_factory", _fake_factory(fs)):
                n = await session_memory_service.save_session_messages("42", [
                    {"role": "user", "content": "你好"},   # content_hash 重复 → 跳过
                    {"role": "user", "content": "   "},    # 空 content → 跳过
                    {"role": "user", "content": "新问题"},  # 新增
                ])
            assert n == 1
            assert [d.content for d in fs.added] == ["新问题"]
        asyncio.run(run())

    def test_save_trims_oldest_when_over_cap(self):
        """每 identity 会话超上限滚动删除最旧（防止 documents 表膨胀）"""
        cap = settings.memory_session_max_messages

        async def run():
            fs = _FakeSession(existing_hashes=[], session_count=cap + 2, oldest_ids=[1, 2])
            with mock.patch("rag.session_memory.async_session_factory", _fake_factory(fs)):
                n = await session_memory_service.save_session_messages("42", [
                    {"role": "user", "content": "新问题"},
                ])
            assert n == 1
            # 超限 2 条 → 发起一次 DELETE（删除最旧 id 1、2）
            assert len(fs.deleted_stmts) == 1
            assert "id IN" in str(fs.deleted_stmts[0])
        asyncio.run(run())

    def test_save_wildcard_identity_normalized(self):
        """通配符 identity 降级 'unknown'（复用 memory._normalize_identity）"""
        async def run():
            fs = _FakeSession(existing_hashes=[])
            with mock.patch("rag.session_memory.async_session_factory", _fake_factory(fs)):
                await session_memory_service.save_session_messages("%", [
                    {"role": "user", "content": "x"},
                ])
            assert {getattr(d, "source", None) for d in fs.added} == {"memory:unknown:session:"}
        asyncio.run(run())


class TestGetSession:
    """get_session_messages：恢复 / limit / 隔离 / 空"""

    def test_get_returns_ordered_recent(self):
        docs = [
            Document(title="session:user", content="第一轮"),
            Document(title="session:assistant", content="答复一"),
            Document(title="session:user", content="第二轮"),
        ]

        async def run():
            fs = _FakeSession(docs=docs)
            with mock.patch("rag.session_memory.async_session_factory", _fake_factory(fs)):
                msgs = await session_memory_service.get_session_messages("42", limit=10)
            assert msgs == [
                {"role": "user", "content": "第一轮"},
                {"role": "assistant", "content": "答复一"},
                {"role": "user", "content": "第二轮"},
            ]
        asyncio.run(run())

    def test_get_respects_limit(self):
        docs = [Document(title="session:user", content=f"消息{i}") for i in range(5)]

        async def run():
            fs = _FakeSession(docs=docs)
            with mock.patch("rag.session_memory.async_session_factory", _fake_factory(fs)):
                msgs = await session_memory_service.get_session_messages("42", limit=2)
            assert [m["content"] for m in msgs] == ["消息3", "消息4"]  # 最近 2 条
        asyncio.run(run())

    def test_get_isolated_by_identity(self):
        """恢复只查本身份会话：SQL 按 source='memory:<identity>:session:' 过滤"""
        captured = {}

        class _CaptureSession(_FakeSession):
            async def execute(self, stmt):
                captured["stmt"] = stmt
                return await super().execute(stmt)

        async def run():
            with mock.patch("rag.session_memory.async_session_factory",
                            _fake_factory(_CaptureSession(docs=[]))):
                await session_memory_service.get_session_messages("42")

        asyncio.run(run())
        sql = str(captured["stmt"].compile(compile_kwargs={"literal_binds": True}))
        assert "memory:42:session:" in sql
        assert "memory:43:session:" not in sql  # 不含他人身份

    def test_get_empty_returns_empty(self):
        async def run():
            fs = _FakeSession(docs=[])
            with mock.patch("rag.session_memory.async_session_factory", _fake_factory(fs)):
                assert await session_memory_service.get_session_messages("42") == []
        asyncio.run(run())

    def test_get_failure_returns_empty(self):
        """恢复失败 → 返回空列表（调用方降级用当前请求 history，零回归）"""
        async def run():
            sess = mock.MagicMock()
            sess.__aenter__ = mock.AsyncMock(side_effect=RuntimeError("db down"))
            sess.__aexit__ = mock.AsyncMock(return_value=False)
            with mock.patch("rag.session_memory.async_session_factory",
                            mock.MagicMock(return_value=sess)):
                assert await session_memory_service.get_session_messages("42") == []
        asyncio.run(run())
