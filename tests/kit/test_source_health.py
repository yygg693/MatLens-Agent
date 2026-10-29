# -*- coding: utf-8 -*-
"""源健康自检测试（matlens_kit.rag.source_health）。

全部离线：不发起真实网络请求（真实链路手工实测 + e2e 验证）。

重点守护：
  - **need_key 与 down 必须分开**：没配密钥不是源坏了，是用户还没配置。
    混为一谈会让用户以为源方挂了。
  - **失败原因要分类**：配额耗尽 / 超时 / DNS / 需密钥的处置完全不同，
    只说「不可用」等于没说。
  - **缓存必须有**：自检是网络操作，每次开页面都探会拖慢首屏、
    白耗免费 API 配额。
  - **免重试模式**：重试会把超时翻倍（5s → 10.8s），自检要快速反馈。
"""
from __future__ import annotations

import sys

import pytest

sys.path.insert(0, r"D:\MatLens")
from matlens_kit.rag import source_health as sh  # noqa: E402


class TestClassifyError:
    def test_quota(self):
        assert "配额" in sh._classify_error("HTTP Error 429: Too Many Requests")

    def test_auth(self):
        assert "密钥" in sh._classify_error("HTTP Error 401: Unauthorized")

    def test_timeout(self):
        assert "超时" in sh._classify_error("urlopen error: timed out")

    def test_dns(self):
        assert "解析" in sh._classify_error(
            "<urlopen error [Errno 11001] getaddrinfo failed>")

    def test_tls(self):
        assert "TLS" in sh._classify_error("SSL: CERTIFICATE_VERIFY_FAILED")

    def test_robots(self):
        assert "robots" in sh._classify_error("robots.txt 明确禁止抓取该路径")

    def test_connection(self):
        assert "拒绝" in sh._classify_error("Connection refused")

    def test_unknown(self):
        assert "未知" in sh._classify_error("some weird error")


class TestSummarize:
    def test_counts_by_status(self):
        items = {
            "a": {"status": "ok"}, "b": {"status": "ok"},
            "c": {"status": "down"}, "d": {"status": "need_key"},
        }
        s = sh._summarize(items)
        assert s["total"] == 4
        assert s["ok"] == 2 and s["down"] == 1 and s["need_key"] == 1

    def test_empty(self):
        s = sh._summarize({})
        assert s["total"] == 0 and s["ok"] == 0


class TestProbeOne:
    def test_ok_when_results_returned(self, monkeypatch):
        monkeypatch.setattr("matlens_kit.rag.scholarly.check_source",
                            lambda sid, timeout=8.0: {"ok": True, "n": 1, "ms": 100})
        r = sh._probe_one("openalex")
        assert r["status"] == sh.OK
        assert r["n"] == 1

    def test_degraded_when_no_hit(self, monkeypatch):
        """连通但探测词无命中 → degraded，不是 ok 也不是 down。

        这是重要区分：源是通的，只是这次没搜到。
        """
        monkeypatch.setattr("matlens_kit.rag.scholarly.check_source",
                            lambda sid, timeout=8.0: {"ok": True, "n": 0, "ms": 50})
        r = sh._probe_one("openalex")
        assert r["status"] == sh.DEGRADED
        assert "无命中" in r["error"]

    def test_down_with_reason(self, monkeypatch):
        monkeypatch.setattr("matlens_kit.rag.scholarly.check_source",
                            lambda sid, timeout=8.0: {"ok": False, "error": "HTTP Error 429"})
        r = sh._probe_one("semantic_scholar")
        assert r["status"] == sh.DOWN
        assert "429" in r["error"]
        assert "配额" in r["hint"], "失败原因要分类，不能只说不可用"

    def test_exception_contained(self, monkeypatch):
        def boom(sid, timeout=8.0):
            raise RuntimeError("net down")
        monkeypatch.setattr("matlens_kit.rag.scholarly.check_source", boom)
        r = sh._probe_one("openalex")
        assert r["status"] == sh.DOWN
        assert "RuntimeError" in r["error"]

    def test_need_key_not_probed(self, monkeypatch):
        """需密钥且未配置 → 直接报 need_key，不该发网络请求。"""
        called = []

        def spy(sid, timeout=8.0):
            called.append(sid)
            return {"ok": True, "n": 1}

        monkeypatch.setattr("matlens_kit.rag.scholarly.check_source", spy)
        monkeypatch.setattr(sh, "_has_key", lambda sid: False)
        monkeypatch.setattr(sh, "_catalog_entry",
                            lambda sid: {"label": "万方数据", "key_required": True,
                                         "key_env": "WANFANG_KEY"})
        r = sh._probe_one("wanfang")
        assert r["status"] == sh.NEED_KEY
        assert not called, "未配置密钥时不该探测"


class TestCache:
    def test_cache_miss_then_hit(self, monkeypatch):
        calls = []

        def fake(*a, **k):
            calls.append(1)
            return {"ok": True, "n": 1, "ms": 10}

        monkeypatch.setattr("matlens_kit.rag.scholarly.check_source", fake)
        monkeypatch.setattr(sh, "_catalog_entry",
                            lambda sid: {"label": sid, "key_required": False})
        monkeypatch.setattr(sh, "_has_key", lambda sid: True)
        monkeypatch.setattr(sh, "include_datasets", False, raising=False)

        sh.invalidate()
        # 探测两个源（catalog 是列表，这里直接替换）
        monkeypatch.setattr("matlens_kit.rag.scholarly.get_catalog",
                            lambda: [{"id": "openalex", "label": "OpenAlex"},
                                     {"id": "crossref", "label": "Crossref"}])
        r1 = sh.check_all(force=True)
        n1 = len(calls)
        assert r1["cached"] is False

        r2 = sh.check_all()
        assert r2["cached"] is True
        assert len(calls) == n1, "命中缓存时不应再发网络请求"

    def test_force_bypasses_cache(self, monkeypatch):
        calls = []

        def fake(*a, **k):
            calls.append(1)
            return {"ok": True, "n": 1, "ms": 10}

        monkeypatch.setattr("matlens_kit.rag.scholarly.check_source", fake)
        monkeypatch.setattr(sh, "_catalog_entry",
                            lambda sid: {"label": sid, "key_required": False})
        monkeypatch.setattr(sh, "_has_key", lambda sid: True)
        monkeypatch.setattr("matlens_kit.rag.scholarly.get_catalog",
                            lambda: [{"id": "openalex", "label": "OpenAlex"}])

        sh.invalidate()
        sh.check_all(force=True)
        n1 = len(calls)
        sh.check_all(force=True)
        assert len(calls) > n1, "force=True 必须重新探测"

    def test_invalidate_clears(self):
        sh.invalidate()
        c = sh.get_cached()
        assert c["fresh"] is False
        assert not c["items"]


class TestProbeMode:
    def test_probe_mode_disables_retries(self):
        """自检要快速反馈：重试会把 5s 超时翻倍成 10.8s。"""
        from matlens_kit.rag import scholarly

        scholarly._set_probe_mode(True)
        try:
            assert scholarly._PROBE_MODE is True
        finally:
            scholarly._set_probe_mode(False)
        assert scholarly._PROBE_MODE is False

    def test_datasets_probe_mode_exists(self):
        from matlens_kit.rag import datasets

        datasets._set_probe_mode(True)
        try:
            assert datasets._PROBE_MODE is True
        finally:
            datasets._set_probe_mode(False)
        assert datasets._PROBE_MODE is False


class TestStatusConstants:
    def test_all_five_statuses_defined(self):
        assert sh.OK == "ok"
        assert sh.DEGRADED == "degraded"
        assert sh.DOWN == "down"
        assert sh.NEED_KEY == "need_key"
        assert sh.OFF == "off"

    def test_cache_ttl_reasonable(self):
        """10 分钟：覆盖一次使用会话，又不至于让修好的状态迟迟不刷新。"""
        assert 60 <= sh.CACHE_TTL <= 1800

    def test_timeout_cap_below_default(self):
        """硬上限必须比默认超时短，否则慢源会把自检拖到几十秒。"""
        assert sh.SOURCE_TIMEOUT_CAP < sh.PROBE_TIMEOUT
