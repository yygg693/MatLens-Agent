# -*- coding: utf-8 -*-
"""MatLens · 数据集源（Zenodo / HuggingFace）。

为什么要有这个模块
------------------
论文源（OpenAlex/Crossref/arxiv…）只能找到**文献**。但材料实验里大量关键
信息不在论文里，而在公开数据集：

- SCAPS-1D 模拟输出、DFT 计算结果、XRD 原始谱、电池循环数据
- 这些常发布在 Zenodo（HuggingFace 上更多是 NLP 数据，材料类较少）

调研时的空白（见 docs/kb_cloud_sources_research.md）就是这一块。

合规
----
- Zenodo / HuggingFace 都有**公开 API**，且 Zenodo 记录通常带
  CC-BY / CC0 等开放许可证 → 属于「合法可编程访问」，与知网/维普完全不同。
- 只取**元数据**与**许可证信息**；文件下载由用户显式触发（体积可能上百 MB），
  不做后台批量抓取。

实测备注（2026-10-29）
---------------------
- Zenodo API 稳定，``q=`` 全文检索可用（材料关键词命中率高）
- **HuggingFace 国内直连超时**（实测 WinError 10060），故默认不勾选，
  保留在源目录里供用户按需开启/换代理
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Any, Dict, List, Optional

from matlens_kit.rag.scholarly import _get_json

# ⚠️ User-Agent 必须是 latin-1 可编码的 —— HTTP 头不允许非 ASCII。
# 早期写成中文 UA，requests/urllib 会抛 UnicodeEncodeError（实测踩过）。
_UA = {"User-Agent": "MatLens/0.1 (materials-chemistry research tool)"}


def _strip_html(html: str) -> str:
    """Zenodo 的 description 是 HTML，需转纯文本。

    ⚠️ 必须解完整 HTML 实体集 —— Zenodo 描述里常见 ``&aring;`` / ``&deg;``
    这类命名实体（实测描述里会出现 "Lule&aring;"），漏解会让描述里
    混进 ``&xxx;`` 字面量，进了 prompt 就很难看。
    """
    if not html:
        return ""
    t = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    t = re.sub(r"</p\s*>", "\n\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    # html.unescape 解全部实体（含 &aring; &deg; &#176; 等命名/数字实体）
    try:
        import html as _html

        t = _html.unescape(t)
    except Exception:
        t = (t.replace("&nbsp;", " ").replace("&amp;", "&")
               .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"'))
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _fmt_size(n: Any) -> str:
    try:
        n = float(n)
    except Exception:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


#: 自检模式标志。为 True 时不重试 —— 自检要快速反馈，
#: 重试会把 5s 超时翻倍（实测整体自检 25s，其中 HuggingFace 占 16.9s）。
_PROBE_MODE = False


def _set_probe_mode(on: bool) -> None:
    """切换自检模式（免重试）。"""
    global _PROBE_MODE
    _PROBE_MODE = bool(on)


def search_zenodo(query: str, limit: int = 8,
                  timeout: float = 15.0) -> List[Dict[str, Any]]:
    """Zenodo 数据集检索。

    ⚠️ 必须在**服务端**用 ``type=dataset`` 过滤（实测）：
    - Zenodo 上论文数量远多于数据集（"solid oxide fuel cell" 命中 49 万，
      其中前 5 条全是 journal article）
    - 客户端过滤会漏掉 subtype 变体（dataset 下还有 publication/dataset 混合），
      且白跑一趟无用请求
    """
    url = ("https://zenodo.org/api/records?q=" + urllib.parse.quote(query)
           + f"&size={max(8, min(limit * 3, 50))}&sort=bestmatch&type=dataset")
    d = _get_json(url, timeout=timeout, headers=_UA,
                  retries=0 if _PROBE_MODE else 1)
    hits = (d.get("hits") or {}).get("hits") or []

    out: List[Dict[str, Any]] = []
    for h in hits:
        m = h.get("metadata") or {}
        title = (m.get("title") or "").strip()
        if not title:
            continue
        # resource_type 是 dict：{"type": "dataset", "subtype": None}
        rt = m.get("resource_type") or {}
        rtype = (rt.get("type") if isinstance(rt, dict) else str(rt) or "").lower()

        raw_files = h.get("files") or []
        # ⚠️ Zenodo 的 type=dataset 里仍混着「无文件的论文补充材料记录」
        #    （实测：DOI 是出版商的 10.1002/xxx，files=[]）。
        #    这些条目对用户无用（没有数据可拿），且会挤占检索结果 ——
        #    故**以有无实际文件**为准过滤，而不是信任 type 字段。
        if not raw_files:
            continue

        doi = (h.get("doi") or m.get("doi") or "").strip()
        lic = (m.get("license") or {})
        files = []
        for f in (h.get("files") or [])[:8]:
            link = (f.get("links") or {}).get("self") or ""
            files.append({
                "key": f.get("key") or "",
                "size": f.get("size") or 0,
                "size_human": _fmt_size(f.get("size")),
                "url": link,
                "type": (f.get("type") or "").split("/")[-1] if f.get("type") else "",
            })
        total_size = sum(f.get("size") or 0 for f in (h.get("files") or []))

        creators = [c.get("name", "") for c in (m.get("creators") or [])][:6]
        desc = _strip_html(m.get("description") or "")
        keywords = m.get("keywords") or []
        if isinstance(keywords, str):
            keywords = [k.strip() for k in keywords.split(",") if k.strip()]

        out.append({
            "id": str(h.get("id") or doi or title[:40]),
            "title": title,
            "source": "Zenodo",
            "source_id": "zenodo",
            "kind": "dataset",
            "doi": doi,
            "authors": ", ".join(c for c in creators if c),
            "year": (m.get("publication_date") or "")[:4],
            "date": m.get("publication_date") or "",
            "journal": "Zenodo 数据集",
            "url": (h.get("links") or {}).get("self") or
                   (h.get("links") or {}).get("html") or "",
            "landing_page": (h.get("links") or {}).get("html") or "",
            "abstract": desc[:1500],
            "description": desc,
            "keywords": [str(k) for k in keywords][:10],
            "license": lic.get("id") or (lic if isinstance(lic, str) else ""),
            "access_right": m.get("access_right") or "",
            "files": files,
            "file_count": len(h.get("files") or []),
            "total_size": total_size,
            "total_size_human": _fmt_size(total_size),
            "resource_type": rtype or "dataset",
            "resource_subtype": (rt.get("subtype") if isinstance(rt, dict) else "") or "",
            "resource_label": (rt.get("title") if isinstance(rt, dict) else "") or "",
            "concept_doi": h.get("conceptdoi") or "",
            "version": h.get("revision") or "",
        })
        if len(out) >= limit:
            break
    return out


def search_huggingface(query: str, limit: int = 8,
                       timeout: float = 15.0) -> List[Dict[str, Any]]:
    """HuggingFace 数据集检索。

    ⚠️ 实测国内直连超时（WinError 10060），故**默认不勾选**此源；
    保留实现供用户换代理或在境外网络环境下启用。
    """
    url = ("https://huggingface.co/api/datasets?search="
           + urllib.parse.quote(query) + f"&limit={max(1, min(limit, 50))}")
    d = _get_json(url, timeout=timeout, headers=_UA,
                  retries=0 if _PROBE_MODE else 1)
    out: List[Dict[str, Any]] = []
    for x in (d or [])[:limit]:
        did = x.get("id") or ""
        if not did:
            continue
        tags = x.get("tags") or []
        out.append({
            "id": did,
            "title": did,
            "source": "HuggingFace",
            "source_id": "huggingface",
            "kind": "dataset",
            "doi": "",
            "authors": (x.get("author") or {}).get("name", "") if isinstance(x.get("author"), dict)
                      else (x.get("author") or ""),
            "year": str(x.get("createdAt") or "")[:4],
            "date": (x.get("createdAt") or "")[:10],
            "journal": "HuggingFace 数据集",
            "url": "https://huggingface.co/datasets/" + did,
            "landing_page": "https://huggingface.co/datasets/" + did,
            "abstract": "",
            "description": "",
            "keywords": [str(t) for t in tags][:10],
            "license": "",   # HF 许可在 tags 里，单独标出
            "files": [],
            "file_count": 0,
            "total_size": 0,
            "total_size_human": "",
            "downloads": x.get("downloads") or 0,
            "likes": x.get("likes") or 0,
        })
    return out


#: 数据集源注册表（与 scholarly.SEARCHERS 同一签名，便于统一调度）
DATASET_SEARCHERS = {
    "zenodo": search_zenodo,
    "huggingface": search_huggingface,
}

#: 默认勾选：Zenodo 实测稳定；HuggingFace 国内直连超时，默认不勾。
DEFAULT_DATASET_SOURCES = ["zenodo"]

#: 源元信息（供 /api/kb/sources 展示）
DATASET_SOURCE_INDEX: Dict[str, Dict[str, Any]] = {
    "zenodo": {
        "id": "zenodo",
        "label": "Zenodo 数据集",
        "kind": "dataset",
        "note": "CERN 主办，开放许可证（常为 CC-BY）。覆盖材料模拟与实验数据。",
        "configured": True,
        "needs_key": False,
        "default_on": True,
    },
    "huggingface": {
        "id": "huggingface",
        "label": "HuggingFace 数据集",
        "kind": "dataset",
        "note": "实测国内直连超时（WinError 10060），默认不勾选；"
                "材料类内容少于 NLP，可在换代理后手动开启。",
        "configured": True,
        "needs_key": False,
        "default_on": False,
    },
}


def search_datasets(query: str, sources: Optional[List[str]] = None,
                    per_source: int = 6, timeout: float = 15.0) -> Dict[str, Any]:
    """多源数据集检索（并发），返回与 scholarly.search_web 同构的结果。"""
    import concurrent.futures
    import time

    srcs = [s for s in (sources or DEFAULT_DATASET_SOURCES)
            if s in DATASET_SEARCHERS]
    t0 = time.time()
    out: List[Dict[str, Any]] = []
    per: Dict[str, Any] = {}

    # ⚠️ 空查询会让 Zenodo 返回「最近上传的任意数据集」—— 对用户毫无意义
    # （实测会返回 ok=True 且内容与关键词无关）。这里直接拒绝。
    if not (query or "").strip():
        return {"ok": False, "count": 0, "items": [], "per_source": {},
                "elapsed_ms": 0, "error": "查询词不能为空"}

    if not srcs:
        return {"ok": False, "count": 0, "items": [], "per_source": {},
                "elapsed_ms": 0, "error": "没有可用的数据集源"}

    def _run(sid: str):
        return DATASET_SEARCHERS[sid](query, per_source, timeout)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(srcs))) as ex:
        futs = {ex.submit(_run, s): s for s in srcs}
        for fut in concurrent.futures.as_completed(futs):
            sid = futs[fut]
            label = DATASET_SOURCE_INDEX.get(sid, {}).get("label", sid)
            try:
                got = fut.result()
                per[sid] = {"ok": True, "n": len(got), "label": label}
                out.extend(got)
            except Exception as e:  # noqa: BLE001
                per[sid] = {"ok": False, "n": 0, "label": label,
                            "error": f"{type(e).__name__}: {str(e)[:90]}"}

    # 去重（按 DOI 或标题）
    seen = set()
    uniq = []
    for it in out:
        k = (it.get("doi") or it.get("title") or "").strip().lower()[:80]
        if k and k in seen:
            continue
        seen.add(k)
        uniq.append(it)

    return {
        "ok": bool(uniq),
        "count": len(uniq),
        "items": uniq,
        "per_source": per,
        "elapsed_ms": int((time.time() - t0) * 1000),
        "kind": "dataset",
    }


def fetch_record_files(record_id: str, timeout: float = 15.0) -> Dict[str, Any]:
    """取某个 Zenodo 记录的完整文件清单（用于导入前确认体积）。

    只读元数据，不下载文件本身 —— 数据集动辄上百 MB，
    是否下载应由用户显式决定。
    """
    url = f"https://zenodo.org/api/records/{urllib.parse.quote(str(record_id))}"
    d = _get_json(url, timeout=timeout, headers=_UA,
                  retries=0 if _PROBE_MODE else 1)
    m = d.get("metadata") or {}
    files = []
    total = 0
    for f in (d.get("files") or []):
        link = (f.get("links") or {}).get("self") or ""
        size = f.get("size") or 0
        total += size
        files.append({
            "key": f.get("key") or "",
            "size": size,
            "size_human": _fmt_size(size),
            "url": link,
            "type": (f.get("type") or "").split("/")[-1] if f.get("type") else "",
        })
    return {
        "ok": True,
        "id": str(d.get("id") or record_id),
        "title": (m.get("title") or "").strip(),
        "doi": (d.get("doi") or "").strip(),
        "license": (m.get("license") or {}).get("id", "") if isinstance(m.get("license"), dict) else "",
        "files": files,
        "file_count": len(files),
        "total_size": total,
        "total_size_human": _fmt_size(total),
        "description": _strip_html(m.get("description") or ""),
    }
