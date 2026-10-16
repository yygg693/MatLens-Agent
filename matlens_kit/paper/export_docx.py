# -*- coding: utf-8 -*-
"""论文工坊 · Word（docx）学术排版导出器。

唯一正文来源是 ``write`` 阶段 content（经 :mod:`md_model.parse_paper` 解析为
标题 / 摘要 / 关键词 / 正文块），参考文献来自 ``search`` 阶段 refs（经
:mod:`refs.ref_lines` 按 cite_style 排版）。本模块只负责把这些结构化数据渲染成
一篇排版规范的学术论文 docx。

排版要点（严格按学术规范）：
- A4 页面，上下页边距 2.5cm、左右 2.8cm；
- Normal：西文 Times New Roman、东亚宋体、正文小四 12pt；
- 论文标题居中加粗约 17pt；Abstract / Keywords 独立排版；
- 各级标题用 Word 内置 Heading 1/2/3，黑色、西文 Times New Roman、中文黑体；
- 正文 1.5 倍行距、两端对齐、首行缩进 2 字符（firstLineChars=200）；
- 行内 token：普通 / 加粗 / 斜体 / Code(Consolas) / 下标 / 上标；
- 列表 List Bullet / List Number；表格 Table Grid 带边框；代码块 Consolas 10pt；
- 参考文献五号 10.5pt、悬挂缩进。

python-docx 未安装时 :func:`export_docx` 返回 ``None``。
"""
from __future__ import annotations

import io
from typing import Any, Dict, List, Optional

from matlens_kit.paper.md_model import (
    BCode,
    BHeading,
    BList,
    BListItem,
    BParagraph,
    BTable,
    IBold,
    ICode,
    IItalic,
    ISub,
    ISup,
    IText,
    parse_paper,
    tokenize_inline,
)
from matlens_kit.paper.refs import ref_lines
import glob as _glob
import os as _os

# ---------------------------------------------------------------------------
# 字体 / 字号常量
# ---------------------------------------------------------------------------
_WESTERN = "Times New Roman"
_CODE_FONT = "Consolas"
_EA_SONG = "宋体"      # 正文 / 摘要 / 表格 / 参考文献
_EA_HEI = "黑体"       # 标题
_BODY_SIZE = 12.0      # 小四
_TITLE_SIZE = 17.0     # 论文标题
_ABS_SIZE = 11.0       # 摘要
_HEADING_SIZES = {1: 14.0, 2: 13.0, 3: 12.0}   # Heading 1/2/3
_TABLE_SIZE = 10.5     # 五号
_CODE_SIZE = 10.0
_REF_SIZE = 10.5       # 五号


# ---------------------------------------------------------------------------
# run 级字体工具
# ---------------------------------------------------------------------------
def _set_run_font(run, *, size: float, bold: bool = False, italic: bool = False,
                  sub: bool = False, sup: bool = False,
                  western: str = _WESTERN, eastasia: str = _EA_SONG) -> None:
    """给一个 run 设置西文 / 东亚字体、字号、加粗 / 斜体 / 上下标。"""
    run.font.name = western
    run.font.size = _Pt(size)
    run.font.bold = bold or None
    run.font.italic = italic or None
    if sub:
        run.font.subscript = True
    if sup:
        run.font.superscript = True
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    rfonts.set(_qname("w:eastAsia"), eastasia)
    # 西文字体双保险（ascii + hAnsi）
    rfonts.set(_qname("w:ascii"), western)
    rfonts.set(_qname("w:hAnsi"), western)


def _add_inline_runs(paragraph, tokens, *, size: float,
                     bold: bool = False, italic: bool = False,
                     eastasia: str = _EA_SONG) -> None:
    """递归把行内 token 渲染成 paragraph 的 run 序列。"""
    for tok in tokens:
        if isinstance(tok, IText):
            if not tok.value:
                continue
            run = paragraph.add_run(tok.value)
            _set_run_font(run, size=size, bold=bold, italic=italic, eastasia=eastasia)
        elif isinstance(tok, IBold):
            _add_inline_runs(paragraph, tok.children, size=size,
                             bold=True, italic=italic, eastasia=eastasia)
        elif isinstance(tok, IItalic):
            _add_inline_runs(paragraph, tok.children, size=size,
                             bold=bold, italic=True, eastasia=eastasia)
        elif isinstance(tok, ICode):
            run = paragraph.add_run(tok.value)
            _set_run_font(run, size=size, western=_CODE_FONT, eastasia=_EA_SONG)
        elif isinstance(tok, ISub):
            run = paragraph.add_run(tok.value)
            _set_run_font(run, size=size, sub=True, eastasia=eastasia)
        elif isinstance(tok, ISup):
            run = paragraph.add_run(tok.value)
            _set_run_font(run, size=size, sup=True, eastasia=eastasia)


# ---------------------------------------------------------------------------
# 段落级排版工具
# ---------------------------------------------------------------------------
def _set_first_line_indent_chars(paragraph, chars: int = 200) -> None:
    """中文首行缩进 N 字符（firstLineChars），并给 twips 兜底。"""
    pPr = paragraph._p.get_or_add_pPr()
    ind = pPr.get_or_add_ind()
    ind.set(_qname("w:firstLineChars"), str(chars))
    # 兜底：12pt 两字符 ≈ 24pt = 480 twips
    ind.set(_qname("w:firstLine"), "480")


def _clear_indent(paragraph) -> None:
    """清除首行 / 左右缩进（用于摘要、代码块、参考文献悬挂）。"""
    pPr = paragraph._p.get_or_add_pPr()
    ind = pPr.find(_qname("w:ind"))
    if ind is not None:
        pPr.remove(ind)


def _set_hanging(paragraph, left_twips: int = 360, hang_twips: int = 360) -> None:
    """悬挂缩进：左缩进 left_twips，首行回退 hang_twips（无首行缩进）。"""
    pPr = paragraph._p.get_or_add_pPr()
    ind = pPr.get_or_add_ind()
    ind.set(_qname("w:left"), str(left_twips))
    ind.set(_qname("w:hanging"), str(hang_twips))
    # 明确去掉首行缩进
    for attr in ("w:firstLine", "w:firstLineChars"):
        if ind.get(_qname(attr)) is not None:
            del ind.attrib[_qname(attr)]


# ---------------------------------------------------------------------------
# 惰性导入（python-docx 缺失时 export_docx 返回 None）
# ---------------------------------------------------------------------------
def _Pt(v):
    from docx.shared import Pt
    return Pt(v)


def _Cm(v):
    from docx.shared import Cm
    return Cm(v)


def _RGB(r, g, b):
    from docx.shared import RGBColor
    return RGBColor(r, g, b)


def _qname(tag):
    from docx.oxml.ns import qn
    return qn(tag)


def _OxmlElement(tag):
    from docx.oxml import OxmlElement
    return OxmlElement(tag)


# ---------------------------------------------------------------------------
# 文档初始化与样式定制
# ---------------------------------------------------------------------------
def _setup_document():
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()

    # 页面：A4，页边距上下 2.5cm、左右 2.8cm
    sec = doc.sections[0]
    sec.page_height = _Cm(29.7)
    sec.page_width = _Cm(21.0)
    sec.top_margin = _Cm(2.5)
    sec.bottom_margin = _Cm(2.5)
    sec.left_margin = _Cm(2.8)
    sec.right_margin = _Cm(2.8)

    # Normal 样式：西文 Times New Roman、东亚宋体、小四 12pt
    normal = doc.styles["Normal"]
    normal.font.name = _WESTERN
    normal.font.size = _Pt(_BODY_SIZE)
    normal.font.bold = False
    normal.font.italic = False
    normal.font.color.rgb = _RGB(0, 0, 0)
    nrpr = normal.element.get_or_add_rPr()
    nrfonts = nrpr.get_or_add_rFonts()
    nrfonts.set(_qname("w:eastAsia"), _EA_SONG)
    nrfonts.set(_qname("w:ascii"), _WESTERN)
    nrfonts.set(_qname("w:hAnsi"), _WESTERN)

    # Heading 1/2/3：黑色、西文 Times New Roman、中文黑体、加粗、固定字号
    for level, size in _HEADING_SIZES.items():
        h = doc.styles[f"Heading {level}"]
        h.font.name = _WESTERN
        h.font.size = _Pt(size)
        h.font.bold = True
        h.font.italic = False
        h.font.color.rgb = _RGB(0, 0, 0)
        hrpr = h.element.get_or_add_rPr()
        hrfonts = hrpr.get_or_add_rFonts()
        hrfonts.set(_qname("w:eastAsia"), _EA_HEI)
        hrfonts.set(_qname("w:ascii"), _WESTERN)
        hrfonts.set(_qname("w:hAnsi"), _WESTERN)

    # List Bullet / List Number 字体也统一为正文样式
    for sname in ("List Bullet", "List Number"):
        try:
            ls = doc.styles[sname]
            ls.font.name = _WESTERN
            ls.font.size = _Pt(_BODY_SIZE)
            lrpr = ls.element.get_or_add_rPr()
            lrfonts = lrpr.get_or_add_rFonts()
            lrfonts.set(_qname("w:eastAsia"), _EA_SONG)
        except KeyError:
            pass

    return doc, WD_ALIGN_PARAGRAPH


# ---------------------------------------------------------------------------
# 各类块的渲染
# ---------------------------------------------------------------------------
def _render_title(doc, parsed, WD_ALIGN_PARAGRAPH):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pf = p.paragraph_format
    pf.space_before = _Pt(6)
    pf.space_after = _Pt(12)
    pf.line_spacing = 1.5
    if parsed.title_tokens:
        _add_inline_runs(p, parsed.title_tokens, size=_TITLE_SIZE, bold=True,
                         eastasia=_EA_HEI)
    else:
        run = p.add_run(parsed.title)
        _set_run_font(run, size=_TITLE_SIZE, bold=True, eastasia=_EA_HEI)


def _render_abstract(doc, parsed, WD_ALIGN_PARAGRAPH):
    if not parsed.abstract_paragraphs:
        return
    label = parsed.abstract_label.strip() or ("摘要" if parsed.lang == "zh" else "Abstract")
    for idx, para in enumerate(parsed.abstract_paragraphs):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        pf = p.paragraph_format
        pf.left_indent = _Cm(0.8)
        pf.right_indent = _Cm(0.8)
        pf.line_spacing = 1.5
        pf.space_after = _Pt(4)
        if idx == 0:
            run = p.add_run(f"{label}. ")
            _set_run_font(run, size=_ABS_SIZE, bold=True, eastasia=_EA_HEI)
        _add_inline_runs(p, para.tokens, size=_ABS_SIZE)


def _render_keywords(doc, parsed, WD_ALIGN_PARAGRAPH):
    if not parsed.keywords:
        return
    label = parsed.keywords_label.strip() or ("关键词" if parsed.lang == "zh" else "Keywords")
    # 统一成 "Keywords:" / "关键词：" 的引导形式
    if label.lower().startswith("key"):
        lead = "Keywords: "
    else:
        lead = "关键词："
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    pf = p.paragraph_format
    pf.left_indent = _Cm(0.8)
    pf.right_indent = _Cm(0.8)
    pf.line_spacing = 1.5
    pf.space_before = _Pt(4)
    pf.space_after = _Pt(10)
    run = p.add_run(lead)
    _set_run_font(run, size=_ABS_SIZE, bold=True, eastasia=_EA_HEI)
    body = "; ".join(k.strip() for k in parsed.keywords if k.strip())
    run2 = p.add_run(body)
    _set_run_font(run2, size=_ABS_SIZE)


def _render_heading(doc, block: BHeading, WD_ALIGN_PARAGRAPH):
    level = min(max(block.level, 1), 3)
    p = doc.add_paragraph(style=f"Heading {level}")
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    pf = p.paragraph_format
    pf.space_before = _Pt(10 if level == 1 else 6)
    pf.space_after = _Pt(6)
    pf.line_spacing = 1.5
    size = _HEADING_SIZES[level]
    if block.tokens:
        _add_inline_runs(p, block.tokens, size=size, bold=True, eastasia=_EA_HEI)
    else:
        run = p.add_run(block.text)
        _set_run_font(run, size=size, bold=True, eastasia=_EA_HEI)


def _render_paragraph(doc, block: BParagraph, WD_ALIGN_PARAGRAPH):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    pf = p.paragraph_format
    pf.line_spacing = 1.5
    pf.space_after = _Pt(4)
    _set_first_line_indent_chars(p, 200)
    _add_inline_runs(p, block.tokens, size=_BODY_SIZE)


def _render_list(doc, block: BList):
    style_name = "List Number" if block.ordered else "List Bullet"
    for item in block.items:
        p = doc.add_paragraph(style=style_name)
        pf = p.paragraph_format
        pf.line_spacing = 1.5
        pf.space_after = _Pt(2)
        _add_inline_runs(p, item.tokens, size=_BODY_SIZE)


def _render_table(doc, block: BTable, WD_ALIGN_PARAGRAPH):
    from docx.enum.table import WD_TABLE_ALIGNMENT

    ncols = max(len(block.header), max((len(r) for r in block.rows), default=0))
    if ncols == 0:
        return
    table = doc.add_table(rows=1, cols=ncols)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True

    align_map = {
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
    }

    def _fill_cell(cell, text: str, *, bold: bool, align):
        cell.text = ""
        para = cell.paragraphs[0]
        para.alignment = align
        pf = para.paragraph_format
        pf.line_spacing = 1.15
        pf.space_after = _Pt(0)
        pf.space_before = _Pt(0)
        tokens = tokenize_inline(text)
        _add_inline_runs(para, tokens, size=_TABLE_SIZE, bold=bold)

    # 表头
    hdr_cells = table.rows[0].cells
    for c in range(ncols):
        txt = block.header[c] if c < len(block.header) else ""
        align = align_map.get(block.aligns[c] if c < len(block.aligns) else "",
                              WD_ALIGN_PARAGRAPH.CENTER)
        _fill_cell(hdr_cells[c], txt, bold=True, align=align)

    # 数据行
    for row in block.rows:
        cells = table.add_row().cells
        for c in range(ncols):
            txt = row[c] if c < len(row) else ""
            align = align_map.get(block.aligns[c] if c < len(block.aligns) else "",
                                  WD_ALIGN_PARAGRAPH.LEFT)
            _fill_cell(cells[c], txt, bold=False, align=align)

    # 表后空一行
    sp = doc.add_paragraph()
    sp.paragraph_format.space_after = _Pt(4)


def _render_code(doc, block: BCode):
    lines = block.text.split("\n")
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.line_spacing = 1.15
    pf.space_after = _Pt(4)
    pf.left_indent = _Cm(0.5)
    for i, ln in enumerate(lines):
        if i > 0:
            run = p.add_run()
            run.add_break()
        run = p.add_run(ln if ln else "")
        _set_run_font(run, size=_CODE_SIZE, western=_CODE_FONT, eastasia=_EA_SONG)


def _render_references(doc, parsed, refs, cite_style, WD_ALIGN_PARAGRAPH):
    lines = ref_lines(refs, cite_style)
    if not lines:
        return
    h = doc.add_paragraph(style="Heading 1")
    h.paragraph_format.space_before = _Pt(12)
    h.paragraph_format.space_after = _Pt(6)
    run = h.add_run(parsed.references_label())
    _set_run_font(run, size=_HEADING_SIZES[1], bold=True, eastasia=_EA_HEI)

    for line in lines:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        pf = p.paragraph_format
        pf.line_spacing = 1.25
        pf.space_after = _Pt(2)
        _set_hanging(p, left_twips=360, hang_twips=360)
        run = p.add_run(line)
        _set_run_font(run, size=_REF_SIZE)


# ---------------------------------------------------------------------------
# 插图嵌入
# ---------------------------------------------------------------------------
import re as _re

# 匹配 BParagraph.raw 是否为 Figure 图注行（"Figure 1. ..." / "Fig. 1 ..." / "图 1 ..."）
_FIG_CAPTION_RE = _re.compile(
    r"^\s*(?:\*\*)?\s*(?:Figure|Fig\.?|图)\s*(\d+)\s*[.:：、\-]?\s*",
    _re.IGNORECASE,
)


def _find_figure_png(fig_num: int, figures_dir: str) -> Optional[str]:
    """在 figures_dir 下找 fig_{num}_*.png。"""
    if not figures_dir or not _os.path.isdir(figures_dir):
        return None
    pattern = _os.path.join(figures_dir, f"fig_{fig_num}_*.png")
    matches = sorted(_glob.glob(pattern))
    return matches[0] if matches else None


def _render_figure_image(doc, png_path: str, WD_ALIGN_PARAGRAPH) -> None:
    """插入居中图片段落，宽 ≤15cm，上下留白。"""
    if not png_path or not _os.path.isfile(png_path):
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pf = p.paragraph_format
    pf.space_before = _Pt(8)
    pf.space_after = _Pt(2)
    pf.line_spacing = 1.0
    run = p.add_run()
    run.add_picture(png_path, width=_Cm(15.0))


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def export_docx(p: Dict[str, Any], cite_style: str = "gb7714",
                figures_dir: Optional[str] = None) -> Optional[bytes]:
    """把一篇论文的 write 正文 + search refs 渲染为 docx 字节。

    Args:
        p: 论文 dict，含 ``title`` 与 ``stages.write.content`` / ``stages.search.refs``。
        cite_style: 参考文献风格（gb7714 / ieee / apa / acs）。
        figures_dir: 可选，示意图 PNG 目录；存在时在 Figure 图注段前插入对应图片。

    Returns:
        docx bytes；python-docx 未安装或 write 为空时返回 ``None``。
    """
    try:
        from docx import Document  # noqa: F401
    except ImportError:
        return None

    stages = p.get("stages", {}) or {}
    write_content = ((stages.get("write") or {}).get("content") or "").strip()
    if not write_content:
        return None
    refs = (stages.get("search") or {}).get("refs") or []

    fallback_title = (p.get("title") or "").strip() or "未命名论文"
    parsed = parse_paper(write_content, fallback_title)

    doc, WD_ALIGN_PARAGRAPH = _setup_document()

    _render_title(doc, parsed, WD_ALIGN_PARAGRAPH)
    _render_abstract(doc, parsed, WD_ALIGN_PARAGRAPH)
    _render_keywords(doc, parsed, WD_ALIGN_PARAGRAPH)

    for block in parsed.blocks:
        if isinstance(block, BHeading):
            _render_heading(doc, block, WD_ALIGN_PARAGRAPH)
        elif isinstance(block, BParagraph):
            # 若该段是 Figure 图注且 figures_dir 有对应 PNG，先插图
            if figures_dir:
                cm = _FIG_CAPTION_RE.match(block.raw or "")
                if cm:
                    fnum = int(cm.group(1))
                    png = _find_figure_png(fnum, figures_dir)
                    if png:
                        _render_figure_image(doc, png, WD_ALIGN_PARAGRAPH)
            _render_paragraph(doc, block, WD_ALIGN_PARAGRAPH)
        elif isinstance(block, BList):
            _render_list(doc, block)
        elif isinstance(block, BTable):
            _render_table(doc, block, WD_ALIGN_PARAGRAPH)
        elif isinstance(block, BCode):
            _render_code(doc, block)

    _render_references(doc, parsed, refs, cite_style, WD_ALIGN_PARAGRAPH)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
