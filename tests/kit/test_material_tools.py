# -*- coding: utf-8 -*-
"""matlens_kit 材料工具包 happy-path 单测（S3 新增）。

覆盖 matlens_material toolset 下全部工具：
- 每个工具至少一次 registry.dispatch 调用，断言返回合法 JSON 且为 dict；
- 旗舰工具 il_viscosity_predict 额外断言 eta 数值、feature_importance、
  plot_b64 以 ``data:image/png;base64,`` 开头；
- experiment_plot 断言 plot_b64 为 base64 PNG（不写临时图片文件）。

不依赖网络、不读写 ~/.matlens 真目录；文件类工具用 pytest tmp_path。
"""
from __future__ import annotations

import json

import numpy as np
import pytest

# 导入即触发全部 matlens_kit 工具注册（含旗舰模型一次性训练）
from matlens_kit.tools import material_kit  # noqa: F401
from tools.registry import registry


def _run(name: str, args: dict) -> dict:
    """经 registry.dispatch 调用工具，返回解析后的 dict；断言合法 JSON。"""
    raw = registry.dispatch(name, args)
    assert isinstance(raw, str), f"{name} 未返回 JSON 字符串: {type(raw)}"
    obj = json.loads(raw)
    assert isinstance(obj, dict), f"{name} 返回非 dict: {type(obj)}"
    return obj


# ── 内联入参 happy-path ───────────────────────────────────────────
INLINE_CASES = {
    "molar_mass": ({"formula": "Fe2O3"}, "molar_mass_g_mol"),
    "solution_prep": ({"mode": "molarity", "molar_mass": 58.44,
                       "molarity": 0.5, "volume_ml": 500}, "solute_mass_g"),
    "energy_convert": ({"value": 2.0, "from_unit": "eV", "to_unit": "nm"}, "result"),
    "unit_convert": ({"value": 25, "from_unit": "°C", "to_unit": "K",
                      "category": "temperature"}, "result"),
    "balance_equation": ({"equation": "H2 + O2 -> H2O"}, "balanced_equation"),
    "data_fit": ({"x": [1, 2, 3, 4, 5], "y": [2, 4, 5, 4, 2],
                  "fit_type": "linear"}, "fit_type"),
    "battery_capacity": ({"formula": "LiFePO4", "n": 1}, "theoretical_capacity_mAh_g"),
    "thermo_gibbs": ({"delta_h": -92.3, "delta_s": -198.7,
                      "temperature_c": 25}, "delta_g_kJ_mol"),
    "lever_rule": ({"composition": 0.4, "phase1": 0.1, "phase2": 0.8},
                   "phase1_mass_fraction"),
    "experiment_protocol": ({"goal": "制备 TiO2 纳米颗粒",
                            "template": "hydrothermal"}, "reagents"),
    "lab_notebook_template": ({"scenario": "synthesis"}, "markdown"),
    "chemical_safety": ({"reagent": "氢氟酸"}, "hazards"),
    "xrd_dspacing": ({"value": 28.4, "mode": "twotheta_to_d", "target": "Cu"},
                      "d_spacing_A"),
    "citation_format": ({"style": "ieee", "authors": "Zhang, W", "year": "2024",
                        "title": "T", "journal": "J", "volume": "1",
                        "pages": "1-2"}, "citation"),
    "experiment_writing": ({"scenario": "synthesis"}, "tips"),
}


@pytest.mark.parametrize("name,args,expected_key",
                         [(n, a, k) for n, (a, k) in INLINE_CASES.items()])
def test_inline_tools_happy_path(name, args, expected_key):
    obj = _run(name, args)
    assert "error" not in obj, f"{name} 意外报错: {obj.get('error')}"
    assert expected_key in obj, f"{name} 缺少预期字段 {expected_key}: {list(obj)}"


# ── 文件类工具（tmp_path，≥6 数据点）──────────────────────────────
def _write_xy(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        f.write("# comment header\n")
        for x, y in rows:
            f.write(f"{x} {y}\n")


def test_tauc_bandgap(tmp_path):
    p = tmp_path / "abs.txt"
    _write_xy(p, [(300, 0.1), (350, 0.2), (400, 0.4), (450, 0.8),
                  (500, 1.5), (550, 2.6), (600, 3.0)])
    obj = _run("tauc_bandgap", {"file_path": str(p), "transition": "direct"})
    assert "error" not in obj, f"tauc_bandgap 报错: {obj.get('error')}"


def test_xrd_preprocess(tmp_path):
    # 真实 XRD 含数百点；此处造一条 40 点带峰曲线，避免触发平滑窗口边界。
    rows = []
    for i in range(40):
        x = 10.0 + i * 1.0
        y = 100 + 800 * float(np.exp(-((x - 30.0) ** 2) / 4.0)) \
            + 200 * float(np.exp(-((x - 45.0) ** 2) / 3.0))
        rows.append((round(x, 2), round(y, 2)))
    p = tmp_path / "xrd.txt"
    _write_xy(p, rows)
    obj = _run("xrd_preprocess", {"file_path": str(p)})
    assert "error" not in obj, f"xrd_preprocess 报错: {obj.get('error')}"


def test_data_normalize(tmp_path):
    p = tmp_path / "spec.txt"
    _write_xy(p, [(1, 10), (2, 20), (3, 35), (4, 30), (5, 15), (6, 5)])
    obj = _run("data_normalize", {"file_path": str(p), "method": "minmax"})
    assert "error" not in obj, f"data_normalize 报错: {obj.get('error')}"
    assert "preview" in obj


# ── experiment_plot：base64 PNG，不落盘 ───────────────────────────
def test_experiment_plot_returns_base64():
    obj = _run("experiment_plot",
               {"x": [1, 2, 3, 4], "y": [1, 4, 9, 16], "plot_type": "xy"})
    assert "error" not in obj, f"experiment_plot 报错: {obj.get('error')}"
    b64 = obj.get("plot_b64", "")
    assert b64.startswith("data:image/png;base64,"), "plot_b64 前缀不正确"
    assert len(b64) > 200, "plot_b64 过短，疑似空图"
    assert "image_path" not in obj, "不应再返回落盘 image_path"


# ── 旗舰工具：il_viscosity_predict ────────────────────────────────
def test_il_viscosity_predict_fields():
    obj = _run("il_viscosity_predict",
               {"cation": "[BMIM]+", "anion": "[BF4]-",
                "temperature_k": 303.15, "pressure_mpa": 0.1})
    assert "error" not in obj, f"il_viscosity_predict 报错: {obj.get('error')}"

    eta = obj["eta_mpa_s"]
    assert isinstance(eta, (int, float)) and eta > 0, f"eta 非正数: {eta}"
    assert 1.0 < eta < 5000, f"eta 量级异常: {eta}"

    ci = obj["ci95_mpa_s"]
    assert isinstance(ci, list) and len(ci) == 2 and ci[0] < eta < ci[1], ci

    fi = obj["feature_importance"]
    assert set(fi) == {"temperature_k", "pressure_mpa", "cation", "anion"}, fi
    assert abs(sum(fi.values()) - 1.0) < 0.02, f"特征重要性未归一: {fi}"
    assert fi["temperature_k"] > 0.2, f"温度应为主导因素之一: {fi}"

    plot_b64 = obj["plot_b64"]
    assert plot_b64.startswith("data:image/png;base64,"), "plot_b64 前缀不正确"
    assert len(plot_b64) > 1000, "预测 vs 实测图过短"


def test_il_viscosity_rejects_bad_enum():
    obj = _run("il_viscosity_predict",
               {"cation": "[XXIM]+", "anion": "[BF4]-",
                "temperature_k": 303.15, "pressure_mpa": 0.1})
    assert "error" in obj, "非法阳离子应返回 error"


# ── crystal_structure：可选依赖 pymatgen，缺库时优雅降级 ──────────
def test_crystal_structure_graceful():
    obj = _run("crystal_structure", {"formula": "NaCl", "structure_type": "nacl"})
    # 有 pymatgen → 成功字段；无 pymatgen → 干净的 error 提示（不能崩）
    assert isinstance(obj, dict)
    assert "error" in obj or "crystal_system" in obj or "density" in obj \
        or "structure_type" in obj, f"意外返回: {list(obj)}"


# ── 全部 matlens_material 工具已注册且 schema 自描述 ──────────────
def test_all_material_tools_registered_and_schemas():
    entries = {e.name: e for e in registry.get_all_entries()
               if e.toolset == "matlens_material"}
    assert "il_viscosity_predict" in entries, "旗舰工具未注册"
    # 每个 schema 都有 type / properties / 顶层 description
    for name, entry in entries.items():
        sch = entry.schema
        assert sch.get("type") == "object", f"{name} schema 缺 type"
        assert "properties" in sch, f"{name} schema 缺 properties"
        assert sch.get("description") or entry.description, \
            f"{name} 缺 description（schema 或 register）"
