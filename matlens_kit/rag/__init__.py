"""本地文献知识库 RAG 核心（FAISS + 复用主 provider 嵌入 + pdfplumber）。"""

from matlens_kit.rag.kb import (
    Embedder,
    KnowledgeBase,
    KnowledgeManager,
    VectorStore,
    knowledge_root,
)

__all__ = ["Embedder", "KnowledgeBase", "KnowledgeManager", "VectorStore", "knowledge_root"]
