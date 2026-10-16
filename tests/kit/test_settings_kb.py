# -*- coding: utf-8 -*-
"""知识库设置接通本地 RAG 的测试（离线、tmp_mat_home 隔离）。

覆盖：
(a) chunk_size=500 vs 1200 对同一长文本块数差异；chunk_overlap 生效（相邻块重叠）；
(b) embed_model=local 时 Embedder 确定性 384 维、无网络；切到 text-embedding-3-small
    时构造出的 Embedder.model / base_url 正确（monkeypatch OpenAI 避免联网）；
(c) table_extract=true/false 时 PDF 页面文本+表格拼装行为不同；表格抽取抛错安全降级；
(d) kb.root 改到自定义目录后新建库目录落在该处；
(e) TestClient 走 POST /api/kb 建库 + 导入临时 txt，chunks 数随 chunk_size 设置变化。

不假设 faiss 存在（VectorStore 已 numpy 降级）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from matlens_kit.api.server import app
from matlens_kit.rag import kb as K
from matlens_kit.rag.kb import Embedder, KnowledgeManager, _page_text_with_tables, _split_text


# ─────────────────────────────────────────────────────────────
# 工具：直接向临时 MATLENS_HOME 写 kb 段配置
# ─────────────────────────────────────────────────────────────
def _write_kb_config(mat_home: Path, **kv) -> None:
    cfg = Path(mat_home) / "config.yaml"
    data = {}
    if cfg.exists():
        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    data.setdefault("kb", {}).update(kv)
    cfg.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


# 无句号/分号的重复单元，保证切分落在固定字符边界（便于断言重叠）
_UNIT = "材料科学与工程导论abcdef"
_LONG_TEXT = _UNIT * 120  # 约 2880 字符


# ─────────────────────────────────────────────────────────────
# (a) 分块大小 / 重叠
# ─────────────────────────────────────────────────────────────
def test_chunk_size_setting_changes_count(tmp_mat_home):
    _write_kb_config(tmp_mat_home, chunk_size=500, chunk_overlap=100)
    chunks_500 = _split_text(_LONG_TEXT)

    _write_kb_config(tmp_mat_home, chunk_size=1200, chunk_overlap=100)
    chunks_1200 = _split_text(_LONG_TEXT)

    assert len(chunks_500) > len(chunks_1200)


def test_chunk_overlap_adjacent_blocks_overlap(tmp_mat_home):
    _write_kb_config(tmp_mat_home, chunk_size=500, chunk_overlap=100)
    chunks = _split_text(_LONG_TEXT)
    assert len(chunks) >= 2
    # 相邻块：后一块的前缀应等于前一块的尾部（重叠区）
    assert chunks[1].startswith(chunks[0][-100:])


# ─────────────────────────────────────────────────────────────
# (b) 嵌入模型
# ─────────────────────────────────────────────────────────────
def test_local_embed_deterministic_384dim_no_network():
    e = Embedder(base_url="", api_key="", model="local")
    assert e._local_fallback is True
    vecs = e.embed(["材料科学", "hello world"])
    assert len(vecs) == 2
    assert len(vecs[0]) == 384
    # 确定性：同文本两次嵌入一致
    assert e.embed(["材料科学"]) == e.embed(["材料科学"])
    # 未创建远程 client
    assert e._client is None


def test_remote_embedder_model_and_base_url(monkeypatch):
    import openai

    seen = {}

    class _FakeEmbeddings:
        def create(self, model, input):
            seen["model"] = model
            n = len(input) if isinstance(input, list) else 1

            class _D:
                def __init__(self):
                    self.embedding = [0.0] * 1536

            class _R:
                data = [_D() for _ in range(n)]

            return _R()

    class _FakeClient:
        def __init__(self, base_url, api_key):
            seen["base_url"] = base_url
            seen["api_key"] = api_key
            self.embeddings = _FakeEmbeddings()

    monkeypatch.setattr(openai, "OpenAI", _FakeClient)

    e = Embedder(base_url="https://llm.example/v1", api_key="sk-test",
                 model="text-embedding-3-small")
    e.embed(["任意文本"])
    assert e.model == "text-embedding-3-small"
    assert seen["base_url"] == "https://llm.example/v1"
    assert seen["model"] == "text-embedding-3-small"


# ─────────────────────────────────────────────────────────────
# (c) PDF 表格识别开关
# ─────────────────────────────────────────────────────────────
def test_page_text_with_tables_assembly():
    out = _page_text_with_tables("正文段落", [["能带", "3.2 eV"], ["宽度", None, "10 nm"]])
    assert "正文段落" in out
    assert "能带 | 3.2 eV" in out
    assert "宽度 | 10 nm" in out  # None 单元格被跳过


def test_page_text_with_tables_empty_tables():
    assert _page_text_with_tables("仅正文", None) == "仅正文"
    assert _page_text_with_tables("", []) == ""


class _FakePage:
    def __init__(self, text, tables=None, raise_tables=False):
        self._text = text
        self._tables = tables
        self._raise = raise_tables

    def extract_text(self):
        return self._text

    def extract_tables(self):
        # 表格抽取失败应安全降级
        if self._raise:
            raise RuntimeError("pdfplumber table boom")
        return self._tables


class _FakePDF:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _install_fake_pdfplumber(monkeypatch, pages):
    """把假 pdfplumber 塞进 sys.modules，使 kb.extract_text 内的 import 命中它。"""
    import types

    mod = types.ModuleType("pdfplumber")
    mod.open = lambda path: _FakePDF(pages)
    monkeypatch.setitem(sys.modules, "pdfplumber", mod)


def test_extract_text_table_extract_true_false(tmp_mat_home, monkeypatch, tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_text("dummy", encoding="utf-8")
    pages = [_FakePage("正文", [["colA", "colB"], ["1", "2"]])]

    _install_fake_pdfplumber(monkeypatch, pages)

    _write_kb_config(tmp_mat_home, table_extract=True)
    out_on = K.extract_text(str(pdf))
    assert "正文" in out_on
    assert "colA | colB" in out_on

    _write_kb_config(tmp_mat_home, table_extract=False)
    out_off = K.extract_text(str(pdf))
    assert "正文" in out_off
    assert "colA" not in out_off


def test_extract_text_table_extract_safe_degrade_on_error(tmp_mat_home, monkeypatch, tmp_path):
    pdf = tmp_path / "b.pdf"
    pdf.write_text("dummy", encoding="utf-8")
    pages = [_FakePage("正文", raise_tables=True)]
    _install_fake_pdfplumber(monkeypatch, pages)
    _write_kb_config(tmp_mat_home, table_extract=True)

    # 表格抽取抛错 → 降级为仅正文，不抛异常
    out = K.extract_text(str(pdf))
    assert out == "正文"


# ─────────────────────────────────────────────────────────────
# (d) 存储根目录
# ─────────────────────────────────────────────────────────────
def test_kb_root_setting_redirects_dir(tmp_mat_home):
    custom = tmp_mat_home / "custom_kb_root"
    _write_kb_config(tmp_mat_home, root=str(custom))
    assert K.knowledge_root() == custom

    mgr = KnowledgeManager()
    assert mgr.root == custom
    custom.mkdir(parents=True, exist_ok=True)
    res = mgr.create("mylib")
    assert res.get("created") == "mylib"
    assert (custom / "mylib").exists()


# ─────────────────────────────────────────────────────────────
# (e) HTTP 建库 + 导入，chunks 随 chunk_size 设置变化
# ─────────────────────────────────────────────────────────────
def test_http_create_and_import_chunks_follow_chunk_size(tmp_mat_home):
    from matlens_kit.plugins import local_rag

    local_rag.reset_manager()
    client = TestClient(app)

    doc = tmp_mat_home / "doc.txt"
    doc.write_text(_LONG_TEXT, encoding="utf-8")

    def _import_into(new_kb_name: str) -> int:
        r = client.post("/api/kb", json={"name": new_kb_name})
        assert r.status_code == 200, r.text
        slug = r.json()["name"]
        r2 = client.post(f"/api/kb/{slug}/import", json={"paths": [str(doc)]})
        assert r2.status_code == 200, r2.text
        items = r2.json()["items"]
        assert items[0]["skipped"] is False
        return items[0]["chunks"]

    _write_kb_config(tmp_mat_home, chunk_size=500, chunk_overlap=100)
    local_rag.reset_manager()
    chunks_500 = _import_into("lib500")

    _write_kb_config(tmp_mat_home, chunk_size=1200, chunk_overlap=100)
    local_rag.reset_manager()
    chunks_1200 = _import_into("lib1200")

    assert chunks_500 > chunks_1200
    local_rag.reset_manager()
