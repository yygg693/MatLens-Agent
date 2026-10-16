# -*- coding: utf-8 -*-
"""MatLens Web 服务层 —— 事件总线。

AIAgent 线程发布事件（stream_text / tool_call / tool_result / done / error），
SSE 端点订阅消费。线程安全，支持多客户端按 session_id 隔离。
"""
from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from typing import Any, Dict, Iterator, List, Optional


class EventBus:
    """线程安全事件总线：publish（任意线程）→ subscribe/stream（SSE 线程）。"""

    def __init__(self, maxsize: int = 2000) -> None:
        self._subs: Dict[str, "queue.Queue[Dict[str, Any]]"] = {}
        self._lock = threading.Lock()
        self._maxsize = maxsize

    def subscribe(self) -> str:
        """创建订阅，返回 sub_id。"""
        sid = uuid.uuid4().hex
        with self._lock:
            self._subs[sid] = queue.Queue(maxsize=self._maxsize)
        return sid

    def unsubscribe(self, sid: str) -> None:
        with self._lock:
            self._subs.pop(sid, None)

    def publish(self, session_id: str, kind: str, data: Dict[str, Any]) -> None:
        """发布事件到所有订阅（SSE 按 session_id 过滤）。"""
        evt: Dict[str, Any] = {
            "session_id": session_id,
            "type": kind,
            "data": data,
            "ts": time.time(),
        }
        payload = json.dumps(evt, ensure_ascii=False)
        with self._lock:
            for q in list(self._subs.values()):
                try:
                    q.put_nowait((evt, payload))
                except queue.Full:
                    pass

    def stream(
        self, sid: str, session_id: str = "", timeout: float = 15.0
    ) -> Iterator[str]:
        """阻塞迭代：yield SSE 帧。session_id 为空接收全部。（同步版本）"""
        q = self._subs.get(sid)
        if q is None:
            return
        while True:
            try:
                evt, payload = q.get(timeout=timeout)
            except queue.Empty:
                yield ": keepalive\n\n"
                continue
            if session_id and evt["session_id"] != session_id:
                continue
            yield f"data: {payload}\n\n"

    async def astream(self, sid: str, session_id: str = "") -> Any:
        """异步迭代（SSE 用）：阻塞等待替代忙轮询；终态事件后主动结束流。

        - 用 run_in_executor 阻塞 q.get(timeout=15)，空转时不再每 80ms 唤醒事件循环。
        - 收到 done/error 后 yield 并 return，连接自然关闭，不依赖前端 es.close()。
        - 超时空闲发 keepalive 注释帧，防中间代理断连。
        """
        import asyncio

        q = self._subs.get(sid)
        if q is None:
            return
        loop = asyncio.get_running_loop()
        while True:
            try:
                evt, payload = await loop.run_in_executor(None, q.get, True, 15.0)
            except queue.Empty:
                yield ": keepalive\n\n"
                continue
            if session_id and evt["session_id"] != session_id:
                continue
            yield f"data: {payload}\n\n"
            if evt["type"] in ("done", "error"):
                return


# 全局单例
_BUS: Optional[EventBus] = None
_BUS_LOCK = threading.Lock()


def get_bus() -> EventBus:
    global _BUS
    if _BUS is None:
        with _BUS_LOCK:
            if _BUS is None:
                _BUS = EventBus()
    return _BUS
