# -*- coding: utf-8 -*-
"""MatLens · 云端学术 API 聚合客户端。

为什么需要这个模块（2026-10-15）
--------------------------------
知识库页面此前只能索引**本地文件**（PDF/TXT/CSV），研究者最缺的一环是
「先联网把这批文献捞回来，再沉淀进本地库」。本模块把多个**免 key 的
开放学术 API** 收敛成一个统一入口，供 /api/kb/{name}/web-search 调用。

收录原则（不做幻觉式承诺）
--------------------------
只收录**实测无需 API Key** 的公开端点。每个源标注：
- ``key_required``：是否需要凭据
- ``coverage``：学科覆盖（材料化学研究者最关心中文/材料类是否可用）
- ``status``：运行时自检结果，由 /api/kb/sources 暴露给前端

**关于中文文献（重要）**
知网 CNKI **没有面向个人开发者开放的 API**，官方 Open API 仅限签署合作协议的
高校/科研机构/图书馆，个人无法自助申请密钥（且代申请、共享密钥属违规）。
万方有官方开放平台 api.wanfangdata.com.cn，但**按点计费**需申请 token。
维普/超星无可用接口。因此：
- 本模块**不**伪造知网端点；
- ``WANFANG_TOKEN`` 配好时可走真实万方接口，否则该源显示为「需授权」；
- 中文文献的正确路径是「知网人工检索 → 导出 Refworks/EndNote 题录 →
  解析后导入本地库」，这条路径在前端「添加文献」tab 已支持。

已在项目中验证可用的源：OpenAlex、Crossref（matlens_kit/paper/search.py
的双通道），本模块在此基础上扩展 arXiv / Semantic Scholar / Europe PMC /
PubMed / DBLP，并发检索 + 单源失败不影响整体。

统一返回结构::

    {
      "id": "10.1234/abc",
      "title": "...",
      "authors": "A, B, C",
      "year": "2024",
      "venue": "Journal of Power Sources",
      "doi": "https://doi.org/10.1234/abc",
      "url": "...",
      "oa_url": "...",        # 开放获取 PDF（可能为空）
      "abstract": "...",
      "cited_by": 42,
      "source": "openalex",   # 机器可读
      "source_label": "OpenAlex",
      "snippet": "..."        # abstract 截断，用于索引
    }
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Callable, Dict, List, Optional

_UA = {
    "User-Agent": "MatLens/0.1 (materials research agent; mailto:matlens@example.com)",
}

_DEFAULT_TIMEOUT = 15.0
_MAX_WORKERS = 7


# ---------------------------------------------------------------------------
# HTTP 工具
# ---------------------------------------------------------------------------
def _http_get(url: str, timeout: float = _DEFAULT_TIMEOUT, retries: int = 1,
              headers: Optional[Dict[str, str]] = None) -> bytes:
    """GET 原始字节（带 1 次重试）。失败抛最后一次异常。"""
    hdrs = dict(_UA)
    if headers:
        hdrs.update(headers)
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            # 4xx（除 429）重试无意义，直接抛
            last = e
            if e.code != 429:
                break
        except Exception as e:  # noqa: BLE001
            last = e
        if attempt < retries:
            import time

            time.sleep(0.8)
    assert last is not None
    raise last


#: 自检模式标志。为 True 时 ``_get_json`` **不重试** ——
#: 自检要快速反馈，重试会把 5s 超时翻倍成 10.8s（实测整体自检 25s）。
#: 真实检索仍应重试 —— 那时多花几秒换来结果更值。
_PROBE_MODE = False


def _set_probe_mode(on: bool) -> None:
    """切换自检模式（免重试）。由 source_health 模块在探测前调用。"""
    global _PROBE_MODE
    _PROBE_MODE = bool(on)


def _get_json(url: str, timeout: float = _DEFAULT_TIMEOUT, retries: int = 1,
              headers: Optional[Dict[str, str]] = None) -> Any:
    if _PROBE_MODE:
        retries = 0
    return json.loads(_http_get(url, timeout=timeout, retries=retries, headers=headers).decode("utf-8", "replace"))


def _get_text(url: str, timeout: float = _DEFAULT_TIMEOUT, retries: int = 1,
              headers: Optional[Dict[str, str]] = None) -> str:
    return _http_get(url, timeout=timeout, retries=retries, headers=headers).decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# 文本工具
# ---------------------------------------------------------------------------
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_tags(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = _TAG_RE.sub(" ", s)
    s = (s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
          .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " "))
    return _WS_RE.sub(" ", s).strip()


def _truncate(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n].rstrip() + "…"


# 各源常见失败原因 → 中文可读说明（前端直接展示，避免用户看到裸异常栈）
_ERROR_HINTS: List[tuple] = [
    ("429", "免 key 配额已用尽，稍后重试或减少并发"),
    ("Making sure you're not a bot", "站点反爬验证拦截（DBLP 对数据中心 IP 不友好），该源暂不可用"),
    ("within.website", "站点反爬验证拦截，该源暂不可用"),
    ("403", "被拒绝访问，通常是 UA/频率限制"),
    ("timed out", "连接超时，网络不通或被墙"),
    ("未配置 WANFANG_TOKEN", "未配置 WANFANG_TOKEN（万方按点计费，需在开放平台申请）"),
    ("Bad Gateway", "上游网关错误，稍后重试"),
    ("Service Unavailable", "源站暂时不可用，稍后重试"),
]


def _explain_error(e: Exception) -> str:
    """把原始异常翻译成研究者能判断下一步动作的中文说明。"""
    raw = str(e) or e.__class__.__name__
    low = raw.lower()
    for needle, hint in _ERROR_HINTS:
        if needle.lower() in low:
            code = ""
            if hasattr(e, "code"):
                code = f"HTTP {e.code} · "
            elif e.__class__.__name__ == "JSONDecodeError":
                code = "返回非 JSON · "
            return _truncate(f"{code}{hint}（{raw[:60]}）", 160)
    return _truncate(raw, 160)


def _abstract_to_text(inverted: Optional[Dict[str, List[int]]]) -> str:
    """OpenAlex 的 abstract_inverted_index 反转还原。

    形如 {"solid": [0], "oxide": [1]} → "solid oxide"

    注意：OpenAlex/Crossref 本身**不对每条文献都提供摘要**（老文献、
    付费墙期刊常见为 null），实测命中里过半 abstract 为空。因此摘要为空
    是数据源常态而非 bug，UI 需要如实提示「该源未返回摘要」。
    """
    if not inverted:
        return ""
    pos: List[tuple] = []
    for word, idxs in inverted.items():
        for i in idxs or []:
            pos.append((i, word))
    if not pos:
        return ""
    pos.sort(key=lambda x: x[0])
    return " ".join(w for _, w in pos)


# ---------------------------------------------------------------------------
# 源目录（前端 /api/kb/sources 直接消费）
# ---------------------------------------------------------------------------
# note 字段写「对材料化学研究者意味着什么」，避免前端堆一串英文名。
SOURCE_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "openalex",
        "label": "OpenAlex",
        "cover": "2.5 亿+ 跨学科论文索引",
        "key_required": False,
        "domain": "全部学科",
        "cn_coverage": False,
        "note": "综合覆盖最广，含被引数与 OA 全文链接；材料类命中好，是默认首选。",
        "priority": 1,
    },
    {
        "id": "crossref",
        "label": "Crossref",
        "cover": "1.5 亿+ DOI 元数据权威源",
        "key_required": False,
        "domain": "全部学科",
        "cn_coverage": True,
        "note": "DOI 权威库，用于核验一条文献是否真实存在；中文期刊收录优于 OpenAlex。",
        "priority": 2,
    },
    {
        "id": "arxiv",
        "label": "arXiv",
        "cover": "预印本（物理 / 化学 / 材料）",
        "key_required": False,
        "domain": "物理 · 化学 · 数学 · 计算机",
        "cn_coverage": False,
        "note": "最新进展最快的预印本源，固态电解质、钙钛矿方向更新通常早于期刊。",
        "priority": 3,
    },
    {
        "id": "semantic_scholar",
        "label": "Semantic Scholar",
        "cover": "2 亿+ 论文 + 引用图谱",
        "key_required": False,
        "domain": "全部学科",
        "cn_coverage": False,
        "note": "擅长引用关系与被引数。**实测免 key 池几乎必 429**，已做退避重试；"
                "默认不勾选，配置环境变量 S2_API_KEY（免费注册）后再启用更划算。",
        "priority": 4,
        "default_on": False,
    },
    {
        "id": "europe_pmc",
        "label": "Europe PMC",
        "cover": "生命科学全文 + 摘要",
        "key_required": False,
        "domain": "生物医学",
        "cn_coverage": False,
        "note": "材料学科覆盖弱，仅当课题涉及生物材料/医用材料时补充使用。",
        "priority": 5,
        "default_on": False,
    },
    {
        "id": "pubmed",
        "label": "PubMed",
        "cover": "生物医学文献",
        "key_required": False,
        "domain": "生物医学",
        "cn_coverage": False,
        "note": "同上，材料方向基本不适用，保留以备跨学科检索。",
        "priority": 6,
        "default_on": False,
    },
    {
        "id": "dblp",
        "label": "DBLP",
        "cover": "计算机 · CS 会议期刊",
        "key_required": False,
        "domain": "计算机",
        "cn_coverage": False,
        "note": "与材料化学无关。**实测站点已启用反爬验证**，对数据中心 IP 返回质询页，"
                "默认不勾选；确需使用时走本地网络或改用 OpenAlex 覆盖 CS 论文。",
        "priority": 7,
        "default_on": False,
        "known_blocked": True,
    },
    {
        "id": "wanfang",
        "label": "万方数据",
        "cover": "中文期刊 · 学位论文 · 会议",
        "key_required": True,
        "key_env": "WANFANG_TOKEN",
        "domain": "中文全学科",
        "cn_coverage": True,
        "note": "官方开放平台按点计费。配置环境变量 WANFANG_TOKEN 后可直接检索；"
                "未配置时本模块不伪造端点，请走「知网/万方人工检索 → 导出题录 → 导入本地库」。",
        "priority": 0,
    },
    {
        "id": "aminer",
        "label": "AMiner 学术图谱",
        "cover": "中文科研图谱 · 支持中文关键词",
        "key_required": True,
        "key_env": "AMINER_API_KEY",
        "domain": "中文为主 · 计算机较强",
        "cn_coverage": True,
        "note": "清华 AMiner，图谱关系与中文关键词检索强，是知网不可用时最现实的中文补缺。"
                "需到 aminer.cn 申请 API Key，配置环境变量 AMINER_API_KEY 后启用。",
        "priority": 0,
    },
]

# 知网等**无公开接口**的来源：如实展示在 UI 上，避免用户以为漏做了。
UNAVAILABLE_SOURCES: List[Dict[str, Any]] = [
    {
        "id": "cnki",
        "label": "知网 CNKI",
        "reason": "无公开 API",
        "detail": "官方 Open API 仅限签署合作协议的高校/科研机构/图书馆，"
                  "个人无法自助申请密钥；代申请与共享密钥属违规。",
        "workaround": "在 kns.cnki.net 检索 → 导出 Refworks/EndNote 题录 → "
                      "用「添加文献」tab 导入本地知识库。",
    },
    {
        "id": "cqvip",
        "label": "维普 / 超星",
        "reason": "无可用接口",
        "detail": "站点对自动化请求返回 412 / 滑动验证，无稳定开放端点。",
        "workaround": "人工检索后复制题录，粘贴到会话中由 Agent 整理入库。",
    },
]

_SOURCE_INDEX = {s["id"]: s for s in SOURCE_CATALOG}


def get_catalog() -> List[Dict[str, Any]]:
    """返回源目录 + 当前凭据可用性（供前端渲染卡片墙）。

    ``configured`` 是关键：付费源没配 key 时前端必须显示为不可勾选并说明原因，
    否则用户点了只会拿到一句看不懂的报错。
    """
    out = []
    for s in SOURCE_CATALOG:
        item = dict(s)
        if s.get("key_required"):
            item["configured"] = bool((os.environ.get(s.get("key_env") or "") or "").strip())
        else:
            item["configured"] = True
        # 显式给出默认勾选状态：后端 DEFAULT_SOURCES 是唯一真相来源，
        # 前端不自己猜，避免两边默认值漂移。
        item["default_on"] = s["id"] in DEFAULT_SOURCES
        out.append(item)
    # 未配置的付费源排最后，避免占据首屏
    out.sort(key=lambda x: (not x["configured"], 0 if x["default_on"] else 1,
                            x.get("priority", 99), x["label"]))
    return out


# ---------------------------------------------------------------------------
# 各源检索实现 —— 统一返回 List[Dict]
# ---------------------------------------------------------------------------
def _search_openalex(query: str, limit: int, timeout: float) -> List[Dict[str, Any]]:
    sel = ",".join([
        "id", "title", "publication_year", "authorships", "doi",
        "primary_location", "abstract_inverted_index", "cited_by_count",
    ])
    url = ("https://api.openalex.org/works?search=" + urllib.parse.quote(query)
           + f"&per-page={max(1, min(limit, 25))}&select={sel}")
    d = _get_json(url, timeout=timeout)
    out = []
    for w in (d.get("results") or [])[:limit]:
        title = (w.get("title") or "").strip()
        if not title:
            continue
        loc = w.get("primary_location") or {}
        src = loc.get("source") or {}
        oa_url = loc.get("pdf_url") or ""
        doi = (w.get("doi") or "").strip()
        abstract = _abstract_to_text(w.get("abstract_inverted_index"))
        auths = [a.get("author", {}).get("display_name", "")
                 for a in (w.get("authorships") or [])[:5]]
        out.append({
            "id": (w.get("id") or "").rsplit("/", 1)[-1] or doi or title[:40],
            "title": title,
            "authors": ", ".join(a for a in auths if a),
            "year": str(w.get("publication_year") or ""),
            "venue": src.get("display_name") or "",
            "doi": doi,
            "url": loc.get("landing_page_url") or "",
            "oa_url": oa_url or "",
            "abstract": abstract,
            "cited_by": int(w.get("cited_by_count") or 0),
            "source": "openalex",
            "source_label": "OpenAlex",
            "snippet": _truncate(abstract, 600),
        })
    return out


def _search_crossref(query: str, limit: int, timeout: float) -> List[Dict[str, Any]]:
    sel = ",".join(["title", "author", "issued", "container-title", "DOI",
                    "abstract", "is-referenced-by-count", "URL"])
    url = ("https://api.crossref.org/works?query.bibliographic="
           + urllib.parse.quote(query)
           + f"&rows={max(1, min(limit, 25))}&select={sel}")
    d = _get_json(url, timeout=timeout)
    items = ((d.get("message") or {}).get("items")) or []
    out = []
    for it in items[:limit]:
        titles = it.get("title") or []
        title = (titles[0] if titles else "").strip()
        if not title:
            continue
        names = []
        for a in (it.get("author") or [])[:5]:
            nm = ((a.get("given") or "") + " " + (a.get("family") or "")).strip()
            if nm:
                names.append(nm)
        year = ""
        try:
            year = str(it["issued"]["date-parts"][0][0])
        except Exception:
            year = ""
        containers = it.get("container-title") or []
        doi = (it.get("DOI") or "").strip()
        abstract = _strip_tags(it.get("abstract") or "")
        out.append({
            "id": doi or title[:40],
            "title": title,
            "authors": ", ".join(names),
            "year": year,
            "venue": (containers[0] if containers else "").strip(),
            "doi": f"https://doi.org/{doi}" if doi else "",
            "url": it.get("URL") or (f"https://doi.org/{doi}" if doi else ""),
            "oa_url": "",
            "abstract": abstract,
            "cited_by": int(it.get("is-referenced-by-count") or 0),
            "source": "crossref",
            "source_label": "Crossref",
            "snippet": _truncate(abstract, 600),
        })
    return out


_ATOM = "{http://www.w3.org/2005/Atom}"

# arXiv 官方要求 ~1 req / 3s politeness。实测：单请求正常，多源并发时同源并发
# 会直接 403（单请求 http/https 均 200，故不是封禁而是限流）。
# 这里用一把进程内锁 + 最小间隔串行化 arXiv 请求。
_ARXIV_MIN_INTERVAL = 3.2
_arxiv_lock = threading.Lock()
_arxiv_last = [0.0]


def _arxiv_throttle() -> None:
    with _arxiv_lock:
        wait = _ARXIV_MIN_INTERVAL - (time.time() - _arxiv_last[0])
        if wait > 0:
            time.sleep(wait)
        _arxiv_last[0] = time.time()


def _search_arxiv(query: str, limit: int, timeout: float) -> List[Dict[str, Any]]:
    url = ("https://export.arxiv.org/api/query?search_query=all:"
           + urllib.parse.quote(query)
           + f"&max_results={max(1, min(limit, 20))}&sortBy=relevance")
    _arxiv_throttle()
    raw = _get_text(url, timeout=timeout)
    root = ET.fromstring(raw)
    out = []
    for e in root.findall(f"{_ATOM}entry")[:limit]:
        def _t(tag: str) -> str:
            el = e.find(f"{_ATOM}{tag}")
            return (el.text or "").strip() if el is not None and el.text else ""

        title = _truncate(_t("title"), 300)
        if not title:
            continue
        summary = _WS_RE.sub(" ", _t("summary")).strip()
        authors = ", ".join(
            (a.find(f"{_ATOM}name").text or "").strip()
            for a in e.findall(f"{_ATOM}author")[:5]
            if a.find(f"{_ATOM}name") is not None
        )
        aid = _t("id")
        pdf_url = ""
        for link in e.findall(f"{_ATOM}link"):
            if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                pdf_url = link.get("href") or ""
                break
        published = _t("published")[:10]
        # arXiv 标识转 DOI（10.48550/arXiv.<id>）
        m = re.search(r"arxiv\.org/abs/(.+)$", aid)
        arxiv_id = m.group(1) if m else ""
        out.append({
            "id": arxiv_id or aid,
            "title": title,
            "authors": authors,
            "year": published[:4],
            "venue": "arXiv 预印本",
            "doi": f"https://doi.org/10.48550/arXiv.{arxiv_id}" if arxiv_id else "",
            "url": aid,
            "oa_url": pdf_url,
            "abstract": summary,
            "cited_by": 0,
            "source": "arxiv",
            "source_label": "arXiv",
            "snippet": _truncate(summary, 600),
        })
    return out


def _search_semantic_scholar(query: str, limit: int, timeout: float) -> List[Dict[str, Any]]:
    """Semantic Scholar。实测免 key 池很紧，常直接 429。

    这里做指数退避重试（最多 2 次），仍失败则抛可读错误，由上层标灰该源。
    若用户配置了 S2_API_KEY（免费注册可得）则带上，配额提升一个量级。
    """
    fields = "title,authors,year,abstract,externalIds,citationCount,venue,openAccessPdf,url"
    url = ("https://api.semanticscholar.org/graph/v1/paper/search?query="
           + urllib.parse.quote(query)
           + f"&limit={max(1, min(limit, 20))}&fields={fields}")
    headers = {}
    key = os.environ.get("S2_API_KEY", "").strip()
    if key:
        headers["x-api-key"] = key

    import time as _t

    last: Exception | None = None
    for attempt in range(3):
        try:
            d = _get_json(url, timeout=timeout, retries=0, headers=headers)
            break
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429 and attempt < 2:
                _t.sleep(1.2 * (attempt + 1))  # 1.2s / 2.4s
                continue
            raise
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < 2:
                _t.sleep(1.0)
                continue
            raise
    else:  # pragma: no cover
        raise last or RuntimeError("Semantic Scholar 请求失败")

    out = []
    for p in (d.get("data") or [])[:limit]:
        title = (p.get("title") or "").strip()
        if not title:
            continue
        ext = p.get("externalIds") or {}
        doi = (ext.get("DOI") or "").strip()
        oa = (p.get("openAccessPdf") or {}).get("url") or ""
        abstract = p.get("abstract") or ""
        out.append({
            "id": p.get("paperId") or doi or title[:40],
            "title": title,
            "authors": ", ".join(a.get("name", "") for a in (p.get("authors") or [])[:5]),
            "year": str(p.get("year") or ""),
            "venue": p.get("venue") or "",
            "doi": f"https://doi.org/{doi}" if doi else "",
            "url": p.get("url") or "",
            "oa_url": oa,
            "abstract": abstract,
            "cited_by": int(p.get("citationCount") or 0),
            "source": "semantic_scholar",
            "source_label": "Semantic Scholar",
            "snippet": _truncate(abstract, 600),
        })
    return out


def _search_europe_pmc(query: str, limit: int, timeout: float) -> List[Dict[str, Any]]:
    url = ("https://www.ebi.ac.uk/europepmc/webservices/rest/search?query="
           + urllib.parse.quote(query)
           + f"&format=json&pageSize={max(1, min(limit, 25))}&resultType=core")
    d = _get_json(url, timeout=timeout)
    out = []
    res = ((d.get("resultList") or {}).get("result")) or []
    for p in res[:limit]:
        title = (p.get("title") or "").strip()
        if not title:
            continue
        doi = (p.get("doi") or "").strip()
        pmcid = p.get("pmcid") or ""
        out.append({
            "id": (p.get("id") or doi or title[:40]),
            "title": title,
            "authors": (p.get("authorString") or "")[:220],
            "year": (p.get("pubYear") or ""),
            "venue": (p.get("journalTitle") or ""),
            "doi": f"https://doi.org/{doi}" if doi else "",
            "url": f"https://europepmc.org/article/{p.get('source', 'MED')}/{p.get('id', '')}",
            "oa_url": f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
                      if pmcid and p.get("isOpenAccess") == "Y" else "",
            "abstract": _strip_tags(p.get("abstractText") or ""),
            "cited_by": int(p.get("citedByCount") or 0),
            "source": "europe_pmc",
            "source_label": "Europe PMC",
            "snippet": _truncate(_strip_tags(p.get("abstractText") or ""), 600),
        })
    return out


def _search_pubmed(query: str, limit: int, timeout: float) -> List[Dict[str, Any]]:
    n = max(1, min(limit, 20))
    su = ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&retmode=json"
          f"&retmax={n}&term=" + urllib.parse.quote(query))
    ids = (((_get_json(su, timeout=timeout).get("esearchresult") or {}).get("idlist")) or [])
    if not ids:
        return []
    fu = ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&retmode=xml&id="
          + ",".join(ids))
    raw = _get_text(fu, timeout=timeout)
    root = ET.fromstring(raw)
    out = []
    for art in root.findall(".//PubmedArticle")[:limit]:
        pmid = (art.findtext(".//PMID") or "").strip()
        title = _WS_RE.sub(" ", _strip_tags(art.findtext(".//ArticleTitle") or "")).strip()
        if not title:
            continue
        abst = " ".join(
            _strip_tags(a.text or "") for a in art.findall(".//Abstract/AbstractText")
        )
        year = (art.findtext(".//PubDate/Year") or art.findtext(".//PubDate/MedlineDate") or "").strip()[:4]
        journal = _strip_tags(art.findtext(".//Journal/Title") or "")
        authors = ", ".join(
            _strip_tags((a.findtext("LastName") or "") + " " + (a.findtext("Initials") or ""))
            for a in art.findall(".//Author")[:5]
        )
        doi = ""
        for aid in art.findall(".//ArticleId"):
            if aid.get("IdType") == "doi":
                doi = (aid.text or "").strip()
                break
        out.append({
            "id": pmid or doi or title[:40],
            "title": title,
            "authors": authors,
            "year": year,
            "venue": journal,
            "doi": f"https://doi.org/{doi}" if doi else "",
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
            "oa_url": "",
            "abstract": abst,
            "cited_by": 0,
            "source": "pubmed",
            "source_label": "PubMed",
            "snippet": _truncate(abst, 600),
        })
    return out


def _search_dblp(query: str, limit: int, timeout: float) -> List[Dict[str, Any]]:
    """DBLP（计算机领域）。**实测：站点已挂 Anubis 反爬验证**，
    对数据中心 IP 一律返回 HTML 质询页而非 JSON。

    这里显式识别并抛出可读错误，让前端把该源标灰，而不是给用户一个
    语焉不详的「JSONDecodeError」。材料化学场景也不需要它。
    """
    url = ("https://dblp.org/search/publ/api?q=" + urllib.parse.quote(query)
           + f"&format=json&h={max(1, min(limit, 30))}")
    try:
        raw = _get_text(url, timeout=timeout)
    except Exception:
        raise RuntimeError("DBLP 不可达（超时或网络受限）")
    head = raw.lstrip()[:200].lower()
    if not head.startswith("{"):
        if "not a bot" in head or "within.website" in head:
            raise RuntimeError("DBLP 站点反爬验证拦截（非 JSON 返回），该源暂不可用")
        raise RuntimeError(f"DBLP 返回非 JSON：{raw[:80]!r}")
    d = json.loads(raw)
    hits = (((d.get("result") or {}).get("hits") or {}).get("hit")) or []
    out = []
    for h in hits[:limit]:
        info = h.get("info") or {}
        title = _strip_tags(info.get("title") or "")
        if not title:
            continue
        doi = (info.get("doi") or "").strip()
        venue = _strip_tags(info.get("venue") or "")
        year = str(info.get("year") or "")
        out.append({
            "id": (info.get("key") or doi or title[:40]),
            "title": title,
            "authors": ", ".join(
                a.get("text", "") if isinstance(a, dict) else str(a)
                for a in (info.get("authors", {}).get("author") or [])[:5]
            ),
            "year": year,
            "venue": venue,
            "doi": f"https://doi.org/{doi}" if doi else "",
            "url": info.get("ee") or (f"https://doi.org/{doi}" if doi else ""),
            "oa_url": "",
            "abstract": "",
            "cited_by": 0,
            "source": "dblp",
            "source_label": "DBLP",
            "snippet": "",
        })
    return out


def _search_wanfang(query: str, limit: int, timeout: float) -> List[Dict[str, Any]]:
    """万方开放平台（需 token，按点计费）。

    无 token 直接抛 RuntimeError —— **不伪造端点**。官方文档见
    https://open.wanfangdata.com.cn/ ，字段命名以返回体为准，失败降级为空。
    """
    token = os.environ.get("WANFANG_TOKEN", "").strip()
    if not token:
        raise RuntimeError("未配置 WANFANG_TOKEN（万方开放平台按点计费，需在开放平台申请）")
    url = ("https://s.wanfangdata.com.cn/ThesisService.SearchService.OpenSearch?token="
           + urllib.parse.quote(token)
           + "&searchType=paper&pageSize=" + str(max(1, min(limit, 20)))
           + "&searchWord=" + urllib.parse.quote(query))
    d = _get_json(url, timeout=timeout, retries=0)
    items = ((d.get("data") or {}).get("ResponseResult") or {}).get("Result") or d.get("result") or []
    out = []
    for it in items[:limit]:
        title = (it.get("Title") or it.get("title") or "").strip()
        if not title:
            continue
        authors = it.get("Author") or it.get("authors") or ""
        if isinstance(authors, list):
            authors = ", ".join(str(a) for a in authors[:5])
        doi = (it.get("DOI") or it.get("doi") or "").strip()
        out.append({
            "id": (it.get("ID") or doi or title[:40]),
            "title": title,
            "authors": str(authors),
            "year": str(it.get("Year") or it.get("PublishYear") or ""),
            "venue": it.get("Source") or it.get("Journal") or "",
            "doi": f"https://doi.org/{doi}" if doi else "",
            "url": it.get("Url") or "",
            "oa_url": "",
            "abstract": _strip_tags(it.get("Abstract") or ""),
            "cited_by": int(it.get("Citations") or 0),
            "source": "wanfang",
            "source_label": "万方",
            "snippet": _truncate(_strip_tags(it.get("Abstract") or ""), 600),
        })
    return out


def _search_aminer(query: str, limit: int, timeout: float) -> List[Dict[str, Any]]:
    """AMiner（清华学术图谱）—— **支持中文关键词**，是知网不可用时最现实的补缺。

    需申请 AMINER_API_KEY（aminer.cn 开放平台）。未配置直接抛可读错误，
    不伪造端点。字段命名以返回体为准，容错解析。
    """
    key = os.environ.get("AMINER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("未配置 AMINER_API_KEY（AMiner 中文学术图谱，需在 aminer.cn 申请）")
    url = ("https://apiv2.aminer.cn/magic?a=search_paper&keyword="
           + urllib.parse.quote(query)
           + f"&size={max(1, min(limit, 20))}&page=0")
    d = _get_json(url, timeout=timeout, retries=0, headers={"Authorization": key})
    items = ((d.get("data") or {}).get("list")) or d.get("list") or []
    out = []
    for it in items[:limit]:
        if not isinstance(it, dict):
            continue
        title = re.sub(r"<[^>]+>", "", str(it.get("title") or it.get("name") or "")).strip()
        if not title:
            continue
        abstract = _strip_tags(str(it.get("abstract") or it.get("abstract_zh") or ""))
        year = str(it.get("year") or it.get("pubYear") or "")
        if not year:
            dt = it.get("updateDate") or it.get("publishDate") or ""
            m = re.search(r"(19|20)\d{2}", str(dt))
            year = m.group(0) if m else ""
        doi = str(it.get("doi") or "").strip()
        authors = ""
        au = it.get("authors") or it.get("author") or []
        if isinstance(au, list):
            names = []
            for a in au[:5]:
                if isinstance(a, dict):
                    n = a.get("name") or ((a.get("zhName") or "") + " " + (a.get("enName") or "")).strip()
                    names.append(n)
                else:
                    names.append(str(a))
            authors = ", ".join(n for n in names if n)
        else:
            authors = str(au)
        venue = str(it.get("venue") or it.get("journal") or "")
        out.append({
            "id": str(it.get("id") or doi or title[:40]),
            "title": title,
            "authors": authors,
            "year": year,
            "venue": venue,
            "doi": f"https://doi.org/{doi}" if doi else "",
            "url": str(it.get("url") or (f"https://www.aminer.cn/pub/{it.get('id')}" if it.get("id") else "")),
            "oa_url": "",
            "abstract": abstract,
            "cited_by": int(it.get("citations") or it.get("citation") or 0),
            "source": "aminer",
            "source_label": "AMiner",
            "snippet": _truncate(abstract, 600),
        })
    return out


def _read_unpaywall_email_from_dotenv() -> str:
    """从 ``~/.matlens/.env`` 读 UNPAYWALL_EMAIL。

    服务进程启动时通常**没有**这个环境变量（用户只写在 .env 里），
    而 ``fetch_unpaywall`` 原先只读环境变量 → 端点恒 502。
    这里补上 .env 回落，且**不修改 os.environ**（只是读一次）。

    ⚠️ 只取这一项，不做整体 dotenv 加载 —— 避免在库代码里产生
    「导入 scholarly 就改了进程环境」的副作用。
    """
    try:
        from pathlib import Path

        from matlens_cli.config import get_matlens_home

        p = Path(get_matlens_home()) / ".env"
        if not p.exists():
            return ""
        for raw in p.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if not line.upper().startswith("UNPAYWALL_EMAIL="):
                continue
            val = line.split("=", 1)[1].strip().strip('"').strip("'")
            if "@" in val:
                return val
    except Exception:
        return ""
    return ""


def fetch_europepmc_fulltext(doi_or_pmcid: str, timeout: float = _DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """经 **Europe PMC 官方 API** 按 DOI 取开放全文（2026-10-29）。

    为什么需要这条路径：
      Unpaywall 给的 OA 链接常在出版商域名，而那些站点的 robots.txt
      往往禁止抓取（实测 MDPI 与 NCBI PMC 都在 ``Disallow`` 列表里）。
      **robots 是站点的明确声明，绕过它就是违规** —— 所以不能靠"换个镜像抓"。

    Europe PMC 提供的是**正规 REST API**（EBI），返回全文 XML，
    合法可编程访问，且不受目标站点的 robots 约束。
    实测 10.3390/membranes12090896 在 PMC 收录，正文可完整取回。

    返回 ``{ok, text, title, pmcid, via}``；取不到时 ``ok=False``。
    """
    key = (doi_or_pmcid or "").strip()
    if not key:
        return {"ok": False, "error": "缺少 DOI"}
    key = re.sub(r"^https?://(dx\.)?doi\.org/", "", key, flags=re.I)
    # 按 DOI 查（Europe PMC 支持 DOI: 前缀查询）
    url = ("https://www.ebi.ac.uk/europepmc/webservices/rest/search?query="
           + urllib.parse.quote("DOI:" + key)
           + "&format=json&pageSize=1&resultType=core")
    try:
        d = _get_json(url, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Europe PMC 查询失败：{type(e).__name__}"}

    res = ((d.get("resultList") or {}).get("result")) or []
    if not res:
        return {"ok": False, "error": "Europe PMC 未收录该 DOI"}
    rec = res[0]
    pmcid = (rec.get("pmcid") or "").strip()
    is_oa = rec.get("isOpenAccess") == "Y"
    if not pmcid:
        return {"ok": False, "error": "Europe PMC 记录无 PMCID（无全文标识）"}
    if not is_oa:
        return {"ok": False, "error": "Europe PMC 中该文非开放获取（isOpenAccess != Y）"}

    # 取全文 XML
    xml_url = (f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML")
    try:
        raw = _http_get(xml_url, timeout=timeout).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"全文抓取失败：{type(e).__name__}"}

    text = _xml_to_text(raw)
    if len(text) < 200:
        return {"ok": False, "error": f"全文过短（{len(text)} 字），疑似解析失败"}
    return {
        "ok": True,
        "text": text,
        "title": (rec.get("title") or "").strip(),
        "pmcid": pmcid,
        "source": rec.get("source") or "",
        "authors": (rec.get("authorString") or "")[:220],
        "year": (rec.get("pubYear") or ""),
        "via": "Europe PMC 官方 API",
    }


def _xml_to_text(xml: str) -> str:
    """把 JATS XML 转纯文本（保留段落与标题层级）。"""
    if not xml:
        return ""
    t = re.sub(r"<xref[^>]*>.*?</xref>", "", xml, flags=re.S | re.I)
    t = re.sub(r"<ref-list.*?</ref-list>", "", t, flags=re.S | re.I)
    # 段落级标签 → 换行
    t = re.sub(r"</(p|title|sec|abstract|caption|list-item)>", "\n\n", t, flags=re.I)
    t = re.sub(r"<title[^>]*>", "\n## ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = (t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
           .replace("&quot;", '"').replace("&apos;", "'"))
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def fetch_unpaywall(doi_or_url: str, timeout: float = _DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """按 DOI 解析合法开放获取全文链接（Unpaywall，只需邮箱）。

    不放进 SEARCHERS：它是**按 DOI 精确查询**而非关键词检索。
    供「已选文献 → 找 OA 全文」按钮使用，补足约 30% 付费墙论文没有全文的问题。
    """
    doi = (doi_or_url or "").strip()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.I)
    if not doi.lower().startswith("10."):
        raise ValueError("需要 DOI（形如 10.xxxx/yyyy），当前来源未提供 DOI")
    # Unpaywall 要求真实联系邮箱，无效邮箱会直接 422。
    # 未配置时给出明确报错，而不是拿占位邮箱去撞接口。
    #
    # ⚠️ 必须同时看**环境变量与 ~/.matlens/.env**（2026-10-29 修复）：
    # 服务进程启动时往往**没有**这个环境变量（用户只写在 .env 里），
    # 于是「找 OA 全文」永远 502 —— 端点看起来坏了，其实只是没读到配置。
    email = (os.environ.get("UNPAYWALL_EMAIL") or "").strip()
    if not email or "@" not in email:
        email = _read_unpaywall_email_from_dotenv()
    if not email or "@" not in email:
        raise RuntimeError(
            "未配置 UNPAYWALL_EMAIL（Unpaywall 需联系邮箱，任意真实邮箱即可）。"
            "请在 ~/.matlens/.env 里加一行 UNPAYWALL_EMAIL=你的邮箱，"
            "或设置同名环境变量后重启服务。")
    url = f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?email={urllib.parse.quote(email)}"
    d = _get_json(url, timeout=timeout)
    loc = d.get("best_oa_location") or {}

    # ⚠️ 必须返回**全部**候选位置，不能只给 best_oa_location（2026-10-29 实测）：
    # 实测 10.3390/membranes12090896 的 best 是 publisher 域（mdpi.com，
    # robots 禁止抓 → 拿不到正文），但同一记录里还有
    #   host_type=repository → ncbi.nlm.nih.gov/pmc/...  ← PMC 镜像，可抓
    #   host_type=repository → doaj.org/...
    # 只用 best 会让「明明有合法 OA 全文」被判成抓不到。
    # 排序规则：repository（机构库/镜像）优先于 publisher，
    # 因为出版商站点的 robots 限制更常见。
    alts = []
    seen_alt = set()
    for o in (d.get("oa_locations") or []):
        u = (o.get("url_for_pdf") or o.get("url") or "").strip()
        if not u or u in seen_alt:
            continue
        seen_alt.add(u)
        alts.append({
            "url": u,
            "landing_page": o.get("url_for_landing_page") or o.get("url") or "",
            "host_type": o.get("host_type") or "",
            "version": o.get("version") or "",
            "license": o.get("license") or "",
        })
    # best 放最前，其余按 repository 优先
    best_url = loc.get("url_for_pdf") or loc.get("url") or ""
    alts.sort(key=lambda x: (0 if x["url"] == best_url else 1,
                              0 if x["host_type"] == "repository" else 1))

    return {
        "doi": d.get("doi") or doi,
        "title": d.get("title") or "",
        "is_oa": bool(d.get("is_oa")),
        "oa_status": d.get("oa_status") or "",
        "oa_url": best_url,
        "landing_page": loc.get("url") or "",
        "host_type": loc.get("host_type") or "",
        "license": loc.get("license") or "",
        "alternatives": alts,
        "note": d.get("message") or "",
    }


# 注册表：id -> (func, 可用于默认勾选)
SEARCHERS: Dict[str, Callable[[str, int, float], List[Dict[str, Any]]]] = {
    "openalex": _search_openalex,
    "crossref": _search_crossref,
    "arxiv": _search_arxiv,
    "semantic_scholar": _search_semantic_scholar,
    "europe_pmc": _search_europe_pmc,
    "pubmed": _search_pubmed,
    "dblp": _search_dblp,
    "wanfang": _search_wanfang,
    "aminer": _search_aminer,
}

def _collect_source(fut, sid: str) -> tuple:
    """取单个源结果 → (统计 dict, 文献列表)。失败不抛，返回可读 error。"""
    label = _SOURCE_INDEX.get(sid, {}).get("label", sid)
    try:
        got = fut.result()
        return {"ok": True, "n": len(got), "label": label}, list(got)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "n": 0, "error": _explain_error(e), "label": label}, []


# 面向材料化学的默认勾选：**实测稳定可用且材料方向命中率高的三个源**。
# Semantic Scholar / Europe PMC / PubMed / DBLP 实测要么配额枯竭、要么学科不匹配、
# 要么被反爬拦截，默认不勾（目录里保留，用户可按需手动开启）。
DEFAULT_SOURCES = ["openalex", "crossref", "arxiv"]

# 单次多源检索的总时间预算（秒）。超时即返回已完成源的结果，
# 剩余源标 timeout —— 前端最多等这么久，不出现「转圈 40 秒」。
TOTAL_BUDGET = 26.0


# ---------------------------------------------------------------------------
# 并发多源检索
# ---------------------------------------------------------------------------
def search_web(
    query: str,
    sources: Optional[List[str]] = None,
    per_source: int = 8,
    timeout: float = _DEFAULT_TIMEOUT,
    budget: float = TOTAL_BUDGET,
) -> Dict[str, Any]:
    """并发检索多个云端学术源。

    返回::

        {
          "query": "...",
          "items": [ ...统一结构文献... ],
          "sources": {"openalex": {"ok": True, "n": 8, "ms": 412},
                      "crossref": {"ok": False, "error": "...", "ms": 1200}},
          "requested": [...], "elapsed_ms": 1830
        }

    单源失败不影响整体：失败源在 sources 里如实给出 error，前端标灰即可。
    """
    import time

    query = (query or "").strip()
    if not query:
        raise ValueError("query 必填")
    # per_source 是「每个源取几条」（int），与结果里的 per_source 字典不是一回事，
    # 这里统一用 limit_per 承载条数，避免早期版本把两者混用导致 dict*int 崩溃。
    limit_per = max(1, per_source)
    srcs = [s for s in (sources or DEFAULT_SOURCES) if s in SEARCHERS]
    # 去重保序
    seen, ordered = set(), []
    for s in srcs:
        if s not in seen:
            seen.add(s)
            ordered.append(s)
    if not ordered:
        ordered = list(DEFAULT_SOURCES)

    t0 = time.time()
    deadline = t0 + budget
    results: List[Dict[str, Any]] = []
    per_source_stat: Dict[str, Any] = {}

    # 每源分摊剩余预算：避免单个慢源（如 S2 配额等待、OpenAlex 网络抖动）
    # 把整个请求拖到 40s+ —— 实测单源退避叠加会让 UI 长时间空转。
    # 下限 8s：给一次超时重试留出余量（单次 ~4s + 重试 ~4s）。
    per_src_timeout = max(8.0, min(timeout, (deadline - time.time()) / max(1, len(ordered))))

    ex = concurrent.futures.ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(ordered)))
    futs = {ex.submit(SEARCHERS[s], query, limit_per, per_src_timeout): s for s in ordered}
    pending = set(futs.keys())
    try:
        # 到达总预算即放弃剩余源（它们会被 cancel / 标记 timeout）
        while pending:
            left = deadline - time.time()
            if left <= 0:
                break
            done, pending = concurrent.futures.wait(pending, timeout=left,
                                                    return_when=concurrent.futures.FIRST_COMPLETED)
            for fut in done:
                sid = futs[fut]
                stat, got = _collect_source(fut, sid)
                per_source_stat[sid] = stat
                results.extend(got)
        # 预算耗尽仍未返回的源：如实标记为超时，不假装失败原因已知
        for fut in pending:
            sid = futs[fut]
            per_source_stat[sid] = {
                "ok": False, "n": 0, "ms": int((time.time() - t0) * 1000),
                "error": "超出总预算 %ds，已放弃等待（可稍后重试或减少勾选源）" % int(budget),
                "label": _SOURCE_INDEX.get(sid, {}).get("label", sid),
            }
            fut.cancel()
    finally:
        ex.shutdown(wait=False)

    # 排序：有 DOI 的、可 OA 的、被引多的优先；同分按标题
    def _rank(it: Dict[str, Any]) -> tuple:
        return (0 if it.get("doi") else 1, 0 if it.get("oa_url") else 1,
                -int(it.get("cited_by") or 0), it.get("title") or "")

    results.sort(key=_rank)

    # 跨源去重：DOI 优先，其次标题归一化
    seen_keys: set = set()
    deduped: List[Dict[str, Any]] = []
    for it in results:
        doi = (it.get("doi") or "").lower().strip()
        title_key = re.sub(r"[^a-z0-9]+", "", (it.get("title") or "").lower())[:70]
        key = doi or title_key
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(it)

    return {
        "query": query,
        "items": deduped[: limit_per * len(ordered)],
        "raw_count": len(results),
        "per_source": per_source_stat,
        "requested": ordered,
        "elapsed_ms": int((time.time() - t0) * 1000),
    }


# ---------------------------------------------------------------------------
# 来源健康自检（/api/kb/sources/health）
# ---------------------------------------------------------------------------
def check_source(source_id: str, timeout: float = 8.0) -> Dict[str, Any]:
    """对单个源做一次轻量自检（1 条结果），返回可达性与耗时。"""
    fn = SEARCHERS.get(source_id)
    if not fn:
        return {"ok": False, "error": f"未知来源 {source_id}"}
    import time

    t0 = time.time()
    try:
        got = fn("solid oxide fuel cell electrolyte", 1, timeout)
        return {"ok": True, "n": len(got), "ms": int((time.time() - t0) * 1000)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": _truncate(str(e) or e.__class__.__name__, 160),
                "ms": int((time.time() - t0) * 1000)}


# ---------------------------------------------------------------------------
# 云端文献 → 本地知识库导入
# ---------------------------------------------------------------------------
def paper_filename(item: Dict[str, Any], stamp: str, idx: int) -> str:
    """生成可读的落盘文件名。

    早期版本直接用 ``{src}_{title}_{stamp}_{i}.md``，结果文献列表里
    出现 ``openalex_..._20261015-213024_0.md`` 这种又长又重复的名字
    （同一批导入的文件名几乎一模一样，肉眼无法区分）。
    现在用 **序号 + 短标题**，时间戳单独放在文件头部的元数据里。
    """
    title = (item.get("title") or "").strip()
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title).strip()
    safe = re.sub(r"\s+", " ", safe)[:48].rstrip(". ")
    if not safe:
        safe = "untitled"
    sid = re.sub(r"[^a-z0-9_]", "", (item.get("source") or "web").lower()) or "web"
    return f"{idx + 1:02d}_{sid}_{safe}.md"


def paper_to_markdown(item: Dict[str, Any]) -> str:
    """把一条云端文献渲染成可索引的 Markdown。

    导入本地库走 kb.add_document，需要真实落盘文件；此函数生成纯文本题录+
    摘要，供 /api/kb/{name}/web-import 写入临时文件后索引。
    """
    lines = [f"# {item.get('title') or 'Untitled'}", ""]
    meta = []
    if item.get("authors"):
        meta.append(f"- 作者：{item['authors']}")
    if item.get("year"):
        meta.append(f"- 年份：{item['year']}")
    if item.get("venue"):
        meta.append(f"- 出处：{item['venue']}")
    if item.get("doi"):
        meta.append(f"- DOI：{item['doi']}")
    if item.get("url"):
        meta.append(f"- 链接：{item['url']}")
    if item.get("oa_url"):
        meta.append(f"- 开放获取全文：{item['oa_url']}")
    if item.get("cited_by"):
        meta.append(f"- 被引：{item['cited_by']}")
    src = item.get("source_label") or item.get("source")
    if src:
        meta.append(f"- 数据源：{src}")
    lines.extend(meta)
    if item.get("abstract"):
        lines += ["", "## 摘要", "", item["abstract"]]
    lines += ["", "> 由 MatLens 从云端学术 API 导入的题录（仅元数据与摘要，非全文）。"]
    return "\n".join(lines)
