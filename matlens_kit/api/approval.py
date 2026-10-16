# -*- coding: utf-8 -*-
"""MatLens Web 服务层 —— 工具级审批协调器（M5）。

前端审批卡联动链路：
1. agent 工具执行前，approval hook（tool_execution 中间件，注册在链首）检查策略
2. 策略命中"需审批" → 登记 request_id + 发 approval_request 事件（SSE）
3. hook 阻塞等待前端 POST /api/approvals/{request_id}/respond
4. approve → 放行执行（调 next_call 进入真实工具）
   deny / 超时 → 短路返回拒绝结果（fail-closed，工具不执行）

策略来自 config.yaml 的 tool_loop_guardrails（M4 配置 API 已读写同一字段）：
- enabled=false        → 全部放行（auto）
- strategy=confirm_list → allowlist 内放行，其余审批
- strategy=deny_list    → denylist 内直接拒绝，其余放行
- strategy=auto         → 全部放行
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

_router = APIRouter(prefix="/api/approvals", tags=["approvals"])


class _Pending:
    __slots__ = ("tool_name", "args", "session_id", "event", "decision", "ts")

    def __init__(self, tool_name: str, args: Any, session_id: str) -> None:
        self.tool_name = tool_name
        self.args = args
        self.session_id = session_id
        self.event = threading.Event()
        self.decision: Optional[str] = None
        self.ts = time.time()


_pending: Dict[str, _Pending] = {}
_lock = threading.Lock()


def _guardrails() -> Dict[str, Any]:
    try:
        from matlens_cli.config import load_config
        cfg = load_config()
        return cfg.get("tool_loop_guardrails", {}) or {}
    except Exception:
        return {}


def timeout() -> float:
    """审批等待上限：优先用官方 human_wait_ceiling，兜底 60s。"""
    try:
        from tools.approval import human_wait_ceiling
        v = float(human_wait_ceiling)
        if 5 <= v <= 600:
            return v
    except Exception:
        pass
    return 60.0


def request(tool_name: str, args: Any, session_id: str) -> Optional[str]:
    """按策略决定是否需要审批。

    返回：
    - None  → 放行（策略不要求审批）
    - "deny"→ 策略直接拒绝（deny_list 命中，无需用户确认）
    - 其他  → request_id，调用方应等待 await_decision()
    """
    g = _guardrails()
    if not g.get("enabled"):
        return None
    strategy = g.get("strategy", "auto")
    allow = set(g.get("allowlist") or [])
    deny = set(g.get("denylist") or [])

    if strategy == "confirm_list":
        if tool_name in allow:
            return None
        return _new_pending(tool_name, args, session_id)
    if strategy == "deny_list":
        if tool_name in deny:
            return "deny"
        return None
    return None  # auto


def _new_pending(tool_name: str, args: Any, session_id: str) -> str:
    rid = uuid.uuid4().hex
    with _lock:
        _pending[rid] = _Pending(tool_name, args, session_id)
    # 防泄漏：超时未响应自动清理（await_decision 返回 deny 后由 hook 清理）
    return rid


def await_decision(request_id: str, wait_s: Optional[float] = None) -> str:
    """阻塞等待前端决定；超时返回 'deny'（fail-closed）。"""
    p = _pending.get(request_id)
    if p is None:
        return "deny"
    if p.event.wait(wait_s or timeout()):
        return p.decision or "deny"
    return "deny"


def respond(request_id: str, decision: str, reason: str = "") -> bool:
    """前端回传决定；不存在/已过期返回 False。"""
    if decision not in ("approve", "deny"):
        return False
    with _lock:
        p = _pending.get(request_id)
        if p is None:
            return False
        p.decision = decision
        p.event.set()
    return True


def cleanup(request_id: str) -> None:
    with _lock:
        _pending.pop(request_id, None)


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
class ApprovalRespond(BaseModel):
    decision: str
    reason: str = ""


@_router.post("/{request_id}/respond")
def respond_approval(request_id: str, req: ApprovalRespond) -> Dict[str, Any]:
    """前端审批卡回传：approve / deny。"""
    if not respond(request_id, req.decision, req.reason):
        raise HTTPException(status_code=404, detail="审批请求不存在或已过期")
    return {"ok": True, "request_id": request_id, "decision": req.decision}
