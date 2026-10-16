# -*- coding: utf-8 -*-
"""论文工坊 · 检索增强（正文补全）。

为什么需要这一层
----------------
``paper/search.py`` 的双通道检索（本地 RAG + OpenAlex/Crossref）能拿到**题录**
（题名/作者/年份/DOI），但写作时需要的是**正文**——引言里要写别人的结论、
方法要引用具体做法，只有题录的话 LLM 只能编。

本模块在检索结果之上补一层「抓正文」：
  1. 优先本地知识库（已有全文则直接用，不重复抓）
  2. 其次抓 OA 链接（OpenAlex 直接给 ``open_access.oa_url``）
  3. 再走 Unpaywall 按 DOI 解析（实测 IOP 整站反爬时，靠它拿到 arXiv 版全文）

⚠️ 合规边界与 web_fetcher 完全一致：遵守 robots、只取合法开放获取版本、
明令禁止的站点（知网/维普等）连降级都不做。抓不到就**如实留空**，
绝不用题录拼一段假正文 —— 那样会让写作阶段产出不可验证的引用。
"""
from __future__ import annotations

import concurrent.futures
import time
from typing import Any, Dict, List, Optional

from matlens_kit.paper import search as _search

#: 单篇正文抓取的字符上限（写作 prompt 上下文有限，够引用即可）
MAX_TEXT_CHARS = 6000
#: 并发抓取数（受同域限速约束，不宜过大）
FETCH_WORKERS = 3
#: 每篇最多尝试的候选链接数
MAX_CANDIDATES = 3


def _kb_snippet_for(ref: Dict[str, Any]) -> str:
    """本地知识库已有命中则取其正文片段（比抓网更快更准）。"""
    try:
        title = (ref.get("title") or "").strip()
        if not title:
            return ""
        q = title[:80]
        hits = _search.search_local_kb(q, top_k=2)
        for h in hits:
            snip = (h.get("snippet") or "").strip()
            if len(snip) > 200:
                return snip[:MAX_TEXT_CHARS]
    except Exception:
        return ""
    return ""


def _candidates(ref: Dict[str, Any]) -> List[str]:
    """列出该文献的候选全文链接（按可得性排序）。"""
    out: List[str] = []
    for key in ("oa_url", "pdf_url", "url", "landing_page_url"):
        v = ref.get(key)
        if isinstance(v, str) and v.startswith(("http://", "https://")):
            if v not in out:
                out.append(v)
    return out[:MAX_CANDIDATES]


def fetch_fulltext(ref: Dict[str, Any], timeout: float = 25.0) -> Dict[str, Any]:
    """为单条检索结果补正文。返回增强后的 ref（字段就地补充）。"""
    out = dict(ref)
    out["text"] = ""
    out["text_source"] = ""

    # 1) 本地知识库优先
    snip = _kb_snippet_for(out)
    if snip:
        out["text"] = snip
        out["text_source"] = "local-kb"
        return out

    # 2) 网络抓取（内含 robots 检查 + Unpaywall OA 降级）
    from matlens_kit.web import web_fetcher as wf

    for url in _candidates(out):
        try:
            r = wf.fetch(url, with_text=True, timeout=timeout)
        except Exception as e:  # noqa: BLE001
            out.setdefault("fetch_notes", []).append(f"{url[:48]}：{type(e).__name__}")
            continue
        if r.get("ok") and (r.get("text") or "").strip():
            t = str(r["text"]).strip()
            if len(t) < 200:
                out.setdefault("fetch_notes", []).append(f"{url[:48]}：正文过短，疑似未渲染")
                continue
            out["text"] = t[:MAX_TEXT_CHARS]
            out["text_chars"] = len(t)
            out["text_truncated"] = len(t) > MAX_TEXT_CHARS
            out["text_source"] = ("oa-fallback" if r.get("resolved_via")
                                  else ("pdf" if r.get("is_pdf") else "web"))
            if r.get("resolved_via"):
                out["resolved_via"] = r["resolved_via"]
            # 抓回来的页面可能带更准的元数据
            for k in ("doi", "journal", "date"):
                if r.get(k) and not out.get(k):
                    out[k] = r[k]
            return out
        # 失败原因如实记录，供 UI 展示「为什么没正文」
        why = r.get("oa_fallback_error") or r.get("reason") or "未取到正文"
        out.setdefault("fetch_notes", []).append(f"{url[:48]}：{str(why)[:70]}")

    # 3) 无 DOI 可降级时明确说明（不是静默失败）
    if not out.get("doi"):
        out["fetch_notes"] = (out.get("fetch_notes") or []) + [
            "无 DOI 且无可用 OA 链接，无法自动获取正文；请手动下载 PDF 上传"]
    return out


def enrich_refs(refs: Any, max_refs: int = 6,
                timeout: float = 25.0, workers: int = FETCH_WORKERS) -> Dict[str, Any]:
    """给检索结果批量补正文。

    只处理前 ``max_refs`` 条 —— 写作时引用集中在那几篇，全抓既慢又没必要。

    ``refs`` 接受两种形态：``search_web()`` 返回的 ``{items: [...]}`` 包装，
    或 ``run_dual_search()`` 的 ``refs`` 列表 —— 两个来源都能直接传进来。

    返回 ``{refs, with_text, without_text, elapsed_s, notes}``。
    """
    # 兼容 search_web() 的 {"items": [...]} 包装
    if isinstance(refs, dict):
        refs = refs.get("items") or refs.get("refs") or []
    refs = list(refs or [])
    t0 = time.time()
    target = refs[:max_refs]

    if not target:
        return {"refs": refs, "with_text": 0, "without_text": 0,
                "elapsed_s": 0.0, "notes": ["没有可补正文的检索结果"]}

    enriched: List[Dict[str, Any]] = []
    try:
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=max(1, workers)) as ex:
            futs = {ex.submit(fetch_fulltext, r, timeout): i for i, r in enumerate(target)}
            result_map = {}
            for fut in concurrent.futures.as_completed(futs):
                i = futs[fut]
                try:
                    result_map[i] = fut.result()
                except Exception as e:  # noqa: BLE001
                    bad = dict(target[i])
                    bad["text"] = ""
                    bad.setdefault("fetch_notes", []).append(f"抓取异常：{type(e).__name__}")
                    result_map[i] = bad
            for i in range(len(target)):
                enriched.append(result_map.get(i, dict(target[i])))
    except Exception:
        enriched = [dict(r) for r in target]

    # 未在前 max_refs 内的原样保留
    merged = enriched + [dict(r) for r in refs[max_refs:]]
    # ⚠️ 必须**重排** index，不能用 setdefault：调用方传入的 refs 可能已带
    # index（例如从 search_web 复用同一批对象），setdefault 会保留旧值导致
    # 编号重复 —— 而 [n] 是引用白名单的锚点，重复会让引用指向错的文献。
    for i, r in enumerate(merged, 1):
        r["index"] = i

    with_text = sum(1 for r in enriched if (r.get("text") or "").strip())
    return {
        "refs": merged,
        "with_text": with_text,
        "without_text": len(enriched) - with_text,
        "elapsed_s": round(time.time() - t0, 1),
        "notes": [
            f"已为 {with_text}/{len(enriched)} 篇获取正文；"
            "写作时只能引用有正文的条目，其余仅可作背景提及。",
            "无正文的原因通常是：出版商付费墙 / 无合法开放版本 / 页面为 JS 动态渲染。",
        ],
    }


def render_fulltext_notes(refs: List[Dict[str, Any]], limit: int = 4,
                          chars_each: int = 2200) -> str:
    """把有正文的条目渲染成 prompt 可用的「原文摘录」块。

    ⚠️ 只放**有正文**的条目。没有正文却把题录塞进 prompt，
    会诱导 LLM 编造原文内容 —— 那是最危险的引用污染。
    """
    picked = [r for r in (refs or []) if (r.get("text") or "").strip()][:limit]
    if not picked:
        return ""
    lines = ["## 可引用的原文摘录（仅以下条目抓到了正文）", ""]
    for r in picked:
        lines.append(f"### [{r.get('index', '?')}] {r.get('title', '')}")
        meta = []
        if r.get("journal"):
            meta.append(str(r["journal"]))
        if r.get("year"):
            meta.append(str(r["year"]))
        if r.get("doi"):
            meta.append("DOI:" + str(r["doi"]))
        if meta:
            lines.append("　" + " · ".join(meta))
        body = str(r["text"])[:chars_each].strip()
        if len(str(r["text"])) > chars_each:
            body += " …（已截断）"
        lines += ["", body, ""]
    lines.append("> 以上为抓取到的原文片段。引用时请以上述原文为依据，"
                 "不要引入片段之外的结论。")
    return "\n".join(lines)