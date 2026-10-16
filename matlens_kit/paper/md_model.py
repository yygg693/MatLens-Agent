# -*- coding: utf-8 -*-
"""论文工坊 · write 正文 Markdown 解析模型（导出渲染器共享）。

输入：write 阶段 content（唯一合法正文来源）。
输出：:class:`ParsedPaper` —— 标题 / 摘要 / 关键词 / 正文块序列。

设计：
- 块级（block）：标题、段落、列表、表格、代码块；
- 行内（inline）：文本、加粗、斜体、代码、下标、上标（化学式 E_a、cm^-1 等）；
- 清洗：引用占位 {A-1}→[1]、剔除「引用说明」过程块与水平分隔线、
  去除「（占位）/（待填…）」等过程性括注。

正文里已经大量使用 Unicode 上下标（TiO₂、cm⁻¹），它们作为普通文本即可；
本模块额外识别 ASCII 的 ``_x`` / ``^x``（多见于表格单元）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, List, Optional, Union

#: write 为空时的统一提示（导出入口与 API 共用）
EMPTY_WRITE_MESSAGE = "论文正文尚未生成，请先完成「逐章写作」步骤后再导出。"


# ===========================================================================
# 行内 token
# ===========================================================================
@dataclass
class IText:
    value: str


@dataclass
class IBold:
    children: List["InlineToken"]


@dataclass
class IItalic:
    children: List["InlineToken"]


@dataclass
class ICode:
    value: str


@dataclass
class ISub:
    value: str


@dataclass
class ISup:
    value: str


InlineToken = Union[IText, IBold, IItalic, ICode, ISub, ISup]


# 顶层结构：代码 / 加粗 / 星号斜体 / 下划线斜体（成对、两侧非字母数字）
_INLINE_RE = re.compile(
    r"(?P<code>`[^`\n]+?`)"
    r"|(?P<bold>\*\*[^*]+?\*\*)"
    r"|(?P<ital>\*(?!\*)[^*\n]+?(?<!\*)\*)"
    r"|(?P<uital>(?<![A-Za-z0-9])_[^_\n]+?_(?![A-Za-z0-9]))"
)

# 纯文本段内的化学式上下标：非空白字符后的 _x（下标）、^x（上标）。
# 用纯 lookbehind 保证相邻「下标+上标」（σ_gb^sp）两次匹配不重叠。
_CHEM_RE = re.compile(
    r"(?<=\S)_(?P<sub>[0-9A-Za-z]+)"
    r"|(?<=\S)\^(?P<sup>[0-9A-Za-z+\-]+)"
)


def _chem_tokens(text: str) -> List[InlineToken]:
    """把一段无结构标记的文本按 ASCII 上下标切开（其余为 IText）。"""
    tokens: List[InlineToken] = []
    pos = 0
    for m in _CHEM_RE.finditer(text):
        if m.start() < pos:
            continue
        if m.start() > pos:
            tokens.append(IText(text[pos:m.start()]))
        if m.group("sub") is not None:
            tokens.append(ISub(m.group("sub")))
        else:
            tokens.append(ISup(m.group("sup")))
        pos = m.end()
    if pos < len(text):
        tokens.append(IText(text[pos:]))
    return tokens or [IText(text)]


def tokenize_inline(text: str) -> List[InlineToken]:
    """把一行 Markdown 文本解析为行内 token 列表（可嵌套）。"""
    text = text.strip("\n")
    tokens: List[InlineToken] = []
    pos = 0
    for m in _INLINE_RE.finditer(text):
        if m.start() > pos:
            tokens.extend(_chem_tokens(text[pos:m.start()]))
        kind = m.lastgroup
        raw = m.group()
        if kind == "code":
            tokens.append(ICode(raw[1:-1]))
        elif kind == "bold":
            tokens.append(IBold(tokenize_inline(raw[2:-2])))
        elif kind == "ital":
            tokens.append(IItalic(tokenize_inline(raw[1:-1])))
        elif kind == "uital":
            tokens.append(IItalic(tokenize_inline(raw[1:-1])))
        pos = m.end()
    if pos < len(text):
        tokens.extend(_chem_tokens(text[pos:]))
    # 合并相邻文本
    merged: List[InlineToken] = []
    for t in tokens:
        if isinstance(t, IText) and merged and isinstance(merged[-1], IText):
            merged[-1].value += t.value
        else:
            merged.append(t)
    return merged


# ===========================================================================
# 块级 block
# ===========================================================================
@dataclass
class BHeading:
    level: int                 # 映射后的层级（## →1，### →2 …）
    text: str                  # 纯文本
    tokens: List[InlineToken]
    hash_count: int            # 原始 # 数量
    raw: str


@dataclass
class BParagraph:
    tokens: List[InlineToken]
    raw: str


@dataclass
class BListItem:
    tokens: List[InlineToken]
    raw: str


@dataclass
class BList:
    ordered: bool
    items: List[BListItem]


@dataclass
class BTable:
    header: List[str]
    aligns: List[str]          # left/center/right/None
    rows: List[List[str]]
    raw: str


@dataclass
class BCode:
    text: str
    lang: str


Block = Union[BHeading, BParagraph, BList, BTable, BCode]


# ===========================================================================
# 清洗（在块解析之前）
# ===========================================================================
_HR_RE = re.compile(r"^\s*(?:[-*_]\s*){3,}$")
_FENCE_RE = re.compile(r"^(\s*)```(.*)$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_LIST_RE = re.compile(r"^\s*(?:([-*+])|(\d+[.)]))\s+(.*)$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{1,}[\s:|-]*$")

# 过程性括注：（…占位/待填/待补充/待实测…）、（…placeholder…）
_PROC_PAREN_RE = re.compile(
    r"[（(][^（）()]*?(?:占位|待填|待补充|待实测|placeholder|to be filled)[^（）()]*?[）)]",
    re.IGNORECASE,
)
# 引用占位 {A-1} / {A1} / {1} → [1]
_CITE_PH_RE = re.compile(r"\{\s*[A-Za-z]{0,3}[-–]?(\d{1,3})\s*\}")

# 过程块起始标记（去掉前导 **# 后）
_PROC_BLOCK_RE = re.compile(
    r"^(?:\*\*)?\s*(?:引用说明|引用标注|引用注|citation\s*notes?|notes?\s*on\s*citations)",
    re.IGNORECASE,
)


def _is_process_block(block: str) -> bool:
    first = block.strip().split("\n", 1)[0].lstrip("># ").strip()
    return bool(_PROC_BLOCK_RE.match(first))


#: 前置声明/写作元信息段标题（连同其下属内容整体剥离——投稿前删除）
_DECL_SECTION_RE = re.compile(r"前置声明|投稿前删除|硬约束自查|自查清单|内部清单")
#: write 自带参考文献标题（参考文献统一由导出引擎从 search refs 渲染，剥离 write 自带版避免重复）
_REF_SECTION_RE = re.compile(r"^(?:references|bibliography|参考文献|参考文献)$", re.IGNORECASE)


def _strip_meta_sections(text: str) -> str:
    """标题感知地剥离 write 正文中的写作元信息段（代码围栏内不识别标题）。

    - **前置声明段**：标题含「前置声明 / 投稿前删除」，连同其下属内容一起丢弃，
      直到遇到下一个同级或更高级标题（``#`` 数量相同或更少 = 同级/更高级）；
    - **write 自带参考文献段**：标题归一后命中 ``references / bibliography /
      参考文献``，同样丢弃该段——参考文献统一由导出引擎从 search 阶段 refs
      渲染，避免成稿里出现两份。

    只剥目标段本身；若参考文献段之后（正常不会）还有同级标题，会保留其后内容。
    """
    lines = text.split("\n")
    out: List[str] = []
    in_fence = False
    drop_level = 0  # >0：正在丢弃某段；记录触发标题的 # 数量
    for ln in lines:
        if _FENCE_RE.match(ln):
            in_fence = not in_fence
            if drop_level == 0:
                out.append(ln)
            continue
        if in_fence:
            if drop_level == 0:
                out.append(ln)
            continue
        hm = _HEADING_RE.match(ln)
        if hm:
            hashes = len(hm.group(1))
            htext = hm.group(2).strip()
            # 命中前置声明或 write 自带参考文献 → 进入丢弃模式
            if _DECL_SECTION_RE.search(htext) or _REF_SECTION_RE.match(_norm_heading_text(htext)):
                drop_level = hashes
                continue
            # 同级或更高级标题 → 退出丢弃段并保留该标题
            if drop_level > 0 and hashes <= drop_level:
                drop_level = 0
            if drop_level == 0:
                out.append(ln)
            continue
        if drop_level > 0:
            continue
        out.append(ln)
    return "\n".join(out)


def clean_write(content: str) -> str:
    """清洗 write 正文：剥离前置声明/自带参考文献段，去水平分隔线/过程块/过程括注，规范化引用编号。"""
    # 1) 行级：去水平分隔线
    kept_lines = [ln for ln in content.split("\n") if not _HR_RE.match(ln)]
    text = "\n".join(kept_lines)

    # 1.5) 标题感知：剥离前置声明段与 write 自带参考文献段
    text = _strip_meta_sections(text)

    # 2) 块级（空行分段）：去过程块（代码围栏内不动）
    out_blocks: List[str] = []
    in_fence = False
    for block in re.split(r"\n[ \t]*\n", text):
        fence_markers = len(re.findall(r"^\s*```", block, flags=re.MULTILINE))
        if not in_fence and _is_process_block(block):
            in_fence = bool(fence_markers % 2)
            continue
        in_fence = bool(in_fence ^ (fence_markers % 2))
        out_blocks.append(block)
    text = "\n\n".join(out_blocks)

    # 3) 行内：去过程括注 + 引用占位归一
    text = _PROC_PAREN_RE.sub("", text)
    text = _CITE_PH_RE.sub(r"[\1]", text)
    # 删除括注后可能在冒号前残留空格（"Figure captions :" → "Figure captions:"）
    text = re.sub(r"(captions?)\s+(:)", r"\1\2", text, flags=re.IGNORECASE)
    # 清理因删除括注残留的行尾/连续空格
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" *\n", "\n", text)
    return text.strip()


# ===========================================================================
# 表格工具
# ===========================================================================
def _split_cells(line: str) -> List[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith(r"\|"):
        s = s[:-1]
    s = s.replace(r"\|", "\x00")
    return [c.strip().replace("\x00", "|") for c in s.split("|")]


def _parse_table(lines: List[str]) -> BTable:
    header = _split_cells(lines[0])
    sep_cells = _split_cells(lines[1])
    aligns: List[str] = []
    for c in sep_cells:
        left, right = c.startswith(":"), c.endswith(":")
        aligns.append("center" if left and right else "left" if left else "right" if right else "")
    rows = [_split_cells(ln) for ln in lines[2:]]
    n = len(header)
    rows = [r + [""] * (n - len(r)) for r in rows]
    return BTable(header=header, aligns=aligns, rows=[r[:n] for r in rows], raw="\n".join(lines))


# ===========================================================================
# 块解析
# ===========================================================================
def _parse_blocks(text: str) -> List[Block]:
    lines = text.split("\n")
    blocks: List[Block] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        # 代码围栏
        fm = _FENCE_RE.match(line)
        if fm:
            lang = fm.group(2).strip()
            buf: List[str] = []
            i += 1
            while i < n and not _FENCE_RE.match(lines[i]):
                buf.append(lines[i])
                i += 1
            i += 1  # 跳过收尾 ```
            blocks.append(BCode(text="\n".join(buf), lang=lang))
            continue

        # 标题
        hm = _HEADING_RE.match(line)
        if hm:
            hashes, htext = hm.group(1), hm.group(2).strip()
            hc = len(hashes)
            level = {1: 1, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5}[hc]
            blocks.append(BHeading(level=level, text=htext,
                                   tokens=tokenize_inline(htext), hash_count=hc, raw=line.strip()))
            i += 1
            continue

        # 表格（当前行含 |，下一行是分隔线）
        if "|" in line and i + 1 < n and _TABLE_SEP_RE.match(lines[i + 1]):
            tbl = [line]
            i += 1
            tbl.append(lines[i])  # 分隔线
            i += 1
            while i < n and lines[i].strip() and "|" in lines[i]:
                tbl.append(lines[i])
                i += 1
            blocks.append(_parse_table(tbl))
            continue

        # 列表（连续行）
        lm0 = _LIST_RE.match(line)
        if lm0:
            ordered = bool(lm0.group(2))
            items: List[BListItem] = []
            while i < n:
                lm = _LIST_RE.match(lines[i])
                if not lm:
                    break
                itext = lm.group(3).strip()
                items.append(BListItem(tokens=tokenize_inline(itext), raw=itext))
                i += 1
            blocks.append(BList(ordered=ordered, items=items))
            continue

        # 段落：累积到下一空行/特殊行
        buf = []
        while i < n and lines[i].strip():
            ln = lines[i]
            if _FENCE_RE.match(ln) or _HEADING_RE.match(ln) or _LIST_RE.match(ln):
                break
            if "|" in ln and i + 1 < n and _TABLE_SEP_RE.match(lines[i + 1]):
                break
            buf.append(ln.lstrip("> ").rstrip())
            i += 1
        raw = " ".join(buf).strip()
        if raw:
            blocks.append(BParagraph(tokens=tokenize_inline(raw), raw=raw))
    return blocks


# ===========================================================================
# 语义识别 + 组装
# ===========================================================================
def _norm_heading_text(t: str) -> str:
    return re.sub(r"[\s:*：.]+", "", t).lower()


def _is_abstract_heading(b: Block) -> bool:
    return isinstance(b, BHeading) and _norm_heading_text(b.text) in ("abstract", "摘要")


_KEYWORDS_RE = re.compile(
    r"^\s*(?:\*\*\s*)?(keywords?|关键词|关键字|key\s*words)\s*[:：]?\s*(?:\*\*)?",
    re.IGNORECASE,
)


def _extract_keywords(raw: str) -> Optional[tuple]:
    m = _KEYWORDS_RE.match(raw.strip())
    if not m:
        return None
    label = m.group(1)
    rest = raw.strip()[m.end():].strip()
    # 冒号可能落在闭合 ** 之后（`**关键词**：GDC…`），正则已吃掉闭合 **，
    # 但后随的全角/半角冒号与空白会残留在第一个关键词前——剥掉。
    rest = re.sub(r"^[:：\s]+", "", rest).strip()
    # 主分隔符 ; ／ ；；缺失时回退逗号
    if re.search(r"[;；]", rest):
        kws = [k.strip() for k in re.split(r"[;；]", rest)]
    else:
        kws = [k.strip() for k in re.split(r"[,，]", rest)]
    kws = [k for k in kws if k]
    return label, kws


def _count_cjk(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def _count_latin_words(text: str) -> int:
    return len(re.findall(r"[A-Za-z]+", text))


@dataclass
class ParsedPaper:
    title: str
    title_tokens: List[InlineToken] = field(default_factory=list)
    lang: str = "en"                       # zh / en
    abstract_label: str = ""               # 源标题文本，如 "Abstract"
    abstract_paragraphs: List[BParagraph] = field(default_factory=list)
    keywords_label: str = ""
    keywords: List[str] = field(default_factory=list)
    blocks: List[Block] = field(default_factory=list)

    def references_label(self) -> str:
        return "参考文献" if self.lang == "zh" else "References"


def parse_paper(write_content: str, fallback_title: str = "未命名论文") -> ParsedPaper:
    """解析 write 正文为 :class:`ParsedPaper`。"""
    cleaned = clean_write(write_content)
    all_blocks = _parse_blocks(cleaned)

    # 定位摘要标题
    abs_idx = next((k for k, b in enumerate(all_blocks) if _is_abstract_heading(b)), -1)
    abs_heading = all_blocks[abs_idx] if abs_idx >= 0 else None

    # 论文标题：摘要之前、位于文首的唯一 level-1（#）标题
    title_heading: Optional[BHeading] = None
    if abs_heading is not None:
        for k in range(abs_idx):
            b = all_blocks[k]
            if isinstance(b, BHeading) and b.hash_count == 1 and k == 0:
                title_heading = b
                break

    if title_heading is not None:
        title = title_heading.text
        title_tokens = title_heading.tokens
    else:
        title = fallback_title or "未命名论文"
        title_tokens = tokenize_inline(title)

    # 收集摘要段落（直到同级/更高级标题）
    abstract_paragraphs: List[BParagraph] = []
    if abs_heading is not None:
        base_level = abs_heading.hash_count
        for k in range(abs_idx + 1, len(all_blocks)):
            b = all_blocks[k]
            if isinstance(b, BHeading) and b.hash_count <= base_level:
                break
            # 关键词段落不属于摘要
            if isinstance(b, BParagraph) and _extract_keywords(b.raw):
                break
            if isinstance(b, BParagraph):
                abstract_paragraphs.append(b)

    # 关键词：优先摘要区之后的第一个标记段落，否则全文第一个
    keywords: List[str] = []
    keywords_label = ""
    kw_block_idx = -1
    start_search = abs_idx + 1 + len(abstract_paragraphs) if abs_idx >= 0 else 0
    for k in list(range(start_search, len(all_blocks))) + list(range(0, start_search)):
        b = all_blocks[k]
        if isinstance(b, BParagraph):
            found = _extract_keywords(b.raw)
            if found:
                keywords_label, keywords = found
                kw_block_idx = k
                break

    # 正文块：剔除 标题/摘要标题/摘要段落/关键词段落
    abs_para_ids = {id(b) for b in abstract_paragraphs}
    body: List[Block] = []
    for k, b in enumerate(all_blocks):
        if title_heading is not None and b is title_heading:
            continue
        if abs_heading is not None and b is abs_heading:
            continue
        if id(b) in abs_para_ids:
            continue
        if k == kw_block_idx:
            continue
        body.append(b)

    # 语言判定
    probe = title + " " + " ".join(
        b.raw for b in all_blocks if hasattr(b, "raw")
    )
    cjk, latin = _count_cjk(probe), _count_latin_words(probe)
    lang = "zh" if cjk > 0 and cjk >= 0.1 * max(latin, 1) else "en"

    if not abstract_paragraphs and abs_heading is None:
        abstract_label = ""
    else:
        abstract_label = abs_heading.text if abs_heading is not None else ""
    if not keywords:
        keywords_label = ""

    return ParsedPaper(
        title=title,
        title_tokens=title_tokens,
        lang=lang,
        abstract_label=abstract_label,
        abstract_paragraphs=abstract_paragraphs,
        keywords_label=keywords_label or ("关键词" if lang == "zh" else "Keywords"),
        keywords=keywords,
        blocks=body,
    )
