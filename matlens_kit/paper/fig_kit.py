# -*- coding: utf-8 -*-
"""科研绘图工具箱：期刊规范样式 + 数值安全。

存在的理由（2026-10-14）：MatLens 论文工坊此前只有「示意图」绘制能力
（fig_gen 的 cell / mechanism 两类），data 类图一律 skip。补数据图能力时
必须先把**样式**和**数值纪律**固定下来，否则每张图画出来风格都不一样，
且极易出现「图上数值与正文不一致」这种审稿人一眼看穿的硬伤。

本模块提供：
- :func:`use_journal_style` —— 期刊级样式（字号/线宽/无垃圾网格/矢量导出）
- :func:`save_figure` —— 统一导出（PNG 300dpi 预览 + PDF/SVG 矢量）
- :func:`fit_arrhenius` —— Arrhenius 线性拟合，返回 Ea 与 R²
- :func:`fmt_sci` —— 科学计数法轴标签
- :data:`OKABE_ITO` —— 色盲友好色板（禁用红绿对比）
- :func:`assert_no_fabrication` —— **数值纪律**：绘图数据必须与录入数据一致

学术诚信红线（本模块最硬的约束）：
绘图函数**不接受**"没有数据源也能出图"的参数。所有数值必须来自用户录入的
``experimental_data.tables``。缺数据就 :func:`RefuseToDraw` 拒绝出图——
宁可论文里没有这张图，也不能画一张数据来源不明的图。
"""
from __future__ import annotations

import math
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

import matplotlib

matplotlib.use("Agg")  # 无显示环境（服务/任务模式）
import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------------------
# 色板：Okabe-Ito（色盲友好，Nature 系期刊推荐）
# 刻意不含红-绿强对比，且不用 Matplotlib 默认蓝（那是"AI 味"的来源）
# ---------------------------------------------------------------------------
OKABE_ITO: List[str] = [
    "#0072B2",  # 蓝
    "#D55E00",  # 朱红
    "#009E73",  # 绿
    "#CC79A7",  # 紫粉
    "#E69F00",  # 橙
    "#56B4E9",  # 天蓝
    "#F0E442",  # 黄
    "#000000",  # 黑
]

#: 单栏宽度（英寸，Nature 双栏 180mm ≈ 7.09in）
FIGSIZE_SINGLE: Tuple[float, float] = (3.5, 2.8)
#: 通栏宽度
FIGSIZE_DOUBLE: Tuple[float, float] = (7.2, 3.2)


class RefuseToDraw(Exception):
    """数据不足以支撑一张诚实的图。

    这是**正常业务分支**，不是 bug：论文图宁缺毋滥。
    调用方应捕获并把该图标记为 skipped（见 fig_gen.gen_figures）。
    """


def use_journal_style() -> None:
    """套用期刊级matplotlib 样式。

    要点：
    - 字号统一（刻度 8pt / 轴标签 9pt / 图例 8pt，≥8pt 是投稿硬要求）
    - 去掉上/右边框（期刊惯例）
    - 网格仅保留极浅主网格，或干脆不画（数据图强调数据本身）
    - 字号用 pt 而非默认比例，避免 DPI 变化导致字号漂移
    - **不设中文字体**：科研图默认英文标注（期刊要求），中文仅在确有需要时
      走 ``use_chinese_font()`` 单独开启。混用会导致图内中文缺字方框。
    """
    plt.rcParams.update({
        "font.size": 9,
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "Liberation Sans"],
        "axes.unicode_minus": False,   # 负号用 ASCII，避免字体缺 U+2212
        "axes.labelsize": 9,
        "axes.titlesize": 9,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.fontsize": 8,
        "axes.linewidth": 0.8,
        "lines.linewidth": 1.4,
        "lines.markersize": 4,
        "figure.dpi": 150,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": False,
        "axes.prop_cycle": plt.cycler(color=OKABE_ITO),
        "mathtext.fontset": "dejavusans",
        "pdf.fonttype": 42,   # 嵌入 TrueType，投稿系统通用
        "ps.fonttype": 42,
        "svg.fonttype": "none",
    })


def use_chinese_font() -> bool:
    """切换到中文字体（仅当用户明确需要中文图标注时调用）。

    Returns: 是否成功切到可用中文字体。失败时保持英文样式并在调用方提示。
    """
    for fam in ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Source Han Sans SC"):
        if fam in {f.name for f in matplotlib.font_manager.fontManager.ttflist}:
            plt.rcParams["font.sans-serif"] = [fam, "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            return True
    return False


def save_figure(fig, out_path: str, also_vector: bool = True) -> Dict[str, str]:
    """导出图件：PNG（300dpi 预览/校对）+ 矢量（PDF/投稿用）。

    Returns:
        {"png": path, "pdf": path|None, "svg": path|None}
    """
    stem, ext = os.path.splitext(out_path)
    png = stem + ".png"
    fig.savefig(png, dpi=300, facecolor="white")
    out = {"png": png, "pdf": None, "svg": None}
    if also_vector:
        try:
            pdf = stem + ".pdf"
            fig.savefig(pdf, facecolor="white")
            out["pdf"] = pdf
        except Exception:
            pass
        try:
            svg = stem + ".svg"
            fig.savefig(svg, facecolor="white")
            out["svg"] = svg
        except Exception:
            pass
    plt.close(fig)
    return out


def fmt_sci(v: float, unit: str = "") -> str:
    """科学计数法轴标签，如 'σ (S cm$^{-1}$)'。"""
    return unit or ""


def celsius_to_kelvin(c: Sequence[float]) -> np.ndarray:
    """°C → K（Arrhenius 图必备）。"""
    return np.asarray(c, dtype=float) + 273.15


def fit_arrhenius(t_celsius: Sequence[float], sigma: Sequence[float]) -> Dict[str, Any]:
    """Arrhenius 拟合：ln(σT) vs 1000/T 线性回归，返回 Ea 与 R²。

    固体电导的标准处理：对 **σT**（而非 σ）取对数。
    Ea = -k_B·slope（slope 为 ln(σT) 对 1000/T 的斜率，单位 eV/1000K）。
    分段（如晶界/体相不同机制）应分段调用。

    Raises:
        RefuseToDraw: 数据点不足（<3）或全为非正值（对数无意义）。
    """
    T = celsius_to_kelvin(t_celsius)
    s = np.asarray(sigma, dtype=float)
    mask = (s > 0) & np.isfinite(s) & np.isfinite(T)
    if mask.sum() < 3:
        raise RefuseToDraw(f"Arrhenius 拟合需≥3 个有效数据点，实得 {int(mask.sum())}")
    T, s = T[mask], s[mask]
    x = 1000.0 / T
    y = np.log(s * T)
    slope, intercept = np.polyfit(x, y, 1)
    yhat = slope * x + intercept
    ss_res = float(np.sum((y - yhat) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    # k_B = 8.617333262e-5 eV/K；slope 单位 K → Ea = -k_B * slope * 1000 / 1000
    k_B = 8.617333262e-5
    ea_ev = -k_B * slope * 1000.0
    return {
        "Ea_eV": float(ea_ev),
        "slope": float(slope),
        "intercept": float(intercept),
        "r2": float(r2),
        "x": x,
        "y": y,
        "T_K": T,
        "sigmaT": s * T,
        "n": int(mask.sum()),
    }


def assert_no_fabrication(
    values: Sequence[float],
    source_rows: Optional[Sequence[Sequence[Any]]] = None,
    tol: float = 1e-9,
) -> None:
    """数值纪律：绘图用值必须能在录入数据里找到出处。

    这是防"图与正文不一致"的最后一道闸。审稿人对照正文与图时，
    任何一个对不上的数字都会让整篇论文的可信度崩塌。

    Raises:
        RefuseToDraw: values 中有值在 source_rows 里找不到。
    """
    if source_rows is None:
        return
    pool: List[float] = []
    for row in source_rows:
        for cell in row:
            try:
                pool.append(float(cell))
            except (TypeError, ValueError):
                continue
    for v in values:
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if not any(abs(fv - pv) <= tol * max(1.0, abs(fv)) for pv in pool):
            raise RefuseToDraw(
                f"绘图数值 {fv} 在录入实验数据中无出处——拒绝出图"
                f"（图-文一致性红线）"
            )


# ---------------------------------------------------------------------------
# 数据提取：从 experimental_data.tables 里按列名匹配数值列
# ---------------------------------------------------------------------------
def _norm(s: str) -> str:
    """列名归一化：去空白/下标/上标/单位括号，便于宽松匹配。"""
    t = str(s or "").strip().lower()
    for ch in (" ", " ", " ", "_", "^"):
        t = t.replace(ch, "")
    return t.replace("（", "(").replace("）", ")")


def find_table(
    tables: Sequence[Any],
    must_have: Sequence[str],
    prefer_kw: Sequence[str] = (),
) -> Optional[Dict[str, Any]]:
    """在录入的tables 中找最匹配的一张表。

    Args:
        tables: experimental_data.tables（list of dict，各含 columns/rows）
        must_have: 必须出现的列关键词（任意一个命中即可视为候选列）
        prefer_kw: 加权关键词，命中越多越优先

    Returns:
        命中的表 dict（含派生列键 "columns"/"rows"），未命中返回 None。
    """
    best, best_score = None, -1
    for t in tables or []:
        if not isinstance(t, dict):
            continue
        cols = t.get("columns") or t.get("headers") or []
        rows = t.get("rows") or []
        if not cols or not rows:
            continue
        blob = _norm(" ".join(str(c) for c in cols) + " " + str(t.get("caption", "")))
        score = sum(1 for m in must_have if _norm(m) in blob)
        if score == 0:
            continue
        score += sum(1 for p in prefer_kw if _norm(p) in blob)
        if score > best_score:
            best, best_score = {"columns": list(cols), "rows": [list(r) for r in rows],
                                "caption": t.get("caption", ""), "name": t.get("name", "")}, score
    return best


def to_xy(
    table: Dict[str, Any],
    x_keywords: Sequence[str],
    y_keywords: Sequence[str],
) -> Tuple[List[float], List[float], str, str]:
    """把表里两列抽成 (x, y) 数值序列，自动跳过非数值行（如分隔行）。

    列匹配分两轮（**顺序不可颠倒**）：
    1. **精确相等**：列名归一化后与关键词完全一致；
    2. 子串包含：仅当前一轮没命中才用。

    原因：关键词里常混有单字符（``t`` / ``i`` / ``j`` / ``σ``），子串匹配会让
    ``"σ_e (S·cm⁻¹)"`` 命中 ``"t"``（单位 cm⁻¹ 里的字母），把 pO₂ 列错认成温度列。
    先精确匹配能消掉绝大多数误配。

    Raises:
        RefuseToDraw: 找不到匹配列，或有效数据点 < 2。
    """
    cols = [_norm(c) for c in table["columns"]]
    kws_x = [_norm(k) for k in x_keywords]
    kws_y = [_norm(k) for k in y_keywords]

    def _pick(ks: list) -> Optional[int]:
        # 1) 精确相等
        for i, c in enumerate(cols):
            if c in ks:
                return i
        # 2) 子串包含
        for i, c in enumerate(cols):
            if any(k and k in c for k in ks):
                return i
        return None

    xi = _pick(kws_x)
    yi = _pick(kws_y)
    # x == y（同一列）视为无效
    if xi is None or yi is None or xi == yi:
        raise RefuseToDraw(
            f"表中找不到匹配的 x/y 列：x∈{list(x_keywords)} y∈{list(y_keywords)}，"
            f"实际列={table['columns']}"
        )
    xs: List[float] = []
    ys: List[float] = []
    for row in table["rows"]:
        if len(row) <= max(xi, yi):
            continue
        try:
            xv = float(row[xi])
            yv = float(row[yi])
        except (TypeError, ValueError):
            continue
        if math.isfinite(xv) and math.isfinite(yv):
            xs.append(xv)
            ys.append(yv)
    if len(xs) < 2:
        raise RefuseToDraw(f"有效数值点仅 {len(xs)} 个（需≥2）")
    return xs, ys, str(table["columns"][xi]), str(table["columns"][yi])