# -*- coding: utf-8 -*-
"""MatLens 旗舰工具：离子液体（IL）粘度机器学习预测。

面向真实课题「基于机器学习的离子液体粘度多因素影响机制及预测模型」。

能力：
- 输入阳离子类型、阴离子类型、温度 T(K)、压力 P(MPa)，
  用在模块加载时一次性训练好的轻量 GBDT（GradientBoostingRegressor）
  预测离子液体粘度 η (mPa·s)。
- 返回预测值、基于训练残差的 ±95% 置信区间、聚合后的特征重要性
  （温度 / 压力 / 阳离子 / 阴离子 谁主导），以及一张「预测 vs 实测」
  的 base64 PNG 散点图（前端 <img src="data:image/png;base64,..."> 直接渲染）。

训练数据为模块内用固定 random_state 生成的**确定性合成数据**：
    log η = log η0 + Ea/(R·T) + α·n_alkyl + log g_anion + β·P + ε
其中烷基链长单调增大粘度、不同阴离子给乘性因子、压力给弱增压项，
再叠加对数空间小噪声。物理量级对齐常见咪唑类离子液体（室温下
约 10~1000 mPa·s）。模型学习的是这个映射，而非任何真实测量值。

设计约束：
- matplotlib 强制 Agg 无头后端；图存 BytesIO → base64，绝不落盘。
- 模型 train-once（模块导入时），内存常驻，不写 ~/.matlens。
- handler 返回 JSON 字符串（tools.registry 约定）。
"""
from __future__ import annotations

import base64
import io
import json
import threading
from typing import Any, Dict, List, Tuple

from tools.registry import registry, tool_result, tool_error

# ── 类别表（与 schema enum 保持一致）────────────────────────────────
CATIONS: List[str] = ["[MMIM]+", "[EMIM]+", "[BMIM]+", "[HMIM]+", "[OMIM]+"]
ANIONS: List[str] = ["[BF4]-", "[PF6]-", "[Tf2N]-", "[Cl]-", "[Ac]-"]

# 烷基链长（主导阳离子侧粘度趋势：链越长粘度越高）
_CATION_CHAINLEN = {
    "[MMIM]+": 1,   # 1,3-二甲基
    "[EMIM]+": 2,   # 乙基
    "[BMIM]+": 4,   # 丁基
    "[HMIM]+": 6,   # 己基
    "[OMIM]+": 8,   # 辛基
}
# 阴离子乘性因子（log 空间加性）：Cl/Ac 强氢键 → 更粘；Tf2N 更稀
_ANION_LOG_FACTOR = {
    "[BF4]-": 0.00,
    "[PF6]-": 0.25,
    "[Tf2N]-": -0.20,
    "[Cl]-": 1.20,
    "[Ac]-": 1.50,
}

_R = 8.314  # J/(mol·K)
_LOG_ETA0 = -4.5       # 预指数因子 log(mPa·s)
_EA = 22000.0          # J/mol，活化能（主导温度依赖性）
_CHAIN_ALPHA = 0.12    # 每增加一个亚甲基的 log 粘度增益
_PRESSURE_BETA = 0.006 # /MPa，增压提升粘度
_NOISE_SIGMA = 0.08    # log 空间噪声标准差（≈8% 乘性）

# 特征列顺序（one-hot 后固定）
_CAT_DUMMY_COLS = [f"cation::{c}" for c in CATIONS]
_AN_DUMMY_COLS = [f"anion::{a}" for a in ANIONS]
_FEATURE_COLS = ["temperature_k", "pressure_mpa"] + _CAT_DUMMY_COLS + _AN_DUMMY_COLS


# ── 合成数据生成（确定性）────────────────────────────────────────────
def _synthesize(n: int = 3000, seed: int = 42) -> Tuple["Any", "Any"]:
    """生成确定性 (X, log_eta) 训练数据。返回 pandas DataFrame 与对数粘度数组。"""
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(seed)
    T = rng.uniform(280.0, 380.0, n)
    P = rng.uniform(0.1, 50.0, n)
    cat_idx = rng.integers(0, len(CATIONS), n)
    an_idx = rng.integers(0, len(ANIONS), n)

    chainlen = np.array([_CATION_CHAINLEN[CATIONS[i]] for i in cat_idx])
    an_logf = np.array([_ANION_LOG_FACTOR[ANIONS[i]] for i in an_idx])

    log_eta = (
        _LOG_ETA0
        + _EA / (_R * T)
        + _CHAIN_ALPHA * chainlen
        + an_logf
        + _PRESSURE_BETA * P
        + rng.normal(0.0, _NOISE_SIGMA, n)
    )

    rows: List[Dict[str, Any]] = {
        "temperature_k": T,
        "pressure_mpa": P,
    }
    X = pd.DataFrame(rows)
    for j, c in enumerate(CATIONS):
        X[f"cation::{c}"] = (cat_idx == j).astype(float)
    for j, a in enumerate(ANIONS):
        X[f"anion::{a}"] = (an_idx == j).astype(float)
    # 保证列顺序
    X = X[_FEATURE_COLS]
    return X, log_eta


# ── 模型单例（train-once）──────────────────────────────────────────
_model_lock = threading.Lock()
_model: Dict[str, Any] = {}


def _build_model() -> Dict[str, Any]:
    """一次性训练模型并缓存。失败时返回带 error 的 dict，不抛。"""
    try:
        import numpy as np
        from sklearn.ensemble import GradientBoostingRegressor
    except Exception as exc:  # noqa: BLE001
        return {"error": f"需要 scikit-learn/numpy：{exc}（pip install scikit-learn numpy）"}

    try:
        X, log_eta = _synthesize()
        model = GradientBoostingRegressor(
            n_estimators=160, max_depth=4, learning_rate=0.08,
            subsample=0.9, random_state=42,
        )
        model.fit(X.values, log_eta)
        pred_log = model.predict(X.values)
        resid = log_eta - pred_log
        sigma_log = float(np.std(resid))

        # 特征重要性聚合：温度 / 压力 / 阳离子 / 阴离子
        fi = model.feature_importances_
        fi_map = dict(zip(_FEATURE_COLS, fi))
        imp = {
            "temperature_k": float(fi_map["temperature_k"]),
            "pressure_mpa": float(fi_map["pressure_mpa"]),
            "cation": float(sum(fi_map[c] for c in _CAT_DUMMY_COLS)),
            "anion": float(sum(fi_map[a] for a in _AN_DUMMY_COLS)),
        }
        total = sum(imp.values()) or 1.0
        imp = {k: round(v / total, 4) for k, v in imp.items()}

        return {
            "model": model,
            "X_train": X,
            "log_eta_train": log_eta,
            "sigma_log": sigma_log,
            "feature_importance": imp,
            "n_train": int(len(X)),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": f"模型训练失败：{exc}"}


def _get_model() -> Dict[str, Any]:
    if "model" not in _model:
        with _model_lock:
            if "model" not in _model:
                _model.update(_build_model())
    return _model


def _encode(cation: str, anion: str, temperature_k: float, pressure_mpa: float) -> "Any":
    import numpy as np

    row = {c: 0.0 for c in _FEATURE_COLS}
    row["temperature_k"] = float(temperature_k)
    row["pressure_mpa"] = float(pressure_mpa)
    row[f"cation::{cation}"] = 1.0
    row[f"anion::{anion}"] = 1.0
    return np.array([[row[c] for c in _FEATURE_COLS]])


# ── 预测主逻辑 ─────────────────────────────────────────────────────
def predict_viscosity(
    cation: str = "[BMIM]+",
    anion: str = "[BF4]-",
    temperature_k: float = 303.15,
    pressure_mpa: float = 0.1,
    **kwargs: Any,
) -> Dict[str, Any]:
    """预测离子液体粘度 η (mPa·s)。

    Args:
        cation: 阳离子类型（枚举）。
        anion: 阴离子类型（枚举）。
        temperature_k: 温度 K（建议 280~380）。
        pressure_mpa: 压力 MPa（建议 0.1~50）。

    Returns:
        预测粘度、置信区间、特征重要性、模型描述与 base64 图。
    """
    if cation not in CATIONS:
        return {"error": f"未知阳离子 {cation!r}，可选：{CATIONS}"}
    if anion not in ANIONS:
        return {"error": f"未知阴离子 {anion!r}，可选：{ANIONS}"}
    try:
        T = float(temperature_k)
        P = float(pressure_mpa)
    except (TypeError, ValueError):
        return {"error": "temperature_k / pressure_mpa 必须是数值"}
    if not (250.0 <= T <= 420.0):
        return {"error": f"温度 {T} K 超出训练域 [250, 420]，外推不可信"}
    if not (-0.05 <= P <= 100.0):
        return {"error": f"压力 {P} MPa 超出训练域 [0, 100]，外推不可信"}

    bundle = _get_model()
    if "error" in bundle:
        return {"error": bundle["error"]}

    import numpy as np

    Xq = _encode(cation, anion, T, P)
    log_eta_pred = float(bundle["model"].predict(Xq)[0])
    eta = float(np.exp(log_eta_pred))

    sigma = bundle["sigma_log"]
    lo = float(np.exp(log_eta_pred - 1.96 * sigma))
    hi = float(np.exp(log_eta_pred + 1.96 * sigma))

    return {
        "cation": cation,
        "anion": anion,
        "temperature_k": T,
        "pressure_mpa": P,
        "eta_mpa_s": round(eta, 3),
        "ci95_mpa_s": [round(lo, 3), round(hi, 3)],
        "ci95_rel_pct": [round((lo / eta - 1) * 100, 1), round((hi / eta - 1) * 100, 1)],
        "feature_importance": bundle["feature_importance"],
        "plot_b64": _plot_pred_vs_actual(bundle),
        "model": {
            "kind": "GradientBoostingRegressor (log-target)",
            "n_train": bundle["n_train"],
            "rmse_log": round(sigma, 4),
            "note": "训练数据为确定性合成（Arrhenius/VFT 型经验公式 + 噪声），"
                    "用于演示多因素影响机制与快速预估；正式发表请替换为实测数据集重训。",
        },
    }


# ── 预测 vs 实测散点图（Agg + BytesIO + base64）────────────────────
def _plot_pred_vs_actual(bundle: Dict[str, Any]) -> str:
    """训练集上预测 vs 实测散点（1:1 线），返回 data:image/png;base64,... 字符串。"""
    try:
        import numpy as np
        import matplotlib
        matplotlib.use("Agg")  # 必须在 pyplot 之前
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001
        return f"matplotlib 不可用：{exc}"

    X = bundle["X_train"]
    log_act = bundle["log_eta_train"]
    log_pred = bundle["model"].predict(X.values)
    act = np.exp(log_act)
    pred = np.exp(log_pred)

    try:
        fig, ax = plt.subplots(figsize=(6.4, 5.2), dpi=130)
        fig.patch.set_facecolor("white")
        ax.scatter(act, pred, s=9, alpha=0.35, color="#2563eb", edgecolors="none")
        lo = min(act.min(), pred.min())
        hi = max(act.max(), pred.max())
        ax.plot([lo, hi], [lo, hi], "--", color="#dc2626", lw=1.4, label="1:1")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("Actual η (mPa·s)")
        ax.set_ylabel("Predicted η (mPa·s)")
        ax.set_title("IL Viscosity: Predicted vs Actual (train set)", fontsize=11)
        ax.grid(True, which="both", alpha=0.22)
        ax.legend(fontsize=9)
        fig.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        b64 = base64.b64encode(buf.read()).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except Exception as exc:  # noqa: BLE001
        return f"绘图失败：{exc}"


# ── Schema ─────────────────────────────────────────────────────────
IL_VISCOSITY_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": "离子液体粘度机器学习预测：输入阳离子/阴离子类型、温度、压力，"
                   "输出 η(mPa·s)、95% 置信区间与多因素特征重要性（旗舰工具）。",
    "properties": {
        "cation": {
            "type": "string",
            "description": "阳离子类型（咪唑类）",
            "enum": CATIONS,
            "default": "[BMIM]+",
        },
        "anion": {
            "type": "string",
            "description": "阴离子类型",
            "enum": ANIONS,
            "default": "[BF4]-",
        },
        "temperature_k": {
            "type": "number",
            "description": "温度，单位 K（训练域 280~380，外推受限）",
            "minimum": 250,
            "maximum": 420,
            "default": 303.15,
        },
        "pressure_mpa": {
            "type": "number",
            "description": "压力，单位 MPa（训练域 0.1~50）",
            "minimum": -0.05,
            "maximum": 100,
            "default": 0.1,
        },
    },
    "required": ["cation", "anion", "temperature_k", "pressure_mpa"],
    "additionalProperties": False,
    "examples": [
        {"cation": "[BMIM]+", "anion": "[BF4]-", "temperature_k": 303.15, "pressure_mpa": 0.1},
        {"cation": "[OMIM]+", "anion": "[Cl]-", "temperature_k": 323.15, "pressure_mpa": 10.0},
        {"cation": "[EMIM]+", "anion": "[Tf2N]-", "temperature_k": 353.15, "pressure_mpa": 0.1},
    ],
}


def _check_il_available() -> bool:
    return True


registry.register(
    name="il_viscosity_predict",
    toolset="matlens_material",
    schema=IL_VISCOSITY_SCHEMA,
    handler=lambda args, **kw: tool_result(predict_viscosity(**args)),
    check_fn=_check_il_available,
    description="离子液体粘度 ML 预测（阳离子/阴离子/温度/压力 → η mPa·s + 置信区间 + 特征重要性 + 散点图）",
    emoji="🧪",
)

# 模块加载时一次性训练（预热单例）；失败不阻断 import，仅在调用时返回错误。
_get_model()
