# -*- coding: utf-8 -*-
"""热力学/相图工具（MatLens 材料垂直）。

thermo_gibbs —— Gibbs 自由能判据与平衡温度：
    ΔG = ΔH − T·ΔS
    判断指定温度下反应自发方向，并给出 ΔG=0 的平衡温度（T_eq = ΔH/ΔS）。

lever_rule —— 二元相图杠杆定律：
    给定整体组成与两平衡相组成，计算两相相对质量分数。
    W_α = (x_β − x_0)/(x_β − x_α)，W_β = (x_0 − x_α)/(x_β − x_α)
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from tools.registry import registry, tool_result


def thermo_gibbs_tool(
    delta_h: float,
    delta_s: float,
    temperature: Optional[float] = None,
    temperature_c: Optional[float] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Gibbs 自由能判据：ΔG = ΔH − T·ΔS。

    Args:
        delta_h: 焓变 kJ/mol。
        delta_s: 熵变 J/(mol·K)。
        temperature: 温度 K（与 temperature_c 二选一）。
        temperature_c: 温度 °C（优先换算成 K）。

    Returns:
        ΔG、自发方向、平衡温度 T_eq 与计算式。
    """
    if temperature_c is not None:
        temperature = float(temperature_c) + 273.15
    if temperature is not None and temperature <= 0:
        return {"error": "温度必须 > 0 K"}
    ds_kj = float(delta_s) / 1000.0  # J→kJ
    dg = float(delta_h) - (float(temperature) * ds_kj if temperature is not None else 0.0)
    t_eq = (float(delta_h) / ds_kj) if ds_kj != 0 else None

    direction = None
    if temperature is not None:
        if dg < 0:
            direction = "正向自发（ΔG<0）"
        elif dg > 0:
            direction = "逆向自发（ΔG>0）"
        else:
            direction = "平衡（ΔG=0）"

    out: Dict[str, Any] = {
        "delta_h_kJ_mol": delta_h,
        "delta_s_J_mol_K": delta_s,
        "temperature_K": temperature,
        "delta_g_kJ_mol": round(dg, 4) if temperature is not None else None,
        "formula": "ΔG = ΔH − T·ΔS",
        "calculation": (
            f"ΔG = {delta_h} − {temperature}×({ds_kj:.6g}) = {dg:.4g} kJ/mol"
            if temperature is not None
            else f"ΔG = ΔH − T·ΔS（未给温度，请提供 temperature 或 temperature_c）"
        ),
    }
    if direction:
        out["direction"] = direction
    if t_eq is not None and t_eq > 0:
        out["equilibrium_temperature_K"] = round(t_eq, 2)
        out["equilibrium_temperature_C"] = round(t_eq - 273.15, 2)
        out["note"] = f"ΔG=0 平衡温度 T_eq = ΔH/ΔS = {t_eq:.2f} K（{t_eq-273.15:.2f} °C）；T<T_eq 时逆焓方向占优，T>T_eq 时熵驱动"
    elif ds_kj == 0:
        out["note"] = "ΔS=0，ΔG 与温度无关，无平衡温度（T_eq 不存在）"
    return out


THERMO_GIBBS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": "Gibbs 自由能判据 ΔG=ΔH−T·ΔS，判断自发方向与平衡温度。",
    "examples": [{"delta_h": -92.3, "delta_s": -198.7, "temperature_c": 25}],
    "properties": {
        "delta_h": {"type": "number", "description": "焓变 kJ/mol"},
        "delta_s": {"type": "number", "description": "熵变 J/(mol·K)"},
        "temperature": {"type": "number", "description": "温度 K（与 temperature_c 二选一）"},
        "temperature_c": {"type": "number", "description": "温度 °C（自动转 K）"},
    },
    "required": ["delta_h", "delta_s"],
    "additionalProperties": False,
}


def lever_rule_tool(
    composition: float,
    phase1: float,
    phase2: float,
    **kwargs: Any,
) -> Dict[str, Any]:
    """二元相图杠杆定律：两平衡相相对质量分数。

    Args:
        composition: 整体组成 x0（原子分数或质量分数，与两相同单位）。
        phase1: α 相组成 xα。
        phase2: β 相组成 xβ。

    Returns:
        两相质量分数（%）、和校验说明。
    """
    xa, xb = float(phase1), float(phase2)
    x0 = float(composition)
    if xa == xb:
        return {"error": "两相组成相同（xα=xβ），杠杆定律无意义"}
    lo, hi = min(xa, xb), max(xa, xb)
    if x0 < lo - 1e-9 or x0 > hi + 1e-9:
        return {
            "error": f"整体组成 {x0} 不在两相区 [{lo}, {hi}] 内（可能为单相区或超出共晶/共析组成）",
            "two_phase_region": [lo, hi],
        }
    # 归一化：把"靠近 β 的组成更多 → α 相更多"的杠杆关系算对
    w_a = (xb - x0) / (xb - xa)  # α 相分数
    w_b = (x0 - xa) / (xb - xa)  # β 相分数
    return {
        "composition_x0": x0,
        "phase1_x_alpha": xa,
        "phase2_x_beta": xb,
        "phase1_mass_fraction": round(w_a, 6),
        "phase2_mass_fraction": round(w_b, 6),
        "phase1_pct": round(w_a * 100, 2),
        "phase2_pct": round(w_b * 100, 2),
        "sum_check": round(w_a + w_b, 9),
        "calculation": f"W(α) = ({xb}−{x0})/({xb}−{xa}) = {w_a:.4f}；W(β) = ({x0}−{xa})/({xb}−{xa}) = {w_b:.4f}",
        "note": "杠杆定律适用于两相区平衡态（整体在 [xα,xβ] 之间）；相分数可理解为该组成的相图水平线截距比",
    }


LEVER_RULE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": "二元相图杠杆定律：两平衡相相对质量分数。",
    "examples": [{"composition": 0.4, "phase1": 0.1, "phase2": 0.8}],
    "properties": {
        "composition": {"type": "number", "description": "整体组成 x0（原子分数或质量分数）"},
        "phase1": {"type": "number", "description": "α 相组成 xα"},
        "phase2": {"type": "number", "description": "β 相组成 xβ"},
    },
    "required": ["composition", "phase1", "phase2"],
    "additionalProperties": False,
}


def _check_thermo_available() -> bool:
    return True


registry.register(
    name="thermo_gibbs",
    toolset="matlens_material",
    schema=THERMO_GIBBS_SCHEMA,
    handler=lambda args, **kw: tool_result(thermo_gibbs_tool(**args)),
    check_fn=_check_thermo_available,
    description="Gibbs 自由能判据：ΔG=ΔH−T·ΔS，判断反应自发方向并给平衡温度",
    emoji="🔥",
)

registry.register(
    name="lever_rule",
    toolset="matlens_material",
    schema=LEVER_RULE_SCHEMA,
    handler=lambda args, **kw: tool_result(lever_rule_tool(**args)),
    check_fn=_check_thermo_available,
    description="二元相图杠杆定律：两平衡相相对质量分数（Wα/Wβ）",
    emoji="⚖️",
)
