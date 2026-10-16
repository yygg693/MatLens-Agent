# -*- coding: utf-8 -*-
"""用一份覆盖多种图型的合成数据，验证第一级绘图链（真实出图，渲染肉眼可查）。"""
import json
import os
import sys

sys.path.insert(0, r"D:\MatLens")
os.chdir(r"D:\MatLens")
os.environ.setdefault("MPLBACKEND", "Agg")

from matlens_kit.paper.fig_gen import gen_figures

TABLES = [
    # 1) σ vs T（两气氛 × 两组分）
    {"name": "GDC20-Ca2 / 空气", "caption": "电导率随温度变化（空气，EIS）",
     "columns": ["温度 (°C)", "σ (S·cm⁻¹)"], "rows": [[600, 0.00698], [650, 0.0182], [700, 0.0421]]},
    {"name": "GDC20 / 空气", "caption": "电导率随温度变化（空气，EIS）",
     "columns": ["温度 (°C)", "σ (S·cm⁻¹)"], "rows": [[600, 0.00621], [650, 0.0165], [700, 0.0403]]},
    {"name": "GDC20-Ca2 / 5%H₂-Ar", "caption": "电导率随温度（还原气氛）",
     "columns": ["温度 (°C)", "σ (S·cm⁻¹)"], "rows": [[600, 0.0022], [650, 0.0071], [700, 0.0198]]},
    # 2) 密度 + 收缩率
    {"name": "GDC20-Ca2", "caption": "致密化与显微结构",
     "columns": ["烧结温度 (°C)", "相对密度 (%)", "线收缩率 (%)"],
     "rows": [[1250, 89.4, 12.1], [1300, 97.9, 14.3], [1350, 98.6, 15.0]]},
    {"name": "GDC20", "caption": "致密化对照",
     "columns": ["烧结温度 (°C)", "相对密度 (%)", "线收缩率 (%)"],
     "rows": [[1250, 71.2, 10.8], [1300, 89.2, 12.6], [1400, 97.5, 14.9]]},
    # 3) I-V / I-P
    {"name": "Cell-1 / 600 °C", "caption": "单电池功率特性",
     "columns": ["电流密度 (A·cm⁻²)", "功率密度 (W·cm⁻²)", "电压 (V)"],
     "rows": [[0, 0, 0.940], [0.2, 0.181, 0.902], [0.5, 0.430, 0.842],
              [0.8, 0.615, 0.769], [1.0, 0.690, 0.690]]},
    # 4) 稳定性（含评审质疑的数量级陷阱：100h 掉 12mV）
    {"name": "Cell-1 / 600 °C", "caption": "100 h 恒流稳定性",
     "columns": ["时间 (h)", "电压 (V)", "电流密度 (A·cm⁻²)"],
     "rows": [[0, 0.802, 0.5], [20, 0.798, 0.5], [50, 0.794, 0.5],
              [80, 0.791, 0.5], [100, 0.790, 0.5]]},
    # 5) σ_e–pO₂
    {"name": "GDC20-Ca2 / 600 °C", "caption": "电子电导的氧分压依赖",
     "columns": ["pO₂ (atm)", "σ_e (S·cm⁻¹)"],
     "rows": [[1e-25, 1.9e-4], [1e-22, 1.4e-3], [1e-20, 8.6e-3], [1e-18, 4.1e-2]]},
    # 6) XRD
    {"name": "GDC20", "caption": "XRD 物相",
     "columns": ["2θ (°)", "强度 (a.u.)"],
     "rows": [[28.2, 320], [33.1, 180], [47.5, 410], [56.6, 210],
              [59.4, 150], [69.6, 260], [79.6, 120]]},
]

WRITE = """# 3结果与讨论

**图 1** X射线衍射全谱与 (111) 峰位移放大（室温 Cu Kα）；GDC20 与 GDC20-Ca2 对照。

**图 2** 线收缩率与相对密度随烧结温度的变化（GDC20-Ca2 与 GDC20 对照，1250–1400 °C）。

**图 3** σT 随 1000/T 的 Arrhenius 图（体相与晶界分列，空气，500–700 °C）。

**图 4** 600 °C 下的 I–V 与 I–P 曲线（Cell-1，6 μm GDC-Ca 电解质）。

**图 5** 100 h 恒流稳定性曲线（0.5 A·cm⁻²，600 °C）。

**图 6** Hebb-Wagner 极化曲线与 σ_e 随 pO₂ 的变化（600 °C）。

**图 7** 电导率随温度变化（空气与 5% H₂–Ar，GDC20-Ca2 与 GDC20 对照）。

**图 8** 阳极支撑单电池截面构型示意（NiO-GDC 支撑体 / 6 μm 电解质 / LSCF-GDC 阴极）。
"""

out_dir = r"D:\MatLens\_fig_test"
res = gen_figures(WRITE, out_dir, experimental_data={"status": "measured", "tables": TABLES})

print(f"{'图':<4}{'类型':<11}{'谱系':<16}{'状态':<11}{'原因/指标'}")
print("-" * 96)
for r in res:
    metric = ""
    if r.get("metrics"):
        metric = json.dumps(r["metrics"], ensure_ascii=False)[:60]
    print(f"图{r['num']:<3}{r['kind']:<11}{str(r.get('scheme')):<16}"
          f"{r['status']:<11}{(r.get('reason') or metric)[:58]}")
gen = sum(1 for r in res if r["status"] == "generated")
print(f"\n生成 {gen}/{len(res)}张")
print("输出目录:", out_dir)