# -*- coding: utf-8 -*-
"""导出质量门：quality 分过低 / 存在红色问题时，导出前警告。

设计取向：**警告而非阻断**。学术写作场景下用户有权决定是否导出，
硬阻断会在「先导出看看」这类正常操作上制造障碍。因此：

- 返回结构与 :mod:`export` 门面一致（``ok``/``error``），不破坏既有调用方；
- 门只在「真的有问题」时触发，且阈值可配置（settings papers.export_quality_gate）；
- 论文没跑过quality 步时**不拦**（无据不判）；
- 带 ``force=1`` 可跳过（前端「仍然导出」按钮）。

纯本地计算，不调模型、不调网络。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from matlens_kit.paper.quality import check_quality

#: 默认最低分（低于此值警告）
DEFAULT_MIN_SCORE = 60
#: 默认设置：警告但不阻断
DEFAULT_ENABLED = True


def gate_settings() -> Dict[str, Any]:
    """实时读 settings papers 段的导出质量门配置。"""
    try:
        from matlens_kit import settings_store

        return settings_store.get_section("papers") or {}
    except Exception:
        return {}


def _to_int(v: Any, default: int) -> int:
    try:
        n = int(v)
        return n if n > 0 else default
    except Exception:
        return default


def evaluate(
    paper: Dict[str, Any],
    min_score: Optional[int] = None,
    enabled: Optional[bool] = None,
) -> Dict[str, Any]:
    """评估导出质量门。返回::

        {"passed": bool, "score": int|None, "checked": bool,
         "reasons": [str], "blocking": [str]}

    ``checked=False`` 表示未跑过 quality 步（或正文为空）→ 不做任何判断。
    ``blocking`` 里的每条都是硬伤（🔴），``reasons`` 是触发警告的原因。
    """
    cfg = gate_settings()
    if enabled is None:
        enabled = bool(cfg.get("export_quality_gate", DEFAULT_ENABLED))
    if min_score is None:
        min_score = _to_int(cfg.get("export_min_score"), DEFAULT_MIN_SCORE)

    stages = paper.get("stages") or {}
    draft = ((stages.get("write") or {}).get("content") or "").strip()
    refs = (stages.get("search") or {}).get("refs") or []
    q_status = ((stages.get("quality") or {}).get("status") or "pending")

    # 没跑过 quality → 无据不判，放行
    if q_status != "done" or not draft:
        return {"passed": True, "score": None, "checked": False, "reasons": [], "blocking": []}

    try:
        check = check_quality(draft, refs)
    except Exception as e:  # noqa: BLE001 —— 门不得因质检异常而挡住导出
        return {
            "passed": True,
            "score": None,
            "checked": False,
            "reasons": [f"质量检查未完成（{e}），已跳过质量门"],
            "blocking": [],
        }

    score = int(check.get("score") or 0)
    issues = check.get("issues") or []
    blocking = [i for i in issues if i.get("severity") == "🔴"]

    reasons: list = []
    if score < min_score:
        reasons.append(f"质量评分 {score}/100 低于阈值 {min_score}")
    if blocking:
        locs = "、".join(str(i.get("location") or "问题") for i in blocking[:3])
        reasons.append(f"存在 {len(blocking)} 项严重问题（{locs}）")

    return {
        "passed": not reasons,
        "score": score,
        "checked": True,
        "reasons": reasons,
        "blocking": [
            f"[{i.get('location', '问题')}] {i.get('issue', '')}"
            + (f" → 建议：{i['suggestion']}" if i.get("suggestion") else "")
            for i in blocking[:5]
        ],
        "threshold": min_score,
    }


def warning_message(verdict: Dict[str, Any]) -> str:
    """把评估结果渲染成给用户看的警告文本（前端弹窗用）。"""
    if verdict.get("passed") or not verdict.get("checked"):
        return ""
    lines = ["⚠️ 这篇论文尚未达到导出质量标准："]
    for r in verdict.get("reasons") or []:
        lines.append(f"· {r}")
    for b in verdict.get("blocking") or []:
        lines.append(f"  - {b}")
    lines.append("建议先执行「质量巡检」并按建议修订，或确认无误后强行导出。")
    return "\n".join(lines)