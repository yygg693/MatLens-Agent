# -*- coding: utf-8 -*-
"""学术评审级质检（quality.py）+ 占位引用检测（enforce_refs.py）单测。

纯本地规则、无网络、不调 LLM。覆盖 DeepSeek 评审 8 条意见对应的坑：
数据占位 / 数值自洽 / 强声称无证据 / 缺对照 / 缺文献对比 / 100h 过度稳定 /
{A-n} 占位引用绕过白名单。
"""
from __future__ import annotations

from matlens_kit.paper.enforce_refs import (
    check_refs_whitelist,
    detect_placeholder_citations,
    parse_citation_ids,
)
from matlens_kit.paper.quality import check_quality, render_report


# ═══════════════════════════════════════════════════════════════════
# enforce_refs：{A-n} 占位引用检测
# ═══════════════════════════════════════════════════════════════════

class TestDetectPlaceholderCitations:
    def test_detects_all_specified_forms(self):
        text = "背景见{A-1}，方法{A1}，对照{a-3}，文献{X-10}"
        assert detect_placeholder_citations(text) == ["{A-1}", "{A1}", "{a-3}", "{X-10}"]

    def test_no_false_match_on_plain_braces_without_digits(self):
        # {TBD} / 空花括号不应被识别为占位引用
        assert detect_placeholder_citations("结论{TBD} 与 {} 正常文本") == []

    def test_parse_citation_ids_only_reads_bracket_n(self):
        # {A-n} 不参与 [n] 引用计数（语义不变）
        assert parse_citation_ids("见{A-1}和[2,3]，另有{X-10}") == [2, 3]


class TestCheckRefsWhitelistPlaceholder:
    def test_placeholder_issue_fires(self):
        issues = check_refs_whitelist("电解质背景{A-1}，方法见{A-2}", [])
        placeholder = [i for i in issues if "占位引用格式" in i["issue"]]
        assert placeholder, "正文含 {A-1} 必须给出占位引用 issue"
        assert placeholder[0]["severity"] == "🔴"
        assert placeholder[0]["location"] == "引用越界"

    def test_whitelist_empty_placeholder_adds_yellow_guidance(self):
        issues = check_refs_whitelist("见{A-1}", [])
        yellows = [i for i in issues if i["severity"] == "🟡" and "白名单为空" in i["issue"]]
        assert yellows, "白名单为空时应追加「先完成检索」🟡 指引"

    def test_whitelist_nonempty_placeholder_red_only(self):
        refs = [{"x": 1}, {"x": 2}]
        issues = check_refs_whitelist("见{A-1}，另引[2]", refs)
        reds = [i for i in issues if i["severity"] == "🔴"]
        # 占位符 🔴；[2] 在白名单内不越界
        assert any("占位引用格式" in i["issue"] for i in reds)
        assert not any("白名单为空" in i["issue"] for i in issues)

    def test_whitelist_empty_bracket_n_stays_yellow(self):
        # 既有行为保留：白名单空 + 正文 [n] -> 🟡（无占位符时）
        issues = check_refs_whitelist("见[1]所述方法", [])
        assert issues and issues[0]["severity"] == "🟡"
        assert "白名单为空" in issues[0]["issue"]


# ═══════════════════════════════════════════════════════════════════
# quality.py：学术评审级维度
# ═══════════════════════════════════════════════════════════════════

#: SOFC 风格「问题草稿」——刻意埋入 DeepSeek 评审指出的坑
BAD_DRAFT = """# 中温 SOFC 电解质研究

## 引言
中温固体氧化物燃料电池电解质研究见{A-1}。

## 方法
本文制备了电解质薄膜并完成电化学测试。

## 结果
电子电导 σ_e = 0.005 S cm⁻¹，离子迁移数 t_ion = 0.98。
We identified as the governing mechanism the grain-boundary impurity scavenging.
电池在 600 °C 下实现 stable operation over 100 h，性能优于 reported GDC cells。

## 讨论
与 reported cells 相比，本文 OCV 数值更高。

## 结论
结果汇总见表 1。

| Sample | σ_e | t_ion | Note |
|---|---|---|---|
| A | — | — | — |
| B | — | — | — |
"""

#: 健康草稿——拟议值标注 / 弱声称 / 有对照 / 有文献对比 / 短期表述，白名单 2 条
HEALTHY_REFS = [{"doi": "10.1/a"}, {"doi": "10.1/b"}]
HEALTHY_DRAFT = """# 中温 SOFC GDC 电解质研究

## 引言
GDC 电解质在中温固体氧化物燃料电池中应用广泛[1]，其电子漏电与晶界电阻是核心瓶颈。

## 方法
采用共沉淀法制备 Ce0.8Gd0.2O2 粉体；以 undoped GDC 为 baseline 对照（σ_total = 0.015 S/cm、OCV = 0.90 V 已测），并设置 x=0.0 的组分系列。结构表征包括 XPS、STEM-EDS 面扫、TGA 热重以及 EIS 配合 DRT 分析，所有数据均给出三次重复的误差棒。

## 结果
XRD confirmed 单相萤石结构，且 XPS 测得 Ce 3d 价态分布。σ_e = 0.008 S cm⁻¹，
t_ion = 0.97；σ_ion = t_ion × σ_total 已由 brick-layer 模型给出数值演算，两数自洽。
以 reference GDC 为对照，其 σ_total = 0.015 S/cm、OCV = 0.90 V，共掺杂样品晶界电阻下降约 40%（拟议值，待实验确认）。
600 h long-term 运行电压衰减小于 2 mV/100 h；100 h short-term 测试已完成。

## 讨论
与 reported GDC cells[2]（600 °C、300 µm、湿 H2）相比，本文 OCV 与 PPD 处于同一区间。
机制上我们 proposed 空间电荷层调制与杂质清除耦合，与 XPS/STEM-EDS 证据 consistent with。

## 结论
上述结果 proposed 为协同改性路径，长期稳定性仍需 500–1000 h 数据补充。

| Sample | σ_e (S/cm) | t_ion | Ref |
|---|---|---|---|
| This work | 0.008 | 0.97 | [2] |
| GDC baseline | 0.015 | 0.90 | [1] |
"""


def _locs(check):
    return [(i["severity"], i["location"]) for i in check["issues"]]


class TestBadDraftTriggersAcademicDimensions:
    def setup_method(self):
        self.check = check_quality(BAD_DRAFT, refs=[])

    def test_placeholder_citation_red(self):
        assert any(loc == "引用越界" and sev == "🔴"
                   for sev, loc in _locs(self.check))

    def test_data_table_placeholder_red(self):
        data = [i for i in self.check["issues"] if i["location"] == "数据" and i["severity"] == "🔴"]
        assert data, "表格 ≥6 处 — 应出 🔴 数据 issue"

    def test_overclaim_without_evidence(self):
        claims = [i for i in self.check["issues"] if i["location"] == "声称"]
        assert claims, "identified/governing 强声称无证据应出 🟡"

    def test_short_stability_overclaim(self):
        stab = [i for i in self.check["issues"] if i["location"] == "稳定性"]
        assert stab, "stable operation over 100 h 应出 🟡"

    def test_missing_control(self):
        ctrl = [i for i in self.check["issues"] if i["location"] == "对照"]
        assert ctrl, "无对照样品应出 🟡"

    def test_weak_literature_comparison(self):
        lit = [i for i in self.check["issues"] if i["location"] == "文献对比"]
        assert lit, "笼统 reported 无 [n] 应出 🟡"

    def test_numerical_self_consistency_yellow(self):
        # σ_e≤0.01 且 t_ion≥0.95，但草稿无 ionic conductivity/σ_total/计算支撑
        num = [i for i in self.check["issues"] if i["location"] == "数值自洽"]
        assert num, "缺总电导/计算过程应出 🟡"


class TestHealthyDraftHasNoRedAcademic:
    def setup_method(self):
        self.check = check_quality(HEALTHY_DRAFT, refs=HEALTHY_REFS)

    def test_no_red_at_all(self):
        reds = [i for i in self.check["issues"] if i["severity"] == "🔴"]
        assert not reds, f"健康草稿不应有 🔴，实际：{reds}"

    def test_no_academic_yellow_in_new_dimensions(self):
        new_locs = {"数据", "数值自洽", "声称", "对照", "文献对比", "稳定性"}
        offenders = [i for i in self.check["issues"] if i["location"] in new_locs]
        assert not offenders, f"健康草稿新维度应无 issue，实际：{[(i['location'], i['issue']) for i in offenders]}"


class TestRenderReport:
    def test_report_contains_new_dimensions(self):
        check = check_quality(BAD_DRAFT, refs=[])
        report = render_report(check)
        assert "质量巡检报告" in report
        assert "问题清单" in report
        # 新维度的 location 应出现在渲染结果里
        assert "**🟡 声称**" in report or "**🔴 数据**" in report
        assert "质量评分" in report

    def test_summary_lists_covered_dimensions(self):
        check = check_quality(BAD_DRAFT, refs=[])
        assert "覆盖维度" in check["summary"]
        assert "稳定性" in check["summary"]


# ═══════════════════════════════════════════════════════════════════
# 第二轮：化学常识 / 比例-活化能 / 百分比换算 / 对照完整性 / 统计力
# ═══════════════════════════════════════════════════════════════════

#: v2 问题草稿——埋入 DeepSeek 第二轮指出的 5 类自洽/常识缺陷
V2_BAD = """# Gd 掺杂 CeO2 电解质研究

## 摘要
600 °C OCV = 0.96 V，100 h 电压衰减 12 ± 4 μV·h⁻¹（相对 100 h 约 0.2%）。

## 1 引言
Gd 掺杂 CeO2 用于中温 SOFC[1]。以 Ca 共掺样 CG-1、1 mol% Co 助剂样 GDC-0.10Co、
GDC/YSZ 双层为对照路线。

## 2 方法
XRD Rietveld 精修。

## 3 结果
晶格常数随 Gd 含量增加而单调下降，与 Gd³⁺ 半径小于 Ce⁴⁺ 的取代关系一致。

| T | σ_bulk | σ_gb | σ_total |
|---|---|---|---|
| 500 °C | 0.0101 | 0.0201 | 0.0067 |
| 600 °C | 0.0300 | 0.0600 | 0.0200 |
| 700 °C | 0.0960 | 0.1920 | 0.0640 |
| Ea_bulk / Ea_gb | 0.78 / 1.02 | — | — |

CG-1 仅做了 STEM-EDS 晶界 Ca 富集观察；GDC-0.10Co 仅测了相对密度 99.0%。
单电池 OCV = 0.96 V（n = 2 电芯），PPD = 0.82 W/cm²（n = 2 电芯）。

## 4 讨论
机制 proposed。

## 5 结论
短期耐久。
"""

#: v2 健康草稿——Gd 晶格增大 / 比例随温度变化 / 0.125% 正确 / 对照全维度 / n=5
V2_HEALTHY = """# Gd 掺杂 CeO2 电解质研究

## 摘要
600 °C OCV = 0.96 V，100 h 电压衰减 12 μV·h⁻¹（相对 OCV 0.96 V 约 0.125%）。

## 1 引言
Gd 掺杂 CeO2 用于中温 SOFC[1]。以 undoped GDC 为 baseline 对照。

## 2 方法
XRD Rietveld 精修。

## 3 结果
晶格常数随 Gd 含量增加而单调增大，与 Gd³⁺ 半径大于 Ce⁴⁺ 一致。

| T | σ_bulk | σ_gb | σ_total |
|---|---|---|---|
| 500 °C | 0.010 | 0.020 | 0.0067 |
| 600 °C | 0.030 | 0.055 | 0.018 |
| 700 °C | 0.096 | 0.150 | 0.058 |
| Ea_bulk / Ea_gb | 0.78 / 1.02 | — | — |

σ_gb/σ_bulk 比例从 2.0 降至 1.56，随温度升高而变化。
undoped baseline 的 σ_total = 0.015 S/cm、OCV = 0.90 V、PPD = 0.60 W/cm² 已测。
单电池 OCV = 0.96 V（n = 5），PPD = 0.82 W/cm²（n = 5）。

## 4 讨论
与 reported cells[2] 对比。机制 proposed。

## 5 结论
结果 proposed。

| Sample | σ_e | OCV | PPD |
|---|---|---|---|
| This work | 0.0008 | 0.96 | 0.82 |
| baseline | 0.0045 | 0.90 | 0.60 |
"""


class TestV2BadDraftTriggersNewDimensions:
    def setup_method(self):
        self.check = check_quality(V2_BAD, refs=[{"x": 1}, {"x": 2}])

    def _locs(self):
        return [(i["severity"], i["location"]) for i in self.check["issues"]]

    def test_chem_fact_gd_lattice(self):
        chem = [i for i in self.check["issues"] if i["location"] == "化学事实"]
        assert chem, "Gd 晶格下降 + 半径小于 应出 🟡 化学事实"

    def test_ratio_activation_energy(self):
        num = [i for i in self.check["issues"]
               if i["location"] == "数值自洽" and "比例" in i["issue"]]
        assert num, "Ea 不同但 σ 比例恒定 应出 🟡"

    def test_percent_calc(self):
        num = [i for i in self.check["issues"]
               if i["location"] == "数值自洽" and "换算" in i["issue"]]
        assert num, "12 μV/h×100h≈0.125% vs 0.2% 应出 🟡"
        assert "0.125" in num[0]["issue"]

    def test_incomplete_control(self):
        ctrl = [i for i in self.check["issues"] if i["location"] == "对照" and "缺少" in i["issue"]]
        assert ctrl, "CG-1/GDC-0.10Co 缺性能数据 应出 🟡"

    def test_low_sample_size(self):
        data = [i for i in self.check["issues"]
                if i["location"] == "数据" and "样本量" in i["issue"]]
        assert data, "n=2 与 OCV/PPD 同现 应出 🟡"


class TestV2HealthyDraftNoNewDimensions:
    def setup_method(self):
        self.check = check_quality(V2_HEALTHY, refs=[{"x": 1}, {"x": 2}])

    def test_no_chem_fact(self):
        assert not [i for i in self.check["issues"] if i["location"] == "化学事实"]

    def test_no_ratio_ea_issue(self):
        assert not [i for i in self.check["issues"]
                    if i["location"] == "数值自洽" and "比例" in i["issue"]]

    def test_no_percent_mismatch(self):
        assert not [i for i in self.check["issues"]
                    if i["location"] == "数值自洽" and "换算" in i["issue"]]

    def test_no_low_n(self):
        assert not [i for i in self.check["issues"]
                    if i["location"] == "数据" and "样本量" in i["issue"]]

    def test_no_incomplete_control(self):
        assert not [i for i in self.check["issues"]
                    if i["location"] == "对照" and "缺少" in i["issue"]]


# ═══════════════════════════════════════════════════════════════════
# N.R./N.D./not reported 是学术规范的"未报道"标注，不应计为空占位
# ═══════════════════════════════════════════════════════════════════

#: 文献对比表：本工作数据齐全，对比文献大量 N.R. 属诚实标注
COMPARISON_TABLE_NR = """# GDC 电解质对比研究

## 结果
本工作 600 °C OCV = 0.96 V、PPD = 0.82 W/cm²。

| Sample | σ_e (S/cm) | t_ion | OCV (V) | 燃料 | Ref |
|---|---|---|---|---|---|
| This work | 0.008 | 0.97 | 0.96 | 湿 H2 | [1] |
| Ref A | N.R. | N.R. | 0.82 | 空气 | [2] |
| Ref B | n.d. | n.d. | N. R. | N.R. | [3] |
| Ref C | not reported | Not Reported. | — | H2 | [4] |
| Ref D | 未报道 | 1.0 | 0.85 | H2 | [5] |
"""

#: 我方数据表里大量裸 — 是真糊弄（≥6 处应出 🔴）
OWN_TABLE_BAD = """# GDC 电解质研究

## 结果
| Sample | σ_e | t_ion | OCV | PPD | ASR |
|---|---|---|---|---|---|
| 1# | — | — | — | — | — |
| 2# | — | — | — | — | — |
"""


class TestNotReportedNotCountedAsPlaceholder:
    def test_comparison_table_with_nr_no_red_placeholder(self):
        chk = check_quality(COMPARISON_TABLE_NR, refs=[{"x": i} for i in range(6)])
        red_data = [i for i in chk["issues"] if i["location"] == "数据" and i["severity"] == "🔴"]
        assert not red_data, f"N.R./not reported 不应触发 🔴 空占位，实际：{red_data}"

    def test_own_table_bare_dash_still_red(self):
        chk = check_quality(OWN_TABLE_BAD, refs=[{"x": i} for i in range(2)])
        red_data = [i for i in chk["issues"] if i["location"] == "数据" and i["severity"] == "🔴"]
        assert red_data, "我方表格 12 处裸 — 应出 🔴"

    def test_unreported_pattern_unit(self):
        from matlens_kit.paper.quality import _table_cell_placeholder_count
        # N.R./N.D./not reported/未报道/空白变体都应被识别为"未报道"而非占位
        draft = "| a | N.R. | N. R. | n.d. | Not Reported | 未报道 |\n"
        assert _table_cell_placeholder_count(draft) == 0, "所有 N.R. 变体不应计占位"


# ═══════════════════════════════════════════════════════════════════
# 第三轮：厚度-ASR 换算 / 理论密度共用 / 图件缺失 / 跨表电阻未分解
# ═══════════════════════════════════════════════════════════════════

#: v3 问题草稿——埋入厚度-ASR 100× 矛盾、共用 M/a、图件缺失、电阻未分解
V3_BAD = """# GDC-Ca 电解质研究

## 摘要
600 °C σ_total = 1.99×10⁻² S·cm⁻¹，对称电池 ASR_total = 0.047 Ω·cm²，
单电池 ASR = 0.25 Ω·cm²，电解质厚度 6 μm。

## 方法
对称电池厚度 L = 0.1 cm。理论密度由 M = 173.94 g·mol⁻¹ 与 a = 5.4236 Å 算得。

## 结果
| Sample | σ_total | ASR_total |
|---|---|---|
| GDC20-Ca2 | 1.99×10⁻² | 0.047 |
| GDC20-1400 | 1.43×10⁻² | 0.060 |
| GDC20-1Co | 1.76×10⁻² | 0.055 |
| GDC20-Ca5 | 1.76×10⁻² | 0.058 |
| GDC20 | 1.43×10⁻² | 0.062 |

图 1 XRD；Fig 2 Arrhenius；Fig 3 Nyquist。
单电池 ASR = 0.25 Ω·cm²（EIS 测得）。

## 讨论
机制 proposed。
"""

#: v3 健康草稿——统一厚度基准 / 逐样品 M/a / 图注带 Schematic 与待实验获取 / R_Ω 分解
V3_HEALTHY = """# GDC-Ca 电解质研究

## 摘要
600 °C σ_total = 1.99×10⁻² S·cm⁻¹，对称电池（L = 0.1 cm）ASR = 5.0 Ω·cm²（R_Ω = 5.0，R_p 见下）。
单电池电解质厚度 100 μm，ASR = 0.50 Ω·cm²（R_Ω = 0.50，R_p = 0.30）。

## 方法
理论密度逐样品计算：GDC20-Ca2 用 M = 173.94 g·mol⁻¹、a = 5.4236 Å；
GDC20-1400 用 M = 173.94、a = 5.4120 Å；GDC20-1Co 用 M = 180.5、a = 5.4310 Å。

## 结果
| Sample | σ_total | R_Ω | R_p |
|---|---|---|---|
| GDC20-Ca2 | 1.99×10⁻² | 5.0 | 0.5 |
| GDC20-1400 | 1.43×10⁻² | 7.0 | 0.6 |

图 1 XRD（Schematic 示意图，待实验获取）；Fig 2 Arrhenius（待实验获取）。
单电池 ASR = 0.50 Ω·cm²，R_Ω 与 R_p 已分解。

## 讨论
机制 proposed。
"""


class TestV3BadDraftTriggersNewDimensions:
    def setup_method(self):
        self.check = check_quality(V3_BAD, refs=[{"x": i} for i in range(3)])

    def test_thickness_asr_red(self):
        red = [i for i in self.check["issues"]
               if i["location"] == "数值自洽" and i["severity"] == "🔴" and "ASR" in i["issue"]]
        assert red, "L=0.1cm σ=0.02 应得 ASR≈5 vs 报告 0.047（100×）→ 🔴"

    def test_shared_theoretical_density(self):
        data = [i for i in self.check["issues"]
                if i["location"] == "数据" and "理论密度" in i["issue"] or "M" in i["issue"] and "a" in i["issue"]]
        assert data, "单一 M/a 用于多样品相对密度 → 🟡"

    def test_figure_missing(self):
        fig = [i for i in self.check["issues"] if i["location"] == "图件"]
        assert fig, "Fig N 引用但无图/Schematic/待实验获取 → 🟡"

    def test_cross_table_resistance(self):
        num = [i for i in self.check["issues"]
               if i["location"] == "数值自洽" and "R_Ω" in i["issue"]]
        assert num, "对称+单电池 ASR 并存无 R_Ω/R_p 分解 → 🟡"


class TestV3HealthyDraftNoNewDimensions:
    def setup_method(self):
        self.check = check_quality(V3_HEALTHY, refs=[{"x": i} for i in range(3)])

    def test_no_thickness_asr_red(self):
        assert not [i for i in self.check["issues"]
                    if i["location"] == "数值自洽" and i["severity"] == "🔴" and "ASR" in i["issue"]]

    def test_no_shared_density(self):
        assert not [i for i in self.check["issues"]
                    if i["location"] == "数据" and ("M" in i["issue"] and "a" in i["issue"])]

    def test_no_figure_missing(self):
        assert not [i for i in self.check["issues"] if i["location"] == "图件"]

    def test_no_cross_table_issue(self):
        assert not [i for i in self.check["issues"]
                    if i["location"] == "数值自洽" and "R_Ω" in i["issue"]]


# ═══════════════════════════════════════════════════════════════════
# 厚度-ASR 多基准豁免：1 mm 对称片 + 6 μm 单电池 + 折算说明
# ═══════════════════════════════════════════════════════════════════

#: 双基准 + 折算说明 → 不应报 🔴
MULTI_BASELINE_WITH_NOTE = """# GDC 电解质研究

## 摘要
600 °C σ_total = 2.00×10⁻² S·cm⁻¹；对称电池片厚度 1 mm，ASR = 5.0 Ω·cm²；
单电池电解质厚度 6 μm，ASR = 0.25 Ω·cm²。两套厚度基准已在表 6 中给出折算对应关系：
对称电池 ASR 按 L=1 mm 折算，单电池 ASR 按 L=6 μm 折算到 L/σ。

## 结果
机制 proposed。
"""

#: 双基准但无折算说明 → 仍应报 🔴（建议改为明确折算关系）
MULTI_BASELINE_NO_NOTE = """# GDC 电解质研究

## 摘要
600 °C σ_total = 2.00×10⁻² S·cm⁻¹；对称电池片厚度 1 mm，ASR = 0.047 Ω·cm²；
单电池电解质厚度 6 μm，ASR = 0.25 Ω·cm²。

## 结果
机制 proposed。
"""


class TestThicknessASRMultiBaselineExemption:
    def test_two_baselines_with_note_no_red(self):
        chk = check_quality(MULTI_BASELINE_WITH_NOTE, refs=[{"x": 1}])
        red = [i for i in chk["issues"]
               if i["location"] == "数值自洽" and i["severity"] == "🔴" and "ASR" in i["issue"]]
        assert not red, f"双基准+折算说明应豁免 🔴，实际：{red}"

    def test_two_baselines_without_note_still_red(self):
        chk = check_quality(MULTI_BASELINE_NO_NOTE, refs=[{"x": 1}])
        red = [i for i in chk["issues"]
               if i["location"] == "数值自洽" and i["severity"] == "🔴" and "ASR" in i["issue"]]
        assert red, "双基准但无折算说明应仍报 🔴"
        assert "折算" in red[0]["suggestion"], "建议应提示明确两套基准的折算关系"
