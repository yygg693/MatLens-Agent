"""数据处理类材料工具：XRD 预处理 / 批量数据归一化。

纯 numpy 实现，离线可用。
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Tuple

from tools.registry import registry, tool_result


def _load_xy(path: str) -> Tuple[List[float], List[float]]:
    """读取 TXT/CSV 两列数值数据。

    Args:
        path: 数据文件（第一列 x，第二列 y）。

    Returns:
        (x_list, y_list)。
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"数据文件不存在：{path}")
    xs, ys = [], []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(("#", ";", "//")):
                continue
            parts = re.split(r"[,\t\s]+", line)
            if len(parts) < 2:
                continue
            try:
                xs.append(float(parts[0]))
                ys.append(float(parts[1]))
            except ValueError:
                continue
    if len(xs) < 5:
        raise ValueError(f"有效数据点不足（{len(xs)}），需至少 5 个")
    return xs, ys


# ─────────────────────────────────────────────────────────────
# ① XRD 数据预处理
# ─────────────────────────────────────────────────────────────
def _background_subtract(x: List[float], y: List[float], window: int = 50) -> List[float]:
    """简单移动平均法估计背景并扣除。"""
    import numpy as np

    yy = np.array(y, dtype=float)
    n = len(yy)
    w = max(3, min(window, n // 3))
    kernel = np.ones(w) / w
    bg = np.convolve(yy, kernel, mode="same")
    # 边界处理：卷积端点偏差用原始值近似
    return (yy - bg).tolist()


def _smooth(y: List[float], window: int = 7) -> List[float]:
    """Savitzky-Golay 平滑（numpy 实现，二次多项式）。"""
    import numpy as np

    yy = np.array(y, dtype=float)
    w = window if window % 2 == 1 else window + 1
    if w < 5 or w > len(yy):
        w = min(5, len(yy) if len(yy) % 2 == 1 else len(yy) - 1)
        if w < 3:
            return y
    half = w // 2
    # 二次多项式 SG 系数（w=5: [-3,12,17,12,-3]/35 等，通用公式计算）
    coeffs = _sg_coeffs(w, 2)
    out = np.copy(yy)
    for i in range(half, len(yy) - half):
        seg = yy[i - half : i + half + 1]
        out[i] = float(np.dot(seg, coeffs))
    return out.tolist()


def _sg_coeffs(window: int, polyorder: int) -> Any:
    """计算 Savitzky-Golay 平滑（中心）滤波系数，返回长度 = window。

    对窗口内数据做最小二乘多项式拟合 p(t)=A·c，中心(t=0)平滑值 = c0。
    因此滤波系数向量为 (A^T A)^-1 · A^T 的**常数项行（第 0 行）**，
    长度必须等于 window，才能与等长滑动窗口 seg 做点积。
    """
    import numpy as np

    half = window // 2
    x = np.arange(-half, half + 1, dtype=float)
    order = np.arange(polyorder + 1)
    A = x[:, None] ** order[None, :]
    AtA = A.T @ A
    H = np.linalg.solve(AtA, A.T)  # (polyorder+1, window)
    # 中心平滑值 = p(0) = c0 → 取第 0 行（常数项）
    return H[0, :]


def _find_peaks(x: List[float], y: List[float], min_prominence: float, min_distance: int = 3) -> List[Dict[str, Any]]:
    """简单峰识别：局部极大 + 显著性过滤（不需要 scipy）。"""
    peaks: List[Dict[str, Any]] = []
    n = len(y)
    ys = y
    base = min(ys) if ys else 0
    span = max(ys) - base if ys else 1
    for i in range(1, n - 1):
        if ys[i] >= ys[i - 1] and ys[i] >= ys[i + 1] and ys[i] > ys[i + 1]:
            # 局部极大（用邻域比较提高鲁棒性）
            window = max(2, min_distance)
            left = ys[max(0, i - window) : i]
            right = ys[i + 1 : min(n, i + window + 1)]
            if left and right and ys[i] >= max(left) and ys[i] >= max(right):
                local_base = max(min(left), min(right))
                prominence = ys[i] - local_base
                if prominence >= min_prominence * span:
                    peaks.append({"position_2theta": round(x[i], 3), "intensity": round(ys[i], 2),
                                  "prominence": round(prominence, 2)})
    # 按强度排序输出
    peaks.sort(key=lambda p: p["intensity"], reverse=True)
    return peaks[:20]


def xrd_preprocess_tool(
    file_path: str,
    background_window: int = 50,
    smooth_window: int = 7,
    min_prominence: float = 0.02,
    **kwargs: Any,
) -> Dict[str, Any]:
    """XRD 数据预处理：背景扣除、平滑、峰位识别。

    Args:
        file_path: XRD 原始数据文件（第一列 2θ，第二列强度）。
        background_window: 背景估计窗口点数（默认 50）。
        smooth_window: 平滑窗口（奇数，默认 7）。
        min_prominence: 峰显著性阈值（相对峰高跨度比例，默认 0.02）。

    Returns:
        处理后的峰列表与数据摘要。
    """
    try:
        xs, ys = _load_xy(file_path)
    except (FileNotFoundError, ValueError) as exc:
        return {"error": str(exc), "file_path": file_path}
    try:
        import numpy as np  # noqa: F401
    except ImportError:
        return {"error": "需要 numpy 支持：pip install numpy"}
    bg_sub = _background_subtract(xs, ys, background_window)
    smoothed = _smooth(bg_sub, smooth_window)
    peaks = _find_peaks(xs, smoothed, min_prominence)
    return {
        "file_path": file_path,
        "data_points": len(xs),
        "peaks_found": len(peaks),
        "peaks": peaks,
        "processed_summary": {
            "background_subtracted": True,
            "smooth_window": smooth_window,
            "min_prominence": min_prominence,
        },
        "note": "处理仅用于快速预览；正式精修建议使用 FullProf / HighScore 等专业软件",
    }


XRD_PREPROCESS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": "XRD 数据预处理：背景扣除、平滑、峰位识别，输出衍射峰列表。",
    "examples": [{"file_path": "xrd_data.txt"}],
    "properties": {
        "file_path": {"type": "string", "description": "XRD 数据文件路径（第一列 2θ，第二列强度）"},
        "background_window": {"type": "number", "description": "背景估计窗口点数（默认 50）"},
        "smooth_window": {"type": "number", "description": "平滑窗口奇数（默认 7）"},
        "min_prominence": {"type": "number", "description": "峰显著性阈值（默认 0.02）"},
    },
    "required": ["file_path"],
    "additionalProperties": False,
}


# ─────────────────────────────────────────────────────────────
# ② 批量数据归一化
# ─────────────────────────────────────────────────────────────
def _normalize_series(y: List[float], method: str) -> List[float]:
    """单序列归一化。"""
    import numpy as np

    yy = np.array(y, dtype=float)
    if method == "minmax":
        lo, hi = float(np.min(yy)), float(np.max(yy))
        return [float((v - lo) / (hi - lo)) if hi > lo else 0.0 for v in yy]
    if method == "zscore":
        mu, sd = float(np.mean(yy)), float(np.std(yy))
        return [float((v - mu) / sd) if sd > 0 else 0.0 for v in yy]
    if method in ("area", "integral"):
        total = float(np.sum(np.abs(yy)))
        return [float(v / total) if total > 0 else 0.0 for v in yy]
    if method == "max":
        mx = float(np.max(np.abs(yy)))
        return [float(v / mx) if mx > 0 else 0.0 for v in yy]
    raise ValueError(f"未知归一化方式：{method}（可选 minmax / zscore / area / max）")


def data_normalize_tool(
    file_path: str,
    method: str = "minmax",
    output_dir: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """批量数据归一化：支持多种方式，输出处理结果（可选保存）。

    Args:
        file_path: 数据文件路径（第一列 x，第二列 y）。
        method: 归一化方式：minmax / zscore / area / max。
        output_dir: 输出目录（可选，不填仅返回处理结果）。

    Returns:
        归一化后的数据（前若干点预览）+ 统计信息。
    """
    try:
        xs, ys = _load_xy(file_path)
    except (FileNotFoundError, ValueError) as exc:
        return {"error": str(exc), "file_path": file_path}
    try:
        norm = _normalize_series(ys, method)
    except ValueError as exc:
        return {"error": str(exc)}
    preview = [{"x": round(xs[i], 4), "y": round(norm[i], 6)} for i in range(min(8, len(norm)))]
    saved_path = None
    if output_dir:
        try:
            os.makedirs(output_dir, exist_ok=True)
            out = os.path.join(output_dir, os.path.splitext(os.path.basename(file_path))[0] + f"_{method}.txt")
            with open(out, "w", encoding="utf-8") as f:
                for xi, yi in zip(xs, norm):
                    f.write(f"{xi}\t{yi:.6f}\n")
            saved_path = out
        except OSError as exc:
            return {"error": f"保存失败：{exc}"}
    import numpy as np

    return {
        "file_path": file_path,
        "method": method,
        "points": len(norm),
        "min": round(float(min(norm)), 6),
        "max": round(float(max(norm)), 6),
        "mean": round(float(np.mean(norm)), 6),
        "preview": preview,
        "saved_to": saved_path,
    }


DATA_NORMALIZE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": "批量数据归一化：minmax / zscore / area / max。",
    "examples": [{"file_path": "spectrum.txt", "method": "minmax"}],
    "properties": {
        "file_path": {"type": "string", "description": "数据文件路径（第一列 x，第二列 y）"},
        "method": {"type": "string", "enum": ["minmax", "zscore", "area", "max"],
                   "description": "归一化方式：minmax 最小最大 / zscore 标准差 / area 面积归一 / max 最大值"},
        "output_dir": {"type": "string", "description": "输出目录（可选）"},
    },
    "required": ["file_path", "method"],
    "additionalProperties": False,
}


# ─────────────────────────────────────────────────────────────
# 注册
# ─────────────────────────────────────────────────────────────
def _check_data_available() -> bool:
    return True


registry.register(
    name="xrd_preprocess",
    toolset="matlens_material",
    schema=XRD_PREPROCESS_SCHEMA,
    handler=lambda args, **kw: tool_result(xrd_preprocess_tool(**args)),
    check_fn=_check_data_available,
    description="XRD 数据预处理：背景扣除、平滑、峰位识别，输出衍射峰列表",
    emoji="📈",
)

registry.register(
    name="data_normalize",
    toolset="matlens_material",
    schema=DATA_NORMALIZE_SCHEMA,
    handler=lambda args, **kw: tool_result(data_normalize_tool(**args)),
    check_fn=_check_data_available,
    description="批量数据归一化：minmax / zscore / 面积归一 / 最大值归一，支持保存结果",
    emoji="📉",
)


# ─────────────────────────────────────────────────────────────
# xrd_dspacing：Bragg 2θ ↔ 晶面间距 d 互转
# ─────────────────────────────────────────────────────────────
import math as _math

# 常用 X 射线靶 Kα1 波长（Å）
_XRD_TARGETS = {
    "cu": 1.5406,
    "co": 1.7902,
    "fe": 1.9374,
    "mo": 0.7107,
    "cr": 2.2910,
    "ag": 0.5594,
}


def xrd_dspacing_tool(
    value: float,
    mode: str = "twotheta_to_d",
    target: str = "Cu",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Bragg 方程 2θ ↔ 晶面间距 d 互转（d = λ / (2·sinθ)）。

    Args:
        value: 输入值（2θ 角度或 d 值 Å）。
        mode: "twotheta_to_d"（2θ→d）| "d_to_twotheta"（d→2θ）。
        target: 靶名 Cu/Co/Fe/Mo/Cr/Ag（大小写不敏感）或直接给波长 Å。

    Returns:
        转换结果与所用波长。
    """
    key = str(target).strip().lower()
    lam = _XRD_TARGETS.get(key)
    if lam is None:
        try:
            lam = float(target)
        except (TypeError, ValueError):
            return {"error": f"未知靶：{target}（可用 Cu/Co/Fe/Mo/Cr/Ag 或直接给波长 Å）"}
    if lam <= 0:
        return {"error": "波长必须 > 0"}
    if value <= 0:
        return {"error": "value 必须 > 0"}

    if mode == "twotheta_to_d":
        theta_rad = _math.radians(value / 2.0)
        d = lam / (2.0 * _math.sin(theta_rad))
        return {
            "mode": "2θ→d",
            "twotheta_deg": value,
            "d_spacing_A": round(d, 4),
            "wavelength_A": lam,
            "target": target,
            "calculation": f"d = {lam:.4f} / (2·sin({value/2:.4f}°)) = {d:.4f} Å",
        }
    if mode == "d_to_twotheta":
        ratio = lam / (2.0 * value)
        if abs(ratio) > 1:
            return {"error": f"无法求解：λ/(2d) = {ratio:.4f} 超出 asin 定义域（晶面间距过小）"}
        twotheta = _math.degrees(2.0 * _math.asin(ratio))
        return {
            "mode": "d→2θ",
            "d_spacing_A": value,
            "twotheta_deg": round(twotheta, 4),
            "wavelength_A": lam,
            "target": target,
            "calculation": f"2θ = 2·asin({lam:.4f}/(2×{value:.4f})) = {twotheta:.4f}°",
        }
    return {"error": f"未知 mode：{mode}（支持 twotheta_to_d / d_to_twotheta）"}


XRD_DSPACING_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": "Bragg 晶面间距换算：2θ↔d 互转（支持 Cu/Co/Fe/Mo/Cr 靶）。",
    "examples": [{"value": 28.4, "mode": "twotheta_to_d", "target": "Cu"}],
    "properties": {
        "value": {"type": "number", "description": "2θ（度）或 d（Å），取决于 mode"},
        "mode": {
            "type": "string",
            "description": "twotheta_to_d（2θ→d，默认）| d_to_twotheta（d→2θ）",
        },
        "target": {"type": "string", "description": "靶：Cu/Co/Fe/Mo/Cr/Ag 或直接给波长 Å"},
    },
    "required": ["value"],
    "additionalProperties": False,
}


registry.register(
    name="xrd_dspacing",
    toolset="matlens_material",
    schema=XRD_DSPACING_SCHEMA,
    handler=lambda args, **kw: tool_result(xrd_dspacing_tool(**args)),
    check_fn=_check_data_available,
    description="Bragg 晶面间距换算：2θ↔d 互转（支持 Cu/Co/Fe/Mo/Cr 常用靶）",
    emoji="📐",
)
