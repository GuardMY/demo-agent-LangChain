"""
RAG (检索增强生成) 模块

功能：
- 文档加载（txt, md, py, pdf）
- 文本分块
- 向量嵌入 (OpenAI / 本地)
- Chroma 向量存储
- 语义检索
- 作为工具注入 Agent

用法:
    from rag import RAGEngine
    rag = RAGEngine()
    rag.ingest_file("docs/report.txt")
    results = rag.search("关键词")
"""

import os
from pathlib import Path
from typing import List, Optional

from logger import get_logger

log = get_logger(__name__)


class SimpleRAGEngine:
    """
    轻量 RAG 引擎 — 基于关键词 + TF-IDF 相似度

    无需外部向量数据库，适合快速原型。
    生产环境可替换为 Chroma + OpenAI Embeddings。
    """

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 100):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._documents: List[str] = []
        self._sources: List[str] = []
        self._chunks: List[str] = []

    def ingest_text(self, text: str, source: str = "inline") -> int:
        """摄入文本"""
        chunks = self._split(text)
        for chunk in chunks:
            self._chunks.append(chunk)
            self._sources.append(source)
        self._documents.append(text)
        log.info(f"RAG 摄入: {source} ({len(chunks)} chunks)")
        return len(chunks)

    def ingest_file(self, file_path: str) -> int:
        """摄入文件"""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")
        # PDF 支持
        if path.suffix.lower() == ".pdf":
            try:
                from PyPDF2 import PdfReader
                reader = PdfReader(str(path))
                text = "\n".join(p.extract_text() or "" for p in reader.pages)
            except ImportError:
                text = path.read_text(encoding="utf-8", errors="ignore")
                log.warning("PyPDF2 未安装，PDF 按纯文本读取")
        else:
            text = path.read_text(encoding="utf-8", errors="ignore")
        return self.ingest_text(text, str(path))

    def ingest_directory(self, dir_path: str, glob_pattern: str = "*.{txt,md,py}") -> int:
        """摄入目录中的所有匹配文件"""
        import glob
        total = 0
        for pattern in glob_pattern.split(","):
            for f in Path(dir_path).rglob(pattern.strip()):
                try:
                    total += self.ingest_file(str(f))
                except Exception as e:
                    log.warning(f"跳过 {f}: {e}")
        return total

    def search(self, query: str, top_k: int = 5) -> List[dict]:
        """
        搜索最相关的文档片段

        Returns:
            [{"content": "...", "source": "...", "score": 0.95}, ...]
        """
        if not self._chunks:
            return [{"content": "知识库为空，请先摄入文档。", "source": "system", "score": 0}]

        # TF-IDF 风格的关键词匹配
        query_terms = set(query.lower().split())
        scored = []
        for i, chunk in enumerate(self._chunks):
            chunk_lower = chunk.lower()
            # 命中率
            hits = sum(1 for t in query_terms if t in chunk_lower)
            if hits == 0:
                continue
            # TF-IDF 近似：命中词数 * 密度加权
            density = hits / max(len(chunk_lower.split()), 1)
            score = hits * 0.6 + density * 100 * 0.4
            scored.append((score, i))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, idx in scored[:top_k]:
            results.append({
                "content": self._chunks[idx][:1000],
                "source": self._sources[idx],
                "score": round(score, 3),
            })
        return results

    def _split(self, text: str) -> List[str]:
        """简单分块（按段落 + 大小限制）"""
        paragraphs = text.split("\n\n")
        chunks = []
        current = ""
        for p in paragraphs:
            if len(current) + len(p) < self.chunk_size:
                current += ("\n\n" if current else "") + p
            else:
                if current:
                    chunks.append(current)
                current = p if len(p) < self.chunk_size else p[:self.chunk_size]
        if current:
            chunks.append(current)
        return chunks

    @property
    def stats(self) -> dict:
        return {"documents": len(self._documents), "chunks": len(self._chunks),
                "sources": list(set(self._sources))[:10]}


# 全局实例
rag_engine = SimpleRAGEngine()


# ==================== RAG 工具（可注册到 Agent） ====================

class RAGSearchTool:
    """RAG 搜索工具 — 适配 LangChain"""
    name = "knowledge_search"
    description = "搜索本地知识库。当用户询问文档、报告、内部资料时使用。输入为搜索关键词。"

    def run(self, query: str) -> str:
        results = rag_engine.search(query.strip(), top_k=3)
        if not results or results[0]["score"] == 0:
            return "知识库中未找到相关信息。"
        formatted = []
        for i, r in enumerate(results, 1):
            formatted.append(f"[{i}] (相关度: {r['score']:.2f})\n{r['content'][:300]}...\n来源: {r['source']}\n")
        return "\n".join(formatted)


class RAGIngestTool:
    """RAG 摄入工具"""
    name = "knowledge_ingest"
    description = "将文件摄入知识库。输入为文件路径。"

    def run(self, file_path: str) -> str:
        try:
            count = rag_engine.ingest_file(file_path.strip())
            return f"成功摄入: {file_path} ({count} chunks)"
        except Exception as e:
            return f"摄入失败: {str(e)}"
