# -*- coding: utf-8 -*-
"""OA 全文解析链测试（Unpaywall 多候选 + Europe PMC 兜底）。

全部离线，不发起真实网络请求。

重点守护：
  - **必须遍历全部 OA 候选**：Unpaywall 的 best 位置常指向出版商域名
    （robots 禁止抓），同记录里往往还有 repository 镜像可抓。
  - **robots 不绕过**：出版商/PMC 的 robots 禁止就是不能抓，
    正确解法是转向**正规 API**（Europe PMC），不是换镜像硬来。
  - **如实报告失败**：没有 OA 版就说明白，不能编造正文。
"""
from __future__ import annotations

import sys

import pytest

sys.path.insert(0, r"D:\MatLens")
from matlens_kit.rag import scholarly  # noqa: E402


class TestUnpaywallEmailFallback:
    """服务进程通常没有 UNPAYWALL_EMAIL 环境变量（用户只写在 .env 里）。"""

    def test_reads_from_dotenv(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text('DEEPSEEK_API_KEY=sk-x\nUNPAYWALL_EMAIL=me@example.com\n',
                       encoding="utf-8")
        monkeypatch.setattr("matlens_cli.config.get_matlens_home", lambda: tmp_path)
        monkeypatch.delenv("UNPAYWALL_EMAIL", raising=False)
        assert scholarly._read_unpaywall_email_from_dotenv() == "me@example.com"

    def test_handles_export_prefix(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text("export UNPAYWALL_EMAIL=me@example.com\n", encoding="utf-8")
        monkeypatch.setattr("matlens_cli.config.get_matlens_home", lambda: tmp_path)
        monkeypatch.delenv("UNPAYWALL_EMAIL", raising=False)
        assert scholarly._read_unpaywall_email_from_dotenv() == "me@example.com"

    def test_strips_quotes(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text('UNPAYWALL_EMAIL="me@example.com"\n', encoding="utf-8")
        monkeypatch.setattr("matlens_cli.config.get_matlens_home", lambda: tmp_path)
        monkeypatch.delenv("UNPAYWALL_EMAIL", raising=False)
        assert scholarly._read_unpaywall_email_from_dotenv() == "me@example.com"

    def test_skips_comments(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text("# UNPAYWALL_EMAIL=commented@x.com\nOTHER=1\n", encoding="utf-8")
        monkeypatch.setattr("matlens_cli.config.get_matlens_home", lambda: tmp_path)
        monkeypatch.delenv("UNPAYWALL_EMAIL", raising=False)
        assert scholarly._read_unpaywall_email_from_dotenv() == ""

    def test_missing_file_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("matlens_cli.config.get_matlens_home", lambda: tmp_path)
        monkeypatch.delenv("UNPAYWALL_EMAIL", raising=False)
        assert scholarly._read_unpaywall_email_from_dotenv() == ""

    def test_does_not_mutate_environ(self, tmp_path, monkeypatch):
        """只读一次，不该改进程环境 —— 否则会产生「导入即副作用」。"""
        env = tmp_path / ".env"
        env.write_text("UNPAYWALL_EMAIL=me@example.com\n", encoding="utf-8")
        monkeypatch.setattr("matlens_cli.config.get_matlens_home", lambda: tmp_path)
        monkeypatch.delenv("UNPAYWALL_EMAIL", raising=False)
        scholarly._read_unpaywall_email_from_dotenv()
        assert "UNPAYWALL_EMAIL" not in __import__("os").environ


class TestFetchUnpaywall:
    def test_requires_doi(self):
        with pytest.raises(ValueError):
            scholarly.fetch_unpaywall("not-a-doi")

    def test_missing_email_raises_actionable_error(self, monkeypatch):
        """报错必须告诉用户**怎么修**，不能只说「未配置」。"""
        monkeypatch.delenv("UNPAYWALL_EMAIL", raising=False)
        monkeypatch.setattr(scholarly, "_read_unpaywall_email_from_dotenv", lambda: "")
        with pytest.raises(RuntimeError) as e:
            scholarly.fetch_unpaywall("10.1039/C4CP00856A")
        msg = str(e.value)
        assert "UNPAYWALL_EMAIL" in msg
        assert ".env" in msg, "要说明去哪里配"

    def test_returns_all_alternatives(self, monkeypatch):
        """⚠️ 必须返回**全部**候选位置，不能只给 best。

        实测 10.3390/membranes12090896：best 是 mdpi.com（robots 禁止），
        但同记录里还有 ncbi PMC / doaj —— 只用 best 会误判「没有 OA 全文」。
        """
        monkeypatch.setenv("UNPAYWALL_EMAIL", "me@example.com")
        payload = {
            "doi": "10.3390/x",
            "title": "T",
            "is_oa": True,
            "oa_status": "gold",
            "best_oa_location": {
                "url": "https://www.mdpi.com/a/pdf",
                "url_for_pdf": "https://www.mdpi.com/a/pdf",
                "host_type": "publisher",
                "license": "cc-by",
            },
            "oa_locations": [
                {"url": "https://www.mdpi.com/a/pdf", "host_type": "publisher"},
                {"url": "https://www.ncbi.nlm.nih.gov/pmc/articles/1",
                 "host_type": "repository"},
                {"url": "https://doaj.org/article/x", "host_type": "repository"},
            ],
        }
        monkeypatch.setattr(scholarly, "_get_json", lambda *a, **k: payload)
        r = scholarly.fetch_unpaywall("10.3390/x")
        urls = [a["url"] for a in r["alternatives"]]
        assert len(urls) == 3, f"应返回全部候选，实为 {urls}"
        assert "https://www.ncbi.nlm.nih.gov/pmc/articles/1" in urls

    def test_repository_sorted_before_publisher(self, monkeypatch):
        """repository 镜像优先 —— 出版商站点的 robots 限制更常见。"""
        monkeypatch.setenv("UNPAYWALL_EMAIL", "me@example.com")
        payload = {
            "doi": "10.1/x", "title": "T", "is_oa": True, "oa_status": "gold",
            "best_oa_location": {"url": "https://pub.com/a", "host_type": "publisher"},
            "oa_locations": [
                {"url": "https://pub.com/a", "host_type": "publisher"},
                {"url": "https://repo.org/a", "host_type": "repository"},
            ],
        }
        monkeypatch.setattr(scholarly, "_get_json", lambda *a, **k: payload)
        r = scholarly.fetch_unpaywall("10.1/x")
        alts = r["alternatives"]
        # best 仍在最前，但其余按 repository 优先
        rest = [a for a in alts if a["url"] != "https://pub.com/a"]
        assert rest and rest[0]["host_type"] == "repository"

    def test_deduplicates_urls(self, monkeypatch):
        monkeypatch.setenv("UNPAYWALL_EMAIL", "me@example.com")
        payload = {
            "doi": "10.1/x", "title": "T", "is_oa": True, "oa_status": "gold",
            "best_oa_location": {"url": "https://a.com/x", "host_type": "publisher"},
            "oa_locations": [
                {"url": "https://a.com/x", "host_type": "publisher"},
                {"url": "https://a.com/x", "host_type": "publisher"},
            ],
        }
        monkeypatch.setattr(scholarly, "_get_json", lambda *a, **k: payload)
        r = scholarly.fetch_unpaywall("10.1/x")
        urls = [a["url"] for a in r["alternatives"]]
        assert len(urls) == len(set(urls)), "候选 URL 应去重"


class TestXmlToText:
    def test_tags_removed(self):
        out = scholarly._xml_to_text("<p>hello</p>")
        assert "hello" in out and "<p>" not in out

    def test_title_becomes_heading(self):
        out = scholarly._xml_to_text("<title>Abstract</title><p>body</p>")
        assert "## Abstract" in out

    def test_paragraphs_separated(self):
        out = scholarly._xml_to_text("<p>one</p><p>two</p>")
        assert "one" in out and "two" in out

    def test_refs_stripped(self):
        """参考文献列表对写作无用且占大量篇幅，去掉。"""
        out = scholarly._xml_to_text("<p>keep</p><ref-list><ref>drop</ref></ref-list>")
        assert "keep" in out and "drop" not in out

    def test_entities_decoded(self):
        out = scholarly._xml_to_text("<p>a &amp; b &lt;c&gt;</p>")
        assert "&" in out and "&lt;" not in out

    def test_empty(self):
        assert scholarly._xml_to_text("") == ""


class TestEuropePmcFulltext:
    def test_not_indexed(self, monkeypatch):
        monkeypatch.setattr(scholarly, "_get_json", lambda *a, **k: {"resultList": {"result": []}})
        r = scholarly.fetch_europepmc_fulltext("10.1/x")
        assert r["ok"] is False
        assert "未收录" in r["error"]

    def test_no_pmcid(self, monkeypatch):
        payload = {"resultList": {"result": [{"doi": "10.1/x", "isOpenAccess": "Y"}]}}
        monkeypatch.setattr(scholarly, "_get_json", lambda *a, **k: payload)
        r = scholarly.fetch_europepmc_fulltext("10.1/x")
        assert r["ok"] is False and "PMCID" in r["error"]

    def test_not_open_access(self, monkeypatch):
        payload = {"resultList": {"result": [
            {"doi": "10.1/x", "pmcid": "PMC1", "isOpenAccess": "N"}]}}
        monkeypatch.setattr(scholarly, "_get_json", lambda *a, **k: payload)
        r = scholarly.fetch_europepmc_fulltext("10.1/x")
        assert r["ok"] is False and "开放获取" in r["error"]

    def test_success(self, monkeypatch):
        payload = {"resultList": {"result": [
            {"doi": "10.1/x", "pmcid": "PMC1", "isOpenAccess": "Y",
             "title": "T", "source": "MED", "pubYear": "2024",
             "authorString": "A"}]}}
        monkeypatch.setattr(scholarly, "_get_json", lambda *a, **k: payload)
        monkeypatch.setattr(scholarly, "_http_get",
                            lambda *a, **k: b"<p>" + b"x" * 500 + b"</p>")
        r = scholarly.fetch_europepmc_fulltext("10.1/x")
        assert r["ok"] is True
        assert r["pmcid"] == "PMC1"
        assert len(r["text"]) > 200
        assert r["via"] == "Europe PMC 官方 API"

    def test_too_short_rejected(self, monkeypatch):
        payload = {"resultList": {"result": [
            {"doi": "10.1/x", "pmcid": "PMC1", "isOpenAccess": "Y", "title": "T"}]}}
        monkeypatch.setattr(scholarly, "_get_json", lambda *a, **k: payload)
        monkeypatch.setattr(scholarly, "_http_get", lambda *a, **k: b"<p>tiny</p>")
        r = scholarly.fetch_europepmc_fulltext("10.1/x")
        assert r["ok"] is False
        assert "过短" in r["error"]

    def test_empty_doi(self):
        r = scholarly.fetch_europepmc_fulltext("")
        assert r["ok"] is False
