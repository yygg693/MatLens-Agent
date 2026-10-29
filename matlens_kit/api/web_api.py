# -*- coding: utf-8 -*-
"""MatLens Web 服务层 —— 网页抓取 API（/api/web）。

封装 matlens_kit.web.web_fetcher。给前端「云端 API」知识库页提供
「搜到文献 → 抓正文 → 入本地库」闭环中缺失的抓取环节。

- GET  /api/web/capabilities  能力自检 + 合规策略（前端要如实展示）
- POST /api/web/fetch         抓单页
- POST /api/web/fetch-batch   批量抓
- POST /api/web/to-kb         抓到的正文写入知识库（Markdown）

合规：全部走 web_fetcher 的 robots 检查与限速，服务端不提供任何
绕过参数（无 headless 开关、无代理池、无 stealth 开关）——
这是有意的：绕过能力不应该存在于产品接口里。
"""
from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

_router = APIRouter(prefix="/api/web", tags=["web"])

MAX_BATCH = 8


@_router.get("/capabilities")
def capabilities() -> Dict[str, Any]:
    """当前环境抓取能力与合规策略。"""
    from matlens_kit.web import web_fetcher as wf

    return wf.capabilities()


@_router.get("/privacy")
def privacy() -> Dict[str, Any]:
    """隐私 / 追踪向量审计报告。

    逐类说明「哪些已阻断、哪些代码控不了、要控住得靠什么」——
    而不是含糊地说「已反追踪」。
    """
    from matlens_kit.web import web_fetcher as wf

    return wf.privacy_report()


@_router.get("/proxy-check")
def proxy_check(proxy: str = "") -> Dict[str, Any]:
    """实测出口 IP：确认代理**真的生效**。

    这是反追踪的关键 —— 配置写错或代理没启动时，请求会照常直连，
    而界面看上去一切正常。这里对比直连 IP 与经代理 IP，
    两者不同才说明保护生效。
    """
    from matlens_kit.web import web_fetcher as wf

    return wf.check_proxy(explicit_proxy=(proxy or "").strip())


@_router.get("/proxy/config")
def proxy_config() -> Dict[str, Any]:
    """读取代理配置 + 轮换状态 + 能力说明（设置页「网络隐私」面板用）。"""
    from matlens_kit.web import proxy_manager as pm
    from matlens_kit.web import web_fetcher as wf

    cfg = pm.get_config()
    return {
        "config": cfg,
        "effective": wf._mask_proxy(pm.effective_proxy()) if pm.effective_proxy() else "",
        "in_use": bool(pm.effective_proxy()),
        "rotate": pm.rotate_status(),
        "supported_schemes": list(pm.SUPPORTED_SCHEMES),
        "newnym_min_interval_s": pm.NEWNYM_MIN_INTERVAL,
        "why_tor": (
            "自动换 IP 由 Tor 的 NEWNYM 信号实现，不使用随机免费代理池 —— "
            "那些代理的运营者能看到全部流量明文，隐藏身份反而交给了陌生人；"
            "而频繁换 IP 本身会打出「同一客户端在轮换」的规律，更易被关联。"
            "Tor 的换线路是协议自带标准动作，中继为志愿者，来源可信。"
        ),
        "blocked_sites": len(wf.BLOCKED_SITES),
    }


@_router.post("/proxy/rotate")
def proxy_rotate(payload: Dict[str, Any] = None) -> Dict[str, Any]:
    """手动请求新出口 IP（Tor NEWNYM）。

    Tor 对同一流量有最小换线路间隔（约 11s），连点无效 ——
    接口会如实返回 skipped 与建议等待秒数，而不是假装成功。
    """
    from matlens_kit.web import proxy_manager as pm

    payload = payload or {}
    addr = (payload.get("control") or "").strip()
    res = pm.tor_newnym(addr=addr)
    res["status"] = pm.rotate_status()
    return res


@_router.get("/blocked-sites")
def blocked_sites() -> Dict[str, Any]:
    """明令禁止抓取的站点清单与替代路径。"""
    from matlens_kit.web import web_fetcher as wf

    return {
        "count": len(wf.BLOCKED_SITES),
        "sites": [{"host": h, "reason": r} for h, r in sorted(wf.BLOCKED_SITES.items())],
        "enforcement": "在 robots 检查之前拦截；无任何绕过开关",
    }


@_router.post("/fetch")
def fetch(payload: Dict[str, Any] = None) -> Dict[str, Any]:
    """抓单个 URL。"""
    from matlens_kit.web import web_fetcher as wf

    payload = payload or {}
    url = (payload.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url 必填")
    try:
        timeout = float(payload.get("timeout") or 20.0)
    except (TypeError, ValueError):
        timeout = 20.0
    try:
        max_chars = int(payload.get("max_chars") or 20000)
    except (TypeError, ValueError):
        max_chars = 20000
    res = wf.fetch_cached(url, with_text=bool(payload.get("with_text", True)),
                          timeout=max(5.0, min(timeout, 60.0)))
    return _cap(res, max_chars)


@_router.post("/fetch-batch")
def fetch_batch(payload: Dict[str, Any] = None) -> Dict[str, Any]:
    """批量抓多个 URL（同域限速，单篇失败不阻塞其他）。"""
    from matlens_kit.web import web_fetcher as wf

    payload = payload or {}
    urls = [str(u).strip() for u in (payload.get("urls") or []) if str(u).strip()]
    if not urls:
        raise HTTPException(status_code=400, detail="urls 不能为空")
    if len(urls) > MAX_BATCH:
        raise HTTPException(status_code=400, detail=f"一次最多 {MAX_BATCH} 个 URL")
    try:
        max_chars = int(payload.get("max_chars") or 8000)
    except (TypeError, ValueError):
        max_chars = 8000
    try:
        timeout = float(payload.get("timeout") or 20.0)
    except (TypeError, ValueError):
        timeout = 20.0

    results = wf.fetch_many(urls, with_text=True, timeout=max(5.0, min(timeout, 60.0)))
    out = [_cap(r, max_chars) for r in results]
    ok_n = sum(1 for r in out if r.get("ok"))
    return {"ok_count": ok_n, "total": len(out), "items": out,
            "note": f"{ok_n}/{len(out)} 篇抓取成功。未成功的已给出 hint，"
                    "请据此改用开放获取渠道，勿重复重试。"}


# ────────────────────────────────────────────────────────────
# 文献 OA 全文解析与抓取（2026-10-29）
#
# 场景：论文工坊检索到一批文献，但只有题录没有正文 → 写作时无法引用
# 具体结论。Unpaywall 能按 DOI 解析出**合法**开放获取版本
# （作者自存 / 机构库 / 预印本），实测能把「0 字符」变成 64004 字全文。
#
# 合规：与 web_fetcher 完全一致 —— 遵守 robots、只取合法 OA 版本、
# 明令禁止的站点不降级。抓不到就如实报告，绝不编造正文。
# ────────────────────────────────────────────────────────────
@_router.post("/resolve-oa")
def resolve_oa_fulltext(payload: Dict[str, Any] = None) -> Dict[str, Any]:
    """按 DOI 找合法 OA 全文版本，并（可选）抓取正文。

    body: ``{doi, title, authors, year, kb?, fetch?: true}``

    返回 ``{ok, is_oa, oa_status, oa_url, text?, text_chars?, kb?, note}``。
    - ``fetch=false``（默认）：只解析链接，不抓正文 —— 快、零流量
    - ``fetch=true``：抓正文；给了 ``kb`` 就顺便写进该知识库
    """
    from matlens_kit.rag import scholarly
    from matlens_kit.web import web_fetcher as wf

    payload = payload or {}
    doi = (payload.get("doi") or "").strip()
    if not doi:
        raise HTTPException(status_code=400, detail="doi 必填")

    try:
        oa = scholarly.fetch_unpaywall(doi)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"OA 解析失败：{str(e)[:140]}")

    out: Dict[str, Any] = {
        "ok": True,
        "doi": doi,
        "is_oa": bool(oa.get("is_oa")),
        "oa_status": oa.get("oa_status", ""),
        "oa_url": oa.get("oa_url") or "",
        "host_type": oa.get("host_type") or "",
        "license": oa.get("license") or "",
    }

    if not out["is_oa"] or not out["oa_url"]:
        out["ok"] = False
        out["note"] = ("该文献没有合法开放获取版本"
                       f"（{out['oa_status'] or 'closed'}）—— "
                       "closed 表示只开放阅读、不提供可直取全文；"
                       "bronze 需机构订阅。正文请手动下载 PDF 后上传。")
        return out

    if not payload.get("fetch"):
        out["note"] = (f"找到开放获取版本（{out['oa_status']}）。"
                       "勾选「抓取正文」可把全文抓下来并索引进知识库。")
        return out

    # 抓正文（内含 robots 检查 + 同域判断 + 降级链）
    #
    # ⚠️ 必须**遍历全部候选位置**：Unpaywall 的 best 位置常指向出版商域名
    # （robots 多半禁止抓），而同一条记录里往往还有 repository 镜像
    # （PMC / 机构库）可以抓。实测 10.3390/membranes12090896 就是这种情况：
    # best=mdpi.com（robots 禁止）→ 换成 ncbi PMC 成功。
    candidates = []
    for a in (oa.get("alternatives") or []):
        u = a.get("url") or ""
        if u and u not in candidates:
            candidates.append(u)
    if out["oa_url"] and out["oa_url"] not in candidates:
        candidates.insert(0, out["oa_url"])

    if not candidates:
        out["ok"] = False
        out["note"] = "Unpaywall 记录里没有可用的全文链接"
        return out

    tried: List[str] = []
    res: Dict[str, Any] = {}
    for url in candidates[:6]:
        tried.append(url)
        try:
            res = wf.fetch(url, with_text=True,
                           timeout=float(payload.get("timeout") or 25.0))
        except Exception as e:  # noqa: BLE001
            out.setdefault("tried", []).append({"url": url, "error": f"{type(e).__name__}"})
            continue
        if res.get("ok") and (res.get("text") or "").strip():
            break
        out.setdefault("tried", []).append({
            "url": url,
            "error": str(res.get("oa_fallback_error") or res.get("reason") or "未取到正文")[:120],
        })

    out["tried"] = out.get("tried", [])[:6]
    text = (res.get("text") or "").strip()
    if not text:
        # ── 兜底：Europe PMC 官方 API ──
        # Unpaywall 给的链接常在出版商域名，而那些站点的 robots 往往
        # 禁止抓（实测 MDPI 与 NCBI PMC 都在 Disallow 列表里）。
        # **robots 是站点的明确声明，绕过即违规** —— 所以不能靠"换镜像硬抓"，
        # 而要转向**正规 API**：Europe PMC（EBI）提供全文 XML，合法可编程访问。
        try:
            from matlens_kit.rag import scholarly as _sch

            epmc = _sch.fetch_europepmc_fulltext(doi, timeout=float(payload.get("timeout") or 25.0))
            if epmc.get("ok"):
                out["ok"] = True
                out["text"] = epmc["text"][:20000]
                out["text_chars"] = len(epmc["text"])
                out["engine"] = "europepmc-xml"
                out["resolved_via"] = epmc.get("via") or "Europe PMC 官方 API"
                out["pmcid"] = epmc.get("pmcid") or ""
                text = epmc["text"]
                out.setdefault("tried", []).append(
                    {"url": "Europe PMC API", "error": "", "ok": True})
            else:
                out.setdefault("tried", []).append(
                    {"url": "Europe PMC API", "error": str(epmc.get("error") or "")[:100]})
        except Exception as e:  # noqa: BLE001
            out.setdefault("tried", []).append(
                {"url": "Europe PMC API", "error": f"{type(e).__name__}"})

    if not text:
        out["ok"] = False
        reasons = "；".join(
            str(t.get("error") or "")[:44] for t in out.get("tried", [])[:3]
        ) or "未知原因"
        out["note"] = ("已尝试 " + str(len(out.get("tried", []))) +
                       " 个开放获取位置都拿不到正文：" + reasons +
                       "。可能是出版商付费墙 / robots 限制 / 页面为 JS 动态渲染，"
                       "请手动下载 PDF 后上传。")
        return out

    out["text"] = text[:20000]
    out["text_chars"] = len(text)
    # ⚠️ 用 setdefault：Europe PMC 兜底路径已经设过 engine/resolved_via，
    # 这里若直接赋值会把它覆盖成空（实测过）。
    out.setdefault("engine", res.get("engine") or "")
    out.setdefault("resolved_via", res.get("resolved_via") or "")

    # 可选：写进知识库
    kb_name = (payload.get("kb") or "").strip()
    if kb_name:
        from matlens_cli.config import get_matlens_home
        from matlens_kit.plugins.local_rag import get_manager

        mgr = get_manager()
        if kb_name not in mgr.list_kbs():
            raise HTTPException(status_code=404, detail=f"知识库 {kb_name} 不存在")
        kb = mgr.get(kb_name)

        title = (payload.get("title") or "").strip() or ("OA-" + doi)
        out_dir = get_matlens_home() / "uploads" / "oa" / time.strftime("%Y%m%d")
        out_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title).strip()
        safe = re.sub(r"\s+", " ", safe)[:56].rstrip(". ") or "untitled"
        doi_key = re.sub(r"[^A-Za-z0-9]", "_", doi)
        p = out_dir / f"{safe}__{doi_key}.md"

        md = [f"# {title}", ""]
        if payload.get("authors"):
            md.append("- 作者：" + str(payload["authors"]))
        if payload.get("year"):
            md.append("- 年份：" + str(payload["year"]))
        md.append("- DOI：" + doi)
        md.append("- 开放获取：" + out["oa_status"] +
                  (f"（{out['license']}）" if out.get("license") else ""))
        md.append("- 全文链接：" + out["oa_url"])
        md += ["", "## 正文", "", text[:20000]]
        try:
            p.write_text("\n".join(md), encoding="utf-8")
            add = kb.add_documents([str(p)])
            out["kb"] = kb_name
            out["indexed"] = True
            out["add"] = add
            out["note"] = (f"已抓取正文 {len(text)} 字并索引进「{kb_name}」，"
                           "写作时 RAG 就能检索到这篇的正文了。")
        except Exception as e:  # noqa: BLE001
            out["indexed"] = False
            out["note"] = (f"正文已抓取（{len(text)} 字），但写入知识库失败："
                           f"{type(e).__name__}")
    else:
        out["note"] = f"已抓取正文 {len(text)} 字（未入库，可指定 kb 参数直接沉淀）"

    return out


@_router.post("/to-kb")
def to_kb(payload: Dict[str, Any] = None) -> Dict[str, Any]:
    """把抓到的页面正文写成 Markdown 并索引进指定知识库。

    场景：云端检索拿到一批文献 → 抓正文 → 沉淀进本地库，
    这样写作时 RAG 检索的是**正文**而不是只有题录。
    """
    from matlens_kit.plugins.local_rag import get_manager
    from matlens_kit.web import web_fetcher as wf

    payload = payload or {}
    kb_name = (payload.get("kb") or "").strip()
    if not kb_name:
        raise HTTPException(status_code=400, detail="kb 必填")
    items = payload.get("items") or []
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=400, detail="items 不能为空（传 [{url,title,...}]）")

    mgr = get_manager()
    if kb_name not in mgr.list_kbs():
        raise HTTPException(status_code=404, detail=f"知识库 {kb_name} 不存在")
    kb = mgr.get(kb_name)

    from matlens_cli.config import get_matlens_home
    out_dir = get_matlens_home() / "uploads" / "web" / time.strftime("%Y%m%d")
    out_dir.mkdir(parents=True, exist_ok=True)

    fetched: List[Dict[str, Any]] = []
    skipped = 0
    n = 0
    for it in items[:MAX_BATCH]:
        if not isinstance(it, dict):
            skipped += 1
            continue
        url = (it.get("url") or "").strip()
        if not url:
            skipped += 1
            continue
        res = wf.fetch_cached(url, with_text=True, timeout=float(payload.get("timeout") or 20.0))
        if not res.get("ok"):
            skipped += 1
            fetched.append({"url": url, "ok": False, "reason": res.get("reason", "")})
            continue
        text = res.get("text") or ""
        title = res.get("title") or url
        md = _page_to_markdown(res, url, title, text)
        safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title).strip()
        safe = re.sub(r"\s+", " ", safe)[:60].rstrip(". ") or "untitled"
        path = out_dir / f"{n + 1:02d}_{safe}.md"
        try:
            path.write_text(md, encoding="utf-8")
        except OSError:
            skipped += 1
            continue
        fetched.append({"url": url, "ok": True, "title": title,
                        "chars": len(text), "file": path.name,
                        "doi": res.get("doi", "")})
        n += 1

    if not n:
        raise HTTPException(status_code=400,
                            detail="没有成功抓取的页面（被拒绝或正文为空）：" +
                                   "; ".join(f.get("reason", "") for f in fetched if not f.get("ok"))[:200])
    try:
        add = kb.add_documents([str(out_dir / f["file"]) for f in fetched if f.get("ok")])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"索引写入失败：{e}")
    return {"ok": True, "kb": kb_name, "imported": n, "skipped": skipped,
            "detail": fetched, **add}


def _cap(res: Dict[str, Any], max_chars: int) -> Dict[str, Any]:
    """裁剪抓取结果体积（前端不需要几十万字符的正文）。"""
    out = {k: v for k, v in res.items() if k != "text"}
    text = res.get("text") or ""
    out["text"] = text[:max(500, max_chars)]
    out["truncated"] = len(text) > max(500, max_chars)
    out["text_chars"] = len(text)
    return out


def _page_to_markdown(res: Dict[str, Any], url: str, title: str, text: str) -> str:
    """抓取页面 → Markdown（题录头 + 正文），供知识库索引。"""
    lines = [f"# {title}", ""]
    meta = [f"- 来源：{url}"]
    if res.get("doi"):
        meta.append(f"- DOI：{res['doi']}")
    if res.get("journal"):
        meta.append(f"- 期刊：{res['journal']}")
    if res.get("date"):
        meta.append(f"- 日期：{res['date']}")
    if res.get("authors"):
        au = res["authors"]
        meta.append("- 作者：" + (", ".join(au[:12]) + (" 等" if len(au) > 12 else "")))
    if res.get("pdf_url"):
        meta.append(f"- PDF：{res['pdf_url']}")
    meta.append(f"- 抓取时间：{res.get('fetched_at', '')}（MatLens 公开网页抓取）")
    lines.extend(meta)
    if res.get("abstract"):
        lines += ["", "## 摘要", "", str(res["abstract"])]
    if text:
        lines += ["", "## 正文", "", text]
    lines += ["", "> 本文档由 MatLens 从公开可访问网页抓取生成，正文原样保留未做改写。"]
    return "\n".join(lines)
