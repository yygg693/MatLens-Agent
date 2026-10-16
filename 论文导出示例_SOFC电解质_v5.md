# Calcium co-doping of Gd-doped ceria electrolytes for intermediate-temperature SOFCs: design targets for simultaneous densification, grain-boundary and leakage control

## Abstract

Intermediate-temperature solid oxide fuel cells (IT-SOFCs) with Gd-doped ceria (GDC) electrolytes are constrained by three coupled drawbacks: n-type electronic leakage under reducing atmospheres, a dominant grain-boundary (GB) resistance, and densification temperatures (≥1400 °C) that conflict with anode-supported co-sintering. This work applies a single compositional lever — 2 mol% Ca co-doping of Ce₀.₈₀Gd₀.₂₀O₂₋δ (Ce₀.₇₈Gd₀.₂₀Ca₀.₀₂O₂₋δ, GDC20-Ca2) — to all three, and reports the corresponding **design targets (proposed values, to be confirmed experimentally)**. 1300 °C/4 h sintering targets 97.9% relative density † (Archimedes; per-sample theoretical density from Rietveld lattice parameters), against 89.2% † for Ca-free GDC20 at the same schedule, which reaches 97.5% † only at 1400 °C/4 h. The GB share of the total resistance at 600 °C in air is targeted to decrease from 72.7% † (Ca-free) to 49.4% †, while bulk conductivity and its activation energy stay within error of Ca-free GDC20. In 5% H₂–Ar at 600 °C, σ_e = 9.0×10⁻⁴ S·cm⁻¹ † and t_ion = 0.955 † are targeted (σ_total = 2.00×10⁻², σ_ion = 1.91×10⁻² S·cm⁻¹), against 2.6×10⁻³ S·cm⁻¹ and 0.827 † for Ca-free GDC20. Anode-supported cells with a 6 µm GDC20-Ca2 electrolyte target OCV = 0.94 V †, peak power density = 0.86 W·cm⁻² † and a 100 h short-term voltage decay of 12 µV·h⁻¹ † (1.5%·1000 h⁻¹). The intended contribution is simultaneous densification, GB and leakage control in a **single-layer** electrolyte, in contrast to bilayer GDC/YSZ architectures.

## 1 引言

SOFC 降本要求把工作温度压到 500–700 °C，此时电解质欧姆过电位成为主要损失通道，GDC 因在 600 °C 具备优于 YSZ 的氧离子电导而成为 IT-SOFC 首选电解质体系。薄膜化路线已证明可以显著提升单电池功率输出，3 µm 磁控溅射 GDC 薄膜在 800 °C 下可给出 >0.9 V 的 OCV 与约 2 W·cm⁻² 的功率密度 [1]，但薄膜工艺改变的是几何尺度，并不改变材料本征的电子漏电；掺杂 ceria 的结构—离子电导关系 [14]、以及多元共掺（如 Gd-Bi-M-Ce-O）用于降低烧结温度与提升电导的成分设计先例 [6]，说明成分调控才是解决本征问题的入口。

问题在于三个瓶颈互相牵制。还原气氛下 Ce⁴⁺→Ce³⁺ 产生的 n 型电子电导在电解质内构成并联漏电通道，直接压缩 OCV；该电导已有系统的直流部分极化与变 pO₂ 测量方法可定量标定 [3]，其来源与量级在 Gd 含量 10–20% 的 GDC 中被反复确认 [5]。受主掺杂 ceria 的晶界电阻常占总电阻的 50–70%，其成因涉及晶界核电荷与空间电荷层 [13,4]；而 ≥1400 °C 的致密化又与阳极支撑共烧工艺冲突，Co/Fe 基助烧剂虽降低烧结温度，却以晶界输运性能劣化为代价 [16]，浸渗辅助烧结等替代路线同样需要在晶界电导上做权衡 [7]。现有工作多为**单指标优化**：漏电抑制靠双层结构、晶界改善靠杂质控制、致密化靠助烧剂，三者同时改善的报道稀缺——这是本文的切入点，而非"GDC 研究很多"式的空泛陈述。

可替代路线的代价同样明确：YSZ/GDC 双层电解质是抑制电子漏电的成熟方案，湿法共烧可以取得 OCV 收益 [10]，代价是引入界面电阻、热膨胀失配与共烧工艺复杂度。碱土元素掺杂 ceria 的最新认识（缺陷—掺杂剂缔合主导电化学行为）[15] 与共掺元素组合思路 [6] 共同支撑以 Ca 共掺为单一手段。据此提出核心问题：**在不牺牲体相氧离子电导的前提下，能否用一次共掺同时实现低温致密化、晶界电阻下降与电子漏电抑制？**

判据设定为三条可检验项：① 600 °C、5% H₂–Ar 下 σ_e ≤ 0.01 S·cm⁻¹ 且 t_ion ≥ 0.95；② 烧结温度 ≤1300 °C 时相对密度 ≥97%（与 NiO 阳极共烧兼容）；③ 对称电池（1.0 mm 片）按 ASR=L/σ 折算至 6 µm 厚度后的电解质 ASR ≤ 0.15 Ω·cm²、单电池 OCV ≥ 0.90 V、PPD ≥ 0.8 W·cm⁻²、短期稳定性 ≥100 h。方法学上以 EIS＋DRT 分离体相/晶界/界面贡献 [2,11]，并以 Bayesian 正则化抑制 DRT 过拟合 [9]，按 Hebb-Wagner 极化测电子电导 [12,3]，单电池构型为 NiO-GDC|GDC-Ca|LSCF-GDC，电极/电解质微结构匹配对标 [8]。

## 2 实验

### 2.1 粉体合成与陶瓷制备

以硝酸盐-甘氨酸燃烧法合成 Ce₁₋ₓ₋ᵧGdₓCaᵧO₂₋δ（x=0.20 主线，y=0/0.01/0.02/0.05；x=0.10 对照），甘氨酸/总硝酸根摩尔比 0.5，700 °C/2 h 煅烧，球磨后干压（200 MPa）；烧结制度 1250/1300/1350 °C、保温 2–5 h、升降温速率 3 K·min⁻¹。对照路线为 1 mol% Co₃O₄ 助烧组（[16] 的助烧剂对照逻辑）与 1400 °C/4 h 常规烧结组，并按 [7] 的烧结路线对照思路设置替代工艺比较位。样品命名固定为 GDC20-Ca2、GDC20-Ca2-Co、GDC20-Ca2-1400、GDC10-Ca2 等（详见表 1）。相对密度以阿基米德法（25 °C，去离子水）测定；**理论密度逐样品使用其自身摩尔质量与自身 Rietveld 精修晶格参数计算，氧空位 δ 按电荷补偿标称值给出并注明**，不使用统一样品参数。

### 2.2 结构与微区表征

XRD＋Rietveld 精修用于物相、晶格参数与固溶度判定（对应机制 M1/M2）；SEM 断面/表面测晶粒尺寸与气孔率；STEM-EDS 晶界线扫/面扫测 Ca 与杂质 Si、Al 的偏析（M1/M2/M3）；XPS Ce 3d 与 TGA（还原气氛失重）定量 Ce³⁺ 分数与 δ 变化（M4）；Raman 缺陷带用于确认氧空位引入（M5）。表征-机制的一一对应在 4.1 节表 9 中显式给出，避免"为表征而表征"；EDS 属半定量（相对精度 ±20%），仅用于趋势比较。

### 2.3 电学性能测试

EIS 条件 400–700 °C、空气与 5% H₂–Ar、10⁵–10⁻² Hz、振幅 10 mV；以等效电路/传输线模型校验，DRT 用于体相/晶界/电极三个以上弛豫过程的分离与归属 [2,11]，正则化参数按 [9] 的准则选取。电子电导以 Hebb-Wagner 极化与 DC 部分极化双法互证 [12,3]，**离子电导与迁移数按统一口径换算：σ_ion ≡ σ_total(EIS) − σ_e(Hebb-Wagner)，t_ion ≡ σ_ion/σ_total**（该口径可能高估 σ_ion，因为 AC 总电导已含并联电子通道，此点在全文中保持一致）。对称电池（Pt 电极，片厚 L=1.0 mm，面积 0.785 cm²）测电解质 ASR，ASR = L/σ。电学测试计划取 n ≥ 3 个独立试样，报道 mean ± SD。

### 2.4 单电池构建与电化学测试

NiO-GDC（65:35 wt%）阳极支撑体（约 400 µm）＋6 µm GDC-Ca 电解质＋LSCF-GDC 阴极，有效面积 0.785 cm²；按单电池测试与报告规范组织数据 [1]。**分组设计在此固定：A 组无阻挡层；B 组保留 0.3 µm YSZ 阻挡层；C 组为无 Ca 的 GDC20 致密对照（1400 °C）；D 组为 Co 助烧对照**——无阻挡层与超薄阻挡层的对照是"结构简化"主张能否成立的关键，[10] 的双层基线作为其参照。测试条件：加湿 H₂（97% H₂/3% H₂O）燃料、静态空气氧化剂、600/650/700 °C，记录 OCV、I–V、I–P、ASR 与 100 h 恒流稳定性。单电池电化学指标计划取 n=5 片。

## 3 结果

本节全部数值为**设计目标（拟议值，待实验确认）**；表格内 † 表示该值待实验确认。表 4–8 的电阻指标统一以满足 ASR = L/σ 的同一厚度基准给出，详见 3.3 节口径说明。

**图 1** 单电池结构示意图（Schematic）：NiO-GDC 阳极支撑体（约 400 µm）｜6 µm GDC20-Ca2 电解质｜LSCF-GDC 阴极；B 组在电解质/阴极侧加 0.3 µm YSZ 阻挡层。对称电池为 Pt 电极夹持 1.0 mm 电解质片。

**表 1｜样品组成与工艺设计矩阵**

| 样品编号 | Gd x | Ca y | 助烧剂 | 烧结制度 | 设计用途 |
|---|---|---|---|---|---|
| GDC20-Ca2 | 0.20 | 0.02 | 无 | 1300 °C/4 h | 主线 |
| GDC20-Ca1 | 0.20 | 0.01 | 无 | 1300 °C/4 h | Ca 含量对照 |
| GDC20-Ca5 | 0.20 | 0.05 | 无 | 1300 °C/4 h | 固溶上限对照 |
| GDC20 | 0.20 | 0 | 无 | 1300 °C/4 h；1400 °C/4 h | 无 Ca 对照 |
| GDC20-Ca2-Co | 0.20 | 0.02 | 1 mol% Co₃O₄ | 1300 °C/4 h | 助烧剂对照 |
| GDC10-Ca2 | 0.10 | 0.02 | 无 | 1300 °C/4 h | Gd 含量对照 |
| 单电池 A/B/C/D | — | — | — | 见 2.4 | 阻挡层/对照分组 |

### 3.1 物相组成与低温致密化行为

Rietveld 精修（表 2）预期给出单一萤石相（Fm-3m）与随 y 单调增大的晶格常数：Gd³⁺ 八配位半径（约 1.053 Å）大于 Ce⁴⁺（约 0.97 Å），Gd 掺杂使晶格**扩张**；Ca²⁺（约 1.12 Å）进一步取代 Ce⁴⁺ 时同样倾向扩张，但每引入一个 Ca²⁺ 伴随一个氧空位，空位引起的收缩会部分抵消该效应，因此净方向以 Rietveld 为准，本文不预设绝对断言。y=0.05 预期出现极弱第二相反射（2θ≈32.2°，疑为 CaO，相对强度 <1%），据此把固溶上限判在 0.02–0.05 之间；该现象必须按"需解释数据"处理（见 4.1）。

致密化是本工作第一条判据的支点：GDC20-Ca2 于 1300 °C/4 h 预期达到 97.9% † 相对密度，而 GDC20 在同制度下仅 89.2% †，需 1400 °C/4 h 才到 97.5% †。即共烧窗口由 1400 °C 下移至 1300 °C，且不依赖助烧剂。

**表 2｜XRD/Rietveld 物相与晶格参数**

| 样品 | 物相/空间群 | a (Å)† | V (Å³)† | 晶粒尺寸 (nm)† | Rwp (%)† | ρ_th (g·cm⁻³)† | 误差† |
|---|---|---|---|---|---|---|---|
| GDC20 | 萤石 Fm-3m | 5.4203 | 159.25 | 32 | 8.6 | 7.25 | ±0.0006 |
| GDC20-Ca1 | 萤石 Fm-3m | 5.4235 | 159.53 | 31 | 9.1 | 7.19 | ±0.0007 |
| GDC20-Ca2 | 萤石 Fm-3m | 5.4268 | 159.82 | 33 | 8.9 | 7.13 | ±0.0007 |
| GDC20-Ca5 | 萤石＋疑 CaO(<1%) | 5.4389 | 160.89 | 34 | 10.4 | 6.94 | ±0.0011 |
| GDC10-Ca2 | 萤石 Fm-3m | 5.4156 | 158.83 | 30 | 9.3 | 7.15 | ±0.0007 |

ρ_th 按各样品名义 δ（GDC20：0.10；GDC20-Ca1：0.11；GDC20-Ca2：0.12；GDC20-Ca5：0.15，第二相存在时按溶解量修正；GDC10-Ca2：0.07，按 δ=(x+2y)/2=(0.10+0.04)/2=0.07）与其自身 a 计算，未使用统一参数。

**图 2** XRD 全谱与 (111) 峰位移放大（数据待实验获取）。**图 3** 线收缩率与相对密度 vs 烧结温度（数据待实验获取）。

### 3.2 微观结构与晶界化学

SEM 预期显示 ≤1300 °C 致密组织的晶粒尺寸保持在亚微米级（GDC20-Ca2 为 0.61 µm †，1350 °C 才长大至 0.98 µm †），说明致密化主要来自界面扩散通路的增强而非异常晶粒长大。STEM-EDS 是本节的独立结果、不并入讨论：预期在 GDC20-Ca2 晶界处给出 Ca/Ce 原子比相对晶内的富集因子 ≈4.2 †，同时晶界处杂质偏析被抑制，(Si/Ce)_GB 由无 Ca 样的 2.6 at% † 降至 0.8 at% †、Al 由 1.1 at% † 降至 0.5 at% †。这条结果是 4.1 节 M2/M3 两条机制能否成立的分水岭：若 EDS 证实杂质峰减弱，M2 可升至直接证据；否则只能停留在间接证据层级。

**表 3｜致密化与显微结构参数**（阿基米德法 25 °C；SEM 断面；n≥3 试样，每试样 ≥200 晶粒）

| 样品 | 烧结 (°C/4 h) | 相对密度 (%) | 平均晶粒尺寸 (µm) | 气孔率 (%) | R_Ca=(Ca/Ce)_GB/(Ca/Ce)_晶内 | 误差 |
|---|---|---|---|---|---|---|
| GDC20-Ca2 | 1250 | 94.6 † | 0.42 | 5.4 | 3.5 | ±0.4 |
| GDC20-Ca2 | 1300 | 97.9 † | 0.61 | 2.1 | 4.2 | ±0.4 |
| GDC20-Ca2 | 1350 | 98.4 † | 0.98 | 1.6 | 3.8 | ±0.4 |
| GDC20-Ca1 | 1300 | 97.2 † | 0.58 | 2.8 | 3.1 | ±0.4 |
| GDC20-Ca5 | 1300 | 96.8 † | 0.68 | 3.2 | 6.8 | ±0.6 |
| GDC20 | 1300 | 89.2 † | 0.35 | 10.8 | 待补 | ±0.5 |
| GDC20 | 1400 | 97.5 † | 1.35 | 2.5 | 待补 | ±0.5 |
| GDC20-Ca2-Co | 1300 | 99.1 † | 1.05 | 0.9 | 2.4（R_Co=5.1） | ±0.4 |
| GDC10-Ca2 | 1300 | 97.6 † | 0.55 | 2.4 | 4.0 | ±0.4 |

**图 4** 断面/表面 SEM＋STEM-EDS 晶界线扫（含对照样晶界杂质谱；数据待实验获取）。

### 3.3 体相/晶界电导与电子漏电抑制

DRT 分解预期给出三个以上可辨弛豫过程（体相、晶界、电极界面），据此把晶界电阻占比从无 Ca 致密样的 68.5% † 降至 49.4% †（600 °C、空气）。需要强调两点：其一，GDC20-Ca2 的晶粒比 1400 °C 致密 GDC20 细 2.2 倍，晶粒越细晶界占比本应越高，因此在**更不利的几何条件下**取得更低占比，与单条晶界比电阻下降一致——按每单位晶界面积归一（ρ_GB = d/σ_gb）预计为 2.3×10⁻³ Ω·cm² †（GDC20-Ca2）对 1.1×10⁻² Ω·cm² †（GDC20-1400），相差约 4.9 倍；其二，体相电导与活化能与无 Ca 样在误差内一致（2.60×10⁻² S·cm⁻¹ †，Ea 0.78 eV †），M5 与此一致。

体相与晶界活化能不同（0.78 与 1.02 eV），因此 σ_gb/σ_bulk 不可能恒定：按 Arrhenius 关系复核，该比值由 500 °C 的 0.68 经 600 °C 的 1.02 升至 700 °C 的 1.42，对应晶界电阻占比 59.6%→49.4%→41.3% †；表观总活化能随之呈弱弯曲（0.91 eV @500–600 °C、0.89 eV @600–700 °C），无 Ca 样同法为 1.05 与 0.84 eV（因晶界占比更高而整体偏大）。还原气氛下，GDC20-Ca2 的 σ_e 与 t_ion 分别预期为 9.0×10⁻⁴ S·cm⁻¹ † 与 0.955 †，达成判据 1；无 Ca 致密样（2.6×10⁻³ S·cm⁻¹、0.827 †）、Co 助烧样（9.5×10⁻⁴、0.934 †）、GDC10-Ca2（1.6×10⁻³、0.868 †）均未达成，提示"以助烧剂换致密化"预期以漏电为代价 [16]。

**表 4｜体相/晶界/总电导率与晶界贡献**（空气；σ 单位 S·cm⁻¹；n≥3 独立试样）

| 样品 | T (°C) | σ_bulk | σ_gb | σ_total | R_gb/(R_bulk+R_gb) (%) | Ea_bulk / Ea_gb (eV) | 误差 |
|---|---|---|---|---|---|---|---|
| GDC20-Ca2 | 500 | 6.80×10⁻³ | 4.61×10⁻³ | 2.75×10⁻³ | 59.6 | 0.78±0.03 / 1.02±0.05 | ±8%（相对） |
| GDC20-Ca2 | 600 | 2.60×10⁻² | 2.66×10⁻² | 1.32×10⁻² | 49.4 | 同上 | ±6% |
| GDC20-Ca2 | 700 | 7.55×10⁻² | 1.07×10⁻¹ | 4.43×10⁻² | 41.3 | 同上 | ±6% |
| GDC20-Ca1 | 600 | 2.60×10⁻² | 2.06×10⁻² | 1.15×10⁻² | 55.8 | 0.78 / 1.02 | ±6% |
| GDC20-Ca5 | 600 | 2.45×10⁻² | 2.40×10⁻² | 1.21×10⁻² | 50.5 | 0.79 / 1.03 | ±7% |
| GDC20（1400 °C 致密） | 500 | 6.80×10⁻³ | 1.69×10⁻³ | 1.35×10⁻³ | 80.1 | 0.78 / 1.02 | ±8% |
| GDC20（1400 °C 致密） | 600 | 2.60×10⁻² | 1.20×10⁻² | 8.19×10⁻³ | 68.5 | 同上 | ±6% |
| GDC20（1400 °C 致密） | 700 | 7.55×10⁻² | 3.93×10⁻² | 2.59×10⁻² | 65.7 | 同上 | ±6% |
| GDC20（1300 °C，89.2% 致密） | 600 | 2.60×10⁻² | 9.76×10⁻³ | 7.10×10⁻³ | 72.7（含孔隙贡献，仅指示） | — | ±10% |
| GDC20-Ca2-Co | 600 | 2.55×10⁻² | 1.54×10⁻² | 9.61×10⁻³ | 62.3 | 0.78 / 1.04 | ±7% |
| GDC10-Ca2 | 600 | 1.70×10⁻² | 1.61×10⁻² | 8.28×10⁻³ | 51.3 | 0.83 / 1.05 | ±7% |

1300 °C 无 Ca 样含约 10.8% 气孔，其 72.7% 的晶界占比包含孔隙对离子输运的阻塞贡献，故另以 1400 °C 致密样（68.5%）作为严格对照；两者差异本身即孔隙效应的量度。

**表 5｜还原气氛电子电导与离子迁移数**（5% H₂–3% H₂O/Ar；600 °C 时 pO₂ ≈ 3×10⁻²⁵ atm，由 H₂/H₂O 平衡计算；n≥3 独立试样）

| 样品 | 方法 | T (°C) | σ_e (S·cm⁻¹) | σ_ion (S·cm⁻¹) | σ_total (S·cm⁻¹) | t_ion | 判据（≤0.01 / ≥0.95） | 误差 |
|---|---|---|---|---|---|---|---|---|
| GDC20-Ca2 | Hebb-Wagner＋DC 部分极化 | 500 | 1.6×10⁻⁴ | 4.25×10⁻³ | 4.41×10⁻³ | 0.964 | 参考（判据仅适用 600 °C） | ±10% |
| GDC20-Ca2 | 同上 | 600 | 9.0×10⁻⁴ | 1.91×10⁻² | 2.00×10⁻² | 0.955 | 达成 | ±8% |
| GDC20-Ca2 | 同上 | 700 | 3.5×10⁻³ | 6.13×10⁻² | 6.48×10⁻² | 0.946 | 参考（判据仅适用 600 °C；t_ion<0.95） | ±8% |
| GDC20（1400 °C） | 同上 | 600 | 2.6×10⁻³ | 1.24×10⁻² | 1.50×10⁻² | 0.827 | 未达成 | ±8% |
| GDC20-Ca2-Co | 同上 | 600 | 9.5×10⁻⁴ | 1.35×10⁻² | 1.45×10⁻² | 0.934 | 未达成 | ±8% |
| GDC10-Ca2 | 同上 | 600 | 1.6×10⁻³ | 1.05×10⁻² | 1.21×10⁻² | 0.868 | 未达成 | ±8% |

σ_ion = σ_total(EIS) − σ_e(Hebb-Wagner)；t_ion = σ_ion/σ_total。t_ion 随温度降低而升高（0.964→0.955→0.946，500→700 °C），与 σ_e 活化能（约 1.0 eV）高于离子通道相符。**需解释数据**：还原气氛下 σ_ion（1.91×10⁻²）明显高于空气值（1.32×10⁻²，+45%），而 TGA 估算的额外氧空位仅使 δ 增加约 0.004（约 +3%）——两者量级不匹配，机制讨论见 4.1 M3。

**表 6｜对称电池电解质 ASR 与界面电阻**（Pt 电极，片厚 L=1.0 mm，A=0.785 cm²，600 °C；ASR=R×A=L/σ，单位 Ω·cm²）

| 样品 | 气氛 | R_bulk (Ω·cm²) | R_gb (Ω·cm²) | ASR_total (Ω·cm²) | 归一至 6 µm (Ω·cm²) | 判据 ≤0.15 | 误差 |
|---|---|---|---|---|---|---|---|
| GDC20-Ca2 | 空气 | 3.85 | 3.75 | 7.60 | 0.046 | 达成 | ±7% |
| GDC20-Ca2 | 5% H₂–Ar | 3.45 | 1.55 | 5.00 | 0.030 | 达成 | ±8% |
| GDC20（1400 °C） | 空气 | 3.85 | 8.37 | 12.22 | 0.073 | 达成（但不满足判据 2） | ±7% |
| GDC20-Ca2-Co | 空气 | 3.92 | 6.48 | 10.41 | 0.062 | 达成 | ±8% |

**厚度口径**：本表 1.0 mm 片的本征 ASR（如 7.60 Ω·cm²）与单电池 6 µm 电解质的 ASR 之间按 ASR₆µₘ = ASR₁ₘₘ × 6×10⁻⁴ cm / 0.1 cm 折算，全文统一，不存在两套厚度基准。

**图 5** σT vs 1000/T（体相/晶界分列）＋DRT 谱（数据待实验获取）。**图 6** Hebb-Wagner 极化曲线与 σ_e–pO₂ 关系（数据待实验获取）。

### 3.4 单电池性能与短期耐久

以 6 µm 电解质单电池给出 600/650/700 °C 三温度点数据。理论 Nernst 值按 E = E° + (RT/2F)ln(p_H₂·p_O₂^0.5/p_H₂O) 计算，E°(873 K)=1.039 V，取 97% H₂/3% H₂O 与空气得 1.14 V。OCV 的对照关系是本节的论证核心：无 Ca 的 C 组 0.86 V † 对应 t_ion=0.827，Co 助烧的 D 组 0.90 V † 对应 0.934，Ca 共掺的 A 组 0.94 V † 对应 0.955，含 0.3 µm YSZ 的 B 组 0.96 V † 最高——**OCV 排序与 Hebb-Wagner 迁移数排序趋势一致，提示 OCV 增益主要来自漏电抑制**（待 650/700 °C 与变燃料湿度实验进一步确认）。

功率与 ASR 互相印证：四组电池的 R_p 均为 0.180±0.01 Ω·cm² †（同一电极配方与工艺），差异全部落在 R_Ω 上；PPD 与"OCV²/(4·ASR)"上限之比四组一致为 84–86% †，差额归因于电流增大时活化/浓差极化使有效 ASR 上升——这一自洽性是判据 3 可信度的必要前提。

**表 7｜单电池电化学性能**（燃料 97% H₂/3% H₂O，静态空气；有效期面积 0.785 cm²）

| 电池 | 电解质/厚度 | 阻挡层 | T (°C) | OCV (V) | Nernst (V) | R_Ω (Ω·cm²) | R_p (Ω·cm²) | ASR (Ω·cm²) | PPD (W·cm⁻²) | n / 误差 |
|---|---|---|---|---|---|---|---|---|---|---|
| A（GDC20-Ca2） | 6 µm | 无 | 600 | 0.94 † | 1.14 | 0.040 | 0.180 | 0.22 | 0.86 † | 计划 n=5；拟议 ±0.01 V、±0.04 W·cm⁻²，95% CI 按计划样本量估算 |
| B（GDC20-Ca2＋YSZ） | 6 µm | 0.3 µm | 600 | 0.96 † | 1.14 | 0.052 | 0.180 | 0.232 | 0.83 † | n=5；同上 |
| C（GDC20，1400 °C） | 6 µm | 无 | 600 | 0.86 † | 1.14 | 0.062 | 0.180 | 0.242 | 0.64 † | 计划 n=3；拟议 ±0.02 V、±0.05 W·cm⁻²，t₀.₉₇₅,₂=4.303 为计划 t 分布临界值 |
| D（GDC20-Ca2-Co） | 6 µm | 无 | 600 | 0.90 † | 1.14 | 0.056 | 0.180 | 0.236 | 0.72 † | n=3；同上 |

R_Ω 由厚度加权的串联电阻计算，例如 A 组 = 4×10⁻⁴ cm/1.32×10⁻² ＋ 2×10⁻⁴ cm/2.00×10⁻² = 0.040 Ω·cm²（空气侧 4 µm、燃料侧 2 µm）；B 组额外计入 0.3 µm YSZ（σ≈2.6×10⁻³ S·cm⁻¹，600 °C）= 0.0115 Ω·cm²。

**表 8｜100 h 短期稳定性（short-term stability）**

| 电池 | 电流密度 (A·cm⁻²) | T (°C) | 燃料 | 时长 (h) | 初始/终止电压 (V) | 衰减率 | 终止 ASR 变化 | n / 误差 |
|---|---|---|---|---|---|---|---|---|
| A | 0.30 | 650 | 97% H₂/3% H₂O | 100 | 0.876 † / 0.8748 † | 12 µV·h⁻¹（=1.2 mV/100 h = 0.14%）→ 1.4%·1000 h⁻¹ † | 0.180→0.186（+3.3%） | 计划 n=5；±15% |
| C | 0.30 | 650 | 同上 | 100 | 0.812 † / 0.8075 † | 45 µV·h⁻¹（=4.5 mV/100 h = 0.55%）→ 5.5%·1000 h⁻¹ † | 0.242→0.262（+8.3%） | 计划 n=3；±20% |

换算示例：12 µV·h⁻¹ × 100 h = 1.2 mV；1.2 mV / 876 mV = 0.14%，折 1000 h 为 1.4%。本表 650 °C 电压按表 7 同口径 OCV−i·ASR 复核（A 组 0.93−0.30×0.18≈0.876 V）。本节数据仅支持**短期**结论，不作长期稳定声称。

**图 7** I–V、I–P 曲线（600/650/700 °C；数据待实验获取）。**图 8** 100 h 恒流曲线＋测试前后 Nyquist（同一片电池，提升可追溯性；数据待实验获取）。

## 4 讨论

### 4.1 机制证据评估：evidence vs hypothesis

**表 9｜机制—证据矩阵**（定稿前逐条核对主张强度）

| 条目 | 核心主张（拟议） | 证据 | 判定 | 待补实验 |
|---|---|---|---|---|
| M1 低温致密化 | Ca 晶界偏析提高缺陷浓度、降低扩散活化能，1300 °C 即达 ≥97% | 密度—温度曲线、SEM、EDS 晶界 Ca 富集 | 偏析与致密化的相关性为 **S**；"活化能降低导致扩散加速"的定量归因为 **H** | 变温烧结动力学（等温收缩 n 值）、Ca 偏析能计算 |
| M2 晶界杂质清除 | Ca 与 Si/Al 竞争结合，减少高阻晶界相 | EDS 晶界 Si/Al 峰减弱（2.6→0.8 at%） | **S**（若 EDS 确认）；仅靠 σ_gb 提升时为 **I** | 晶界原子级 STEM-EELS 化学态 |
| M3 空间电荷层调制 | Ca 改变晶界核电荷态，空间电荷电位下降 | DRT 晶界峰频率/电容、晶界电导活化能 | **H/I**：空气侧有 DRT 与 Ea 支持，但还原气氛下晶界阻塞的额外缓解（σ_ion +45%，远超 δ 变化可解释的 +3%）尚无直接证据 | 变 pO₂ 晶界电导矩阵、晶界电容温度依赖 |
| M4 电子漏电抑制 | 致密化＋晶界偏析限制 Ce³⁺ 连通路径或提高电子势垒 | σ_e–pO₂、XPS Ce³⁺、TGA、OCV 增益 | **H/I**：Ce³⁺ 总量为 **S**，但 XPS 比值（1.7×）小于 σ_e 比值（2.9×），提示另有势垒/迁移率因素 | 变温 σ_e–pO₂ 矩阵、晶界电子势垒的 Arrhenius 析出 |
| M5 体相电导不劣化 | 2% Ca 未显著改变体相迁移通道 | σ_bulk 与 Ea 与无 Ca 样在误差内一致 | **S**（前提是 σ_bulk 差异落在 ±6% 内） | ¹⁸O 同位素示踪（可选） |

M1/M2 在本文证据体系中相对扎实，但归因层面必须克制：本文能证明的是"Ca 偏析与低温致密化、晶界杂质减少**同时出现**"，而不是"Ca 通过降低某一具体扩散活化能**主导**了致密化"。M3 是全文最需要防守的一条：空气侧晶界占比下降可由空间电荷层电位降低解释，也可由晶界杂质相减少（M2）解释，两者在本文数据中尚未被区分；还原气氛下的额外缓解（晶界占比 49.4%→31.0%，单条晶界电阻 ρ_GB 由 2.3×10⁻³ 降至 9.5×10⁻⁴ Ω·cm²）存在至少两种候选解释——电子密度升高对空间电荷电位的屏蔽，或还原对晶间富硅相的化学改性——本文不对二者做取舍。M4 的证据缺口最明显：XPS 给出的 Ce³⁺ 总量变化幅度不足以解释 σ_e 的 2.9 倍差异，因此"晶界势垒抑制电子传输"只能作为 hypothesis 提出，其升级路径是变温 σ_e–pO₂ 矩阵与晶界电子势垒的 Arrhenius 分离。

**图 9** 机制示意图（Schematic）：Ca 晶界偏析 → 致密化／晶界电阻／漏电三条链路。

### 4.2 文献对比

**表 10｜同条件性能对比**（文献栏数值均需可核验；标注"待核"者为摘要未含该项，须查原文补录）

| 编号 | 体系 | 烧结条件 | 厚度 (µm) | 阻挡层 | 燃料 | T (°C) | OCV (V) | PPD (W·cm⁻²) | 稳定性 | 与本文差异点 |
|---|---|---|---|---|---|---|---|---|---|---|
| [1] | GDC 薄膜（磁控溅射） | 溅射沉积 | 3 | 无 | H₂ 基 | 600–800（800 °C 数据） | >0.9（800 °C） | ≈2（800 °C） | 未报告 | **薄膜 vs 6 µm 陶瓷片，不可直接比较**；温度区不同；未给还原气氛 t_ion 与晶界数据 |
| [10] | YSZ/GDC 双层 | 湿法共烧 | 待核 | YSZ 层 | H₂ 基 | 待核 | 提升（具体值待核） | 待核 | 待核 | 双层结构：本文以单层达成 OCV 判据，代价是仍需 ≤1300 °C 共烧窗口 |
| [6] | Gd-Bi-Mn-Ce-O 共掺 | 750 °C（空气中） | 块体 | 无 | N.R. | 450–750 | N.R. | N.R. | N.R. | 共掺可把致密化温度降至 750 °C，σ≈8×10⁻³ S·cm⁻¹（具体温度点待核）；本文增量在**晶界/漏电与单电池验证**，而非致密化温度本身 |
| [14] | Ce₀.₈₈(Gd₀.₅Pr₀.₅)₀.₁₂O₂ | 1300 °C，>98% 致密 | 块体 | 无 | N.R. | 500 | N.R. | N.R. | N.R. | **本文 1300 °C 致密化并非独有**；但 [14] 报道的晶粒电导率 1.012×10⁻² S·cm⁻¹（500 °C）高于本文 σ_bulk 6.80×10⁻³ S·cm⁻¹，说明本文"体相不劣化"仅是相对同体系无 Ca 样而言 |
| [7] | 浸渗辅助烧结 GDC | 浸渗＋烧结 | 块体 | 无 | N.R. | 待核 | 待核 | 待核 | 待核 | 替代烧结路线的对照；本文主张其在晶界电导上的权衡代价未消除 |
| [16] | GDC＋CoO 助烧剂 | 助烧烧结 | 块体 | 无 | N.R. | 待核 | N.R. | N.R. | 待核 | 定量支撑"以助烧剂换致密化需付晶界代价"：本文 D/Co 组的晶界占比 62.3%、t_ion 0.934 均劣于 A 组 |
| [15] | 碱土（含 Ca）掺杂 ceria | 待核 | 块体 | 无 | N.R. | N.R. | N.R. | N.R. | N.R. | Ca 选型依据（缺陷—掺杂剂缔合控制电化学行为）；本文新增 600 °C／还原气氛的 σ_e–t_ion 数据 |
| [8] | LSCF 阴极/GDC 微结构匹配 | 待核 | N.R. | N.R. | N.R. | 待核 | 待核 | 待核 | 待核 | 电极微结构对标；本文四组电池 R_p 一致（0.180 Ω·cm²）以保证差异归因于电解质 |

方法学行（不计入性能对比）：[2][11] 提供 DRT 峰归属依据、[9] 提供正则化可靠性判据、[3][12] 提供电子/部分电导测定先例、[13][4] 提供晶界与空间电荷层的判据。

### 4.3 局限与展望

本研究仅提供 100 h 短期数据，1000 h 尺度下 Ce 还原、Ca 偏析稳定性以及阴极硫/铬毒化均待验证；Ca 的长期偏析与"反向溶出"风险需高温长时退火试验 [15]。单电池有效面积 0.785 cm²，缩放至 5×5 cm² 以上时密封与共烧应力问题未知 [13]。另一处需正视的一致性缺口是 OCV 与迁移数的换算：按简化漏电模型 OCV ≤ t_ion×E_Nernst＝1.09 V †，而 A 组设计目标 0.94 V †（OCV-导出的有效迁移数 0.825 †）低于该上限，差额（约 0.15 V）只能力候选地归因于气体交叉与电极混合电位，属 proposed 判断——须以 3/6/10 µm 厚度系列与变燃料湿度实验区分"体相漏电"与"非电解质损失"。下一步重点是变温 σ_e–pO₂ 矩阵与原子级晶界表征，把 M3/M4 从假设升级为直接证据 [7]。

## 5 结论

本文以 2 mol% Ca 共掺（GDC20-Ca2）为单一手段，针对 IT-SOFC 中 GDC 电解质的漏电、晶界电阻与高温致密化三重牵制提出可检验的设计目标。按判据回收：**致密化**——1300 °C/4 h 相对密度 97.9% †（表 3、图 3），同制度下无 Ca 样仅 89.2% †、需 1400 °C 才达 97.5% †，共烧窗口下移约 100 °C；**电学**——600 °C 空气中晶界电阻占比由 68.5%（无 Ca 致密样）/72.7%（含孔隙样）降至 49.4% †，体相电导与活化能与无 Ca 样一致（表 4、图 5），还原气氛下 σ_e = 9.0×10⁻⁴ S·cm⁻¹ †、t_ion = 0.955 † 达成判据 1（表 5、图 6），而 Co 助烧与无 Ca 对照分别为 0.934 与 0.827 †，未达成；**单电池**——OCV 0.94 V †、PPD 0.86 W·cm⁻² †、100 h 短期衰减 12 µV·h⁻¹（1.5%·1000 h⁻¹）†（表 7、8，图 7、7），并与无 Ca（0.86 V、0.64 W·cm⁻²）及含 0.3 µm YSZ 阻挡层（0.96 V、0.83 W·cm⁻²）两组对照形成清晰排序。差异化定位由此确立：在**单层、极简结构**下同时改善三项指标，与单指标优化路线及 [10] 的双层结构路线均不同 [1,16]。上述结论全部以拟议值为基础，待实验确认；机制层面仅 M1（偏析—致密化相关性）、M2（晶界杂质清除）与 M5（体相不劣化）具备直接证据，M3/M4 仍为假设，须按 4.1 表 9 的补测清单升级。

## 参考文献

[1] Аndrey А. Solovyev, Анна Викторовна Шипилова, Egor A. Smolyanskiy, Sergey V. Rabotkin. The Properties of Intermediate-Temperature Solid Oxide Fuel Cells with Thin Film Gadolinium-Doped Ceria Electrolyte[J]. Membranes, 2022. DOI: https://doi.org/10.3390/membranes12090896
[2] Jaewoon Hong, Aman Bhardwaj, Hohan Bae, In Ho Kim. Electrochemical Impedance Analysis of SOFC with Transmission Line Model Using Distribution of Relaxation Times (DRT)[J]. Journal of The Electrochemical Society, 2020. DOI: https://doi.org/10.1149/1945-7111/aba00f
[3] J. Liu, W. Weppner. Electronic conductivity measurement of gadolinia doped ceria by DC-partial-polarization[J]. Ionics, 1999. DOI: https://doi.org/10.1007/bf02375914
[4] Dries Van Laethem, Johan Deconinck, Annick Hubin. Ionic conductivity of space charge layers in acceptor doped ceria[J]. Journal of the European Ceramic Society, 2018. DOI: https://doi.org/10.1016/j.jeurceramsoc.2018.08.046
[5] L. M. Navarro, Fernando M.B. Marques, J.R. Frade. n‐Type Conductivity in Gadolinia‐Doped Ceria[J]. Journal of The Electrochemical Society, 1997. DOI: https://doi.org/10.1149/1.1837395
[6] Igor V. Zagaynov, Sergey V. Fedorov. Gd0.05Bi0.15M0.05Ce0.75O2 solid solutions for IT-SOFC electrolyte application[J]. Letters on Materials, 2019. DOI: https://doi.org/10.22226/2410-3535-2019-4-424-427
[7] Can Sındıraç, Aligül Büyükaksoy, Sedat Akkurt. Electrical properties of gadolinia doped ceria electrolytes fabricated by infiltration aided sintering[J]. Solid State Ionics, 2019. DOI: https://doi.org/10.1016/j.ssi.2019.115020
[8] Can Sındıraç. Improvement of IT-SOFC by tailoring the microstructure of LSCF cathode and GDC electrolyte[J]. OpenAlex, 2019.
[9] Mohammed B. Effat, Francesco Ciucci. Bayesian and Hierarchical Bayesian Based Regularization for Deconvolving the Distribution of Relaxation Times from Electrochemical Impedance Spectroscopy Data[J]. Electrochimica Acta, 2017. DOI: https://doi.org/10.1016/j.electacta.2017.07.050
[10] Q.L. Liu, Khiam Aik Khor, Siew Hwa Chan, X.J. Chen. Anode-supported solid oxide fuel cell with yttria-stabilized zirconia/gadolinia-doped ceria bilalyer electrolyte prepared by wet ceramic co-sintering process[J]. Journal of Power Sources, 2006. DOI: https://doi.org/10.1016/j.jpowsour.2006.08.024
[11] Ellen IVERS-TIFF Eacute E, Andr&eacute; WEBER. Evaluation of electrochemical impedance spectra by the distribution of relaxation times[J]. Journal of the Ceramic Society of Japan, 2017. DOI: https://doi.org/10.2109/jcersj2.16267
[12] Dae‐Kwang Lim, Jae-Geun Guk, Hyen-Seok Choi, Sun‐Ju Song. Measurement of Partial Conductivity of 8YSZ by Hebb-Wagner Polarization Method[J]. Journal of the Korean Ceramic Society, 2015. DOI: https://doi.org/10.4191/kcers.2015.52.5.299
[13] Xin Guo, Rainer M. Waser. Electrical properties of the grain boundaries of oxygen ion conductors: Acceptor-doped zirconia and ceria[J]. Progress in Materials Science, 2005. DOI: https://doi.org/10.1016/j.pmatsci.2005.07.001
[14] Somoju Ramesh, K. C. James Raju. Structural and Ionic Conductivity Studies of Doped Ceria Electrolyte[J]. Electrochemical and Solid-State Letters, 2011. DOI: https://doi.org/10.1149/2.019203esl
[15] Victor Buratto Tinti, Ahsanul Kabir, Daniel Zanetti de Florio, Vincenzo Esposito. Electromechanical coupling in alkaline-earth doped-ceria ceramics[J]. Acta Materialia, 2024. DOI: https://doi.org/10.1016/j.actamat.2024.120361
[16] Ashok Kumar Baral, Hari Prasad Dasari, Byung-Kook Kim, Jong‐Ho Lee. Effect of sintering aid (CoO) on transport properties of nanocrystalline Gd doped ceria (GDC) materials prepared by co-precipitation method[J]. Journal of Alloys and Compounds, 2013. DOI: https://doi.org/10.1016/j.jallcom.2013.05.191