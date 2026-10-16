# -*- coding: utf-8 -*-
"""MatLens 功能深化回归测试：新增 3 个材料工具 + 论文三种格式导出。"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from matlens_kit.tools import material_kit  # noqa: E402,F401  确保注册


# ── battery_capacity ──────────────────────────────────────────────
def test_battery_capacity_lifepo4_formula():
    """LiFePO4（M≈157.76）n=1 → ≈169.9 mAh/g。"""
    from matlens_kit.tools.electrochem import battery_capacity_tool

    r = battery_capacity_tool(formula="LiFePO4", n=1)
    assert "error" not in r
    assert abs(r["theoretical_capacity_mAh_g"] - 96485 / 3.6 / 157.76) < 0.5
    assert "mAh/g" in r["calculation"]


def test_battery_capacity_ncm811_molar_mass():
    """固溶体 NCM811 走 molar_mass 模式：M=96.5 n=1 → ≈277.8 mAh/g。"""
    from matlens_kit.tools.electrochem import battery_capacity_tool

    r = battery_capacity_tool(molar_mass=96.5, n=1)
    assert "error" not in r
    assert abs(r["theoretical_capacity_mAh_g"] - 96485 / 3.6 / 96.5) < 0.5
    assert r["theoretical_capacity_mAh_g"] > 250  # NCM811 理论值确实较高


def test_battery_capacity_solid_solution_formula_hint():
    """固溶体小数下标公式 → 明确提示改用 molar_mass，不硬解析。"""
    from matlens_kit.tools.electrochem import battery_capacity_tool

    r = battery_capacity_tool(formula="LiNi0.8Co0.1Mn0.1O2", n=1)
    assert "error" in r
    assert "molar_mass" in r["error"]


def test_battery_capacity_invalid():
    from matlens_kit.tools.electrochem import battery_capacity_tool

    assert "error" in battery_capacity_tool(molar_mass=0)
    assert "error" in battery_capacity_tool(n=-1, molar_mass=100)


def test_material_kit_includes_new_tools():
    """MATERIAL_TOOLS 应包含新增 6 个深化工具。"""
    for n in ("battery_capacity", "energy_convert", "xrd_dspacing",
              "experiment_plot", "thermo_gibbs", "lever_rule"):
        assert n in material_kit.MATERIAL_TOOLS, n


# ── energy_convert ────────────────────────────────────────────────
def test_energy_convert_ev_to_nm():
    from matlens_kit.tools.computation import energy_convert_tool

    r = energy_convert_tool(value=1.24, from_unit="eV", to_unit="nm")
    assert "error" not in r
    assert abs(r["result"] - 1000.0) < 0.1  # 1240/1.24 = 1000


def test_energy_convert_all_units_roundtrip():
    from matlens_kit.tools.computation import energy_convert_tool

    # 3.1 eV → nm ≈ 400；→ cm-1 ≈ 25003
    r = energy_convert_tool(value=3.1, from_unit="eV", to_unit="nm")
    assert abs(r["result"] - 400.0) < 1.0
    r2 = energy_convert_tool(value=3.1, from_unit="eV", to_unit="cm-1")
    assert abs(r2["result"] - 3.1 * 8065.5) < 5.0


def test_energy_convert_errors():
    from matlens_kit.tools.computation import energy_convert_tool

    assert "error" in energy_convert_tool(value=1, from_unit="eV", to_unit="eV")
    assert "error" in energy_convert_tool(value=1, from_unit="furlong", to_unit="nm")


# ── xrd_dspacing ──────────────────────────────────────────────────
def test_xrd_dspacing_cu_38deg():
    """Cu Kα（1.5406Å）2θ=38° → d ≈ 2.367 Å。"""
    from matlens_kit.tools.data_processing import xrd_dspacing_tool

    r = xrd_dspacing_tool(value=38.0, mode="twotheta_to_d", target="Cu")
    assert "error" not in r
    import math

    expect = 1.5406 / (2 * math.sin(math.radians(19.0)))
    assert abs(r["d_spacing_A"] - expect) < 1e-3


def test_xrd_dspacing_roundtrip():
    """d → 2θ → d 应回到原值（±0.01）。"""
    from matlens_kit.tools.data_processing import xrd_dspacing_tool

    r1 = xrd_dspacing_tool(value=38.0, mode="twotheta_to_d", target="Cu")
    d = r1["d_spacing_A"]
    r2 = xrd_dspacing_tool(value=d, mode="d_to_twotheta", target="Cu")
    assert abs(r2["twotheta_deg"] - 38.0) < 0.01


def test_xrd_dspacing_errors():
    from matlens_kit.tools.data_processing import xrd_dspacing_tool

    assert "error" in xrd_dspacing_tool(value=38, target="Uknow")
    # d 过小超出 asin 定义域
    assert "error" in xrd_dspacing_tool(value=0.5, mode="d_to_twotheta", target="Cu")
    assert "error" in xrd_dspacing_tool(value=38, mode="bogus")


# ── thermo_gibbs ──────────────────────────────────────────────────
def test_thermo_gibbs_balance_temperature():
    """ΔH=100 kJ, ΔS=200 J/K → T_eq=500K；T=500K 时 ΔG=0 平衡。"""
    from matlens_kit.tools.thermo import thermo_gibbs_tool

    r = thermo_gibbs_tool(delta_h=100, delta_s=200, temperature=500)
    assert "error" not in r
    assert abs(r["delta_g_kJ_mol"]) < 1e-6
    assert r["direction"] == "平衡（ΔG=0）"
    assert abs(r["equilibrium_temperature_K"] - 500) < 0.01


def test_thermo_gibbs_direction():
    """ΔH=100, ΔS=200：T=300K 时 ΔG=40>0 逆向；T=800K 时 ΔG=-60 正向。"""
    from matlens_kit.tools.thermo import thermo_gibbs_tool

    r1 = thermo_gibbs_tool(delta_h=100, delta_s=200, temperature=300)
    assert r1["direction"].startswith("逆向")
    r2 = thermo_gibbs_tool(delta_h=100, delta_s=200, temperature_c=526.85)  # 800K
    assert r2["direction"].startswith("正向")
    assert abs(r2["temperature_K"] - 800) < 0.5


def test_thermo_gibbs_errors():
    from matlens_kit.tools.thermo import thermo_gibbs_tool

    assert "error" in thermo_gibbs_tool(delta_h=100, delta_s=200, temperature=-5)
    r = thermo_gibbs_tool(delta_h=100, delta_s=0, temperature=300)
    assert r.get("note", "").startswith("ΔS=0")


# ── lever_rule ────────────────────────────────────────────────────
def test_lever_rule_midpoint():
    """x0=0.5, xα=0.2, xβ=0.8 → 两相各 50%。"""
    from matlens_kit.tools.thermo import lever_rule_tool

    r = lever_rule_tool(composition=0.5, phase1=0.2, phase2=0.8)
    assert "error" not in r
    assert abs(r["phase1_pct"] - 50) < 1e-6
    assert abs(r["phase2_pct"] - 50) < 1e-6
    assert r["sum_check"] == 1.0


def test_lever_rule_asymmetric():
    """x0=0.3, xα=0.1, xβ=0.7 → Wα=66.67%, Wβ=33.33%。"""
    from matlens_kit.tools.thermo import lever_rule_tool

    r = lever_rule_tool(composition=0.3, phase1=0.1, phase2=0.7)
    assert abs(r["phase1_pct"] - 66.67) < 0.01
    assert abs(r["phase2_pct"] - 33.33) < 0.01


def test_lever_rule_out_of_region():
    from matlens_kit.tools.thermo import lever_rule_tool

    assert "error" in lever_rule_tool(composition=0.9, phase1=0.2, phase2=0.8)
    assert "error" in lever_rule_tool(composition=0.5, phase1=0.2, phase2=0.2)


# ── experiment_plot ───────────────────────────────────────────────
def test_experiment_plot_inline_xy():
    """内联 x/y → 生成 PNG 且统计正确。"""
    from matlens_kit.tools.plotting import experiment_plot_tool

    xs = [10, 20, 30, 40, 50]
    ys = [2, 4, 6, 8, 10]
    r = experiment_plot_tool(x=xs, y=ys, plot_type="xy")
    assert "error" not in r
    assert r["stats"]["n"] == 5
    assert r["stats"]["y_max"] == 10
    import os

    assert os.path.exists(r["image_path"])
    assert r["image_path"].endswith(".png")


def test_experiment_plot_xrd_from_file(tmp_path):
    """文件模式 XRD 图。"""
    from matlens_kit.tools.plotting import experiment_plot_tool

    f = tmp_path / "xrd.txt"
    f.write_text("2theta,intensity\n10,100\n20,300\n30,200\n40,150\n50,80\n", encoding="utf-8")
    r = experiment_plot_tool(file=str(f), plot_type="xrd")
    assert "error" not in r
    assert r["stats"]["n"] == 5
    assert r["plot_type"] == "xrd"


def test_experiment_plot_errors():
    from matlens_kit.tools.plotting import experiment_plot_tool

    assert "error" in experiment_plot_tool()  # 无数据
    assert "error" in experiment_plot_tool(x=[1, 2], y=[1])  # 长度不一致


# ── 论文导出 ──────────────────────────────────────────────────────
def _make_paper():
    return {
        "id": "paper_test",
        "title": "NCM811 正极材料循环性能研究",
        "paper_type": "research",
        "topic": "锂离子电池高镍正极容量衰减机制",
        "created_at": "2026-08-26 10:00:00",
        "stages": {
            "topic": {"status": "done", "content": "研究 NCM811 容量衰减机制，聚焦晶格氧损失与相变。"},
            "search": {"status": "done", "content": "文献综述：高镍正极衰减研究进展。",
                       "refs": [{"title": "Surface reconstruction in Ni-rich cathodes", "authors": "A. Zhang", "year": "2024", "source": "Adv. Mater.", "doi": "10.1000/xyz"}]},
            "outline": {"status": "done", "content": "## 1 引言\n## 2 实验方法"},
            "write": {"status": "done", "content": "# 摘要\n高镍正极材料容量衰减机制综述。\n\n# 引言\n锂离子电池……"},
            "quality": {"status": "done", "content": "自查通过。"},
            "review": {"status": "done", "content": "评审意见：补充首效数据。"},
            "export": {"status": "pending", "content": ""},
        },
    }


def test_export_markdown_full():
    from matlens_kit.paper.export import export_markdown

    md = export_markdown(_make_paper())
    # 标题 + write 正文 + 参考文献
    assert "# NCM811 正极材料循环性能研究" in md
    assert "高镍正极材料容量衰减机制综述。" in md
    assert "## 参考文献" in md
    assert "A. Zhang" in md and "10.1000/xyz" in md
    # 过程性内容一律不得进入成稿
    assert "选题设定" not in md and "文献检索" not in md and "大纲生成" not in md
    assert "逐章写作" not in md and "质量巡检" not in md and "模拟审稿" not in md
    assert "**主题**" not in md and "项目 ID" not in md
    assert "研究 NCM811 容量衰减机制，聚焦晶格氧损失" not in md  # topic 内容
    assert "实验方法" not in md        # outline 内容
    assert "自查通过" not in md        # quality 内容
    assert "评审意见" not in md        # review 内容


def test_export_paper_rejects_empty_write():
    from matlens_kit.paper.export import export_paper

    p = _make_paper()
    p["stages"]["write"]["content"] = ""
    r = export_paper(p, "md")
    assert r["ok"] is False
    assert "尚未" in r["error"]


def test_export_latex_escape():
    from matlens_kit.paper.export import export_latex

    p = _make_paper()
    p["stages"]["write"]["content"] = "衰减率 100% 与 $x$ 的关系\n\n第二段 & 特殊 \\ 字符"
    tex = export_latex(p)
    assert "\\documentclass[12pt]{ctexart}" in tex
    assert "\\begin{document}" in tex
    assert "\\end{document}" in tex
    assert "\\%" in tex and "\\$" in tex and "\\&" in tex and r"\textbackslash{}" in tex
    assert "NCM811 正极材料循环性能研究" in tex


def test_export_docx_bytes():
    from matlens_kit.paper.export import export_docx

    data = export_docx(_make_paper())
    assert data is not None
    # docx = zip 容器，魔数 PK
    assert data[:2] == b"PK"


def test_export_paper_entry():
    from matlens_kit.paper.export import export_paper

    r = export_paper(_make_paper(), "md")
    assert r["ok"] and r["filename"].endswith(".md")
    r2 = export_paper(_make_paper(), "tex")
    assert r2["ok"] and r2["filename"].endswith(".tex")
    r3 = export_paper(_make_paper(), "docx")
    assert r3["ok"] and r3["bytes"][:2] == b"PK"
    assert export_paper(_make_paper(), "pdf")["ok"] is False
