# -*- coding: utf-8 -*-
"""数据图谱系：从录入的实验数据自动识别图型并绘制（第一级能力）。

设计原则（承接 :mod:`fig_kit`）：
- **唯一数据源**是 ``experimental_data.tables``。没有数据 → :class:`RefuseToDraw`，
  该图标记 skipped，绝不凭空画。
- 每个谱系对应一个真实科研图型，不是"折线图"泛化：σ–T、Arrhenius、
  密度–收缩率、EIS Nyquist、I–V/I–P、恒流稳定性、σ_e–pO₂。
- 图注里的量纲/条件从表名与表注继承，不臆造。

图型与判据（按优先级匹配，顺序即特异性）：

===================  ==========================================
谱系                识别依据
===================  ==========================================
``arrhenius``        含 Arrhenius / Ea / 1000/T / σT
``sigma_t``          电导率随温度（σ vs T），多组分对照
``density_shrink``   收缩率 / 相对密度 vs 烧结温度
``iv_ip``            I–V / I–P / 功率密度 / OCV
``stability``        恒流 / 稳定性 / 衰减 / h
``po2_sigmae``       σ_e–pO₂ / Hebb-Wagner / 电子电导
``xrd``              XRD / 衍射全谱 / 峰位
===================  ==========================================
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

import matplotlib.pyplot as plt
import numpy as np

from matlens_kit.paper.fig_kit import (
    FIGSIZE_DOUBLE,
    FIGSIZE_SINGLE,
    OKABE_ITO,
    RefuseToDraw,
    assert_no_fabrication,
    celsius_to_kelvin,
    find_table,
    fit_arrhenius,
    save_figure,
    to_xy,
    use_journal_style,
)

__all__ = ["detect_scheme", "draw_scheme", "SCHEMES"]

# ---------------------------------------------------------------------------
# 谱系识别
# ---------------------------------------------------------------------------
#: (谱系名, 判别关键词, 更加权关键词, 数据表查找关键词)
_SCHEME_SPECS: List[Tuple[str, Sequence[str], Sequence[str], Sequence[str]]] = [
    ("arrhenius",
     ("arrhenius", "ea", "1000/t", "激活能", "σt", "sigma-t"),
     ("drt", "晶界", "体相"),
     ("温度", "t", "电导", "σ", "conductivity")),
    ("sigma_t",
     ("电导率随温度", "sigma-t", "σ-t", "conductivity vs temperature",
      "σ 与温度", "电导率–温度", "温度依赖", "不同温度下电导"),
     ("空气", "n2", "h2", "不同温度", "temperature", "对照"),
     ("温度", "电导", "t", "σ")),
    ("density_shrink",
     ("收缩率", "相对密度", "shrinkage", "relative density", "densification"),
     ("烧结温度", "sintering", "致密化"),
     ("温度", "收缩", "密度", "shrinkage", "density")),
    ("iv_ip",
     ("i-v", "i–v", "i-p", "i–p", "功率密度", "power density", "iv曲线", "ip曲线"),
     ("ocv", "放电", "电池", "cell"),
     ("电压", "电流", "功率", "ocv", "voltage", "current", "power")),
    ("stability",
     ("恒流", "稳定性", "衰减", "stability", "degradation", "耐久", "100 h", "1000 h"),
     ("时间", "time", "电压", "voltage"),
     ("时间", "电压", "电流密度", "time", "voltage", "current")),
    ("po2_sigmae",
     ("pO₂", "po2", "hebb-wagner", "电子电导", "σe", "sigma_e", "sigmae"),
     ("氧分压", "oxygen partial"),
     ("pO₂", "po2", "σe", "电子电导", "voltage")),
    ("eis",
     ("nyquist", "eis", "电化学阻抗", "阻抗谱", "bode", " EIS "),
     ("hebb-wagner", "拟合", "等效电路", "relaxation", "弛豫"),
     ("z'", "zre", "实部", "虚部", "f", "freq", "频率")),
    ("xrd",
     ("xrd", "衍射", "全谱", "物相", "晶格常数", "rietveld"),
     ("(111)", "峰位", "相"),
     ("2θ", "2theta", "强度", "intensity")),
]


def detect_scheme(desc: str) -> Optional[str]:
    """从图注文字识别谱系。识别不出返回 None（→ 保持 skipped）。

    注意与 :func:`matlens_kit.paper.fig_gen._classify_caption` 的分工：
    那边只分cell / mechanism / data / unknown 四类用于决定"要不要画"；
    这里在 data 类内部再细分"画哪种图"。
    """
    t = str(desc or "").lower()
    if not t.strip():
        return None
    best, best_score = None, 0
    for name, kws, weights, _ in _SCHEME_SPECS:
        score = sum(2 for k in kws if k.lower() in t)
        score += sum(1 for w in weights if w.lower() in t)
        if score > best_score:
            best, best_score = name, score
    # 阈值 2：单个泛词（如"曲线"）不足以定谱系
    return best if best_score >= 2 else None


def _pick_table_for(tables: Sequence[Any], scheme: str) -> Dict[str, Any]:
    """按谱系在录入数据里选表。"""
    spec = next((s for s in _SCHEME_SPECS if s[0] == scheme), None)
    if spec is None:
        raise RefuseToDraw(f"未知谱系：{scheme}")
    table = find_table(tables, spec[3], spec[2])
    if table is None:
        raise RefuseToDraw(
            f"谱系 '{scheme}' 需要匹配 {list(spec[3])} 的数据表，录入数据中未找到"
        )
    return table


# ---------------------------------------------------------------------------
# 各谱系绘图器：签名统一 (table, out_path) -> dict
# ---------------------------------------------------------------------------
def _multi_series_sigma(
    tables: Sequence[Any], x_col_hint: str = "温度"
) -> List[Tuple[str, List[float], List[float]]]:
    """多组分对照的 σ–T：把所有「某组分 / 某气氛」表都取出来。

    **必须按 x 列的数值范围筛选**（2026-10-14 实测踩坑）：
    σ_e–pO₂ 表的 pO₂ 列同样是纯数字（1e-25 ~ 1e-18），若只看"存在数字列"
    就会被误当成温度列拉进 Arrhenius 图，凭空多出一条 Ea=0.00 eV 的假曲线。
    这里用物理区间约束：温度列须落在 [-50, 2000] °C，且**随行单调递增**
    （σ_e–pO₂ 的 pO₂ 通常随行递减或跨数量级，不满足单调性）。
    """
    out: List[Tuple[str, List[float], List[float]]] = []
    for t in tables or []:
        if not isinstance(t, dict):
            continue
        cols = t.get("columns") or []
        rows = t.get("rows") or []
        if not cols or not rows:
            continue
        label = str(t.get("name") or t.get("caption") or "series")
        try:
            x, y, xname, _ = to_xy({"columns": cols, "rows": rows},
                                   [x_col_hint, "温度", "temperature", "temp"],
                                   ["σ (s·cm⁻¹)", "σ (s/cm)", "电导", "conductivity", "sigma"])
        except RefuseToDraw:
            continue
        # ── 四重物理约束（缺一不可，见模块说明）─────────────────
        # 1) 跨度合理性：温度类 x 跨度应在 1~2500 °C（实验温区至少几十度）。
        #    pO₂ 列跨度仅 1e-18，必须用「下限」而非「上限」来拦——
        #    上限拦不住"极小跨度"，下限才能。
        span = max(x) - min(x)
        if span < 1.0 or span > 2500:
            continue
        # 2) 起点合理性：温度不应从 1e-25 起，也不应密集聚集在 0 附近
        if abs(min(x)) > 2000:
            continue
        # 3) 单调性（温度应随行有序；pO₂/时间跨数量级或无序）
        if len(x) >= 3 and not (all(x[i] < x[i + 1] for i in range(len(x) - 1))
                                or all(x[i] > x[i + 1] for i in range(len(x) - 1))):
            continue
        # 4) 间距均匀性：温度测点通常是 50/100 °C 等距，不会有量级跳跃
        diffs = [abs(x[i + 1] - x[i]) for i in range(len(x) - 1)]
        if diffs and max(diffs) / max(min(diffs), 1e-12) > 100:
            continue
        if len(x) >= 2:
            out.append((label, x, y))
    if not out:
        raise RefuseToDraw("多组分对照：没有任何表同时含合理温度列与电导率列")
    return out


def _is_cn(text: str) -> bool:
    """是否含中文字符。"""
    return any("\u4e00" <= ch <= "\u9fff" for ch in str(text or ""))


def _axis_en(col_name: str, keywords: Tuple[str, ...], default: str) -> str:
    """轴标签英文化：列名是中文（或含中文）就换成标准英译，否则保留原名。

    直接把「时间 (h)」丢给 matplotlib 会因无中文字体而渲染成方框（豆腐块），
    这在投稿图里是硬伤。检索中文期刊图时也要求轴标签英文或斜体拉丁转写。
    """
    name = str(col_name or "")
    if not _is_cn(name):
        return name or default
    low = name.lower()
    for zh in keywords:
        if zh.lower() in low:
            return default
    return default


def _ascii_label(text: str, maxlen: int = 22) -> str:
    """图例文字净化：去中文/特殊符号，避免 matplotlib 字体缺字方框。

    期刊图默认英文标注；若组分为纯中文（如「空气」），退化为 Sample N——
    **宁可信息少一点也不出现豆腐块**，正文图注里已能说明各组含义。

    化学式下标（₂ / ₃ / ⁻¹）在 Arial 下会渲染成错误字形（如 ₂→α），
    统一降级为 ASCII 形式（H2 / H2-Ar），期刊同样接受。
    """
    t = str(text or "")
    # 常见中文→英文对照（够用即可，不追求完备）
    repl = {
        "空气": "air", "还原": "red.", "电池": "cell", "对照": "ref", "主线": "primary",
    }
    for zh, en in repl.items():
        t = t.replace(zh, en)
    # 上下标与特殊符号降级（避免字体缺字导致错误字形）
    for bad, good in (("₂", "2"), ("₃", "3"), ("₂₋₄", "2-4"), ("⁻", "-"), ("⁺", "+"),
                      ("²", "2"), ("·", "-"), ("℃", " C"), ("°", " ")):
        t = t.replace(bad, good)
    if any("\u4e00" <= ch <= "\u9fff" for ch in t):
        return f"Sample {abs(hash(t)) % 90 + 10}"
    return " ".join(t.split())[:maxlen]


def _draw_sigma_t(tables: Sequence[Any], out_path: str) -> Dict[str, Any]:
    """σ vs T 多组分对照（含 log 副轴可选）。"""
    use_journal_style()
    series = _multi_series_sigma(tables)
    fig, ax = plt.subplots(figsize=FIGSIZE_SINGLE)
    for i, (label, x, y) in enumerate(series):
        ax.plot(x, y, "o-", color=OKABE_ITO[i % len(OKABE_ITO)], label=_ascii_label(label))
    ax.set_xlabel("Temperature (°C)")
    ax.set_ylabel("σ (S cm$^{-1}$)")
    ax.legend(frameon=False)
    ax.set_xlim(min(min(s[1]) for s in series) - 20, max(max(s[1]) for s in series) + 20)
    return {**save_figure(fig, out_path), "series": len(series)}


def _draw_arrhenius(tables: Sequence[Any], out_path: str) -> Dict[str, Any]:
    """Arrhenius 图：ln(σT) vs 1000/T，含 Ea 拟合标注。"""
    use_journal_style()
    series = _multi_series_sigma(tables)
    fig, ax = plt.subplots(figsize=FIGSIZE_SINGLE)
    fits: List[Dict[str, Any]] = []
    for i, (label, x, y) in enumerate(series):
        c = OKABE_ITO[i % len(OKABE_ITO)]
        try:
            fit = fit_arrhenius(x, y)
        except RefuseToDraw:
            continue
        # 拟合质量闸：R² 过低（<0.9）说明这不是 Arrhenius 行为，标注出来
        if fit["r2"] < 0.9:
            fit["warning"] = f"R²={fit['r2']:.3f} 偏低，非理想 Arrhenius 行为"
        fits.append(fit)
        ax.plot(fit["x"], fit["y"], "s", color=c, ms=3.5,
                label=f"{_ascii_label(label, 16)} ($E_a$={fit['Ea_eV']:.2f} eV)")
        xs = np.linspace(fit["x"].min(), fit["x"].max(), 50)
        ax.plot(xs, fit["slope"] * xs + fit["intercept"], "-", color=c, lw=1.2)
    if not fits:
        raise RefuseToDraw("Arrhenius：没有一组数据满足拟合条件（≥3 个正值点）")
    ax.set_xlabel("1000/T (K$^{-1}$)")
    ax.set_ylabel("ln(σT)")
    ax.legend(frameon=False, fontsize=7)
    ax.invert_xaxis()  # 惯例：高温在左
    return {**save_figure(fig, out_path),
            "Ea_eV": [round(f["Ea_eV"], 3) for f in fits],
            "r2": [round(f["r2"], 4) for f in fits],
            "warnings": [f["warning"] for f in fits if f.get("warning")]}


def _draw_density_shrink(tables: Sequence[Any], out_path: str) -> Dict[str, Any]:
    """烧结温度–相对密度 / 线收缩率双面板。"""
    use_journal_style()
    pairs: List[Tuple[str, List[float], List[float], List[float]]] = []
    for t in tables or []:
        if not isinstance(t, dict):
            continue
        cols, rows = t.get("columns") or [], t.get("rows") or []
        if not cols or not rows:
            continue
        label = str(t.get("name") or t.get("caption") or "sample")
        try:
            temp, rho, _, _ = to_xy({"columns": cols, "rows": rows},
                                     ["温度", "temperature", "t"],
                                     ["相对密度", "density", "密度"])
        except RefuseToDraw:
            continue
        try:
            _, shrink, _, _ = to_xy({"columns": cols, "rows": rows},
                                     ["温度", "temperature"],
                                     ["收缩", "shrinkage", "线收缩"])
        except RefuseToDraw:
            shrink = [float("nan")] * len(temp)
        if len(temp) >= 2:
            pairs.append((label, temp, rho, shrink))
    if not pairs:
        raise RefuseToDraw("密度/收缩率：录入数据中无「温度×相对密度」表")
    fig, axes = plt.subplots(1, 2, figsize=FIGSIZE_DOUBLE)
    for i, (label, temp, rho, shrink) in enumerate(pairs):
        c = OKABE_ITO[i % len(OKABE_ITO)]
        axes[0].plot(temp, rho, "o-", color=c, label=_ascii_label(label, 18))
        s = [v for v in shrink if np.isfinite(v)]
        if s:
            axes[1].plot(temp[: len(s)], s, "s-", color=c, label=_ascii_label(label, 18))
    axes[0].set_xlabel("Sintering temperature (°C)")
    axes[0].set_ylabel("Relative density (%)")
    axes[1].set_xlabel("Sintering temperature (°C)")
    axes[1].set_ylabel("Linear shrinkage (%)")
    for a in axes:
        a.legend(frameon=False, fontsize=7)
    fig.tight_layout()
    return {**save_figure(fig, out_path), "series": len(pairs)}


def _draw_iv_ip(tables: Sequence[Any], out_path: str) -> Dict[str, Any]:
    """I–V / I–P 双面板（OCV 标注）。"""
    use_journal_style()
    picked = None
    for t in tables or []:
        if not isinstance(t, dict):
            continue
        cols, rows = t.get("columns") or [], t.get("rows") or []
        if not cols or not rows:
            continue
        try:
            j, pp, _, _ = to_xy({"columns": cols, "rows": rows},
                                ["电流密度", "current density", "j (a·cm⁻²)", "j"],
                                ["功率密度", "power density", "ppd", "功率"])
        except RefuseToDraw:
            continue
        if len(j) >= 2:
            picked = (str(t.get("name") or t.get("caption") or "cell"), j, pp)
            break
    if picked is None:
        raise RefuseToDraw("I–V/I–P：录入数据中无「电流密度×功率密度」表")
    label, j, pp = picked
    fig, axes = plt.subplots(1, 2, figsize=FIGSIZE_DOUBLE)
    axes[0].plot(pp, j, "o-", color=OKABE_ITO[0])
    axes[0].set_xlabel("Power density (W cm$^{-2}$)")
    axes[0].set_ylabel("Current density (A cm$^{-2}$)")
    axes[1].plot(j, pp, "o-", color=OKABE_ITO[1])
    axes[1].set_xlabel("Current density (A cm$^{-2}$)")
    axes[1].set_ylabel("Power density (W cm$^{-2}$)")
    axes[0].set_title(_ascii_label(label, 30), fontsize=8)
    fig.tight_layout()
    peak = max(pp)
    return {**save_figure(fig, out_path), "peak_power_density": round(float(peak), 4)}


def _draw_stability(tables: Sequence[Any], out_path: str) -> Dict[str, Any]:
    """恒流稳定性：电压–时间曲线 + 衰减率标注。"""
    use_journal_style()
    picked = None
    for t in tables or []:
        if not isinstance(t, dict):
            continue
        cols, rows = t.get("columns") or [], t.get("rows") or []
        if not cols or not rows:
            continue
        try:
            tt, vv, xname, yname = to_xy({"columns": cols, "rows": rows},
                                          ["时间", "time", "t/h", "h"],
                                          ["电压", "voltage", "v"])
        except RefuseToDraw:
            continue
        if len(tt) >= 2:
            picked = (str(t.get("name") or t.get("caption") or "stability"), tt, vv, xname, yname)
            break
    if picked is None:
        raise RefuseToDraw("稳定性：录入数据中无「时间×电压」表")
    label, tt, vv, xname, yname = picked
    use_journal_style()
    fig, ax = plt.subplots(figsize=FIGSIZE_SINGLE)
    ax.plot(tt, vv, "o-", color=OKABE_ITO[0])
    # 轴标签统一英文化：录入列名多为中文，直接用会渲染成豆腐块
    xl = _axis_en(xname, ("时间", "time"), "Time (h)")
    yl = _axis_en(yname, ("电压", "voltage"), "Voltage (V)")
    ax.set_xlabel(xl)
    ax.set_ylabel(yl)
    ax.set_title(_ascii_label(label, 34), fontsize=8)
    # 衰减率（%/100h）——评审特别关注数量级，这里显式计算并标注
    decay_per_100h = None
    if len(tt) >= 2 and tt[-1] != tt[0] and vv[0]:
        span_h = tt[-1] - tt[0]
        decay_per_100h = (vv[0] - vv[-1]) / vv[0] * 100.0 / (span_h / 100.0) if span_h else None
        if decay_per_100h is not None:
            ax.text(0.03, 0.95, f"decay ≈ {decay_per_100h:.2f} %·(100 h)$^{{-1}}$",
                    transform=ax.transAxes, va="top", fontsize=8)
    return {**save_figure(fig, out_path),
            "decay_pct_per_100h": None if decay_per_100h is None else round(decay_per_100h, 4)}


def _draw_po2_sigmae(tables: Sequence[Any], out_path: str) -> Dict[str, Any]:
    """σ_e–pO₂（log–log，含 1/4 / 1/2 斜率参考线）。"""
    use_journal_style()
    picked = None
    for t in tables or []:
        if not isinstance(t, dict):
            continue
        cols, rows = t.get("columns") or [], t.get("rows") or []
        if not cols or not rows:
            continue
        try:
            x, y, xn, yn = to_xy({"columns": cols, "rows": rows},
                                  ["po2", "po₂", "氧分压"],
                                  ["σe", "σ_e", "sigmae", "sigma_e", "电子电导"])
        except RefuseToDraw:
            continue
        if len(x) >= 2 and all(v > 0 for v in x):
            picked = (str(t.get("name") or t.get("caption") or "sigma_e"), x, y, xn, yn)
            break
    if picked is None:
        raise RefuseToDraw("σ_e–pO₂：录入数据中无「pO₂×σ_e」表")
    label, x, y, xn, yn = picked
    use_journal_style()
    fig, ax = plt.subplots(figsize=FIGSIZE_SINGLE)
    lx, ly = np.log10(np.asarray(x)), np.log10(np.asarray(y))
    ax.plot(lx, ly, "o", color=OKABE_ITO[2], label=label[:22])
    # 参考斜率 1/4（p 型电子电导典型）
    if len(lx) >= 2:
        ref_x = np.linspace(lx.min(), lx.max(), 20)
        anchor = ly[0] - 0.25 * (lx[0] - ref_x[0])
        ax.plot(ref_x, anchor + 0.25 * ref_x, "--", color=OKABE_ITO[7], lw=1.0, label="slope 1/4")
    ax.set_xlabel("log pO$_2$")
    ax.set_ylabel("log σ$_e$")
    ax.legend(frameon=False)
    slope = float(np.polyfit(lx, ly, 1)[0]) if len(lx) >= 2 else None
    return {**save_figure(fig, out_path), "fitted_slope": None if slope is None else round(slope, 3)}


def _draw_xrd(tables: Sequence[Any], out_path: str) -> Dict[str, Any]:
    """XRD 全谱（多组分叠放）。"""
    use_journal_style()
    series: List[Tuple[str, List[float], List[float]]] = []
    for t in tables or []:
        if not isinstance(t, dict):
            continue
        cols, rows = t.get("columns") or [], t.get("rows") or []
        if not cols or not rows:
            continue
        try:
            two_theta, inten, _, _ = to_xy({"columns": cols, "rows": rows},
                                           ["2θ", "2theta", "角度", "2-theta"],
                                           ["强度", "intensity", "counts", "cps"])
        except RefuseToDraw:
            continue
        if len(two_theta) >= 3:
            series.append((str(t.get("name") or t.get("caption") or "sample"), two_theta, inten))
    if not series:
        raise RefuseToDraw("XRD：录入数据中无「2θ×强度」表")
    fig, ax = plt.subplots(figsize=FIGSIZE_DOUBLE if len(series) > 1 else FIGSIZE_SINGLE)
    for i, (label, tt, yy) in enumerate(series):
        base = i * 0.15
        ax.plot(tt, [v / max(yy) * 0.8 + base for v in yy], "-",
                color=OKABE_ITO[i % len(OKABE_ITO)], lw=1.0, label=_ascii_label(label, 18))
    ax.set_xlabel("2θ (°)")
    ax.set_ylabel("Intensity (normalized)")
    ax.legend(frameon=False, fontsize=7)
    return {**save_figure(fig, out_path), "series": len(series)}


def _draw_eis(tables: Sequence[Any], out_path: str) -> Dict[str, Any]:
    """EIS Nyquist（含等效电路拟合）—— 走 impedance.py 专业库。

    若 impedance.py 不可用，降级为纯散点图（matplotlib），
    保证「有数据总能出图」，只是失去拟合叠加。
    """
    try:
        from matlens_kit.paper.fig_eis import draw_nyquist_bode

        res = draw_nyquist_bode(tables, out_path)
        if res:
            return res
    except RefuseToDraw:
        raise
    except Exception as e:  # noqa: BLE001
        # 专业库失败 → 降级通用散点，但必须如实告知
        import warnings

        warnings.warn(f"impedance.py 绘图失败（{e}），降级为散点图")
    use_journal_style()
    from matlens_kit.paper.fig_eis import extract_eis

    spec = extract_eis(tables)
    fig, ax = plt.subplots(figsize=FIGSIZE_SINGLE)
    ax.plot(spec["zreal"], spec["znegimag"], "s", ms=3.5,
            color=OKABE_ITO[0], mfc=OKABE_ITO[0], mec="none")
    ax.set_xlabel("$Z\'$ ($\\Omega$ cm$^2$)")
    ax.set_ylabel("$-Z\'\'$ ($\\Omega$ cm$^2$)")
    ax.set_aspect("equal", adjustable="datalim")
    return {**save_figure(fig, out_path), "n_points": int(len(spec["f"])),
            "library": "matplotlib (impedance.py 不可用)"}


# ---------------------------------------------------------------------------
# 调度
# ---------------------------------------------------------------------------
SCHEMES = {
    "sigma_t": _draw_sigma_t,
    "arrhenius": _draw_arrhenius,
    "density_shrink": _draw_density_shrink,
    "iv_ip": _draw_iv_ip,
    "stability": _draw_stability,
    "po2_sigmae": _draw_po2_sigmae,
    "xrd": _draw_xrd,
    "eis": _draw_eis,
}


def draw_scheme(
    scheme: str,
    tables: Sequence[Any],
    out_path: str,
    strict: bool = True,
) -> Dict[str, Any]:
    """按谱系绘图。数据不足时抛 :class:`RefuseToDraw`。

    Args:
        scheme: :func:`detect_scheme` 返回的谱系名
        tables: experimental_data.tables
        out_path: 输出路径前缀（不含扩展名）
        strict: True 时对数值做图-文一致性校验（检查绘图值能在录入数据里找到）
    """
    fn = SCHEMES.get(scheme)
    if fn is None:
        raise RefuseToDraw(f"未实现的谱系：{scheme}（可用：{list(SCHEMES)}）")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    return fn(tables, out_path)