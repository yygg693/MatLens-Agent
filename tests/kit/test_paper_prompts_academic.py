# -*- coding: utf-8 -*-
"""论文 prompt 学术严谨性硬约束测试（纯函数级，仅 stdlib + pytest，无网络）。

对照 DeepSeek 对 SOFC 论文的 8 条评审意见，断言 prompts.py 渲染出的
write/review/outline/search prompt 已内置对应防护约束：
  ① 数据不完整 ② 过度声称 ③ σ_e 与 t_ion 不自洽 ④ 机制证据不足
  ⑤ 对照实验不够 ⑥ 文献对比太弱 ⑦ 稳定性短测被称长期 ⑧ 伪引用/参考文献缺失
"""
from __future__ import annotations

import pytest

from matlens_kit.paper.prompts import data_block, render_prompt


def _write_ctx(**kw):
    ctx = {
        "topic": "Co 掺杂 GDC 电解质",
        "paper_type": "研究论文",
        "outline_text": "## 引言\n## 方法\n## 结果\n## 讨论",
        "section": "结果与讨论",
        "word_count": "2000",
        "section_points": "电导率、单电池性能、机理",
        "refs_text": "[1] GDC electrolytes · Zhang · 2023 · DOI:10.1/x",
        "existing_text": "",
        "continuation": "",
    }
    ctx.update(kw)
    return ctx


# --------------------------------------------------------------------------
# write：学术严谨性硬约束
# --------------------------------------------------------------------------
def test_write_prompt_has_academic_hard_constraints():
    out = render_prompt("write", _write_ctx())
    # A 数据占位规范
    assert "拟议值" in out
    assert "待实验确认" in out
    assert "重复次数" in out
    # B 声称克制：弱声称被要求、强声称被禁止
    assert "proposed" in out
    assert "hypothesis" in out
    assert "identified" in out  # 作为被禁止的强出现在约束里
    # C 数值自洽
    assert "σ_e" in out
    assert "t_ion" in out
    assert "自洽" in out
    # D 对照实验
    assert "对照" in out
    # E 文献对比表
    assert "对比表" in out
    # F 稳定性短期表述
    assert "short-term" in out
    assert "短期" in out
    # G 禁止 {A-n} 占位伪引用（模板 {{A-n}} 经 format 渲染为 {A-n}）
    assert "{A-" in out


def test_write_prompt_legacy_placeholders_intact():
    out = render_prompt("write", _write_ctx())
    # 旧占位符全部被填充
    assert "Co 掺杂 GDC 电解质" in out
    assert "结果与讨论" in out
    assert "2000" in out


def test_write_cite_style_ieee():
    out = render_prompt("write", _write_ctx(cite_style="ieee"))
    assert "IEEE" in out


def test_write_tone_variants():
    assert "正式学术" in render_prompt("write", _write_ctx(tone="formal"))
    assert "简洁精炼" in render_prompt("write", _write_ctx(tone="concise"))
    assert "详细深入" in render_prompt("write", _write_ctx(tone="detailed"))


# --------------------------------------------------------------------------
# review：六维学术评审 + 修改清单固定格式
# --------------------------------------------------------------------------
def test_review_prompt_six_dimensions():
    out = render_prompt("review", {"topic": "Co 掺杂 GDC 电解质", "draft_text": "草稿正文……"})
    for dim in ("数据完整性", "数值自洽", "声称-证据一致性",
                "对照实验充分性", "文献对比充分性", "稳定性"):
        assert dim in out, f"缺少评审维度：{dim}"
    # 稳定性短测 / 伪引用 / 参考文献缺失 三条防护
    assert "stable operation" in out
    assert "{A-" in out
    # 修改清单固定格式
    assert "建议:" in out
    assert "操作: 修改|删除|补充" in out


# --------------------------------------------------------------------------
# outline：数据表设计 + 机制证据评估 + 文献对比小节
# --------------------------------------------------------------------------
def test_outline_prompt_requires_data_tables_and_discussion():
    out = render_prompt("outline", {
        "topic": "Co 掺杂 GDC 电解质",
        "paper_type": "研究论文",
        "topic_content": "降低 GDC 烧结温度",
        "refs_text": "[1] xxx",
    })
    assert "Results" in out
    assert "重复次数" in out
    assert "误差" in out
    assert "机制证据" in out
    assert "evidence vs hypothesis" in out
    assert "文献对比" in out or "对比表" in out


# --------------------------------------------------------------------------
# search：真实核验文献清单（作者·年份·期刊·DOI），空白名单禁止编造
# --------------------------------------------------------------------------
def test_search_prompt_requires_verifiable_list():
    out = render_prompt("search", {
        "topic": "GDC 电解质",
        "refs_text": "[1] Zhang. GDC. JACS. 2023. DOI:10.1/x",
    })
    assert "DOI" in out
    assert "编号" in out
    assert "编造" in out or "虚构" in out


# --------------------------------------------------------------------------
# experimental_data 注入兼容
# --------------------------------------------------------------------------
def test_render_without_experimental_data_ok():
    """旧调用方不传 experimental_data → 不抛异常且含未录入提示。"""
    out = render_prompt("write", _write_ctx())
    assert "未录入实验数据" in out
    out2 = render_prompt("outline", {
        "topic": "t", "paper_type": "研究论文", "topic_content": "", "refs_text": "",
    })
    assert "未录入实验数据" in out2


def test_render_experimental_data_dict_measured():
    data = {"status": "measured", "notes": "800°C 湿氢, n=3", "tables": {"sigma": [0.12, 0.15]}}
    out = render_prompt("write", _write_ctx(experimental_data=data))
    assert "实测数据" in out
    assert "800°C" in out
    assert "sigma" in out


def test_render_experimental_data_dict_proposed():
    data = {"status": "proposed", "notes": "待烧结后实测"}
    out = render_prompt("write", _write_ctx(experimental_data=data))
    assert "拟议" in out
    assert "待实验确认" in out


def test_data_block_empty():
    assert "未录入实验数据" in data_block(None)
    assert "未录入实验数据" in data_block({})


def test_unknown_step_raises_keyerror():
    with pytest.raises(KeyError):
        render_prompt("nonexistent", {"topic": "x"})


# --------------------------------------------------------------------------
# 第二轮：DeepSeek 网页版评审暴露的 write prompt 硬约束 H–M
# --------------------------------------------------------------------------
def test_write_prompt_physical_fact_constraint():
    """H：Gd³⁺/Ce⁴⁺ 离子半径方向、晶格常数增大、XRD 精修兜底。"""
    out = render_prompt("write", _write_ctx())
    assert "Gd³⁺" in out
    assert "Ce⁴⁺" in out
    assert "1.053" in out
    assert "0.97" in out
    assert "晶格常数" in out
    assert "X 射线衍射精修确认" in out


def test_write_prompt_arrhenius_cross_table_consistency():
    """I：σ_bulk/σ_gb 活化能不同 → 比例随温度变化（Arrhenius 复核）。"""
    out = render_prompt("write", _write_ctx())
    assert "σ_bulk" in out
    assert "σ_gb" in out
    assert "Arrhenius" in out
    assert "活化能" in out


def test_write_prompt_recheckable_calculation():
    """J：百分比/换算必须给出可验算中间步骤（含示例数字）。"""
    out = render_prompt("write", _write_ctx())
    assert "可复核" in out or "可验算" in out
    assert "1.2 mV" in out
    assert "0.125%" in out


def test_write_prompt_control_full_dimension():
    """K：对照样品同维度全指标（待补），不得只给个别指标下判断。"""
    out = render_prompt("write", _write_ctx())
    assert "对照样品全维度" in out or "全维度" in out
    assert "待补" in out


def test_write_prompt_statistical_power():
    """L：PPD/OCV n≥5 或标注 n/置信区间；n<5 按 Student-t 保守估计。"""
    out = render_prompt("write", _write_ctx())
    assert "n≥5" in out
    assert "Student-t" in out
    assert "置信区间" in out


def test_write_prompt_methodology_citation_density():
    """M：白名单≥8 条须覆盖方法学文献且按引言/方法/讨论分布。"""
    out = render_prompt("write", _write_ctx())
    assert "Hebb-Wagner" in out
    assert "EIS" in out
    assert "空间电荷层" in out
    assert "缺陷化学" in out


def test_review_prompt_new_dimension_hints():
    """六维评审新增：物理化学事实核查、Arrhenius 一致性、可复核计算、对照全维度。"""
    out = render_prompt("review", {"topic": "t", "draft_text": "d"})
    assert "物理化学事实" in out
    assert "Arrhenius" in out
    assert "可验算" in out
    assert "Student-t" in out


# --------------------------------------------------------------------------
# 第三轮：v3 评审暴露的 write prompt 硬约束 N–R
# --------------------------------------------------------------------------
def test_write_prompt_asr_thickness_unified():
    """N：厚度-ASR 统一基准，ASR = L/σ，禁厚度矛盾差百倍。"""
    out = render_prompt("write", _write_ctx())
    assert "ASR = L/σ" in out
    assert "厚度" in out
    assert "L/σ" in out


def test_write_prompt_samplewise_theoretical_density():
    """O：逐样品理论密度（各自 M 与精修 a），禁共用主线参数。"""
    out = render_prompt("write", _write_ctx())
    assert "逐样品" in out
    assert "理论密度" in out
    assert "晶格常数" in out or "精修" in out


def test_write_prompt_cross_table_resistance_decomposition():
    """P：单电池/对称电池 ASR 同时出现时给 R_Ω 与 R_p 分解。"""
    out = render_prompt("write", _write_ctx())
    assert "R_Ω" in out
    assert "R_p" in out
    assert "分解" in out


def test_write_prompt_anomaly_discussion():
    """Q：反常数据必须讨论（还原气氛电导下降/第二相/高温共烧）。"""
    out = render_prompt("write", _write_ctx())
    assert "待实验验证" in out
    assert "反常" in out


def test_write_prompt_figure_plan():
    """R：Figure 清单 ≥2 张示意图（Schematic），数据图无实测须标"待实验获取"。"""
    out = render_prompt("write", _write_ctx())
    assert "Schematic" in out
    assert "待实验获取" in out
    assert "Figure" in out


def test_review_prompt_seventh_dimension_figures():
    """七维评审：维度 7 图件完整性 + 维度 2 的 ASR/密度/电阻分解提示。"""
    out = render_prompt("review", {"topic": "t", "draft_text": "d"})
    assert "图件完整性" in out
    assert "待实验获取" in out
    assert "ASR = L/σ" in out
    assert "R_Ω" in out
    assert "逐样品" in out
