# -*- coding: utf-8 -*-
"""数据集源测试（matlens_kit.rag.datasets）。

全部离线，不发起真实网络请求（真实链路手工实测 + e2e 验证）。

重点守护：
  - **只保留有实际文件的记录**：Zenodo 的 type=dataset 里混着「无文件的论文
    补充材料记录」（DOI 是出版商的、files=[]），留着会挤占结果且用户拿不到数据。
  - 许可证必须透出（材料数据集要能判断能否自由引用）
  - HTML 实体要解干净（描述里有 &aring; 这类命名实体，漏解会进 prompt）
"""
from __future__ import annotations

import sys

import pytest

sys.path.insert(0, r"D:\MatLens")
from matlens_kit.rag import datasets as ds  # noqa: E402


class TestStripHtml:
    def test_tags_removed(self):
        assert ds._strip_html("<p>hello</p>") == "hello"

    def test_named_entities_decoded(self):
        """Zenodo 描述里常见 &aring; —— 必须解成 å。"""
        out = ds._strip_html("<p>Lule&aring; demosite</p>")
        assert "&aring;" not in out
        assert "å" in out

    def test_numeric_entities(self):
        assert "°" in ds._strip_html("25&deg;C")

    def test_ampersand_not_double_unescaped(self):
        """&amp;lt; 应解成 &lt;（一层），不是 <。"""
        out = ds._strip_html("a &amp;lt; b")
        assert "&lt;" in out

    def test_line_breaks_preserved(self):
        out = ds._strip_html("line1<br/>line2")
        assert "line1" in out and "line2" in out

    def test_empty(self):
        assert ds._strip_html("") == ""


class TestFmtSize:
    def test_bytes(self):
        assert ds._fmt_size(512) == "512 B"

    def test_mb(self):
        assert "MB" in ds._fmt_size(5 * 1024 * 1024)

    def test_gb(self):
        assert "GB" in ds._fmt_size(4 * 1024 ** 3)

    def test_invalid(self):
        assert ds._fmt_size(None) == ""


class TestSourceIndex:
    def test_zenodo_default_on(self):
        assert ds.DATASET_SOURCE_INDEX["zenodo"]["default_on"] is True
        assert ds.DATASET_SOURCE_INDEX["zenodo"]["needs_key"] is False

    def test_huggingface_default_off(self):
        """实测国内直连超时（WinError 10060），故默认不勾选。"""
        assert ds.DATASET_SOURCE_INDEX["huggingface"]["default_on"] is False

    def test_defaults_only_zenodo(self):
        assert ds.DEFAULT_DATASET_SOURCES == ["zenodo"]

    def test_no_source_needs_key(self):
        """Zenodo / HuggingFace 都有公开 API，不需要任何 key。"""
        assert all(not v["needs_key"] for v in ds.DATASET_SOURCE_INDEX.values())


class TestSearchDatasets:
    def test_empty_query_reports_error(self):
        r = ds.search_datasets("", sources=["zenodo"])
        assert r["ok"] is False
        assert r["count"] == 0

    def test_unknown_source_filtered(self):
        r = ds.search_datasets("x", sources=["not_a_source"])
        assert r["ok"] is False
        assert "没有可用的数据集源" in r.get("error", "")

    def test_source_failure_is_contained(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("net down")
        monkeypatch.setitem(ds.DATASET_SEARCHERS, "zenodo", boom)
        r = ds.search_datasets("x", sources=["zenodo"])
        assert r["ok"] is False
        assert r["per_source"]["zenodo"]["ok"] is False
        assert "RuntimeError" in r["per_source"]["zenodo"]["error"]

    def test_dedup_by_doi(self, monkeypatch):
        item = {"doi": "10.1/x", "title": "T"}
        monkeypatch.setitem(ds.DATASET_SEARCHERS, "zenodo",
                            lambda *a, **k: [dict(item), dict(item)])
        r = ds.search_datasets("x", sources=["zenodo"])
        assert r["count"] == 1, "同 DOI 只应保留一条"

    def test_result_shape(self, monkeypatch):
        monkeypatch.setitem(ds.DATASET_SEARCHERS, "zenodo",
                            lambda *a, **k: [{"doi": "10.1/x", "title": "T"}])
        r = ds.search_datasets("x", sources=["zenodo"])
        assert r["kind"] == "dataset"
        assert r["elapsed_ms"] >= 0
        assert "per_source" in r


class TestZenodoParsing:
    """用真实 Zenodo 响应结构做解析测试（不联网）。"""

    SAMPLE = {
        "id": 12345,
        "doi": "10.5281/zenodo.12345",
        "conceptdoi": "10.5281/zenodo.12345",
        "revision": "2",
        "links": {"self": "https://zenodo.org/api/records/12345",
                  "html": "https://zenodo.org/records/12345"},
        "files": [
            {"key": "data.zip", "size": 1048576, "type": "application/zip",
             "links": {"self": "https://zenodo.org/api/records/12345/files/data.zip/content"}},
            {"key": "readme.txt", "size": 512, "type": "text/plain",
             "links": {"self": "https://zenodo.org/api/records/12345/files/readme.txt/content"}},
        ],
        "metadata": {
            "title": "A dataset of SOFC electrode microstructure",
            "publication_date": "2024-03-15",
            "description": "<p>Microstructure data for <b>nickel</b> particles.</p>",
            "creators": [{"name": "Zhang, Wei"}, {"name": "Li, Ming"}],
            "keywords": ["SOFC", "microstructure"],
            "license": {"id": "cc-by-4.0"},
            "resource_type": {"title": "Dataset", "type": "dataset", "subtype": None},
        },
    }

    def _run_one(self, monkeypatch, payload):
        monkeypatch.setattr(ds, "_get_json", lambda *a, **k: payload)
        return ds.search_zenodo("x", limit=1)

    def test_core_fields(self, monkeypatch):
        r = self._run_one(monkeypatch, {"hits": {"hits": [self.SAMPLE]}})
        assert len(r) == 1
        it = r[0]
        assert it["title"].startswith("A dataset of SOFC")
        assert it["doi"] == "10.5281/zenodo.12345"
        assert it["source"] == "Zenodo"
        assert it["kind"] == "dataset"
        assert it["year"] == "2024"

    def test_license_exposed(self, monkeypatch):
        """材料数据集要能判断能否自由引用，许可证必须透出。"""
        r = self._run_one(monkeypatch, {"hits": {"hits": [self.SAMPLE]}})
        assert r[0]["license"] == "cc-by-4.0"

    def test_files_with_size(self, monkeypatch):
        r = self._run_one(monkeypatch, {"hits": {"hits": [self.SAMPLE]}})
        it = r[0]
        assert it["file_count"] == 2
        assert it["total_size"] == 1048576 + 512
        assert "MB" in it["total_size_human"]
        assert it["files"][0]["key"] == "data.zip"
        assert it["files"][0]["url"].startswith("https://")

    def test_description_html_stripped(self, monkeypatch):
        r = self._run_one(monkeypatch, {"hits": {"hits": [self.SAMPLE]}})
        d = r[0]["description"]
        assert "<p>" not in d and "<b>" not in d
        assert "nickel" in d

    def test_authors_joined(self, monkeypatch):
        r = self._run_one(monkeypatch, {"hits": {"hits": [self.SAMPLE]}})
        assert "Zhang, Wei" in r[0]["authors"]

    def test_records_without_files_are_dropped(self, monkeypatch):
        """⚠️ Zenodo 的 type=dataset 里混着无文件的论文补充材料记录，
        留着会挤占结果且用户拿不到任何数据。"""
        s = dict(self.SAMPLE)
        s["files"] = []
        r = self._run_one(monkeypatch, {"hits": {"hits": [s]}})
        assert r == [], "无文件的记录应被过滤"

    def test_paper_doi_record_dropped(self, monkeypatch):
        """DOI 是出版商的 10.1002/xxx 且无文件 → 论文补充材料，应过滤。"""
        s = dict(self.SAMPLE)
        s["files"] = []
        s["doi"] = "10.1002/cssc.201600813"
        r = self._run_one(monkeypatch, {"hits": {"hits": [s]}})
        assert r == []

    def test_keyword_split(self, monkeypatch):
        r = self._run_one(monkeypatch, {"hits": {"hits": [self.SAMPLE]}})
        assert r[0]["keywords"] == ["SOFC", "microstructure"]

    def test_missing_title_skipped(self, monkeypatch):
        s = dict(self.SAMPLE)
        s["metadata"] = dict(s["metadata"])
        s["metadata"]["title"] = ""
        r = self._run_one(monkeypatch, {"hits": {"hits": [s]}})
        assert r == []


class TestFetchRecordFiles:
    def test_returns_file_list(self, monkeypatch):
        payload = {
            "id": 1, "doi": "10.5281/zenodo.1",
            "metadata": {"title": "T", "license": {"id": "cc-by-4.0"},
                         "description": "<p>d</p>"},
            "files": [{"key": "a.zip", "size": 100,
                       "links": {"self": "https://x/a.zip"}}],
        }
        monkeypatch.setattr(ds, "_get_json", lambda *a, **k: payload)
        r = ds.fetch_record_files("1")
        assert r["ok"] is True
        assert r["file_count"] == 1
        assert r["total_size"] == 100
        assert r["license"] == "cc-by-4.0"
        assert "<p>" not in r["description"]