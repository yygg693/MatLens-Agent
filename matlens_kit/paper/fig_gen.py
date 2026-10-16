# -*- coding: utf-8 -*-
"""论文工坊 · 图件生成器（matplotlib）。

从 write 正文解析 Figure 图注，按图型分派到不同绘图器：

**示意图**（无需实验数据，可直接画）
a) 电池/器件结构示意（图注含 cell / schematic / 结构 / 电池 / layer / 截面）
   → 多层截面色块图（阳极 | 电解质 | 阴极 + 标注 + 厚度）。
b) 机制示意（图注含 mechanism / 机制 / 示意 / proposed / 晶界 / space charge）
   → 简单框图（标号方框 + 箭头 + 图注文字）。

**数据图**（2026-10-14 新增，需真实实验数据）
数据类图注不再一律跳过：交给 :mod:`fig_schemes` 按谱系（σ–T / Arrhenius /
密度–收缩率 / I–V/I–P / 稳定性 / σ_e–pO₂ / XRD）从 ``experimental_data.tables``
取数绘制。**没有录入数据就拒绝出图**（RefuseToDraw）——论文图宁缺毋滥，
绝不用臆造数值画出一张"看起来像实验结果"的图。

输出：每张图一组文件（PNG 300dpi 预览 + PDF/SVG 矢量），图内标注 "Schematic"（仅示意图）。
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle, FancyArrowPatch

# ---------------------------------------------------------------------------
# 中文字体（Windows 优先 Microsoft YaHei / SimHei，跨平台兜底）
# ---------------------------------------------------------------------------
_SETUP_FONT_DONE = False


def _setup_font() -> None:
    global _SETUP_FONT_DONE
    if _SETUP_FONT_DONE:
        return
    from matplotlib import font_manager
    candidates = ["Microsoft YaHei", "SimHei", "SimSun", "Arial Unicode MS",
                  "Noto Sans CJK SC", "DejaVu Sans"]
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in available:
            plt.rcParams["font.sans-serif"] = [name]
            break
    plt.rcParams["axes.unicode_minus"] = False
    _SETUP_FONT_DONE = True


# Unicode 上下标 → ASCII（图标题 desc 清洗，避免缺字形方块）
_UNI_SUBSUP = str.maketrans({
    "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
    "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9",
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
    "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
    "⁺": "+", "⁻": "-", "₋": "-",
})


def _sanitize(text: str) -> str:
    """把 Unicode 上下标替换为 ASCII，避免图标题出现缺字形方块。"""
    return text.translate(_UNI_SUBSUP)


_setup_font()

# ---------------------------------------------------------------------------
# 图注识别
# ---------------------------------------------------------------------------
# 独立图注行："Figure 1. ..." / "Fig. 1 ..." / "图 1 ..." / "图1 ..."
_CAPTION_RE = re.compile(
    r"^\s*(?:\*\*)?\s*(?:Figure|Fig\.?|图)\s*(\d+)\s*[.:：、\-]?\s*(.+?)(?:\*\*)?\s*$",
    re.IGNORECASE,
)

# 汇总行里的 "Fig N xxx；" / "Fig N xxx；" 片段
_SUMMARY_ITEM_RE = re.compile(
    r"(?:Fig\.?|Figure|图)\s*(\d+)\s*[.．、]?\s*([^；;。\n]+)",
    re.IGNORECASE,
)

# 类型关键词
_CELL_KW = re.compile(
    r"(cell|schematic cross|cross.section|结构|电池|anode|cathode|electrolyte|"
    r"阳极|阴极|电解质|支撑|thin film|membrane|截面|分层)",
    re.IGNORECASE,
)
_MECH_KW = re.compile(
    r"(mechanism|机制|示意|proposed|schematic|晶界|space charge|space-charge|"
    r"grain.boundary|缺陷|diffusion|conductivity mechanism|"
    r"载流子|氧空位|小极化子|band diagram|energy diagram)",
    re.IGNORECASE,
)
_DATA_KW = re.compile(
    r"(XRD|XPS|SEM|TEM|EIS|Nyquist|DRT|Arrhenius|TGA|Raman|ICP|"
    r"I[–-]V|I-V|polarization|impedance|density|shrinkage|grain size|"
    r"\bpO[2₂_]?\b|conductivity.*log|log.*pO|voltage.*time|decay|"
    r"电导率|电导随|σ.?T|sigma.?t|"
    r"衍射|阻抗|极化|恒流|电压|收缩|晶粒|谱|曲线|全谱|分峰)",
    re.IGNORECASE,
)


def _classify_caption(text: str) -> str:
    """返回 'cell' / 'mechanism' / 'data' / 'unknown'。"""
    if _DATA_KW.search(text):
        return "data"
    if _CELL_KW.search(text):
        return "cell"
    if _MECH_KW.search(text):
        return "mechanism"
    return "unknown"


def _clean_desc(text: str) -> str:
    """清洗图注描述：去掉残留的 ** 与首尾空白。

    v7 实测发现 `**图 1** **XRD 全谱...` 这类写法会把 `**` 带进 desc，
    进而污染谱系识别关键词匹配（`**xrd` 与 `xrd` 匹配结果相同，但会让
    后续展示文本出现多余星号）。
    """
    t = str(text or "").strip()
    t = t.replace("**", "")
    return t.strip(" ；;，,。.")


def _extract_captions(write_content: str) -> List[Dict[str, Any]]:
    """从 write 正文提取所有 Figure 图注条目。"""
    items: List[Dict[str, Any]] = []
    seen = set()
    for raw in write_content.split("\n"):
        line = raw.strip()
        # 1) 独立图注行
        m = _CAPTION_RE.match(line)
        if m:
            num = int(m.group(1))
            desc = _clean_desc(m.group(2))
            key = (num, desc[:40])
            if key not in seen:
                seen.add(key)
                items.append({"num": num, "desc": desc, "kind": _classify_caption(desc)})
            continue
        # 2) 汇总行里的多个 Fig N 片段（如 "**图**：Fig 1 XRD...；Fig 2 ..."）
        if re.search(r"(图\s*[：:]|figure\s*[：:])", line, re.IGNORECASE) or "Fig" in line:
            for sm in _SUMMARY_ITEM_RE.finditer(line):
                num = int(sm.group(1))
                desc = _clean_desc(sm.group(2))
                key = (num, desc[:40])
                if key not in seen:
                    seen.add(key)
                    items.append({"num": num, "desc": desc, "kind": _classify_caption(desc)})
    return items


# ---------------------------------------------------------------------------
# 绘制：电池/器件截面示意图
# ---------------------------------------------------------------------------
def _draw_cell_schematic(fig_num: int, desc: str, out_path: str) -> None:
    fig, ax = plt.subplots(figsize=(7.0, 4.2), dpi=150)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6)
    ax.axis("off")

    # 三层：阳极(底) | 电解质(中) | 阴极(顶)
    layers = [
        {"name": "Cathode (LSCF–GDC)", "color": "#4C72B0", "h": 1.4, "y": 4.2},
        {"name": "Electrolyte (GDC–Ca)", "color": "#DD8452", "h": 0.6, "y": 3.6},
        {"name": "Anode support (NiO–GDC)", "color": "#55A868", "h": 1.8, "y": 1.8},
    ]
    for L in layers:
        ax.add_patch(Rectangle((1.5, L["y"]), 7.0, L["h"],
                               facecolor=L["color"], edgecolor="black", linewidth=1.2))
        ax.text(5.0, L["y"] + L["h"] / 2, L["name"],
                ha="center", va="center", fontsize=10, color="white", weight="bold")

    # 气体标注
    ax.text(0.7, 4.9, "Air", ha="center", va="center", fontsize=9, color="#333")
    ax.text(0.7, 2.7, r"H$_2$/H$_2$O", ha="center", va="center", fontsize=9, color="#333")
    ax.annotate("", xy=(1.4, 4.9), xytext=(0.9, 4.9),
                arrowprops=dict(arrowstyle="->", color="#333", lw=1))
    ax.annotate("", xy=(1.4, 2.7), xytext=(0.9, 2.7),
                arrowprops=dict(arrowstyle="->", color="#333", lw=1))

    # 厚度标注（右侧）
    ax.annotate("", xy=(8.7, 4.2), xytext=(8.7, 5.6),
                arrowprops=dict(arrowstyle="<->", color="#333", lw=0.8))
    ax.text(8.85, 4.9, "~30 µm", fontsize=8, va="center")
    ax.annotate("", xy=(8.7, 3.6), xytext=(8.7, 4.2),
                arrowprops=dict(arrowstyle="<->", color="#333", lw=0.8))
    ax.text(8.85, 3.9, "6 µm", fontsize=8, va="center")
    ax.annotate("", xy=(8.7, 1.8), xytext=(8.7, 3.6),
                arrowprops=dict(arrowstyle="<->", color="#333", lw=0.8))
    ax.text(8.85, 2.7, "~500 µm", fontsize=8, va="center")

    # 标题 / Schematic 标注
    ax.text(5.0, 5.8, f"Fig. {fig_num}. {_sanitize(desc)}", ha="center", va="center",
            fontsize=10, weight="bold")
    ax.text(5.0, 0.6, "Schematic — not to scale", ha="center", va="center",
            fontsize=8, style="italic", color="#666")

    plt.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------
# 绘制：机制框图
# ---------------------------------------------------------------------------
def _draw_mechanism_diagram(fig_num: int, desc: str, out_path: str) -> None:
    fig, ax = plt.subplots(figsize=(7.5, 4.5), dpi=150)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6)
    ax.axis("off")

    boxes = [
        {"text": "Ca co-doping\nin GDC lattice", "xy": (1.2, 3.8), "color": "#4C72B0"},
        {"text": r"Reduced Ce$^{3+}$" + "\nreduction", "xy": (4.2, 4.2), "color": "#55A868"},
        {"text": r"Lower electronic" + "\n" + r"leakage ($\sigma_e \downarrow$)", "xy": (7.2, 4.2), "color": "#C44E52"},
        {"text": "Grain-boundary\nscavenging", "xy": (1.2, 1.6), "color": "#8172B3"},
        {"text": "Space-charge\nlayer modulation", "xy": (4.2, 1.6), "color": "#CCB974"},
        {"text": r"Lower $R_{gb}$" + "\n" + r"($\sigma_i \uparrow$)", "xy": (7.2, 1.6), "color": "#C44E52"},
    ]
    for b in boxes:
        ax.add_patch(FancyBboxPatch(b["xy"], 2.0, 1.0,
                                    boxstyle="round,pad=0.08",
                                    facecolor=b["color"], edgecolor="black",
                                    linewidth=1.0, alpha=0.85))
        ax.text(b["xy"][0] + 1.0, b["xy"][1] + 0.5, b["text"],
                ha="center", va="center", fontsize=8.5, color="white", weight="bold")

    # 箭头
    arrows = [
        ((3.2, 4.3), (4.2, 4.5)),
        ((6.2, 4.5), (7.2, 4.5)),
        ((3.2, 1.9), (4.2, 1.9)),
        ((6.2, 1.9), (7.2, 1.9)),
        ((2.2, 3.8), (2.2, 2.6)),   # 两条路径汇合到 Ca 掺杂
        ((5.2, 3.8), (5.2, 2.6)),
    ]
    for (x1, y1), (x2, y2) in arrows:
        ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2),
                                     arrowstyle="->", color="#333", lw=1.2))

    ax.text(5.0, 5.6, f"Fig. {fig_num}. {_sanitize(desc)}", ha="center", va="center",
            fontsize=10, weight="bold")
    ax.text(5.0, 0.5, "Schematic mechanism diagram", ha="center", va="center",
            fontsize=8, style="italic", color="#666")

    plt.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def gen_figures(
    write_content: str,
    out_dir: str,
    experimental_data: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """解析 write 正文中的 Figure 图注，为可绘制的图生成 PNG/矢量图。

    Args:
        write_content: write 阶段正文 markdown。
        out_dir: 图件输出目录（不存在则创建）。
        experimental_data: 可选。论文的实验数据 dict（``{"status","notes","tables"}``）；
            传入后**数据图会尝试从tables 取数绘制**，未录入则该图保持 skipped。

    Returns:
        list[dict]，每条：
        {"num": int, "desc": str, "kind": "cell"|"mechanism"|"data"|"unknown",
         "scheme": str|None, "path": str|None, "status": "generated"|"skipped",
         "reason": str|None, **绘图元信息}
    """
    if not write_content or not write_content.strip():
        return []
    os.makedirs(out_dir, exist_ok=True)

    captions = _extract_captions(write_content)
    if not captions:
        return []

    tables = []
    if isinstance(experimental_data, dict):
        tbls = experimental_data.get("tables")
        if isinstance(tbls, list):
            tables = [t for t in tbls if isinstance(t, dict)]

    results: List[Dict[str, Any]] = []
    for cap in captions:
        num = cap["num"]
        desc = cap["desc"]
        kind = cap["kind"]
        if kind == "cell":
            path = os.path.join(out_dir, f"fig_{num}_cell.png")
            try:
                _draw_cell_schematic(num, desc, path)
                results.append({"num": num, "desc": desc, "kind": kind,
                                "scheme": None, "path": path, "status": "generated",
                                "reason": None})
            except Exception:
                results.append({"num": num, "desc": desc, "kind": kind,
                                "scheme": None, "path": None, "status": "skipped",
                                "reason": "示意图绘制失败"})
        elif kind == "mechanism":
            path = os.path.join(out_dir, f"fig_{num}_mechanism.png")
            try:
                _draw_mechanism_diagram(num, desc, path)
                results.append({"num": num, "desc": desc, "kind": kind,
                                "scheme": None, "path": path, "status": "generated",
                                "reason": None})
            except Exception:
                results.append({"num": num, "desc": desc, "kind": kind,
                                "scheme": None, "path": None, "status": "skipped",
                                "reason": "示意图绘制失败"})
        elif kind == "data":
            # 数据图：从录入实验数据取数，按谱系绘制（2026-10-14 新增）
            results.append(_draw_data_figure(num, desc, tables, out_dir))
        else:
            # unknown → 跳过：图注既不属示意图也不属已知数据图型，画出来只会误导
            results.append({"num": num, "desc": desc, "kind": kind, "scheme": None,
                            "path": None, "status": "skipped",
                            "reason": "图注无法归类（既非示意图也非已知数据图型）"})
    return results


def _draw_data_figure(
    num: int, desc: str, tables: List[Dict[str, Any]], out_dir: str
) -> Dict[str, Any]:
    """按谱系绘制数据图；数据不足则返回 skipped（不抛异常）。"""
    base = {"num": num, "desc": desc, "kind": "data", "scheme": None,
            "path": None, "status": "skipped", "reason": None}
    try:
        from matlens_kit.paper.fig_schemes import detect_scheme, draw_scheme
        from matlens_kit.paper.fig_kit import RefuseToDraw
    except Exception as e:  # noqa: BLE001
        return {**base, "reason": f"绘图模块不可用：{e}"}

    scheme = detect_scheme(desc)
    if not scheme:
        return {**base, "reason": "未识别的数据图谱系（需更明确的图注，如'σ vs T'/'Arrhenius'）"}
    if not tables:
        return {**base, "scheme": scheme,
                "reason": f"谱系 '{scheme}' 需真实实验数据：请在「实验数据」中录入数据表"}

    path = os.path.join(out_dir, f"fig_{num}_{scheme}")
    try:
        meta = draw_scheme(scheme, tables, path)
    except RefuseToDraw as e:
        return {**base, "scheme": scheme, "reason": str(e)}
    except Exception as e:  # noqa: BLE001
        return {**base, "scheme": scheme, "reason": f"绘图失败：{type(e).__name__}: {e}"}

    png = meta.get("png")
    return {**base, "scheme": scheme, "path": png, "status": "generated",
            "reason": None, "vector": {k: v for k, v in meta.items() if k in ("pdf", "svg")},
            "metrics": {k: v for k, v in meta.items() if k not in ("png", "pdf", "svg")}}
