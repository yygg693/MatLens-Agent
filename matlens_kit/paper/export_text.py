# -*- coding: utf-8 -*-
"""论文工坊 · Markdown / LaTeX 论文导出渲染器。

只产出一篇干净的学术成稿：
- 唯一正文来源是 ``write``（逐章写作）阶段 content，经 :func:`md_model.parse_paper`
  解析为 标题 / 摘要 / 关键词 / 正文块序列；
- 参考文献来自 ``search`` 阶段 refs，按 cite_style 排版；
- ``topic / search / outline / quality / review`` 的过程文字一律不进入成稿。

门面 :mod:`export` 负责 ``write`` 为空时的报错（:data:`EMPTY_WRITE_MESSAGE`）；
本模块在 ``write`` 为空时仅返回空串。

两个对外函数（签名固定，门面 import）：
- :func:`export_markdown`
- :func:`export_latex`
"""
from __future__ import annotations

from typing import Any, Dict, List

from matlens_kit.paper.md_model import (
    BCode,
    BHeading,
    BList,
    BParagraph,
    BTable,
    ICode,
    IBold,
    IItalic,
    ISub,
    ISup,
    IText,
    parse_paper,
    tokenize_inline,
)
from matlens_kit.paper.refs import fmt_refs, ref_lines


# ---------------------------------------------------------------------------
# p dict 取值
# ---------------------------------------------------------------------------
def _write_content(p: Dict[str, Any]) -> str:
    st = (p.get("stages", {}) or {}).get("write", {}) or {}
    return (st.get("content") or "").strip()


def _search_refs(p: Dict[str, Any]) -> List[Dict[str, Any]]:
    st = (p.get("stages", {}) or {}).get("search", {}) or {}
    return st.get("refs") or []


# ===========================================================================
# Markdown
# ===========================================================================
def _render_block_md(b: Any) -> str:
    if isinstance(b, BHeading):
        hashes = {1: "##", 2: "###", 3: "####"}.get(b.level, "#####")
        return f"{hashes} {b.text}"
    if isinstance(b, BParagraph):
        return b.raw
    if isinstance(b, BList):
        mark = "1. " if b.ordered else "- "
        return "\n".join(mark + it.raw for it in b.items)
    if isinstance(b, BTable):
        return b.raw  # 已是合法 markdown 表格
    if isinstance(b, BCode):
        return f"```{b.lang or ''}\n{b.text}\n```"
    return ""


def export_markdown(p: Dict[str, Any], cite_style: str = "gb7714") -> str:
    """导出干净的 Markdown 论文；write 为空返回 ""。"""
    write = _write_content(p)
    if not write:
        return ""

    paper = parse_paper(write, fallback_title=(p.get("title") or "未命名论文"))
    joined = "；" if paper.lang == "zh" else "; "

    out: List[str] = [f"# {paper.title}"]

    if paper.abstract_label:
        out.append(f"## {paper.abstract_label}")
        for para in paper.abstract_paragraphs:
            out.append(para.raw)

    if paper.keywords:
        out.append(f"**{paper.keywords_label}:** {joined.join(paper.keywords)}")

    for b in paper.blocks:
        rendered = _render_block_md(b)
        if rendered:
            out.append(rendered)

    refs = _search_refs(p)
    if refs:
        out.append(f"## {paper.references_label()}")
        out.append(fmt_refs(refs, cite_style))

    return "\n\n".join(out)


# ===========================================================================
# LaTeX
# ===========================================================================
#: 需转义的 LaTeX 特殊字符（Unicode 上下标/℃/Ω/≥/δ 等原样保留）
_LATEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def _esc_tex(s: str) -> str:
    """转义一段纯文本里的 LaTeX 特殊字符（不动我们自己生成的命令）。"""
    return "".join(_LATEX_ESCAPES.get(ch, ch) for ch in s)


def _render_inline_tex(tokens: List[Any]) -> str:
    """按行内 token 序列化为 LaTeX。"""
    parts: List[str] = []
    for t in tokens:
        if isinstance(t, IText):
            parts.append(_esc_tex(t.value))
        elif isinstance(t, IBold):
            parts.append(r"\textbf{" + _render_inline_tex(t.children) + "}")
        elif isinstance(t, IItalic):
            parts.append(r"\textit{" + _render_inline_tex(t.children) + "}")
        elif isinstance(t, ICode):
            parts.append(r"\texttt{" + _esc_tex(t.value) + "}")
        elif isinstance(t, ISub):
            parts.append(r"\textsubscript{" + _esc_tex(t.value) + "}")
        elif isinstance(t, ISup):
            parts.append(r"\textsuperscript{" + _esc_tex(t.value) + "}")
    return "".join(parts)


def _colspec(aligns: List[str], n: int) -> str:
    cols = []
    for i in range(n):
        a = aligns[i] if i < len(aligns) else ""
        cols.append({"center": "c", "right": "r"}.get(a, "l"))
    return "|" + "|".join(cols) + "|"


def _render_table_tex(tbl: BTable) -> str:
    n = len(tbl.header)
    lines: List[str] = [
        r"\begin{tabular}{" + _colspec(tbl.aligns, n) + "}",
        r"\hline",
    ]
    hdr = [r"\textbf{" + _render_inline_tex(tokenize_inline(h)) + "}" for h in tbl.header]
    lines.append(" & ".join(hdr) + r" \\")
    lines.append(r"\hline")
    for row in tbl.rows:
        cells = [_render_inline_tex(tokenize_inline(c)) for c in row]
        lines.append(" & ".join(cells) + r" \\")
    lines.append(r"\hline")
    lines.append(r"\end{tabular}")
    return "\n".join(lines)


def _render_block_tex(b: Any) -> str:
    if isinstance(b, BHeading):
        cmd = {1: r"\section", 2: r"\subsection", 3: r"\subsubsection"}.get(
            b.level, r"\subsubsection"
        )
        return cmd + "{" + _render_inline_tex(b.tokens) + "}"
    if isinstance(b, BParagraph):
        return _render_inline_tex(b.tokens)
    if isinstance(b, BList):
        env = "enumerate" if b.ordered else "itemize"
        parts = [r"\begin{" + env + "}"]
        for it in b.items:
            parts.append(r"\item " + _render_inline_tex(it.tokens))
        parts.append(r"\end{" + env + "}")
        return "\n".join(parts)
    if isinstance(b, BTable):
        return _render_table_tex(b)
    if isinstance(b, BCode):
        return r"\begin{verbatim}" + "\n" + b.text + "\n" + r"\end{verbatim}"
    return ""


def export_latex(p: Dict[str, Any], cite_style: str = "gb7714") -> str:
    """导出 ctexart 结构、可编译的 LaTeX 论文；write 为空返回 ""。"""
    write = _write_content(p)
    if not write:
        return ""

    paper = parse_paper(write, fallback_title=(p.get("title") or "未命名论文"))
    zh = paper.lang == "zh"
    joined = "；" if zh else "; "
    kw_label = "关键词：" if zh else "Keywords: "

    L: List[str] = [
        r"\documentclass[12pt]{ctexart}",
        r"\usepackage[margin=2.5cm]{geometry}",
        r"\usepackage{amsmath,amssymb}",
        r"\setlength{\parindent}{2em}",
        r"\title{" + _render_inline_tex(paper.title_tokens) + r"}",
        r"\author{}",
        r"\date{\today}",
        r"\begin{document}",
        r"\maketitle",
    ]

    if paper.abstract_label:
        L.append(r"\begin{abstract}")
        for para in paper.abstract_paragraphs:
            L.append(_render_inline_tex(para.tokens))
        L.append(r"\end{abstract}")

    if paper.keywords:
        kw = joined.join(_esc_tex(k) for k in paper.keywords)
        L.append(r"\noindent\textbf{" + kw_label + "}" + kw)

    for b in paper.blocks:
        rendered = _render_block_tex(b)
        if rendered:
            L.append(rendered)

    refs = _search_refs(p)
    if refs:
        L.append(r"\section*{" + _esc_tex(paper.references_label()) + "}")
        L.append(r"\small")
        for line in ref_lines(refs, cite_style):
            L.append(_esc_tex(line))
        L.append(r"\normalsize")

    L.append(r"\end{document}")
    return "\n\n".join(L)
