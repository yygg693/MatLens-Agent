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


def test_cooc_bridges_join_entities_that_share_a_memory():
    """分批抽取连不起来的两批实体，靠同条记忆共现补桥。"""
    nodes = [{"id": "n0", "label": "钙钛矿"}, {"id": "n1", "label": "旋涂法"}]
    memos = [{"memory": "[方法] 钙钛矿用旋涂法制备"}]

    bridges = graph_api._cooc_bridges(nodes, memos, [])

    assert len(bridges) == 1
    assert bridges[0]["kind"] == "cooc"
    assert {bridges[0]["source"], bridges[0]["target"]} == {"n0", "n1"}


def test_cooc_bridges_do_not_duplicate_semantic_edges():
    nodes = [{"id": "n0", "label": "钙钛矿"}, {"id": "n1", "label": "旋涂法"}]
    memos = [{"memory": "钙钛矿用旋涂法制备"}]
    edges = [{"id": "e0", "source": "n1", "target": "n0", "label": "用", "kind": "semantic"}]

    assert graph_api._cooc_bridges(nodes, memos, edges) == []


def test_cooc_bridges_match_longest_label_first():
    """短 label 命中长 label 内部时不能算两个实体，否则会凭空多出一对。"""
    nodes = [{"id": "n0", "label": "Gd掺杂CeO2"},
             {"id": "n1", "label": "GDC-Ca共掺杂电解质"},
             {"id": "n2", "label": "阻抗"}]
    memos = [{"memory": "测试 Gd掺杂CeO2 的阻抗"}]

    bridges = graph_api._cooc_bridges(nodes, memos, [])

    assert len(bridges) == 1
    assert {bridges[0]["source"], bridges[0]["target"]} == {"n0", "n2"}


def test_cooc_bridges_only_bridge_the_gap():
    """三个实体同框，但其中两点已有语义边：只补一条能连上第三点的桥。"""
    nodes = [{"id": "n0", "label": "钙钛矿"},
             {"id": "n1", "label": "旋涂法"},
             {"id": "n2", "label": "阻抗"}]
    memos = [{"memory": "钙钛矿旋涂法测阻抗"}]
    edges = [{"id": "e0", "source": "n0", "target": "n1", "label": "用", "kind": "semantic"}]

    bridges = graph_api._cooc_bridges(nodes, memos, edges)

    assert len(bridges) == 1
    assert "n2" in (bridges[0]["source"], bridges[0]["target"])


def test_cooc_bridges_stop_when_the_graph_is_already_connected():
    """已经连通就不再补，否则短名实体（用户/GDC）会长出几百条噪声边。"""
    nodes = [{"id": "n0", "label": "钙钛矿"},
             {"id": "n1", "label": "阻抗"}]
    memos = [{"memory": "钙钛矿的阻抗"}, {"memory": "钙钛矿阻抗偏高"}]
    edges = [{"id": "e0", "source": "n0", "target": "n1", "label": "有", "kind": "semantic"}]

    assert graph_api._cooc_bridges(nodes, memos, edges) == []


def test_cooc_bridges_skip_single_mention_memories():
    nodes = [{"id": "n0", "label": "钙钛矿"}]
    memos = [{"memory": "钙钛矿的长期稳定性"}]

    assert graph_api._cooc_bridges(nodes, memos, []) == []


def test_llm_extract_hands_known_labels_to_the_model(monkeypatch):
    """后一批要复用前一批的实体名，否则同一个人被抽成三个节点。"""
    from types import SimpleNamespace

    captured = {}

    def fake_create(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"nodes":[],"edges":[]}'))]
        )

    class _FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=fake_create))

    import openai

    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    monkeypatch.setattr(graph_api, "_get_deepseek_key", lambda: "sk-test")
    monkeypatch.setattr(graph_api, "_DEEPSEEK_BASE_URL", "https://example.com/v1")

    graph_api._llm_extract(
        [{"id": "1", "memory": "钙钛矿长期稳定性差", "category": "结论"}],
        ["固态电池", "用户"],
    )

    user_prompt = captured["messages"][1]["content"]
    assert "固态电池" in user_prompt and "用户" in user_prompt
    assert "复用" in user_prompt
