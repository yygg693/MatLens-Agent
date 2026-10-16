# -*- coding: utf-8 -*-
"""paper.search 单测：mock 网络，验证降级/过滤/返回结构。"""
from __future__ import annotations

import io
import json
import sys
import types

import pytest

# 让 import 在 D:\MatLens 下可用
sys.path.insert(0, r"D:\MatLens")

from matlens_kit.paper import search as S  # noqa: E402


# ---------------------------------------------------------------------------
# 工具：构造假 urlopen
# ---------------------------------------------------------------------------
class _FakeResp:
    def __init__(self, payload):
        self._raw = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def read(self):
        return self._raw.read()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _make_urlopen(route):
    """route: callable(url, timeout) -> payload 或 raise。"""
    def _urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        return route(url, timeout)
    return _urlopen


# ---------------------------------------------------------------------------
# 1. OpenAlex 抛异常 → 走 Crossref 解析成功
# ---------------------------------------------------------------------------
def test_openalex_fails_then_crossref_succeeds(monkeypatch):
    def route(url, timeout):
        if "openalex.org" in url:
            raise OSError("network down")
        if "crossref.org" in url:
            return _FakeResp({
                "message": {
                    "items": [
                        {
                            "title": ["GDC 电解质在中温 SOFC 中的离子传导研究"],
                            "author": [{"given": "Wei", "family": "Zhang"}, {"given": "Li", "family": "Wang"}],
                            "issued": {"date-parts": [[2022]]},
                            "container-title": ["Journal of Power Sources"],
                            "DOI": "10.1000/xyz123",
                        }
                    ]
                }
            })
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(S.urllib.request, "urlopen", _make_urlopen(route))

    refs = S.search_openalex("GDC electrolyte", per_page=5, timeout=2.0)
    assert refs == [], "OpenAlex should return [] on network error"

    cr = S.search_crossref("GDC electrolyte", rows=5, timeout=2.0)
    assert len(cr) == 1
    assert cr[0]["title"].startswith("GDC")
    assert "Crossref" in cr[0]["source"]
    assert "2022" in cr[0]["year"]
    assert "Zhang" in cr[0]["authors"]


# ---------------------------------------------------------------------------
# 2. 两者都抛 → 返回 [] 不崩
# ---------------------------------------------------------------------------
def test_both_channels_fail_return_empty(monkeypatch):
    def route(url, timeout):
        raise OSError("total network failure")

    monkeypatch.setattr(S.urllib.request, "urlopen", _make_urlopen(route))

    oa = S.search_openalex("anything", per_page=5, timeout=1.0)
    cr = S.search_crossref("anything", rows=5, timeout=1.0)
    combined, oa_hit, cr_hit = S._search_network("anything", 5)
    assert oa == []
    assert cr == []
    assert combined == []
    assert oa_hit is False and cr_hit is False


# ---------------------------------------------------------------------------
# 3. search_local_kb 异常 → []
# ---------------------------------------------------------------------------
def test_local_kb_exception_returns_empty(monkeypatch):
    # 让 import local_rag.get_manager 抛
    fake_mod = types.ModuleType("matlens_kit.plugins.local_rag")

    def _boom():
        raise RuntimeError("kb crashed")

    fake_mod.get_manager = _boom
    monkeypatch.setitem(sys.modules, "matlens_kit.plugins.local_rag", fake_mod)

    refs = S.search_local_kb("固态氧化物燃料电池", top_k=5)
    assert refs == []


def test_local_kb_no_active_returns_empty(monkeypatch):
    fake_mod = types.ModuleType("matlens_kit.plugins.local_rag")

    class _Mgr:
        active = None

        def get(self, name):
            return None

    fake_mod.get_manager = lambda: _Mgr()
    monkeypatch.setitem(sys.modules, "matlens_kit.plugins.local_rag", fake_mod)

    assert S.search_local_kb("topic", top_k=3) == []


# ---------------------------------------------------------------------------
# 4. 弱条目过滤
# ---------------------------------------------------------------------------
def test_weak_entry_filtering():
    entries = [
        {"title": "固态氧化物燃料电池 GDC 电解质离子电导率研究", "source": "OpenAlex", "score": 0.5},
        {"title": "", "source": "OpenAlex", "score": 0.5},  # 空
        {"title": "short", "source": "OpenAlex", "score": 0.5},  # 过短
        {"title": "raw_notes_v1.txt", "source": "本地知识库·default", "score": 0.5},  # .txt
        {"title": "local_doc_2024_final", "source": "本地知识库·default", "score": 0.01},  # 本地低分
        {"title": "Local KB result on GDC electrolyte performance", "source": "本地知识库·default", "score": 0.2},
    ]
    kept = S._filter_weak(entries)
    titles = [r["title"] for r in kept]
    assert "固态氧化物燃料电池 GDC 电解质离子电导率研究" in titles
    assert "Local KB result on GDC electrolyte performance" in titles
    assert "" not in titles
    assert "short" not in titles
    assert "raw_notes_v1.txt" not in titles
    assert "local_doc_2024_final" not in titles


# ---------------------------------------------------------------------------
# 5. run_dual_search 返回结构含 count/queries/refs/channels
# ---------------------------------------------------------------------------
def test_run_dual_search_structure(monkeypatch):
    # 强制不走 LLM 改写
    monkeypatch.setattr(S, "query_rewrite", lambda topic: [topic])
    # 本地 KB 走空
    monkeypatch.setattr(S, "search_local_kb", lambda q, top_k=5: [])
    # OpenAlex 抛，Crossref 返回 1 条
    def route(url, timeout):
        if "openalex.org" in url:
            raise OSError("oa down")
        if "crossref.org" in url:
            return _FakeResp({
                "message": {
                    "items": [
                        {
                            "title": ["GDC 中温电解质燃料电池性能综述"],
                            "author": [{"given": "San", "family": "Zhang"}],
                            "issued": {"date-parts": [[2023]]},
                            "container-title": ["Fuel Cells"],
                            "DOI": "10.1/test.abc",
                        }
                    ]
                }
            })
        raise AssertionError(url)

    monkeypatch.setattr(S.urllib.request, "urlopen", _make_urlopen(route))

    out = S.run_dual_search("SOFC GDC electrolyte", top_k=8, use_llm_rewrite=False, auto_queries=False)
    assert out["ok"] is True
    assert "count" in out and out["count"] >= 1
    assert "queries" in out and out["queries"] == ["SOFC GDC electrolyte"]
    assert "refs" in out and isinstance(out["refs"], list)
    assert "channels" in out
    assert out["channels"] == {"local": False, "openalex": False, "crossref": True}
    # 编号
    assert out["refs"][0]["index"] == 1


# ---------------------------------------------------------------------------
# 6. query_rewrite 无 key → 回退 [topic]
# ---------------------------------------------------------------------------
def test_query_rewrite_no_key(monkeypatch):
    # 模拟无 DEEPSEEK_API_KEY
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    # 防止 dotenv 偷偷从 ~/.matlens/.env 加载 key
    def _fake_load_dotenv(*a, **kw):
        return False

    monkeypatch.setattr("dotenv.load_dotenv", _fake_load_dotenv, raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")  # 明确置空

    qs = S.query_rewrite("固态氧化物燃料电池")
    assert qs == ["固态氧化物燃料电池"]


# ---------------------------------------------------------------------------
# 7. render_refs 输出含编号/作者/年份/刊名/DOI
# ---------------------------------------------------------------------------
def test_render_refs_contains_fields():
    refs = [
        {
            "index": 1,
            "title": "GDC electrolyte intermediate temperature SOFC",
            "authors": "Wei Zhang, Li Wang",
            "year": "2022",
            "source": "Crossref·Journal of Power Sources",
            "doi": "https://doi.org/10.1000/xyz",
        }
    ]
    md = S.render_refs(refs)
    assert "[1]" in md
    assert "GDC electrolyte" in md
    assert "Wei Zhang" in md
    assert "2022" in md
    assert "Journal of Power Sources" in md
    assert "10.1000/xyz" in md


def test_render_refs_empty():
    md = S.render_refs([])
    assert "未命中" in md


# ---------------------------------------------------------------------------
# 8. 方法学扩充：SOFC 主题触发追加，非材料主题不触发
# ---------------------------------------------------------------------------
def test_detect_methodology_sofc_topic():
    dims = S._detect_methodology_queries(
        "固态氧化物燃料电池 电解质 GDC 中温固体氧化物燃料电池"
    )
    tags = [t for t, _ in dims]
    assert "GDC_SINGLE_CELL" in tags
    assert "EIS_DRT" in tags
    assert "HEBB_WAGNER" in tags
    assert "SPACE_CHARGE" in tags
    # v3 新增维度
    assert "CA_DOPED_GDC" in tags
    assert "ALKALINE_DOPED_CERIA" in tags
    assert "CO_SINTERING_AID_GB" in tags
    assert "LSCF_GDC_INTERFACE" in tags
    assert "DRT_REGULARIZATION" in tags


def test_detect_methodology_non_material_topic():
    dims = S._detect_methodology_queries("大语言模型推理优化 分布式缓存")
    assert dims == []


# ---------------------------------------------------------------------------
# 9. run_dual_search：方法学查询被追加、合并去重编号、非材料主题不追加
# ---------------------------------------------------------------------------
def _fake_openalex_payload(title: str):
    return {
        "results": [
            {
                "title": title,
                "publication_year": 2023,
                "authorships": [{"author": {"display_name": "A Author"}}],
                "primary_location": {"source": {"display_name": "Some Journal"}},
                "doi": f"https://doi.org/10.1000/{abs(hash(title)) % 100000}",
            }
        ]
    }


def test_run_dual_search_appends_methodology_for_sofc(monkeypatch):
    """SOFC 主题 → 方法学查询被追加，refs 合并去重后连续编号。"""
    monkeypatch.setattr(S, "query_rewrite", lambda topic: [topic])
    monkeypatch.setattr(S, "search_local_kb", lambda q, top_k=5: [])

    # 每个 url 都返回 1 条不同 title 的 OpenAlex 结果
    counter = {"n": 0}

    def route(url, timeout):
        if "openalex.org" in url:
            counter["n"] += 1
            # 从 URL 里抽出 search 词，拼成稳定 title
            return _FakeResp(_fake_openalex_payload(f"Paper about query {counter['n']}"))
        if "crossref.org" in url:
            return _FakeResp({"message": {"items": []}})
        raise AssertionError(url)

    monkeypatch.setattr(S.urllib.request, "urlopen", _make_urlopen(route))

    out = S.run_dual_search(
        "固态氧化物燃料电池 电解质 GDC 中温固体氧化物燃料电池",
        top_k=8,
        use_llm_rewrite=False,
    )
    # 主查询 1 条 + 4 个方法学维度各 1 条 = 5 条（不同 title）
    assert out["count"] >= 5
    # 方法学查询被追加到 queries
    assert len(out["meth_queries"]) == len(S._SOFC_METHODOLOGY_QUERIES)
    # 编号连续 1..N
    idxs = [r["index"] for r in out["refs"]]
    assert idxs == list(range(1, out["count"] + 1))
    # 至少有若干条带 meth 标签（每个方法学维度至少 1 条，按 floor 策略）
    meth_tags = {r.get("meth") for r in out["refs"] if r.get("meth")}
    assert len(meth_tags) >= 4


def test_run_dual_search_no_methodology_for_non_material(monkeypatch):
    monkeypatch.setattr(S, "query_rewrite", lambda topic: [topic])
    monkeypatch.setattr(S, "search_local_kb", lambda q, top_k=5: [])

    def route(url, timeout):
        if "openalex.org" in url:
            return _FakeResp(_fake_openalex_payload("LLM inference optimization paper"))
        if "crossref.org" in url:
            return _FakeResp({"message": {"items": []}})
        raise AssertionError(url)

    monkeypatch.setattr(S.urllib.request, "urlopen", _make_urlopen(route))

    out = S.run_dual_search(
        "大语言模型推理优化",
        top_k=8,
        use_llm_rewrite=False,
    )
    # 非材料主题 → 不追加方法学查询
    assert out["meth_queries"] == []
    # refs 数 = 主题查询命中数（这里 1）
    assert out["count"] == 1
