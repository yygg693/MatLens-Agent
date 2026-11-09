"""记忆去重判定与写入折叠的单测。

覆盖两层：
- ``_dedup`` 纯函数（归一化、相似度、簇聚合）
- ``Mem0MemoryProvider`` 的写入折叠（用假 backend，不碰真实向量库）
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from plugins.memory.mem0 import _dedup
from plugins.memory.mem0 import Mem0MemoryProvider


# ---------------------------------------------------------------------------
# _dedup 纯函数
# ---------------------------------------------------------------------------


def test_normalize_strips_prefix_and_punctuation():
    assert _dedup.normalize_text("[结论] 水热共沉淀，须避开硝酸盐。") == "水热共沉淀须避开硝酸盐"
    assert _dedup.normalize_text("  [用户]  喜欢 XRD  ") == "喜欢xrd"


def test_fingerprint_marks_identical_text_only():
    a = "[结论] 水热共沉淀须避开硝酸盐"
    b = "水热共沉淀，须避开硝酸盐。"
    assert _dedup.fingerprint(a) == _dedup.fingerprint(b)


def test_similarity_orders_related_above_unrelated():
    base = "水热共沉淀选盐必须避开硝酸盐，优先硫酸盐"
    paraphrase = "共沉淀金属盐优选硫酸盐、必须避开硝酸盐"
    unrelated = "用户常用表征手段为 SEM 和 XRD"

    assert _dedup.similarity(base, base) == pytest.approx(1.0)
    related = _dedup.similarity(base, paraphrase)
    other = _dedup.similarity(base, unrelated)

    # 无关对落在 0.05 附近；同义重述落在"疑似"区间（够进复核队列，
    # 但够不到写入端自动合并线——自动合并只拦更接近逐字重复的那些）。
    assert other < 0.10
    assert related > _dedup.SUSPECT_THRESHOLD
    assert related < _dedup.DUP_THRESHOLD
    assert _dedup.similarity(base, base + "。") == pytest.approx(1.0)


def test_similarity_empty_text_is_zero():
    assert _dedup.similarity("", "任何内容") == 0.0
    assert _dedup.similarity("", "") == 0.0


def test_richer_text_keeps_more_informative_variant():
    short = "避开硝酸盐"
    long = "水热共沉淀选盐必须避开硝酸盐，因为 NO3- 会把 Mn2+ 氧化"
    assert _dedup.richer_text(short, long) == long
    assert _dedup.richer_text(long, short) == long


def test_best_match_respects_threshold_and_skip():
    rows = [
        {"id": "a", "memory": "水热共沉淀须避开硝酸盐"},
        {"id": "b", "memory": "用户常用表征为 SEM"},
    ]
    hit, score = _dedup.best_match(
        "水热共沉淀必须避开硝酸盐", rows, threshold=0.5
    )
    assert hit["id"] == "a" and score > 0.5

    skipped, _ = _dedup.best_match(
        "水热共沉淀必须避开硝酸盐", rows, threshold=0.5, skip_ids={"a"}
    )
    assert skipped is None

    # 阈值高于实际相似度时不命中，避免把不同事实并成一条
    assert _dedup.best_match("水热共沉淀须避开硝酸盐", rows, threshold=1.01)[0] is None
    assert _dedup.best_match("用户常用表征为 XRD", rows, threshold=0.9)[0] is None


def test_group_duplicates_clusters_transitively():
    items = [
        {"id": "1", "memory": "水热共沉淀须避开硝酸盐，优先硫酸盐"},
        {"id": "2", "memory": "水热共沉淀须避开硝酸盐，优选硫酸盐"},
        {"id": "3", "memory": "水热共沉淀须避开硝酸盐，硫酸盐优先"},
        {"id": "4", "memory": "用户常用表征手段为 SEM 和 XRD"},
    ]
    groups = _dedup.group_duplicates(items, threshold=0.5)
    assert len(groups) == 1
    assert set(groups[0]["ids"]) == {"1", "2", "3"}
    assert groups[0]["score"] > 0.5


def test_group_duplicates_returns_empty_for_distinct_items():
    items = [
        {"id": "1", "memory": "水热共沉淀须避开硝酸盐"},
        {"id": "2", "memory": "用户常用表征手段为 SEM 和 XRD"},
    ]
    assert _dedup.group_duplicates(items, threshold=0.5) == []


# ---------------------------------------------------------------------------
# 写入折叠
# ---------------------------------------------------------------------------


class _FakeBackend:
    """最小假后端：只实现 provider 去重路径用到的四个调用。"""

    def __init__(self, rows: List[Dict[str, Any]]):
        self.rows = list(rows)
        self.updated: List[tuple] = []
        self.deleted: List[str] = []
        self.added: List[Dict[str, Any]] = []

    def search(self, query, *, filters, top_k=10, rerank=False):
        return self.rows[:top_k]

    def update(self, memory_id, text):
        self.updated.append((memory_id, text))
        return {"id": memory_id, "memory": text}

    def delete(self, memory_id):
        self.deleted.append(memory_id)
        self.rows = [r for r in self.rows if r.get("id") != memory_id]
        return {"id": memory_id}

    def add(self, messages, *, user_id="", agent_id="", infer=True, metadata=None):
        row = {"id": "new-1", "memory": messages[0]["content"]}
        self.added.append(row)
        return {"results": [row]}


def _make_provider(backend) -> Mem0MemoryProvider:
    provider = object.__new__(Mem0MemoryProvider)
    provider._backend = backend
    provider._user_id = "tester"
    provider._agent_id = "matlens"
    # 索引相关留空，best-effort 路径会自己跳过
    provider._keyword_index = None
    provider._index_dirty = False
    provider._consecutive_failures = 0
    provider._breaker_open_until = 0.0
    return provider


def test_find_similar_returns_existing_row_and_merged_text():
    backend = _FakeBackend(
        [{"id": "old", "memory": "水热共沉淀须避开硝酸盐，优先硫酸盐"}]
    )
    provider = _make_provider(backend)

    dup_id, score, merged = provider._find_similar("水热共沉淀必须避开硝酸盐，优先硫酸盐")
    assert dup_id == "old"
    assert score > _dedup.DUP_THRESHOLD
    assert "硫酸盐" in merged


def test_find_similar_ignores_unrelated_rows():
    backend = _FakeBackend([{"id": "x", "memory": "用户常用表征手段为 SEM 和 XRD"}])
    provider = _make_provider(backend)
    assert provider._find_similar("水热共沉淀须避开硝酸盐")[0] is None


def test_find_similar_survives_search_failure():
    class _Broken(_FakeBackend):
        def search(self, *a, **kw):
            raise RuntimeError("vector store down")

    provider = _make_provider(_Broken([]))
    assert provider._find_similar("任何内容") == (None, 0.0, "任何内容")


def test_fold_duplicate_rows_merges_and_deletes_new_row():
    backend = _FakeBackend(
        [{"id": "old", "memory": "水热共沉淀须避开硝酸盐，优先硫酸盐"}]
    )
    provider = _make_provider(backend)

    provider._fold_duplicate_rows(
        {"results": [{"id": "new-1", "memory": "水热共沉淀必须避开硝酸盐，优先硫酸盐"}]}
    )
    assert backend.deleted == ["new-1"]
    assert [u[0] for u in backend.updated] == ["old"]


def test_fold_duplicate_rows_does_not_merge_loose_paraphrase():
    """重述型重复只进复核队列，不该被自动合并——写入端宁漏勿错。"""
    backend = _FakeBackend(
        [{"id": "old", "memory": "水热共沉淀须避开硝酸盐，优先硫酸盐"}]
    )
    provider = _make_provider(backend)

    provider._fold_duplicate_rows(
        {"results": [{"id": "new-1", "memory": "共沉淀金属盐优选硫酸盐、必须避开硝酸盐"}]}
    )
    assert backend.deleted == []
    assert backend.updated == []


def test_fold_duplicate_rows_keeps_genuinely_new_row():
    backend = _FakeBackend([{"id": "old", "memory": "用户常用表征手段为 SEM 和 XRD"}])
    provider = _make_provider(backend)

    provider._fold_duplicate_rows(
        {"results": [{"id": "new-1", "memory": "水热共沉淀须避开硝酸盐"}]}
    )
    assert backend.deleted == []
    assert backend.updated == []
