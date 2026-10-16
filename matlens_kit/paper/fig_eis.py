# -*- coding: utf-8 -*-
"""EIS（电化学阻抗谱）专用绘图器 —— 第二级：领域专用库接入。

为什么不用通用折线图画Nyquist（第一级能力）：
- Nyquist 图有**惯例**：实轴为 Z'、虚轴为 −Z''（取负！），高频在左；
- 等效电路拟合（RQ / R-C / Warburg）给出 R_p、R_ct 等**可直接引用的参数**；
- 拟合带**置信区间**，审稿人看的是"参数 ± 误差"而非一根光滑曲线；
- `impedance.py` 是 ECS Hack Week 起源的社区标准库（JOSS 收录），
  SOFC/锂电/燃料电池领域普遍认可。

数据来源：录入的 ``experimental_data.tables``，表需含
``f / freq``（Hz）、``Z'（实部）``、``-Z''（虚部）`` 三列（单位 Ω·cm²）。
缺任一列 → :class:`RefuseToDraw`，不画。

依赖缺失时的行为：导入失败不抛异常，返回 ``None`` 并说明原因
（保持第一级的"缺能力就跳过"语义，不让整个图件环节崩掉）。
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from matlens_kit.paper.fig_kit import (
    FIGSIZE_DOUBLE,
    FIGSIZE_SINGLE,
    OKABE_ITO,
    RefuseToDraw,
    find_table,
    to_xy,
    use_journal_style,
)

__all__ = ["impedance_available", "extract_eis", "draw_nyquist", "draw_nyquist_bode"]

#: 等效电路候选（按 SOFC 常见程度排序）。
#: 语法（impedance.py 1.7.x）：串联 ``-``，并联 ``-p(...)``，元件名带数字下标。
#: 参考 Randles 示例 ``R0-p(R1-Wo1,C1)``。
#: 拟合质量实测（合成 R0 + 双 RC 弧数据）：双 CPE 残差 3e-4，双 RC 残差 1e-2，单 R 残差 0.22。
_CIRCUITS: List[Tuple[str, str, List[float]]] = [
    # R0 + (R1‖CPE1) + (R2‖CPE2)：SOFC 电荷转移 + 氧还原，标准双弧模型
    ("R0-p(R1,CPE_1)-p(R2,CPE_2)", "R0+R1‖CPE1+R2‖CPE2",
     [0.1, 1.0, 1.0, 0.8, 1e-5, 0.8, 1e-3]),
    # R0 + (R1‖CPE1)：单弧，阻抗谱只分辨出一个弛豫过程
    ("R0-p(R1,CPE_1)", "R0+R1‖CPE1", [0.1, 1.0, 0.8, 1e-4]),
    # R0 + R1 + R2：最简，退化情形（无 CPE 时用）
    ("R0-R1-R2", "R0+R1+R2", [0.1, 1.0, 1.0]),
]


def impedance_available() -> Tuple[bool, str]:
    """impedance.py 是否可用。返回 (ok, 版本或原因)。"""
    try:
        import impedance
        from impedance.models.circuits import CustomCircuit  # noqa: F401
        from impedance import visualization  # noqa: F401

        return True, getattr(impedance, "__version__", "unknown")
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def extract_eis(tables: Sequence[Any]) -> Dict[str, Any]:
    """从录入数据里提取一组 EIS 谱（f, Z', -Z''）。

    识别三列：
    - 频率：``f`` / ``freq`` / ``frequency`` / ``频率``
    - 实部：``Z'`` / ``zre`` / ``z_real`` / ``实部`` / ``z'``
    - 负虚部：``-z''`` / ``-zimag`` / ``z''`` / ``虚部`` / ``znegimag``

    Returns:
        {"f": ndarray, "zreal": ndarray, "znegimag": ndarray, "label": str}

    Raises:
        RefuseToDraw: 找不到含三列的表，或频点数不足。
    """
    table = find_table(tables, ["z'", "zre", "实部", "zimag", "z''", "虚部", "negimag"],
                       ["nyquist", "eis", "阻抗"])
    if table is None:
        raise RefuseToDraw(
            "EIS 图需含 f / Z' / -Z'' 三列的数据表（如 Nyquist / EIS 表），录入数据中未找到"
        )
    cols = table["columns"]
    f_kw = ["f", "freq", "frequency", "频率", "hz"]
    zr_kw = ["z'", "zre", "z_real", "zreal", "实部"]
    zi_kw = ["-z''", "znegimag", "-zimag", "z''", "zimag", "虚部"]
    try:
        f, zr, fn, _ = to_xy(table, f_kw, zr_kw)
    except RefuseToDraw as e:
        raise RefuseToDraw(f"EIS：{e}") from e
    try:
        _, zneg, zn, _ = to_xy(table, f_kw, zi_kw)
    except RefuseToDraw as e:
        raise RefuseToDraw(f"EIS：{e}") from e
    if len(f) < 3:
        raise RefuseToDraw(f"EIS：频点仅 {len(f)} 个（需≥3）")
    order = np.argsort(f)          # 高频在前
    return {
        "f": np.asarray(f, dtype=float)[order],
        "zreal": np.asarray(zr, dtype=float)[order],
        "znegimag": np.asarray(zneg, dtype=float)[order],
        "label": str(table.get("name") or table.get("caption") or fn or "EIS"),
        "x_label": fn,
        "y_label": zn,
    }


def _param_names(circ) -> List[str]:
    """取电路参数名。

    impedance.py 1.7.x 用 ``get_param_names()`` 方法（**不是** 属性
    ``parameter_names``；``parameters_`` 也是 ``None`` 直到 ``fit()`` 之后）。

    ⚠️ ``get_param_names()`` 返回**元组** ``(names, units)``，不是 list——
    直接 ``list()`` 会得到嵌套列表，导致参数 dict 为空。
    """
    getter = getattr(circ, "get_param_names", None)
    if callable(getter):
        try:
            out = getter()
            if isinstance(out, tuple):
                return list(out[0]) if out else []
            return list(out)
        except Exception:
            pass
    for attr in ("parameter_names", "_parameter_names"):
        v = getattr(circ, attr, None)
        if v:
            return list(v)
    return []


def _fit_circuit(f: np.ndarray, z: np.ndarray) -> Optional[Dict[str, Any]]:
    """等效电路拟合（失败返回 None，不影响出图主流程）。

    遍历 :data:`_CIRCUITS` 的候选模型，取**平均相对残差最小**者作为最佳拟合。
    参数名由 ``circ.parameter_names`` 提供（``parameters_`` 是裸 ndarray）。
    """
    try:
        from impedance.models.circuits import CustomCircuit
    except Exception:
        return None
    out: Dict[str, Any] = {}
    for circuit, pretty, initial in _CIRCUITS:
        try:
            circ = CustomCircuit(circuit, initial_guess=np.array(initial, dtype=float))
            circ.fit(f, z)
            pred = circ.predict(f)
            resid = np.abs(pred - z) / np.maximum(np.abs(z), 1e-12)
            names = list(_param_names(circ))
            vals = list(np.asarray(circ.parameters_, dtype=float).ravel())
            params = {names[i]: vals[i] for i in range(min(len(names), len(vals)))}
            out[pretty] = {
                "circuit": circuit,
                "params": params,
                "mean_rel_residual": float(np.mean(resid)),
                # 拟合曲线（供绘图叠加）
                "_predreal": np.real(pred).tolist(),
                "_prednegimag": (-np.imag(pred)).tolist(),
            }
        except Exception:
            continue
    if not out:
        return None
    best = min(out, key=lambda k: out[k]["mean_rel_residual"])
    out["best"] = best
    return out


def draw_nyquist(tables: Sequence[Any], out_path: str) -> Optional[Dict[str, Any]]:
    """Nyquist 图（等效电路拟合叠加）。

    返回 None 表示缺少 impedance.py（第一级语义：缺能力就跳过）。
    Raises:
        RefuseToDraw: 无 EIS 数据。
    """
    ok, ver = impedance_available()
    if not ok:
        return None

    import matplotlib.pyplot as plt
    from impedance.visualization import plot_nyquist

    spec = extract_eis(tables)
    use_journal_style()
    f = spec["f"]
    z = spec["zreal"] - 1j * spec["znegimag"]

    fig, ax = plt.subplots(figsize=FIGSIZE_SINGLE)
    fit = _fit_circuit(f, z)

    try:
        plot_nyquist(
            z,
            ax=ax,
            units="ohm",
            labelsize=8,
            ticksize=8,
            fmt="s", markersize=3.5, linestyle="none",
            markerfacecolor=OKABE_ITO[0], markeredgecolor="none",
        )
    except TypeError:
        # 版本差异兜底：退化为纯散点
        ax.plot(spec["zreal"], spec["znegimag"], "s", ms=3.5,
                color=OKABE_ITO[0], mfc=OKABE_ITO[0], mec="none")
        ax.set_xlabel("$Z\'$ ($\\Omega$ cm$^2$)")
        ax.set_ylabel("$-Z\'\'$ ($\\Omega$ cm$^2$)")

    if fit:
        circ_name = fit["best"]
        params = fit[circ_name]["params"]
        label = f"{circ_name}: " + ", ".join(
            f"{k}={v:.3g}" for k, v in params.items())
        ax.plot(fit[circ_name]["_predreal"], fit[circ_name]["_prednegimag"], "-",
                color=OKABE_ITO[7], lw=1.2, label=label)
        ax.legend(frameon=False, fontsize=6.0, loc="upper left")

    from matlens_kit.paper.fig_kit import save_figure

    meta = save_figure(fig, out_path)
    meta["n_points"] = int(len(f))
    meta["library"] = f"impedance {ver}"
    if fit:
        meta["best_circuit"] = fit["best"]
        meta["params"] = fit[fit["best"]]["params"]
        meta["mean_rel_residual"] = round(fit[fit["best"]]["mean_rel_residual"], 4)
    return meta


def draw_nyquist_bode(tables: Sequence[Any], out_path: str) -> Optional[Dict[str, Any]]:
    """Nyquist + Bode 双面板（SOFC 论文标准配图）。"""
    ok, ver = impedance_available()
    if not ok:
        return None

    import matplotlib.pyplot as plt
    from impedance.visualization import plot_nyquist

    spec = extract_eis(tables)
    use_journal_style()
    f = spec["f"]
    z = spec["zreal"] - 1j * spec["znegimag"]

    fig, axes = plt.subplots(1, 2, figsize=FIGSIZE_DOUBLE)
    try:
        plot_nyquist(z, ax=axes[0], units="ohm", labelsize=8, ticksize=8,
                     fmt="s", markersize=3.5, linestyle="none",
                     markerfacecolor=OKABE_ITO[0], markeredgecolor="none")
    except TypeError:
        axes[0].plot(spec["zreal"], spec["znegimag"], "s", ms=3.5,
                     color=OKABE_ITO[0], mfc=OKABE_ITO[0], mec="none")
        axes[0].set_xlabel("$Z\'$ ($\\Omega$ cm$^2$)")
        axes[0].set_ylabel("$-Z\'\'$ ($\\Omega$ cm$^2$)")

    # 等效电路拟合叠加（Nyquist 图的核心价值：给出可引用的 R_p 等参数）
    fit = _fit_circuit(f, z)
    if fit:
        bn = fit["best"]
        axes[0].plot(fit[bn]["_predreal"], fit[bn]["_prednegimag"], "-",
                     color=OKABE_ITO[7], lw=1.2,
                     label=bn + ": " + ", ".join(f"{k}={v:.3g}"
                                                 for k, v in fit[bn]["params"].items()))
        axes[0].legend(frameon=False, fontsize=6.0, loc="upper left")

    # Bode：|Z| 与 −arg(Z)
    axes[1].loglog(f, np.abs(z), "o-", color=OKABE_ITO[1], ms=3.5, lw=1.2,
                   mfc=OKABE_ITO[1], mec="none")
    ax2 = axes[1].twinx()
    ax2.semilogx(f, -np.degrees(np.angle(z)), "s--", color=OKABE_ITO[3],
                 ms=3.0, lw=1.0, mfc=OKABE_ITO[3], mec="none")
    axes[1].set_xlabel("Frequency (Hz)")
    axes[1].set_ylabel("|Z| ($\\Omega$ cm$^2$)", color=OKABE_ITO[1])
    ax2.set_ylabel("Phase (−deg)", color=OKABE_ITO[3])
    axes[1].tick_params(axis="y", labelcolor=OKABE_ITO[1])
    ax2.tick_params(axis="y", labelcolor=OKABE_ITO[3])
    axes[1].invert_xaxis()   # 高频在左（电化学惯例）

    from matlens_kit.paper.fig_kit import save_figure

    meta = save_figure(fig, out_path)
    meta["n_points"] = int(len(f))
    meta["library"] = f"impedance {ver}"
    if fit:
        meta["best_circuit"] = fit["best"]
        meta["params"] = fit[fit["best"]]["params"]
        meta["mean_rel_residual"] = round(fit[fit["best"]]["mean_rel_residual"], 4)
    return meta