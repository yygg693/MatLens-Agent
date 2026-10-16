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
