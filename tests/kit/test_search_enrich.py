# -*- coding: utf-8 -*-
"""论文检索正文补全测试（matlens_kit.paper.search_enrich）。

**全部离线**：不发起真实网络请求（真实链路由手工实测 + e2e 验证）。

核心守护点：
  - 抓不到正文时**绝不用题录拼假正文** —— 那是引用污染的源头
  - render_fulltext_notes 只输出有正文的条目
  - 单条失败不影响整批
"""
from __future__ import annotations

import sys

import pytest

sys.path.insert(0, r"D:\MatLens")
from matlens_kit.paper import search_enrich as se  # noqa: E402

REF = {
    "index": 1,
    "title": "Ceria co-doping: Synergistic or average effect?",
    "doi": "10.1039/C4CP00856A",
    "authors": "Burbano et al.",
    "year": "2014",
    "url": "https://doi.org/10.1039/C4CP00856A",
}

OK_FETCH = {
    "ok": True, "status": 200, "text": "x" * 1200, "text_chars": 1200,
    "engine": "trafilatura", "doi": "10.1039/C4CP00856A",
}
FAIL_FETCH = {
    "ok": False, "reason": "robots.txt 明确禁止抓取该路径（已遵守）",
    "oa_fallback_error": "该文献没有合法开放获取版本",
}


@pytest.fixture(autouse=True)
def _no_local_kb(monkeypatch):
    """默认不查本地库，让测试聚焦网络分支。"""
    monkeypatch.setattr(se, "_kb_snippet_for", lambda ref: "")


class TestCandidates:
    def test_orders_oa_first(self):
        c = se._candidates({"url": "https://x/landing", "oa_url": "https://x/oa.pdf"})
        assert c[0] == "https://x/oa.pdf"

    def test_dedup(self):
        c = se._candidates({"url": "https://x/a", "oa_url": "https://x/a"})
        assert c == ["https://x/a"]

    def test_skips_non_http(self):
        assert se._candidates({"url": "javascript:alert(1)"}) == []

    def test_respects_limit(self):
        ref = {k: f"https://x/{k}" for k in ("url", "oa_url", "pdf_url", "landing_page_url")}
        assert len(se._candidates(ref)) <= se.MAX_CANDIDATES


class TestFetchFulltext:
    def test_success_marks_source(self, monkeypatch):
        monkeypatch.setattr("matlens_kit.web.web_fetcher.fetch",
                            lambda *a, **k: dict(OK_FETCH))
        r = se.fetch_fulltext(dict(REF))
        assert r["text"].startswith("xxx")
        assert r["text_source"] == "web"

    def test_local_kb_takes_priority(self, monkeypatch):
        monkeypatch.setattr(se, "_kb_snippet_for", lambda ref: "本地库正文片段")
        called = []
        monkeypatch.setattr("matlens_kit.web.web_fetcher.fetch",
                            lambda *a, **k: called.append(1))
        r = se.fetch_fulltext(dict(REF))
        assert r["text"] == "本地库正文片段"
        assert r["text_source"] == "local-kb"
        assert not called, "本地命中时不该再走网络抓取"

    def test_oa_fallback_source_labeled(self, monkeypatch):
        r = dict(OK_FETCH)
        r["resolved_via"] = "Unpaywall OA 版本"
        r["is_pdf"] = True
        monkeypatch.setattr("matlens_kit.web.web_fetcher.fetch", lambda *a, **k: r)
        out = se.fetch_fulltext(dict(REF))
        assert out["text_source"] == "oa-fallback"
        assert out["resolved_via"] == "Unpaywall OA 版本"

    def test_too_short_treated_as_failure(self, monkeypatch):
        """正文过短通常意味着页面未渲染（JS），不能当正文用。"""
        monkeypatch.setattr("matlens_kit.web.web_fetcher.fetch",
                            lambda *a, **k: {"ok": True, "text": "太短了"})
        out = se.fetch_fulltext(dict(REF))
        assert out["text"] == ""
        assert any("正文过短" in n for n in out["fetch_notes"])

    def test_failure_reason_recorded(self, monkeypatch):
        monkeypatch.setattr("matlens_kit.web.web_fetcher.fetch",
                            lambda *a, **k: dict(FAIL_FETCH))
        out = se.fetch_fulltext(dict(REF))
        assert out["text"] == "", "失败时不得留下假正文"
        notes = " ".join(out.get("fetch_notes") or [])
        assert "robots" in notes or "合法开放获取" in notes

    def test_exception_contained(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("net down")
        monkeypatch.setattr("matlens_kit.web.web_fetcher.fetch", boom)
        out = se.fetch_fulltext(dict(REF))     # 不应抛
        assert out["text"] == ""

    def test_no_doi_no_link_explains(self, monkeypatch):
        monkeypatch.setattr("matlens_kit.web.web_fetcher.fetch",
                            lambda *a, **k: dict(FAIL_FETCH))
        out = se.fetch_fulltext({"title": "X", "doi": ""})
        assert any("无 DOI" in n for n in out.get("fetch_notes") or [])


class TestEnrichRefs:
    def test_accepts_search_web_wrapper(self, monkeypatch):
        """search_web() 返回 {"items": [...]}，必须能直接传进来。"""
        monkeypatch.setattr("matlens_kit.web.web_fetcher.fetch",
                            lambda *a, **k: dict(OK_FETCH))
        r = se.enrich_refs({"items": [dict(REF), dict(REF, doi="10.1/y")]}, max_refs=2)
        assert r["with_text"] == 2
        assert len(r["refs"]) == 2

    def test_accepts_plain_list(self, monkeypatch):
        monkeypatch.setattr("matlens_kit.web.web_fetcher.fetch",
                            lambda *a, **k: dict(OK_FETCH))
        r = se.enrich_refs([dict(REF)], max_refs=1)
        assert r["with_text"] == 1

    def test_counts_are_honest(self, monkeypatch):
        monkeypatch.setattr("matlens_kit.web.web_fetcher.fetch",
                            lambda *a, **k: dict(FAIL_FETCH))
        r = se.enrich_refs([dict(REF), dict(REF, doi="10.1/b")], max_refs=2)
        assert r["with_text"] == 0
        assert r["without_text"] == 2

    def test_max_refs_limits_fetching(self, monkeypatch):
        calls = []
        monkeypatch.setattr("matlens_kit.web.web_fetcher.fetch",
                            lambda *a, **k: calls.append(1) or dict(OK_FETCH))
        refs = [dict(REF, doi=f"10.1/{i}") for i in range(10)]
        r = se.enrich_refs(refs, max_refs=3)
        assert len(calls) == 3, "只应抓前 max_refs 条"
        assert len(r["refs"]) == 10, "其余条目原样保留"

    def test_empty_input(self):
        r = se.enrich_refs([])
        assert r["with_text"] == 0 and r["refs"] == []

    def test_index_renumbered(self, monkeypatch):
        monkeypatch.setattr("matlens_kit.web.web_fetcher.fetch",
                            lambda *a, **k: dict(OK_FETCH))
        refs = [dict(REF, doi="10.1/a"), dict(REF, doi="10.1/b")]
        r = se.enrich_refs(refs, max_refs=2)
        assert [x["index"] for x in r["refs"]] == [1, 2]

    def test_notes_tell_user_truth(self, monkeypatch):
        monkeypatch.setattr("matlens_kit.web.web_fetcher.fetch",
                            lambda *a, **k: dict(FAIL_FETCH))
        r = se.enrich_refs([dict(REF)], max_refs=1)
        joined = " ".join(r["notes"])
        assert "0/1" in joined or "仅可作背景提及" in joined


class TestRenderFulltextNotes:
    def test_only_includes_with_text(self, monkeypatch):
        """⚠️ 关键：没有正文的条目绝不能进 prompt，否则诱导模型编造。"""
        refs = [
            {"index": 1, "title": "有正文", "text": "REAL CONTENT HERE", "doi": "10.1/a"},
            {"index": 2, "title": "只有题录", "text": "", "doi": "10.1/b"},
        ]
        out = se.render_fulltext_notes(refs)
        assert "有正文" in out and "REAL CONTENT HERE" in out
        assert "只有题录" not in out, "无正文条目不得出现在 prompt 里"

    def test_empty_when_nothing_fetched(self):
        assert se.render_fulltext_notes([{"index": 1, "title": "x", "text": ""}]) == ""

    def test_truncates_long_text(self):
        refs = [{"index": 1, "title": "T", "text": "y" * 9000}]
        out = se.render_fulltext_notes(refs, chars_each=500)
        assert "已截断" in out
        assert len(out) < 3000

    def test_includes_doi_for_verification(self):
        out = se.render_fulltext_notes([{"index": 1, "title": "T",
                                        "text": "c", "doi": "10.1/xyz"}])
        assert "10.1/xyz" in out

    def test_respects_limit(self):
        refs = [{"index": i, "title": f"T{i}", "text": "content"} for i in range(10)]
        out = se.render_fulltext_notes(refs, limit=2)
        assert "T0" in out and "T1" in out and "T2" not in out