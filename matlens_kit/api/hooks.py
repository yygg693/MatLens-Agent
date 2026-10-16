# -*- coding: utf-8 -*-
"""MatLens Web 服务层 —— 中间件钩子。

把 Hermes 的工具执行中间件（tool_request / tool_execution）接到事件总线：
- tool_request  → 发 tool_call 事件（含参数）
- tool_execution → 发 tool_result 事件（含结果/状态）
- tool_execution（链首）→ 审批闸：approval_request 事件 + 等待前端回传

审批走 tool_execution 链：approval hook 在链首，approve 后调 next_call
进入事件 hook + 真实工具；deny/超时短路返回（fail-closed）。
"""
from __future__ import annotations

import json
import threading
import uuid
from typing import Any, Callable, Dict, Optional

try:
    from matlens_cli.middleware import TOOL_EXECUTION_MIDDLEWARE, TOOL_REQUEST_MIDDLEWARE
    from matlens_cli.plugins import get_plugin_manager
    _HAS_MIDDLEWARE = True
except Exception:  # pragma: no cover
    _HAS_MIDDLEWARE = False

_installed = False
_install_lock = threading.Lock()
_sessions: Dict[str, str] = {}  # thread_id -> session_id（当前对话的 session 上下文）
_ACTIVE_SESSION: str = ""       # 全局活动会话（工具子线程回退用，单用户 Web 场景）

# call_id 注册表：sid -> [{call_id, name}]，tool_call 时入队，tool_result 时按名出队
# 解决多实例同名工具（如连续多次 web_search）的状态匹配问题
_pending_calls: Dict[str, list] = {}
_pending_lock = threading.Lock()


def _push_pending(sid: str, name: str) -> str:
    cid = uuid.uuid4().hex[:8]
    with _pending_lock:
        _pending_calls.setdefault(sid, []).append({"call_id": cid, "name": name})
    return cid


def _pop_pending(sid: str, name: str) -> str:
    with _pending_lock:
        lst = _pending_calls.get(sid, [])
        for i, c in enumerate(lst):
            if c["name"] == name:
                lst.pop(i)
                return c["call_id"]
    return ""


def set_active_session(session_id: str) -> None:
    """标记当前线程归属的会话（对话开始前调用）。"""
    global _ACTIVE_SESSION
    _ACTIVE_SESSION = session_id
    _sessions[threading.get_ident()] = session_id


def clear_active_session() -> None:
    _sessions.pop(threading.get_ident(), None)


def _current_session() -> str:
    # 工具执行在 tool_executor 的子线程 → 线程映射缺失，回退全局活动会话
    return _sessions.get(threading.get_ident(), _ACTIVE_SESSION)


def _make_tool_call_hook() -> Callable[..., Any]:
    from matlens_kit.api.events import get_bus

    def hook(**kwargs: Any) -> Dict[str, Any]:
        tool_name = str(kwargs.get("tool_name") or "")
        args = kwargs.get("args") or {}
        # 优先用中间件传入的 session_id（tool_executor 注入），彻底避免多会话并发串话；
        # 兜底保留线程映射/全局（旧调用路径无 session_id 时）。
        sid = str(kwargs.get("session_id") or "") or _current_session()
        call_id = _push_pending(sid, tool_name)
        get_bus().publish(
            sid,
            "tool_call",
            {"call_id": call_id, "name": tool_name, "args": args},
        )
        return {}  # 不改参数，透传
    return hook


def _make_tool_result_hook() -> Callable[..., Any]:
    from matlens_kit.api.events import get_bus

    def hook(**kwargs: Any) -> Any:
        tool_name = str(kwargs.get("tool_name") or "")
        next_call = kwargs.get("next_call")
        sid = str(kwargs.get("session_id") or "") or _current_session()
        if not callable(next_call):
            # 理论上 tool_execution 链一定带 next_call；缺失则透传空结果
            return {}
        # 关键：执行链中间件必须调用 next_call() 拿到真实工具结果，再发布事件
        call_id = _pop_pending(sid, tool_name)
        try:
            real_result = next_call()
        except Exception as exc:  # 工具执行失败：发布错误事件后向上游传播
            get_bus().publish(
                sid,
                "tool_result",
                {"call_id": call_id, "name": tool_name, "result": f"ERROR: {exc}", "status": "error"},
            )
            raise
        get_bus().publish(
            sid,
            "tool_result",
            {"call_id": call_id, "name": tool_name, "result": str(real_result)[:4000]},
        )
        return real_result
    return hook


def _make_approval_hook() -> Callable[..., Any]:
    """审批闸（tool_execution 链首）：按策略拦截工具，等待前端回传。

    - 策略放行 → 调 next_call 进入下游（事件 hook + 真实工具）
    - 需审批  → 发 approval_request 事件 + 阻塞等待；approve 放行，deny/超时短路
    - deny_list 命中 → 直接拒绝（无需用户确认）
    """
    from matlens_kit.api import approval as A
    from matlens_kit.api.events import get_bus

    def hook(**kwargs: Any) -> Any:
        tool_name = str(kwargs.get("tool_name") or "")
        args = kwargs.get("args") or {}
        next_call = kwargs.get("next_call")
        sid = str(kwargs.get("session_id") or "") or _current_session()

        rid = A.request(tool_name, args, sid)
        if rid is None:
            return next_call() if callable(next_call) else {}
        if rid == "deny":
            return {
                "error": f"工具 {tool_name} 已被策略禁用",
                "denied": True,
                "tool": tool_name,
            }
        # 需要审批：发事件 + 阻塞等待
        wait_s = A.timeout()
        get_bus().publish(sid, "approval_request", {
            "request_id": rid,
            "tool": tool_name,
            "args": args,
            "timeout_s": wait_s,
        })
        try:
            decision = A.await_decision(rid, wait_s)
            if decision == "approve":
                return next_call() if callable(next_call) else {}
            return {
                "error": f"用户拒绝了工具 {tool_name}",
                "denied": True,
                "tool": tool_name,
                "request_id": rid,
            }
        finally:
            A.cleanup(rid)
    return hook


def install_hooks(force: bool = False) -> None:
    """注册工具执行中间件钩子（幂等；force=True 时强制重新注册）。

    agent 首次初始化会清空 plugin manager 的中间件注册表，
    因此服务端需在 get_agent() 之后以 force=True 再注册一次。
    """
    global _installed
    if not _HAS_MIDDLEWARE or (_installed and not force):
        return
    with _install_lock:
        if _installed and not force:
            return
        try:
            pm = get_plugin_manager()
            # 幂等：先移除旧的自身回调，再追加（避免重复注册）
            for kind in (TOOL_REQUEST_MIDDLEWARE, TOOL_EXECUTION_MIDDLEWARE):
                cb_list = pm._middleware.setdefault(kind, [])
                pm._middleware[kind] = [cb for cb in cb_list if not getattr(cb, "_matlens_hook", False)]
            tc = _make_tool_call_hook()
            tc._matlens_hook = True
            tr = _make_tool_result_hook()
            tr._matlens_hook = True
            ap = _make_approval_hook()
            ap._matlens_hook = True
            pm._middleware.setdefault(TOOL_REQUEST_MIDDLEWARE, []).append(tc)
            # 审批闸必须在链首：先审批，再事件，再真实工具
            ex_list = pm._middleware.setdefault(TOOL_EXECUTION_MIDDLEWARE, [])
            ex_list.insert(0, ap)
            ex_list.append(tr)
            _installed = True
        except Exception:
            _installed = False
