"""计算辅助类材料工具：摩尔质量 / 溶液配制 / 半导体带隙（Tauc plot）。

全部离线实现，通过 Hermes registry 注册为 matlens 工具集。
"""

from __future__ import annotations

import json
import math
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from tools.registry import registry, tool_error, tool_result

from matlens_kit.tools.periodic_table import SYMBOL_INDEX


# ─────────────────────────────────────────────────────────────
# ① 摩尔质量计算器
# ─────────────────────────────────────────────────────────────
def parse_formula(formula: str) -> List[Tuple[str, int]]:
    """解析化学式（支持括号与下标，如 Fe2O3、Ca(OH)2、CuSO4·5H2O）。

    Args:
        formula: 化学式字符串（元素符号 + 下标数字，支持圆括号与点号水合物）。

    Raises:
        ValueError: 公式含固溶体小数下标（如 LiNi0.8Co0.1Mn0.1O2）时明确报错——
            小数下标与水合物点号（·5H2O）语义冲突，本解析器不支持，避免静默给错摩尔质量。

    Returns:
        元素计数列表 [(符号, 原子数), ...]，按出现顺序。
    """
    text = formula.replace("·", ".").replace("•", ".")
    # 固溶体小数下标检测：点号后数字紧跟元素符号（Ni0.8 / Co0.1）＝小数下标；
    # 点号后数字紧跟 H2O（·5H2O）＝水合物，二者语义不同，混用会静默算错。
    for m in re.finditer(r"\.(\d+)", text):
        after = text[m.end():m.end() + 3]
        if after.startswith(("H2O", "H₂O", "H2o", "D2O")):
            continue  # 水合物点号，正常
        if re.match(r"[A-Z]", after):
            raise ValueError(
                "化学式含小数下标（固溶体，如 NCM811 的 LiNi0.8Co0.1Mn0.1O2），"
                "本工具不支持小数下标，请直接给 molar_mass"
            )
    # 先解析水合物部分（点号后的 H2O 视为整体）
    parts = re.split(r"\.", text)
    counts: Dict[str, int] = {}
    for part in parts:
        _parse_hydrate_group(part, counts)
    return [(sym, n) for sym, n in counts.items() if n > 0]


def _parse_hydrate_group(part: str, counts: Dict[str, int]) -> None:
    """解析点号分隔的一段化学式，支持水合物前导系数（如 5H2O、10H2O）。

    一段形如 ``5H2O`` 的段：前导数字 ``5`` 是水分子系数，剩余 ``H2O`` 整体 ×5；
    无前导数字（如 ``H2O`` / ``CuSO4``）系数视为 1。
    """
    if not part:
        return
    coef = 1
    m = re.match(r"\d+", part)
    if m:
        coef = int(m.group(0))
        part = part[m.end():]
        if not part:
            return
    _parse_group(part, coef, counts)


def _parse_group(part: str, multiplier: int, counts: Dict[str, int]) -> None:
    """递归解析一段化学式（含圆括号），累加到 counts。"""
    i, n = 0, len(part)
    while i < n:
        ch = part[i]
        if ch == "(":
            # 找匹配的右括号
            depth, j = 1, i + 1
            while j < n and depth > 0:
                if part[j] == "(":
                    depth += 1
                elif part[j] == ")":
                    depth -= 1
                j += 1
            inner = part[i + 1 : j - 1]
            # 读取括号后的下标
            m = re.match(r"\d+", part[j:])
            group_mult = int(m.group(0)) if m else 1
            _parse_group(inner, group_mult * multiplier, counts)
            i = j + (m.end() if m else 0)
            continue
        if ch.isalpha() and ch.isupper():
            # 元素符号：大写 + 可选小写
            j = i + 1
            while j < n and part[j].islower():
                j += 1
            sym = part[i:j]
            if sym not in SYMBOL_INDEX:
                raise ValueError(f"未知元素符号：{sym}")
            m = re.match(r"\d+", part[j:])
            num = int(m.group(0)) if m else 1
            counts[sym] = counts.get(sym, 0) + num * multiplier
            i = j + (m.end() if m else 0)
            continue
        if ch.islower():
            raise ValueError(f"化学式格式错误：'{part}' 中的 '{ch}' 前缺少大写元素符号")
        raise ValueError(f"化学式包含无法解析的字符：'{ch}'（位置 {i}）")


def molar_mass_tool(
    formula: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    """计算化学式的摩尔质量、元素占比与组成公式。

    Args:
        formula: 化学式，如 "Fe2O3"、"Ca(OH)2"、"CuSO4·5H2O"。

    Returns:
        含 molar_mass、elements（每元素占比）、formula_breakdown、unit 的字典。
    """
    try:
        elements = parse_formula(formula)
    except ValueError as exc:
        return {"error": f"化学式解析失败：{exc}", "formula": formula}
    total = 0.0
    parts: List[Dict[str, Any]] = []
    for sym, count in elements:
        _, zh, mass = SYMBOL_INDEX[sym]
        contrib = mass * count
        total += contrib
        parts.append({"symbol": sym, "name_zh": zh, "count": count, "mass": mass, "contrib": round(contrib, 4)})
    if total <= 0:
        return {"error": "化学式未包含任何有效元素", "formula": formula}
    for p in parts:
        p["weight_percent"] = round(p["contrib"] / total * 100, 2)
    breakdown = " + ".join(
        f"{p['symbol']}×{p['count']}×{p['mass']}" for p in parts
    )
    return {
        "formula": formula,
        "molar_mass_g_mol": round(total, 4),
        "elements": parts,
        "formula_breakdown": breakdown,
        "unit": "g/mol",
    }


MOLAR_MASS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": "计算化学式摩尔质量、元素占比与组成公式（支持括号与结晶水）。",
    "examples": [{"formula": "Fe2O3"}, {"formula": "Ca(OH)2"}],
    "properties": {
        "formula": {
            "type": "string",
            "description": "化学式，支持括号与结晶水，如 Fe2O3 / Ca(OH)2 / CuSO4·5H2O",
        },
    },
    "required": ["formula"],
    "additionalProperties": False,
}


# ─────────────────────────────────────────────────────────────
# ② 溶液配制计算器
# ─────────────────────────────────────────────────────────────
def solution_prep_tool(
    mode: str,
    molar_mass: Optional[float] = None,
    molarity: Optional[float] = None,
    mass_concentration: Optional[float] = None,
    mass_fraction: Optional[float] = None,
    volume_ml: Optional[float] = None,
    solute_mass_g: Optional[float] = None,
    solvent_volume_ml: Optional[float] = None,
    solution_density: Optional[float] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """溶液配制计算：支持摩尔浓度 / 质量浓度 / 质量分数三种模式。

    Args:
        mode: "molarity"（摩尔浓度）| "mass_conc"（质量浓度）| "mass_fraction"（质量分数）。
        molar_mass: 溶质摩尔质量 g/mol（摩尔浓度模式必需）。
        molarity: 目标摩尔浓度 mol/L。
        mass_concentration: 目标质量浓度 g/L。
        mass_fraction: 目标质量分数（0~1 或 0~100%）。
        volume_ml: 目标溶液体积 mL。
        solute_mass_g: 溶质质量 g（反算模式）。
        solvent_volume_ml: 溶剂体积 mL（质量分数模式用）。
        solution_density: 溶液密度 g/mL（质量分数换算体积用，可选）。

    Returns:
        配制步骤与用量清单。
    """
    try:
        if mode == "molarity":
            if not molar_mass or molar_mass <= 0:
                return {"error": "摩尔浓度模式需要有效的 molar_mass（g/mol）"}
            if not molarity or molarity <= 0 or not volume_ml or volume_ml <= 0:
                return {"error": "摩尔浓度模式需要 molarity（mol/L）与 volume_ml"}
            moles = molarity * volume_ml / 1000
            mass = moles * molar_mass
            return _solution_result(
                mode="摩尔浓度", molar_mass=molar_mass, target=f"{molarity} mol/L",
                volume_ml=volume_ml, solute_mass_g=mass,
                steps=[
                    f"称取 {mass:.4f} g 溶质（摩尔质量 {molar_mass} g/mol，需 {moles:.6f} mol）",
                    f"溶于少量溶剂，转移至 {volume_ml:.0f} mL 容量瓶",
                    "定容至刻度线，摇匀",
                ],
            )
        if mode == "mass_conc":
            if not mass_concentration or mass_concentration <= 0 or not volume_ml or volume_ml <= 0:
                return {"error": "质量浓度模式需要 mass_concentration（g/L）与 volume_ml"}
            mass = mass_concentration * volume_ml / 1000
            return _solution_result(
                mode="质量浓度", molar_mass=molar_mass, target=f"{mass_concentration} g/L",
                volume_ml=volume_ml, solute_mass_g=mass,
                steps=[
                    f"称取 {mass:.4f} g 溶质",
                    f"溶于溶剂并定容至 {volume_ml:.0f} mL",
                ],
            )
        if mode == "mass_fraction":
            if mass_fraction is None or volume_ml is None or volume_ml <= 0:
                return {"error": "质量分数模式需要 mass_fraction（如 0.05 或 5）与 volume_ml"}
            frac = mass_fraction / 100 if mass_fraction > 1 else mass_fraction
            if not 0 < frac < 1:
                return {"error": f"质量分数 {mass_fraction} 无效（应为 0~1 或 0~100%）"}
            density = solution_density or 1.0
            total_mass = density * volume_ml
            solute = total_mass * frac
            solvent = total_mass - solute
            return _solution_result(
                mode="质量分数", molar_mass=molar_mass, target=f"{frac * 100:.2f} %",
                volume_ml=volume_ml, solute_mass_g=solute, solvent_mass_g=solvent,
                steps=[
                    f"称取 {solute:.4f} g 溶质（按密度 {density} g/mL、体积 {volume_ml:.0f} mL 计，溶液总质量 {total_mass:.2f} g）",
                    f"加入 {solvent:.4f} g（约 {solvent / density:.1f} mL）溶剂，搅拌溶解至均匀",
                    "注意：质量分数按质量比，体积为近似值",
                ],
            )
        return {"error": f"未知模式：{mode}（可选 molarity / mass_conc / mass_fraction）"}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"计算失败：{exc}"}


def _solution_result(mode: str, molar_mass: Optional[float], target: str, volume_ml: float,
                     solute_mass_g: float, solvent_mass_g: Optional[float] = None,
                     steps: Optional[List[str]] = None) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "mode": mode,
        "target": target,
        "volume_ml": volume_ml,
        "solute_mass_g": round(solute_mass_g, 4),
        "steps": steps or [],
    }
    if molar_mass:
        result["solute_moles"] = round(solute_mass_g / molar_mass, 6)
    if solvent_mass_g is not None:
        result["solvent_mass_g"] = round(solvent_mass_g, 4)
    return result


SOLUTION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": "溶液配制：摩尔浓度/质量浓度/质量分数三模式，输出溶质用量与步骤。",
    "examples": [{"mode": "molarity", "molar_mass": 58.44, "molarity": 0.5, "volume_ml": 500}],
    "properties": {
        "mode": {"type": "string", "enum": ["molarity", "mass_conc", "mass_fraction"],
                 "description": "配制模式：摩尔浓度 / 质量浓度 / 质量分数"},
        "molar_mass": {"type": "number", "description": "溶质摩尔质量 g/mol（摩尔浓度模式必需，可用摩尔质量工具算）"},
        "molarity": {"type": "number", "description": "目标摩尔浓度 mol/L"},
        "mass_concentration": {"type": "number", "description": "目标质量浓度 g/L"},
        "mass_fraction": {"type": "number", "description": "目标质量分数（0~1 或 0~100）"},
        "volume_ml": {"type": "number", "description": "目标溶液体积 mL"},
        "solute_mass_g": {"type": "number", "description": "溶质质量 g（备用）"},
        "solvent_volume_ml": {"type": "number", "description": "溶剂体积 mL"},
        "solution_density": {"type": "number", "description": "溶液密度 g/mL（质量分数模式换算用，默认 1）"},
    },
    "required": ["mode", "volume_ml"],
    "additionalProperties": False,
}


# ─────────────────────────────────────────────────────────────
# ③ 半导体带隙计算（Tauc plot）
# ─────────────────────────────────────────────────────────────
def _is_transmittance_hint(text: str) -> bool:
    """判断一行/表头是否提示第二列为透射率（%T / T% / T(%) / transmittance / 透射 / 透过）。"""
    h = (text or "").lower()
    if any(k in h for k in ("trans", "透射", "透过")):
        return True
    if "%t" in h or re.search(r"t\s*\(?\s*%", h):
        return True
    return False


def _is_pct_transmittance_hint(text: str) -> bool:
    """表头是否明确标注百分比透射率（%T / T% / T(%) / transmittance(%)）——此时数值一律按百分比解释。

    与 _is_transmittance_hint 的区别：后者只判断「这是透射率」（可能为 0~1 小数），
    前者额外锁定「单位是百分比」。用于 _to_absorbance 消除 %T 数值 <1 时的歧义
    （强吸收区 T<1%，若按 0~1 小数解释会把 A 算错）。
    """
    h = (text or "").lower()
    if "%t" in h:
        return True
    if "%" in h and any(k in h for k in ("trans", "透射", "透过")):
        return True
    return bool(re.search(r"t\s*\(?\s*%", h))


def _load_absorbance_data(path: str) -> Tuple[List[Tuple[float, float]], str]:
    """读取 TXT/CSV 光谱数据（波长 nm, 吸光度或透射率）。

    Args:
        path: 数据文件路径。支持 TXT（空格/逗号/制表符分隔）与 CSV。
              第一列波长(nm)，第二列吸光度（Abs）或透射率（%T / 小数）。

    Returns:
        ([(波长, 吸光度), ...], header_hint)。
        header_hint 为表头/注释行中提取的单位线索（含 %T/transmittance/透射 等），
        供 _to_absorbance 判断是否需要把透射率转为吸光度；无则空字符串。
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"数据文件不存在：{path}")
    rows: List[Tuple[float, float]] = []
    header_hint = ""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith(("#", ";", "//")):
                # 注释行：可能携带单位线索
                if _is_transmittance_hint(line):
                    header_hint = line[:80]
                continue
            parts = re.split(r"[,\t\s]+", line)
            if len(parts) < 2:
                continue
            try:
                x, y = float(parts[0]), float(parts[1])
            except ValueError:
                # 非数据行（无注释符号的表头，如 "wavelength trans"）→ 检查单位线索
                if _is_transmittance_hint(line):
                    header_hint = line[:80]
                continue
            rows.append((x, y))
    if len(rows) < 5:
        raise ValueError(f"有效数据点不足（{len(rows)}），需至少 5 个数据点")
    return sorted(rows), header_hint


def _to_absorbance(y: float, header_hint: str = "") -> float:
    """若输入为透射率（%T 或 0~1 小数）则转为吸光度，否则原样返回。

    %T 明确（表头含 %t / T% / T(%)）时，数值无论大小一律按百分比解释
    A = -log10(T/100)，避免强吸收区 T<1% 被误判为 0~1 小数；单位不明
    （transmittance / 透射 / 透过）时启发式：≤1 视为 0~1 小数，>1 视为百分比。
    """
    if not _is_transmittance_hint(header_hint):
        return y
    if _is_pct_transmittance_hint(header_hint):
        # %T 明确：A = -log10(T/100)，T=0.1% → A=3.0（而非误判为小数）
        return -math.log10(max(y / 100, 1e-6))
    if y <= 1:
        # 0~1 小数透过率：A = -log10(T)
        return -math.log10(max(y, 1e-6))
    if y <= 100:
        # %T 百分比透射率：A = -log10(T/100)
        return -math.log10(max(y / 100, 1e-6))
    return y


def tauc_bandgap_tool(
    file_path: str,
    transition: str = "direct",
    wavelength_unit: str = "nm",
    **kwargs: Any,
) -> Dict[str, Any]:
    """基于 Tauc plot 计算半导体带隙（直接/间接）。

    Args:
        file_path: TXT/CSV 数据文件路径（第一列波长，第二列吸光度或 %T）。
        transition: "direct"（直接带隙，n=1/2）| "indirect"（间接带隙，n=2）。
        wavelength_unit: 波长单位 "nm" 或 "ev"（第二列若为能量 eV）。

    Returns:
        带隙值、拟合信息、线性区间与处理数据摘要。
    """
    try:
        rows, header_hint = _load_absorbance_data(file_path)
    except (FileNotFoundError, ValueError) as exc:
        return {"error": str(exc), "file_path": file_path}
    try:
        import numpy as np  # numpy 为 MatLens 领域依赖
    except ImportError:
        return {"error": "需要 numpy 支持：pip install numpy", "file_path": file_path}

    xs = np.array([r[0] for r in rows], dtype=float)
    ys = np.array([_to_absorbance(r[1], header_hint) for r in rows], dtype=float)
    # 波长 → 光子能量 E = 1240 / λ(nm)
    if wavelength_unit == "nm":
        energy = 1240.0 / xs
    else:
        energy = xs
    # Tauc 转换：(αhν)^(1/n)，n=1/2 直接、n=2 间接（常用简化：(A·hν)^(1/n)）
    n = 0.5 if transition == "direct" else 2.0
    tauc = np.power(np.maximum(ys * energy, 0), 1.0 / n)
    # 取上升段做线性拟合（最大斜率附近 60% 点）
    idx = np.argsort(energy)
    e_sorted, t_sorted = energy[idx], tauc[idx]
    grad = np.gradient(t_sorted, e_sorted)
    peak = int(np.argmax(np.abs(grad)))
    lo = max(0, peak - int(len(e_sorted) * 0.3))
    hi = min(len(e_sorted), peak + int(len(e_sorted) * 0.3))
    if hi - lo < 3:
        lo, hi = 0, len(e_sorted)
    slope, intercept = np.polyfit(e_sorted[lo:hi], t_sorted[lo:hi], 1)
    bandgap = -intercept / slope if slope != 0 else 0.0
    r_sq = _r_squared(e_sorted[lo:hi], t_sorted[lo:hi], slope, intercept)
    return {
        "bandgap_eV": round(float(bandgap), 3),
        "transition": transition,
        "fit": {"slope": round(float(slope), 4), "intercept": round(float(intercept), 4), "r_squared": round(float(r_sq), 4)},
        "linear_fit_range": {"start_eV": round(float(e_sorted[lo]), 3), "end_eV": round(float(e_sorted[hi - 1]), 3)},
        "data_points": len(rows),
        "note": "基于 Tauc plot 简化计算：(A·hν)^(1/n) 对 hν 线性区外推至 x 轴截距",
    }


def _r_squared(x: Any, y: Any, slope: float, intercept: float) -> float:
    """线性拟合 R²。"""
    import numpy as np

    pred = slope * x + intercept
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    return 1 - ss_res / ss_tot if ss_tot > 0 else 0.0


TAUC_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": "基于 Tauc plot 计算半导体直接/间接带隙（导入紫外吸收数据）。",
    "examples": [{"file_path": "abs_spectrum.txt", "transition": "direct"}],
    "properties": {
        "file_path": {"type": "string", "description": "紫外吸收数据文件路径（TXT/CSV：第一列波长 nm，第二列吸光度或 %T）"},
        "transition": {"type": "string", "enum": ["direct", "indirect"], "description": "直接带隙选 direct，间接选 indirect"},
        "wavelength_unit": {"type": "string", "enum": ["nm", "ev"], "description": "第一列波长单位（默认 nm）"},
    },
    "required": ["file_path", "transition"],
    "additionalProperties": False,
}


# ─────────────────────────────────────────────────────────────
# 注册
# ─────────────────────────────────────────────────────────────
def _check_math_available() -> bool:
    return True


registry.register(
    name="molar_mass",
    toolset="matlens_material",
    schema=MOLAR_MASS_SCHEMA,
    handler=lambda args, **kw: tool_result(molar_mass_tool(formula=args.get("formula"))),
    check_fn=_check_math_available,
    description="计算化学式摩尔质量、元素占比与组成公式（支持括号与结晶水，如 Fe2O3、Ca(OH)2）",
    emoji="⚖️",
)

registry.register(
    name="solution_prep",
    toolset="matlens_material",
    schema=SOLUTION_SCHEMA,
    handler=lambda args, **kw: tool_result(solution_prep_tool(**args)),
    check_fn=_check_math_available,
    description="溶液配制计算：摩尔浓度/质量浓度/质量分数三种模式，输出溶质用量与配制步骤",
    emoji="🧪",
)

registry.register(
    name="tauc_bandgap",
    toolset="matlens_material",
    schema=TAUC_SCHEMA,
    handler=lambda args, **kw: tool_result(tauc_bandgap_tool(**args)),
    check_fn=_check_math_available,
    description="基于 Tauc plot 计算半导体直接/间接带隙（导入 TXT/CSV 紫外吸收数据）",
    emoji="⚡",
)


# ─────────────────────────────────────────────────────────────
def energy_convert_tool(
    value: float,
    from_unit: str = "eV",
    to_unit: str = "nm",
    **kwargs: Any,
) -> Dict[str, Any]:
    """光谱能量单位互转（eV / nm / cm⁻¹ / THz / kJ·mol⁻¹）。

    Args:
        value: 数值。
        from_unit: 来源单位：eV / nm / cm-1 / THz / kJ-mol。
        to_unit: 目标单位；缺省传空时同时返回全部单位换算表。

    Returns:
        目标值（result + result_unit）以及全部单位换算表 all_units。
    """
    _ALIAS = {
        "ev": "eV", "nm": "nm", "cm-1": "cm-1", "cm": "cm-1", "cm⁻¹": "cm-1",
        "thz": "THz", "kj-mol": "kJ/mol", "kj/mol": "kJ/mol", "kjmol": "kJ/mol",
        "kj·mol⁻¹": "kJ/mol",
    }

    def _to_ev(v: float, u: str) -> float:
        if u == "eV":
            return v
        if u == "nm":
            return 1240.0 / v
        if u == "cm-1":
            return v / 8065.5
        if u == "THz":
            return v / 241.8
        if u == "kJ/mol":
            return v / 96.485
        raise ValueError(f"未知单位：{u}")

    def _from_ev(e: float, u: str) -> float:
        if u == "eV":
            return e
        if u == "nm":
            return 1240.0 / e
        if u == "cm-1":
            return e * 8065.5
        if u == "THz":
            return e * 241.8
        if u == "kJ/mol":
            return e * 96.485
        raise ValueError(f"未知单位：{u}")

    fu = _ALIAS.get(str(from_unit).strip().lower(), str(from_unit).strip().lower())
    tu = _ALIAS.get(str(to_unit).strip().lower(), str(to_unit).strip().lower())
    if fu == tu:
        return {"error": "from_unit 与 to_unit 相同，无需转换"}
    try:
        ev = _to_ev(float(value), fu)
    except (ValueError, ZeroDivisionError) as exc:
        return {"error": f"转换失败：{exc}（支持 eV / nm / cm-1 / THz / kJ-mol）"}
    all_units = {u: round(_from_ev(ev, u), 6) for u in ("eV", "nm", "cm-1", "THz", "kJ/mol")}
    return {
        "value": value,
        "from": fu,
        "to": tu,
        "result": round(_from_ev(ev, tu), 6),
        "result_unit": tu,
        "all_units": all_units,
        "note": "关系：E(eV)=1240/λ(nm)=ν(cm⁻¹)/8065.5=ν(THz)/241.8=E(kJ/mol)/96.485",
    }


ENERGY_CONVERT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": "光谱能量单位换算 eV↔nm↔cm⁻¹↔THz↔kJ/mol。",
    "examples": [{"value": 2.0, "from_unit": "eV", "to_unit": "nm"}],
    "properties": {
        "value": {"type": "number", "description": "数值"},
        "from_unit": {"type": "string", "description": "来源单位：eV / nm / cm-1 / THz / kJ-mol"},
        "to_unit": {"type": "string", "description": "目标单位（同上）"},
    },
    "required": ["value"],
    "additionalProperties": False,
}


registry.register(
    name="energy_convert",
    toolset="matlens_material",
    schema=ENERGY_CONVERT_SCHEMA,
    handler=lambda args, **kw: tool_result(energy_convert_tool(**args)),
    check_fn=_check_math_available,
    description="光谱能量单位换算：eV↔nm↔cm⁻¹↔THz↔kJ/mol（带隙/光电子能谱常用）",
    emoji="🌡️",
)



# ═══════════════════════════════════════════════════════════════
# 通用单位换算（温度/压力/长度/质量/体积）
# ═══════════════════════════════════════════════════════════════

_UNIT_TABLE = {
    "temperature": {
        "base": "K",
        "units": {
            "K": {"to_base": lambda v: v, "from_base": lambda v: v},
            "C": {"to_base": lambda v: v + 273.15, "from_base": lambda v: v - 273.15},
            "°C": {"to_base": lambda v: v + 273.15, "from_base": lambda v: v - 273.15},
            "celsius": {"to_base": lambda v: v + 273.15, "from_base": lambda v: v - 273.15},
            "F": {"to_base": lambda v: (v - 32) * 5 / 9 + 273.15, "from_base": lambda v: (v - 273.15) * 9 / 5 + 32},
            "°F": {"to_base": lambda v: (v - 32) * 5 / 9 + 273.15, "from_base": lambda v: (v - 273.15) * 9 / 5 + 32},
            "fahrenheit": {"to_base": lambda v: (v - 32) * 5 / 9 + 273.15, "from_base": lambda v: (v - 273.15) * 9 / 5 + 32},
        },
    },
    "pressure": {
        "base": "Pa",
        "units": {
            "Pa": 1.0,
            "kPa": 1e3,
            "MPa": 1e6,
            "GPa": 1e9,
            "bar": 1e5,
            "mbar": 100.0,
            "atm": 101325.0,
            "mmHg": 133.322,
            "torr": 133.322,
            "psi": 6894.76,
        },
    },
    "length": {
        "base": "m",
        "units": {
            "m": 1.0,
            "dm": 0.1,
            "cm": 0.01,
            "mm": 1e-3,
            "um": 1e-6,
            "μm": 1e-6,
            "nm": 1e-9,
            "pm": 1e-12,
            "A": 1e-10,
            "Å": 1e-10,
            "angstrom": 1e-10,
            "inch": 0.0254,
            "ft": 0.3048,
        },
    },
    "mass": {
        "base": "kg",
        "units": {
            "kg": 1.0,
            "g": 1e-3,
            "mg": 1e-6,
            "ug": 1e-9,
            "μg": 1e-9,
            "t": 1000.0,
            "lb": 0.453592,
            "oz": 0.0283495,
        },
    },
    "volume": {
        "base": "m3",
        "units": {
            "m3": 1.0,
            "m³": 1.0,
            "L": 1e-3,
            "l": 1e-3,
            "mL": 1e-6,
            "ml": 1e-6,
            "uL": 1e-9,
            "μL": 1e-9,
            "cm3": 1e-6,
            "cm³": 1e-6,
            "cc": 1e-6,
            "gal": 0.00378541,
        },
    },
}


def unit_convert_tool(
    value: float,
    from_unit: str,
    to_unit: str,
    category: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """通用单位换算。

    Args:
        value: 数值。
        from_unit: 来源单位（如 K、°C、MPa、nm、g、mL）。
        to_unit: 目标单位。
        category: 类别（temperature/pressure/length/mass/volume），可选；不填时自动匹配。

    Returns:
        换算结果 + 同类别全部单位换算表。
    """
    fu = from_unit.strip()
    tu = to_unit.strip()

    # 自动匹配类别
    cat = category.strip().lower()
    if not cat:
        for cname, cdata in _UNIT_TABLE.items():
            units = cdata["units"]
            if fu in units and tu in units:
                cat = cname
                break
        if not cat:
            return {"error": f"无法识别单位组合：{fu} → {tu}，请指定 category"}

    if cat not in _UNIT_TABLE:
        return {"error": f"未知类别：{cat}，支持：{list(_UNIT_TABLE.keys())}"}

    cdata = _UNIT_TABLE[cat]
    units = cdata["units"]

    if fu not in units or tu not in units:
        return {"error": f"类别 {cat} 不支持单位 {fu} 或 {tu}，支持：{list(units.keys())}"}

    # 温度需要特殊处理（非线性）
    if cat == "temperature":
        base_val = units[fu]["to_base"](value)
        result = units[tu]["from_base"](base_val)
        all_units = {u: round(units[u]["from_base"](base_val), 6) for u in ["K", "°C", "°F"]}
    else:
        factor_from = units[fu] if isinstance(units[fu], (int, float)) else units[fu].get("factor", 1)
        factor_to = units[tu] if isinstance(units[tu], (int, float)) else units[tu].get("factor", 1)
        base_val = value * factor_from
        result = base_val / factor_to
        all_units = {u: round(base_val / (units[u] if isinstance(units[u], (int, float)) else 1), 6)
                     for u in units if isinstance(units[u], (int, float))}

    return {
        "input": value,
        "from_unit": fu,
        "to_unit": tu,
        "category": cat,
        "result": round(result, 8),
        "result_str": f"{value} {fu} = {round(result, 6)} {tu}",
        "all_units": all_units,
    }


UNIT_CONVERT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": "通用单位换算：温度/压力/长度/质量/体积。",
    "examples": [{"value": 25, "from_unit": "°C", "to_unit": "K", "category": "temperature"}],
    "properties": {
        "value": {"type": "number", "description": "数值"},
        "from_unit": {"type": "string", "description": "来源单位，如 K/°C/MPa/nm/g/mL"},
        "to_unit": {"type": "string", "description": "目标单位"},
        "category": {"type": "string", "description": "类别：temperature/pressure/length/mass/volume（可选，自动匹配）"},
    },
    "required": ["value", "from_unit", "to_unit"],
    "additionalProperties": False,
}


registry.register(
    name="unit_convert",
    toolset="matlens_material",
    schema=UNIT_CONVERT_SCHEMA,
    handler=lambda args, **kw: tool_result(unit_convert_tool(**args)),
    check_fn=_check_math_available,
    description="通用单位换算：温度(K/°C/°F)、压力(Pa/kPa/MPa/atm/bar/mmHg)、长度(m/cm/mm/μm/nm/Å)、质量(kg/g/mg)、体积(L/mL/m³)",
    emoji="🔄",
)



# ═══════════════════════════════════════════════════════════════
# 化学方程式配平
# ═══════════════════════════════════════════════════════════════

import re as _re


def _parse_formula(formula: str) -> dict:
    """解析化学式，返回元素计数。如 H2O -> {'H':2, 'O':1}，Ca(OH)2 -> {'Ca':1,'O':2,'H':2}"""
    counts = {}
    # 处理括号
    formula = formula.strip()
    # 展开括号：(OH)2 -> O2H2
    while '(' in formula:
        m = _re.search(r'\(([^()]*)\)(\d*)', formula)
        if not m:
            break
        inner, mult = m.group(1), int(m.group(2) or '1')
        expanded = ''
        for em in _re.finditer(r'([A-Z][a-z]?)(\d*)', inner):
            expanded += em.group(1) + str(int(em.group(2) or '1') * mult)
        formula = formula[:m.start()] + expanded + formula[m.end():]
    # 解析元素
    for em in _re.finditer(r'([A-Z][a-z]?)(\d*)', formula):
        elem, num = em.group(1), int(em.group(2) or '1')
        counts[elem] = counts.get(elem, 0) + num
    return counts


def balance_equation_tool(equation: str, **kwargs: Any) -> Dict[str, Any]:
    """化学方程式配平。

    Args:
        equation: 化学方程式，如 "H2 + O2 -> H2O" 或 "Fe + O2 = Fe2O3"

    Returns:
        配平后的方程式、各物质系数、元素守恒验证。
    """
    eq = equation.strip()
    # 统一分隔符
    eq = eq.replace('=', '->').replace('→', '->').replace('-->', '->')
    parts = eq.split('->')
    if len(parts) != 2:
        return {"error": f"无法解析方程式：{equation}，请使用 A + B -> C 格式"}

    def _split_side(side: str):
        items = [s.strip() for s in side.split('+') if s.strip()]
        return items

    reactants = _split_side(parts[0])
    products = _split_side(parts[1])
    if not reactants or not products:
        return {"error": "反应物或生成物为空"}

    all_species = reactants + products
    n_species = len(all_species)

    # 收集所有元素
    all_elements = set()
    species_counts = []
    for sp in all_species:
        # 去掉前导系数（用户可能已写了系数）
        m = _re.match(r'^(\d*)(.+)$', sp)
        coeff, formula = int(m.group(1) or '1'), m.group(2).strip()
        cnt = _parse_formula(formula)
        species_counts.append(cnt)
        all_elements.update(cnt.keys())

    elements = sorted(all_elements)
    n_elem = len(elements)

    # 建立矩阵：每行一个元素，每列一个物质，值为该物质中该元素的原子数
    # 反应物为正，生成物为负（守恒：sum(reactant) - sum(product) = 0）
    matrix = []
    for elem in elements:
        row = []
        for i, cnt in enumerate(species_counts):
            val = cnt.get(elem, 0)
            if i >= len(reactants):
                val = -val  # 生成物取负
            row.append(val)
        matrix.append(row)

    # 用高斯消元求零空间（配平系数）
    # 尝试最后一个物质系数为 1，求解前 n-1 个
    # 矩阵：A * x = 0，其中 x 是系数向量
    # 固定 x[-1] = 1，解 A[:, :-1] * x[:-1] = -A[:, -1]
    try:
        import fractions
        # 用分数精确计算
        A = [[fractions.Fraction(matrix[i][j]) for j in range(n_species - 1)] for i in range(n_elem)]
        b = [fractions.Fraction(-matrix[i][-1]) for i in range(n_elem)]

        # 高斯消元
        n_rows = len(A)
        n_cols = n_species - 1
        pivot_row = 0
        for col in range(n_cols):
            # 找主元
            found = -1
            for r in range(pivot_row, n_rows):
                if A[r][col] != 0:
                    found = r
                    break
            if found == -1:
                continue
            A[pivot_row], A[found] = A[found], A[pivot_row]
            b[pivot_row], b[found] = b[found], b[pivot_row]
            # 消元
            for r in range(n_rows):
                if r != pivot_row and A[r][col] != 0:
                    factor = A[r][col] / A[pivot_row][col]
                    for c in range(col, n_cols):
                        A[r][c] -= factor * A[pivot_row][c]
                    b[r] -= factor * b[pivot_row]
            pivot_row += 1

        # 回代求解
        coeffs = [fractions.Fraction(0)] * n_cols
        for r in range(min(pivot_row, n_rows)):
            for c in range(n_cols):
                if A[r][c] != 0:
                    coeffs[c] = b[r] / A[r][c]
                    break
        coeffs.append(fractions.Fraction(1))  # 最后一个系数固定为 1

        # 找最小公倍数，转为整数
        from math import gcd
        from functools import reduce
        def lcm(a, b):
            return a * b // gcd(a, b)
        denoms = [c.denominator for c in coeffs if c != 0]
        if denoms:
            L = reduce(lcm, denoms)
            int_coeffs = [int(c * L) for c in coeffs]
        else:
            int_coeffs = [int(c) for c in coeffs]

        # 确保系数为正
        if any(c < 0 for c in int_coeffs):
            int_coeffs = [-c for c in int_coeffs]

        # 约简
        g = reduce(gcd, [abs(c) for c in int_coeffs if c != 0])
        if g > 1:
            int_coeffs = [c // g for c in int_coeffs]

    except Exception as e:
        return {"error": f"配平失败：{e}"}

    # 构造配平后的方程式
    def _format(sp, coeff):
        m = _re.match(r'^(\d*)(.+)$', sp)
        formula = m.group(2).strip()
        return (str(coeff) if coeff > 1 else '') + formula

    balanced_reactants = ' + '.join(_format(reactants[i], int_coeffs[i]) for i in range(len(reactants)))
    balanced_products = ' + '.join(_format(products[i], int_coeffs[len(reactants) + i]) for i in range(len(products)))
    balanced_eq = balanced_reactants + ' -> ' + balanced_products

    # 验证元素守恒
    verification = {}
    for elem in elements:
        left = sum(int_coeffs[i] * species_counts[i].get(elem, 0) for i in range(len(reactants)))
        right = sum(int_coeffs[len(reactants) + i] * species_counts[len(reactants) + i].get(elem, 0) for i in range(len(products)))
        verification[elem] = {"reactants": left, "products": right, "balanced": left == right}

    return {
        "input": equation,
        "balanced_equation": balanced_eq,
        "coefficients": {all_species[i]: int_coeffs[i] for i in range(n_species)},
        "element_balance": verification,
        "all_balanced": all(v["balanced"] for v in verification.values()),
    }


BALANCE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": "化学方程式配平，输出系数与元素守恒验证。",
    "examples": [{"equation": "H2 + O2 -> H2O"}],
    "properties": {
        "equation": {"type": "string", "description": "化学方程式，如 H2 + O2 -> H2O 或 Fe + O2 = Fe2O3"},
    },
    "required": ["equation"],
    "additionalProperties": False,
}


registry.register(
    name="balance_equation",
    toolset="matlens_material",
    schema=BALANCE_SCHEMA,
    handler=lambda args, **kw: tool_result(balance_equation_tool(equation=args.get("equation", ""))),
    check_fn=_check_math_available,
    description="化学方程式配平：输入未配平方程式（如 H2 + O2 -> H2O），输出配平系数与元素守恒验证",
    emoji="⚗️",
)



# ═══════════════════════════════════════════════════════════════
# 数据自动拟合（线性/高斯峰/Tauc带隙）
# ═══════════════════════════════════════════════════════════════

def data_fit_tool(
    x: list,
    y: list,
    fit_type: str = "linear",
    **kwargs: Any,
) -> Dict[str, Any]:
    """数据自动拟合。

    Args:
        x: x 数据列表。
        y: y 数据列表。
        fit_type: 拟合类型：linear（线性）、gaussian（高斯峰）、tauc（Tauc带隙）。

    Returns:
        拟合参数、R²、拟合曲线数据点。
    """
    try:
        import numpy as np
        from scipy.optimize import curve_fit
    except ImportError:
        return {"error": "需要 numpy 和 scipy 支持"}

    if len(x) != len(y) or len(x) < 2:
        return {"error": f"数据长度不匹配或不足：x={len(x)}, y={len(y)}"}

    xa = np.array(x, dtype=float)
    ya = np.array(y, dtype=float)

    if fit_type == "linear":
        # 线性拟合 y = ax + b
        coeffs = np.polyfit(xa, ya, 1)
        a, b = coeffs[0], coeffs[1]
        y_fit = a * xa + b
        ss_res = np.sum((ya - y_fit) ** 2)
        ss_tot = np.sum((ya - np.mean(ya)) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 1.0
        # 生成拟合曲线（更密的采样）
        x_dense = np.linspace(xa.min(), xa.max(), 100)
        y_dense = a * x_dense + b
        return {
            "fit_type": "linear",
            "equation": f"y = {a:.6g} * x + {b:.6g}",
            "slope": float(a),
            "intercept": float(b),
            "r_squared": round(float(r2), 6),
            "fit_curve": {"x": x_dense.tolist(), "y": y_dense.tolist()},
            "residuals": (ya - y_fit).tolist(),
        }

    elif fit_type == "gaussian":
        # 高斯峰拟合 y = A * exp(-(x-μ)²/(2σ²)) + y0
        def gauss(x, A, mu, sigma, y0):
            return A * np.exp(-(x - mu) ** 2 / (2 * sigma ** 2)) + y0
        # 初始猜测
        A0 = ya.max() - ya.min()
        mu0 = xa[np.argmax(ya)]
        sigma0 = (xa.max() - xa.min()) / 6
        y0_0 = ya.min()
        try:
            popt, _ = curve_fit(gauss, xa, ya, p0=[A0, mu0, sigma0, y0_0], maxfev=10000)
            A, mu, sigma, y0 = popt
            y_fit = gauss(xa, *popt)
            ss_res = np.sum((ya - y_fit) ** 2)
            ss_tot = np.sum((ya - np.mean(ya)) ** 2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 1.0
            fwhm = 2 * np.sqrt(2 * np.log(2)) * abs(sigma)
            x_dense = np.linspace(xa.min(), xa.max(), 200)
            y_dense = gauss(x_dense, *popt)
            return {
                "fit_type": "gaussian",
                "amplitude": round(float(A), 6),
                "center": round(float(mu), 6),
                "sigma": round(float(sigma), 6),
                "fwhm": round(float(fwhm), 6),
                "baseline": round(float(y0), 6),
                "r_squared": round(float(r2), 6),
                "fit_curve": {"x": x_dense.tolist(), "y": y_dense.tolist()},
            }
        except Exception as e:
            return {"error": f"高斯拟合失败：{e}"}

    elif fit_type == "tauc":
        # Tauc 带隙拟合：在 (αhν)^n vs hν 曲线中找吸收边的线性区，外推到 y=0
        # 假设输入 x = 能量 (eV), y = (αhν)^n
        if len(xa) < 5:
            return {"error": "Tauc 拟合需要至少 5 个数据点"}
        ymax = ya.max()
        if ymax <= 0:
            return {"error": "y 值全为 0，无法拟合"}
        # 找吸收边区域：y 在峰值的 10% 到 60% 之间
        # 这是 Tauc plot 中通常最接近线性的部分
        mask = (ya >= ymax * 0.1) & (ya <= ymax * 0.6)
        if mask.sum() < 3:
            # 退而求其次：y > 峰值 5% 的区域
            mask = ya > ymax * 0.05
        if mask.sum() < 3:
            return {"error": "未找到明显的吸收边"}
        x_edge = xa[mask]
        y_edge = ya[mask]
        # 滑动窗口找最线性的一段
        best_r2 = -1
        best_coeffs = None
        best_range = None
        window = max(3, min(len(x_edge), len(x_edge) // 2 + 2))
        for s in range(len(x_edge) - window + 1):
            xw = x_edge[s:s + window]
            yw = y_edge[s:s + window]
            coeffs = np.polyfit(xw, yw, 1)
            y_fit = coeffs[0] * xw + coeffs[1]
            ss_res = np.sum((yw - y_fit) ** 2)
            ss_tot = np.sum((yw - np.mean(yw)) ** 2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 1.0
            if r2 > best_r2:
                best_r2 = r2
                best_coeffs = coeffs
                best_range = (s, s + window)
        if best_coeffs is None:
            return {"error": "Tauc 拟合失败"}
        a, b = best_coeffs
        bandgap = -b / a if a != 0 else None
        x_dense = np.linspace(min(x_edge.min(), bandgap or x_edge.min()), max(x_edge.max(), bandgap or x_edge.max()), 100)
        y_dense = a * x_dense + b
        return {
            "fit_type": "tauc",
            "bandgap_eV": round(float(bandgap), 4) if bandgap else None,
            "linear_region": {
                "x_start": round(float(x_edge[best_range[0]]), 4),
                "x_end": round(float(x_edge[best_range[1] - 1]), 4),
                "y_range": f"{ymax*0.1:.1f}% - {ymax*0.6:.1f}% of peak",
            },
            "slope": round(float(a), 6),
            "intercept": round(float(b), 6),
            "r_squared": round(float(best_r2), 6),
            "fit_curve": {"x": x_dense.tolist(), "y": y_dense.tolist()},
            "note": "带隙 = 拟合直线与 x 轴交点 (y=0)；在吸收边 10%-60% 峰值区域自动找最线性段",
        }

    else:
        return {"error": f"未知拟合类型：{fit_type}，支持：linear/gaussian/tauc"}


DATA_FIT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": "数据自动拟合：线性/高斯峰/Tauc 带隙。",
    "examples": [{"x": [1, 2, 3, 4, 5], "y": [2, 4, 5, 4, 2], "fit_type": "linear"}],
    "properties": {
        "x": {"type": "array", "items": {"type": "number"}, "description": "x 数据列表"},
        "y": {"type": "array", "items": {"type": "number"}, "description": "y 数据列表"},
        "fit_type": {"type": "string", "description": "拟合类型：linear/gaussian/tauc", "default": "linear"},
    },
    "required": ["x", "y"],
    "additionalProperties": False,
}


registry.register(
    name="data_fit",
    toolset="matlens_material",
    schema=DATA_FIT_SCHEMA,
    handler=lambda args, **kw: tool_result(data_fit_tool(**args)),
    check_fn=_check_math_available,
    description="数据自动拟合：线性拟合、高斯峰拟合（XRD/光谱峰位/FWHM）、Tauc带隙拟合（自动找吸收边线性区）",
    emoji="📈",
)



# ═══════════════════════════════════════════════════════════════
# 晶体结构解析（pymatgen）
# ═══════════════════════════════════════════════════════════════

def crystal_structure_tool(
    formula: str,
    structure_type: str = "auto",
    lattice_constant: float = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """晶体结构解析与计算。

    Args:
        formula: 化学式，如 NaCl、TiO2、CaTiO3
        structure_type: 结构类型：auto/nacl/cscl/zincblende/diamond/fcc/bcc/hcp/perovskite/rutile
        lattice_constant: 晶格常数 (Å)，不填则用离子半径估算

    Returns:
        晶格参数、理论密度、配位数、原子位置、结构信息。
    """
    try:
        from pymatgen.core import Structure, Lattice, Composition
        from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    except ImportError:
        return {"error": "需要 pymatgen 支持，请运行 pip install pymatgen"}

    try:
        comp = Composition(formula)
    except Exception as e:
        return {"error": f"无法解析化学式 {formula}：{e}"}

    stype = (structure_type or "auto").lower()

    # 自动判断结构类型
    if stype == "auto":
        n_elems = len(comp.elements)
        if n_elems == 1:
            stype = "fcc"
        elif n_elems == 2:
            # 简单二元默认 NaCl
            stype = "nacl"
        elif n_elems == 3:
            # 三元 ABO3 默认钙钛矿
            if comp.num_atoms == 5:  # ABO3
                stype = "perovskite"
            else:
                stype = "nacl"
        else:
            stype = "fcc"

    # 估算晶格常数（如果未提供）
    if lattice_constant is None:
        # 简单估算：用元素半径之和
        try:
            from pymatgen.core import Element
            radii = []
            for el in comp.elements:
                try:
                    r = el.atomic_radius or 1.5
                    radii.append(float(r))
                except Exception:
                    radii.append(1.5)
            if stype in ("nacl", "fcc", "zincblende", "diamond", "rocksalt"):
                lattice_constant = 2 * (max(radii) + min(radii)) if len(radii) > 1 else 4 * max(radii) / (2 ** 0.5)
            elif stype in ("cscl", "bcc"):
                lattice_constant = 2 * (max(radii) + min(radii)) / (3 ** 0.5) if len(radii) > 1 else 4 * max(radii) / (3 ** 0.5)
            elif stype == "hcp":
                lattice_constant = 2 * max(radii)
            elif stype == "perovskite":
                lattice_constant = 2 * (max(radii) + min(radii))
            else:
                lattice_constant = 4.0
        except Exception:
            lattice_constant = 4.0

    a = lattice_constant
    structure = None

    try:
        if stype in ("nacl", "rocksalt"):
            # NaCl 惯用晶胞：4 个阳离子 + 4 个阴离子 = 8 原子
            elems = list(comp.elements)
            if len(elems) >= 2:
                cation, anion = elems[0], elems[1]
                species = [cation]*4 + [anion]*4
                coords = [[0,0,0],[0.5,0.5,0],[0.5,0,0.5],[0,0.5,0.5],
                          [0.5,0.5,0.5],[0,0,0.5],[0,0.5,0],[0.5,0,0]]
                lattice = Lattice.cubic(a)
                structure = Structure(lattice, species, coords)
        elif stype == "cscl":
            # CsCl 惯用晶胞：2 原子（简单立方）
            elems = list(comp.elements)
            if len(elems) >= 2:
                species = [elems[0], elems[1]]
                coords = [[0, 0, 0], [0.5, 0.5, 0.5]]
                lattice = Lattice.cubic(a)
                structure = Structure(lattice, species, coords)
        elif stype in ("zincblende", "zns"):
            # 闪锌矿惯用晶胞：8 原子（FCC 格子 + 内部 4 个）
            elems = list(comp.elements)
            if len(elems) >= 2:
                cation, anion = elems[0], elems[1]
                species = [cation]*4 + [anion]*4
                coords = [[0,0,0],[0.5,0.5,0],[0.5,0,0.5],[0,0.5,0.5],
                          [0.25,0.25,0.25],[0.75,0.75,0.25],[0.75,0.25,0.75],[0.25,0.75,0.75]]
                lattice = Lattice.cubic(a)
                structure = Structure(lattice, species, coords)
        elif stype == "diamond":
            # 金刚石惯用晶胞：8 原子
            elem = list(comp.elements)[0]
            species = [elem]*8
            coords = [[0,0,0],[0.5,0.5,0],[0.5,0,0.5],[0,0.5,0.5],
                      [0.25,0.25,0.25],[0.75,0.75,0.25],[0.75,0.25,0.75],[0.25,0.75,0.75]]
            lattice = Lattice.cubic(a)
            structure = Structure(lattice, species, coords)
        elif stype == "fcc":
            # FCC 惯用晶胞：4 原子
            elem = list(comp.elements)[0]
            species = [elem]*4
            coords = [[0,0,0],[0.5,0.5,0],[0.5,0,0.5],[0,0.5,0.5]]
            lattice = Lattice.cubic(a)
            structure = Structure(lattice, species, coords)
        elif stype == "bcc":
            # BCC 惯用晶胞：2 原子
            elem = list(comp.elements)[0]
            species = [elem, elem]
            coords = [[0, 0, 0], [0.5, 0.5, 0.5]]
            lattice = Lattice.cubic(a)
            structure = Structure(lattice, species, coords)
        elif stype == "hcp":
            # HCP 惯用晶胞：2 原子
            elem = list(comp.elements)[0]
            c = a * 1.633
            species = [elem, elem]
            coords = [[0, 0, 0], [1/3, 2/3, 0.5]]
            lattice = Lattice.hexagonal(a, c)
            structure = Structure(lattice, species, coords)
        elif stype == "perovskite":
            # ABO3 钙钛矿惯用晶胞：5 原子
            elems = list(comp.elements)
            if len(elems) >= 3:
                A, B, O = elems[0], elems[1], elems[2]
                species = [A, B, O, O, O]
                coords = [[0,0,0],[0.5,0.5,0.5],[0.5,0.5,0],[0.5,0,0.5],[0,0.5,0.5]]
                lattice = Lattice.cubic(a)
                structure = Structure(lattice, species, coords)
        elif stype == "rutile":
            # TiO2 金红石惯用晶胞：6 原子（2 阳离子 + 4 阴离子）
            elems = list(comp.elements)
            if len(elems) >= 2:
                cation, anion = elems[0], elems[1]
                c = a * 0.644
                species = [cation, cation, anion, anion, anion, anion]
                coords = [[0,0,0],[0.5,0.5,0.5],
                          [0.3,0.3,0],[0.7,0.7,0],[0.2,0.8,0.5],[0.8,0.2,0.5]]
                lattice = Lattice.tetragonal(a, c)
                structure = Structure(lattice, species, coords)
        else:
            return {"error": f"未知结构类型：{stype}，支持：nacl/cscl/zincblende/diamond/fcc/bcc/hcp/perovskite/rutile"}
    except Exception as e:
        return {"error": f"结构生成失败：{e}"}

    if structure is None:
        return {"error": "无法生成结构"}

    # 计算性质
    try:
        volume = structure.volume  # Å³
        density = structure.density  # g/cm³
        n_sites = structure.num_sites
        formula_reduced = structure.composition.reduced_formula

        # 空间群分析
        try:
            sga = SpacegroupAnalyzer(structure)
            spacegroup = sga.get_space_group_symbol()
            spacegroup_number = sga.get_space_group_number()
        except Exception:
            spacegroup = "N/A"
            spacegroup_number = None

        # 配位数（简化：最近邻分析）
        try:
            from pymatgen.analysis.local_env import VoronoiNN
            vnn = VoronoiNN()
            cn_info = {}
            for i, site in enumerate(structure):
                elem = str(site.specie)
                try:
                    cn = vnn.get_cn(structure, i)
                    if elem not in cn_info:
                        cn_info[elem] = cn
                except Exception:
                    pass
        except Exception:
            cn_info = {}

        # 原子位置
        sites_info = []
        for site in structure:
            sites_info.append({
                "element": str(site.specie),
                "frac_coords": [round(c, 4) for c in site.frac_coords],
            })

        return {
            "formula": formula,
            "reduced_formula": formula_reduced,
            "structure_type": stype,
            "lattice": {
                "a": round(a, 4),
                "b": round(structure.lattice.b, 4),
                "c": round(structure.lattice.c, 4),
                "alpha": round(structure.lattice.alpha, 2),
                "beta": round(structure.lattice.beta, 2),
                "gamma": round(structure.lattice.gamma, 2),
                "volume_A3": round(volume, 4),
            },
            "density_g_cm3": round(float(density), 4),
            "n_atoms_per_cell": n_sites,
            "spacegroup": spacegroup,
            "spacegroup_number": spacegroup_number,
            "coordination_numbers": cn_info,
            "sites": sites_info[:10],  # 最多显示 10 个位置
            "note": "晶格常数为估算值，实际值需实验测定；结构为理想原型",
        }
    except Exception as e:
        return {"error": f"性质计算失败：{e}"}


CRYSTAL_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": "晶体结构解析：晶格参数、理论密度、空间群、配位数。",
    "examples": [{"formula": "NaCl", "structure_type": "nacl"}],
    "properties": {
        "formula": {"type": "string", "description": "化学式，如 NaCl、TiO2、CaTiO3"},
        "structure_type": {"type": "string", "description": "结构类型：auto/nacl/cscl/zincblende/diamond/fcc/bcc/hcp/perovskite/rutile", "default": "auto"},
        "lattice_constant": {"type": "number", "description": "晶格常数 a (Å)，可选，不填则估算"},
    },
    "required": ["formula"],
    "additionalProperties": False,
}


registry.register(
    name="crystal_structure",
    toolset="matlens_material",
    schema=CRYSTAL_SCHEMA,
    handler=lambda args, **kw: tool_result(crystal_structure_tool(**args)),
    check_fn=_check_math_available,
    description="晶体结构解析：输入化学式+结构类型，生成晶体结构并计算晶格参数、理论密度、空间群、配位数、原子位置",
    emoji="🔷",
)
