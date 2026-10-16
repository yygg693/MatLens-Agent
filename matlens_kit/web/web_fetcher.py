# -*- coding: utf-8 -*-
"""MatLens · 网页/文献抓取内核（web_fetcher）。

为什么需要这个模块（2026-10-15）
--------------------------------
此前 MatLens 只能「打开用户给的 PDF / 本地文件」，Agent 无法主动去网上取材料：
论文写作流程里最缺的一环是「找到这批文献后把正文抓下来」，否则只能拿到题录。
本模块提供 Agent 可调用的抓取能力，并**在设计上守住合规底线**。

设计原则（不可妥协）
--------------------
1. **只抓公开可访问的内容**。遵守 robots.txt（``/robots.txt`` 的 Disallow），
   付费墙后的正文取不到就如实报告 ``blocked_by_paywall``，**不做绕过**。
2. **不做反检测伪装**。不使用 undetected 浏览器、指纹伪造、验证码绕过、
   代理池轮换等规避手段。User-Agent 如实标识 MatLens —— 这是学术工具该有的
   礼貌，也是让站点管理员能联系到我们的唯一途径。
3. **礼貌限速**。默认单域请求间隔 1.5s，单次并发 3，超时 20s。
   我们宁可慢，也不给目标站造成压力（这既是伦理也是长期可持续性）。
4. **原文返回、不改写**。抽取正文用 trafilatura（开源、去噪保真），
   降级用内置 lxml 规则。**不做摘要改写** —— 避免生成失真的「引用」。

三层能力（按依赖优雅降级）
--------------------------
- **L1 HTTP + 正文抽取**（零额外依赖，httpx + lxml，项目已有）→ 始终可用
- **L2 trafilatura 正文抽取**（可选，抽取质量显著更好）→ 装了自动用
- **L3 crawl4ai 动态渲染**（可选，能处理 JS 页面 / arXiv abs 页等）→ 装了自动用

对应 GitHub 参考（详见 docs/kb_cloud_sources_research.md）：
- ``unclecode/crawl4ai``（85.6k★, Apache-2.0）—— LLM 友好 Markdown，
  **其 stealth/undetected 能力本项目明确不启用**
- ``adbar/trafilatura``（7.0k★, Apache-2.0）—— 正文抽取事实标准
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from typing import Any, Dict, List, Optional, Tuple

# ────────────────────────────────────────────────────────────
# 合规常量
# ────────────────────────────────────────────────────────────
#: User-Agent —— **不含任何可关联到个人/机构的标识**。
#:
#: 反追踪第一原则：请求头本身不能成为「指纹」。
#: 这里只留工具名与用途；**不放 GitHub 地址、不放邮箱、不放本机路径**。
#: 早期版本写的是 ``MatLens/0.1 (+https://github.com/yygg693/matlens;
#: mailto:matlens@example.com)`` —— 那等于每次抓取都把「谁在抓」主动
#: 递到对方手里，对方只需保存一次日志就能长期关联同一来源。这是自曝，
#: 不是礼貌。站点方要联系开发者时看项目主页即可，不需要出现在请求头里。
#:
#: 想自定义请设环境变量 ``MATLENS_WEB_UA``；留空则用下面这个最小标识。
_UA_DEFAULT = "MatLens/0.1 (academic research crawler)"
USER_AGENT = (os.environ.get("MATLENS_WEB_UA") or "").strip() or _UA_DEFAULT

DEFAULT_TIMEOUT = 20.0
DEFAULT_DELAY = 1.5          # 同域最小请求间隔（秒）
MAX_CONCURRENCY = 3
MAX_HTML_BYTES = 12 * 1024 * 1024   # 单页最大下载 12MB，防超大页面打爆内存
MAX_TEXT_CHARS = 200_000     # 单页返回正文上限

#: 明确不做的事，写进代码里防止以后被"顺手加回去"
REFUSED_TECHNIQUES = (
    "undetected-chromedriver / playwright-stealth 指纹伪装",
    "验证码 OCR 与滑块破解",
    "付费墙 cookie 注入与内容盗取",
    "代理池轮换以规避 IP 封禁",
    "伪造 Referer / 登录态绕过机构访问控制",
    "抓取知网 / 维普 / 超星等明令禁止的站点（见 BLOCKED_SITES）",
)


# ────────────────────────────────────────────────────────────
# 站点禁止名单 —— 明令禁止，不做任何例外
# ────────────────────────────────────────────────────────────
#: 这些站点**明确禁止自动化抓取**（服务条款 / 技术措施），
#: 或需付费订阅且无公开接口。MatLens 不抓，代码层面直接拦死。
#:
#: 拦截发生在 robots 检查**之前**：即便对方 robots 允许（知网首页是允许的），
#: 本名单仍然拒绝 —— 因为服务条款的效力高于 robots 文件，robots 只是
#: 技术层的一层，不能替代条款授权。
#:
#: 替代路径不是没有，只是人工的：
#:   知网/万方 官网检索 → 导出 Refworks/EndNote 题录 → 用知识库「添加文献」导入。
BLOCKED_SITES = {
    "cnki.net": "知网服务条款禁止自动化抓取；且无公开 API（仅机构合作）。"
                "正确路径：官网检索 → 导出 Refworks/EndNote 题录 → 用知识库导入。",
    "cnki.com.cn": "知网服务条款禁止自动化抓取。改用官网人工检索并导出题录。",
    "cqvip.com": "维普对自动化请求返回 412/滑动验证，且服务条款禁止批量抓取。"
                 "改用官网人工检索并导出题录。",
    "wanfangdata.com.cn": "万方开放平台按点计费、未授权时不可调用；"
                          "服务条款禁止非授权批量抓取。改用官网导出题录。",
    "cqvip.cn": "维普镜像站，同样禁止自动化抓取。改用官网人工检索导出题录。",
    "duxiu.com": "读秀（超星）服务条款禁止自动化抓取，且有验证码体系。"
                 "改用官网人工检索导出题录。",
    "duxiu.net": "读秀（超星）服务条款禁止自动化抓取，且有验证码体系。"
                 "改用官网人工检索导出题录。",
    "chaoxing.com": "超星服务条款禁止自动化抓取。改用官网人工检索导出题录。",
}


def _check_blocked(url: str) -> Tuple[bool, str]:
    """检查是否命中禁止名单。返回 (是否允许, 原因)。"""
    try:
        host = (urllib.parse.urlsplit(url).netloc or "").lower()
    except Exception:
        return True, ""
    if not host:
        return True, ""
    # 去掉端口
    host = host.split(":")[0]
    for blocked, reason in BLOCKED_SITES.items():
        if host == blocked or host.endswith("." + blocked):
            return False, f"MatLens 明令禁止抓取 {blocked}：{reason}"
    return True, "不在禁止名单"


# ────────────────────────────────────────────────────────────
# 单域限速器
# ────────────────────────────────────────────────────────────
class _RateLimiter:
    """按域名限速。

    我们做「礼貌抓取」而不是「高速轰炸」：同域请求至少间隔 delay 秒。
    这既是对目标站的基本尊重，也避免被判定为滥用后整个 IP 段被拉黑
    （对科研用户反而更不利）。
    """

    def __init__(self, delay: float = DEFAULT_DELAY):
        self.delay = delay
        self._last: Dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str) -> float:
        """阻塞直到该域可以发起请求，返回实际等待秒数。"""
        with self._lock:
            now = time.time()
            last = self._last.get(host, 0.0)
            wait = self.delay - (now - last)
            if wait > 0:
                time.sleep(wait)
                now = time.time()
            self._last[host] = now
        return max(0.0, wait)

    def mark(self, host: str) -> None:
        with self._lock:
            self._last[host] = time.time()


_RATE = _RateLimiter()

# robots.txt 缓存：同一域名只查一次（robots 本身也是请求）
_ROBOTS: Dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}
_ROBOTS_LOCK = threading.Lock()


def _robots_allows(url: str) -> Tuple[bool, str]:
    """检查 robots.txt 是否允许抓取该 URL。

    返回 (allowed, reason)。robots 拿不到时**保守放行**（等同主流爬虫惯例：
    连不上 robots 视为无限制），但记下原因供 UI 展示。
    """
    parts = urllib.parse.urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return False, "非法 URL"
    if parts.scheme not in ("http", "https"):
        return False, f"仅支持 http/https，收到 {parts.scheme}"
    base = f"{parts.scheme}://{parts.netloc}"

    with _ROBOTS_LOCK:
        cached = _ROBOTS.get(base, "__miss__")
    if cached == "__miss__":
        rp: Optional[urllib.robotparser.RobotFileParser] = None
        try:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(base + "/robots.txt")
            # RobotFileParser.read() 用 urllib，10s 超时防挂起
            import socket
            old = socket.getdefaulttimeout()
            socket.setdefaulttimeout(8.0)
            try:
                rp.read()
            finally:
                socket.setdefaulttimeout(old)
        except Exception:
            rp = None
        with _ROBOTS_LOCK:
            _ROBOTS[base] = rp

    rp = _ROBOTS.get(base)
    if rp is None:
        return True, "robots.txt 无法获取（按惯例放行）"
    try:
        allowed = rp.can_fetch(USER_AGENT, url)
    except Exception:
        return True, "robots 解析异常（按惯例放行）"
    if allowed:
        return True, "robots.txt 允许"
    return False, "robots.txt 明确禁止抓取该路径（已遵守）"


# ────────────────────────────────────────────────────────────
# HTTP 抓取
# ────────────────────────────────────────────────────────────
class FetchResult(dict):
    """抓取结果（dict 子类，便于 JSON 序列化）。"""


def _minimal_headers(accept: Optional[str] = None) -> Dict[str, str]:
    """构造**最小化**的请求头 —— 反追踪的第二个关键面。

    每个多余的请求头都是一条可关联的信息。逐条说明我们为什么这么取舍：

    ``User-Agent``
        只含工具名与用途，**无邮箱 / 无 GitHub / 无本机路径**（见模块顶部说明）。
    ``Accept`` / ``Accept-Language``
        功能必需，且值保持通用（不暴露系统语言细节到可区分粒度）。
    ``Accept-Encoding``
        显式指定 gzip，避免 ``urllib`` 默认发 ``identity`` 让部分站点据此
        推断客户端能力；同时减小传输量。
    **不发** ``Referer``
        Referer 会泄露「你从哪个页面跳过来」。抓文献是**我们主动访问**，
        没有真实的来源页可报，发一个编造的比不发更糟 —— 直接不发。
    **不发** ``Origin``
        仅 CORS 场景需要，服务端抓取无意义。
    **不发** ``Cookie`` / ``Authorization``
        永不使用任何登录态或会话 Cookie。每次请求都是独立无状态请求，
        对方拿不到可用于关联两次请求的会话标识。
    **不发** ``X-Forwarded-For`` / ``X-Real-IP``
        不主动泄露本机 IP 链路信息（反被用来伪造会更糟）。
    **不发** ``sec-ch-ua`` 等浏览器指纹头
        我们不是浏览器，不需要伪造浏览器特征。
    """
    return {
        "User-Agent": USER_AGENT,
        "Accept": accept or "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
        "Accept-Language": "en,zh;q=0.8",
        "Accept-Encoding": "gzip, identity",
        # Connection 交给 urllib 默认处理，显式声明反而可能暴露客户端特征
    }


def _capabilities_privacy() -> Dict[str, Any]:
    """隐私/追踪向量审计 —— 如实报告每一类当前的处理状态。

    为什么要做这个：用户问「能不能反追踪」，最负责任的回答不是一句
    「能」或「不能」，而是**逐条说明哪些挡住了、哪些挡不住、
    要挡住得靠什么**。含糊其辞会让用户以为已经匿名了 —— 那更危险。
    """
    return {
        "http_layer": {
            "title": "HTTP 层身份泄露（代码可控）",
            "blocked": [
                ("User-Agent 不含邮箱 / GitHub / 本机路径",
                 f"当前 UA：{_ua_summary()}"),
                ("不发送 Referer（不泄露从哪个页面来）", "已省略"),
                ("不发送 Origin（非 CORS 场景无意义）", "已省略"),
                ("不使用 Cookie / 登录态（跨请求无法关联）", "每次请求独立无状态"),
                ("不发送 sec-ch-ua 等浏览器指纹头", "我们不是浏览器，不伪造特征"),
                ("不主动发送 X-Forwarded-For", "不泄露本机 IP 链路"),
                ("本地缓存 URL 脱敏（去 query / userinfo）", "不在磁盘留完整访问清单"),
            ],
        },
        "network_layer": {
            "title": "网络层身份（代码控不了）",
            "reality": (
                "服务器在 TCP 层就能看到你的出口 IP 和 ASN。改请求头、换 UA、"
                "改指纹都改变不了这一点 —— 这是物理事实。"
            ),
            "options": [
                ("Tor", "系统级流量匿名，是目前唯一能真正隐藏出口 IP 的免费手段。"
                        "urllib 原生支持 SOCKS 代理，配 MATLENS_WEB_PROXY 即可。"),
                ("VPN", "隐藏家宽 IP，但 VPN 服务商仍能看到你的连接。"),
                ("自建 / 单位代理", "校园网场景下可控性最好。"),
            ],
            "warning": (
                "即便用 Tor 也**不是绝对匿名**：全局被动监听者、以及你访问的"
                "目标站点自身，仍可通过请求关联与时间线做推断。"
                "对科研抓取而言 Tor 的实际价值是「不让出版商积累你的阅读画像」。"
            ),
        },
        "stealth_clarification": {
            "title": "关于 crawl4ai 的 stealth / undetected 模式",
            "what_it_does": (
                "它解决的是**「不让网站发现我是机器人」** —— 即向站点隐藏自动化身份、"
                "绕过站点的反爬检测。"
            ),
            "why_not_here": [
                "方向相反：那是「对站点隐藏我们是爬虫」，"
                "而反追踪要的是「对站点隐藏我们是谁」。目标站点看到 UA 是 MatLens "
                "或看到 UA 是 Chrome，对我们身份的保护力度是一样的。",
                "不解决 IP 问题：stealth 换了指纹，服务器照样看到你的 IP。",
                "可能**加重**指纹：用真实浏览器指纹却不做 JS 执行、不产生 cookie、"
                "请求间隔规律 —— 这种「像人又不像人」的组合反而更异常。",
                "用途是规避站点的反爬措施，属于我明确不做的范围。",
            ],
        },
        "honest_bottom_line": (
            "代码能消除「可关联的痕迹」（HTTP 层身份、会话、磁盘记录），"
            "这是本模块做到的。要隐藏 IP 必须走网络层（Tor / VPN / 代理），"
            "没有任何代码能替代。所以「黑客也无法追踪」这个承诺，"
            "我不会给 —— 给了就是不负责任。"
        ),
    }


def _ua_summary() -> str:
    """UA 泄露自检：不该出现的标识一律判为不合格。"""
    ua = USER_AGENT
    leaks = []
    if "@" in ua:
        leaks.append("含邮箱")
    if "http://" in ua or "https://" in ua:
        leaks.append("含网址")
    if re.search(r"[A-Za-z]:\\|/Users/|/home/", ua):
        leaks.append("含本机路径")
    return ua if not leaks else f"{ua}  ⚠️{'/'.join(leaks)}"


def privacy_report() -> Dict[str, Any]:
    """对外的隐私审计报告（/api/web/privacy）。"""
    rep = _capabilities_privacy()
    rep["ua_leak_free"] = "⚠️" not in _ua_summary()
    rep["user_agent"] = _ua_summary()
    proxy = _configured_proxy()
    kind = _proxy_kind(proxy) if proxy else ""
    rep["proxy"] = {
        "configured": bool(proxy),
        "scheme": kind,
        "supported": kind in ("http", "https", "socks5", "socks5h", "socks4", "socks4a"),
        "dns_via_proxy": kind in ("socks5h", "socks4a"),
        "note": (
            f"已配置 {kind} 代理（目标站点看到的是代理出口 IP，不是你的本机 IP）"
            if proxy else
            "未配置代理：目标站点看到的是你的本机出口 IP。"
            "如需隐藏 IP，请设置 MATLENS_WEB_PROXY（支持 socks5:// 与 http://）。"
        ),
        "howto": {
            "tor": "装 Tor 后：export MATLENS_WEB_PROXY=socks5h://127.0.0.1:9150"
                    "（用 socks5h 而非 socks5，避免 DNS 查询走本地泄露真实域名）",
            "tor_legacy": "若 Tor 用默认端口：socks5h://127.0.0.1:9050",
            "http_proxy": "export MATLENS_WEB_PROXY=http://127.0.0.1:8080",
            "vpn": "开 VPN 即可，无需改配置（系统级路由）",
        },
        "verify": "调 GET /api/web/proxy-check 可实测出口 IP 是否真的改变",
    }
    return rep


#: 用于探测出口 IP 的公共服务（只取 IP，不取内容）
_IP_ECHO = ("https://api.ipify.org?format=json",
            "https://api.ip.sb/ip")


def check_proxy(explicit_proxy: str = "", timeout: float = 12.0) -> Dict[str, Any]:
    """实测当前出口 IP —— 让「反追踪是否生效」变成可验证的事实。

    为什么必须有这个：反追踪最大的风险是**以为自己被保护了**。
    配置写错、协议不被支持、代理没启动 —— 这些都会让请求照常直连，
    而界面看上去一切正常。这里对比「直连 IP」与「经代理 IP」，
    两者不同才说明保护真的生效。

    只访问返回纯 IP 的探测服务，不抓任何网页内容。
    """
    proxy = (explicit_proxy or _configured_proxy()).strip()
    out: Dict[str, Any] = {
        "proxy_configured": bool(proxy),
        "proxy_masked": _mask_proxy(proxy) if proxy else "",
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if proxy:
        kind = _proxy_kind(proxy)
        out["scheme"] = kind
        if kind not in ("http", "https", "socks5", "socks5h", "socks4", "socks4a"):
            out["ok"] = False
            out["error"] = f"不支持的代理协议（{proxy.split('://')[0] if '://' in proxy else proxy}）"
            out["advice"] = "请使用 socks5:// / socks5h:// / http:// 形式"
            return out
        out["dns_via_proxy"] = kind in ("socks5h", "socks4a")

    # 1) 直连出口
    direct = _probe_ip(proxy="", timeout=timeout)
    out["direct_ip"] = direct.get("ip", "")

    # 2) 经代理出口
    if proxy:
        via = _probe_ip(proxy=proxy, timeout=timeout)
        out["proxy_ip"] = via.get("ip", "")
        if not via.get("ok"):
            out["ok"] = False
            out["error"] = via.get("error") or "代理连接失败"
            out["advice"] = (
                "代理不可用。常见原因：代理程序没启动 / 端口不对 / 需要认证。"
                "MatLens 不会在代理失败时静默改成直连——那会让你以为已匿名、实际裸奔。"
            )
            return out
        out["ok"] = True
        out["protected"] = bool(out["direct_ip"] and out["proxy_ip"]
                                and out["direct_ip"] != out["proxy_ip"])
        out["verdict"] = (
            "出口 IP 已改变，保护生效" if out["protected"]
            else "⚠️ 出口 IP 与直连相同，代理未实际生效，你仍在裸奔"
        )
        if not out["protected"]:
            out["advice"] = ("检查代理是否在运行、端口是否正确；"
                             "部分代理会拒绝 CONNECT 隧道而回落到直连。")
    else:
        out["ok"] = True
        out["protected"] = False
        out["verdict"] = "未配置代理，目标站点看到的是你的本机出口 IP"
    return out


def _mask_proxy(proxy: str) -> str:
    """代理地址脱敏（去掉可能的用户名密码）。"""
    try:
        p = urllib.parse.urlsplit(proxy)
        if p.username or p.password:
            host = p.hostname or ""
            if p.port:
                host = f"{host}:{p.port}"
            return f"{p.scheme}://***:***@{host}"
    except Exception:
        pass
    return proxy.split("@")[-1] if "@" in proxy else proxy


def _probe_ip(proxy: str, timeout: float = 12.0) -> Dict[str, Any]:
    """通过（或不通过）代理探测出口 IP。只请求 IP 回显服务。"""
    opener = None
    if proxy:
        try:
            opener = _build_opener(proxy)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:160]}
    last = "所有探测端点均失败"
    for url in _IP_ECHO:
        try:
            req = urllib.request.Request(url, headers=_minimal_headers("application/json,*/*"))
            open_target = opener.open if opener else urllib.request.urlopen
            with open_target(req, timeout=timeout) as r:
                raw = r.read(2048).decode("utf-8", "replace").strip()
            ip = ""
            if raw.startswith("{"):
                import json as _j
                ip = (_j.loads(raw).get("ip") or "").strip()
            else:
                ip = raw
            if ip:
                return {"ok": True, "ip": ip}
            last = "探测服务返回空内容"
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"[:160]
            continue
    return {"ok": False, "error": last}


def _configured_proxy() -> str:
    """当前应使用的代理。

    优先级：proxy_manager（设置页 / 环境变量）> 环境变量 MATLENS_WEB_PROXY。
    代理不可用时**不会静默直连** —— 见 _build_opener。
    """
    try:
        from matlens_kit.web import proxy_manager

        return proxy_manager.effective_proxy()
    except Exception:
        return (os.environ.get("MATLENS_WEB_PROXY") or "").strip()


def _auto_rotate_if_due() -> Optional[Dict[str, Any]]:
    """抓取前按需自动换 IP（依赖 Tor NEWNYM）。

    未启用自动轮换时直接返回 None，不产生任何额外开销。
    """
    try:
        from matlens_kit.web import proxy_manager

        proxy_manager.note_request()
        res = proxy_manager.maybe_rotate()
        if res and not res.get("ok") and res.get("skipped"):
            pass  # 间隔未到是正常现象，静默
        return res
    except Exception:
        return None


def _proxy_kind(url: str) -> str:
    """识别代理协议：http / https / socks5 / socks5h / socks4 / socks4a。"""
    try:
        scheme = (urllib.parse.urlsplit(url).scheme or "").lower()
    except Exception:
        return ""
    if scheme in ("socks5h", "socks5", "socks4a", "socks4"):
        return scheme
    if scheme in ("http", "https"):
        return scheme
    return ""


def _build_opener(proxy: str = "") -> Optional[urllib.request.OpenerDirector]:
    """按需构造带代理的 opener。

    ⚠️ 这里修掉了一个**严重安全问题**（2026-10-15）：
    ``urllib.request.ProxyHandler`` 的键**只有 http / https**，
    传 ``socks5://127.0.0.1:9050`` 会被它当作未知协议**静默忽略**，
    于是 opener 照常直连 —— 用户以为配好了 Tor，实际仍在裸奔，
    且没有任何报错。这是最危险的一类 bug：保护措施看起来生效了。

    现在的行为：
    - socks5/socks5h/socks4 → 走 PySocks（正确实现）
    - 缺少 PySocks 或配置非法 → **显式抛异常，绝不静默直连**
    - http/https → urllib 原生 ProxyHandler

    同时保证**不启用 HTTPCookieProcessor** —— 这是最关键的一行：
    一旦装了 cookie 处理，站点种下的 Cookie 会被保留并在下一次请求带回，
    跨请求关联立刻成立，等于我们主动帮对方建立追踪档案。
    """
    proxy = (proxy or "").strip()
    if not proxy:
        return None

    kind = _proxy_kind(proxy)
    if not kind:
        raise ValueError(
            f"无法识别的代理协议：{proxy.split('://')[0] if '://' in proxy else proxy!r}。"
            "支持 socks5:// / socks5h:// / socks4:// / http:// / https://"
        )

    if kind.startswith("socks"):
        _ensure_vendor_on_path()
        try:
            import socks
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                f"配置了 {kind} 代理但缺少 PySocks 库，无法建立 SOCKS 通道。"
                "为保护你的隐私，这里**直接失败**而不是静默改成直连——"
                "否则你会以为已匿名、实际却在裸奔。"
                "请安装：pip install PySocks"
            ) from e

        # socks5h = 由代理端做 DNS 解析，避免本地 DNS 泄露真实查询的域名
        rdns = kind in ("socks5h", "socks4a")
        parts = urllib.parse.urlsplit(proxy if "//" in proxy else f"//{proxy}")
        phost = parts.hostname or ""
        pport = parts.port or (1080 if kind.startswith("socks5") else 1080)
        # 代理自身若带认证（socks5h://user:pass@host:9050），一并带上
        puser = parts.username or ""
        ppass = parts.password or ""
        if not phost:
            raise ValueError(f"代理地址缺少主机名：{_mask_proxy(proxy)}")

        class _SocksOpener(urllib.request.OpenerDirector):
            """经 SOCKS 代理访问。

            实现方式：用 PySocks 的 create_connection 建立隧道，
            再把 socket 塞进 http.client。**不用** sockshandler ——
            它绑死了 httplib 版本，且对 https 的处理要靠 SocksiPyConnectionS，
            跨版本容易踩坑（实测其构造签名随 PySocks 版本变化）。
            自己拼 http.client 反而稳定可控。
            """

            def open(self, fullurl, data=None, timeout=DEFAULT_TIMEOUT):
                import http.client
                import ssl

                url = fullurl if isinstance(fullurl, str) else fullurl.full_url
                headers = dict(getattr(fullurl, "headers", None) or {})
                p = urllib.parse.urlsplit(url)
                host = p.hostname
                port = p.port or (443 if p.scheme == "https" else 80)
                if not host:
                    return urllib.request.OpenerDirector.open(self, fullurl, data, timeout)

                # 关键：连接目标 host:port 时经代理转发
                sock = socks.create_connection(
                    (host, port), timeout=timeout,
                    proxy_type=socks.PROXY_TYPE_SOCKS5 if kind.startswith("socks5")
                               else socks.PROXY_TYPE_SOCKS4,
                    proxy_addr=phost, proxy_port=pport, proxy_rdns=rdns,
                    proxy_username=puser or None, proxy_password=ppass or None)

                if p.scheme == "https":
                    ctx = ssl.create_default_context()
                    conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)
                else:
                    conn = http.client.HTTPConnection(host, port, timeout=timeout)
                conn.sock = sock
                path = p.path or "/"
                if p.query:
                    path += "?" + p.query
                conn.request("GET", path, body=data, headers=headers)
                resp = conn.getresponse()
                raw = resp.read()
                status, reason = resp.status, resp.reason
                ctype = resp.getheader("Content-Type") or ""
                headers_out = resp.getheaders()
                try:
                    conn.close()
                except Exception:
                    pass

                # 包成 urllib 的可读对象，保持与 urlopen 一致的调用契约
                class _R:
                    headers = _HeadersShim(headers_out)

                    def read(self, amt=None):
                        return raw if amt is None else raw[:amt]

                    def info(self):
                        return self.headers

                    def getcode(self):
                        return status

                    def geturl(self):
                        return url

                    def __enter__(self):
                        return self

                    def __exit__(self, *a):
                        return False
                _R.status = status          # type: ignore[attr-defined]
                _R.reason = reason          # type: ignore[attr-defined]
                _R.ctype = ctype            # type: ignore[attr-defined]
                return _R

        return _SocksOpener()

    handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    # 注意：**不**加入 HTTPCookieProcessor
    return urllib.request.build_opener(handler)


class _HeadersShim(dict):
    """把 list[(k, v)] 包成 email.Message 风格，让 resp.getheader 可用。"""

    def __init__(self, pairs):
        super().__init__({k.lower(): v for k, v in pairs})
        self._pairs = list(pairs)

    def getheader(self, name, default=None):
        k = name.lower()
        for kk, vv in self._pairs:
            if kk.lower() == k:
                return vv
        return default


def _http_get(url: str, timeout: float = DEFAULT_TIMEOUT,
              accept: Optional[str] = None) -> Tuple[int, str, str]:
    """GET 一个 URL，返回 (status, content_type, text)。非 200 抛 HTTPError。"""
    headers = _minimal_headers(accept)
    req = urllib.request.Request(url, headers=headers)
    opener = _build_opener(_configured_proxy())
    open_target = opener.open if opener else urllib.request.urlopen
    with open_target(req, timeout=timeout) as r:
        ctype = (r.headers.get("Content-Type") or "").lower()
        data = r.read(MAX_HTML_BYTES)
        # 编码嗅探：学术站点常见 iso-8859-1 误标
        enc = "utf-8"
        m = re.search(r"charset=([\w\-]+)", ctype)
        if m:
            enc = m.group(1)
        try:
            text = data.decode(enc, "replace")
        except LookupError:
            text = data.decode("utf-8", "replace")
        return r.status, ctype, text


# ────────────────────────────────────────────────────────────
# 正文抽取（L2 trafilatura → L1 内置规则）
# ────────────────────────────────────────────────────────────
def _ensure_vendor_on_path() -> None:
    """把项目内 vendor/pylibs 加入 sys.path。

    为什么需要：本项目运行时（D:/MatLens/.venv 内嵌 Python、WorkBuddy 环境）
    常常无法直接 pip 安装到 site-packages（pip 覆盖文件会被安全守卫拦下），
    因此增强依赖统一装到 ``D:/MatLens/vendor/pylibs``，这里主动挂上。
    目录不存在时静默跳过 —— L1 零依赖路径永远可用。
    """
    try:
        if any("vendor/pylibs" in (p or "") for p in sys.path):
            return
        import pathlib
        vendor = pathlib.Path(__file__).resolve().parents[2] / "vendor" / "pylibs"
        if vendor.is_dir():
            sys.path.insert(0, str(vendor))
    except Exception:
        pass


def _has_trafilatura() -> bool:
    _ensure_vendor_on_path()
    try:
        import trafilatura  # noqa: F401
        return True
    except Exception:
        return False


def _has_crawl4ai() -> bool:
    _ensure_vendor_on_path()
    try:
        import crawl4ai  # noqa: F401
        return True
    except Exception:
        return False


_SCRIPT_STYLE_RE = re.compile(r"<(script|style|nav|footer|header|aside|noscript|svg|form)[^>]*>.*?</\1>",
                              re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_NL_RE = re.compile(r"\n{3,}")


def _html_to_text(html: str) -> str:
    """降级抽取：粗粒度去标签保文本（trafilatura 不可用时）。"""
    if not html:
        return ""
    s = _SCRIPT_STYLE_RE.sub(" ", html)
    # 段落/换行语义
    s = re.sub(r"<(br|/p|/div|/li|/h[1-6]|/tr)[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<li[^>]*>", "- ", s, flags=re.I)
    s = _TAG_RE.sub(" ", s)
    s = (s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
          .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
          .replace("&mdash;", "—").replace("&ndash;", "–"))
    s = _WS_RE.sub(" ", s)
    s = _NL_RE.sub("\n\n", s)
    return s.strip()


def extract_text(html: str, url: str = "") -> Tuple[str, str]:
    """抽取正文。返回 (text, engine)。engine 标明实际用了哪条路径。

    有 trafilatura 就用（去噪保真最好），否则退回内置规则。
    """
    if _has_trafilatura():
        try:
            import trafilatura
            text = trafilatura.extract(
                html, url=url or None, output_format="txt",
                include_comments=False, include_tables=True, favor_precision=True)
            if text and len(text) > 200:
                return text[:MAX_TEXT_CHARS], "trafilatura"
        except Exception:
            pass
    return _html_to_text(html)[:MAX_TEXT_CHARS], "builtin-lxml"


# ────────────────────────────────────────────────────────────
# 元数据抽取
# ────────────────────────────────────────────────────────────
def extract_meta(html: str) -> Dict[str, Any]:
    """抽取页面元数据：标题、作者、DOI、期刊、摘要、PDF 链接。

    学术页面高度标准化（citation_* meta 标签几乎所有出版商都有），
    这套规则对材料类期刊命中率很高。
    """
    meta: Dict[str, Any] = {}
    if not html:
        return meta

    def _get(*names: str) -> str:
        for n in names:
            m = re.search(
                r'<meta[^>]+(?:name|property)=["\']' + re.escape(n) + r'["\'][^>]*content=["\']([^"\']*)["\']',
                html, re.I)
            if m and m.group(1).strip():
                return m.group(1).strip()
            m = re.search(
                r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:name|property)=["\']' + re.escape(n) + r'["\']',
                html, re.I)
            if m and m.group(1).strip():
                return m.group(1).strip()
        return ""

    meta["title"] = _get("citation_title", "dc.title", "og:title", "title")
    meta["doi"] = _get("citation_doi", "dc.identifier", "dc.doi")
    meta["journal"] = _get("citation_journal_title", "prism.publicationName")
    meta["date"] = _get("citation_publication_date", "citation_date", "dc.date")
    meta["volume"] = _get("citation_volume")
    meta["issue"] = _get("citation_issue")
    meta["firstpage"] = _get("citation_firstpage")
    meta["abstract"] = _get("citation_abstract", "dc.description", "og:description", "description")
    meta["pdf_url"] = _get("citation_pdf_url", "eprints.document_url")

    # 作者：citation_author 可以出现多次
    authors = re.findall(
        r'<meta[^>]+name=["\']citation_author["\'][^>]*content=["\']([^"\']+)["\']', html, re.I)
    if not authors:
        one = _get("dc.creator", "author")
        authors = [one] if one else []
    meta["authors"] = [a.strip() for a in authors if a.strip()]

    if not meta["title"]:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        if m:
            meta["title"] = _WS_RE.sub(" ", _TAG_RE.sub("", m.group(1))).strip()[:300]

    # 去掉可能存在的 doi 前缀 URL 形式
    if meta["doi"]:
        meta["doi"] = re.sub(r"^https?://(dx\.)?doi\.org/", "", meta["doi"], flags=re.I).strip()

    meta = {k: v for k, v in meta.items() if v}
    return meta


# ────────────────────────────────────────────────────────────
# 主入口：抓单个 URL
# ────────────────────────────────────────────────────────────
def _host_of(url: str) -> str:
    """取 URL 的 host（去端口，小写）。用于「是否换了站点」判断。"""
    try:
        return (urllib.parse.urlsplit(url or "").netloc or "").split(":")[0].lower()
    except Exception:
        return ""


def _doi_from_url(url: str) -> str:
    """从 URL 里抠出 DOI（403/无正文时的 OA 降级入口）。

    覆盖出版商常见形态：
      https://doi.org/10.1149/1.1837395
      https://iopscience.iop.org/article/10.1149/1.1837395
      https://www.nature.com/articles/s41560-023-01321-7  → 10.1038/s41560-023-01321-7
    Nature/Cell 这类用 sXXXX 编号，需配前缀映射；无法确定前缀时返回空串
    （宁可不降级，也别用错误 DOI 查到错误文献）。
    """
    try:
        u = url or ""
    except Exception:
        return ""
    m = re.search(r"10\.\d{4,9}/[^\s\"'<>?&]+", u, re.I)
    if m:
        return m.group(0).rstrip(".,;)")
    m = re.search(r"/articles/([a-z]?\d{4,5}(?:-\d{1,5}){2,3})", u, re.I)
    if m:
        return "10.1038/" + m.group(1)
    return ""


def _try_oa_fallback(res: FetchResult, doi: str) -> None:
    """抓不到正文时，按 DOI 找合法开放获取版本并重试一次。

    为什么需要（实测数据支撑）：
    - IOP（iopscience.iop.org）整站 302 跳 ``validate.perfdrive.com`` 反爬页，
      **连 doi.org 跳转也一样**，正文永远抽不到。
    - 但 Unpaywall 实测能给出 arXiv 预印本：``10.1039/C4CP00856A`` →
      ``https://arxiv.org/pdf/1404.3036``，正文 1621 字可用。

    ⚠️ 两个诚实的边界：
    1. 只用**合法** OA 版本（作者自存/机构知识库/预印本），不碰付费墙。
    2. Unpaywall 返回的 bronze 版本可能仍在出版商域名上（实测 IOP 那条就是），
       此时重试仍会失败 —— **如实报告**，不假装成功。
    """
    if not doi:
        return
    try:
        from matlens_kit.rag.scholarly import fetch_unpaywall
    except Exception:
        return
    try:
        oa = fetch_unpaywall(doi, timeout=15.0)
    except Exception as e:  # noqa: BLE001
        res["oa_fallback_error"] = f"Unpaywall 查询失败：{type(e).__name__}"[:120]
        return

    res["oa_fallback"] = {
        "is_oa": oa.get("is_oa"),
        "status": oa.get("oa_status", ""),
        "tried_url": _mask_url(oa.get("oa_url") or ""),
    }
    if not oa.get("is_oa") or not oa.get("oa_url"):
        res["oa_fallback_error"] = "该文献没有合法开放获取版本（closed/bronze 不含可直取全文）"
        return

    # 别在同一个被封的域上重试 —— bronze 版常仍指向出版商自身，换路径也没用。
    # 注意比**域名**而非完整 URL：Unpaywall 常给同域的 /pdf 后缀链接，
    # 若按完整 URL 比较会误判为「换了目标」而白跑一次（实测 IOP 即如此，
    # 会真的去请求那个被 robots 禁止的域）。
    original = _host_of(res.get("url") or "")
    target = oa["oa_url"]
    if original and original == _host_of(target):
        res["oa_fallback_error"] = (
            f"Unpaywall 给的是 {oa.get('oa_status')} 版本，但仍在原站点"
            f"（{oa.get('oa_status')} 通常意味着只开放阅读、不提供可直取全文），"
            "换域名才有意义")
        return

    # 真正重试一次
    try:
        status, ctype, _body = _http_get(target, timeout=DEFAULT_TIMEOUT,
                                         accept="application/pdf,text/html,*/*")
    except Exception as e:  # noqa: BLE001
        res["oa_fallback_error"] = f"OA 版本抓取失败：{type(e).__name__}"[:120]
        return

    res2: Dict[str, Any] = {}
    if "pdf" in (ctype or "") or target.lower().endswith(".pdf"):
        res2 = _handle_pdf(target, timeout=DEFAULT_TIMEOUT)
    else:
        r2 = fetch(target, with_text=True, timeout=DEFAULT_TIMEOUT,
                   oa_fallback=False)   # 只降级一层，避免无限递归
        res2 = dict(r2)
        if res2.get("ok"):
            res2["status"] = r2.get("status", status)
    if res2.get("text"):
        res["ok"] = True
        res["status"] = res2.get("status", 200)
        res["content_type"] = res2.get("content_type", "")
        res["text"] = res2.get("text")
        res["text_chars"] = res2.get("text_chars", len(res2.get("text", "")))
        res["engine"] = "oa-fallback:" + str(res2.get("engine", ""))
        res["resolved_via"] = "Unpaywall OA 版本"
        res.pop("notes", None)
        res.pop("oa_fallback_error", None)
        # 元数据仍以原页面为准，只补 PDF 直链
        if res2.get("pdf_url") and not res.get("pdf_url"):
            res["pdf_url"] = res2["pdf_url"]
    else:
        res["oa_fallback_error"] = "OA 版本同样抓不到正文（可能仍需浏览器或已下架）"


def fetch(url: str, with_text: bool = True, timeout: float = DEFAULT_TIMEOUT,
          check_robots: bool = True, check_blocked: bool = True,
          oa_fallback: bool = True) -> FetchResult:
    """抓取单个 URL，返回结构化结果。

    返回::

        {
          "ok": True,
          "url": "...", "final_url": "...",
          "status": 200,
          "content_type": "text/html",
          "title": "...", "authors": [...], "doi": "...", "journal": "...",
          "abstract": "...", "pdf_url": "...",
          "text": "正文…",            # with_text=True 且非 PDF 时
          "engine": "trafilatura",
          "elapsed_ms": 812,
          "robots": "robots.txt 允许",
          "notes": [...]
        }

    失败时 ``ok=False`` + ``reason``（不给 traceback 给用户看）。
    """
    t0 = time.time()
    res = FetchResult(ok=False, url=url, fetched_at=time.strftime("%Y-%m-%d %H:%M:%S"))

    if not url or not str(url).strip():
        res["reason"] = "URL 为空"
        return res
    url = str(url).strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
        res["url"] = url

    # ── 合规检查 1：站点禁止名单（优先级最高，先于 robots）──
    if check_blocked:
        allowed, why = _check_blocked(url)
        res["blocked_policy"] = why
        if not allowed:
            res["reason"] = why
            res["elapsed_ms"] = int((time.time() - t0) * 1000)
            res["note_policy"] = "该站点在 MatLens 明令禁止名单内，不提供任何绕过方式"
            return res
    # ── 合规检查 2：robots.txt ──
    if check_robots:
        allowed, why = _robots_allows(url)
        res["robots"] = why
        if not allowed:
            res["reason"] = why
            # 2026-10-16：robots 拒绝时，仍尝试一次 Unpaywall OA 降级。
            # 这**不是绕过 robots** —— 我们不再请求该站点，而是转向作者自存的
            # 合法开放版本（通常在 arXiv / 机构知识库）。这些目标域各自的
            # robots 会在递归 fetch 里正常接受检查。
            # 关闭名单（上一段）**不**走这条路：那是服务条款层面的禁止，
            # 连找替代版都不合适。
            if oa_fallback:
                doi0 = _doi_from_url(url)
                if doi0:
                    _try_oa_fallback(res, doi0)
                    if res.get("text"):
                        res["ok"] = True
                        res["elapsed_ms"] = int((time.time() - t0) * 1000)
                        res["note_policy"] = (
                            "原站点 robots 禁止抓取，已改用 Unpaywall 解析到的"
                            "合法开放获取版本（作者自存 / 预印本）")
                        return res
            res["elapsed_ms"] = int((time.time() - t0) * 1000)
            res["note_policy"] = "MatLens 遵守 robots.txt，不抓取被禁止的路径"
            return res

    # ── 自动换 IP（按设置页的定时/计数条件，仅 Tor 有效）──
    rot = _auto_rotate_if_due()
    if rot and not rot.get("skipped"):
        res["ip_rotated"] = bool(rot.get("ok"))
        if rot.get("ok"):
            res["ip_rotate_note"] = rot.get("note", "")
        else:
            res["ip_rotate_error"] = rot.get("reason") or rot.get("advice") or "自动换 IP 未成功"

    # ── 限速 ──
    host = urllib.parse.urlsplit(url).netloc
    waited = _RATE.wait(host)
    if waited > 0.05:
        res["rate_limit_wait_ms"] = int(waited * 1000)

    # ── 抓取 ──
    try:
        status, ctype, body = _http_get(url, timeout=timeout)
    except urllib.error.HTTPError as e:
        res["status"] = e.code
        res["reason"] = f"HTTP {e.code} {e.reason or ''}".strip()
        res["elapsed_ms"] = int((time.time() - t0) * 1000)
        if e.code in (401, 403):
            res["reason"] = f"HTTP {e.code}：站点拒绝访问（可能需要机构订阅或触发反爬）"
            res["note_policy"] = "MatLens 不绕过访问控制；请通过机构订阅或开放获取渠道获取"
            # 2026-10-16：URL 里若含 DOI，尝试 Unpaywall 找合法 OA 版本
            if oa_fallback:
                doi = _doi_from_url(url)
                if doi:
                    _try_oa_fallback(res, doi)
        return res
    except urllib.error.URLError as e:
        res["reason"] = f"网络错误：{e.reason}"
        res["elapsed_ms"] = int((time.time() - t0) * 1000)
        return res
    except Exception as e:  # noqa: BLE001
        res["reason"] = f"{type(e).__name__}: {e}"
        res["elapsed_ms"] = int((time.time() - t0) * 1000)
        return res

    res["ok"] = True
    res["status"] = status
    res["content_type"] = ctype

    # ── PDF：走 pymupdf 抽文本（项目已装）──
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        res.update(_handle_pdf(url, timeout=timeout))
        res["elapsed_ms"] = int((time.time() - t0) * 1000)
        return res

    if not with_text:
        res["elapsed_ms"] = int((time.time() - t0) * 1000)
        return res

    meta = extract_meta(body)
    text, engine = extract_text(body, url=url)
    res.update(meta)
    res["text"] = text
    res["text_chars"] = len(text)
    res["engine"] = engine
    if not text:
        res["notes"] = (res.get("notes") or []) + [
            "未抽取出正文：可能页面为纯 JS 渲染（需 crawl4ai）或正文在付费墙后"]
        # 2026-10-16：空正文时也走一次 OA 降级 —— 出版商页面常见「标题能读、
        # 正文被挡」，此时 DOI 往往就在页面里（已由 extract_meta 抓到）。
        if oa_fallback:
            doi = res.get("doi") or _doi_from_url(url)
            if doi:
                _try_oa_fallback(res, doi)
    res["elapsed_ms"] = int((time.time() - t0) * 1000)
    return res


def _handle_pdf(url: str, timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """下载并解析 PDF（优先 pymupdf，降级 pdfplumber）。"""
    out: Dict[str, Any] = {}
    try:
        # 同样走最小化请求头 + 同一代理配置：PDF 分支早期版本自己造 Request
        # 并只带 UA，既漏掉 Accept-Encoding，也绕过了统一的代理与隐私管控。
        req = urllib.request.Request(url, headers=_minimal_headers("application/pdf,*/*"))
        opener = _build_opener(_configured_proxy())
        open_target = opener.open if opener else urllib.request.urlopen
        with open_target(req, timeout=timeout) as r:
            data = r.read(MAX_HTML_BYTES)
        out["pdf_bytes"] = len(data)
    except Exception as e:  # noqa: BLE001
        out["ok"] = False
        out["reason"] = f"PDF 下载失败：{e}"
        return out

    text = ""
    try:
        import fitz  # pymupdf
        doc = fitz.open(stream=data, filetype="pdf")
        parts = []
        for pg in doc:
            parts.append(pg.get_text())
            if len("".join(parts)) > MAX_TEXT_CHARS:
                break
        doc.close()
        text = "\n".join(parts)[:MAX_TEXT_CHARS]
        out["engine"] = "pymupdf"
    except Exception:
        try:
            import io
            import pdfplumber
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                text = "\n".join((p.extract_text() or "") for p in pdf.pages[:200])
            text = text[:MAX_TEXT_CHARS]
            out["engine"] = "pdfplumber"
        except Exception as e:  # noqa: BLE001
            out["ok"] = False
            out["reason"] = f"PDF 解析失败（需 pymupdf 或 pdfplumber）：{e}"
            return out

    out["ok"] = True
    out["content_type"] = "application/pdf"
    out["text"] = text
    out["text_chars"] = len(text)
    out["is_pdf"] = True
    return out


# ────────────────────────────────────────────────────────────
# 批量抓取（并发 + 单页限速）
# ────────────────────────────────────────────────────────────
def fetch_many(urls: List[str], with_text: bool = True,
               timeout: float = DEFAULT_TIMEOUT, max_workers: int = MAX_CONCURRENCY,
               check_robots: bool = True, check_blocked: bool = True) -> List[FetchResult]:
    """并发抓多个 URL。同域请求仍被 _RateLimiter 串行化，
    不同域之间最多 max_workers 并发。
    """
    urls = [u for u in (urls or []) if u]
    if not urls:
        return []
    out: List[FetchResult] = [None] * len(urls)  # type: ignore[list-item]
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, min(max_workers, MAX_CONCURRENCY))) as ex:
        futs = {ex.submit(fetch, u, with_text, timeout, check_robots, check_blocked): i
                for i, u in enumerate(urls)}
        for fut in concurrent.futures.as_completed(futs):
            i = futs[fut]
            try:
                out[i] = fut.result()
            except Exception as e:  # noqa: BLE001
                out[i] = FetchResult(ok=False, url=urls[i],
                                     reason=f"{type(e).__name__}: {e}")
    return out


# ────────────────────────────────────────────────────────────
# 能力自检（UI 要如实告诉用户当前环境能做到什么）
# ────────────────────────────────────────────────────────────
def capabilities() -> Dict[str, Any]:
    """报告当前环境的抓取能力（诚实标注哪些增强可用）。"""
    tf = _has_trafilatura()
    c4 = _has_crawl4ai()
    try:
        import pymupdf  # noqa: F401
        pdf_ok = True
    except Exception:
        try:
            import pdfplumber  # noqa: F401
            pdf_ok = True
        except Exception:
            pdf_ok = False
    return {
        "l1_http": True,
        "l1_engine": "httpx/urllib + 内置 lxml 规则",
        "trafilatura": tf,
        "crawl4ai": c4,
        "pdf_parse": pdf_ok,
        "tier": "L3 全量（动态渲染）" if c4 else ("L2 正文抽取" if tf else "L1 基础抽取"),
        "tier_hint": (
            "已装 crawl4ai：可处理 JS 动态渲染页面"
            if c4 else
            "未装 crawl4ai：JS 动态渲染页面抽不到正文（静态页面不受影响）"
        ),
        "rate_limit": f"同域最小间隔 {DEFAULT_DELAY}s，单域串行，最多 {MAX_CONCURRENCY} 域并发",
        "respects_robots": True,
        "blocked_sites": len(BLOCKED_SITES),
        "privacy": {
            "ua": _ua_summary(),
            "ua_leak_free": "⚠️" not in _ua_summary(),
            "no_cookies": True,
            "no_referer": True,
            "proxy_configured": bool(_configured_proxy()),
            "summary": "HTTP 层已去关联（无 Cookie/Referer/邮箱 UA）；"
                       "IP 匿名需走代理或 Tor，详见 /api/web/privacy",
        },
        "policy": {
            "yes": [
                "公开可访问内容抓取，正文原样返回不做改写",
                "遵守 robots.txt，被 Disallow 的路径直接拒绝",
                f"知网/维普/超星/万方共 {len(BLOCKED_SITES)} 个站点明令禁止抓取",
                "不使用 Cookie 与登录态，跨请求无法被关联",
                "请求头最小化，不泄露邮箱 / 本机路径 / 访问来源页",
                "本地缓存 URL 脱敏，不留完整访问痕迹清单",
                "同域限速，避免给目标站造成压力",
            ],
            "no": list(REFUSED_TECHNIQUES),
        },
        "privacy_detail": _capabilities_privacy(),
    }


# ────────────────────────────────────────────────────────────
# 缓存（避免重复抓同一页）
# ────────────────────────────────────────────────────────────
def _cache_dir() -> str:
    from matlens_cli.config import get_matlens_home
    d = get_matlens_home() / "fetch_cache"
    os.makedirs(d, exist_ok=True)
    return str(d)


def _mask_url(url: str) -> str:
    """URL 脱敏：**移除 query、fragment 与 userinfo**。

    为什么：query 里常带追踪参数（``utm_source``、``fbclid``、会话 token、
    个性化检索参数）；userinfo 里可能直接是**用户名与密码**。把这些原样
    存进本地缓存，等于在自己的磁盘上留一份完整清单，一旦缓存目录被同步到
    云盘或被其他工具扫到，就是可关联的画像原料甚至凭据泄露。
    索引功能只需要 host+path。
    """
    try:
        p = urllib.parse.urlsplit(url)
    except Exception:
        return "[unparsable]"
    if not p.scheme or not p.netloc:
        return "[invalid]"
    # hostname 不含 userinfo；netloc 可能带，需显式剥离
    host = p.hostname or ""
    if p.port:
        host = f"{host}:{p.port}"
    return f"{p.scheme}://{host}{p.path or '/'}"


def _cache_key(url: str) -> str:
    """缓存键用**含 query 的完整 URL 哈希**，保证不同文献不串键；
    但**存到文件里的 URL 是脱敏版**。
    """
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]


def fetch_cached(url: str, max_age_h: float = 24.0, **kw) -> FetchResult:
    """带磁盘缓存的抓取。相同 URL 在 max_age_h 内不重复请求。

    对 Agent 很有用：同一批文献反复被引用时不该反复打扰目标站。
    磁盘缓存里保存的是**脱敏 URL**（去 query / 去 userinfo），避免本地
    留下完整的访问痕迹清单。
    """
    import json as _json
    key = _cache_key(url)
    path = os.path.join(_cache_dir(), key + ".json")
    if os.path.exists(path):
        try:
            age = (time.time() - os.path.getmtime(path)) / 3600.0
            if age <= max_age_h:
                with open(path, encoding="utf-8") as f:
                    data = _json.load(f)
                # 缓存里 url 是脱敏版（query 已剥）；命中时用调用方传入的
                # 真实 URL 还原，否则 ?query 形式的文献链接会抓到首页。
                real = url
                masked = data.pop("url", "")
                out = FetchResult(**data)
                out["url"] = real
                out["url_masked"] = masked
                out["cache"] = f"命中缓存（{age:.1f}h 前）"
                return out
        except Exception:
            pass
    res = fetch(url, **kw)
    try:
        stored = dict(res)
        # 落盘时把真实 URL 换成脱敏版：不在磁盘上留「我们访问过什么」的完整清单
        stored["url"] = _mask_url(url)
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(stored, f, ensure_ascii=False)
    except Exception:
        pass
    return res
