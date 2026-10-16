# -*- coding: utf-8 -*-
"""论文工坊 · 参考文献排版与设置读取（导出渲染器共享的窄腰）。

可用 ref 字段：title / authors(字符串) / year / source("OpenAlex·刊名") / doi。
四种真实可辨的排版风格：gb7714 / ieee / apa / acs。
"""
from __future__ import annotations

from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def venue(r: Dict[str, Any]) -> str:
    """从 "OpenAlex·Journal Name" / "本地知识库·lib" 取真正的刊名/来源。"""
    src = (r.get("source") or "").strip()
    return src.split("·", 1)[1].strip() if "·" in src else src


def _doi_suffix(doi: str, scheme: str = "DOI: ") -> str:
    return f" {scheme}{doi}" if doi else ""


# ---------------------------------------------------------------------------
# 四种风格
# ---------------------------------------------------------------------------
def fmt_refs_gb7714(refs: List[Dict[str, Any]]) -> str:
    """GB/T 7714-2014 编号制：[n] 作者. 题名[J]. 刊名, 年. DOI: xxx"""
    lines = []
    for i, r in enumerate(refs, 1):
        title = (r.get("title") or "").strip()
        authors = (r.get("authors") or "").strip() or "佚名"
        year = r.get("year")
        v = venue(r)
        doi = (r.get("doi") or "").strip()
        doctype = "[J]" if v else "[EB/OL]"
        head = f"[{i}] {authors}. {title}{doctype}"
        tail = ", ".join([x for x in [v, (str(year) if year else "")] if x])
        line = f"{head}. {tail}." if tail else f"{head}."
        line += _doi_suffix(doi)
        lines.append(line)
    return "\n".join(lines)


def fmt_refs_ieee(refs: List[Dict[str, Any]]) -> str:
    """IEEE 编号制：[n] A. Author, "Title," Journal, Year.（标题加双引号）"""
    lines = []
    for i, r in enumerate(refs, 1):
        title = (r.get("title") or "").strip()
        authors = (r.get("authors") or "").strip() or "佚名"
        year = r.get("year")
        v = venue(r)
        doi = (r.get("doi") or "").strip()
        segs = [f'[{i}] {authors}, "{title},"']
        if v:
            segs.append(v)
        if year:
            segs.append(str(year))
        line = ", ".join(segs) + "."
        line += _doi_suffix(doi)
        lines.append(line)
    return "\n".join(lines)


def fmt_refs_apa(refs: List[Dict[str, Any]]) -> str:
    """APA 作者-年制：作者 (年). 题名. 刊名. https://doi.org/xxx（无编号）。"""
    lines = []
    for r in refs:
        title = (r.get("title") or "").strip()
        authors = (r.get("authors") or "").strip() or "佚名"
        year = r.get("year")
        v = venue(r).rstrip(".")
        doi = (r.get("doi") or "").strip()
        head = f"{authors} ({year})" if year else f"{authors}"
        segs = [head, title]
        if v:
            segs.append(v)
        line = ". ".join(segs) + "."
        line += _doi_suffix(doi, "https://doi.org/")
        lines.append(line)
    return "\n".join(lines)


def fmt_refs_acs(refs: List[Dict[str, Any]]) -> str:
    """ACS 编号制：[n] 作者. 题名. 期刊. 年.（句点分段）。"""
    lines = []
    for i, r in enumerate(refs, 1):
        title = (r.get("title") or "").strip()
        authors = (r.get("authors") or "").strip() or "佚名"
        year = r.get("year")
        v = venue(r).rstrip(".")
        doi = (r.get("doi") or "").strip()
        segs = [f"[{i}] {authors}.", title]
        if v:
            segs.append(v + ".")
        if year:
            segs.append(str(year) + ".")
        line = " ".join(segs)
        line += _doi_suffix(doi)
        lines.append(line)
    return "\n".join(lines)


_REF_FORMATTERS: Dict[str, Any] = {
    "gb7714": fmt_refs_gb7714,
    "ieee": fmt_refs_ieee,
    "apa": fmt_refs_apa,
    "acs": fmt_refs_acs,
}


def fmt_refs(refs: List[Dict[str, Any]], cite_style: str = "gb7714") -> str:
    """按 cite_style 渲染参考文献（空则返回空串）。未知风格回退 gb7714。"""
    if not refs:
        return ""
    style = (cite_style or "gb7714").strip().lower()
    return _REF_FORMATTERS.get(style, fmt_refs_gb7714)(refs)


def ref_lines(refs: List[Dict[str, Any]], cite_style: str = "gb7714") -> List[str]:
    """同 fmt_refs 但返回行列表（docx 逐条排版用）。"""
    text = fmt_refs(refs, cite_style)
    return text.split("\n") if text else []


# ---------------------------------------------------------------------------
# settings 实时读取（动作发生时刻读，不缓存）
# ---------------------------------------------------------------------------
def papers_settings() -> Dict[str, Any]:
    """实时读 settings papers 段（读 config.yaml，不缓存）。失败回退空 dict。"""
    try:
        from matlens_kit import settings_store

        return settings_store.get_section("papers")
    except Exception:
        return {}


def resolve_cite_style(explicit: str | None = None) -> str:
    """显式 cite_style 优先；否则实时读 settings papers.cite_style（默认 gb7714）。"""
    if explicit:
        return explicit.strip().lower()
    return (papers_settings().get("cite_style") or "gb7714").strip().lower()


def default_export_format() -> str:
    """实时读 settings papers.export_format（docx/tex/md，默认 docx）。"""
    return (papers_settings().get("export_format") or "docx").strip().lower()
