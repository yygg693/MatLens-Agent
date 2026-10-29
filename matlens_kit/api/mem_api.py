"""记忆 API —— 复用 matlens 统一后端的 Mem0MemoryProvider。

设计原则（见 design/backend-api.md）：
- 不另写记忆存储，直接走 agent 的 MemoryManager → Mem0MemoryProvider
  （与对话中 mem0_search/mem0_add 走同一条后端链路）。
- 后端不可用（如 qdrant 本地锁异常）时优雅返回 503，不拖垮前端。
- 记忆文本含 [用户]/[实验]/[材料]/[结论] 类别标签，API 解析为 category 字段。
"""
from __future__ import annotations

import json
import re
import threading
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

# The production dashboard server (matlens_cli/web_server.py) already owns
# ``/api/memory`` for *provider* status and cannot hand it over, so this
# module is mounted twice:
#
#   * ``/api/memory``   — the kit server (matlens_kit/api/server.py) and the
#                          design prototype, unchanged from before.
#   * ``/api/memories`` — the dashboard server, where the path is free.
#
# Both mounts serve the same endpoints; only the prefix differs.
MEMORY_ROUTES_PREFIX = "/api/memory"
MEMORY_CONTENT_PREFIX = "/api/memories"

# 记忆类别标签正则：[用户] [实验] [材料] [结论] ...
_CAT_RE = re.compile(r"^\s*\[([^\]]+)\]\s*")

# agent 初始化可能因 qdrant 导入阻塞而长时间挂起；用超时守卫避免拖垮 HTTP 请求。
_AGENT_CACHE: Dict[str, Any] = {}
_AGENT_LOCK = threading.Lock()


def _get_agent_timed(timeout: float = 45) -> Any:
    with _AGENT_LOCK:
        if "_agent" in _AGENT_CACHE:
            return _AGENT_CACHE["_agent"]
    box: Dict[str, Any] = {}

    def _t() -> None:
        try:
            from matlens_kit.ui.common import get_agent

            box["a"] = get_agent()
        except Exception as e:  # noqa: BLE001
            box["e"] = e

    th = threading.Thread(target=_t, daemon=True, name="mem-agent-fetch")
    th.start()
    th.join(timeout)
    if "a" in box:
        with _AGENT_LOCK:
            _AGENT_CACHE["_agent"] = box["a"]
        return box["a"]
    if "e" in box:
        raise box["e"]
    raise TimeoutError("agent 初始化超时（可能 qdrant 导入阻塞）")


def _get_provider():
    """取 mem0 provider（统一后端）。任何失败都返回 None，由调用方降级。"""
    try:
        agent = _get_agent_timed()
        mm = getattr(agent, "_memory_manager", None)
        if mm is None:
            import sys as _sys
            print("[mem_api] memory_manager is None", file=_sys.stderr, flush=True)
            return None
        prov = mm.get_provider("mem0")
        import sys as _sys
        print(f"[mem_api] provider={type(prov).__name__ if prov else None} backend={getattr(prov, '_backend', 'N/A') if prov else None}", file=_sys.stderr, flush=True)
        return prov
    except Exception as e:
        import sys as _sys
        print(f"[mem_api] _get_provider failed: {type(e).__name__}: {e}", file=_sys.stderr, flush=True)
        return None


def _backend_ready(provider) -> bool:
    if provider is None:
        return False
    return getattr(provider, "_backend", None) is not None


def _memory_settings() -> Dict[str, Any]:
    """实时读取 memory 设置段（settings_store 不做进程内缓存）。读取失败回退默认。"""
    try:
        from matlens_kit import settings_store

        return settings_store.get_section("memory")
    except Exception:
        return {"enabled": True, "auto_write": True, "graph_auto_build": True, "provider": "mem0"}


def _exact_count(provider) -> Optional[int]:
    """Count the stored memories for real.

    The previous implementation searched with a broad query and counted the
    hits, which is a *sample*, not a total: a vector search only returns the
    nearest neighbours, so the number it reported was capped by top_k and
    drifted from the true size of the store. Ask the backend for an exact
    count first; fall back to the page listing's own total, and only then to
    the old sampling so the UI still gets a number.
    """
    try:
        if not _backend_ready(provider):
            return None
        counter = getattr(provider, "count_memories", None)
        if callable(counter):
            total = counter()
            if isinstance(total, int):
                return total
        lister = getattr(provider, "list_memories", None)
        if callable(lister):
            data = lister(page=1, page_size=1)
            if isinstance(data, dict):
                total = data.get("total")
                if isinstance(total, int):
                    return total
                count = data.get("count")
                if isinstance(count, int):
                    return count
        return _best_effort_count(provider)
    except Exception:
        return None


def _best_effort_count(provider) -> Optional[int]:
    """最佳努力统计记忆条数：后端未就绪/出错一律返回 None，绝不挂死、不抛错。"""
    try:
        if not _backend_ready(provider):
            return None
        raw = provider.handle_tool_call(
            "mem0_search",
            {"query": "材料 科研 实验 用户 结论 方向 参数 偏好", "top_k": 100},
        )
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                return None
        results = raw.get("results", []) if isinstance(raw, dict) else []
        return len(results) if isinstance(results, list) else None
    except Exception:
        return None


def _backend_source(provider) -> Optional[str]:
    """JSON 安全的后端来源标识字符串（绝不把后端对象放进响应）。

    真实后端是 plugins.memory.mem0._backend.OSSBackend 等实例，直接放进 dict 会让
    FastAPI/Pydantic 序列化炸掉。这里只取可读标识：优先 provider._mode/_host 语义，
    兜底用后端类名；后端未就绪时返回 None。
    """
    try:
        backend = getattr(provider, "_backend", None)
        if backend is None:
            return None
        mode = str(getattr(provider, "_mode", "") or "").lower()
        host = getattr(provider, "_host", None)
        if mode == "oss":
            return "oss"
        if host:
            return "self-hosted"
        if mode == "platform":
            return "platform"
        # 兜底：后端类名（OSSBackend / SelfHostedBackend / PlatformBackend）
        return type(backend).__name__
    except Exception:
        return None


def _call(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """走 provider 公开工具接口；统一把 JSON 字符串解析为 dict。"""
    provider = _get_provider()
    if not _backend_ready(provider):
        raise HTTPException(
            status_code=503,
            detail="记忆后端未就绪（Mem0/qdrant 未初始化）。请检查 ~/.matlens/mem0_qdrant 与 mem0.json。",
        )
    raw = provider.handle_tool_call(tool_name, args)
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {"raw": raw}
    return raw if isinstance(raw, dict) else {"raw": str(raw)}


def _categorize(text: str) -> str:
    m = _CAT_RE.match(text or "")
    if m:
        return m.group(1)
    return "其他"


def _normalize(item: Dict[str, Any]) -> Dict[str, Any]:
    memory = item.get("memory") or item.get("text") or ""
    meta = item.get("metadata")
    if not isinstance(meta, dict):
        meta = {}
    created_at = item.get("created_at") or meta.get("created_at")
    out = {
        "id": item.get("id"),
        "memory": memory,
        "category": _categorize(memory),
        "score": item.get("score", 0),
        "created_at": created_at,
        "updated_at": item.get("updated_at") or meta.get("updated_at"),
        "source_type": meta.get("source_type"),
        "source_ref": meta.get("source_ref"),
        "confidence": meta.get("confidence"),
        "metadata": meta,
    }
    # 混合检索会在每行盖一个融合分；带上它，前端才能说清这条是
    # 「向量命中」「关键词命中」还是「两边都命中」。
    if isinstance(item.get("rrf_score"), (int, float)):
        out["rrf_score"] = item["rrf_score"]
    return out


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class AddMemoryReq(BaseModel):
    content: str


class UpdateMemoryReq(BaseModel):
    text: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
def list_memories(
    q: str = Query("", description="检索词；留空则取代表性记忆集合"),
    top_k: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0, description="分页偏移量"),
    limit: int = Query(30, ge=1, le=200, description="单页条数"),
) -> Dict[str, Any]:
    """列出/检索记忆。无 query 时用宽泛词拉取近期记忆集合。

    检索与浏览是两条不同的路径：
    - 带 ``q`` 时走语义检索（向量近邻），天然只返回最相关的一批。
    - 不带 ``q`` 时走全量列举（``mem0_list``），可以翻页看到第 51 条之后
      的内容——这是旧的 top_k 截断永远做不到的。
    """
    # 总开关关闭时不报错：返回空集合（不构造 agent、不打后端）。
    if not bool(_memory_settings().get("enabled", True)):
        return {
            "ok": True, "count": 0, "total": 0, "query": q.strip(),
            "memories": [], "offset": offset, "limit": limit,
            "has_more": False, "disabled": True,
        }

    provider = _get_provider()
    if not _backend_ready(provider):
        raise HTTPException(
            status_code=503,
            detail="记忆后端未就绪（Mem0/qdrant 未初始化）。请检查 ~/.matlens/mem0_qdrant 与 mem0.json。",
        )

    query = q.strip()
    if query:
        # 语义检索：先多取一条用于判断是否还有更多。
        fetch_k = min(max(limit, top_k) + 1, 200)
        res = _call("mem0_search", {"query": query, "top_k": fetch_k})
        results = res.get("results", []) if isinstance(res, dict) else []
        window = results[offset:offset + limit]
        items = [_normalize(r) for r in window]
        has_more = len(results) > offset + limit
        return {
            "ok": True, "count": len(items), "total": len(results),
            "query": query, "memories": items,
            "offset": offset, "limit": limit, "has_more": has_more,
            "mode": "search",
        }

    # 全量浏览：按窗口列举。
    page = offset // limit + 1
    lister = getattr(provider, "list_memories", None)
    if not callable(lister):
        # 后端不支持列举 —— 退化为宽搜抽样（总数不可信，仅供前端显示）。
        res = _call("mem0_search", {
            "query": "材料 科研 实验 用户 结论 方向 参数",
            "top_k": min(max(limit, top_k) + 1, 200),
        })
        results = res.get("results", []) if isinstance(res, dict) else []
        window = results[offset:offset + limit]
        items = [_normalize(r) for r in window]
        return {
            "ok": True, "count": len(items), "total": len(results),
            "query": "", "memories": items,
            "offset": offset, "limit": limit,
            "has_more": len(results) > offset + limit, "mode": "browse",
        }

    # offset 直接下传给 provider：后端能原生分页就原生分页，
    # 只能按页取的就按覆盖该窗口的页取回后本地切片。
    try:
        data = lister(page=page, page_size=limit, offset=offset)
    except TypeError:
        # 老 provider 只认 page/page_size。
        data = lister(page=page, page_size=limit)
    rows = data.get("results", []) if isinstance(data, dict) else []
    if not isinstance(rows, list):
        rows = []
    window = rows[:limit]
    items = [_normalize(r) for r in window]
    total = data.get("total") if isinstance(data, dict) else None
    has_more = data.get("has_more") if isinstance(data, dict) else None
    if not isinstance(has_more, bool):
        has_more = (
            offset + len(items) < total if isinstance(total, int) else False
        )
    return {
        "ok": True, "count": len(items),
        "total": total if isinstance(total, int) else None,
        "query": "", "memories": items,
        "offset": offset, "limit": limit, "has_more": has_more, "mode": "browse",
    }


def add_memory(req: AddMemoryReq) -> Dict[str, Any]:
    """新增一条记忆（无 LLM 抽取，原样存储）。"""
    # 总开关关闭：明确拒绝手动写入，返回 ok:false（不抛 503）。
    if not bool(_memory_settings().get("enabled", True)):
        return {"ok": False, "error": "记忆已关闭"}
    content = (req.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content 不能为空")
    res = _call("mem0_add", {"content": content})
    return {"ok": True, **res}


def memory_status() -> Dict[str, Any]:
    """记忆子系统状态：设置开关 + 后端就绪情况 + 记忆条数（真实计数）。

    形状（契约第 3 节）：
        {ok, enabled, provider, source, count, auto_write, graph_auto_build}
    enabled=false 时不构造 agent、不碰后端，count=null。
    """
    mem = _memory_settings()
    enabled = bool(mem.get("enabled", True))
    provider_name = mem.get("provider", "mem0")
    source: Optional[str] = None
    count: Optional[int] = None
    if enabled:
        try:
            prov = _get_provider()
            if _backend_ready(prov):
                # 必须取可读标识字符串，不能把后端对象塞进响应（Pydantic 序列化会炸）
                source = _backend_source(prov)
                count = _exact_count(prov)
        except Exception:
            count = None
    out = {
        "ok": True,
        "enabled": enabled,
        "provider": provider_name,
        "source": source,
        "count": count,
        "auto_write": bool(mem.get("auto_write", True)),
        "graph_auto_build": bool(mem.get("graph_auto_build", True)),
    }
    # 兜底自检：任何字段意外带了不可序列化对象，退化为安全的 source=None/count=None，
    # 绝不把 500 抛给前端。
    try:
        json.dumps(out)
    except Exception:
        out["source"] = None
        out["count"] = None
    return out


def get_memory(memory_id: str) -> Dict[str, Any]:
    """按 ID 取单条记忆详情（用于编辑前的回填）。

    必须按 ID 精确取：向量检索只能返回近邻，永远定位不到指定的那一条
    （旧实现用空 query 搜索再在结果里找 id，实际上永远取不到）。
    """
    provider = _get_provider()
    if not _backend_ready(provider):
        raise HTTPException(
            status_code=503,
            detail="记忆后端未就绪（Mem0/qdrant 未初始化）。请检查 ~/.matlens/mem0_qdrant 与 mem0.json。",
        )
    getter = getattr(provider, "get_memory", None)
    if callable(getter):
        raw = getter(memory_id)
        if isinstance(raw, dict) and raw:
            return {"ok": True, "memory": _normalize(raw)}
        return {"ok": True, "memory": None}

    # 兜底：后端不支持按 ID 取时，翻一页列举后本地匹配。
    lister = getattr(provider, "list_memories", None)
    if callable(lister):
        try:
            data = lister(page=1, page_size=200, offset=0)
        except TypeError:
            data = lister(page=1, page_size=200)
        for raw in (data.get("results") or []) if isinstance(data, dict) else []:
            if isinstance(raw, dict) and raw.get("id") == memory_id:
                return {"ok": True, "memory": _normalize(raw)}
    return {"ok": True, "memory": None}


def update_memory(memory_id: str, req: UpdateMemoryReq) -> Dict[str, Any]:
    """按 ID 更新记忆文本。"""
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text 不能为空")
    res = _call("mem0_update", {"memory_id": memory_id, "text": text})
    return {"ok": True, **res}


def delete_memory(memory_id: str) -> Dict[str, Any]:
    """按 ID 删除记忆。"""
    res = _call("mem0_delete", {"memory_id": memory_id})
    return {"ok": True, **res}


def last_injection() -> Dict[str, Any]:
    """本轮注入了哪些记忆——供前端展示"Agent 用了什么"。

    记忆在检索时被拼成一段纯文本注入 system prompt，那段文本不带 id 与
    来源，用户无法回答"这句话是凭哪条记忆说的"。provider 在 prefetch 时
    已经拿到了完整的检索结果，这里把最近一次的结果透出来。
    """
    provider = _get_provider()
    if not _backend_ready(provider):
        return {"ok": True, "memories": [], "count": 0, "available": False}
    getter = getattr(provider, "last_injected_memories", None)
    if not callable(getter):
        return {"ok": True, "memories": [], "count": 0, "available": False}
    try:
        items = getter() or []
    except Exception:
        return {"ok": True, "memories": [], "count": 0, "available": False}
    normalized = [_normalize(i) if isinstance(i, dict) else i for i in items]
    return {
        "ok": True, "memories": normalized, "count": len(normalized),
        "available": True,
    }


def build_router(prefix: str = MEMORY_ROUTES_PREFIX) -> APIRouter:
    """Build the memory-content router under a caller-chosen prefix.

    The same endpoints are mounted twice: the kit server keeps the historical
    ``/api/memory`` path, while the dashboard server — where ``/api/memory``
    already means "provider status" — mounts them at ``/api/memories``.
    """
    router = APIRouter(prefix=prefix, tags=["memory"])

    router.add_api_route("", list_memories, methods=["GET"], name="list_memories")
    router.add_api_route("", add_memory, methods=["POST"], name="add_memory")
    router.add_api_route("/status", memory_status, methods=["GET"], name="memory_status")
    router.add_api_route(
        "/last-injection", last_injection, methods=["GET"], name="memory_last_injection"
    )
    router.add_api_route(
        "/{memory_id}", get_memory, methods=["GET"], name="get_memory"
    )
    router.add_api_route(
        "/{memory_id}", update_memory, methods=["PATCH"], name="update_memory"
    )
    router.add_api_route(
        "/{memory_id}", delete_memory, methods=["DELETE"], name="delete_memory"
    )
    return router


# Default router for the kit server (matlens_kit/api/server.py).
_router = build_router(MEMORY_ROUTES_PREFIX)
