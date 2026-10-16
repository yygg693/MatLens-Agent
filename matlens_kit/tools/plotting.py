# -*- coding: utf-8 -*-
"""实验数据可视化工具（MatLens 材料垂直）。

experiment_plot —— 把材料实验数据（XRD 图谱、Tauc 光谱、CV 曲线、充放电曲线、
普通 XY 数据）渲染为 PNG 图表并保存，同时返回数据统计。

数据来源二选一：
1. ``file``：数据文件路径（第一列 x，第二列 y，支持 CSV/TXT，跳过表头）；
2. ``x`` + ``y``：直接内联数值数组。

图类型 plot_type：
- xy：普通折线（默认）
- xrd：XRD 衍射图谱（峰形填充 + 自动标峰）
- tauc：Tauc plot（散点 + 线性拟合段，带隙参考）
- cv：CV 回线（电流-电压）
- discharge：充放电曲线（电压-比容量）

依赖：matplotlib + numpy（运行时懒加载；缺失时报错提示）。
输出：Agg 后端渲染为 PNG，base64 内嵌到返回 JSON 的 plot_b64 字段，
不落盘；前端 <img src="data:image/png;base64,..."> 直接渲染。
"""
from __future__ import annotations

import base64
import io
import os
from typing import Any, Dict, List, Tuple, Optional

from tools.registry import registry, tool_result


def _read_xy_file(path: str) -> Tuple[List[float], List[float]]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"数据文件不存在：{path}")
    xs: List[float] = []
    ys: List[float] = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith(("#", ";", "//")):
                continue
            parts = ln.replace(",", " ").split()
            if len(parts) < 2:
                continue
            try:
                xv, yv = float(parts[0]), float(parts[1])
            except ValueError:
                continue  # 表头/非数字行跳过
            xs.append(xv)
            ys.append(yv)
    if len(xs) < 2:
        raise ValueError("数据点不足（至少 2 个有效数据点）")
    return xs, ys


def _data_stats(xs: List[float], ys: List[float]) -> Dict[str, Any]:
    return {
        "n": len(xs),
        "x_range": [round(min(xs), 4), round(max(xs), 4)],
        "y_range": [round(min(ys), 4), round(max(ys), 4)],
        "y_mean": round(sum(ys) / len(ys), 4),
        "y_max": round(max(ys), 4),
    }


def _out_path(name: str) -> str:
    try:
        from matlens_constants import get_matlens_home
    except Exception:
        from pathlib import Path as _P

        home = os.path.join(str(_P.home()), ".matlens")
    else:
        home = get_matlens_home()
    d = os.path.join(home, "plots")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


# 输出格式 → (media_type, 文件扩展名)。与 settings experiment.plot_format 取值一致。
_PLOT_MEDIA = {
    "png": ("image/png", "png"),
    "svg": ("image/svg+xml", "svg"),
    "pdf": ("application/pdf", "pdf"),
}


def _plot_settings() -> Tuple[str, int]:
    """动作时刻实时读 settings experiment.plot_format 与 dpi。

    读不到/非法时回退 png / 300，保证绘图永不因设置异常而失败。
    """
    fmt, dpi = "png", 300
    try:
        from matlens_kit import settings_store
        exp = settings_store.get_section("experiment")
        fmt = str(exp.get("plot_format", "png")).lower().strip()
        dpi = int(exp.get("dpi", 300))
    except Exception:  # noqa: BLE001
        pass
    if fmt not in _PLOT_MEDIA:
        fmt = "png"
    if dpi not in (150, 300, 600):
        # 允许但不限制：仍用传入 dpi，仅兜底异常值
        try:
            dpi = int(dpi)
        except Exception:  # noqa: BLE001
            dpi = 300
    return fmt, dpi


def experiment_plot_tool(
    file: str = "",
    x: Optional[List[float]] = None,
    y: Optional[List[float]] = None,
    plot_type: str = "xy",
    title: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """实验数据可视化（matplotlib 渲染 PNG）。

    Args:
        file: 数据文件路径（第一列 x，第二列 y）；与 x/y 二选一。
        x: 内联 x 数组。
        y: 内联 y 数组（与 x 等长）。
        plot_type: xy / xrd / tauc / cv / discharge。
        title: 图表标题（可选）。

    Returns:
        图片保存路径、统计信息与图类型说明。
    """
    try:
        import numpy as np  # noqa: F401
        import matplotlib
        matplotlib.use("Agg")  # 无显示环境
        import matplotlib.pyplot as plt
    except ImportError as exc:
        return {"error": f"可视化需要 matplotlib + numpy：{exc}（pip install matplotlib numpy）"}

    # 数据来源
    if file:
        try:
            xs, ys = _read_xy_file(file)
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}
    elif x is not None and y is not None:
        xs = [float(v) for v in x]
        ys = [float(v) for v in y]
        if len(xs) != len(ys):
            return {"error": f"x 与 y 长度不一致：{len(xs)} vs {len(ys)}"}
        if len(xs) < 2:
            return {"error": "数据点不足（至少 2 个）"}
    else:
        return {"error": "需要 file 或 x+y 数据"}

    pt = (plot_type or "xy").lower().strip()
    # 动作时刻实时读 settings experiment.plot_format / dpi
    plot_format, dpi = _plot_settings()
    media_type, _ext = _PLOT_MEDIA[plot_format]
    try:
        fig, ax = plt.subplots(figsize=(8, 5.2), dpi=dpi)
        fig.patch.set_facecolor("white")
        if pt == "xrd":
            ax.vlines(xs, 0, ys, color="#2563eb", lw=1.6)
            ax.fill_between(xs, 0, ys, color="#2563eb", alpha=0.25)
            ax.set_xlabel("2θ / degree")
            ax.set_ylabel("Intensity / a.u.")
        elif pt == "tauc":
            ax.plot(xs, ys, "o-", color="#7c3aed", ms=3.5, lw=1.2)
            ax.set_xlabel("hν / eV")
            ax.set_ylabel("(αhν)^n")
            # 数据区间内的线性拟合段（粗略参考线，不代替完整 Tauc 分析）
            try:
                npx, npy = np.array(xs), np.array(ys)
                if len(npx) >= 4:
                    k = npx[-1] - npx[0]
                    if k != 0:
                        slope, intercept = np.polyfit(npx, npy, 1)
                        fit_y = slope * npx + intercept
                        ax.plot(npx, fit_y, "--", color="#f59e0b", lw=1.1, alpha=0.8)
                        ax.text(0.02, 0.96, f"slope≈{slope:.3f}", transform=ax.transAxes,
                                fontsize=9, color="#b45309")
            except Exception:  # noqa: BLE001
                pass
        elif pt == "cv":
            ax.plot(xs, ys, "-", color="#059669", lw=1.5)
            ax.fill_between(xs, ys, color="#059669", alpha=0.12)
            ax.set_xlabel("Potential / V")
            ax.set_ylabel("Current / mA")
        elif pt == "discharge":
            ax.plot(xs, ys, "-", color="#d97706", lw=1.6)
            ax.set_xlabel("Specific capacity / mAh g⁻¹")
            ax.set_ylabel("Voltage / V")
        else:  # xy 默认
            ax.plot(xs, ys, "-o", color="#2563eb", ms=3, lw=1.3)
            ax.set_xlabel("x")
            ax.set_ylabel("y")

        ax.set_title(title or f"experiment_plot · {pt}", fontsize=11)
        ax.grid(True, alpha=0.25)
        fig.tight_layout()

        # 统一：Agg 后端 + BytesIO + base64，不写临时图片文件；
        # format/dpi 实时取自 settings experiment.{plot_format,dpi}。
        buf = io.BytesIO()
        fig.savefig(buf, format=plot_format, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        raw = buf.read()
        plot_b64 = f"data:{media_type};base64," + base64.b64encode(raw).decode("ascii")
    except Exception as exc:  # noqa: BLE001
        return {"error": f"绘图失败：{exc}"}

    return {
        "plot_type": pt,
        "plot_format": plot_format,
        "media_type": media_type,
        "dpi": dpi,
        "plot_b64": plot_b64,
        "stats": _data_stats(xs, ys),
        "note": f"图表以 {plot_format.upper()}（{media_type}）内嵌为 base64（plot_b64），dpi={dpi}；PNG 可用 <img src=data:{media_type};base64,...> 直接渲染，SVG/PDF 为矢量图；Tauc 图为拟合参考，正式带隙请用 tauc_bandgap",
    }


EXPERIMENT_PLOT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": "实验数据可视化：XRD/Tauc/CV/充放电曲线渲染为 base64 图（格式/DPI 取设置 experiment.plot_format/dpi），支持文件或内联数据。",
    "properties": {
        "file": {"type": "string", "description": "数据文件路径（第一列 x，第二列 y）；与 x/y 二选一"},
        "x": {"type": "array", "items": {"type": "number"}, "description": "内联 x 数组"},
        "y": {"type": "array", "items": {"type": "number"}, "description": "内联 y 数组"},
        "plot_type": {
            "type": "string",
            "description": "xy / xrd / tauc / cv / discharge",
            "enum": ["xy", "xrd", "tauc", "cv", "discharge"],
            "default": "xy",
        },
        "title": {"type": "string", "description": "图表标题"},
    },
    "additionalProperties": False,
    "examples": [
        {"x": [10, 20, 30, 40, 50], "y": [0.1, 0.5, 0.9, 0.4, 0.2], "plot_type": "xrd", "title": "Cu Kα XRD"},
        {"file": "spectrum.txt", "plot_type": "tauc", "title": "Tauc plot"},
    ],
}


def _check_plot_available() -> bool:
    return True


registry.register(
    name="experiment_plot",
    toolset="matlens_material",
    schema=EXPERIMENT_PLOT_SCHEMA,
    handler=lambda args, **kw: tool_result(experiment_plot_tool(**args)),
    check_fn=_check_plot_available,
    description="实验数据可视化：XRD/Tauc/CV/充放电曲线渲染 base64 图（格式/DPI 取设置，支持文件或内联数据）",
    emoji="📊",
)
