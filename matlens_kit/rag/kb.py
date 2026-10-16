"""本地文献 RAG 核心实现。

技术栈：FAISS 向量库 + 复用主模型 provider 的 OpenAI 兼容嵌入端点 + pdfplumber 解析。
数据默认存 ~/.matlens/knowledge/<kb_name>/，全程本地可控。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# 与 settings_store.DEFAULTS["kb"]["root"] 一致的默认值字面量
_DEFAULT_KB_ROOT = "~/.matlens/knowledge"


def _kb_settings() -> dict:
    """动作时刻实时读取 kb 设置段（唯一入口：settings_store.get_section）。

    在「新建知识库 / 导入文档 / 解析 PDF」动作发生时调用，保证改设置后
    下一次动作立即生效，而不是模块 import 时固化。
    """
    try:
        from matlens_kit import settings_store

        return settings_store.get_section("kb")
    except Exception:
        return {}


def knowledge_root() -> Path:
    """知识库根目录。

    - kb.root 在设置里被显式配置（且不是默认字面量）：用它，os.path.expanduser 展开 ~；
    - 否则跟随 MATLENS_HOME / profile 默认根目录（<matlens_home>/knowledge），
      保证 profile 与测试隔离不被默认值破坏。
    """
    root = _kb_settings().get("root")
    if root and root != _DEFAULT_KB_ROOT:
        return Path(os.path.expanduser(str(root)))
    home = os.environ.get("MATLENS_HOME") or os.path.expanduser("~/.matlens")
    return Path(home) / "knowledge"


# ─────────────────────────────────────────────────────────────
# 嵌入（复用主 provider 的 OpenAI 兼容端点）
# ─────────────────────────────────────────────────────────────
class Embedder:
    """嵌入向量器：默认走主 provider 配置的 OpenAI 兼容嵌入端点。

    若未配置嵌入服务，降级为基于字符 n-gram 的本地哈希嵌入
    （保证离线场景仍可用，向量为确定性低维特征）。
    """

    def __init__(self, base_url: str = "", api_key: str = "", model: str = "") -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.model = model or "text-embedding-3-small"
        self._client = None
        self._local_fallback = not (base_url and api_key)

    def _ensure_client(self):
        if self._client is None and not self._local_fallback:
            try:
                from openai import OpenAI

                self._client = OpenAI(base_url=self.base_url, api_key=self.api_key)
                # 探活：无嵌入模型时报错则降级本地
                self._client.embeddings.create(model=self.model, input="ping")
            except Exception:
                self._client = None
                self._local_fallback = True
        return self._client

    def embed(self, texts: List[str]) -> List[List[float]]:
        """批量嵌入文本，返回向量列表。"""
        if not texts:
            return []
        client = self._ensure_client()
        if client is not None:
            try:
                resp = client.embeddings.create(model=self.model, input=texts)
                return [d.embedding for d in resp.data]
            except Exception:
                self._local_fallback = True
        return [self._local_embed(t) for t in texts]

    @staticmethod
    def _local_embed(text: str, dim: int = 384) -> List[float]:
        """本地降级嵌入：字符 n-gram 哈希特征（确定性、无需外部服务）。"""
        vec = [0.0] * dim
        tokens = re.findall(r"[\u4e00-\u9fff]|[a-zA-Z]+|\d+", text.lower())
        for tok in tokens:
            for gram in (tok[i : i + 3] for i in range(max(1, len(tok) - 2))):
                idx = int(hashlib.md5(gram.encode("utf-8")).hexdigest()[:8], 16) % dim
                vec[idx] += 1.0
        norm = sum(v * v for v in vec) ** 0.5
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec


# ─────────────────────────────────────────────────────────────
# 向量存储（FAISS，不可用时降级 numpy）
# ─────────────────────────────────────────────────────────────
try:
    import faiss  # type: ignore

    _FAISS_AVAILABLE = True
except Exception:  # pragma: no cover - 离线/未装 faiss 环境
    faiss = None  # type: ignore
    _FAISS_AVAILABLE = False


class VectorStore:
    """向量库 + 文档元数据（持久化到知识库目录）。

    优先使用 FAISS IndexFlatIP；若环境未安装 faiss，自动降级为
    纯 numpy 余弦相似度检索（向量已 L2 归一化，点积即余弦），
    保证离线场景仍可入库与检索。
    """

    def __init__(self, kb_dir: Path, dim: int = 384) -> None:
        self.kb_dir = kb_dir
        self.index_path = kb_dir / "index.faiss"
        self.vectors_path = kb_dir / "vectors.npy"
        self.meta_path = kb_dir / "chunks.json"
        self.index = None
        self.dim = dim
        self.chunks: List[Dict[str, Any]] = []
        self._np_vectors: Any = None  # numpy 降级存储
        self._use_faiss = _FAISS_AVAILABLE
        self._load()

    def _load(self) -> None:
        self.kb_dir.mkdir(parents=True, exist_ok=True)
        if self._use_faiss:
            if self.index_path.exists():
                try:
                    self.index = faiss.read_index(str(self.index_path))
                    self.dim = self.index.d
                except Exception:
                    self.index = None
            if self.index is None:
                self.index = faiss.IndexFlatIP(self.dim)
        else:
            # numpy 降级：从 vectors.npy 恢复
            import numpy as _np

            if self.vectors_path.exists():
                try:
                    self._np_vectors = _np.load(str(self.vectors_path))
                    self.dim = int(self._np_vectors.shape[1])
                except Exception:
                    self._np_vectors = None
            if self._np_vectors is None:
                self._np_vectors = _np.zeros((0, self.dim), dtype="float32")
        if self.meta_path.exists():
            try:
                self.chunks = json.loads(self.meta_path.read_text(encoding="utf-8"))
            except Exception:
                self.chunks = []

    def add(self, vectors: List[List[float]], chunks: List[Dict[str, Any]]) -> None:
        """追加向量与文档块并持久化。"""
        if not vectors:
            return
        import numpy as np

        arr = np.asarray(vectors, dtype="float32")
        if self._use_faiss:
            self.index.add(arr)
        else:
            self._np_vectors = (
                arr if self._np_vectors is None else np.vstack([self._np_vectors, arr])
            )
        self.chunks.extend(chunks)
        self._save()

    def search(self, query_vec: List[float], top_k: int = 5) -> List[Tuple[Dict[str, Any], float]]:
        """相似度检索，返回 (chunk, score)。"""
        import numpy as np

        if not self.chunks:
            return []
        k = min(top_k, len(self.chunks))
        if self._use_faiss:
            scores, idxs = self.index.search(np.asarray([query_vec], dtype="float32"), k)
            results = []
            for score, idx in zip(scores[0], idxs[0]):
                if idx >= 0 and idx < len(self.chunks):
                    results.append((self.chunks[int(idx)], float(score)))
            return results
        # numpy 降级：点积（向量已归一化）即余弦相似度
        q = np.asarray([query_vec], dtype="float32")
        if self._np_vectors is None or self._np_vectors.shape[0] == 0:
            return []
        sims = (self._np_vectors @ q.T).ravel()
        order = np.argsort(-sims)[:k]
        return [(self.chunks[int(i)], float(sims[int(i)])) for i in order if int(i) < len(self.chunks)]

    def _save(self) -> None:
        if self._use_faiss:
            faiss.write_index(self.index, str(self.index_path))
        else:
            import numpy as _np

            _np.save(str(self.vectors_path), self._np_vectors)
        self.meta_path.write_text(
            json.dumps(self.chunks, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    def remove_doc(self, doc_id: str) -> int:
        """移除某篇文献的全部分块，返回被移除的分块数。

        为什么需要（2026-10-15 新增）：此前误传一份文献只能整库删除重建，
        而库里往往已有几十篇精读过的东西 —— 这是知识库最痛的缺失。

        实现要点：chunks / 向量 / faiss index 三者按行一一对应，
        故先算保留行号，再对**两条后端路径**分别剔除：
          - faiss：IndexFlatIP 用 IndexIDMap 重建（reconstruct 逐行取回）
          - numpy：直接按行索引取子矩阵
        不引入 reconstruct 之外的 faiss API，保证旧版本 faiss-cpu 也能跑。
        """
        import numpy as np

        keep = [i for i, c in enumerate(self.chunks) if str(c.get("doc_id")) != str(doc_id)]
        removed = len(self.chunks) - len(keep)
        if removed == 0:
            return 0

        if self._use_faiss and self.index is not None:
            try:
                n = self.index.ntotal
                vecs = np.empty((n, self.index.d), dtype="float32")
                for i in range(n):
                    self.index.reconstruct(i, vecs[i])
                new_index = faiss.IndexFlatIP(self.index.d)
                if keep:
                    new_index.add(np.ascontiguousarray(vecs[keep], dtype="float32"))
                self.index = new_index
            except Exception:
                # faiss 重建失败时退化为「仅清元数据」并重建空索引，
                # 避免 chunks 与向量错位导致后续检索返回错文献
                self.index = faiss.IndexFlatIP(self.dim)
        else:
            src = self._np_vectors
            if src is not None and getattr(src, "shape", (0,))[0] > 0:
                dim = src.shape[1]
                # 向量行数可能少于 chunks（历史异常），行号越界的行保留原有行为
                valid_keep = [i for i in keep if i < src.shape[0]]
                out = (np.ascontiguousarray(src[valid_keep], dtype="float32")
                       if valid_keep else np.zeros((0, dim), dtype="float32"))
            else:
                out = np.zeros((0, self.dim), dtype="float32")
            self._np_vectors = out

        self.chunks = [self.chunks[i] for i in keep]
        self._save()
        return removed

    def size(self) -> int:
        return len(self.chunks)


# ─────────────────────────────────────────────────────────────
# 文献导入（PDF/TXT/Markdown）
# ─────────────────────────────────────────────────────────────
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


def _split_text(
    text: str,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
) -> List[str]:
    """按段落分块（优先在句号/分号边界切分）。

    chunk_size / chunk_overlap 缺省时在调用时刻实时读 kb 设置
    （默认 800 / 100）——导入文档时改设置即对新导入生效。
    """
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    if chunk_size is None or chunk_overlap is None:
        kb = _kb_settings()
        if chunk_size is None:
            chunk_size = int(kb.get("chunk_size") or CHUNK_SIZE)
        if chunk_overlap is None:
            ov = kb.get("chunk_overlap")
            chunk_overlap = int(ov) if ov is not None else CHUNK_OVERLAP
    chunks: List[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_size, n)
        if end < n:
            # 尽量在句号/分号处断开
            cut = text.rfind("。", start + chunk_size // 2, end)
            if cut == -1:
                cut = text.rfind(".", start + chunk_size // 2, end)
            if cut == -1:
                cut = text.rfind(";", start + chunk_size // 2, end)
            if cut != -1:
                end = cut + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(end - chunk_overlap, start + 1)
    return chunks


def _page_text_with_tables(page_text: str, tables: Any) -> str:
    """把 pdfplumber ``page.extract_tables()`` 的行文本拼到页面正文之后。

    - page_text：该页 ``extract_text()`` 结果（可能为空）；
    - tables：``extract_tables()`` 返回（list[list] 或 None）。
    单元格跳过空值/空串，每行用 ``" | "`` 连接；表格为空/None 时只返回正文。
    单独成函数便于对 table_extract 开关做单测。
    """
    parts: List[str] = [page_text or ""]
    for row in tables or []:
        cells = []
        for c in row or []:
            s = "" if c is None else str(c).strip()
            if s:
                cells.append(s)
        if cells:
            parts.append(" | ".join(cells))
    return "\n".join(p for p in parts if p)


def extract_text(path: str, table_extract: Optional[bool] = None) -> str:
    """按扩展名提取文本（PDF → pdfplumber，TXT/MD → 直接读）。

    table_extract 缺省时实时读 kb.table_extract：为 True 时在 PDF 正文之外
    额外抽取页面表格行文本拼入；表格抽取抛错/表格缺失时安全降级为仅正文。
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"文件不存在：{path}")
    if p.suffix.lower() == ".pdf":
        try:
            import pdfplumber
        except ImportError:
            raise RuntimeError("PDF 解析需要 pdfplumber：pip install pdfplumber")
        if table_extract is None:
            table_extract = bool(_kb_settings().get("table_extract", True))
        pages: List[str] = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                if table_extract:
                    try:
                        tables = page.extract_tables()
                    except Exception:
                        tables = None
                    pages.append(_page_text_with_tables(page_text, tables))
                else:
                    pages.append(page_text)
        return "\n".join(pages)
    if p.suffix.lower() in (".txt", ".md", ".markdown", ".ris", ".csv"):
        return p.read_text(encoding="utf-8", errors="replace")
    raise ValueError(f"不支持的文献格式：{p.suffix}（支持 PDF/TXT/Markdown）")


class KnowledgeBase:
    """单个知识库：文档导入 + 向量化 + 检索。"""

    def __init__(self, name: str, embedder: Embedder) -> None:
        self.name = name
        self.dir = knowledge_root() / name
        self.embedder = embedder
        self.store = VectorStore(self.dir)
        self._docs_index = self._load_docs()

    def _load_docs(self) -> List[Dict[str, str]]:
        p = self.dir / "docs.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return []
        return []

    def _save_docs(self) -> None:
        (self.dir / "docs.json").write_text(
            json.dumps(self._docs_index, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    def add_document(self, path: str) -> Dict[str, Any]:
        """导入单个文献文件：解析 → 分块 → 嵌入 → 入库（增量更新）。"""
        doc_id = hashlib.md5(str(path).encode("utf-8")).hexdigest()[:12]
        # 增量：同路径已导入则跳过
        if any(d["id"] == doc_id for d in self._docs_index):
            return {"doc_id": doc_id, "skipped": True, "reason": "该文件已导入（如需更新请先删除后重新导入）"}
        text = extract_text(path)
        chunks = _split_text(text)
        if not chunks:
            return {"doc_id": doc_id, "chunks": 0, "skipped": True, "reason": "未提取到有效文本"}
        vectors = self.embedder.embed(chunks)
        meta = [
            {
                "doc_id": doc_id,
                "source": os.path.basename(path),
                "path": path,
                "chunk_idx": i,
                "text": c,
            }
            for i, c in enumerate(chunks)
        ]
        self.store.add(vectors, meta)
        self._docs_index.append({"id": doc_id, "path": path, "source": os.path.basename(path),
                                 "chunks": len(chunks)})
        self._save_docs()
        return {"doc_id": doc_id, "chunks": len(chunks), "skipped": False, "source": os.path.basename(path)}

    def add_documents(self, paths: List[str]) -> Dict[str, Any]:
        """批量导入文献。"""
        results = {"ok": 0, "skipped": 0, "errors": [], "items": []}
        for p in paths:
            try:
                r = self.add_document(p)
                results["items"].append(r)
                if r.get("skipped"):
                    results["skipped"] += 1
                else:
                    results["ok"] += 1
            except Exception as exc:  # noqa: BLE001
                results["errors"].append({"path": p, "error": str(exc)})
        return results

    def query(self, question: str, top_k: int = 5, score_threshold: float = 0.0) -> List[Dict[str, Any]]:
        """检索相关文献片段。"""
        vec = self.embedder.embed([question])[0]
        hits = self.store.search(vec, top_k=top_k)
        return [
            {"text": chunk["text"], "source": chunk["source"], "score": round(score, 4),
             "chunk_idx": chunk["chunk_idx"]}
            for chunk, score in hits
            if score >= score_threshold
        ]

    def stats(self) -> Dict[str, Any]:
        return {"name": self.name, "docs": len(self._docs_index), "chunks": self.store.size(),
                "dir": str(self.dir)}


class KnowledgeManager:
    """多知识库管理。"""

    def __init__(self, base_url: str = "", api_key: str = "", embed_model: str = "") -> None:
        self.root = knowledge_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.embedder = Embedder(base_url=base_url, api_key=api_key, model=embed_model)
        self.active: Optional[str] = None
        self._state_file = self.root / ".active"
        self._load_active()

    def _load_active(self) -> None:
        if self._state_file.exists():
            name = self._state_file.read_text(encoding="utf-8").strip()
            if (self.root / name).exists():
                self.active = name

    def _save_active(self) -> None:
        self._state_file.write_text(self.active or "", encoding="utf-8")

    def list_kbs(self) -> List[str]:
        return sorted(d.name for d in self.root.iterdir() if d.is_dir() and not d.name.startswith("."))

    def create(self, name: str) -> Dict[str, Any]:
        if not re.match(r"^[\w\u4e00-\u9fff-]{1,32}$", name):
            return {"error": "知识库名仅支持中文/字母/数字/下划线/短横线，1-32 字符"}
        if name in self.list_kbs():
            return {"error": f"知识库 {name} 已存在"}
        (self.root / name).mkdir()
        return {"created": name}

    def delete(self, name: str) -> Dict[str, Any]:
        import shutil

        target = self.root / name
        if not target.exists():
            return {"error": f"知识库 {name} 不存在"}
        shutil.rmtree(target)
        if self.active == name:
            self.active = None
            self._save_active()
        return {"deleted": name}

    def switch(self, name: str) -> Dict[str, Any]:
        if name not in self.list_kbs():
            return {"error": f"知识库 {name} 不存在（可用 /kb list 查看）"}
        self.active = name
        self._save_active()
        return {"active": name}

    def get(self, name: Optional[str] = None) -> KnowledgeBase:
        target = name or self.active
        if not target:
            raise ValueError("未指定知识库（请先 /kb create 并 /kb switch，或传 name 参数）")
        if target not in self.list_kbs():
            raise ValueError(f"知识库 {target} 不存在")
        return KnowledgeBase(target, self.embedder)
