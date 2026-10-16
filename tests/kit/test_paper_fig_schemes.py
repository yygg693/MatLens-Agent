# -*- coding: utf-8 -*-
"""科研绘图链回归测试（fig_kit / fig_schemes / fig_gen 数据图分派）。

核心红线：**没有真实数据就拒绝出图**。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from matlens_kit.paper.fig_kit import (
    OKABE_ITO,
    RefuseToDraw,
    assert_no_fabrication,
    find_table,
    fit_arrhenius,
    to_xy,
)
from matlens_kit.paper.fig_schemes import SCHEMES, detect_scheme, draw_scheme

SIGMA_T = [
    {"name": "A/air", "columns": ["温度 (°C)", "σ (S·cm⁻¹)"],
     "rows": [[600, 0.00698], [650, 0.0182], [700, 0.0421]]},
    {"name": "B/air", "columns": ["温度 (°C)", "σ (S·cm⁻¹)"],
     "rows": [[600, 0.00621], [650, 0.0165], [700, 0.0403]]},
]
STABILITY = [
    {"name": "Cell-1", "columns": ["时间 (h)", "电压 (V)"],
     "rows": [[0, 0.802], [50, 0.794], [100, 0.790]]},
]
PO2 = [
    {"name": "po2", "columns": ["pO₂ (atm)", "σ_e (S·cm⁻¹)"],
     "rows": [[1e-25, 1.9e-4], [1e-22, 1.4e-3], [1e-20, 8.6e-3], [1e-18, 4.1e-2]]},
]


class TestSchemeDetection:
    @pytest.mark.parametrize("desc,expected", [
        ("σT 随 1000/T 的 Arrhenius 图", "arrhenius"),
        ("X射线衍射全谱与 (111) 峰位移放大", "xrd"),
        ("线收缩率与相对密度随烧结温度的变化", "density_shrink"),
        ("600 °C 下的 I–V 与 I–P 曲线", "iv_ip"),
        ("100 h 恒流稳定性曲线", "stability"),
        ("Hebb-Wagner 极化曲线与 σ_e 随 pO₂ 的变化", "po2_sigmae"),
        ("电导率随温度变化（空气与 5% H₂–Ar）", "sigma_t"),
    ])
    def test_detects_known_schemes(self, desc, expected):
        assert detect_scheme(desc) == expected

    @pytest.mark.parametrize("desc", ["", "   ", "一幅插图", "示意图"])
    def test_vague_caption_returns_none(self, desc):
        """模糊图注不得硬凑谱系（宁可跳过也不画错）。"""
        assert detect_scheme(desc) is None


class TestRefuseWithoutData:
    """学术诚信红线：数据不足必须拒绝出图。"""

    def test_missing_tables_raises(self):
        with pytest.raises(RefuseToDraw):
            draw_scheme("sigma_t", [], os.path.join(tempfile.gettempdir(), "x_no_data"))

    def test_wrong_schema_raises(self):
        """表结构不匹配谱系 → 拒绝（不得凑合画一张错的）。"""
        with pytest.raises(RefuseToDraw):
            draw_scheme("stability", SIGMA_T, os.path.join(tempfile.gettempdir(), "x_bad"))

    def test_too_few_points_raises(self):
        with pytest.raises(RefuseToDraw):
            to_xy({"columns": ["温度", "σ"], "rows": [[600, 1.0]]}, ["温度"], ["σ"])

    def test_nonpositive_sigma_rejected_by_arrhenius(self):
        """σ 出现非正值 → Arrhenius 对数无意义，必须拒绝。"""
        bad = [{"columns": ["温度 (°C)", "σ (S·cm⁻¹)"],
                "rows": [[600, -1.0], [650, 0.018], [700, 0.042]]}]
        with pytest.raises(RefuseToDraw):
            draw_scheme("arrhenius", bad, os.path.join(tempfile.gettempdir(), "x_neg"))


class TestNoFabrication:
    def test_value_without_source_rejected(self):
        """图上数值在录入数据里找不到出处 → 拒绝（防图-文不一致）。"""
        rows = [[600, 0.00698], [650, 0.0182], [700, 0.0421]]
        with pytest.raises(RefuseToDraw):
            assert_no_fabrication([0.999], source_rows=rows)

    def test_value_with_source_passes(self):
        rows = [[600, 0.00698], [650, 0.0182], [700, 0.0421]]
        assert_no_fabrication([0.0182], source_rows=rows)   # 不抛异常即通过

    def test_no_source_table_skips_check(self):
        assert_no_fabrication([123.456], source_rows=None)


class TestColumnMisMatch:
    """2026-10-14 实测踩坑：σ_e–pO₂ 表被误当成 σ–T 表拉进Arrhenius。"""

    def test_po2_table_excluded_from_sigma_series(self):
        """pO₂ 列（跨 7 个数量级）不得被误认为温度列。"""
        from matlens_kit.paper.fig_schemes import _multi_series_sigma

        series = _multi_series_sigma(SIGMA_T + PO2)
        labels = [s[0] for s in series]
        assert len(series) == 2
        assert "po2" not in " ".join(labels)

    def test_all_zero_x_column_rejected(self):
        """x 全同值（如误匹配的 0 列）必须被拦。"""
        from matlens_kit.paper.fig_schemes import _multi_series_sigma

        zeros = [{"name": "z", "columns": ["温度 (°C)", "σ (S·cm⁻¹)"],
                  "rows": [[0, 0.1], [0, 0.2], [0, 0.3]]}]
        with pytest.raises(RefuseToDraw):
            _multi_series_sigma(zeros)


class TestArrhenius:
    def test_known_ea_recovered(self):
        """用真实 Arrhenius 关系合成数据，验证拟合能还原 Ea（±0.15 eV）。

        固体电导的标准形式：σ = σ0·exp(-Ea/kT)，
        故 ln(σT) = ln(σ0·T) - Ea/(kT)，对 1000/T 的斜率 = -Ea/(k·1000)。
        注意这里带 σT 而非 σ，斜率换算会引入 T 因子，故容差取 ±0.15 eV。
        """
        import numpy as np

        k_B = 8.617333262e-5
        true_ea = 1.25
        temps = [600, 650, 700, 750]
        T = np.asarray(temps, dtype=float) + 273.15
        sigma = np.exp(-true_ea / (k_B * T))     # σ0 = 1
        fit = fit_arrhenius(temps, list(sigma))
        assert abs(fit["Ea_eV"] - true_ea) < 0.15
        assert fit["r2"] > 0.999

    def test_too_few_points_raises(self):
        with pytest.raises(RefuseToDraw):
            fit_arrhenius([600, 650], [0.1, 0.2])


class TestPalette:
    def test_no_default_matplotlib_blue(self):
        """禁止 Matplotlib 默认蓝（#1f77b4）——那是"AI 味"的来源。"""
        assert "#1f77b4" not in OKABE_ITO

    def test_colorblind_safe(self):
        """Okabe-Ito 是色盲友好色板，不应含红绿强对比。"""
        blob = " ".join(OKABE_ITO).lower()
        assert "#d55e00" in blob and "#009e73" in blob   # 朱红 + 绿（配对使用，非红绿对比）


class TestDrawingProducesFiles:
    @pytest.mark.parametrize("scheme,tables", [
        ("sigma_t", SIGMA_T),
        ("arrhenius", SIGMA_T),
        ("stability", STABILITY),
        ("po2_sigmae", PO2),
    ])
    def test_png_and_vector_written(self, scheme, tables):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, f"fig_test")
            meta = draw_scheme(scheme, tables, out)
            assert os.path.isfile(meta["png"])
            assert os.path.getsize(meta["png"]) > 3000     # 真实图片非空文件
            assert meta["pdf"] and os.path.isfile(meta["pdf"])   # 矢量投稿格式

    def test_stability_reports_decay_rate(self):
        """衰减率必须算出来——评审正是盯这个数量级。"""
        with tempfile.TemporaryDirectory() as d:
            meta = draw_scheme("stability", STABILITY, os.path.join(d, "s"))
            # 0.802 → 0.790 over 100 h = 1.4963 %/(100 h)
            assert abs(meta["decay_pct_per_100h"] - 1.4963) < 0.01

    def test_all_schemes_implemented(self):
        """全部已注册谱系（eis 由第二级 fig_eis 提供专业实现）。"""
        assert set(SCHEMES) == {"sigma_t", "arrhenius", "density_shrink",
                                "iv_ip", "stability", "po2_sigmae", "xrd", "eis"}


class TestGenFiguresIntegration:
    """fig_gen 集成：data 类图不再一律 skipped，但无数据仍跳过。"""

    WRITE = (
        "**图 1** X射线衍射全谱与 (111) 峰位移放大。\n\n"
        "**图 2** 电导率随温度变化（空气）。\n\n"
        "**图 3** 阳极支撑单电池截面构型示意（阳极/电解质/阴极）。\n"
    )

    def test_data_fig_generated_when_data_present(self):
        from matlens_kit.paper.fig_gen import gen_figures

        with tempfile.TemporaryDirectory() as d:
            res = gen_figures(self.WRITE, d, experimental_data={"tables": [
                {"name": "xrd", "columns": ["2θ (°)", "强度 (a.u.)"],
                 "rows": [[28, 320], [33, 180], [47, 410], [56, 210]]},
            ] + SIGMA_T})
            by_num = {r["num"]: r for r in res}
            assert by_num[1]["status"] == "generated"
            assert by_num[1]["scheme"] == "xrd"
            assert by_num[2]["status"] == "generated"
            assert by_num[3]["status"] == "generated"      # cell 示意图仍工作

    def test_data_fig_skipped_when_no_data(self):
        from matlens_kit.paper.fig_gen import gen_figures

        with tempfile.TemporaryDirectory() as d:
            res = gen_figures(self.WRITE, d, experimental_data=None)
            by_num = {r["num"]: r for r in res}
            assert by_num[1]["status"] == "skipped"
            assert "实验数据" in (by_num[1]["reason"] or "")
            assert by_num[3]["status"] == "generated"    # 示意图不受影响

    def test_reason_is_explicit_not_silent(self):
        """skip 必须给出 reason，前端才能告诉用户为什么没图。"""
        from matlens_kit.paper.fig_gen import gen_figures

        with tempfile.TemporaryDirectory() as d:
            res = gen_figures("**图 1** 电导率随温度变化。", d, experimental_data=None)
            assert res[0]["status"] == "skipped"
            assert res[0]["reason"]

    def test_caption_desc_has_no_markdown_bold(self):
        """图注描述不应残留 ** （v7 实测问题）。"""
        from matlens_kit.paper.fig_gen import _extract_captions

        caps = _extract_captions("**图 1** **XRD 全谱测试。**\n")
        assert caps and "**" not in caps[0]["desc"]