# -*- coding: utf-8 -*-
"""电化学/电池领域工具（MatLens 材料垂直）。

battery_capacity —— 电极材料理论比容量：
    C = n·F / (3.6·M)  （mAh/g）
    F = 96485 C/mol（法拉第常数）；3.6 = 3600 s/h ÷ 1000 的合并因子（C·s⁻¹·h 换算成 mAh）。

支持两种输入：
1. ``formula``（整数下标化学式，如 LiFePO4 / LiCoO2）→ 自动用 parse_formula 求摩尔质量；
2. ``molar_mass``（直接给 g/mol，如固溶体 NCM811 ≈ 96.5）→ 跳过公式解析。

注意：parse_formula 仅支持整数下标与点号水合物，固溶体小数下标（LiNi0.8Co0.1Mn0.1O2）
不在其支持范围内，请使用 molar_mass 输入模式（本工具会给出明确提示）。
"""
from __future__ import annotations

from typing import Any, Dict

from tools.registry import registry, tool_result

_FARADAY = 96485.0  # C/mol

# 常见电极材料参考摩尔质量（g/mol，含 Li 脱嵌前化学式）——仅作提示，不参与计算
_REFERENCE_M = {
    "LiCoO2": 97.87,
    "LiFePO4": 157.76,
    "LiMn2O4": 180.81,
    "LiNi0.8Co0.1Mn0.1O2": 96.49,
    "LiNi0.6Co0.2Mn0.2O2": 95.93,
}


def _parse_molar_mass(formula: str) -> float:
    """用 parse_formula 计算整数下标化学式的摩尔质量；失败抛 ValueError。"""
    from matlens_kit.tools.computation import molar_mass_tool

    r = molar_mass_tool(formula=formula)
    mm = r.get("molar_mass_g_mol")
    if mm is None or mm <= 0:
        raise ValueError(r.get("error") or f"无法解析化学式：{formula}")
    return float(mm)


def battery_capacity_tool(
    formula: str = "",
    molar_mass: float | None = None,
    n: float = 1.0,
    **kwargs: Any,
) -> Dict[str, Any]:
    """计算电极材料的理论比容量（mAh/g）。

    Args:
        formula: 整数下标化学式（LiFePO4 / LiCoO2）。固溶体（NCM811 等）请用 molar_mass。
        molar_mass: 摩尔质量 g/mol（与 formula 二选一；给 formula 时忽略）。
        n: 每个分子式的转移电子数（锂电正极常见 1）。

    Returns:
        理论比容量、所用摩尔质量、电子数与计算式。
    """
    m_value: float | None = molar_mass
    source = "molar_mass"
    if not m_value and formula:
        try:
            m_value = _parse_molar_mass(formula)
            source = f"formula={formula}"
        except ValueError as exc:
            # 固溶体小数下标不在 parse_formula 支持范围 → 明确提示用 molar_mass
            return {
                "error": (
                    f"{exc}。固溶体/小数下标化学式（如 NCM811 LiNi0.8Co0.1Mn0.1O2）"
                    "请用 molar_mass 直接给摩尔质量（NCM811 ≈ 96.5 g/mol）。"
                ),
                "formula": formula,
            }
    if not m_value or m_value <= 0:
        return {"error": "需要 molar_mass（g/mol）或可解析的 formula，且 molar_mass > 0"}
    if n <= 0:
        return {"error": "n（转移电子数）必须 > 0"}

    capacity = n * _FARADAY / (3.6 * m_value)  # mAh/g
    return {
        "formula": formula or None,
        "molar_mass_g_mol": round(m_value, 4),
        "n": n,
        "theoretical_capacity_mAh_g": round(capacity, 2),
        "calculation": f"C = {n} × {_FARADAY:.0f} / (3.6 × {m_value:.4g}) = {capacity:.2f} mAh/g",
        "note": (
            "理论比容量为上限，实际受结构/导电剂/首效影响；"
            + (f"参考：{formula} 常见 M ≈ {_REFERENCE_M.get(formula, '')} g/mol" if formula in _REFERENCE_M else "")
        ),
    }


BATTERY_CAPACITY_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": "电极材料理论比容量 C=nF/(3.6M)，支持化学式或直接给摩尔质量（含固溶体）。",
    "examples": [{"formula": "LiFePO4", "n": 1}],
    "properties": {
        "formula": {
            "type": "string",
            "description": "整数下标化学式，如 LiFePO4 / LiCoO2；固溶体（NCM811）请改用 molar_mass",
        },
        "molar_mass": {
            "type": "number",
            "description": "摩尔质量 g/mol（NCM811 ≈ 96.5）；与 formula 二选一",
        },
        "n": {
            "type": "number",
            "description": "每个分子式转移电子数（锂电正极常见 1）",
        },
    },
    "additionalProperties": False,
}


def _check_electrochem_available() -> bool:
    return True


registry.register(
    name="battery_capacity",
    toolset="matlens_material",
    schema=BATTERY_CAPACITY_SCHEMA,
    handler=lambda args, **kw: tool_result(battery_capacity_tool(**args)),
    check_fn=_check_electrochem_available,
    description="电极材料理论比容量：C=nF/(3.6M)，支持化学式或直接给摩尔质量（含固溶体 NCM811）",
    emoji="🔋",
)
