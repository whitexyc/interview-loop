"""
Markdown 文档分块器 — 预处理层（父子分块）
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

在整个 RAG 链路中的位置：
  文档入库 → [Chunker] 两级分块 → [EmbeddingService] 子块向量化 → 入库

为什么需要两级分块？
  父块（section 级）：按 ## 标题分割，保持完整的段落语义，无向量，
     检索时不参与，但作为最终返回给用户的粒度。
  子块（~300 字符）：对每个父块内容二次分割，携带向量嵌入，
     参与混合检索（FTS + 向量），命中后通过 parent_id 映射回父块。

  这种方式结合了检索精度（小块更聚焦）和展示完整性（父块语义完整）。

实现：
  使用 LangChain 的 MarkdownHeaderTextSplitter（一级：按 ## 标题）
  和 RecursiveCharacterTextSplitter（二级：按语义边界）。
"""
import logging
from typing import Optional

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)


class MarkdownChunker:
    """Markdown 文档分块器（父子两级）

    第一级：MarkdownHeaderTextSplitter 按 ## 标题分割 → 父块
    第二级：RecursiveCharacterTextSplitter 对每父块二次分割 → 子块

    为什么用 LangChain 而不是手写正则？
    1. 成熟的分割逻辑，处理了标题嵌套、代码块等边界情况
    2. 保留标题层级 metadata（如 {"section": "G1 GC"}）
    3. RecursiveCharacterTextSplitter 按语义边界（段落、句子）分割
    """

    def __init__(
        self,
        headers_to_split_on: Optional[list[tuple[str, str]]] = None,
        min_chars: int = 50,
        child_chunk_size: int = 300,
        child_chunk_overlap: int = 50,
    ):
        """
        Args:
            headers_to_split_on: 按哪些标题分割，默认 [("##", "section")]
            min_chars: 最小块字符数，低于此值的父块被过滤
            child_chunk_size: 子块目标字符数
            child_chunk_overlap: 相邻子块重叠字符数
        """
        self._headers_to_split_on = headers_to_split_on or [("##", "section")]
        self._min_chars = min_chars
        self._splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=self._headers_to_split_on,
        )
        self._child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=child_chunk_size,
            chunk_overlap=child_chunk_overlap,
            separators=["\n\n", "\n", "。", ".", " ", ""],
        )

    def chunk(self, text: str, source: str = "") -> dict:
        """将 Markdown 文本两级分割为父块和子块

        Args:
            text: Markdown 原文
            source: 来源标识（仅用于日志）

        Returns:
            {
                "parents": [{"title": str, "content": str}, ...],
                "children": [{"title": str, "content": str, "parent_index": int}, ...]
            }
        """
        if not text or not text.strip():
            return {"parents": [], "children": []}

        # ===== 第一级：按 ## 标题分割 → 父块 =====
        langchain_docs = self._splitter.split_text(text)

        parents = []
        for doc in langchain_docs:
            content = doc.page_content.strip()
            if len(content) < self._min_chars:
                continue

            # 从 metadata 构建标题路径
            title_parts = []
            for _, header_name in self._headers_to_split_on:
                val = doc.metadata.get(header_name, "")
                if val:
                    title_parts.append(val)

            title = " > ".join(title_parts) if title_parts else ""
            parents.append({"title": title, "content": content})

        # 无 ## 标题或全部被 min_chars 过滤 → fallback
        # 无标题时整个文档作为单一父块；全过滤时由 add_document 兜底
        if not parents:
            logger.debug("分块: source=%s, 无有效父块（返回空，由引擎兜底）", source)
            return {"parents": [], "children": []}

        # ===== 第二级：对每父块用 RecursiveCharacterTextSplitter 分割 → 子块 =====
        children = []
        for pi, parent in enumerate(parents):
            child_texts = self._child_splitter.split_text(parent["content"])
            for ct in child_texts:
                child_content = ct.strip()
                if not child_content:
                    continue
                children.append({
                    "title": parent["title"],
                    "content": child_content,
                    "parent_index": pi,
                })

        logger.debug("分块: source=%s, input=%d chars, parents=%d, children=%d",
                      source, len(text), len(parents), len(children))
        return {"parents": parents, "children": children}


# 全局单例
chunker = MarkdownChunker()
