"""混合召回（向量 + 关键词 → RRF）的行为契约。

被锁住的性质：

1. **关键词能捞到向量捞不到的东西** —— 型号、缩写、字面 token；
2. **两个召回器都命中的条目排在前面** —— RRF 的核心；
3. **索引不可用时退回纯向量**，不报错、不丢结果；
4. **写入 / 删除会同步索引**，索引不会撒谎；
5. **租户隔离** —— 只召回本 principal 的记忆；
6. **查询里的 FTS5 运算符不会打穿索引**（用户输入进 MATCH 的安全边界）；
7. **principal 的 id 不是可搜索内容** —— 它只用来圈定范围。
"""

import os
import sqlite3

import pytest

from plugins.memory.mem0 import Mem0MemoryProvider
from plugins.memory.mem0._hybrid import rrf_fuse_ids, rrf_fuse_rows
from plugins.memory.mem0._keyword_index import (
    MemoryKeywordIndex,
    default_index_path,
    split_query_terms,
)


# ---------------------------------------------------------------------------
# RRF
# ---------------------------------------------------------------------------
class TestReciprocalRankFusion:
    def test_document_in_both_lists_wins(self):
        fused = rrf_fuse_ids([["a", "b"], ["b", "a"]])
        # a is rank1 in list 1 and rank2 in list 2; b is the mirror image —
        # tie broken deterministically by id.
        assert {doc_id for doc_id, _ in fused} == {"a", "b"}
        assert len(fused) == 2

    def test_shared_document_outranks_a_single_list_hit(self):
        fused = rrf_fuse_ids([["x", "y"], ["x"]])
        assert fused[0][0] == "x"
        assert fused[0][1] > fused[1][1]

    def test_empty_rankings_are_harmless(self):
        assert rrf_fuse_ids([]) == []
        assert rrf_fuse_ids([[], []]) == []

    def test_rows_carry_the_fused_score(self):
        fused = rrf_fuse_rows(
            [[{"id": "a", "memory": "first"}], [{"id": "b", "memory": "second"}]]
        )
        assert {row["id"] for row in fused} == {"a", "b"}
        assert all("rrf_score" in row for row in fused)

    def test_first_ranking_supplies_the_payload(self):
        fused = rrf_fuse_rows(
            [[{"id": "a", "memory": "from-vector"}], [{"id": "a", "memory": "from-keyword"}]]
        )
        assert len(fused) == 1
        assert fused[0]["memory"] == "from-vector"

    def test_rows_without_an_id_are_dropped(self):
        assert rrf_fuse_rows([[{"memory": "no id"}]]) == []


# ---------------------------------------------------------------------------
# 查询切分
# ---------------------------------------------------------------------------
class TestQuerySplitting:
    def test_latin_and_cjk_runs_are_separated(self):
        latin, cjk = split_query_terms("NCM811 正极材料")
        assert latin == ["NCM811"]
        assert cjk == ["正极材料"]

    def test_quoted_phrase_is_kept_whole(self):
        latin, cjk = split_query_terms('"高镍三元" 电池')
        # The quoted phrase stays one term; the unquoted run is kept too,
        # so the FTS query becomes a phrase AND a phrase.
        assert cjk == ["高镍三元", "电池"]
        assert latin == []

    def test_empty_query_yields_nothing(self):
        assert split_query_terms("") == ([], [])
        assert split_query_terms("   ") == ([], [])


# ---------------------------------------------------------------------------
# 关键词索引
# ---------------------------------------------------------------------------
@pytest.fixture
def index(tmp_path):
    idx = MemoryKeywordIndex(path=str(tmp_path / "idx.sqlite3"))
    assert idx.open() is True
    yield idx
    idx.close()


class TestKeywordIndex:
    def test_finds_an_exact_latin_token(self, index):
        index.upsert("m1", "用户使用 NCM811 正极材料", user_id="u1")
        hits = index.search("NCM811", user_id="u1")
        assert [mid for mid, _ in hits] == ["m1"]

    def test_finds_a_cjk_phrase(self, index):
        index.upsert("m1", "用户正在做钠离子电池的固态电解质", user_id="u1")
        hits = index.search("固态电解质", user_id="u1")
        assert [mid for mid, _ in hits] == ["m1"]

    def test_short_cjk_term_falls_back_to_substring(self, index):
        index.upsert("m1", "用户偏好中文回答", user_id="u1")
        hits = index.search("中文", user_id="u1")
        assert [mid for mid, _ in hits] == ["m1"]

    def test_mixed_query_finds_latin_and_cjk(self, index):
        index.upsert("m1", "NCM811 的循环寿命数据", user_id="u1")
        hits = index.search("NCM811 循环寿命", user_id="u1")
        assert [mid for mid, _ in hits] == ["m1"]

    def test_other_principals_are_never_returned(self, index):
        index.upsert("m1", "NCM811 材料", user_id="u1")
        index.upsert("m2", "NCM811 材料", user_id="u2")
        hits = index.search("NCM811", user_id="u1")
        assert [mid for mid, _ in hits] == ["m1"]

    def test_the_principal_id_is_not_searchable_content(self, index):
        # user_id scopes the search, it is not part of the text. Indexed as
        # an ordinary column it would be tokenized like the memory text,
        # so a term that happens to occur in the principal's id would match
        # every one of their rows.
        index.upsert("m1", "NCM811 材料", user_id="matlens-user")
        index.upsert("m2", "LFP 材料", user_id="matlens-user")
        assert index.search("user", user_id="matlens-user") == []
        assert index.search("matlens", user_id="matlens-user") == []

    def test_an_older_schema_is_dropped_and_rebuilt(self, tmp_path):
        path = str(tmp_path / "legacy.sqlite3")
        legacy = MemoryKeywordIndex(path=path)
        assert legacy.open()
        legacy.upsert("m1", "NCM811 材料", user_id="u1")
        legacy.close()

        # Simulate a file written by an older build: wrong user_version.
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
        conn.close()

        reopened = MemoryKeywordIndex(path=path)
        assert reopened.open()
        try:
            # The cached rows were dropped — the provider rebuilds them from
            # the vector store, which owns the real data.
            assert reopened.count() == 0
            reopened.upsert("m2", "LFP 材料", user_id="u1")
            assert [mid for mid, _ in reopened.search("LFP", user_id="u1")] == ["m2"]
        finally:
            reopened.close()

    def test_deleted_memory_disappears(self, index):
        index.upsert("m1", "NCM811 材料", user_id="u1")
        assert index.search("NCM811", user_id="u1")
        index.delete("m1")
        assert index.search("NCM811", user_id="u1") == []

    def test_upsert_replaces_the_previous_text(self, index):
        index.upsert("m1", "NCM811 材料", user_id="u1")
        index.upsert("m1", "LFP 材料", user_id="u1")
        assert index.search("NCM811", user_id="u1") == []
        assert [mid for mid, _ in index.search("LFP", user_id="u1")] == ["m1"]

    def test_count_tracks_the_indexed_rows(self, index):
        assert index.count() == 0
        index.upsert("m1", "a", user_id="u1")
        index.upsert("m2", "b", user_id="u1")
        assert index.count() == 2

    def test_clear_empties_the_index(self, index):
        index.upsert("m1", "a", user_id="u1")
        index.clear()
        assert index.count() == 0

    def test_fts5_operators_in_the_query_do_not_break_it(self, index):
        index.upsert("m1", "NCM811 材料", user_id="u1")
        # A query full of FTS5 syntax must return results, not raise.
        for hostile in ['"', "AND", "*", "NEAR(", "a:b", "((", "^", "-"]:
            hits = index.search(hostile, user_id="u1")
            assert isinstance(hits, list)

    def test_unavailable_index_is_inert(self, tmp_path):
        idx = MemoryKeywordIndex(path=str(tmp_path / "sub" / "idx.sqlite3"))
        assert idx.open() is True
        idx.close()
        assert idx.available is False
        assert idx.search("x", user_id="u1") == []
        assert idx.count() == 0
        assert idx.upsert("m1", "x", user_id="u1") is False

    def test_default_path_follows_matlens_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MATLENS_HOME", str(tmp_path))
        assert default_index_path() == os.path.join(str(tmp_path), "mem0_index.sqlite3")


# ---------------------------------------------------------------------------
# Provider 层的混合召回
# ---------------------------------------------------------------------------
class _HybridBackend:
    """向量召回只认语义，关键词召回认字面 token。"""

    def __init__(self, rows, vector_hits=None):
        self.rows = {row["id"]: row for row in rows}
        self.vector_hits = vector_hits or []
        self.searches = []

    def search(self, query, *, filters, top_k=10, rerank=False):
        self.searches.append({"query": query, "top_k": top_k, "rerank": rerank})
        return list(self.vector_hits)

    def get(self, memory_id):
        return self.rows.get(memory_id)

    def count_all(self, *, filters):
        return len(self.rows)

    def get_all(self, *, filters, page=1, page_size=100, offset=None):
        start = offset if offset is not None else (page - 1) * page_size
        window = list(self.rows.values())[start:start + page_size]
        return {
            "results": window,
            "count": len(window),
            "total": len(self.rows),
            "has_more": start + len(window) < len(self.rows),
        }


def _provider(backend, tmp_path, monkeypatch):
    monkeypatch.setenv("MATLENS_HOME", str(tmp_path))
    provider = Mem0MemoryProvider()
    provider.initialize("test-session")
    provider._user_id = "u123"
    provider._agent_id = "matlens"
    provider._backend = backend
    return provider


class TestHybridSearch:
    def test_keyword_hit_survives_when_vector_finds_nothing(self, tmp_path, monkeypatch):
        rows = [{"id": "m1", "memory": "用户使用 NCM811 正极材料"}]
        backend = _HybridBackend(rows)
        provider = _provider(backend, tmp_path, monkeypatch)
        provider._ensure_index_fresh()
        results = provider._hybrid_search("NCM811", top_k=5)
        assert [r["id"] for r in results] == ["m1"]

    def test_shared_hit_outranks_a_vector_only_hit(self, tmp_path, monkeypatch):
        rows = [
            {"id": "m1", "memory": "NCM811 材料"},
            {"id": "m2", "memory": "完全无关的一条记忆"},
        ]
        backend = _HybridBackend(rows, vector_hits=[rows[1]])
        provider = _provider(backend, tmp_path, monkeypatch)
        provider._ensure_index_fresh()
        results = provider._hybrid_search("NCM811", top_k=5)
        assert results[0]["id"] == "m1"

    def test_without_an_index_the_result_is_the_vector_recall(self, tmp_path, monkeypatch):
        rows = [{"id": "m2", "memory": "向量命中"}]
        backend = _HybridBackend(rows, vector_hits=rows)
        provider = _provider(backend, tmp_path, monkeypatch)
        provider._get_keyword_index = lambda: None
        results = provider._hybrid_search("任意查询", top_k=5)
        assert [r["id"] for r in results] == ["m2"]

    def test_vector_call_keeps_its_top_k(self, tmp_path, monkeypatch):
        rows = [{"id": "m1", "memory": "NCM811 材料"}]
        backend = _HybridBackend(rows, vector_hits=rows)
        provider = _provider(backend, tmp_path, monkeypatch)
        provider._ensure_index_fresh()
        provider._hybrid_search("NCM811", top_k=7)
        assert backend.searches[-1]["top_k"] == 7

    def test_writes_are_indexed(self, tmp_path, monkeypatch):
        rows = []
        backend = _HybridBackend(rows)
        provider = _provider(backend, tmp_path, monkeypatch)
        provider._ensure_index_fresh()
        provider._index_memory("m1", "NCM811 正极材料")
        index = provider._get_keyword_index()
        assert index.count() == 1
        assert [mid for mid, _ in index.search("NCM811", user_id="u123")] == ["m1"]

    def test_deletes_are_unindexed(self, tmp_path, monkeypatch):
        backend = _HybridBackend([])
        provider = _provider(backend, tmp_path, monkeypatch)
        provider._ensure_index_fresh()
        provider._index_memory("m1", "NCM811 正极材料")
        provider._unindex_memory("m1")
        index = provider._get_keyword_index()
        assert index.count() == 0

    def test_index_is_rebuilt_when_it_falls_behind_the_store(self, tmp_path, monkeypatch):
        rows = [
            {"id": "m1", "memory": "NCM811 正极材料"},
            {"id": "m2", "memory": "LFP 磷酸铁锂"},
        ]
        backend = _HybridBackend(rows)
        provider = _provider(backend, tmp_path, monkeypatch)
        provider._ensure_index_fresh()
        index = provider._get_keyword_index()
        assert index.count() == 2
        assert [mid for mid, _ in index.search("LFP", user_id="u123")] == ["m2"]

    def test_index_rebuild_is_skipped_when_it_is_already_complete(self, tmp_path, monkeypatch):
        rows = [{"id": "m1", "memory": "NCM811 正极材料"}]
        backend = _HybridBackend(rows)
        provider = _provider(backend, tmp_path, monkeypatch)
        provider._ensure_index_fresh()
        index = provider._get_keyword_index()
        index.upsert("m1", "NCM811 正极材料", user_id="u123")
        calls = []
        original = provider._rebuild_index

        def _counting_rebuild():
            calls.append(1)
            return original()

        provider._rebuild_index = _counting_rebuild
        provider._index_checked = False
        provider._ensure_index_fresh()
        assert calls == []

    def test_prefetch_uses_the_hybrid_path(self, tmp_path, monkeypatch):
        rows = [{"id": "m1", "memory": "NCM811 正极材料"}]
        backend = _HybridBackend(rows)
        provider = _provider(backend, tmp_path, monkeypatch)
        provider._ensure_index_fresh()
        body = provider.prefetch("NCM811 用的是什么材料")
        assert "NCM811 正极材料" in body
