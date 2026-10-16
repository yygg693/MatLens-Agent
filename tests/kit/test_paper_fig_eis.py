# -*- coding: utf-8 -*-
"""EIS 专用绘图器回归测试（fig_eis.py，依赖 impedance.py）。

验证重点：
- impedance.py 缺失/版本差异时不崩（降级语义）
- 电路语法与参数提取正确（1.7.x API 踩坑记录）
- 等效电路拟合能还原已知参数
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from matlens_kit.paper.fig_kit import RefuseToDraw


def _synth_eis(freq=None):
    """合成 SOFC 风格 Nyquist：R0 + 两个 RC 弧（真值 R0=0.12, R1=0.35, R2=0.55, n=0.85）。"""
    freq = freq if freq is not None else np.logspace(5, -1, 40)
    def arc(R, tau, n=0.85):
        return R / (1 + (1j * freq * (1 / (2 * np.pi * tau))) ** n)
    z = 0.12 + arc(0.35, 1e-4) + arc(0.55, 1e-2)
    return freq, z


def _table(freq, z):
    return [{
        "name": "Cell-1",
        "caption": "Nyquist 谱（EIS）",
        "columns": ["f (Hz)", "Z' (Ω·cm²)", "-Z'' (Ω·cm²)"],
        "rows": [[float(f), float(zz.real), float(-zz.imag)] for f, zz in zip(freq, z)],
    }]


class TestImpedanceAvailable:
    def test_library_present(self):
        from matlens_kit.paper.fig_eis import impedance_available

        ok, ver = impedance_available()
        assert ok, f"impedance.py 不可用：{ver}"


class TestExtractEis:
    def test_extracts_three_columns(self):
        """抽出的三列应与原始谱一致（按频率对应，不假设行序）。"""
        from matlens_kit.paper.fig_eis import extract_eis

        freq, z = _synth_eis()
        spec = extract_eis(_table(freq, z))
        assert len(spec["f"]) == len(freq)
        # 抽出的 zreal/znegimag 必须能在原始谱里找到对应点
        for fr, zr, zi in zip(spec["f"], spec["zreal"], spec["znegimag"]):
            idx = int(np.argmin(np.abs(freq - fr)))
            assert np.isclose(zr, z[idx].real, rtol=1e-6, atol=1e-9)
            assert np.isclose(zi, -z[idx].imag, rtol=1e-6, atol=1e-9)

    def test_sorted_by_frequency(self):
        """频率须升序（内部约定），保证画图与拟合稳定。"""
        from matlens_kit.paper.fig_eis import extract_eis

        freq, z = _synth_eis()
        t = _table(freq, z)
        t[0]["rows"] = list(reversed(t[0]["rows"]))   # 故意倒序
        spec = extract_eis(t)
        assert list(spec["f"]) == sorted(spec["f"])

    def test_missing_eis_table_raises(self):
        from matlens_kit.paper.fig_eis import extract_eis

        bad = [{"name": "σ-T", "columns": ["温度", "σ"], "rows": [[600, 0.01], [700, 0.02]]}]
        with pytest.raises(RefuseToDraw):
            extract_eis(bad)

    def test_too_few_points_raises(self):
        from matlens_kit.paper.fig_eis import extract_eis

        t = [{"columns": ["f (Hz)", "Z'", "-Z''"], "rows": [[1000, 0.1, 0.0], [500, 0.11, 0.01]]}]
        with pytest.raises(RefuseToDraw):
            extract_eis(t)


class TestCircuitFitting:
    def test_recovers_r0(self):
        """拟合应还原欧姆电阻 R0 ≈ 0.12。"""
        from matlens_kit.paper.fig_eis import _fit_circuit

        freq, z = _synth_eis()
        fit = _fit_circuit(freq, z)
        assert fit is not None
        best = fit[fit["best"]]
        assert abs(best["params"]["R0"] - 0.12) < 0.02

    def test_recovers_cpe_exponent(self):
        """CPE 指数应还原 n ≈ 0.85。"""
        from matlens_kit.paper.fig_eis import _fit_circuit

        freq, z = _synth_eis()
        fit = _fit_circuit(freq, z)
        best = fit[fit["best"]]
        eta_keys = [k for k in best["params"] if k.startswith("CPE") and k.endswith("_1")]
        assert eta_keys, f"参数中无 CPE 指数：{list(best['params'])}"
        assert abs(best["params"][eta_keys[0]] - 0.85) < 0.08

    def test_picks_lowest_residual_model(self):
        fit_freq, z = _synth_eis()
        from matlens_kit.paper.fig_eis import _fit_circuit

        fit = _fit_circuit(fit_freq, z)
        residuals = {k: v["mean_rel_residual"] for k, v in fit.items() if k != "best"}
        assert fit["best"] == min(residuals, key=lambda k: residuals[k])

    def test_param_names_not_nested_tuple(self):
        """1.7.x 的 get_param_names() 返回 (names, units) 元组——不得当 list 用。

        这是真实踩坑：直接 list() 会得到嵌套列表，参数 dict 全空。
        """
        from impedance.models.circuits import CustomCircuit
        from matlens_kit.paper.fig_eis import _param_names

        c = CustomCircuit("R0-p(R1,CPE_1)", initial_guess=np.array([0.1, 1.0, 0.8, 1e-4]))
        names = _param_names(c)
        assert all(isinstance(n, str) for n in names)
        assert names and "R0" in names

    def test_prediction_curve_returned(self):
        """拟合曲线必须回传（否则图上叠不上拟合线）。"""
        from matlens_kit.paper.fig_eis import _fit_circuit

        freq, z = _synth_eis()
        fit = _fit_circuit(freq, z)
        best = fit[fit["best"]]
        assert len(best["_predreal"]) == len(freq)
        assert len(best["_prednegimag"]) == len(freq)


class TestDrawNyquist:
    def test_draws_with_fit_and_metadata(self):
        from matlens_kit.paper.fig_eis import draw_nyquist

        freq, z = _synth_eis()
        with tempfile.TemporaryDirectory() as d:
            meta = draw_nyquist(_table(freq, z), os.path.join(d, "nyq"))
            assert meta is not None
            assert os.path.isfile(meta["png"]) and os.path.getsize(meta["png"]) > 3000
            assert meta["pdf"], "应同时产出矢量 PDF"
            assert meta["n_points"] == len(freq)
            assert "impedance" in meta["library"]
            assert meta["mean_rel_residual"] < 0.05, "拟合残差过大"

    def test_draws_nyquist_bode(self):
        from matlens_kit.paper.fig_eis import draw_nyquist_bode

        freq, z = _synth_eis()
        with tempfile.TemporaryDirectory() as d:
            meta = draw_nyquist_bode(_table(freq, z), os.path.join(d, "nb"))
            assert os.path.isfile(meta["png"])
            assert meta["best_circuit"]          # 双面板版本也带拟合信息
            assert meta["params"]

    def test_no_eis_data_raises(self):
        from matlens_kit.paper.fig_eis import draw_nyquist

        bad = [{"name": "σ-T", "columns": ["温度", "σ"], "rows": [[600, 0.01], [700, 0.02]]}]
        with tempfile.TemporaryDirectory() as d:
            with pytest.raises(RefuseToDraw):
                draw_nyquist(bad, os.path.join(d, "x"))


class TestSchemeIntegration:
    def test_eis_registered_and_dispatchable(self):
        from matlens_kit.paper.fig_schemes import SCHEMES, detect_scheme, draw_scheme

        assert "eis" in SCHEMES
        assert detect_scheme("测试前后 Nyquist 谱对比（EIS）") == "eis"
        freq, z = _synth_eis()
        with tempfile.TemporaryDirectory() as d:
            meta = draw_scheme("eis", _table(freq, z), os.path.join(d, "s"))
            assert os.path.isfile(meta["png"])
            assert meta["library"].startswith("impedance")

    def test_po2_caption_not_mistaken_for_eis(self):
        """Hebb-Wagner 段落在谱系上属 po2_sigmae，不得被 eis 抢走。"""
        from matlens_kit.paper.fig_schemes import detect_scheme

        assert detect_scheme("Hebb-Wagner 极化曲线与 σ_e 随 pO₂ 的变化") == "po2_sigmae"