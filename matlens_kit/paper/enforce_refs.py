# -*- coding: utf-8 -*-
"""论文工坊 · 引用白名单强制（enforce_refs）。

两条职责（单一事实源，供 prompts / quality / api 共用）：
(a) 写前注入：write 步渲染 prompt 时，把 search 步核验 refs 作为**引用白名单**
    注入上下文，提示模型只能引用 [1..N]（杜绝幻觉引用）。
(b) 写后核验：quality 步扫描正文里所有 [n] 上标编号，凡落在白名单数量范围
    之外的（>N 或 <1）记入质检报告的「引用越界」条目——只标警告，不抛异常。

设计：纯函数、无副作用、不依赖 LLM；返回结构化 issue 字典，
由 quality.render_report 统一渲染为 Markdown。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

#: 匹配 [1] / [1,2] / [1-3] / [1, 2-4] 形式的上标引用标记
_CITE_RE = re.compile(r"\[([0-9,\-\s]+)\]")

#: 匹配写作阶段遗留的占位引用格式：{A-1} / {A1} / {a-3} / {X-10} / {10} 等。
#: 这类占位符绕过了 [n] 白名单校验，导出前必须替换为真实编号或删除。
_PLACEHOLDER_CITE_RE = re.compile(r"\{[A-Za-z]{0,3}[-\u2013]?(\d{1,3})\}")


def detect_placeholder_citations(text: str) -> List[str]:
    """检测正文里遗留的占位引用格式（{A-1} / {A1} / {a-3} / {X-10} / {10} 等）。

    正则：``\\{[A-Za-z]{0,3}[-\\u2013]?(\\d{1,3})\\}``
    （字母前缀 0–3 个，可选连字符 / en-dash，1–3 位数字，整体花括号包裹）。

    返回匹配到的**原文片段**列表（保持出现顺序、允许重复）。这类占位符不被
    ``_CITE_RE`` 识别，因此绕过白名单校验——写作完成后必须替换为白名单编号
    ``[n]`` 或删除。
    """
    return [m.group(0) for m in _PLACEHOLDER_CITE_RE.finditer(text or "")]


def parse_citation_ids(text: str) -> List[int]:
    """抽取正文里所有引用编号（展开连写/区间），保持出现顺序、允许重复。

    例："见[1][2,3]和[4-6]" -> [1,2,3,4,5,6]
    无法解析的 token（空、非数字）直接跳过，不报错。
    """
    ids: List[int] = []
    for mark in _CITE_RE.findall(text or ""):
        for part in mark.replace(" ", "").split(","):
            if not part:
                continue
            if "-" in part:
                try:
                    a, b = part.split("-")
                    lo, hi = int(a), int(b)
                    if lo > hi:
                        lo, hi = hi, lo
                    ids.extend(range(lo, hi + 1))
                except ValueError:
                    continue
            else:
                try:
                    ids.append(int(part))
                except ValueError:
                    continue
    return ids


def out_of_range_ids(text: str, ref_count: int) -> List[int]:
    """返回正文里引用了但白名单内不存在的编号（去重、升序）。

    ref_count == 0 时视为白名单为空——此时任何编号都算越界。
    """
    ids = parse_citation_ids(text)
    if not ids:
        return []
    valid = set(range(1, ref_count + 1))
    bad = sorted({n for n in ids if n not in valid})
    return bad


def check_refs_whitelist(draft: str, refs: Optional[List[Any]] = None) -> List[Dict[str, str]]:
    """生成「引用越界」质检 issue 列表（纯数据，不抛异常）。

    - 正文出现 {A-n} 占位引用格式 -> 🔴（导出硬伤，必须替换为白名单 [n] 或删除）
    - 白名单为空但正文有占位引用 / [n] 引用 -> 🟡（检索步未核验文献）
    - 白名单非空：正文出现 >N 或 <1 的 [n] 编号 -> 🔴
    """
    refs = refs or []
    ref_count = len(refs)
    issues: List[Dict[str, str]] = []

    # ── 0. 占位引用格式（{A-n} 等）——绕过 [n] 白名单校验的漏洞 ──
    placeholders = detect_placeholder_citations(draft)
    if placeholders:
        n_ph = len(placeholders)
        sample = ", ".join(placeholders[:5])
        more = "" if n_ph <= 5 else f" 等 {n_ph} 处"
        # 占位符是导出硬伤：无论白名单是否就绪都必须修掉
        if ref_count > 0:
            ph_suggest = "把 {A-n} 占位符替换为白名单内的文献编号 [1]-[%d]，或删除未核验文献" % ref_count
        else:
            ph_suggest = "把 {A-n} 占位符替换为真实文献编号 [n]，或删除未核验文献"
        issues.append({
            "severity": "🔴",
            "location": "引用越界",
            "issue": f"正文使用占位引用格式 {sample}{more}，必须替换为白名单编号 [n] 或删除",
            "suggestion": ph_suggest,
        })
        if ref_count == 0:
            issues.append({
                "severity": "🟡",
                "location": "引用越界",
                "issue": f"正文存在 {n_ph} 处占位引用但检索步未核验文献（白名单为空）",
                "suggestion": "先完成文献检索建立白名单，再把占位符统一替换为真实 [n] 编号",
            })

    if ref_count > 0:
        bad = out_of_range_ids(draft, ref_count)
        if bad:
            shown = ", ".join(f"[{n}]" for n in bad[:10])
            more = "" if len(bad) <= 10 else f" 等 {len(bad)} 个"
            issues.append({
                "severity": "🔴",
                "location": "引用越界",
                "issue": f"正文引用了白名单之外的编号：{shown}{more}（白名单共 {ref_count} 条）",
                "suggestion": "删除或改写为白名单内的文献编号 [1]-[%d]" % ref_count,
            })
    else:
        if parse_citation_ids(draft):
            issues.append({
                "severity": "🟡",
                "location": "引用越界",
                "issue": f"正文有 {len(parse_citation_ids(draft))} 处引用标记，但检索步未核验任何文献（白名单为空）",
                "suggestion": "先完成文献检索以建立白名单，或删除虚构引用",
            })
    return issues


def whitelist_block(refs: Optional[List[Any]] = None) -> str:
    """把引用白名单渲染为 prompt 文本块（复用 prompts.refs_text）。"""
    from matlens_kit.paper.prompts import refs_text

    return refs_text(refs)


def inject_whitelist(ctx: Dict[str, Any], refs: Optional[List[Any]] = None) -> Dict[str, Any]:
    """写前注入：把 search 步 refs 白名单写进 prompt 渲染上下文。

    保证 ctx["refs_text"] 总是存在且反映最新白名单；供 write/outline 步使用。
    """
    ctx["refs_text"] = whitelist_block(refs or [])
    ctx["ref_count"] = len(refs or [])
    return ctx
