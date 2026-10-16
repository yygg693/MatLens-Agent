# -*- coding: utf-8 -*-
"""MatLens 工具 · 网页/文献抓取（toolset: matlens_web）。

把 web_fetcher 暴露成 Agent 可调用的工具，让「搜到文献 → 拿到正文」
这条链路真正闭环。论文写作、文献综述里，题录只够引用，真正要读的是正文。

**合规边界（与 web_fetcher 一致）**
只抓公开可访问内容；遵守 robots.txt；不绕过付费墙/验证码/反爬；
User-Agent 如实标识。遇到访问受限就如实报告，让 Agent 换路径
（Unpaywall 找 OA 版本 / 机构订阅），而不是硬刚。

工具：
- ``web_fetch``        抓单页：正文 + 元数据（标题/作者/DOI/期刊/PDF 链接）
- ``web_fetch_batch``  批量抓（多文献同时取正文，同域自动限速）
- ``web_capabilities`` 自检当前环境抓取能力与合规策略
"""
from __future__ import annotations

import os
from typing import Any, Dict, List

from tools.registry import registry, tool_result

# ────────────────────────────────────────────────────────────
# Schema
# ────────────────────────────────────────────────────────────
WEB_FETCH_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": (
        "抓取公开网页/PDF 的正文与学术元数据（标题、作者、DOI、期刊、摘要、PDF 链接）。"
        "遵守 robots.txt，不绕过付费墙或反爬；受限时会在 reason 中说明原因。"
    ),
    "examples": [
        {"url": "https://arxiv.org/abs/1404.3036"},
        {"url": "https://doi.org/10.1039/C4CP00856A", "with_text": True},
    ],
    "properties": {
        "url": {"type": "string", "description": "目标 URL（支持 arxiv abs 页、DOI 链接、期刊文章页、PDF 直链）"},
        "with_text": {"type": "boolean", "description": "是否返回正文全文（默认 true；只要元数据可设 false）"},
        "timeout": {"type": "number", "description": "单页超时秒数（默认 20）"},
        "max_chars": {"type": "integer", "description": "正文最大返回字符数（默认 20000，防止撑爆上下文）"},
    },
    "required": ["url"],
    "additionalProperties": False,
}

WEB_FETCH_BATCH_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": (
        "批量抓取多个文献页面正文。适合已在知识库/云端检索中拿到一批 DOI 或 URL，"
        "需要逐篇读正文时使用。最多 8 个 URL。"
    ),
    "examples": [{"urls": ["https://arxiv.org/abs/1404.3036"]}],
    "properties": {
        "urls": {"type": "array", "items": {"type": "string"}, "description": "URL 列表（最多 8 个）"},
        "max_chars": {"type": "integer", "description": "每篇正文最大返回字符数（默认 8000）"},
        "timeout": {"type": "number", "description": "单页超时秒数（默认 20）"},
    },
    "required": ["urls"],
    "additionalProperties": False,
}

WEB_CAPABILITIES_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": "查询当前环境的网页抓取能力（是否装了正文抽取增强 / PDF 解析）与合规策略说明。",
    "examples": [{}],
    "properties": {},
    "additionalProperties": False,
}

MAX_BATCH = 8
DEFAULT_MAX_CHARS = 20000


# ────────────────────────────────────────────────────────────
# 工具实现
# ────────────────────────────────────────────────────────────
def web_fetch_tool(url: str, with_text: bool = True, timeout: float = 20.0,
                   max_chars: int = DEFAULT_MAX_CHARS, **_) -> Dict[str, Any]:
    """抓单页。返回给 Agent 的结构化结果。"""
    from matlens_kit.web import web_fetcher as wf

    try:
        res = wf.fetch_cached(str(url), with_text=bool(with_text), timeout=float(timeout))
    except Exception as e:  # noqa: BLE001
        return {"success": False, "url": url, "reason": f"{type(e).__name__}: {e}"}

    out: Dict[str, Any] = {
        "success": bool(res.get("ok")),
        "url": res.get("url") or url,
        "robots": res.get("robots"),
    }
    if not res.get("ok"):
        out["reason"] = res.get("reason") or "抓取失败"
        if res.get("note_policy"):
            out["note_policy"] = res["note_policy"]
        out["hint"] = _hint_for_failure(res.get("status"), res.get("reason", ""))
        return out

    out["status"] = res.get("status")
    out["content_type"] = res.get("content_type")
    out["engine"] = res.get("engine")
    out["elapsed_ms"] = res.get("elapsed_ms")

    for k in ("title", "doi", "journal", "date", "volume", "issue",
              "firstpage", "abstract", "pdf_url"):
        if res.get(k):
            out[k] = res[k]
    if res.get("authors"):
        out["authors"] = res["authors"]

    text = res.get("text") or ""
    if text:
        cap = max(200, int(max_chars))
        out["text"] = text[:cap]
        out["text_chars"] = len(text)
        out["truncated"] = len(text) > cap
    else:
        out["text"] = ""
        out["notes"] = res.get("notes") or ["未抽取出正文"]
    if res.get("rate_limit_wait_ms"):
        out["rate_limit_wait_ms"] = res["rate_limit_wait_ms"]
    return out


def _hint_for_failure(status: Any, reason: str) -> str:
    """失败时给 Agent 一个**可执行**的下一步，而不是让它反复重试。"""
    s = str(status or "")
    if s in ("401", "403") or "403" in reason or "401" in reason:
        return ("站点拒绝访问：可能是机构订阅限制或触发反爬。"
                "建议改走开放获取渠道（Unpaywall 按 DOI 查 OA 全文 / arXiv 预印本），"
                "或提示用户提供已订阅的导出文件。MatLens 不绕过访问控制。")
    if s == "404":
        return "页面不存在：核对 DOI 是否正确，或该文献可能尚未公开。"
    if s == "429":
        return "触发限流：请降低抓取频率或稍后重试（我们已内置同域限速）。"
    if "robots" in reason.lower():
        return "robots.txt 禁止抓取该路径：请让用户人工检索后导出题录，或改用开放 API。"
    if "429" in reason:
        return "触发对方限流：稍后重试，或减少单次批量数量。"
    return "建议换用开放获取版本（arXiv / 机构知识库）或让用户手动提供文件。"


def web_fetch_batch_tool(urls: List[str], max_chars: int = 8000,
                         timeout: float = 20.0, **_) -> Dict[str, Any]:
    """批量抓取（同域自动限速，单篇失败不影响其他）。"""
    from matlens_kit.web import web_fetcher as wf

    urls = [str(u) for u in (urls or []) if u][:MAX_BATCH]
    if not urls:
        return {"success": False, "reason": "urls 为空"}

    results = wf.fetch_many(urls, with_text=True, timeout=float(timeout))
    items: List[Dict[str, Any]] = []
    ok_n = 0
    cap = max(200, int(max_chars))
    for r in results:
        if r.get("ok"):
            ok_n += 1
            item = {
                "url": r.get("url"),
                "title": r.get("title", ""),
                "doi": r.get("doi", ""),
                "journal": r.get("journal", ""),
                "authors": (r.get("authors") or [])[:5],
                "pdf_url": r.get("pdf_url", ""),
                "text": (r.get("text") or "")[:cap],
                "text_chars": r.get("text_chars", 0),
                "engine": r.get("engine", ""),
            }
        else:
            item = {
                "url": r.get("url"),
                "ok": False,
                "reason": r.get("reason", ""),
                "hint": _hint_for_failure(r.get("status"), r.get("reason", "")),
            }
        items.append(item)

    return {
        "success": ok_n > 0,
        "ok_count": ok_n,
        "total": len(urls),
        "items": items,
        "note": (f"{ok_n}/{len(urls)} 篇抓取成功。"
                 "未成功的已给出 hint，请据此改用开放获取渠道，勿重复重试。"),
    }


def web_capabilities_tool(**_) -> Dict[str, Any]:
    """能力自检 + 合规策略。"""
    from matlens_kit.web import web_fetcher as wf
    return wf.capabilities()


# ────────────────────────────────────────────────────────────
# 注册
# ────────────────────────────────────────────────────────────
registry.register(
    name="web_fetch",
    toolset="matlens_web",
    schema=WEB_FETCH_SCHEMA,
    handler=lambda args, **kw: tool_result(web_fetch_tool(**args)),
    check_fn=lambda: True,
    description="抓取公开网页/PDF 的正文与学术元数据（遵守 robots.txt，不绕过付费墙与反爬）",
    emoji="🌐",
)

registry.register(
    name="web_fetch_batch",
    toolset="matlens_web",
    schema=WEB_FETCH_BATCH_SCHEMA,
    handler=lambda args, **kw: tool_result(web_fetch_batch_tool(**args)),
    check_fn=lambda: True,
    description="批量抓取多篇文献正文（同域限速，单篇失败不阻塞其他）",
    emoji="📚",
)

registry.register(
    name="web_capabilities",
    toolset="matlens_web",
    schema=WEB_CAPABILITIES_SCHEMA,
    handler=lambda args, **kw: tool_result(web_capabilities_tool(**args)),
    check_fn=lambda: True,
    description="查询当前环境的抓取能力与合规策略说明",
    emoji="🛡️",
)
