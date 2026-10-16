# -*- coding: utf-8 -*-
"""论文工坊 · Markdown / LaTeX 导出渲染器测试。

直接 import matlens_kit.paper.export_text（不经过 export 门面——门面依赖
尚未就绪的 export_docx）。只用 stdlib + pytest，无网络。
"""
from __future__ import annotations

import pytest

from matlens_kit.paper.export_text import export_latex, export_markdown
from matlens_kit.paper.md_model import clean_write, parse_paper


# ---------------------------------------------------------------------------
# 合成论文
# ---------------------------------------------------------------------------
WRITE = """# Study of E_a in ceramics

## Abstract

This is the abstract body. It mentions the activation energy E_a and the
grain-boundary conductivity sigma_gb^sp as examples.

**Keywords:** foo; bar; baz

## 1. Introduction

Intro paragraph with a 50% discount & a $100 budget and a #tag to test escaping.

### 1.1 Background

- item one
- item two

1. first step
2. second step

| Col A | Col B | Col C |
|:--|--:|:--:|
| E_a/cm^-1 | sigma_gb^sp | 50% & x |
| value | 0.95 | # tag |

```python
print("hi")
```
"""

REFS = [
    {
        "title": "A study of GDC electrolytes",
        "authors": "Zhang Y, Li X",
        "year": "2021",
        "source": "OpenAlex·Journal of Power Sources",
        "doi": "10.1000/xyz",
    },
    {
        "title": "Second paper on ceramics",
        "authors": "Wang Z",
        "year": "2020",
        "source": "OpenAlex·Nature Energy",
        "doi": "",
    },
]


def _paper(refs=None, write=WRITE):
    return {
        "title": "Study of E_a in ceramics",
        "stages": {
            "write": {"content": write},
            "search": {"refs": refs if refs is not None else REFS},
        },
    }


# 工作流阶段标签 / 过程字样，绝不能出现在成稿里
FORBIDDEN = ["选题设定", "文献检索", "大纲生成", "逐章写作",
             "质量巡检", "模拟审稿", "引用说明"]


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------
def test_markdown_structure():
    md = export_markdown(_paper(), "gb7714")
    assert md.startswith("# Study of E_a in ceramics")
    assert "## Abstract" in md
    assert "This is the abstract body." in md
    assert "**Keywords:** foo; bar; baz" in md
    assert "## 1. Introduction" in md
    assert "### 1.1 Background" in md
    # 列表（有序按规范统一用 "1. "，markdown 自动编号）
    assert "- item one" in md and "- item two" in md
    assert "1. first step" in md and "1. second step" in md
    # 表格 raw 保留
    assert "| Col A | Col B | Col C |" in md
    assert "| E_a/cm^-1 |" in md
    # 代码围栏
    assert "```python" in md
    # 参考文献区
    assert "## References" in md


def test_markdown_forbidden_absent():
    md = export_markdown(_paper(), "gb7714")
    for word in FORBIDDEN:
        assert word not in md


def test_markdown_refs_gb7714():
    md = export_markdown(_paper(), "gb7714")
    assert "[1] Zhang Y, Li X." in md
    assert "[J]" in md  # gb7714 期刊类型标记


def test_markdown_refs_acs_period_separated():
    md = export_markdown(_paper(), "acs")
    # acs 句点分段（作者句点、期刊. 年.），不带 [J]
    assert "[1] Zhang Y, Li X." in md
    assert "Journal of Power Sources. 2021." in md
    assert "[J]" not in md


# ---------------------------------------------------------------------------
# LaTeX
# ---------------------------------------------------------------------------
def test_latex_preamble_and_structure():
    tex = export_latex(_paper(), "gb7714")
    assert r"\documentclass[12pt]{ctexart}" in tex
    assert r"\usepackage[margin=2.5cm]{geometry}" in tex
    assert r"\usepackage{amsmath,amssymb}" in tex
    assert r"\setlength{\parindent}{2em}" in tex
    assert r"\maketitle" in tex
    assert r"\title{Study of E" in tex  # title 渲染（E_a 的 E）
    assert r"\begin{abstract}" in tex and r"\end{abstract}" in tex
    # 关键词行
    assert r"\noindent\textbf{Keywords: }foo; bar; baz" in tex


def test_latex_headings_numbered_nonstarred():
    tex = export_latex(_paper(), "gb7714")
    assert r"\section{1. Introduction}" in tex
    assert r"\subsection{1.1 Background}" in tex
    # 正文章节用编号命令（非 starred）；全文仅参考文献区用一次 starred
    assert tex.count(r"\section*{") == 1
    assert r"\section*{References}" in tex


def test_latex_special_char_escaping():
    tex = export_latex(_paper(), "gb7714")
    assert r"50\%" in tex
    assert r"\&" in tex          # & 转义
    assert r"\$100" in tex       # $ 转义
    assert r"\#tag" in tex       # #tag -> \# tag（空格保留）
    # 化学式 E_a -> E\textsubscript{a}
    assert r"E\textsubscript{a}" in tex


def test_latex_table_and_lists():
    tex = export_latex(_paper(), "gb7714")
    assert r"\begin{tabular}" in tex
    assert r"\hline" in tex
    assert r"\textbf{Col A}" in tex  # 表头加粗
    assert r"\begin{itemize}" in tex
    assert r"\begin{enumerate}" in tex
    assert r"\item item one" in tex
    # verbatim 代码块
    assert r"\begin{verbatim}" in tex


def test_latex_references_compilable():
    tex = export_latex(_paper(), "gb7714")
    assert r"\section*{References}" in tex
    assert r"\small" in tex
    # 每条参考文献作为独立段落，含 [n]
    assert "[1] Zhang Y, Li X." in tex
    assert "[J]" in tex


# ---------------------------------------------------------------------------
# 空 write
# ---------------------------------------------------------------------------
def test_empty_write_returns_empty():
    empty = {"title": "x", "stages": {"write": {"content": ""}, "search": {"refs": REFS}}}
    assert export_markdown(empty, "gb7714") == ""
    assert export_latex(empty, "gb7714") == ""


# ---------------------------------------------------------------------------
# 清洗：剥离前置声明段 + write 自带参考文献段
# ---------------------------------------------------------------------------
WRITE_WITH_META = """# My Paper Title

## Abstract

Abstract body here.

**Keywords:** foo; bar

## 0 前置声明（写作文前信息，投稿前删除）

**命名锁定：** abbreviation GDC means gadolinium doped ceria.

**数据状态：** all numbers are proposed.

## 1. Introduction

Real intro paragraph that must survive.

## References

[1] Some reference entry written by the model.
[2] Another self-listed reference.
"""


def test_clean_strips_preamble_and_self_references():
    cleaned = clean_write(WRITE_WITH_META)
    # 前置声明段整体剥离
    assert "前置声明" not in cleaned
    assert "命名锁定" not in cleaned
    assert "数据状态" not in cleaned
    # write 自带参考文献段整体剥离（避免与 search refs 重复）
    assert "References" not in cleaned
    assert "[1] Some reference entry" not in cleaned
    assert "[2] Another self-listed reference" not in cleaned
    # 论文真正内容保留
    assert "# My Paper Title" in cleaned
    assert "Abstract body here." in cleaned
    assert "Real intro paragraph that must survive." in cleaned


def test_parse_paper_drops_meta_sections():
    paper = parse_paper(WRITE_WITH_META, fallback_title="t")
    body_text = " ".join(getattr(b, "raw", "") for b in paper.blocks)
    # body 块里没有前置声明、没有自带参考文献条目
    assert "前置声明" not in body_text
    assert "命名锁定" not in body_text
    assert "References" not in body_text
    assert "[1] Some reference entry" not in body_text
    # 真正的章节保留
    assert "Real intro paragraph that must survive." in body_text
    assert any(getattr(b, "text", "") == "1. Introduction" for b in paper.blocks
               if hasattr(b, "text"))


def test_export_markdown_no_duplicate_references():
    # write 自带 References + search refs：成稿只出现一份参考文献（来自 search）
    p = {"title": "My Paper Title",
         "stages": {"write": {"content": WRITE_WITH_META},
                    "search": {"refs": REFS}}}
    md = export_markdown(p, "gb7714")
    # 前置声明不泄漏
    assert "前置声明" not in md and "命名锁定" not in md
    # 自带模型参考文献不出现
    assert "Some reference entry written by the model" not in md
    # search refs 渲染出的参考文献恰好一份
    assert md.count("## References") == 1
    assert "[1] Zhang Y, Li X." in md


# ---------------------------------------------------------------------------
# 关键词前导冒号剥离（评审点名："关键词 '：：' 重复"）
# ---------------------------------------------------------------------------
def test_extract_keywords_leading_colon_forms():
    from matlens_kit.paper.md_model import _extract_keywords
    # 冒号在闭合星号之后（中文全角冒号）——历史缺陷形态
    assert _extract_keywords("**关键词**：GDC；bar；baz")[1] == ["GDC", "bar", "baz"]
    # 冒号在星号内（正常形态）
    assert _extract_keywords("**关键词:** GDC；bar")[1] == ["GDC", "bar"]
    # 英文
    assert _extract_keywords("**Keywords:** foo; bar")[1] == ["foo", "bar"]
    # 半角冒号在闭合星号后
    assert _extract_keywords("**关键词**: GDC；bar")[1] == ["GDC", "bar"]


def test_export_keywords_no_double_colon():
    write = "# T\n\n## 摘要\n\nabstract body.\n\n**关键词**：GDC；bar；baz\n\n## 1 引言\n\nintro paragraph.\n"
    p = {"title": "T", "stages": {"write": {"content": write}, "search": {"refs": []}}}
    md = export_markdown(p, "gb7714")
    assert "**关键词:** GDC；bar；baz" in md
    # 不再出现「：：」或「**: ：」重复冒号
    assert "：：" not in md
    assert ":** ：" not in md


# ---------------------------------------------------------------------------
# 清洗：剥离「附：硬约束自查」等内部 QA 清单段
# ---------------------------------------------------------------------------
WRITE_WITH_CHECKLIST = """# My Paper Title

## Abstract

Abstract body.

**Keywords:** foo; bar

## 1. Introduction

Real intro paragraph.

## 参考文献

[1] Model self-listed reference.

## 附：硬约束自查

| 约束 | 状态 |
|---|---|
| A 数据占位 | ✅ |
| B 声称克制 | ✅ |

**需要你确认的两处口径**：这里是与用户的内部对话，必须剥离。
"""


def test_clean_strips_hard_constraint_checklist():
    cleaned = clean_write(WRITE_WITH_CHECKLIST)
    # 自查清单段整体剥离（含其下表格与内部对话）
    assert "硬约束自查" not in cleaned
    assert "约束" not in cleaned  # 表头「| 约束 | 状态 |」随段剥离
    assert "A 数据占位" not in cleaned
    assert "需要你确认的两处口径" not in cleaned
    # 自带参考文献也剥离
    assert "Model self-listed reference" not in cleaned
    # 正文保留
    assert "Real intro paragraph." in cleaned


def test_export_no_checklist_leak():
    p = {"title": "My Paper Title",
         "stages": {"write": {"content": WRITE_WITH_CHECKLIST},
                    "search": {"refs": REFS}}}
    md = export_markdown(p, "gb7714")
    assert "硬约束自查" not in md
    assert "需要你确认的两处口径" not in md
    assert "Real intro paragraph." in md
    # 参考文献只来自 search refs，恰好一份
    assert md.count("## References") == 1
    assert "[1] Zhang Y, Li X." in md
