# -*- coding: utf-8 -*-
"""论文工坊 · 质量巡检（自研三维检查，本地规则、无需 LLM）。

维度：
1. 引用核验 —— 正文 [n] 是否在白名单范围内、有无悬空/格式错误
2. 结构检查 —— 引言/方法/结果/讨论/结论 关键章节是否完整、长度是否达标
3. AI 味启发式 —— 机械连接词 / 句式重复 / 空话套话

输出问题清单：[{severity: 🔴|🟡|🟢, location, issue, suggestion}]
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

# ── 机械连接词 / 空话（AI 味信号） ──
_MECHANICAL_PHRASES = [
    "首先", "其次", "最后", "综上所述", "总而言之", "众所周知",
    "值得注意的是", "需要指出的是", "不言而喻", "毋庸置疑",
    "随着.*的发展", "在当今", "近年来，随着",
]
_EMPTY_PHRASES = [
    "具有重要意义", "具有重大意义", "有着广阔的应用前景",
    "受到了广泛关注", "引起了广泛关注", "发挥着重要作用",
    "为.*提供了新的思路", "为.*奠定了坚实基础",
]

# ── 关键章节（研究论文） ──
_RESEARCH_SECTIONS = ["引言", "方法", "结果", "讨论", "结论"]
# ── 综述关键章节 ──
_REVIEW_SECTIONS = ["引言", "展望", "结论"]


def _extract_citations(text: str) -> List[str]:
    """提取正文引用标记 [n] / [n,m] / [n-m]（含 [1][2] 连排）。"""
    return re.findall(r"\[([0-9,\-\s]+)\]", text)


def _split_sentences(text: str) -> List[str]:
    """按句号/感叹号/问号切句（忽略缩写）。"""
    parts = re.split(r"(?<=[。！？!?])\s*", text)
    return [p for p in parts if p and len(p) > 4]


# ─────────────────────────────────────────────────────────────────────
# 学术评审级维度（本地规则、不调 LLM）—— 对应 DeepSeek 评审 8 条意见
# ─────────────────────────────────────────────────────────────────────

# 表格单元格占位符（数据完整性）
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?[\s:\-|]+\|?\s*$")
_BAD_CELLS = {"", "—", "–", "---", "-", "tbd", "n/a"}
# 学术规范的"未报道"标注（对比表对综述/机制类文献未给出参数的诚实写法），不计入占位糊弄
_UNREPORTED_CELL_RE = re.compile(
    r"^\s*n\.?\s*r\.?\s*$"          # N.R. / N.R / n.r. / N. R.
    r"|^\s*n\.?\s*d\.?\s*$"         # N.D. / n.d.
    r"|^\s*not\s*reported\.?\s*$"   # not reported / Not Reported
    r"|^\s*未报道\s*$",              # 未报道
    re.I,
)
_BODY_PLACEHOLDER_RE = re.compile(r"待填|待补充|占位")

# 强声称 / 证据 / 弱声称
_STRONG_CLAIM_RE = re.compile(r"\b(identified|confirmed|verified|established|governing)\b", re.I)
_EVIDENCE_RE = re.compile(
    r"XPS|STEM|TGA|DRT|EIS|EDS|XRD|Raman|SEM|direct\s+evidence|spectroscop|measured",
    re.I,
)
_WEAK_CLAIM_RE = re.compile(r"hypothesis|proposed|consistent\s+with", re.I)

# 对照实验词
_CONTROL_RE = re.compile(
    r"control|对照|co-doped|reference|baseline|undoped|未掺杂|"
    r"单独\s*Ca|烧结助剂|bilayer|双层|组分系列|x\s*=\s*0|vs\.?\b",
    re.I,
)

# 文献对比
_COMPARE_CTX_RE = re.compile(r"compare|对比|ocv|ppd|performance|性能", re.I)
_CITE_NUM_RE = re.compile(r"\[\d+\]")

# 稳定性时长（100 h / 100h / 500 小时）
_DURATION_RE = re.compile(r"(\d{1,4})\s*(h|hours|小时)\b", re.I)


def _table_cell_placeholder_count(draft: str) -> int:
    """统计表格区域（含 | 的行）中"空 / — / – / -- / - / TBD / N/A"占位单元格数量。

    自动跳过 Markdown 表头分隔行（|---|---|），并去掉首尾管道符产生的空串，
    避免把分隔行和表格外框误判为占位数据。
    """
    count = 0
    for line in (draft or "").splitlines():
        if "|" not in line:
            continue
        if "-" in line and _TABLE_SEPARATOR_RE.match(line):
            continue  # Markdown 表头分隔行
        cells = line.split("|")
        stripped = line.strip()
        if stripped.startswith("|") and cells:
            cells = cells[1:]
        if stripped.endswith("|") and cells:
            cells = cells[:-1]
        for cell in cells:
            stripped_cell = cell.strip()
            # 学术规范的 N.R./N.D./not reported/未报道 是诚实标注，不计入占位
            if _UNREPORTED_CELL_RE.match(stripped_cell):
                continue
            if stripped_cell.lower() in _BAD_CELLS:
                count += 1
    return count


def _data_integrity_issues(draft: str) -> List[Dict[str, str]]:
    """数据完整性：表格单元格占位符 + 正文「待填/占位/待补充」括注。"""
    issues: List[Dict[str, str]] = []
    n_table = _table_cell_placeholder_count(draft)
    if n_table >= 6:
        issues.append({
            "severity": "🔴",
            "location": "数据",
            "issue": f"表格中出现 {n_table} 处空/—/TBD/N/A 占位单元格，数据严重不完整",
            "suggestion": "填入实测值；确无实验值时填拟议值并标注「拟议值，待实验确认」，同时补误差棒/重复次数/测试条件",
        })
    elif n_table >= 3:
        issues.append({
            "severity": "🟡",
            "location": "数据",
            "issue": f"表格中出现 {n_table} 处空/—/TBD/N/A 占位单元格",
            "suggestion": "填入实测值或拟议值（标注「拟议值，待实验确认」），并补测试条件/误差",
        })
    n_body = len(_BODY_PLACEHOLDER_RE.findall(draft))
    if n_body:
        issues.append({
            "severity": "🟡",
            "location": "数据",
            "issue": f"正文出现 {n_body} 处「待填/占位/待补充」括注",
            "suggestion": "删除占位提示文字，替换为具体数值与测试条件",
        })
    return issues


def _numbers_near(text: str, start: int, span: int = 90) -> List[float]:
    out = []
    for tok in re.findall(r"\d+\.?\d*", text[start:start + span]):
        try:
            out.append(float(tok))
        except ValueError:
            pass
    return out


def _has_low_sigma_e(text: str) -> bool:
    for m in re.finditer(r"σ[_\s]*e|σₑ|electronic\s+conductivity", text, re.I):
        for v in _numbers_near(text, m.end()):
            if 0 < v <= 0.01:
                return True
    return False


def _has_high_tion(text: str) -> bool:
    for m in re.finditer(r"\bt_?ion\b|tᵢₒₙ|transference\s+number", text, re.I):
        for v in _numbers_near(text, m.end()):
            if 0.95 <= v <= 1.0:
                return True
    return False


_NUM_SELF_SUPPORT_RE = re.compile(
    r"σ[_\s]*total|σtotal|总电导|ionic\s+conductivity|离子电导|σ[_\s]*ion|σion|"
    r"×\s*t|t\s*[×x]|brick-layer|等效电路|计算",
    re.I,
)


def _numerical_self_consistency_issues(draft: str) -> List[Dict[str, str]]:
    """数值自洽：σ_e≤0.01 且 t_ion≥0.95 时，检查总电导/离子电导构成与计算过程。"""
    issues: List[Dict[str, str]] = []
    if _has_low_sigma_e(draft) and _has_high_tion(draft):
        if not _NUM_SELF_SUPPORT_RE.search(draft):
            issues.append({
                "severity": "🟡",
                "location": "数值自洽",
                "issue": "σ_e ≤ 0.01 与 t_ion ≥ 0.95 同现，但缺少总电导/离子电导构成与计算过程支撑",
                "suggestion": "补充 σ_total = σ_ion + σ_e 的分解或 σ_ion = t_ion × σ_total 的数值演算，证明两数自洽",
            })
    # 同一指标两处不同数值且无解释
    for name, pat in (("σ_e", r"σ[_\s]*e|σₑ"), ("t_ion", r"\bt_?ion\b|tᵢₒₙ|transference\s+number")):
        vals = set()
        for m in re.finditer(pat, draft, re.I):
            tail = draft[m.end():m.end() + 30]
            eq = re.match(r"\s*[=≈:~≤≥<>]?\s*(\d+\.?\d*)", tail)
            if eq:
                try:
                    vals.add(round(float(eq.group(1)), 4))
                except ValueError:
                    pass
        if len(vals) >= 2:
            issues.append({
                "severity": "🟡",
                "location": "数值自洽",
                "issue": f"指标 {name} 在正文出现多个不同数值（{sorted(vals)}）且无差异解释",
                "suggestion": "统一数值或说明不同测试条件/温度下的取值差异",
            })
    return issues


def _claim_evidence_issues(draft: str) -> List[Dict[str, str]]:
    """声称-证据一致性：强声称词附近 200 字无直接实验证据。"""
    flagged: List[str] = []
    for m in _STRONG_CLAIM_RE.finditer(draft):
        lo = max(0, m.start() - 200)
        hi = min(len(draft), m.end() + 200)
        if not _EVIDENCE_RE.search(draft[lo:hi]):
            flagged.append(m.group(0).lower())
    if not flagged:
        return []
    uniq = sorted(set(flagged))
    weak = bool(_WEAK_CLAIM_RE.search(draft))
    issue = (f"强声称词「{', '.join(uniq)}」附近 200 字内无直接实验证据"
             f"（XPS/STEM/TGA/DRT/EIS/spectroscopy/measured 等）")
    suggestion = "把 identified/confirmed/verified 改为 proposed / consistent with，或补对应表征/测试的定量证据"
    if weak:
        issue += "；且与 hypothesis/proposed 等弱声称混用，措辞强度需统一"
        suggestion += "，并统一强弱声称措辞"
    return [{"severity": "🟡", "location": "声称", "issue": issue, "suggestion": suggestion}]


def _control_experiment_issues(draft: str) -> List[Dict[str, str]]:
    """对照实验：结果/讨论区有无对照样品/对比路线词。"""
    if _CONTROL_RE.search(draft):
        return []
    return [{
        "severity": "🟡",
        "location": "对照",
        "issue": "结果/讨论未见对照样品或对比路线设计",
        "suggestion": "补充对照（undoped/baseline/reference、单独 Ca 掺杂、烧结助剂、bilayer 双层、组分系列 x=0.0 等）以支撑归因",
    }]


def _literature_comparison_issues(draft: str) -> List[Dict[str, str]]:
    """文献对比：性能对比语境下是否有具体 [n] 引用与测试参数。"""
    if not _COMPARE_CTX_RE.search(draft):
        return []
    issues: List[Dict[str, str]] = []
    # (1) reported/对比 语境附近无 [n]
    vague = 0
    for m in re.finditer(r"reported|compared\s+to|对比", draft, re.I):
        window = draft[max(0, m.start() - 120):m.end() + 120]
        if not _CITE_NUM_RE.search(window):
            vague += 1
    if vague:
        issues.append({
            "severity": "🟡",
            "location": "文献对比",
            "issue": f"存在性能对比语境（{vague} 处 reported/对比），但附近无具体文献编号 [n] 与测试参数（温度/厚度/燃料）",
            "suggestion": "对比句后补 [n] 引用，并标注文献的温度/厚度/燃料/OCV/PPD，避免笼统的 \"Reported GDC cells\"",
        })
    # (2) 对比表（含 Ref./文献/Reported 列）整块无任何 [n]
    lines = draft.splitlines()
    i = 0
    while i < len(lines):
        if "|" in lines[i]:
            block = []
            while i < len(lines) and "|" in lines[i]:
                block.append(lines[i])
                i += 1
            block_text = "\n".join(block)
            if re.search(r"ref\.?|文献|reported|this\s+work|对比", block_text, re.I) \
                    and not _CITE_NUM_RE.search(block_text):
                issues.append({
                    "severity": "🟡",
                    "location": "文献对比",
                    "issue": "对比表（含 Ref./文献/Reported/This work 列）中没有任何 [n] 文献编号",
                    "suggestion": "在 Ref. 列填入白名单文献编号 [n]，并补全温度/厚度/燃料/OCV/PPD 参数",
                })
        else:
            i += 1
    return issues


def _stability_issues(draft: str) -> List[Dict[str, str]]:
    """稳定性表述：≤500 h 短时测试与 stable/稳定/长期 同现。"""
    flagged: List[int] = []
    for m in _DURATION_RE.finditer(draft):
        hrs = int(m.group(1))
        if not (1 <= hrs <= 500):
            continue
        window = draft[max(0, m.start() - 80):m.end() + 80]
        if re.search(r"stable|稳定|长期", window, re.I):
            flagged.append(hrs)
    if not flagged:
        return []
    rep = min(flagged)
    return [{
        "severity": "🟡",
        "location": "稳定性",
        "issue": f"出现 {rep} h 量级短时测试与 stable/长期 同现（如 stable operation over {rep} h）",
        "suggestion": "明确标注 short-term，或补充 500–1000 h 长期运行数据后再称 stable/长期稳定",
    }]


# ─────────────────────────────────────────────────────────────────────
# 第二轮：数据自洽 / 化学常识 / 对照完整性 / 统计力（本地启发式）
# ─────────────────────────────────────────────────────────────────────

#: 化学常识：Gd³⁺(CN8≈1.05 Å) 实际大于 Ce⁴⁺(≈0.97 Å)，Gd 掺杂通常增大晶格常数
_GD_PRESENT_RE = re.compile(r"Gd")
_LATTICE_DOWN_RE = re.compile(
    r"晶格常数[^。\n]{0,12}(下降|减小|降低)|lattice\s+constant[^.]{0,20}(decreas|reduc)",
    re.I,
)
_WRONG_RADIUS_RE = re.compile(r"Gd[³3+]*[^。\n]{0,10}半径[^。\n]{0,6}(小于|更小|less)")


def _chem_fact_issues(draft: str) -> List[Dict[str, str]]:
    """化学常识：Gd 掺杂却称晶格常数下降/半径更小。"""
    if not _GD_PRESENT_RE.search(draft):
        return []
    if _LATTICE_DOWN_RE.search(draft) or _WRONG_RADIUS_RE.search(draft):
        return [{
            "severity": "🟡",
            "location": "化学事实",
            "issue": "Gd 掺杂与「晶格常数下降/减小」或「Gd³⁺ 半径小于 Ce⁴⁺」表述同现；"
                     "实际 Gd³⁺(CN8≈1.05 Å) 半径大于 Ce⁴⁺(≈0.97 Å)，Gd 掺杂通常使晶格常数增大",
            "suggestion": "核对 Rietveld 晶格常数随 Gd 含量的变化方向；若确实下降，须给出氧空位收缩/价态补偿等替代解释，而非「半径更小」",
        }]
    return []


#: 比例-活化能：Ea_bulk/Ea_gb 不同 但 σ_gb/σ_bulk 比例在温度序列上恒定
_EA_PAIR_RE = re.compile(r"Ea[_\s/]*(?:bulk|gb|晶界|体相)?[^\d]{0,20}(\d+\.\d+)\s*/\s*(\d+\.\d+)")


def _ratio_ea_consistency_issues(draft: str) -> List[Dict[str, str]]:
    m = _EA_PAIR_RE.search(draft)
    if not m:
        return []
    ea1, ea2 = float(m.group(1)), float(m.group(2))
    if abs(ea1 - ea2) < 0.05:
        return []  # 活化能相同，比例可恒定
    # 只取 Ea 所在表格块内的温度行，避免污染到其他表
    lines = draft.splitlines()
    ea_idx = None
    for i, line in enumerate(lines):
        if "Ea" in line and str(ea1) in line:
            ea_idx = i
            break
    if ea_idx is None:
        return []
    block: List[str] = []
    j = ea_idx
    while j >= 0 and "|" in lines[j]:
        block.append(lines[j]); j -= 1
    j = ea_idx + 1
    while j < len(lines) and "|" in lines[j]:
        block.append(lines[j]); j += 1
    ratios: List[float] = []
    for line in block:
        if "Ea" in line or "活化能" in line or "°C" not in line:
            continue
        cond = [float(n) for n in re.findall(r"\d+\.\d+", line) if 1e-4 <= float(n) <= 1.0]
        if len(cond) >= 2:
            ratios.append(cond[1] / cond[0])
    if len(ratios) >= 3:
        mean_r = sum(ratios) / len(ratios)
        spread = max(abs(r - mean_r) for r in ratios) / mean_r if mean_r else 1.0
        if spread < 0.10:
            return [{
                "severity": "🟡",
                "location": "数值自洽",
                "issue": f"Ea_bulk={ea1} eV 与 Ea_gb={ea2} eV 不同，但 σ_gb/σ_bulk 比例在 "
                         f"{len(ratios)} 个温度点恒为 ≈{mean_r:.2f}",
                "suggestion": "活化能不同则 σ_gb/σ_bulk 比例必随温度变化（σ∝exp(-Ea/kT)）；检查比例是否由同一 Arrhenius 模型推导",
            }]
    return []


#: 百分比换算：μV·h⁻¹ 衰减率 × 时长 与 声称的相对百分比（容忍 "12 ± 4 μV·h⁻¹" 误差棒）
_DECAY_RATE_RE = re.compile(r"(\d+(?:\.\d+)?)(?:\s*±\s*\d+(?:\.\d+)?)?\s*[μµu]V[·\.]?h⁻¹")


def _percent_calc_issues(draft: str) -> List[Dict[str, str]]:
    m_ocv = re.search(r"OCV\s*[=≈]\s*(\d+\.\d+)", draft)
    if not m_ocv:
        return []
    ocv = float(m_ocv.group(1))
    # 遍历所有衰减率匹配，找窗口内带百分比表述的那一处
    for m in _DECAY_RATE_RE.finditer(draft):
        rate = float(m.group(1))
        win = draft[max(0, m.start() - 250):m.end() + 250]
        m_pct = re.search(r"约\s*(\d+(?:\.\d+)?)\s*%|≈\s*(\d+(?:\.\d+)?)\s*%", win)
        if not m_pct:
            continue
        m_h = re.search(r"(\d+)\s*h", win)
        hours = float(m_h.group(1)) if m_h else 100.0
        pct = float(next(g for g in m_pct.groups() if g))
        expected = rate * hours / (ocv * 1e6) * 100.0  # μV→V 差 1e6
        if expected <= 0:
            continue
        if abs(pct - expected) / expected > 0.5:
            return [{
                "severity": "🟡",
                "location": "数值自洽",
                "issue": f"衰减率换算与表述不符：{rate:g} μV·h⁻¹×{hours:g} h={rate * hours / 1000:g} mV≈"
                         f"{expected:.3f}%（OCV {ocv:g} V），但正文称约 {pct:g}%",
                "suggestion": "核对衰减率×时长/基准电压的百分比换算；若基准非 OCV 请明确说明分母",
            }]
    return []


#: 对照样全维度：对照路线出现但缺 σ/ASR/OCV/PPD/t_ion 数值
_CONTROL_SAMPLE_RE = re.compile(r"GDC-0\.10Co|CG-1|GDC-0\.10-C|双层|bilayer|商业粉体|undoped|Co\s?助剂|Ca\s?共掺")
_PERF_VALUE_RE = re.compile(
    r"σ[_\s]*(?:e|ion|gb|total|bulk)?\s*[=≈]\s*\d|OCV\s*[=≈]?\s*\d|PPD\s*[=≈]?\s*\d|"
    r"ASR\s*[=≈]?\s*\d|t[_\s]*ion\s*[=≈]?\s*\d|\d+(?:\.\d+)?\s*[×x]\s*10[⁻\-]",
)


def _control_completeness_issues(draft: str) -> List[Dict[str, str]]:
    labels: Dict[str, bool] = {}  # label -> has performance value in same sentence/row
    # 按句/行切分：对照样只有在"同一句/同一表格行"内出现 σ/OCV/PPD 数值才算有数据
    for unit in re.split(r"[。；;\n]", draft):
        for m in _CONTROL_SAMPLE_RE.finditer(unit):
            raw = m.group(0)
            labels.setdefault(raw, False)
            if _PERF_VALUE_RE.search(unit):
                labels[raw] = True
    incomplete = sorted(k for k, v in labels.items() if not v)
    if incomplete:
        return [{
            "severity": "🟡",
            "location": "对照",
            "issue": f"对照路线（{', '.join(incomplete[:3])}）在文中出现，但同句/同表格行缺少电导/电池性能数值（σ/ASR/OCV/PPD/t_ion）",
            "suggestion": "对照样补齐同维度性能数据；确实未测的项明确标注「待补」，否则对比判断不成立",
        }]
    return []


#: 统计力：n=2/3 与性能指标同现
_LOW_N_RE = re.compile(r"n\s*=\s*[23]\b")
_PERF_CTX_RE = re.compile(r"PPD|OCV|衰减率|功率密度|峰值功率")


def _sample_size_issues(draft: str) -> List[Dict[str, str]]:
    hits = 0
    for m in _LOW_N_RE.finditer(draft):
        win = draft[max(0, m.start() - 150):m.end() + 150]
        if _PERF_CTX_RE.search(win):
            hits += 1
    if hits:
        return [{
            "severity": "🟡",
            "location": "数据",
            "issue": f"性能指标（OCV/PPD/衰减率）与 n=2–3 小样本同现（{hits} 处），样本量偏低",
            "suggestion": "建议 n≥5 重复实验，或标注置信区间与电芯间离散来源",
        }]
    return []


# ── 第三轮：厚度-ASR 换算 / 理论密度共用 / 图件缺失 / 跨表电阻未分解 ──

_SUP_MAP = {'⁰': '0', '¹': '1', '²': '2', '³': '3', '⁴': '4',
            '⁵': '5', '⁶': '6', '⁷': '7', '⁸': '8', '⁹': '9', '⁻': '-'}


def _parse_scientific(text: str):
    """解析 '1.99×10⁻²' / '1.99×10^-2' / '1.99e-2' → float。失败返回 None。"""
    m = re.search(r"(\d+\.\d+)\s*[×x]\s*10\s*([⁻⁰¹²³⁴⁵⁶⁷⁸⁹]+)", text)
    if m:
        mant = float(m.group(1))
        exp = int(''.join(_SUP_MAP.get(c, '') for c in m.group(2)))
        return mant * (10 ** exp)
    m = re.search(r"(\d+\.\d+)\s*[×x]\s*10\^?\s*(-?\d+)", text)
    if m:
        return float(m.group(1)) * (10 ** int(m.group(2)))
    return None


def _thickness_asr_issues(draft: str) -> List[Dict[str, str]]:
    """厚度-ASR 数量级复核：ASR_expected = L/σ；与文档报告 ASR 差 >10× → 🔴。

    按位置邻近配对：每个 ASR 数值找最近的 L 表述（±400 字），
    避免把单电池薄电解质 ASR 与对称电池厚片 L 错配。
    """
    # 1) σ_total 数值
    sigmas: List[float] = []
    for m in re.finditer(r"σ_total", draft):
        v = _parse_scientific(draft[m.end():m.end() + 40])
        if v is not None and 1e-5 < v < 1:
            sigmas.append(v)
    if not sigmas:
        return []
    sigma = max(sigmas)

    # 2) ASR 数值 + 位置
    asr_hits: List[tuple] = []  # (pos, value)
    for m in re.finditer(r"ASR", draft):
        after = draft[m.end():m.end() + 60]
        dm = re.search(r"(\d+\.\d+)\s*(?:Ω[·.]?cm²|Ω cm²)?", after)
        if dm:
            v = float(dm.group(1))
            if 1e-3 < v < 10:
                asr_hits.append((m.start(), v))
    if not asr_hits:
        return []

    # 3) L 表述 + 位置（cm）
    L_hits: List[tuple] = []
    L_units_seen: set = set()
    for lm in re.finditer(r"(?:厚度|L)\s*[=＝为约]?\s*(\d+(?:\.\d+)?)\s*(mm|μm|µm|um|cm)", draft):
        L_val = float(lm.group(1))
        L_unit = lm.group(2)
        L_cm = L_val / 10.0 if L_unit == "mm" else (L_val / 10000.0 if L_unit in ("μm", "µm", "um") else L_val)
        if L_cm > 0:
            L_hits.append((lm.start(), L_cm))
            # 单位族：mm 一组，μm/um/cm 另一组（区分厚片 vs 薄膜基准）
            L_units_seen.add("mm" if L_unit == "mm" else "thin")
    if not L_hits:
        return []

    # 3b) 多基准豁免：若正文同时出现厚片（mm）与薄膜（μm/cm）两套厚度基准，
    # 且已给出折算/换算/对应说明，则不再按单一 L 报 🔴。
    multi_baseline = len(L_units_seen) >= 2
    has_conversion_note = bool(re.search(
        r"折算|换算|对应|折算为|折算到|按.{0,8}厚度|对称电池.{0,30}单电池|单电池.{0,30}对称电池",
        draft,
    ))

    # 4) 邻近配对：每个 ASR 找最近 L
    worst_ratio = 1.0
    worst_L = 0.0
    worst_expected = 0.0
    worst_asr = 0.0
    for a_pos, asr_v in asr_hits:
        nearest = min(L_hits, key=lambda L: abs(L[0] - a_pos))
        if abs(nearest[0] - a_pos) > 400:
            continue
        L_cm = nearest[1]
        expected = L_cm / sigma
        if expected <= 0:
            continue
        ratio = asr_v / expected
        if ratio < 1:
            ratio = 1.0 / ratio
        if ratio > worst_ratio:
            worst_ratio = ratio
            worst_L = L_cm
            worst_expected = expected
            worst_asr = asr_v
    if worst_ratio > 10:
        if multi_baseline and has_conversion_note:
            # 两套厚度基准 + 折算说明已交代，豁免
            return []
        if multi_baseline and not has_conversion_note:
            return [{
                "severity": "🔴",
                "location": "数值自洽",
                "issue": f"厚度/ASR 换算矛盾：σ_total ≈ {sigma:.2e} S/cm 与 ASR ≈ {worst_asr:.3f} Ω·cm² "
                         f"在邻近厚度基准 L ≈ {worst_L:.4f} cm 下应得 ASR = L/σ ≈ {worst_expected:.4f} Ω·cm²，"
                         f"与报告值差约 {worst_ratio:.0f} 倍",
                "suggestion": "正文已出现两套厚度基准（对称电池厚片 mm 与单电池薄膜 μm），但未说明二者间的折算关系；请明确各 ASR 对应的厚度基准并给出折算说明",
            }]
        return [{
            "severity": "🔴",
            "location": "数值自洽",
            "issue": f"厚度/ASR 换算矛盾：σ_total ≈ {sigma:.2e} S/cm 与 ASR ≈ {worst_asr:.3f} Ω·cm² "
                     f"在邻近厚度基准 L ≈ {worst_L:.4f} cm 下应得 ASR = L/σ ≈ {worst_expected:.4f} Ω·cm²，"
                     f"与报告值差约 {worst_ratio:.0f} 倍",
            "suggestion": "统一厚度基准（对称电池 ~1 mm 与单电池 ~μm 级厚度不同）；按 ASR = L/σ 复核换算，注意 L 单位（mm→cm ÷10，μm→cm ÷10⁴）",
        }]
    return []


def _theoretical_density_issues(draft: str) -> List[Dict[str, str]]:
    """理论密度共用主线 M/a：多样品相对密度表却只给一组 M 和 a。"""
    m_vals = set(re.findall(r"M\s*[=＝]\s*(\d+\.\d+)\s*g·mol⁻¹", draft))
    a_vals = set(re.findall(r"a\s*[=＝]\s*(\d+\.\d+)\s*Å", draft))
    if len(m_vals) == 1 and len(a_vals) == 1:
        # 统计表格中含两位小数密度数值的样品行数（排除表头）
        rel_density_rows = sum(
            1 for line in draft.splitlines()
            if "|" in line and "相对密度" not in line and re.search(r"\d+\.\d+", line)
        )
        if rel_density_rows >= 3:
            return [{
                "severity": "🟡",
                "location": "数据",
                "issue": f"相对密度计算共用单一 M = {next(iter(m_vals))} g·mol⁻¹ 与 a = {next(iter(a_vals))} Å（主线样品），"
                         f"但表中含 {rel_density_rows} 行样品数据",
                "suggestion": "逐样品用实测组成（不同 x/y）与各自 Rietveld 精修 a 计算理论密度；Ca 共掺/1400 °C/Co 助烧组的 M 与 a 与主线不同",
            }]
    return []


def _figure_missing_issues(draft: str) -> List[Dict[str, str]]:
    """图件检查。

    两种失效模式（2026-10-14 v6 实测发现第二种）：
    1. 正文有 Fig N / 图 N 引用，但无实际图片 / Schematic 标注 / 待实验获取 标注；
    2. **全文完全没有图注段**——模型把该画图的数据全改写成表格，
       导致导出时`export_docx` 找不到图注行→ 成稿丢图（v5 有 2 图，v6 有 0 图）。
    """
    # 模式 2：研究论文（篇幅足够）却一个图注行都没有 —— 直接判丢图
    # 判据用「图注行」而非任意「图 N」字样：正文里"见表 7""如图 3 所示"这类
    # 交叉引用不代表规划了图（v6 实测：图 N 引用 12 处，图注行 0 处 → 丢图）。
    table_count = len(re.findall(r"表\s*\d+|Table\s*\d+", draft, re.IGNORECASE))
    fig_refs = re.findall(r"Fig(?:ure)?\s*\d+|图\s*\d+", draft)
    caption_lines = re.findall(r"\*\*图\s*\d+\*\*", draft)
    if not caption_lines and table_count >= 3 and len(draft) > 3000:
        return [{
            "severity": "🟡",
            "location": "图件",
            "issue": f"全文 {table_count} 处表格引用但零图注（无 `**图 N**` 独立行），导出后将丢失全部示意图",
            "suggestion": "补图注：至少 2 张示意图（电池结构 / 机制，标「Schematic」）与数据图（XRD/EIS/SEM，无实测数据时标「数据待实验获取」）；表格承载数值、图注承载结构与数据图，不可把图改写成表",
        }]

    if not fig_refs:
        return []
    has_image = bool(re.search(r"!\[[^\]]*\]\([^)]+\)", draft))
    has_schematic = bool(re.search(r"Schematic|示意|待实验获取|待获取", draft))
    if not has_image and not has_schematic:
        return [{
            "severity": "🟡",
            "location": "图件",
            "issue": f"正文引用了 {len(fig_refs)} 处图号（{fig_refs[0]} 等），但全文无图片文件、无 Schematic 标注、无「待实验获取」标注",
            "suggestion": "示意图需在图注中标注「Schematic」；数据图需标注「待实验获取」或实际插图；否则图注为空号",
        }]
    return []


def _cross_table_resistance_issues(draft: str) -> List[Dict[str, str]]:
    """跨表电阻未分解：对称电池 ASR 与单电池 ASR 并存，但未给出 R_Ω/R_p 分解。"""
    has_symmetric = bool(re.search(r"对称电池\s*ASR|R_b|R_gb", draft))
    has_cell = bool(re.search(r"单电池.*ASR|电池\s*[A-E].*ASR|ASR\s*/\s*Ω·cm²", draft))
    if not (has_symmetric and has_cell):
        return []
    decomposed = bool(re.search(r"R_Ω|RΩ|欧姆电阻|极化电阻|分解", draft))
    if not decomposed:
        return [{
            "severity": "🟡",
            "location": "数值自洽",
            "issue": "对称电池 ASR（R_b/R_gb）与单电池 ASR 同时出现，但未给出 R_Ω（欧姆）与 R_p（极化）的分解与跨表厚度折算",
            "suggestion": "在 EIS 表注中给出 R_Ω 与 R_p 分解，并说明单电池厚度与对称电池厚度不同导致的 ASR 折算关系",
        }]
    return []


def check_quality(draft: str, refs: Optional[List[Any]] = None) -> Dict[str, Any]:
    """三维巡检。返回 {ok, score, issues: [...], summary}。"""
    from matlens_kit.paper.enforce_refs import check_refs_whitelist

    issues: List[Dict[str, str]] = []
    refs = refs or []
    ref_count = len(refs)

    # ── 1. 引用核验（引用越界）—— 统一委托 enforce_refs 单一事实源 ──
    # 只标警告写进报告，绝不抛异常（quality 步本身返回 report 文本）
    issues.extend(check_refs_whitelist(draft, refs))

    # ── 2. 结构检查 ──
    text_len = len(draft)
    lower = draft.lower()
    has_sections = [s for s in _RESEARCH_SECTIONS if f"# {s}" in draft or s in draft[:200]]
    if text_len > 0:
        for sec in _RESEARCH_SECTIONS:
            if sec not in draft:
                issues.append({
                    "severity": "🟡",
                    "location": "结构",
                    "issue": f"缺少关键章节「{sec}」",
                    "suggestion": f"补充「{sec}」章节（研究论文五段式完整性）",
                })
    if text_len < 1500:
        issues.append({
            "severity": "🟡",
            "location": "篇幅",
            "issue": f"全文仅 {text_len} 字，篇幅偏短",
            "suggestion": "研究论文建议 3000 字以上，补充方法细节与讨论",
        })
    elif text_len < 800:
        issues.append({
            "severity": "🔴",
            "location": "篇幅",
            "issue": f"全文仅 {text_len} 字，严重不足",
            "suggestion": "按大纲逐节展开写作",
        })

    # ── 3. AI 味启发式 ──
    for phrase in _MECHANICAL_PHRASES:
        hits = re.findall(phrase, draft)
        if hits:
            issues.append({
                "severity": "🟡",
                "location": "AI 味",
                "issue": f"机械连接词「{hits[0]}」出现 {len(hits)} 次",
                "suggestion": "改为自然过渡或直接衔接，避免模板化连接",
            })
    for phrase in _EMPTY_PHRASES:
        hits = re.findall(phrase, draft)
        if hits:
            issues.append({
                "severity": "🟢",
                "location": "空话",
                "issue": f"空话套话「{hits[0]}」",
                "suggestion": "替换为具体事实或数据支撑",
            })
    # 句式重复：相邻两句同首字
    sents = _split_sentences(draft)
    if len(sents) >= 4:
        starts = [s.strip()[:4] for s in sents]
        dup = 0
        for i in range(1, len(starts)):
            if starts[i] == starts[i - 1] and len(starts[i]) >= 2:
                dup += 1
        if dup >= 2:
            issues.append({
                "severity": "🟢",
                "location": "句式",
                "issue": f"相邻 {dup + 1} 句以相同短语开头（句式重复）",
                "suggestion": "变换句首结构，增加句式多样性",
            })

    # ── 4. 学术评审级维度（本地规则、不调 LLM）──
    issues.extend(_data_integrity_issues(draft))
    issues.extend(_numerical_self_consistency_issues(draft))
    issues.extend(_claim_evidence_issues(draft))
    issues.extend(_control_experiment_issues(draft))
    issues.extend(_literature_comparison_issues(draft))
    issues.extend(_stability_issues(draft))

    # ── 5. 第二轮：化学常识 / 比例-活化能 / 百分比换算 / 对照完整性 / 统计力 ──
    issues.extend(_chem_fact_issues(draft))
    issues.extend(_ratio_ea_consistency_issues(draft))
    issues.extend(_percent_calc_issues(draft))
    issues.extend(_control_completeness_issues(draft))
    issues.extend(_sample_size_issues(draft))
    issues.extend(_thickness_asr_issues(draft))
    issues.extend(_theoretical_density_issues(draft))
    issues.extend(_figure_missing_issues(draft))
    issues.extend(_cross_table_resistance_issues(draft))

    # 评分：100 - 严重度加权
    score = 100
    for it in issues:
        score -= {"🔴": 10, "🟡": 5, "🟢": 2}.get(it["severity"], 3)
    score = max(0, min(100, score))
    red = sum(1 for i in issues if i["severity"] == "🔴")
    yellow = sum(1 for i in issues if i["severity"] == "🟡")

    covered = "引用越界/结构/篇幅/AI味/空话/句式/数据/数值自洽/声称/对照/文献对比/稳定性/化学事实/图件"
    summary = (
        f"巡检完成：发现 {len(issues)} 项问题（🔴{red} · 🟡{yellow} · 🟢{len(issues) - red - yellow}），"
        f"质量评分 {score}/100。覆盖维度：{covered}。"
    )
    return {"ok": True, "score": score, "issues": issues, "summary": summary, "ref_count": ref_count}


def render_report(check: Dict[str, Any]) -> str:
    """巡检结果渲染为 Markdown（落库 content）。"""
    lines = ["## 质量巡检报告", "", check.get("summary", ""), ""]
    issues = check.get("issues", [])
    if not issues:
        lines.append("✅ 未发现明显问题，质量良好。")
    else:
        lines.append("### 问题清单")
        lines.append("")
        for i, it in enumerate(issues, 1):
            lines.append(f"{i}. **{it['severity']} {it['location']}**：{it['issue']}")
            lines.append(f"   - 建议：{it['suggestion']}")
    lines.append("")
    lines.append(f"**质量评分：{check.get('score', 0)} / 100**")
    return "\n".join(lines)
