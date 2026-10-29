# -*- coding: utf-8 -*-
"""抓取缓存统计测试（matlens_kit.web.cache_stats）。

重点守护：
  - **不泄露访问痕迹**：统计只取 host 维度，**绝不暴露完整 URL** ——
    缓存文件里存的是脱敏 URL（去 query / 去 userinfo），
    统计接口若把完整 URL 吐出来，正好抵消了脱敏的意义。
  - **清理只删缓存文件**，不碰知识库与已导入文档。
  - **命中率口径要说清**：磁盘可用率与运行时命中率是两个不同含义。
"""
from __future__ import annotations

import json
import os
import sys
import time

import pytest

sys.path.insert(0, r"D:\MatLens")
from matlens_kit.web import cache_stats as cs  # noqa: E402


@pytest.fixture()
def cache_home(tmp_path, monkeypatch):
    """把缓存目录指到临时目录。"""
    home = tmp_path / "matlens_home"
    (home / "fetch_cache").mkdir(parents=True)
    monkeypatch.setattr("matlens_cli.config.get_matlens_home", lambda: home)
    return home / "fetch_cache"


def _write_cache(cache_dir, name, url, age_h=0.0):
    p = cache_dir / name
    p.write_text(json.dumps({"url": url, "text": "x" * 100}, ensure_ascii=False),
                 encoding="utf-8")
    if age_h:
        t = time.time() - age_h * 3600
        os.utime(p, (t, t))
    return p


class TestScan:
    def test_empty_dir(self, cache_home):
        s = cs._scan()
        assert s["total"] == 0
        assert s["fresh"] == 0 and s["stale"] == 0
        assert s["size_human"] == "0 B"

    def test_counts_fresh_and_stale(self, cache_home):
        _write_cache(cache_home, "a.json", "https://a.com/x", age_h=1)
        _write_cache(cache_home, "b.json", "https://b.com/y", age_h=48)
        s = cs._scan(ttl_h=24)
        assert s["total"] == 2
        assert s["fresh"] == 1
        assert s["stale"] == 1

    def test_size_accounted(self, cache_home):
        _write_cache(cache_home, "a.json", "https://a.com/x")
        s = cs._scan()
        assert s["size_bytes"] > 0
        assert "B" in s["size_human"]

    def test_broken_file_counted(self, cache_home):
        (cache_home / "broken.json").write_text("{not json", encoding="utf-8")
        s = cs._scan()
        assert s["total"] == 1
        assert s["broken"] == 1

    def test_non_json_ignored(self, cache_home):
        (cache_home / "readme.txt").write_text("hello", encoding="utf-8")
        assert cs._scan()["total"] == 0


class TestPrivacy:
    def test_response_has_no_full_url_with_query(self, cache_home):
        """⚠️ 关键：响应里不能出现带 query 的完整 URL。"""
        secret = "https://publisher.com/article?id=12345&token=SECRET"
        _write_cache(cache_home, "a.json", secret)
        s = cs._scan()
        blob = json.dumps(s, ensure_ascii=False)
        assert "SECRET" not in blob
        assert "id=12345" not in blob
        assert "token=" not in blob

    def test_only_host_reported(self, cache_home):
        _write_cache(cache_home, "a.json", "https://publisher.com/a/b/c?x=1")
        s = cs._scan()
        hosts = [h["host"] for h in s["hosts"]]
        assert "publisher.com" in hosts
        assert not any("/" in h for h in hosts)

    def test_stats_note_states_privacy(self, cache_home):
        assert "脱敏" in cs.stats()["note"]


class TestRuntimeCounters:
    def test_hit_miss_tracked(self):
        cs._runtime.update({"hit": 0, "miss": 0, "store": 0})
        cs.record_hit()
        cs.record_miss()
        cs.record_miss()
        s = cs.stats()
        assert s["runtime"]["hit"] == 1
        assert s["runtime"]["miss"] == 2
        assert s["runtime"]["requests"] == 3
        assert s["runtime"]["hit_rate"] == pytest.approx(1 / 3, abs=0.01)

    def test_hit_rate_none_when_no_requests(self):
        cs._runtime.update({"hit": 0, "miss": 0, "store": 0})
        assert cs.stats()["runtime"]["hit_rate"] is None

    def test_usable_rate_distinct_from_hit_rate(self, cache_home):
        """两个口径含义不同：磁盘可用率 vs 运行时命中率。"""
        _write_cache(cache_home, "a.json", "https://a.com/x", age_h=1)
        _write_cache(cache_home, "b.json", "https://b.com/y", age_h=48)
        s = cs.stats(ttl_h=24)
        assert s["usable_rate"] == 0.5
        assert "hit_rate" in s["runtime"]


class TestPurge:
    def test_removes_only_stale_by_default(self, cache_home):
        _write_cache(cache_home, "fresh.json", "https://a.com/x", age_h=1)
        _write_cache(cache_home, "stale.json", "https://b.com/y", age_h=48)
        r = cs.purge(stale_only=True, ttl_h=24)
        assert r["removed"] == 1
        assert (cache_home / "fresh.json").exists()
        assert not (cache_home / "stale.json").exists()

    def test_removes_all_when_asked(self, cache_home):
        _write_cache(cache_home, "a.json", "https://a.com/x", age_h=1)
        _write_cache(cache_home, "b.json", "https://b.com/y", age_h=1)
        r = cs.purge(stale_only=False)
        assert r["removed"] == 2
        assert cs._scan()["total"] == 0

    def test_reports_freed_bytes(self, cache_home):
        _write_cache(cache_home, "a.json", "https://a.com/x", age_h=48)
        r = cs.purge(stale_only=True, ttl_h=24)
        assert r["freed_bytes"] > 0
        assert r["freed_human"]

    def test_does_not_touch_other_files(self, cache_home):
        """只删 .json 缓存文件，其它不动。"""
        other = cache_home / "keep.txt"
        other.write_text("keep", encoding="utf-8")
        _write_cache(cache_home, "a.json", "https://a.com/x", age_h=48)
        cs.purge(stale_only=False)
        assert other.exists(), "非缓存文件不应被删"

    def test_empty_dir_purge(self, cache_home):
        r = cs.purge()
        assert r["ok"] is True and r["removed"] == 0


class TestFormatSize:
    def test_bytes(self):
        assert cs._fmt_size(512) == "512 B"

    def test_mb(self):
        assert "MB" in cs._fmt_size(5 * 1024 * 1024)

    def test_invalid(self):
        assert cs._fmt_size(None) == "0 B"
