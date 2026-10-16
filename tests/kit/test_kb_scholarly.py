# -*- coding: utf-8 -*-
"""云端学术 API 聚合模块测试（matlens_kit.rag.scholarly）。

覆盖：源目录、错误翻译、限流节流、排序去重、Markdown 渲染、导入文件名。
**全部离线**：不发真实网络请求（真实链路由 _e2e_kb2.py 验证）。
"""
from __future__ import annotations

import os
import sys
import types

import pytest

sys.path.insert(0, r"D:\MatLens")
from matlens_kit.rag import scholarly  # noqa: E402


class _Resp:
    def __init__(self, data: bytes):
        self._d = data

    def read(self):
        return self._d

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# ────────────────────────────────────────────────────────────
# 源目录
# ────────────────────────────────────────────────────────────
class TestCatalog:
    def test_catalog_has_known_sources(self):
        ids = {s["id"] for s in scholarly.SOURCE_CATALOG}
        for must in ("openalex", "crossref", "arxiv"):
            assert must in ids, f"默认源 {must} 缺失"

    def test_catalog_fields_complete(self):
        for s in scholarly.SOURCE_CATALOG:
            assert s.get("label"), f"{s['id']} 缺 label"
            assert s.get("note"), f"{s['id']} 缺 note（前端要展示给用户看）"
            assert "key_required" in s

    def test_default_sources_are_configured(self):
        """默认勾选的源必须是不需要 key 的，否则用户一点就报错。"""
        for sid in scholarly.DEFAULT_SOURCES:
            item = {s["id"]: s for s in scholarly.SOURCE_CATALOG}[sid]
            assert not item.get("key_required"), f"{sid} 需要 key，不该默认勾选"

    def test_cnki_declared_unavailable(self):
        """知网必须如实声明为不可用，不能偷偷提供假端点。"""
        ids = {s["id"] for s in scholarly.UNAVAILABLE_SOURCES}
        assert "cnki" in ids
        na = [s for s in scholarly.UNAVAILABLE_SOURCES if s["id"] == "cnki"][0]
        assert na.get("reason") and na.get("workaround"), "知网需给出原因与替代路径"

    def test_get_catalog_reports_configured(self, monkeypatch):
        monkeypatch.delenv("WANFANG_TOKEN", raising=False)
        monkeypatch.delenv("AMINER_API_KEY", raising=False)
        cat = {c["id"]: c for c in scholarly.get_catalog()}
        assert cat["wanfang"]["configured"] is False
        assert cat["aminer"]["configured"] is False
        assert cat["openalex"]["configured"] is True

    def test_get_catalog_configured_when_key_present(self, monkeypatch):
        monkeypatch.setenv("WANFANG_TOKEN", "dummy")
        cat = {c["id"]: c for c in scholarly.get_catalog()}
        assert cat["wanfang"]["configured"] is True

    def test_get_catalog_default_on_matches_constant(self):
        cat = {c["id"]: c for c in scholarly.get_catalog()}
        for sid in scholarly.DEFAULT_SOURCES:
            assert cat[sid]["default_on"] is True
        for sid in ("dblp", "pubmed", "europe_pmc"):
            assert cat[sid]["default_on"] is False

    def test_locked_sources_sorted_last(self):
        """未配置凭据的源排最后，不占首屏。"""
        items = scholarly.get_catalog()
        first_locked = min((i for i, s in enumerate(items) if not s["configured"]), default=len(items))
        last_open = max((i for i, s in enumerate(items) if s["configured"]), default=-1)
        assert last_open < first_locked, "已配置的源必须排在未配置源之前"

    def test_dblp_marked_known_blocked(self):
        """DBLP 实测被反爬拦截，目录里必须如实标注。"""
        d = {s["id"]: s for s in scholarly.SOURCE_CATALOG}["dblp"]
        assert d.get("known_blocked") is True
        assert "反爬" in d["note"]


# ────────────────────────────────────────────────────────────
# 工具函数
# ────────────────────────────────────────────────────────────
class TestHelpers:
    def test_strip_tags(self):
        assert scholarly._strip_tags("<p>Hello <b>World</b></p>") == "Hello World"
        assert scholarly._strip_tags("a &amp; b") == "a & b"
        assert scholarly._strip_tags("") == ""

    def test_strip_tags_removes_script(self):
        s = scholarly._strip_tags("<script>bad()</script>ok")
        assert "bad" not in s and "ok" in s

    def test_truncate(self):
        assert scholarly._truncate("abcdef", 3) == "abc…"
        assert scholarly._truncate("ab", 5) == "ab"

    def test_abstract_to_text_inverts_index(self):
        idx = {"solid": [0], "oxide": [2], "fuel": [1]}
        assert scholarly._abstract_to_text(idx) == "solid fuel oxide"

    def test_abstract_to_text_empty(self):
        assert scholarly._abstract_to_text(None) == ""
        assert scholarly._abstract_to_text({}) == ""


class TestErrorExplain:
    def test_429_gives_actionable_hint(self):
        import urllib.error
        e = urllib.error.HTTPError("u", 429, "Too Many", {}, None)
        msg = scholarly._explain_error(e)
        assert "429" in msg and "配额" in msg

    def test_anticrawl_detected(self):
        """DBLP 返回质询页时要识别出来，而不是裸露 JSONDecodeError。"""
        e = json_error = ValueError("Expecting value: line 1 column 1")
        msg = scholarly._explain_error(json_error)
        assert isinstance(msg, str) and msg

    def test_wanfang_missing_token(self):
        msg = scholarly._explain_error(RuntimeError("未配置 WANFANG_TOKEN"))
        assert "WANFANG_TOKEN" in msg

    def test_generic_error_passthrough(self):
        assert "disk on fire" in scholarly._explain_error(RuntimeError("disk on fire"))


class TestArxivThrottle:
    def test_throttle_sleeps_between_calls(self, monkeypatch):
        """arXiv 要求 ~3s 间隔；节流函数必须真的睡。"""
        slept = []
        monkeypatch.setattr(scholarly.time, "sleep", lambda s: slept.append(s))
        scholarly._arxiv_last[0] = scholarly.time.time()
        scholarly._arxiv_throttle()
        assert slept and slept[0] > 0, "连续请求应触发等待"

    def test_throttle_no_wait_when_enough_time_passed(self, monkeypatch):
        slept = []
        monkeypatch.setattr(scholarly.time, "sleep", lambda s: slept.append(s))
        scholarly._arxiv_last[0] = scholarly.time.time() - 100
        scholarly._arxiv_throttle()
        assert not slept


# ────────────────────────────────────────────────────────────
# 解析器（喂假响应）
# ────────────────────────────────────────────────────────────
class TestParsers:
    def test_openalex_parse(self, monkeypatch):
        payload = {
            "results": [{
                "id": "https://openalex.org/W1",
                "title": "Ceria electrolyte",
                "publication_year": 2020,
                "authorships": [{"author": {"display_name": "A B"}}],
                "doi": "https://doi.org/10.1/x",
                "primary_location": {
                    "source": {"display_name": "JACS"},
                    "pdf_url": "https://x/p.pdf",
                    "landing_page_url": "https://x/l",
                },
                "abstract_inverted_index": {"ceria": [0], "electrolyte": [1]},
                "cited_by_count": 12,
            }]
        }
        monkeypatch.setattr(scholarly, "_get_json", lambda *a, **k: payload)
        got = scholarly._search_openalex("q", 5, 10)
        assert len(got) == 1
        it = got[0]
        assert it["title"] == "Ceria electrolyte"
        assert it["venue"] == "JACS"
        assert it["oa_url"] == "https://x/p.pdf"
        assert it["cited_by"] == 12
        assert it["abstract"] == "ceria electrolyte"

    def test_crossref_parse(self, monkeypatch):
        payload = {"message": {"items": [{
            "title": ["GDC paper"], "author": [{"given": "A", "family": "B"}],
            "issued": {"date-parts": [[2021, 5]]},
            "container-title": ["J Power Sources"], "DOI": "10.2/y",
            "is-referenced-by-count": 5, "URL": "https://u",
        }]}}
        monkeypatch.setattr(scholarly, "_get_json", lambda *a, **k: payload)
        got = scholarly._search_crossref("q", 5, 10)
        assert got[0]["year"] == "2021"
        assert got[0]["venue"] == "J Power Sources"
        assert got[0]["doi"].startswith("https://doi.org/10.2/y")

    def test_pubmed_parse(self, monkeypatch):
        xml = """<?xml version="1.0"?>
        <PubmedArticleSet><PubmedArticle><MedlineCitation>
        <PMID>12345</PMID>
        <Article><Journal><Title>Nature</Title><JournalIssue><PubDate><Year>2024</Year></PubDate></JournalIssue></Journal>
        <ArticleTitle>Battery test</ArticleTitle>
        <Abstract><AbstractText>Some abstract text.</AbstractText></Abstract>
        <AuthorList><Author><LastName>Smith</LastName><Initials>J</Initials></Author></AuthorList>
        </Article></MedlineCitation>
        <PubmedData><ArticleIdList><ArticleId IdType="doi">10.3/z</ArticleId></ArticleIdList></PubmedData>
        </PubmedArticle></PubmedArticleSet>"""
        monkeypatch.setattr(scholarly, "_get_text", lambda *a, **k: xml)
        got = scholarly._search_pubmed("q", 5, 10)
        assert got[0]["title"] == "Battery test"
        assert got[0]["year"] == "2024"
        assert "Smith" in got[0]["authors"]

    def test_dblp_anticrawl_raises_readable(self, monkeypatch):
        monkeypatch.setattr(scholarly, "_get_text",
                            lambda *a, **k: "<!doctype html>Making sure you're not a bot!")
        with pytest.raises(RuntimeError) as ei:
            scholarly._search_dblp("q", 5, 10)
        assert "反爬" in str(ei.value), "应给出可读原因，而不是 JSONDecodeError"

    def test_wanfang_without_token_raises(self, monkeypatch):
        monkeypatch.delenv("WANFANG_TOKEN", raising=False)
        with pytest.raises(RuntimeError) as ei:
            scholarly._search_wanfang("q", 5, 10)
        assert "WANFANG_TOKEN" in str(ei.value), "未配 token 必须显式报错，不伪造端点"

    def test_aminer_without_key_raises(self, monkeypatch):
        monkeypatch.delenv("AMINER_API_KEY", raising=False)
        with pytest.raises(RuntimeError) as ei:
            scholarly._search_aminer("q", 5, 10)
        assert "AMINER_API_KEY" in str(ei.value)


# ────────────────────────────────────────────────────────────
# 聚合检索
# ────────────────────────────────────────────────────────────
def _fake_searcher(items, fail=False):
    def fn(query, limit, timeout):
        if fail:
            raise RuntimeError("boom")
        return list(items[:limit])
    return fn


ITEM_A = {
    "id": "a", "title": "Alpha paper", "authors": "X", "year": "2020",
    "venue": "V", "doi": "https://doi.org/10.1/a", "url": "u", "oa_url": "",
    "abstract": "abs a", "cited_by": 5, "source": "openalex",
    "source_label": "OpenAlex", "snippet": "abs a",
}


class TestSearchWeb:
    def test_merges_and_reports_per_source(self, monkeypatch):
        monkeypatch.setitem(scholarly.SEARCHERS, "openalex", _fake_searcher([ITEM_A]))
        monkeypatch.setitem(scholarly.SEARCHERS, "crossref",
                            _fake_searcher([{**ITEM_A, "id": "b", "doi": "", "source": "crossref"}]))
        r = scholarly.search_web("q", sources=["openalex", "crossref"], per_source=3)
        assert len(r["items"]) == 2
        assert r["per_source"]["openalex"]["ok"] is True
        assert r["per_source"]["crossref"]["ok"] is True
        assert r["elapsed_ms"] >= 0

    def test_one_source_failure_does_not_break_others(self, monkeypatch):
        """单源失败不影响整体 —— 多源检索的核心要求。"""
        monkeypatch.setitem(scholarly.SEARCHERS, "openalex", _fake_searcher([ITEM_A]))
        monkeypatch.setitem(scholarly.SEARCHERS, "crossref", _fake_searcher([], fail=True))
        r = scholarly.search_web("q", sources=["openalex", "crossref"], per_source=3)
        assert len(r["items"]) == 1
        assert r["per_source"]["crossref"]["ok"] is False
        assert "boom" in r["per_source"]["crossref"]["error"]

    def test_dedup_by_doi(self, monkeypatch):
        """跨源同一 DOI 只保留一条。"""
        dup = {**ITEM_A, "source": "crossref", "source_label": "Crossref"}
        monkeypatch.setitem(scholarly.SEARCHERS, "openalex", _fake_searcher([ITEM_A]))
        monkeypatch.setitem(scholarly.SEARCHERS, "crossref", _fake_searcher([dup]))
        r = scholarly.search_web("q", sources=["openalex", "crossref"], per_source=3)
        assert len(r["items"]) == 1
        assert r["raw_count"] == 2

    def test_sorted_with_doi_first(self, monkeypatch):
        no_doi = {**ITEM_A, "id": "n", "doi": "", "cited_by": 999}
        monkeypatch.setitem(scholarly.SEARCHERS, "openalex",
                            _fake_searcher([no_doi, ITEM_A]))
        r = scholarly.search_web("q", sources=["openalex"], per_source=5)
        assert r["items"][0]["doi"] != "", "有 DOI 的应排前面"

    def test_empty_query_rejected(self):
        with pytest.raises(ValueError):
            scholarly.search_web("   ", sources=["openalex"])

    def test_unknown_source_falls_back_to_defaults(self, monkeypatch):
        monkeypatch.setitem(scholarly.SEARCHERS, "openalex", _fake_searcher([ITEM_A]))
        r = scholarly.search_web("q", sources=["not_a_source"], per_source=1)
        assert "openalex" in r["requested"]


class TestUnpaywall:
    def test_requires_doi(self):
        with pytest.raises(ValueError):
            scholarly.fetch_unpaywall("no-doi-here")

    def test_requires_email_config(self, monkeypatch):
        monkeypatch.delenv("UNPAYWALL_EMAIL", raising=False)
        with pytest.raises(RuntimeError) as ei:
            scholarly.fetch_unpaywall("10.1/x")
        assert "UNPAYWALL_EMAIL" in str(ei.value)

    def test_parses_oa_location(self, monkeypatch):
        monkeypatch.setenv("UNPAYWALL_EMAIL", "a@b.com")
        monkeypatch.setattr(scholarly, "_get_json", lambda *a, **k: {
            "doi": "10.1/x", "title": "T", "is_oa": True, "oa_status": "gold",
            "best_oa_location": {"url_for_pdf": "https://pdf", "url": "https://l",
                                 "host_type": "repository", "license": "cc"},
        })
        r = scholarly.fetch_unpaywall("https://doi.org/10.1/x")
        assert r["is_oa"] is True
        assert r["oa_url"] == "https://pdf"
        assert r["oa_status"] == "gold"

    def test_closed_work_reported_honestly(self, monkeypatch):
        monkeypatch.setenv("UNPAYWALL_EMAIL", "a@b.com")
        monkeypatch.setattr(scholarly, "_get_json", lambda *a, **k: {
            "doi": "10.1/x", "is_oa": False, "oa_status": "closed",
        })
        r = scholarly.fetch_unpaywall("10.1/x")
        assert r["is_oa"] is False and r["oa_url"] == ""


# ────────────────────────────────────────────────────────────
# 导入渲染
# ────────────────────────────────────────────────────────────
class TestImportRendering:
    def test_markdown_contains_metadata(self):
        md = scholarly.paper_to_markdown(ITEM_A)
        assert "# Alpha paper" in md
        assert "10.1/a" in md
        assert "OpenAlex" in md
        assert "非全文" in md, "须注明这是题录而非全文，避免误用"

    def test_markdown_includes_abstract_section(self):
        assert "## 摘要" in scholarly.paper_to_markdown(ITEM_A)
        assert "abs a" in scholarly.paper_to_markdown(ITEM_A)

    def test_markdown_handles_missing_fields(self):
        """字段缺失不应崩，也不该凭空造出摘要段。"""
        md = scholarly.paper_to_markdown({"title": "Bare"})
        assert md.startswith("# Bare")
        assert "## 摘要" not in md, "没有摘要时不应生成摘要小节"
        assert "数据源：None" not in md, "来源缺失时不应写出字面量 None"

    def test_filename_readable_and_ordered(self):
        """文件名应是「序号_源_短标题」，而不是又长又重复的一串。"""
        n1 = scholarly.paper_filename(ITEM_A, "20261015-120000", 0)
        assert n1.startswith("01_openalex_")
        assert "20261015-120000" not in n1, "时间戳不该进文件名"
        assert len(n1) < 80

    def test_filename_sanitizes_illegal_chars(self):
        bad = {**ITEM_A, "title": "A/B:C*D?E<F>G|H"}
        fn = scholarly.paper_filename(bad, "s", 3)
        for ch in '/\\:*?"<>|':
            assert ch not in fn, f"文件名不应含 {ch}"

    def test_filename_dedupes_with_index(self):
        same = scholarly.paper_filename(ITEM_A, "s", 0)
        same2 = scholarly.paper_filename(ITEM_A, "s", 1)
        assert same != same2, "同标题不同条目须有不同文件名，避免互相覆盖"
