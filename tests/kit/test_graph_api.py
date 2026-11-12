"""Tests for the memory-graph builder: batch merging and cache staleness."""
import json
import time

from matlens_kit.api import graph_api


def _pairs(graph):
    id_to_label = {n["id"]: n["label"] for n in graph["nodes"]}
    return {(id_to_label[e["source"]], id_to_label[e["target"]]) for e in graph["edges"]}


def test_merge_parts_keeps_ids_local_to_each_batch():
    """Each batch numbers its own ids; the merge must not wire batch 1 to batch 2."""
    parts = [
        {"nodes": [{"id": "1", "label": "钙钛矿", "category": "材料"},
                   {"id": "2", "label": "旋涂法", "category": "方法"}],
         "edges": [{"source": "1", "target": "2", "label": "用"}]},
        {"nodes": [{"id": "1", "label": "硅碳负极", "category": "材料"},
                   {"id": "2", "label": "SEI膜", "category": "材料"}],
         "edges": [{"source": "1", "target": "2", "label": "形成"}]},
    ]
    graph = graph_api._merge_graph_parts(parts)

    assert {n["label"] for n in graph["nodes"]} == {"钙钛矿", "旋涂法", "硅碳负极", "SEI膜"}
    assert len(graph["nodes"]) == 4
    assert len(graph["edges"]) == 2
    # 两批各有一条边，绝不允许出现跨批的连线
    assert _pairs(graph) == {("钙钛矿", "旋涂法"), ("硅碳负极", "SEI膜")}


def test_merge_parts_dedupes_same_label_and_repeated_edges():
    parts = [
        {"nodes": [{"id": "a", "label": "钙钛矿"}, {"id": "b", "label": "稳定性"}],
         "edges": [{"source": "a", "target": "b", "label": "影响"}]},
        {"nodes": [{"id": "x", "label": "钙钛矿 "}, {"id": "y", "label": "稳定性"}],
         "edges": [{"source": "x", "target": "y", "label": "影响"},
                   {"source": "x", "target": "y", "label": "影响"}]},
    ]
    graph = graph_api._merge_graph_parts(parts)

    assert len(graph["nodes"]) == 2
    assert len(graph["edges"]) == 1


def test_merge_parts_drops_self_loops_and_dangling_edges():
    parts = [{
        "nodes": [{"id": "a", "label": "钙钛矿"}],
        "edges": [{"source": "a", "target": "a", "label": "自指"},
                  {"source": "a", "target": "ghost", "label": "悬空"}],
    }]
    graph = graph_api._merge_graph_parts(parts)

    assert graph["edges"] == []
    assert len(graph["nodes"]) == 1


def test_merge_parts_tolerates_junk_shapes():
    parts = [None, "oops", {"nodes": None, "edges": None}, {"nodes": [{}]}]
    graph = graph_api._merge_graph_parts(parts)

    assert graph == {"nodes": [], "edges": []}


def test_cache_stale_when_memory_total_changed(monkeypatch):
    graph_api._stale_probe["at"] = 0.0
    monkeypatch.setattr(graph_api, "_current_memory_total", lambda: 130)

    assert graph_api._cache_is_stale({"nodes": [1], "memory_count": 105}) is True


def test_cache_stale_unknown_total_keeps_cache(monkeypatch):
    """A probe failure must never throw the existing graph away."""
    graph_api._stale_probe["at"] = 0.0
    monkeypatch.setattr(graph_api, "_current_memory_total", lambda: None)

    assert graph_api._cache_is_stale({"nodes": [1], "memory_count": 105}) is False


def test_cache_stale_probe_is_throttled(monkeypatch):
    graph_api._stale_probe["at"] = time.time()
    monkeypatch.setattr(graph_api, "_current_memory_total", lambda: 999)

    assert graph_api._cache_is_stale({"nodes": [1], "memory_count": 105}) is False


class _FakeProvider:
    _backend = object()

    def list_memories(self, *, page=1, page_size=50, offset=None):
        rows = [{"id": "1", "memory": "[材料] 钙钛矿太阳能电池"},
                {"id": "2", "memory": "[方法] 旋涂法制膜"}]
        if offset not in (None, 0):
            return {"results": [], "total": 2, "has_more": False}
        return {"results": rows, "count": 2, "total": 2, "has_more": False}


def test_fetch_memories_enumerates_whole_store(monkeypatch):
    import matlens_kit.api.mem_api as mem_api

    monkeypatch.setattr(mem_api, "_get_provider", lambda: _FakeProvider())

    rows = graph_api._fetch_memories()

    assert [r["memory"] for r in rows] == ["[材料] 钙钛矿太阳能电池", "[方法] 旋涂法制膜"]
    assert [r["category"] for r in rows] == ["材料", "方法"]


def test_fetch_memories_returns_nothing_without_backend(monkeypatch):
    import matlens_kit.api.mem_api as mem_api

    class _NoBackend:
        _backend = None

    monkeypatch.setattr(mem_api, "_get_provider", lambda: _NoBackend())

    assert graph_api._fetch_memories() == []


def test_degraded_rebuild_must_not_overwrite_a_real_graph():
    """LLM 抽取失败时产物是启发式图，拿它顶替真图等于把图降级成垃圾。"""
    previous = {"nodes": [{"id": "n1", "label": "钙钛矿"}], "fallback": False}
    candidate = {"nodes": [{"id": "m1", "label": "很长的一句记忆…"}], "fallback": True}

    assert graph_api._should_replace(previous, candidate) is False


def test_degraded_rebuild_may_replace_an_equally_degraded_graph():
    previous = {"nodes": [{"id": "m1", "label": "旧"}], "fallback": True}
    candidate = {"nodes": [{"id": "m1", "label": "新"}], "fallback": True}

    assert graph_api._should_replace(previous, candidate) is True


def test_rebuild_allowed_when_extraction_succeeded():
    previous = {"nodes": [{"id": "n1", "label": "钙钛矿"}], "fallback": False}
    candidate = {"nodes": [{"id": "n1", "label": "钙钛矿"}], "fallback": False}

    assert graph_api._should_replace(previous, candidate) is True


def test_empty_rebuild_never_overwrites():
    previous = {"nodes": [{"id": "n1", "label": "钙钛矿"}], "fallback": False}

    assert graph_api._should_replace(previous, {"nodes": [], "edges": []}) is False


def test_manual_extract_keeps_previous_graph_when_extraction_degrades(monkeypatch, tmp_path):
    """手动点"重新抽取"也得过降级门：一次失败不该把好图换掉。"""
    cache = tmp_path / "graph.json"
    cache.write_text(
        json.dumps({"nodes": [{"id": "n1", "label": "钙钛矿"}], "edges": [], "fallback": False}),
        encoding="utf-8",
    )
    monkeypatch.setattr(graph_api, "_GRAPH_PATH", cache)
    monkeypatch.setattr(graph_api, "_graph_auto_build_enabled", lambda: True)
    monkeypatch.setattr(
        graph_api, "_build_graph",
        lambda force=False: {"nodes": [{"id": "m1", "label": "一整句记忆"}],
                             "edges": [], "fallback": True},
    )

    out = graph_api.extract_graph()

    assert out["fallback"] is True
    assert out["skipped"] is True
    saved = json.loads(cache.read_text(encoding="utf-8"))
    assert saved["fallback"] is False
    assert saved["nodes"][0]["label"] == "钙钛矿"


def test_manual_extract_writes_when_extraction_succeeds(monkeypatch, tmp_path):
    cache = tmp_path / "graph.json"
    cache.write_text(
        json.dumps({"nodes": [{"id": "n1", "label": "旧"}], "edges": [], "fallback": False}),
        encoding="utf-8",
    )
    monkeypatch.setattr(graph_api, "_GRAPH_PATH", cache)
    monkeypatch.setattr(graph_api, "_graph_auto_build_enabled", lambda: True)
    monkeypatch.setattr(
        graph_api, "_build_graph",
        lambda force=False: {"nodes": [{"id": "n1", "label": "新"}], "edges": [], "fallback": False},
    )

    out = graph_api.extract_graph()

    assert out.get("skipped") is None
    saved = json.loads(cache.read_text(encoding="utf-8"))
    assert saved["nodes"][0]["label"] == "新"
