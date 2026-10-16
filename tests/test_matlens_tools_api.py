# -*- coding: utf-8 -*-
"""MatLens 回归测试 —— P2-1 工具中心真实数据。

覆盖 tools_api 从 Hermes registry 动态拉取材料工具、从核心工具集统计通用能力的
真实结果，防止前端重新退回 mock 假数据（material_count / general.count 变化时
本测试即报警）。
"""
import pytest

from matlens_kit.api.tools_api import _general_tools, _material_tools


class TestMaterialTools:
    def test_count_is_18(self):
        tools = _material_tools()
        assert len(tools) == 18

    def test_includes_real_kb_tools(self):
        names = {t["name"] for t in _material_tools()}
        assert "rag_search" in names  # 真实知识库检索工具（注册于 local_rag）
        assert "matlens_kb" in names

    def test_core_tools_present(self):
        names = {t["name"] for t in _material_tools()}
        for core in ("molar_mass", "solution_prep", "tauc_bandgap", "xrd_preprocess"):
            assert core in names

    def test_new_deepen_tools_present(self):
        """功能深化新增工具应出现在工具中心。"""
        names = {t["name"] for t in _material_tools()}
        for n in ("battery_capacity", "energy_convert", "xrd_dspacing",
                  "experiment_plot", "thermo_gibbs", "lever_rule"):
            assert n in names, n

    def test_entries_have_cn_and_cat(self):
        for t in _material_tools():
            assert t["name"]
            assert t["cn"]
            assert t["cat"] in {"材料计算", "实验辅助", "数据处理", "写作", "知识库"}

    def test_order_stable_by_category(self):
        order = {"材料计算": 0, "实验辅助": 1, "数据处理": 2, "写作": 3, "知识库": 4}
        tools = _material_tools()
        cats = [order[t["cat"]] for t in tools]
        assert cats == sorted(cats)


class TestGeneralTools:
    def test_count_matches_core_tools(self):
        g = _general_tools()
        assert g["count"] == 71  # _MATLENS_CORE_TOOLS 当前规模（变化时同步更新）

    def test_categories_have_examples(self):
        cats = _general_tools()["categories"]
        assert cats  # 非空
        for cat in cats:
            assert cat["key"] and cat["count"] > 0 and cat["examples"]
