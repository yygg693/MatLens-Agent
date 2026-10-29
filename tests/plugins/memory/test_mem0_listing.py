"""Mem0 记忆列举契约 —— 真实计数、真分页、按 ID 精确取。

这一组测试锁住的是「不能再撒谎」的三件事：

1. 计数必须是**该用户的真实条数**，不能因为 ``Collection.count()`` 不支持
   ``where`` 就悄悄退化成整个集合的大小；
2. 分页必须是**真分页**——第 51 条要能翻到，且相邻页不重叠；
3. 按 ID 取回必须是**精确取**，不能用向量检索凑。

参考实现：``plugins/memory/mem0/_backend.py`` / ``plugins/memory/mem0/__init__.py``
/ ``matlens_kit/api/mem_api.py``。
"""

import pytest

from plugins.memory.mem0 import Mem0MemoryProvider
from plugins.memory.mem0._backend import (
    OSSBackend,
    PlatformBackend,
    _normalize_page,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
def _matches(payload, where):
    """Minimal Chroma where-clause matcher ($eq only)."""
    if not where:
        return True
    for key, cond in where.items():
        if key == "$and":
            if not all(_matches(payload, sub) for sub in cond):
                return False
            continue
        if key == "$or":
            if not any(_matches(payload, sub) for sub in cond):
                return False
            continue
        if isinstance(cond, dict):
            if "$eq" in cond and payload.get(key) != cond["$eq"]:
                return False
        elif payload.get(key) != cond:
            return False
    return True


class FakeChromaCollection:
    """Mimics chromadb 1.5.9 ``Collection`` — including its no-``where`` count."""

    def __init__(self, rows):
        # rows: list of (id, metadata dict)
        self.rows = list(rows)
        self.get_calls = []
        self.count_calls = []

    def count(self, *args, **kwargs):
        # chroma 1.5.9: count(self, read_level=...) — there is NO where.
        self.count_calls.append(kwargs)
        if "where" in kwargs:
            raise TypeError(
                "Collection.count() got an unexpected keyword argument 'where'"
            )
        return len(self.rows)

    def get(self, ids=None, where=None, limit=None, offset=None, include=None, **kwargs):
        self.get_calls.append(
            {"where": where, "limit": limit, "offset": offset, "include": include}
        )
        rows = [r for r in self.rows if _matches(r[1], where or {})]
        if ids is not None:
            wanted = set(ids)
            rows = [r for r in rows if r[0] in wanted]
        if offset:
            rows = rows[offset:]
        if limit is not None:
            rows = rows[:limit]
        out = {"ids": [r[0] for r in rows]}
        if include is None or "metadatas" in include:
            out["metadatas"] = [r[1] for r in rows]
        if include is None or "documents" in include:
            out["documents"] = [None for _ in rows]
        return out


class FakeChromaVectorStore:
    def __init__(self, collection):
        self.collection = collection
        self.client = None

    @staticmethod
    def _generate_where_clause(where):
        """Same translation mem0's ChromaDB performs."""
        if not where:
            return None
        out = {}
        for key, value in where.items():
            out[key] = {"$eq": value}
        return out


class FakeMemory:
    def __init__(self, vector_store=None, all_results=None):
        self.vector_store = vector_store
        self.calls = []
        self._all_results = all_results if all_results is not None else {"results": []}
        self._items = {}

    def get_all(self, **kwargs):
        self.calls.append(("get_all", kwargs))
        return self._all_results

    def get(self, memory_id):
        self.calls.append(("get", memory_id))
        return self._items.get(memory_id)


def _chroma_backend(rows, collection_name="matlens"):
    """Build an OSSBackend wired to a fake Chroma collection."""
    collection = FakeChromaCollection(rows)
    backend = OSSBackend.__new__(OSSBackend)
    backend._memory = FakeMemory(vector_store=FakeChromaVectorStore(collection))
    backend._oss_config = {
        "vector_store": {
            "provider": "chroma",
            "config": {"collection_name": collection_name},
        }
    }
    return backend, collection


def _rows(n=30, user="u1"):
    return [
        (
            f"m{i}",
            {
                "data": f"事实 {i}",
                "user_id": user,
                "agent_id": "matlens",
                "hash": f"h{i}",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-02T00:00:00+00:00",
                "channel": "cli",
            },
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# 1. 精确计数
# ---------------------------------------------------------------------------
class TestExactCount:
    def test_count_is_scoped_to_the_user(self):
        rows = _rows(5, user="u1") + _rows(7, user="u2")
        backend, _ = _chroma_backend(rows)
        assert backend.count_all(filters={"user_id": "u1"}) == 5
        assert backend.count_all(filters={"user_id": "u2"}) == 7

    def test_count_never_falls_back_to_the_whole_collection(self):
        """count(where=...) 在 chroma 1.5.9 上会抛 TypeError。

        旧实现把这个异常吞掉，然后退回 collection.count()——那是**整个集合**
        的大小。多租户下直接就是错的。
        """
        rows = _rows(5, user="u1") + _rows(7, user="u2")
        backend, collection = _chroma_backend(rows)
        total = backend.count_all(filters={"user_id": "u1"})
        assert total == 5
        # 绝不能出现 "count(where=...)" 这种 chroma 不支持的调用
        assert all("where" not in call for call in collection.count_calls)

    def test_unfiltered_count_uses_fast_path(self):
        backend, collection = _chroma_backend(_rows(3))
        assert backend.count_all(filters={}) == 3
        assert collection.count_calls  # 走了 collection.count() 快路径

    def test_count_is_none_when_store_cannot_answer(self):
        backend = OSSBackend.__new__(OSSBackend)
        backend._memory = FakeMemory()
        backend._oss_config = {"vector_store": {"provider": "faiss", "config": {}}}
        assert backend.count_all(filters={"user_id": "u1"}) is None


# ---------------------------------------------------------------------------
# 2. 真分页
# ---------------------------------------------------------------------------
class TestRealPaging:
    def test_pages_do_not_overlap_and_cover_the_store(self):
        backend, _ = _chroma_backend(_rows(35))
        seen = []
        for page in range(1, 4):
            data = backend.get_all(
                filters={"user_id": "u1"}, page=page, page_size=10
            )
            assert data["count"] == 10
            assert data["total"] == 35
            assert data["has_more"] is True
            seen.extend(r["id"] for r in data["results"])
        tail = backend.get_all(filters={"user_id": "u1"}, page=4, page_size=10)
        assert tail["count"] == 5
        assert tail["has_more"] is False
        seen.extend(r["id"] for r in tail["results"])
        assert len(seen) == 35
        assert len(set(seen)) == 35  # 无重叠

    def test_last_page_reports_no_more(self):
        backend, _ = _chroma_backend(_rows(25))
        data = backend.get_all(filters={"user_id": "u1"}, offset=20, page_size=10)
        assert data["count"] == 5
        assert data["total"] == 25
        assert data["has_more"] is False

    def test_offset_beyond_the_end_is_empty(self):
        backend, _ = _chroma_backend(_rows(5))
        data = backend.get_all(filters={"user_id": "u1"}, offset=100, page_size=10)
        assert data["count"] == 0
        assert data["total"] == 5
        assert data["has_more"] is False

    def test_offset_window_matches_the_equivalent_page_slice(self):
        backend, _ = _chroma_backend(_rows(20))
        whole = backend.get_all(filters={"user_id": "u1"}, page=1, page_size=20)
        window = backend.get_all(filters={"user_id": "u1"}, offset=5, page_size=10)
        assert [r["id"] for r in window["results"]] == [
            r["id"] for r in whole["results"][5:15]
        ]

    def test_rows_carry_mem0_shaped_fields(self):
        backend, _ = _chroma_backend(_rows(2))
        row = backend.get_all(filters={"user_id": "u1"}, page=1, page_size=1)["results"][0]
        assert row["id"] == "m0"
        assert row["memory"] == "事实 0"
        assert row["created_at"] == "2026-01-01T00:00:00+00:00"
        assert row["metadata"]["channel"] == "cli"
        assert "data" not in row["metadata"]

    def test_unknown_store_falls_back_to_the_sdk_listing(self):
        """pgvector / faiss 等没有原生分页的存储退回 SDK 列举并本地切片。"""
        backend = OSSBackend.__new__(OSSBackend)
        backend._memory = FakeMemory(
            all_results={"results": [{"id": f"s{i}"} for i in range(10)]}
        )
        backend._oss_config = {"vector_store": {"provider": "faiss", "config": {}}}
        data = backend.get_all(filters={"user_id": "u1"}, offset=4, page_size=3)
        assert [r["id"] for r in data["results"]] == ["s4", "s5", "s6"]
        assert data["total"] is None  # 不知道就说不知道
        assert data["has_more"] is True


# ---------------------------------------------------------------------------
# 3. Platform / 自建服务的分页语义
# ---------------------------------------------------------------------------
class FakePlatformClient:
    def __init__(self, total=25):
        self.total = total
        self.calls = []

    def get_all(self, **kwargs):
        page = kwargs.get("page", 1)
        size = kwargs.get("page_size", 100)
        self.calls.append(dict(kwargs))
        start = (page - 1) * size
        rows = [
            {"id": f"m{i}", "memory": f"f{i}"}
            for i in range(start, min(start + size, self.total))
        ]
        has_next = start + size < self.total
        return {
            "count": self.total,  # DRF 语义：全量总数，不是本页条数
            "next": f"/next?page={page + 1}" if has_next else None,
            "previous": None,
            "results": rows,
        }


class TestPlatformPaging:
    def _backend(self, total=25):
        client = FakePlatformClient(total)
        backend = PlatformBackend.__new__(PlatformBackend)
        backend._client = client
        return backend, client

    def test_count_field_is_the_store_wide_total(self):
        backend, _ = self._backend(total=25)
        data = backend.get_all(filters={"user_id": "u1"}, page=1, page_size=10)
        assert data["count"] == 10       # 本页条数
        assert data["total"] == 25       # 全量总数
        assert data["has_more"] is True

    def test_last_page_has_no_more(self):
        backend, _ = self._backend(total=25)
        data = backend.get_all(filters={"user_id": "u1"}, page=3, page_size=10)
        assert data["count"] == 5
        assert data["has_more"] is False

    def test_unaligned_offset_is_served_by_walking_pages(self):
        backend, _ = self._backend(total=25)
        data = backend.get_all(filters={"user_id": "u1"}, offset=5, page_size=10)
        assert [r["id"] for r in data["results"]] == [f"m{i}" for i in range(5, 15)]
        assert data["total"] == 25

    def test_normalize_page_without_total_leaves_total_unknown(self):
        data = _normalize_page({"results": [{"id": "a"}], "count": 1})
        assert data["count"] == 1
        assert data["total"] is None

    def test_normalize_page_reads_the_memories_key(self):
        data = _normalize_page({"memories": [{"id": "a"}, {"id": "b"}], "total": 9})
        assert data["count"] == 2
        assert data["total"] == 9


# ---------------------------------------------------------------------------
# 4. Provider 契约
# ---------------------------------------------------------------------------
class _OffsetBackend:
    """支持 offset 的后端。"""

    def __init__(self):
        self.calls = []
        self.rows = [{"id": f"m{i}", "memory": f"f{i}"} for i in range(20)]

    def search(self, query, *, filters, top_k=10, rerank=False):
        return []

    def get_all(self, *, filters, page=1, page_size=100, offset=None):
        self.calls.append({"page": page, "page_size": page_size, "offset": offset})
        start = offset if offset is not None else (page - 1) * page_size
        window = self.rows[start:start + page_size]
        return {
            "results": window,
            "count": len(window),
            "total": len(self.rows),
            "has_more": start + len(window) < len(self.rows),
        }

    def count_all(self, *, filters):
        return len(self.rows)

    def get(self, memory_id):
        for row in self.rows:
            if row["id"] == memory_id:
                return row
        return None


class _LegacyBackend(_OffsetBackend):
    """只认 page/page_size 的老后端。"""

    def get_all(self, *, filters, page=1, page_size=100):
        self.calls.append({"page": page, "page_size": page_size, "offset": None})
        window = self.rows[(page - 1) * page_size: page * page_size]
        return {"results": window, "count": len(window), "total": len(self.rows)}

    def count_all(self, *, filters):
        return None


def _provider(backend):
    provider = Mem0MemoryProvider()
    provider.initialize("test-session")
    provider._user_id = "u123"
    provider._agent_id = "matlens"
    provider._backend = backend
    return provider


class TestProviderListing:
    def test_offset_is_forwarded_to_the_backend(self):
        backend = _OffsetBackend()
        provider = _provider(backend)
        data = provider.list_memories(page=1, page_size=10, offset=30)
        assert backend.calls[-1]["offset"] == 30
        assert data["total"] == 20
        assert data["has_more"] is False

    def test_legacy_backend_without_offset_still_works(self):
        backend = _LegacyBackend()
        provider = _provider(backend)
        data = provider.list_memories(page=2, page_size=10)
        assert data["count"] == 10
        assert backend.calls[-1]["offset"] is None

    def test_count_memories_uses_the_backend_count(self):
        provider = _provider(_OffsetBackend())
        assert provider.count_memories() == 20

    def test_count_memories_is_none_when_unknown(self):
        provider = _provider(_LegacyBackend())
        assert provider.count_memories() is None

    def test_get_memory_fetches_by_id(self):
        provider = _provider(_OffsetBackend())
        raw = provider.get_memory("m7")
        assert raw["id"] == "m7"

    def test_get_memory_returns_none_for_unknown_id(self):
        provider = _provider(_OffsetBackend())
        assert provider.get_memory("nope") is None


# ---------------------------------------------------------------------------
# 5. API 层
# ---------------------------------------------------------------------------
class _ApiProvider:
    def __init__(self, rows):
        self._backend = object()
        self.rows = rows
        self.list_calls = []

    def list_memories(self, *, page=1, page_size=50, offset=None):
        self.list_calls.append({"page": page, "page_size": page_size, "offset": offset})
        start = offset if offset is not None else (page - 1) * page_size
        window = self.rows[start:start + page_size]
        return {
            "results": window,
            "count": len(window),
            "total": len(self.rows),
            "has_more": start + len(window) < len(self.rows),
        }

    def count_memories(self):
        return len(self.rows)

    def get_memory(self, memory_id):
        for row in self.rows:
            if row["id"] == memory_id:
                return row
        return None


@pytest.fixture
def mem_api(monkeypatch):
    from matlens_kit.api import mem_api as module

    monkeypatch.setattr(module, "_memory_settings", lambda: {"enabled": True})
    return module


class TestMemoryApi:
    def test_browse_forwards_offset_and_limit(self, mem_api, monkeypatch):
        provider = _ApiProvider([{"id": f"m{i}", "memory": f"f{i}"} for i in range(30)])
        monkeypatch.setattr(mem_api, "_get_provider", lambda: provider)
        out = mem_api.list_memories(q="", top_k=30, offset=10, limit=10)
        assert provider.list_calls[-1] == {"page": 2, "page_size": 10, "offset": 10}
        assert out["count"] == 10
        assert out["total"] == 30
        assert out["has_more"] is True
        assert out["memories"][0]["id"] == "m10"

    def test_browse_last_page_reports_no_more(self, mem_api, monkeypatch):
        provider = _ApiProvider([{"id": f"m{i}", "memory": f"f{i}"} for i in range(25)])
        monkeypatch.setattr(mem_api, "_get_provider", lambda: provider)
        out = mem_api.list_memories(q="", top_k=30, offset=20, limit=10)
        assert out["count"] == 5
        assert out["has_more"] is False

    def test_get_memory_uses_the_provider_lookup(self, mem_api, monkeypatch):
        provider = _ApiProvider([{"id": "m3", "memory": "第三条"}])
        monkeypatch.setattr(mem_api, "_get_provider", lambda: provider)
        out = mem_api.get_memory("m3")
        assert out["ok"] is True
        assert out["memory"]["id"] == "m3"
        assert out["memory"]["memory"] == "第三条"

    def test_get_memory_returns_none_for_unknown_id(self, mem_api, monkeypatch):
        provider = _ApiProvider([{"id": "m3", "memory": "第三条"}])
        monkeypatch.setattr(mem_api, "_get_provider", lambda: provider)
        out = mem_api.get_memory("missing")
        assert out == {"ok": True, "memory": None}

    def test_exact_count_prefers_the_backend_total(self, mem_api):
        provider = _ApiProvider([{"id": "m0", "memory": "x"}])
        assert mem_api._exact_count(provider) == 1

    def test_search_path_still_reports_mode(self, mem_api, monkeypatch):
        class _SearchProvider(_ApiProvider):
            def handle_tool_call(self, tool, args, **kwargs):
                return {"results": [{"id": "s1", "memory": "命中"}]}

        monkeypatch.setattr(mem_api, "_get_provider", lambda: _SearchProvider([]))
        out = mem_api.list_memories(q="钠离子", top_k=10, offset=0, limit=10)
        assert out["mode"] == "search"
        assert out["memories"][0]["id"] == "s1"
