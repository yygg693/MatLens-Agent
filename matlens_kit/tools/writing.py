"""写作辅助类材料工具：参考文献格式化 / 实验段落润色提示。

内置 GB/T 7714、IEEE、APA 三种引文格式与材料论文实验表述建议库。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from tools.registry import registry, tool_result


# ─────────────────────────────────────────────────────────────
# ① 参考文献格式化
# ─────────────────────────────────────────────────────────────
def _format_authors(authors: str, style: str) -> str:
    """作者列表格式化。

    Args:
        authors: 作者，逗号分隔（如 "张三, 李四, 王五" 或 "Zhang S, Li L, Wang W"）。
        style: gb7714 / ieee / apa。

    Returns:
        格式化后的作者部分。
    """
    names = [a.strip() for a in re_split(authors) if a.strip()]
    if not names:
        return ""
    if style == "gb7714":
        if len(names) > 3:
            return names[0] + " 等"
        return "、".join(names)
    if style == "ieee":
        return ", ".join(names[:3]) + ("  et al." if len(names) > 3 else "")
    # apa
    if len(names) >= 3:
        return names[0] + " et al."
    return " & ".join(names)


def re_split(authors: str) -> List[str]:
    """按中英文逗号/分号拆分作者。"""
    import re

    return [a for a in re.split(r"[,，;；]", authors) if a.strip()]


def citation_format_tool(
    style: str,
    authors: str = "",
    year: str = "",
    title: str = "",
    journal: str = "",
    volume: str = "",
    issue: str = "",
    pages: str = "",
    doi: str = "",
    publisher: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """参考文献格式化（GB/T 7714 / IEEE / APA）。

    Args:
        style: gb7714（中文国标）| ieee | apa。
        authors: 作者列表（逗号分隔）。
        year: 年份。
        title: 题名/标题。
        journal: 期刊名（书籍填出版社，学位论文填学校）。
        volume: 卷号。
        issue: 期号。
        pages: 页码（如 100-110 或 100-110）。
        doi: DOI 号。
        publisher: 出版社（书籍用）。

    Returns:
        格式化引文 + 组成说明。
    """
    if style not in ("gb7714", "ieee", "apa"):
        return {"error": f"未知格式：{style}（可选 gb7714 / ieee / apa）"}
    if not authors and not title:
        return {"error": "至少需要提供作者或题名"}
    fa = _format_authors(authors, style)
    doi_txt = doi.strip()
    if style == "gb7714":
        if journal:  # 期刊文章
            cite = f"{fa}. {title}[J]. {journal}, {year}, {volume}({issue}): {pages}."
        elif publisher:  # 书籍
            cite = f"{fa}. {title}[M]. {publisher}: {publisher and '出版社' or ''}, {year}."
        else:
            cite = f"{fa}. {title}[J]. {journal or ''}, {year}."
        if doi_txt:
            cite += f" DOI: {doi_txt}."
    elif style == "ieee":
        if journal:
            cite = f"{fa}, \u201c{title},\u201d {journal}, vol. {volume}, no. {issue}, pp. {pages}, {year}."
        elif publisher:
            cite = f"{fa}, {title}. {publisher}, {year}."
        else:
            cite = f"{fa}, \u201c{title},\u201d {year}."
        if doi_txt:
            cite += f" doi: {doi_txt}."
    else:  # apa
        if journal:
            cite = f"{fa} ({year}). {title}. *{journal}*, *{volume}*({issue}), {pages}."
        elif publisher:
            cite = f"{fa} ({year}). *{title}*. {publisher}."
        else:
            cite = f"{fa} ({year}). *{title}*."
        if doi_txt:
            cite += f" https://doi.org/{doi_txt}"
    return {"style": style, "citation": cite, "components": {
        "authors": authors, "year": year, "title": title, "journal": journal,
        "volume": volume, "issue": issue, "pages": pages, "doi": doi_txt,
    }}


CITATION_FORMAT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": "参考文献格式化：GB/T 7714 / IEEE / APA 三种格式。",
    "examples": [{"style": "ieee", "authors": "Zhang, Wei", "year": "2024", "title": "A study", "journal": "J. Mater. Sci.", "volume": "59", "pages": "120-130"}],
    "properties": {
        "style": {"type": "string", "enum": ["gb7714", "ieee", "apa"],
                  "description": "引文格式：gb7714 中文国标 / ieee / apa"},
        "authors": {"type": "string", "description": "作者（逗号分隔，如 张三, 李四）"},
        "year": {"type": "string", "description": "年份"},
        "title": {"type": "string", "description": "题名"},
        "journal": {"type": "string", "description": "期刊名"},
        "volume": {"type": "string", "description": "卷号"},
        "issue": {"type": "string", "description": "期号"},
        "pages": {"type": "string", "description": "页码"},
        "doi": {"type": "string", "description": "DOI"},
        "publisher": {"type": "string", "description": "出版社（书籍）"},
    },
    "required": ["style"],
    "additionalProperties": False,
}


# ─────────────────────────────────────────────────────────────
# ② 实验段落润色提示
# ─────────────────────────────────────────────────────────────
WRITING_TIPS: Dict[str, List[str]] = {
    "synthesis": [
        "首句点明合成目标与关键策略：\u201c为了获得粒径均匀的 X，采用溶剂热法在 Y 条件下合成。\u201d",
        "试剂用量精确表述：\u201c称取 0.50 g（2.1 mmol）前驱体\u201d（质量+物质的量双标注，便于复现）",
        "条件参数完整：温度、时间、气氛、升温速率一个不落，如 \u201c以 2 ℃/min 升温至 600 ℃ 并保温 3 h\u201d",
        "避免口语化：\u201c把料混合\u201d → \u201c将前驱体与沉淀剂按 1:2 摩尔比混合\u201d",
        "后处理标准化表述：\u201c产物用去离子水和无水乙醇交替离心洗涤 3 次，60 ℃ 真空干燥 12 h\u201d",
    ],
    "characterization": [
        "表征结果与仪器条件对应：\u201cXRD 图谱（Cu Kα，λ=1.5406 Å）显示…\u201d",
        "峰位定量表述而非\u201c有几个峰\u201d：\u201c在 2θ = 27.3°、35.9° 处观察到特征衍射峰，归属于锐钛矿相（JCPDS 21-1272）\u201d",
        "形貌描述量化：\u201cSEM 显示粒径约为 50–80 nm 的均匀球形颗粒\u201d（给出统计范围而非\u201c较小\u201d）",
        "性能数据带单位与误差：\u201c比容量为 128.5 mAh/g（0.5 A/g，第 100 圈）\u201d",
        "避免主观词：\u201c很好的性能\u201d → \u201c优于文献报道的 X（123 mAh/g）\u201d（有对比才有说服力）",
    ],
    "structure": [
        "逻辑链：现象→数据→归属→结论，每段一个核心论点",
        "段落衔接用逻辑连接词：\u201c进一步地\u201d\u201c值得注意的是\u201d\u201c与此一致\u201d",
        "中文表达精炼：删除\u201c进行了…的研究\u201d\u201c对…进行了分析\u201d等冗余结构",
        "时态一致：实验过程用一般过去时，普遍规律用一般现在时",
    ],
}


def experiment_writing_tool(
    scenario: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    """材料论文实验部分写作润色建议。

    Args:
        scenario: "synthesis"（合成实验）| "characterization"（表征测试）| "structure"（论文结构表达）。

    Returns:
        专业表述建议列表与常用句式。
    """
    tips = WRITING_TIPS.get(scenario)
    if tips is None:
        return {"error": f"未知场景：{scenario}（可选 synthesis / characterization / structure）"}
    return {
        "scenario": scenario,
        "tips": tips,
        "general_rule": "材料论文实验部分的核心标准：可复现、可量化、可溯源——每个数字带单位，每个条件带参数，每句话有依据",
    }


EXPERIMENT_WRITING_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": "材料论文实验部分写作润色建议与常用句式。",
    "examples": [{"scenario": "synthesis"}],
    "properties": {
        "scenario": {"type": "string", "enum": ["synthesis", "characterization", "structure"],
                     "description": "写作场景：synthesis 合成实验 / characterization 表征测试 / structure 结构表达"},
    },
    "required": ["scenario"],
    "additionalProperties": False,
}


# ─────────────────────────────────────────────────────────────
# 注册
# ─────────────────────────────────────────────────────────────
def _check_writing_available() -> bool:
    return True


registry.register(
    name="citation_format",
    toolset="matlens_material",
    schema=CITATION_FORMAT_SCHEMA,
    handler=lambda args, **kw: tool_result(citation_format_tool(**args)),
    check_fn=_check_writing_available,
    description="参考文献格式化：GB/T 7714 / IEEE / APA 三种格式",
    emoji="📚",
)

registry.register(
    name="experiment_writing",
    toolset="matlens_material",
    schema=EXPERIMENT_WRITING_SCHEMA,
    handler=lambda args, **kw: tool_result(experiment_writing_tool(scenario=args.get("scenario", "synthesis"))),
    check_fn=_check_writing_available,
    description="材料论文实验部分写作润色建议与常用句式（合成/表征/结构三类场景）",
    emoji="✍️",
)
