"""
Markdown 文档分块器 — 预处理层
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

在整个 RAG 链路中的位置：
  文档入库 → [Chunker] 按标题分块 → [EmbeddingService] 逐块向量化 → 入库

为什么需要分块？
  之前整篇文档入库，一个长文档只产生一个 embedding 向量。
  当文档包含多个主题（如"G1 GC"和"Kafka"在同一篇笔记中），
  检索时难以精确命中用户需要的部分。

  按 Markdown 标题分块后：
  - 每个段落独立 embedding，语义更聚焦
  - 用户搜"G1 GC Region分区"时，只返回相关的块而非整篇文章
  - 引用时也更精确（可以引用到具体章节）

实现：
  使用 LangChain 的 MarkdownHeaderTextSplitter，按 ##（二级标题）分割，
  保留标题层级作为 metadata，方便追溯来源。
"""
import logging
from typing import Optional

from langchain_text_splitters import MarkdownHeaderTextSplitter

logger = logging.getLogger(__name__)


class MarkdownChunker:
    """Markdown 文档分块器

    基于 LangChain MarkdownHeaderTextSplitter，按 ## 标题分割文档。
    每块附带标题层级信息，便于前端展示和引用溯源。

    为什么用 LangChain 而不是手写正则？
    1. 成熟的分割逻辑，处理了标题嵌套、代码块等边界情况
    2. 保留标题层级 metadata（如 {"section": "G1 GC"}）
    3. 可与其他 LangChain 组件（如 RecursiveCharacterTextSplitter）组合使用
    """

    def __init__(
        self,
        headers_to_split_on: Optional[list[tuple[str, str]]] = None,
        min_chars: int = 50,
    ):
        """
        Args:
            headers_to_split_on: 按哪些标题分割，默认 [("##", "section")]
            min_chars: 最小块字符数，低于此值的块被过滤
        """
        self._headers_to_split_on = headers_to_split_on or [("##", "section")]
        self._min_chars = min_chars
        self._splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=self._headers_to_split_on,
        )

    def chunk(self, text: str, source: str = "") -> list[dict[str, str]]:
        """将 Markdown 文本分割为块

        Args:
            text: Markdown 原文
            source: 来源标识（仅用于日志）

        Returns:
            每块包含 title（标题路径）和 content（块内容）
        """
        if not text or not text.strip():
            return []

        # LangChain 返回 Document 列表，每项有 page_content 和 metadata
        langchain_docs = self._splitter.split_text(text)

        chunks = []
        for doc in langchain_docs:
            content = doc.page_content.strip()
            if len(content) < self._min_chars:
                continue

            # 从 metadata 构建标题路径
            # MarkdownHeaderTextSplitter 的 metadata 格式：
            # {"section": "G1 GC", ...} 键名对应 headers_to_split_on 的值
            title_parts = []
            for _, header_name in self._headers_to_split_on:
                val = doc.metadata.get(header_name, "")
                if val:
                    title_parts.append(val)

            title = " > ".join(title_parts) if title_parts else ""
            chunks.append({"title": title, "content": content})

        logger.debug("分块: source=%s, input=%d chars, output=%d chunks",
                      source, len(text), len(chunks))
        return chunks


# 全局单例
chunker = MarkdownChunker()
