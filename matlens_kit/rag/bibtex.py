# -*- coding: utf-8 -*-
"""MatLens · 题录文件解析（RIS / BibTeX / EndNote / RefWorks）。

为什么需要这个模块
------------------
知网无公开 API（见 docs/kb_cloud_sources_research.md），**官网人工检索 →
导出题录 → 本地导入**是唯一合规入口。但目前「添加文献」只能导入 .txt/.pdf，
无法解析这些数据库导出的题录格式 —— 于是这条唯一合法的中文文献通路是断的。

支持格式
--------
===========  ==================================================================
格式          典型来源
===========  ==================================================================
RIS           知网/万方/PubMed/EndNote 默认导出
BibTeX        Google Scholar / Zotero / Overleaf
EndNote        知网「导出 → EndNote」；RefWorks 的英文变体
RefWorks      知网「导出 → Refworks」（中文文献主力格式）
NoteExpress    导出格式与 RefWorks 高度重合，一并支持
===========  ==================================================================

⚠️ RefWorks 解析的两个坑（实测踩过）
--------------------------------------
1. ``%0`` 既是**类型标记**（%0 Journal Article）又是**多条分隔符**
   （``%A 张伟%0 李明`` 中 %0 分隔两个作者）。必须区分：
   - ``%0`` 在行首且后跟类型词 → 类型
   - ``%0`` 紧跟在其他 ``%X`` 值之后 → 分隔符
2. 标签不总是两个字符（``%A3``、``%J1``、``%B6`` 都是知网导出的变体），
   因此**不能**假设固定 ``%XY``，要用「``%`` + 字母 + 可选数字」的模式。

**只解析题录元数据，不抓全文** —— 全文仍走用户手动下载或 OA 降级链。
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List

# ────────────────────────────────────────────────────────────
# 格式识别
# ────────────────────────────────────────────────────────────
#: 知网 RefWorks 实际使用的标签（覆盖非标准变体）
REFWORKS_TAGS = {
    "T": "title", "A": "authors", "J": "journal", "B": "booktitle",
    "C": "city", "D": "year", "V": "volume", "N": "issue",
    "P": "pages", "R": "note", "U": "url", "X": "keywords",
    "G": "language", "I": "publisher", "K": "keywords2",
    "F": "label", "S": "special", "W": "secondary",
}

RIS_TYPE_MAP = {
    "JOUR": "journal_article", "JFULL": "journal_article",
    "BOOK": "book", "CHAP": "book_section", "CONF": "conference",
    "THES": "thesis", "RPRT": "report", "ELEC": "web",
    "GEN": "generic", "MGZN": "magazine_article", "NEWS": "news",
}

BIBTEX_TYPE_MAP = {
    "article": "journal_article", "book": "book", "inproceedings": "conference",
    "incollection": "book_section", "phdthesis": "thesis",
    "mastersthesis": "thesis", "techreport": "report", "misc": "generic",
}

#: RefWorks 系格式的 %0 类型词表（知网/EndNote/NoteExpress 实际用到的）。
#: 实测踩过的坑：漏掉「Book Section」会导致整条记录被当成上一条的续写而丢失。
REFWORKS_TYPE_WORDS = (
    "Journal Article", "Book", "Book Section", "Book Series", "Book Chapter",
    "Conference Paper", "Article in a Conference", "Conference Proceedings",
    "Thesis", "Dissertation", "Report", "Web Page", "Generic",
    "Magazine Article", "Newspaper Article", "Journal", "Article",
)


def detect_format(text: str, filename: str = "") -> str:
    """按内容特征判断格式（文件名只作次要依据）。"""
    head = (text or "")[:4000]
    low = filename.lower()

    # BibTeX：@type{ key,
    if re.search(r"^\s*@\w+\s*\{", head, re.M):
        return "bibtex"
    # RIS：TY  - JOUR / ER  -
    if re.search(r"^TY\s{2}-\s*\w+", head, re.M) and re.search(r"^ER\s{2}-", head, re.M):
        return "ris"
    # RefWorks / EndNote / NoteExpress：%0 类型 + %T/%A 标签
    if re.search(r"^%0\s+\w", head, re.M):
        return "refworks"
    # 后缀兜底：只对扩展名明确的格式生效。
    # ⚠️ 不要无条件把 .txt 兜底成 refworks —— .txt 也可能是普通说明文档。
    # 但知网最常用的导出后缀恰恰是 .txt，所以这里改判「内容像不像题录」：
    # 有 %T（标题）或 %A（作者）标签才算，否则交给 auto 试探。
    if low.endswith(".bib") or low.endswith(".bibtex"):
        return "bibtex"
    if low.endswith(".ris"):
        return "ris"
    if low.endswith(".enw") or low.endswith(".refworks") or low.endswith(".rw"):
        return "refworks"
    if low.endswith(".txt") and re.search(r"^%[TA]\s?\S", head, re.M):
        return "refworks"
    return "unknown"


# ────────────────────────────────────────────────────────────
# RIS
# ────────────────────────────────────────────────────────────
def parse_ris(text: str) -> List[Dict[str, Any]]:
    """解析 RIS。``ER  -`` 结束一条记录，``TY`` 开始一条。"""
    out: List[Dict[str, Any]] = []
    cur: Dict[str, Any] = {}
    last_key: str = ""

    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        m = re.match(r"^([A-Z][A-Z0-9])\s{2}-\s?(.*)$", line)
        if not m:
            m = re.match(r"^([A-Z][A-Z0-9])\s*-\s?(.*)$", line)
        if not m:
            # 续行：并入上一个字段
            if last_key and cur.get(last_key):
                cur[last_key] = (str(cur[last_key]) + " " + line.strip()).strip()
            continue
        tag, val = m.group(1), m.group(2).strip()
        if tag == "TY":
            cur = {"entry_type": RIS_TYPE_MAP.get(val.upper(), "generic")}
            last_key = ""
            continue
        if tag == "ER":
            if cur:
                out.append(_finalize(cur))
            cur = {}
            last_key = ""
            continue

        fld = _ris_field(tag)
        if not fld:
            last_key = ""
            continue
        if fld == "authors":
            cur.setdefault("authors", []).append(val)
            last_key = "authors"
            return_val = val
        elif fld == "keywords":
            cur.setdefault("keywords", []).append(val)
            last_key = "keywords"
            return_val = val
        else:
            # 同一标签重复出现时保留首个（如多行 TI）
            cur.setdefault(fld, val)
            last_key = fld
            return_val = cur[fld]
    if cur:
        out.append(_finalize(cur))
    return out


def _ris_field(tag: str) -> str:
    m = {
        "TI": "title", "T1": "title", "BT": "title", "ST": "subtitle",
        "AU": "authors", "A1": "authors", "PY": "year", "DA": "date",
        "JO": "journal", "JF": "journal", "T2": "journal_secondary",
        "VL": "volume", "IS": "issue", "SP": "start_page",
        "EP": "end_page", "DO": "doi", "UR": "url", "L1": "url",
        "AB": "abstract", "N1": "note", "KW": "keywords", "PB": "publisher",
        "CY": "city", "LA": "language", "SN": "issn",
    }
    return m.get(tag.upper(), "")


# ────────────────────────────────────────────────────────────
# BibTeX
# ────────────────────────────────────────────────────────────
def parse_bibtex(text: str) -> List[Dict[str, Any]]:
    """解析 BibTeX（够用即可，不追求完整实现）。"""
    out: List[Dict[str, Any]] = []
    if not text:
        return out
    # 按 @type{...} 切块；花括号嵌套用计数处理
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,\s]*)\s*,", text):
        btype = m.group(1).lower()
        start = m.end()
        depth = 1
        i = start
        while i < len(text) and depth > 0:
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            i += 1
        body = text[start:i - 1] if depth == 0 else text[start:]
        rec = _parse_bib_body(body)
        rec["entry_type"] = BIBTEX_TYPE_MAP.get(btype, btype)
        rec["citation_key"] = m.group(2)
        out.append(_finalize(rec))
    return out


def _parse_bib_body(body: str) -> Dict[str, Any]:
    rec: Dict[str, Any] = {}
    # field = {value} 或 "value" 或 number
    pat = re.compile(r"(\w+)\s*=\s*(\{(?:[^{}]|\{[^{}]*\})*\}|[\"'][^\"']*[\"']|[^,\n]+)\s*,?", re.S)
    for fm in pat.finditer(body):
        key = fm.group(1).strip().lower()
        val = fm.group(2).strip()
        if val.startswith("{") and val.endswith("}"):
            # 只剥最外层。直接 re.sub 掉所有花括号会毁掉
            # ``title = {A {nested} title}`` 里的嵌套内容（实测踩过）。
            val = val[1:-1]
        elif val[:1] in ("\"", "'") and val[-1:] == val[:1]:
            val = val[1:-1]
        val = val.strip()
        amap = {
            "title": "title", "author": "authors", "journal": "journal",
            "journaltitle": "journal", "booktitle": "booktitle",
            "year": "year", "date": "date", "volume": "volume",
            "number": "issue", "issue": "issue", "pages": "pages",
            "page": "pages", "doi": "doi", "url": "url", "abstract": "abstract",
            "keywords": "keywords", "publisher": "publisher",
            "language": "language", "issn": "issn", "note": "note",
        }
        tgt = amap.get(key)
        if not tgt:
            continue
        if tgt == "authors":
            rec.setdefault("authors", [])
            for a in re.split(r"\s+and\s+", val, flags=re.I):
                if a.strip():
                    rec["authors"].append(a.strip())
        elif tgt == "keywords":
            rec.setdefault("keywords", [])
            rec["keywords"].extend([k.strip() for k in re.split(r"[;,]", val) if k.strip()])
        else:
            rec.setdefault(tgt, val)
    return rec


# ────────────────────────────────────────────────────────────
# RefWorks / EndNote / NoteExpress
# ────────────────────────────────────────────────────────────
def parse_refworks(text: str) -> List[Dict[str, Any]]:
    """解析 RefWorks 系格式（知网/EndNote/NoteExpress）。

    ⚠️ 核心难点（实测）：
    ``%A 张伟%0 李明`` —— 这里的 ``%0`` **不是类型标记，而是多条分隔符**。
    判定规则：
      - ``%0`` 出现在行首，且后跟英文类型词（Journal Article / Book …）→ 类型
      - ``%0`` 紧跟其它 ``%X`` 的值之后 → 分隔符，把当前字段切成多条
    另外知网会导出 ``%A3`` / ``%J1`` 这类变体，故用 ``%`` + 字母 + 可选数字 匹配。
    """
    out: List[Dict[str, Any]] = []
    cur: Dict[str, Any] = {}
    pending: str = ""          # 正在累积值的标签
    pending_value: str = ""    # 该标签已累积的值（遇 %0 分隔符时被切成多条）
    TYPE_WORDS = REFWORKS_TYPE_WORDS

    def flush_multi(tag: str, values: List[str]) -> None:
        fld = REFWORKS_TAGS.get(tag)
        if not fld:
            return
        if fld == "authors":
            cur.setdefault("authors", [])
            for v in values:
                cur["authors"].append(v.strip())
        elif fld in ("keywords", "keywords2"):
            cur.setdefault("keywords", [])
            for v in values:
                cur["keywords"].extend([k.strip() for k in re.split(r"[;,，]", v) if k.strip()])
        else:
            # 期刊/书名等取首个非空，其余并入 note（多值通常意味着脏数据）
            first = next((v for v in values if v.strip()), "")
            if fld not in cur or not cur[fld]:
                cur[fld] = first.strip()
            else:
                cur.setdefault("note", "")
                cur["note"] = (str(cur["note"]) + " | " +
                               " / ".join(v for v in values if v.strip()))[:600]

    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        # 标签：% + 单字符（字母或数字）+ 值
        # ⚠️ 实测踩过两个坑，都在这里：
        #  1. ``%0`` 后面是**数字 0**（类型标记），用 ``%([A-Za-z])`` 永远匹配不到
        #     → 每条记录不会开始新条目，多记录文件被并成一条。故用 ``\w``。
        #  2. 知网会导出 ``%A3`` / ``%J1`` 这类变体，故标签后允许**多个字符**。
        m = re.match(r"^%(\w{1,2})\s?(.*)$", line)
        if not m:
            continue
        # ``%A3`` / ``%J1`` 变体：取首字母作为标签位（知网导出的尾部数字无语义）
        tag = m.group(1)[0].upper()
        # 「0」是类型标记位，单独保留完整 token 供判定
        if m.group(1)[0] == "0":
            tag = "0"
        val = (m.group(2) or "").strip()

        # --- 行内 %0 分隔符（知网特有，实测最坑的一处）---
        # ``%A 张伟%0 李明%0 王芳`` 整行只会匹配到 %A，%0 混在值内部。
        # 必须按标签处理之前先拆，否则三位作者会粘成一条。
        # 注意 tag != "0"：``%0 Journal Article`` 里的 %0 是**类型标记**，
        # 不能当分隔符拆（实测漏了这个判断会导致整条记录丢失）。
        if tag != "0" and "%0" in val:
            parts = [p.strip() for p in re.split(r"%0\s*", val) if p.strip()]
            if pending and pending_value:
                flush_multi(pending, [pending_value])
            pending = ""
            pending_value = ""
            if parts:
                flush_multi(tag, parts)
            continue

        # --- %0 独立成行：类型标记 ---
        if tag == "0":
            head_val = val.strip()
            looks_type = any(head_val.lower().startswith(w.lower()) for w in TYPE_WORDS)
            at_line_start = (line.lstrip().startswith("%0"))
            if looks_type or (at_line_start and not cur):
                if pending and pending_value:
                    flush_multi(pending, [pending_value])
                    pending = ""
                    pending_value = ""
                if cur:
                    out.append(_finalize(cur))
                cur = {"entry_type": _refworks_type(head_val)}
                continue
            # 不是类型 → 当作上一标签的分隔续写
            if pending and pending_value:
                flush_multi(pending, [pending_value])
            pending = ""
            pending_value = val
            continue

        # 遇到新标签：先落盘上一个标签累积的值
        if pending and pending_value:
            flush_multi(pending, [pending_value])
        pending = tag
        pending_value = val

    if pending and pending_value:
        flush_multi(pending, [pending_value])
    if cur:
        out.append(_finalize(cur))
    return out


def _refworks_type(v: str) -> str:
    s = (v or "").lower()
    if "journal" in s:
        return "journal_article"
    if "conference" in s:
        return "conference"
    if "book section" in s or "chapter" in s:
        return "book_section"
    if "book" in s:
        return "book"
    if "thesis" in s:
        return "thesis"
    if "report" in s:
        return "report"
    return "generic"


# ────────────────────────────────────────────────────────────
# 统一收尾
# ────────────────────────────────────────────────────────────
def _finalize(rec: Dict[str, Any]) -> Dict[str, Any]:
    """规整字段：补 DOI 规范化、作者去重、拼页码。"""
    r = dict(rec)
    r.pop("_tmp", None)

    # RefWorks 的 %R 常直接放 DOI（可能带 "DOI:" 前缀或 URL 形式）
    if not r.get("doi") and r.get("note"):
        n = str(r["note"]).strip()
        stripped = re.sub(r"^doi\s*[:：]\s*", "", n, flags=re.I)
        if re.match(r"^(?:https?://(?:dx\.)?doi\.org/)?10\.\d{4,9}/", stripped, re.I):
            r["doi"] = stripped

    doi = (r.get("doi") or "").strip()
    if doi:
        # RefWorks 常写 "DOI:10.xxxx/yyy"
        doi = re.sub(r"^doi\s*[:：]\s*", "", doi, flags=re.I).strip()
        doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.I)
        r["doi"] = doi
    # DOI 常常只在 note 里（RefWorks %R，且可能写成 URL 形式）
    if not r.get("doi") and r.get("note"):
        n = str(r["note"])
        m = re.search(r"https?://(?:dx\.)?doi\.org/(10\.\d{4,9}/[^\s|,;]+)", n, re.I)
        if not m:
            m = re.search(r"10\.\d{4,9}/[^\s|,;]+", n)
        if m:
            r["doi"] = m.group(1) if m.lastindex else m.group(0).rstrip(".")

    # 页码：SP+EP 或直接 pages（去掉 BibTeX 的双连字符）
    if not r.get("pages"):
        sp, ep = r.pop("start_page", ""), r.pop("end_page", "")
        if sp and ep:
            r["pages"] = f"{sp}-{ep}"
        else:
            r.pop("start_page", None)
            r.pop("end_page", None)
    if r.get("pages"):
        r["pages"] = str(r["pages"]).replace("--", "-").strip()

    au = r.get("authors") or []
    seen = set()
    uniq = []
    for a in au:
        a = str(a).strip()
        if a and a not in seen:
            seen.add(a)
            uniq.append(a)
    r["authors"] = uniq

    y = str(r.get("year") or "").strip()
    m = re.search(r"(19|20)\d{2}", y)
    r["year"] = m.group(0) if m else (y[:4] if y else "")

    for k in ("title", "journal", "booktitle", "abstract", "url", "publisher", "language"):
        if k in r:
            r[k] = str(r[k]).strip()
    return r


def parse_bibliography(text: str, filename: str = "") -> Dict[str, Any]:
    """自动识别格式并解析。返回 ``{format, count, items, errors}``。"""
    fmt = detect_format(text, filename)
    errors: List[str] = []
    try:
        if fmt == "ris":
            items = parse_ris(text)
        elif fmt == "bibtex":
            items = parse_bibtex(text)
        elif fmt == "refworks":
            items = parse_refworks(text)
        else:
            # 兜底：依次尝试，拿到最多结果的那个
            cands = []
            for fn in (parse_ris, parse_bibtex, parse_refworks):
                try:
                    cands.append(fn(text))
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{fn.__name__}: {e}")
            items = max(cands, key=len) if cands else []
            fmt = "auto"
    except Exception as e:  # noqa: BLE001
        errors.append(str(e))
        items = []

    # 只保留有标题的条目（题录没标题说明没解析对）
    good = [x for x in items if (x.get("title") or "").strip()]
    if items and not good and errors:
        errors.append("解析出 %d 条但均无标题，可能格式识别错误" % len(items))
    if not good:
        good = items

    return {
        "ok": bool(good),
        "format": fmt,
        "count": len(good),
        "skipped": len(items) - len(good),
        "items": good,
        "errors": errors[:5],
    }


def parse_bibliography_file(path: str) -> Dict[str, Any]:
    """从文件解析（自动处理编码与 BOM）。"""
    try:
        raw = open(path, "rb").read()
    except OSError as e:
        return {"ok": False, "format": "unknown", "count": 0, "items": [],
                "errors": [f"读取失败：{e}"]}
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except Exception:
            continue
    else:
        text = raw.decode("utf-8", "replace")
    res = parse_bibliography(text, os.path.basename(path))
    res["source_file"] = os.path.basename(path)
    return res


def to_markdown(items: List[Dict[str, Any]]) -> str:
    """把题录列表渲染成 Markdown（供写盘后进知识库索引）。

    只用题录字段拼装，**不含正文** —— 正文需用户下载 PDF 或走 OA 降级链。
    """
    blocks = []
    for i, it in enumerate(items, 1):
        lines = [f"# {i}. {it.get('title') or '（无标题）'}", ""]
        meta = []
        if it.get("authors"):
            au = it["authors"]
            meta.append("- 作者：" + "，".join(au[:12]) + (" 等" if len(au) > 12 else ""))
        if it.get("journal"):
            meta.append("- 出处：" + it["journal"])
        if it.get("booktitle"):
            meta.append("- 出处：" + it["booktitle"] + "（会议/文集）")
        if it.get("year"):
            meta.append("- 年份：" + it["year"])
        for label, key in (("卷", "volume"), ("期", "issue"), ("页码", "pages")):
            if it.get(key):
                meta.append(f"- {label}：{it[key]}")
        if it.get("doi"):
            meta.append("- DOI：" + it["doi"])
        if it.get("url"):
            meta.append("- 链接：" + it["url"])
        if it.get("keywords"):
            kw = it["keywords"]
            meta.append("- 关键词：" + "，".join(kw[:8]))
        lines.extend(meta)
        if it.get("abstract"):
            lines += ["", "## 摘要", "", str(it["abstract"])]
        lines += ["", "> 由 MatLens 解析题录文件生成（仅元数据，非全文）。"]
        blocks.append("\n".join(lines))
    return "\n\n---\n\n".join(blocks)