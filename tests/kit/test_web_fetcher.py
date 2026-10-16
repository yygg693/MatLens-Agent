# -*- coding: utf-8 -*-
"""网页抓取模块测试（matlens_kit.web.web_fetcher）。

**全部离线**：不发真实网络请求，用 monkeypatch 注入假响应。
真实链路（robots / 限速 / 抽取质量）由 _e2e_web_fetch.py 验证。

覆盖重点：
  - robots.txt 判定（这是合规底线，必须可靠）
  - 限速器（同域串行、跨域不阻塞）
  - 元数据抽取（学术 citation_* 标签）
  - 正文抽取（trafilatura 优先、内置降级）
  - 协议白名单（拒绝 javascript:/file:/ftp:）
  - PDF 处理与降级
  - 失败时给出可执行 hint 而不是让 Agent 死磕重试
"""
from __future__ import annotations

import sys
import time
import urllib.error

import pytest

sys.path.insert(0, r"D:\MatLens")
from matlens_kit.web import proxy_manager as pm  # noqa: E402
from matlens_kit.web import web_fetcher as wf  # noqa: E402
from matlens_kit.tools.web_tools import (  # noqa: E402
    _hint_for_failure, web_fetch_batch_tool, web_fetch_tool,
)

HTML_ARTICLE = """<!doctype html><html><head>
<title>Fallback title</title>
<meta name="citation_title" content="Ceria co-doping: Synergistic or average effect?">
<meta name="citation_doi" content="10.1039/C4CP00856A">
<meta name="citation_journal_title" content="Physical Chemistry Chemical Physics">
<meta name="citation_publication_date" content="2014/09/01">
<meta name="citation_volume" content="16">
<meta name="citation_issue" content="35">
<meta name="citation_firstpage" content="15214">
<meta name="citation_abstract" content="Ceria co-doping has been suggested as a means to improve ionic conductivity.">
<meta name="citation_pdf_url" content="https://arxiv.org/pdf/1404.3036">
<meta name="citation_author" content="Burbano, Mario">
<meta name="citation_author" content="Nadin, Sian">
<meta name="citation_author" content="Marrocchelli, Dario">
</head><body>
<nav>menu junk</nav>
<article><p>""" + ("Ionic conductivity is the key material property. " * 40) + """</p>
<p>This work studies Sm-doped ceria co-doping behaviour in solid oxide cells.</p></article>
<footer>footer junk</footer>
</body></html>"""


# ────────────────────────────────────────────────────────────
# robots.txt 合规（最关键）
# ────────────────────────────────────────────────────────────
class TestRobots:
    def test_rejects_non_http_schemes(self):
        for bad in ("ftp://x.org/a.pdf", "file:///etc/passwd"):
            ok, why = wf._robots_allows(bad)
            assert ok is False
            assert why

    def test_rejects_malformed(self):
        for bad in ("javascript:alert(1)", "data:text/html,x", "not a url", ""):
            ok, why = wf._robots_allows(bad)
            assert ok is False, f"{bad!r} 必须拒绝"

    def test_fetch_refuses_when_robots_disallows(self, monkeypatch):
        monkeypatch.setattr(wf, "_robots_allows", lambda u: (False, "robots.txt 明确禁止"))
        r = wf.fetch("https://blocked.example/paper")
        assert r["ok"] is False
        assert "robots" in r["reason"]
        assert "note_policy" in r, "被 robots 拒绝时必须说明这是遵守而非失败"

    def test_robots_cache_reused(self, monkeypatch):
        """robots.txt 只应查一次，避免每次抓取都额外请求。"""
        wf._ROBOTS.clear()
        calls = []

        class _RP:
            def set_url(self, u):
                calls.append(u)

            def read(self):
                pass

            def can_fetch(self, ua, url):
                return True

        monkeypatch.setattr(wf.urllib.robotparser, "RobotFileParser", _RP)
        wf._robots_allows("https://a.example/1")
        wf._robots_allows("https://a.example/2")
        wf._robots_allows("https://a.example/3")
        assert len(calls) == 1, f"robots 应缓存，实际请求 {len(calls)} 次"
        wf._ROBOTS.clear()


# ────────────────────────────────────────────────────────────
# 限速
# ────────────────────────────────────────────────────────────
class TestRateLimiter:
    def test_same_host_serialised(self):
        rl = wf._RateLimiter(delay=0.4)
        t0 = time.time()
        for _ in range(3):
            rl.wait("same.org")
        assert (time.time() - t0) >= 0.7, "同域请求必须串行限速"

    def test_different_host_not_blocked(self):
        rl = wf._RateLimiter(delay=5.0)
        t0 = time.time()
        rl.wait("host-a.org")
        assert (time.time() - t0) < 0.5, "不同域之间不应互相阻塞"

    def test_mark_updates_timestamp(self):
        """mark() 表示「刚发过一次请求」，因此后续 wait() 应等满间隔。

        这是并发场景下的关键保证：某个线程抓完后立刻 mark，
        下一个线程的 wait 才知道要等，而不会紧接着再打一次。
        """
        rl = wf._RateLimiter(delay=0.3)
        rl.mark("h.org")
        t0 = time.time()
        rl.wait("h.org")
        assert (time.time() - t0) >= 0.25, "mark 之后必须等满间隔，不能立刻再请求"


# ────────────────────────────────────────────────────────────
# 元数据抽取
# ────────────────────────────────────────────────────────────
class TestMetaExtraction:
    def test_citation_fields(self):
        m = wf.extract_meta(HTML_ARTICLE)
        assert m["title"].startswith("Ceria co-doping")
        assert m["doi"] == "10.1039/C4CP00856A"
        assert m["journal"] == "Physical Chemistry Chemical Physics"
        assert m["volume"] == "16" and m["issue"] == "35"
        assert m["firstpage"] == "15214"
        assert m["pdf_url"] == "https://arxiv.org/pdf/1404.3036"

    def test_multiple_authors(self):
        m = wf.extract_meta(HTML_ARTICLE)
        assert len(m["authors"]) == 3
        assert m["authors"][0] == "Burbano, Mario"

    def test_doi_url_normalised(self):
        html = '<meta name="citation_doi" content="https://doi.org/10.1/abc">'
        assert wf.extract_meta(html)["doi"] == "10.1/abc"

    def test_title_fallback_to_tag(self):
        m = wf.extract_meta("<html><head><title>Plain Title</title></head><body>x</body></html>")
        assert m["title"] == "Plain Title"

    def test_empty_html_safe(self):
        assert wf.extract_meta("") == {}


# ────────────────────────────────────────────────────────────
# 正文抽取
# ────────────────────────────────────────────────────────────
class TestTextExtraction:
    def test_strips_nav_and_footer(self, monkeypatch):
        monkeypatch.setattr(wf, "_has_trafilatura", lambda: False)
        text, engine = wf.extract_text(HTML_ARTICLE, "https://x.example/p")
        assert engine == "builtin-lxml"
        assert "menu junk" not in text and "footer junk" not in text
        assert "Ionic conductivity" in text

    def test_script_content_removed(self):
        t = wf._html_to_text("<script>evil()</script><p>real</p>")
        assert "evil" not in t and "real" in t

    def test_entities_decoded(self):
        t = wf._html_to_text("<p>a &amp; b &lt;c&gt; &nbsp;d</p>")
        assert "a & b <c> d" in t

    def test_paragraphs_preserved(self):
        t = wf._html_to_text("<p>first para</p><p>second para</p>")
        assert "first para" in t and "second para" in t
        assert "first para" in t.split("second para")[0]

    def test_empty_html_safe(self):
        assert wf.extract_text("", "")[0] == ""


# ────────────────────────────────────────────────────────────
# 协议白名单与安全
# ────────────────────────────────────────────────────────────
class TestSecurity:
    def test_only_http_allowed_in_fetch(self, monkeypatch):
        for bad in ("javascript:alert(1)", "file:///c:/windows/system32/config", "data:text/html,x"):
            r = wf.fetch(bad, check_robots=False)
            assert r["ok"] is False, f"{bad} 必须被拒绝"

    def test_user_agent_has_no_identifying_info(self):
        """UA 不得含任何可关联到个人/机构的标识（2026-10-15 反追踪改动）。

        早期版本是 ``MatLens/0.1 (+https://github.com/yygg693/matlens;
        mailto:matlens@example.com)`` —— 每次抓取都主动把「谁在抓」递到
        对方手里，保存一次日志即可长期关联同一来源。
        """
        ua = wf.USER_AGENT
        assert "MatLens" in ua, "仍应标明是学术工具（诚实且无需保密）"
        assert "@" not in ua, "UA 不得含邮箱"
        assert "http://" not in ua and "https://" not in ua, "UA 不得含网址"
        assert "⚠️" not in wf._ua_summary(), f"UA 泄露自检未通过：{ua}"

    def test_ua_env_override_supported(self, monkeypatch):
        """允许用户自定义 UA，但仍受泄露自检约束。"""
        monkeypatch.setenv("MATLENS_WEB_UA", "MyLab/2.0")
        import importlib
        m = importlib.reload(wf)
        try:
            assert m.USER_AGENT == "MyLab/2.0"
        finally:
            monkeypatch.delenv("MATLENS_WEB_UA", raising=False)
            importlib.reload(wf)

    def test_refused_techniques_documented(self):
        """明确记录不做的手段，防止以后被顺手加回。"""
        joined = " ".join(wf.REFUSED_TECHNIQUES).lower()
        for kw in ("undetected", "stealth", "验证码", "代理池", "付费墙"):
            assert kw in joined, f"{kw} 应在拒绝清单中"

    def test_no_stealth_switch_in_public_api(self):
        """服务层不得暴露任何绕过开关 —— 这是有意的不提供。"""
        import inspect
        sig = inspect.signature(wf.fetch)
        for forbidden in ("stealth", "headless", "proxy", "bypass", "cookie"):
            assert not any(forbidden in p for p in sig.parameters), \
                f"fetch() 不应有 {forbidden} 参数"


# ────────────────────────────────────────────────────────────
# 明令禁止的站点（2026-10-15）
# ────────────────────────────────────────────────────────────
class TestBlockedSites:
    def test_cnki_blocked(self):
        for u in ("https://kns.cnki.net/kns8s/search",
                  "http://www.cnki.net/",
                  "https://kns.cnki.net"):
            ok, why = wf._check_blocked(u)
            assert ok is False, f"{u} 必须被禁止"
            assert "明令禁止" in why

    def test_vip_and_cqvip_blocked(self):
        for u in ("https://www.cqvip.com/x", "https://qikan.cqvip.com/"):
            ok, _ = wf._check_blocked(u)
            assert ok is False

    def test_wanfang_blocked(self):
        ok, why = wf._check_blocked("https://s.wanfangdata.com.cn/api")
        assert ok is False and "万方" in why

    def test_subdomain_of_blocked_blocked(self):
        """子域也必须拦住，否则 cnki.net 的镜像站就绕过去了。"""
        ok, _ = wf._check_blocked("https://sub.deep.cnki.net/x")
        assert ok is False

    def test_lookalike_domain_allowed(self):
        """相似域名不能误杀：cnki.net.evil.com 是别人的站点。"""
        ok, _ = wf._check_blocked("https://x.com/cnki.net.evil.com")
        assert ok is True

    def test_normal_sites_allowed(self):
        for u in ("https://arxiv.org/abs/1", "https://www.nature.com/x",
                  "https://api.crossref.org/works"):
            ok, _ = wf._check_blocked(u)
            assert ok is True

    def test_every_entry_has_reason(self):
        for host, reason in wf.BLOCKED_SITES.items():
            assert reason and len(reason) > 12, f"{host} 必须给出原因与替代路径"

    def test_fetch_refuses_blocked_site(self, monkeypatch):
        """即使 robots 允许也拒绝 —— 条款效力高于 robots 文件。"""
        monkeypatch.setattr(wf, "_robots_allows", lambda u: (True, "允许"))
        r = wf.fetch("https://kns.cnki.net/kns8s/search")
        assert r["ok"] is False
        assert "明令禁止" in r["reason"]
        assert "绕过" in r["note_policy"]

    def test_blocked_checked_before_robots(self, monkeypatch):
        """顺序：禁止名单先于 robots。禁止名单不应依赖网络。"""
        calls = []
        monkeypatch.setattr(wf, "_robots_allows", lambda u: (calls.append(u), (True, "ok"))[1])
        wf.fetch("https://www.cnki.net/")
        assert not calls, "命中禁止名单时不应再去查 robots（省一次请求）"


# ────────────────────────────────────────────────────────────
# 反追踪 / 隐私（2026-10-15）
# ────────────────────────────────────────────────────────────
class TestAntiTracking:
    def test_headers_minimalised(self):
        h = {k.lower() for k in wf._minimal_headers()}
        assert "user-agent" in h and "accept" in h
        # 泄露/关联类头一律不发
        for bad in ("referer", "origin", "cookie", "authorization",
                    "x-forwarded-for", "sec-ch-ua", "sec-fetch-site"):
            assert bad not in h, f"不应发送 {bad}"

    def test_no_cookie_processor_in_opener(self):
        """最关键一行：绝不能装 cookie 处理，否则跨请求可被关联。"""
        op = wf._build_opener("socks5://127.0.0.1:9050")
        if op is None:
            pytest.skip("build_opener 不可用")
        handlers = {type(h).__name__ for h in op.handlers}
        assert not any("Cookie" in h for h in handlers), \
            f"opener 含 cookie 处理：{handlers}"

    def test_no_opener_without_proxy(self):
        assert wf._build_opener("") is None

    def test_ua_masking_strips_query_and_userinfo(self):
        masked = wf._mask_url("https://x.org/path?token=secret&utm_source=hn#frag")
        assert "secret" not in masked and "utm_source" not in masked
        assert masked.startswith("https://x.org/path")

    def test_ua_masking_strips_credentials(self):
        masked = wf._mask_url("https://user:pass@x.org/a")
        assert "user" not in masked and "pass" not in masked

    def test_privacy_report_covers_http_and_network_layers(self):
        rep = wf.privacy_report()
        assert "http_layer" in rep and "network_layer" in rep
        assert "stealth_clarification" in rep
        assert rep["ua_leak_free"] is True

    def test_privacy_report_explains_ip_reality(self):
        """必须如实说明 IP 属于网络层、代码控不了 —— 不能含糊承诺。"""
        rep = wf.privacy_report()
        txt = rep["network_layer"]["reality"]
        assert "IP" in txt
        assert "代理" in " ".join(o[0] + o[1] for o in rep["network_layer"]["options"]) \
            or "Tor" in str(rep["network_layer"]["options"])

    def test_privacy_report_bottom_line_not_overpromising(self):
        rep = wf.privacy_report()
        assert "不会给" in rep["honest_bottom_line"], "不应承诺无法兑现的匿名性"

    def test_stealth_clarification_explains_direction(self):
        """必须讲清 stealth 与反追踪方向相反，否则用户会继续误解。"""
        s = wf.privacy_report()["stealth_clarification"]
        assert "相反" in " ".join(s["why_not_here"])

    def test_proxy_env_read(self, monkeypatch):
        """代理配置来自设置页（network 段），环境变量仅作未配置时的兜底。"""
        from matlens_kit.web import proxy_manager as pm

        monkeypatch.setattr(pm, "_load_network_section", lambda: {
            "proxy_enabled": True, "proxy_url": "socks5://127.0.0.1:9050"})
        rep = wf.privacy_report()
        assert rep["proxy"]["configured"] is True
        assert rep["proxy"]["scheme"] == "socks5"
        monkeypatch.setattr(pm, "_load_network_section", lambda: {
            "proxy_enabled": False, "proxy_url": ""})
        monkeypatch.delenv("MATLENS_WEB_PROXY", raising=False)
        rep2 = wf.privacy_report()
        assert rep2["proxy"]["configured"] is False
        assert "本机" in rep2["proxy"]["note"]

    def test_capabilities_expose_privacy(self):
        c = wf.capabilities()
        assert c["privacy"]["ua_leak_free"] is True
        assert c["privacy"]["no_cookies"] is True
        assert c["privacy"]["no_referer"] is True
        assert c["blocked_sites"] >= 4

    def test_capabilities_policy_mentions_privacy(self):
        yes = " ".join(wf.capabilities()["policy"]["yes"])
        assert "Cookie" in yes and "缓存" in yes


# ────────────────────────────────────────────────────────────
# 代理：协议识别 / 绝不静默回落 / 出口实测
# ────────────────────────────────────────────────────────────
class TestProxy:
    def test_scheme_recognition(self):
        assert wf._proxy_kind("socks5://127.0.0.1:9050") == "socks5"
        assert wf._proxy_kind("socks5h://127.0.0.1:9150") == "socks5h"
        assert wf._proxy_kind("http://127.0.0.1:8080") == "http"
        assert wf._proxy_kind("https://p:443") == "https"

    def test_unsupported_scheme_rejected(self):
        for bad in ("ftp://1.2.3.4:1080", "garbage", "socks9://x"):
            assert wf._proxy_kind(bad) == ""

    def test_invalid_proxy_raises_not_silent(self):
        """⚠️ 这是安全关键：非法配置必须报错，绝不静默直连。

        urllib 的 ProxyHandler 只认 http/https，传 socks5 会被**静默忽略**
        —— 用户以为配好了 Tor，实际在裸奔，且毫无报错。
        """
        for bad in ("ftp://1.2.3.4:1080", "garbage"):
            with pytest.raises(ValueError):
                wf._build_opener(bad)

    def test_no_proxy_returns_none(self):
        assert wf._build_opener("") is None

    def test_socks_opener_built(self):
        op = wf._build_opener("socks5://127.0.0.1:9050")
        assert op is not None
        handlers = {type(h).__name__ for h in getattr(op, "handlers", [])}
        assert not any("Cookie" in h for h in handlers), f"SOCKS opener 不得含 cookie：{handlers}"

    def test_socks_connection_failure_not_fallback(self):
        """SOCKS 代理不可用时必须抛错，绝不退回直连。"""
        op = wf._build_opener("socks5://127.0.0.1:1")   # 必然不可达
        with pytest.raises(Exception):
            op.open("https://api.ipify.org?format=json", timeout=4)

    def test_proxy_masking_hides_credentials(self):
        masked = wf._mask_proxy("socks5://user:secret@127.0.0.1:9050")
        assert "secret" not in masked and "user" not in masked
        assert "127.0.0.1" in masked

    def test_privacy_report_proxy_fields(self, monkeypatch):
        from matlens_kit.web import proxy_manager as pm

        monkeypatch.setattr(pm, "_load_network_section", lambda: {
            "proxy_enabled": True, "proxy_url": "socks5h://127.0.0.1:9150"})
        p = wf.privacy_report()["proxy"]
        assert p["configured"] is True
        assert p["scheme"] == "socks5h"
        assert p["dns_via_proxy"] is True, "socks5h 应由代理端做 DNS"

    def test_privacy_recommends_socks5h_for_dns_leak(self):
        howto = " ".join(wf.privacy_report()["proxy"]["howto"].values())
        assert "socks5h" in howto, "应提示用 socks5h 避免 DNS 泄露"

    def test_check_proxy_reports_not_protected(self, monkeypatch):
        """未配代理时必须明确说「你在裸奔」，而不是含糊带过。"""
        monkeypatch.delenv("MATLENS_WEB_PROXY", raising=False)
        monkeypatch.setattr(wf, "_probe_ip", lambda proxy="", timeout=12.0:
                            {"ok": True, "ip": "1.2.3.4"})
        r = wf.check_proxy()
        assert r["protected"] is False
        assert "本机" in r["verdict"]

    def test_check_proxy_detects_same_ip_as_unprotected(self, monkeypatch):
        """最危险的假象：配了代理但出口 IP 一样 = 白配。"""
        monkeypatch.setattr(wf, "_probe_ip", lambda proxy="", timeout=12.0:
                            {"ok": True, "ip": "1.2.3.4"})
        r = wf.check_proxy(explicit_proxy="http://127.0.0.1:8080")
        assert r["ok"] is True
        assert r["protected"] is False, "出口未变必须判定为未受保护"
        assert "裸奔" in r["verdict"]

    def test_check_proxy_detects_changed_ip(self, monkeypatch):
        def fake(proxy="", timeout=12.0):
            return {"ok": True, "ip": "9.9.9.9" if proxy else "1.2.3.4"}
        monkeypatch.setattr(wf, "_probe_ip", fake)
        r = wf.check_proxy(explicit_proxy="socks5://127.0.0.1:9050")
        assert r["protected"] is True
        assert r["direct_ip"] != r["proxy_ip"]

    def test_check_proxy_proxy_failure_explains(self, monkeypatch):
        def fake(proxy="", timeout=12.0):
            if proxy:
                return {"ok": False, "error": "连接被拒"}
            return {"ok": True, "ip": "1.2.3.4"}
        monkeypatch.setattr(wf, "_probe_ip", fake)
        r = wf.check_proxy(explicit_proxy="socks5://127.0.0.1:9050")
        assert r["ok"] is False
        assert "静默" in r["advice"], "须说明不会静默改直连"

    def test_check_proxy_rejects_bad_scheme(self):
        r = wf.check_proxy(explicit_proxy="ftp://1.2.3.4:1080")
        assert r["ok"] is False and "不支持" in r["error"]


# ────────────────────────────────────────────────────────────
# fetch 主流程（注入假 HTTP）
# ────────────────────────────────────────────────────────────
class TestFetch:
    def test_success_path(self, monkeypatch):
        monkeypatch.setattr(wf, "_robots_allows", lambda u: (True, "ok"))
        monkeypatch.setattr(wf, "_http_get",
                            lambda *a, **k: (200, "text/html; charset=utf-8", HTML_ARTICLE))
        monkeypatch.setattr(wf, "_has_trafilatura", lambda: False)
        r = wf.fetch("https://x.example/paper")
        assert r["ok"] is True and r["status"] == 200
        assert r["doi"] == "10.1039/C4CP00856A"
        assert r["text_chars"] > 100
        assert "elapsed_ms" in r

    def test_http_403_reports_paywall_hint(self, monkeypatch):
        monkeypatch.setattr(wf, "_robots_allows", lambda u: (True, "ok"))
        err = urllib.error.HTTPError("u", 403, "Forbidden", {}, None)
        monkeypatch.setattr(wf, "_http_get", lambda *a, **k: (_ for _ in ()).throw(err))
        r = wf.fetch("https://x.example/paywalled")
        assert r["ok"] is False and r["status"] == 403
        assert "不绕过" in r["note_policy"]

    def test_network_error_handled(self, monkeypatch):
        monkeypatch.setattr(wf, "_robots_allows", lambda u: (True, "ok"))
        err = urllib.error.URLError("connection refused")
        monkeypatch.setattr(wf, "_http_get", lambda *a, **k: (_ for _ in ()).throw(err))
        r = wf.fetch("https://x.example/a")
        assert r["ok"] is False and "网络错误" in r["reason"]

    def test_empty_url(self):
        assert wf.fetch("")["ok"] is False

    def test_missing_scheme_autopadded(self, monkeypatch):
        monkeypatch.setattr(wf, "_robots_allows", lambda u: (True, "ok"))
        monkeypatch.setattr(wf, "_http_get",
                            lambda *a, **k: (200, "text/html", HTML_ARTICLE))
        monkeypatch.setattr(wf, "_has_trafilatura", lambda: False)
        r = wf.fetch("example.org/paper")
        assert r["url"].startswith("https://")

    def test_with_text_false_skips_body(self, monkeypatch):
        monkeypatch.setattr(wf, "_robots_allows", lambda u: (True, "ok"))
        monkeypatch.setattr(wf, "_http_get",
                            lambda *a, **k: (200, "text/html", HTML_ARTICLE))
        r = wf.fetch("https://x.example/p", with_text=False)
        assert r["ok"] is True and not r.get("text")


# ────────────────────────────────────────────────────────────
# 批量
# ────────────────────────────────────────────────────────────
class TestFetchMany:
    def test_partial_failure_isolated(self, monkeypatch):
        monkeypatch.setattr(wf, "_robots_allows", lambda u: (True, "ok"))
        monkeypatch.setattr(wf, "_has_trafilatura", lambda: False)
        wf._RATE.delay = 0.01

        err = urllib.error.HTTPError("u", 404, "Not Found", {}, None)

        def fake_http(url, timeout=20.0, accept=None):
            if "bad" in url:
                raise err
            return (200, "text/html; charset=utf-8", HTML_ARTICLE)

        monkeypatch.setattr(wf, "_http_get", fake_http)
        out = wf.fetch_many(["https://a.example/1", "https://bad.example/2",
                             "https://c.example/3"])
        assert len(out) == 3
        assert out[0]["ok"] and out[2]["ok"], "正常页应成功"
        assert out[1]["ok"] is False, "失败页应被隔离，不影响其他页"
        assert out[1]["status"] == 404

    def test_empty_input(self):
        assert wf.fetch_many([]) == []


# ────────────────────────────────────────────────────────────
# 工具层
# ────────────────────────────────────────────────────────────
class TestTools:
    def test_failure_returns_actionable_hint(self, monkeypatch):
        monkeypatch.setattr(wf, "_robots_allows", lambda u: (True, "ok"))
        err = urllib.error.HTTPError("u", 403, "F", {}, None)
        monkeypatch.setattr(wf, "_http_get", lambda *a, **k: (_ for _ in ()).throw(err))
        out = web_fetch_tool(url="https://x.example/p")
        assert out["success"] is False
        assert "Unpaywall" in out["hint"], "403 必须指向开放获取替代路径"
        assert "不绕过" in out.get("hint", "") + out.get("reason", "")

    def test_success_truncates_text(self, monkeypatch):
        monkeypatch.setattr(wf, "_robots_allows", lambda u: (True, "ok"))
        monkeypatch.setattr(wf, "_http_get",
                            lambda *a, **k: (200, "text/html; charset=utf-8", HTML_ARTICLE))
        monkeypatch.setattr(wf, "_has_trafilatura", lambda: False)
        out = web_fetch_tool(url="https://x.example/p", max_chars=500)
        assert out["success"] is True
        assert len(out["text"]) <= 500
        assert out["truncated"] is True

    def test_batch_tool_limit(self):
        out = web_fetch_batch_tool(urls=[f"https://x/{i}" for i in range(50)])
        assert out["total"] <= 8, "批量必须限流，避免打爆对方站点"

    def test_batch_empty_urls(self):
        assert web_fetch_batch_tool(urls=[])["success"] is False

    def test_hint_for_robots_block(self):
        h = _hint_for_failure(None, "robots.txt 明确禁止抓取该路径（已遵守）")
        assert "robots" in h.lower()
        assert "人工检索" in h or "开放 API" in h

    def test_hint_for_404(self):
        assert "DOI" in _hint_for_failure(404, "HTTP 404")

    def test_hint_for_429(self):
        assert "限流" in _hint_for_failure(429, "HTTP 429")


# ────────────────────────────────────────────────────────────
# 能力自检
# ────────────────────────────────────────────────────────────
class TestCapabilities:
    def test_reports_tier_and_policy(self):
        c = wf.capabilities()
        assert c["l1_http"] is True
        assert c["respects_robots"] is True
        assert c["policy"]["yes"] and c["policy"]["no"]
        assert any("robots" in x for x in c["policy"]["yes"])

    def test_declares_rate_limit(self):
        assert "间隔" in wf.capabilities()["rate_limit"]


# ────────────────────────────────────────────────────────────
# 代理管理器：配置解析 / 自动+手动换 IP（2026-10-15）
# ────────────────────────────────────────────────────────────
class TestProxyManager:
    def _cfg(self, **over):
        """注意：这里模拟的是 _load_network_section 的**磁盘形状**（proxy_url），
        不是 get_config 的 API 形状（url）—— 两者键名不同，容易搞混。"""
        base = {"proxy_enabled": True, "proxy_url": "socks5h://127.0.0.1:9150",
                "tor_control": "127.0.0.1:9051", "rotate_enabled": False,
                "rotate_every": 30, "rotate_max_requests": 50}
        base.update(over)
        return base

    def test_config_shape(self):
        cfg = pm.get_config()
        for k in ("enabled", "url", "tor_control", "rotate_enabled",
                  "rotate_every", "rotate_max_requests"):
            assert k in cfg

    def test_disabled_means_no_proxy(self, monkeypatch):
        monkeypatch.setattr(pm, "_load_network_section",
                            lambda: self._cfg(proxy_enabled=False))
        monkeypatch.delenv("MATLENS_WEB_PROXY", raising=False)
        assert pm.effective_proxy() == "", "关闭时必须直连，不能隐式回退"

    def test_scheme_autofilled(self, monkeypatch):
        """没写协议时按 socks5h 处理（防 DNS 泄露）。"""
        monkeypatch.setattr(pm, "_load_network_section",
                            lambda: self._cfg(proxy_url="127.0.0.1:9050"))
        assert pm.effective_proxy() == "socks5h://127.0.0.1:9050"

    def test_env_fallback_when_not_configured(self, monkeypatch):
        """设置页**从未配置过** network 段时，才用环境变量兜底。"""
        monkeypatch.setattr(pm, "_load_network_section", lambda: {})
        monkeypatch.setenv("MATLENS_WEB_PROXY", "http://127.0.0.1:8080")
        assert pm.effective_proxy() == "http://127.0.0.1:8080"
        assert pm.get_config()["source"] == "env"

    def test_disabled_wins_over_env(self, monkeypatch):
        """设置页明确关闭时，环境变量不该把它偷偷打开。"""
        monkeypatch.setattr(pm, "_load_network_section",
                            lambda: self._cfg(proxy_enabled=False, proxy_url="socks5h://x:1"))
        monkeypatch.setenv("MATLENS_WEB_PROXY", "http://127.0.0.1:8080")
        assert pm.effective_proxy() == ""

    def test_rotate_disabled_never_due(self, monkeypatch):
        monkeypatch.setattr(pm, "_load_network_section",
                            lambda: self._cfg(rotate_enabled=False))
        pm.note_request()
        due, why = pm._should_rotate()
        assert due is False and "未开启" in why

    def test_rotate_by_request_count(self, monkeypatch):
        monkeypatch.setattr(pm, "_load_network_section",
                            lambda: self._cfg(rotate_enabled=True, rotate_max_requests=3))
        with pm._state_lock:
            pm._requests_since_rotate = 0
            pm._last_rotate_ts = 0.0
        for _ in range(3):
            pm.note_request()
        due, why = pm._should_rotate()
        assert due is True and "上限" in why

    def test_rotate_not_due_before_threshold(self, monkeypatch):
        monkeypatch.setattr(pm, "_load_network_section",
                            lambda: self._cfg(rotate_enabled=True, rotate_max_requests=50))
        with pm._state_lock:
            pm._requests_since_rotate = 0
        pm.note_request()
        assert pm._should_rotate()[0] is False

    def test_rotate_needs_proxy(self, monkeypatch):
        monkeypatch.setattr(pm, "_load_network_section",
                            lambda: self._cfg(proxy_enabled=False, proxy_url="", rotate_enabled=True))
        monkeypatch.delenv("MATLENS_WEB_PROXY", raising=False)
        due, why = pm._should_rotate()
        assert due is False and "代理" in why

    def test_newnym_reports_failure_not_fake_success(self):
        """Tor 不可用时必须如实失败，不能假装换成功。"""
        r = pm.tor_newnym(timeout=2, addr="127.0.0.1:1")
        assert r["ok"] is False
        assert r.get("reason")

    def test_newnym_throttled_when_too_soon(self, monkeypatch):
        with pm._state_lock:
            pm._last_rotate_ts = pm.time.time()   # 刚换过
        r = pm.tor_newnym(timeout=2, addr="127.0.0.1:1")
        assert r.get("skipped") is True, "间隔未到应跳过而非连打 Tor"
        assert r.get("retry_after_s", 0) > 0

    def test_counter_is_process_local(self, monkeypatch):
        """请求计数只在内存里 —— 磁盘上不留「换过几次 IP」的痕迹。"""
        with pm._state_lock:
            pm._requests_since_rotate = 0
        pm.note_request(); pm.note_request()
        with pm._state_lock:
            assert pm._requests_since_rotate == 2
        st = pm.rotate_status()
        assert "requests_since_rotate" in st and "note" in st

    def test_rotate_status_explains_tor_requirement(self):
        st = pm.rotate_status()
        assert st["tor_needed"] is True
        assert "NEWNYM" in st["note"]

    def test_no_random_proxy_pool(self):
        """不应存在「随机代理池」相关实现 —— 只走 Tor。"""
        import inspect
        src = inspect.getsource(pm)
        for banned in ("random.choice", "proxy_list", "free_proxy", "pool[", "random_proxy"):
            assert banned not in src, f"不应出现 {banned}"


# ────────────────────────────────────────────────────────────
# Unpaywall OA 自动降级链（2026-10-16）
# ────────────────────────────────────────────────────────────
class TestOaFallback:
    """抓不到正文时自动转向合法开放获取版本。

    背景：IOP（iopscience.iop.org）整站跳 validate.perfdrive.com 反爬，
    robots 也禁止 —— 但这些论文大多有 arXiv 预印本，Unpaywall 能解析出来。
    实测 10.1039/C4CP00856A：从 0 字符变成 64004 字全文。
    """

    def test_doi_from_url_doi_org(self):
        assert wf._doi_from_url("https://doi.org/10.1039/C4CP00856A") == "10.1039/C4CP00856A"

    def test_doi_from_publisher_url(self):
        assert wf._doi_from_url(
            "https://iopscience.iop.org/article/10.1149/1.1837395") == "10.1149/1.1837395"

    def test_doi_from_nature_article_url(self):
        """Nature 用 sXXXX 编号，需补 10.1038 前缀（实测过严正则会漏）。"""
        assert wf._doi_from_url(
            "https://www.nature.com/articles/s41560-023-01321-7") == "10.1038/s41560-023-01321-7"

    def test_doi_from_url_strips_trailing_punct(self):
        assert wf._doi_from_url("https://x.org/10.1039/C4CP00856A.") == "10.1039/C4CP00856A"

    def test_doi_from_url_returns_empty_when_unknown(self):
        """无法确定前缀时宁可不降级，也别查错文献。"""
        assert wf._doi_from_url("https://arxiv.org/abs/1404.3036") == ""
        assert wf._doi_from_url("https://example.com/page") == ""

    def test_fallback_disabled_by_flag(self, monkeypatch):
        monkeypatch.setattr(wf, "_robots_allows", lambda u: (False, "robots 禁止"))
        r = wf.fetch("https://iopscience.iop.org/article/10.1149/1.1837395",
                     oa_fallback=False)
        assert r["ok"] is False
        assert "oa_fallback" not in r, "关闭降级时不应触发 Unpaywall"

    def test_blocked_site_never_falls_back(self, monkeypatch):
        """明令禁止的站点连找替代版都不做 —— 那是服务条款层面的禁止。"""
        called = []
        monkeypatch.setattr(wf, "_robots_allows", lambda u: (True, "允许"))
        monkeypatch.setattr(wf, "_try_oa_fallback",
                            lambda *a, **k: called.append(a))
        wf.fetch("https://kns.cnki.net/kns8s/search")
        assert not called, "禁止名单站点不应触发 OA 降级"

    def test_same_domain_oa_is_rejected(self, monkeypatch):
        """bronze 版常仍指向出版商自身，换域名才有意义 —— 直接标注不重试。"""
        oa = {"is_oa": True, "oa_status": "bronze",
              "oa_url": "https://iopscience.iop.org/article/10.1149/1.1837395/pdf"}
        monkeypatch.setattr("matlens_kit.rag.scholarly.fetch_unpaywall",
                            lambda doi, timeout=15.0: dict(oa))
        res = wf.FetchResult(ok=False, url="https://iopscience.iop.org/article/10.1149/1.1837395")
        wf._try_oa_fallback(res, "10.1149/1.1837395")
        assert res.get("oa_fallback_error"), "同域 OA 必须说明原因"
        assert "bronze" in res["oa_fallback_error"]

    def test_no_oa_version_reported_honestly(self, monkeypatch):
        """没有合法 OA 版本时如实说明，不编造链接。"""
        oa = {"is_oa": False, "oa_status": "closed", "oa_url": ""}
        monkeypatch.setattr("matlens_kit.rag.scholarly.fetch_unpaywall",
                            lambda doi, timeout=15.0: dict(oa))
        res = wf.FetchResult(ok=False, url="https://x.org/a")
        wf._try_oa_fallback(res, "10.1/x")
        assert res.get("oa_fallback_error")
        assert "没有合法开放获取版本" in res["oa_fallback_error"]
        assert not res.get("text")

    def test_unpaywall_exception_is_contained(self, monkeypatch):
        def boom(doi, timeout=15.0):
            raise RuntimeError("未配置 UNPAYWALL_EMAIL")
        monkeypatch.setattr("matlens_kit.rag.scholarly.fetch_unpaywall", boom)
        res = wf.FetchResult(ok=False, url="https://x.org/a")
        wf._try_oa_fallback(res, "10.1/x")     # 不应抛出
        assert "Unpaywall 查询失败" in res.get("oa_fallback_error", "")

    def test_fallback_respects_blocked_list(self, monkeypatch):
        """OA 目标域名若本身在禁止名单里，也不能抓。"""
        oa = {"is_oa": True, "oa_status": "green",
              "oa_url": "https://some.cnki.net/paper.pdf"}
        monkeypatch.setattr("matlens_kit.rag.scholarly.fetch_unpaywall",
                            lambda doi, timeout=15.0: dict(oa))
        res = wf.FetchResult(ok=False, url="https://x.org/a")
        wf._try_oa_fallback(res, "10.1/x")
        # 递归 fetch 内部会再做禁止名单检查；此处至少不应声称成功
        assert not res.get("resolved_via")


# ────────────────────────────────────────────────────────────
# Unpaywall OA 自动降级链（2026-10-16）
# ────────────────────────────────────────────────────────────
class TestOaFallback:
    """抓不到正文时自动转向合法开放获取版本。

    背景：IOP（iopscience.iop.org）整站跳 validate.perfdrive.com 反爬，
    robots 也禁止 —— 但这些论文大多有 arXiv 预印本，Unpaywall 能解析出来。
    实测 10.1039/C4CP00856A：从 0 字符变成 64004 字全文。
    """

    def test_doi_from_url_doi_org(self):
        assert wf._doi_from_url("https://doi.org/10.1039/C4CP00856A") == "10.1039/C4CP00856A"

    def test_doi_from_publisher_url(self):
        assert wf._doi_from_url(
            "https://iopscience.iop.org/article/10.1149/1.1837395") == "10.1149/1.1837395"

    def test_doi_from_nature_article_url(self):
        """Nature 用 sXXXX 编号，需补 10.1038 前缀（实测过严正则会漏）。"""
        assert wf._doi_from_url(
            "https://www.nature.com/articles/s41560-023-01321-7") == "10.1038/s41560-023-01321-7"

    def test_doi_from_url_strips_trailing_punct(self):
        assert wf._doi_from_url("https://x.org/10.1039/C4CP00856A.") == "10.1039/C4CP00856A"

    def test_doi_from_url_returns_empty_when_unknown(self):
        """无法确定前缀时宁可不降级，也别查错文献。"""
        assert wf._doi_from_url("https://arxiv.org/abs/1404.3036") == ""
        assert wf._doi_from_url("https://example.com/page") == ""

    def test_fallback_disabled_by_flag(self, monkeypatch):
        monkeypatch.setattr(wf, "_robots_allows", lambda u: (False, "robots 禁止"))
        r = wf.fetch("https://iopscience.iop.org/article/10.1149/1.1837395",
                     oa_fallback=False)
        assert r["ok"] is False
        assert "oa_fallback" not in r, "关闭降级时不应触发 Unpaywall"

    def test_blocked_site_never_falls_back(self, monkeypatch):
        """明令禁止的站点连找替代版都不做 —— 那是服务条款层面的禁止。"""
        called = []
        monkeypatch.setattr(wf, "_robots_allows", lambda u: (True, "允许"))
        monkeypatch.setattr(wf, "_try_oa_fallback",
                            lambda *a, **k: called.append(a))
        wf.fetch("https://kns.cnki.net/kns8s/search")
        assert not called, "禁止名单站点不应触发 OA 降级"

    def test_same_domain_oa_is_rejected(self, monkeypatch):
        """bronze 版常仍指向出版商自身，换域名才有意义 —— 直接标注不重试。"""
        oa = {"is_oa": True, "oa_status": "bronze",
              "oa_url": "https://iopscience.iop.org/article/10.1149/1.1837395/pdf"}
        monkeypatch.setattr("matlens_kit.rag.scholarly.fetch_unpaywall",
                            lambda doi, timeout=15.0: dict(oa))
        res = wf.FetchResult(ok=False, url="https://iopscience.iop.org/article/10.1149/1.1837395")
        wf._try_oa_fallback(res, "10.1149/1.1837395")
        assert res.get("oa_fallback_error"), "同域 OA 必须说明原因"
        assert "bronze" in res["oa_fallback_error"]

    def test_no_oa_version_reported_honestly(self, monkeypatch):
        """没有合法 OA 版本时如实说明，不编造链接。"""
        oa = {"is_oa": False, "oa_status": "closed", "oa_url": ""}
        monkeypatch.setattr("matlens_kit.rag.scholarly.fetch_unpaywall",
                            lambda doi, timeout=15.0: dict(oa))
        res = wf.FetchResult(ok=False, url="https://x.org/a")
        wf._try_oa_fallback(res, "10.1/x")
        assert res.get("oa_fallback_error")
        assert "没有合法开放获取版本" in res["oa_fallback_error"]
        assert not res.get("text")

    def test_unpaywall_exception_is_contained(self, monkeypatch):
        def boom(doi, timeout=15.0):
            raise RuntimeError("未配置 UNPAYWALL_EMAIL")
        monkeypatch.setattr("matlens_kit.rag.scholarly.fetch_unpaywall", boom)
        res = wf.FetchResult(ok=False, url="https://x.org/a")
        wf._try_oa_fallback(res, "10.1/x")     # 不应抛出
        assert "Unpaywall 查询失败" in res.get("oa_fallback_error", "")

    def test_fallback_respects_blocked_list(self, monkeypatch):
        """OA 目标域名若本身在禁止名单里，也不能抓。"""
        oa = {"is_oa": True, "oa_status": "green",
              "oa_url": "https://some.cnki.net/paper.pdf"}
        monkeypatch.setattr("matlens_kit.rag.scholarly.fetch_unpaywall",
                            lambda doi, timeout=15.0: dict(oa))
        res = wf.FetchResult(ok=False, url="https://x.org/a")
        wf._try_oa_fallback(res, "10.1/x")
        # 递归 fetch 内部会再做禁止名单检查；此处至少不应声称成功
        assert not res.get("resolved_via")
