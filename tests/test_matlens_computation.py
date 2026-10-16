# -*- coding: utf-8 -*-
"""MatLens 回归测试 —— P1 材料工具修复。

覆盖：
- P1-1 水合物解析（CuSO4·5H2O / Na2SO4·10H2O / 英文点写法）
- P1-2 Tauc 带隙透射率→吸光度转换（%T 文件与 Abs 文件带隙一致）
"""
import math

import pytest

from matlens_kit.tools.computation import (
    _is_transmittance_hint,
    _load_absorbance_data,
    _to_absorbance,
    molar_mass_tool,
    parse_formula,
    tauc_bandgap_tool,
)


class TestHydrateParsing:
    """P1-1：parse_formula 必须支持结晶水（点号 + 前导系数）。"""

    def test_cuso4_5h2o_element_counts(self):
        # CuSO4·5H2O → Cu1 S1 O9 H10
        counts = dict(parse_formula("CuSO4·5H2O"))
        assert counts == {"Cu": 1, "S": 1, "O": 9, "H": 10}

    def test_na2so4_10h2o_element_counts(self):
        # Na2SO4·10H2O → Na2 S1 O14 H20
        counts = dict(parse_formula("Na2SO4·10H2O"))
        assert counts == {"Na": 2, "S": 1, "O": 14, "H": 20}

    def test_english_dot_compatible(self):
        # 英文点与中点等价
        assert dict(parse_formula("CuSO4.5H2O")) == dict(parse_formula("CuSO4·5H2O"))

    def test_no_hydrate_still_works(self):
        assert dict(parse_formula("Fe2O3")) == {"Fe": 2, "O": 3}
        assert dict(parse_formula("Ca(OH)2")) == {"Ca": 1, "O": 2, "H": 2}

    def test_molar_mass_cuso4_5h2o(self):
        r = molar_mass_tool(formula="CuSO4·5H2O")
        assert r.get("molar_mass_g_mol") == pytest.approx(249.677, abs=0.01)

    def test_molar_mass_na2so4_10h2o(self):
        r = molar_mass_tool(formula="Na2SO4·10H2O")
        assert r.get("molar_mass_g_mol") == pytest.approx(322.186, abs=0.01)

    def test_invalid_formula_returns_error(self):
        r = molar_mass_tool(formula="NotAChemical")
        assert "error" in r


class TestTransmittanceDetection:
    """P1-2：透射率单位提示判定与吸光度转换。"""

    def test_transmittance_hints_detected(self):
        for h in ["wavelength %T", "transmittance", "透射率", "透过率", "T (%)"]:
            assert _is_transmittance_hint(h), h

    def test_absorbance_not_misdetected(self):
        assert not _is_transmittance_hint("absorbance")
        assert not _is_transmittance_hint("Abs")
        assert not _is_transmittance_hint("intensity")

    def test_to_absorbance_pct(self):
        # %T=50 → A = -log10(0.5) ≈ 0.3010
        assert _to_absorbance(50.0, "%T") == pytest.approx(0.3010, abs=1e-3)

    def test_to_absorbance_fraction(self):
        # T=0.5（0~1 小数）→ 同样 ≈ 0.3010
        assert _to_absorbance(0.5, "transmittance") == pytest.approx(0.3010, abs=1e-3)

    def test_no_hint_passthrough(self):
        assert _to_absorbance(2.5, "") == 2.5


class TestTaucTransmittanceConsistency:
    """P1-2 核心回归：同一光谱的 %T 版与 Abs 版带隙必须一致。"""

    @staticmethod
    def _write_spectrum(path, transmittance=True):
        # 构造一段带吸收边的光谱（波长 300-800nm）
        with open(path, "w", encoding="utf-8") as f:
            if transmittance:
                f.write("# wavelength(nm)  transmittance(%)\n")
            else:
                f.write("# wavelength(nm)  absorbance\n")
            for wl in range(300, 801, 10):
                # 吸收边在 ~500nm：小于边吸收强（T 小 / A 大），大于边透射（T 大 / A 小）
                a = 3.0 if wl < 500 else 3.0 * math.exp(-(wl - 500) / 60.0)
                if transmittance:
                    # A = -log10(T/100) → T = 100 * 10^(-A)
                    t = 100.0 * (10 ** (-a))
                    f.write(f"{wl} {t:.6f}\n")
                else:
                    f.write(f"{wl} {a:.6f}\n")

    def test_bandgap_identical_for_transmittance_and_absorbance(self, tmp_path):
        t_file = tmp_path / "trans.txt"
        a_file = tmp_path / "abs.txt"
        self._write_spectrum(t_file, transmittance=True)
        self._write_spectrum(a_file, transmittance=False)

        t_res = tauc_bandgap_tool(str(t_file), transition="direct", wavelength_unit="nm")
        a_res = tauc_bandgap_tool(str(a_file), transition="direct", wavelength_unit="nm")

        assert "error" not in t_res, t_res
        assert "error" not in a_res, a_res
        assert t_res["bandgap_eV"] == pytest.approx(a_res["bandgap_eV"], abs=1e-3), (
            f"%T 版带隙 {t_res['bandgap_eV']} 与 Abs 版 {a_res['bandgap_eV']} 不一致"
        )

    def test_load_absorbance_returns_header_hint(self, tmp_path):
        path = tmp_path / "data.txt"
        self._write_spectrum(path, transmittance=True)
        rows, hint = _load_absorbance_data(str(path))
        assert len(rows) >= 5
        assert hint and "trans" in hint.lower()

    def test_load_absorbance_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _load_absorbance_data(str(tmp_path / "nope.txt"))
