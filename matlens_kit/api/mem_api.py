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

_router = APIRouter(prefix="/api/memory", tags=["memory"])

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
    return {
        "id": item.get("id"),
        "memory": memory,
        "category": _categorize(memory),
        "score": item.get("score", 0),
        "created_at": item.get("created_at") or item.get("metadata", {}).get("created_at"),
        "metadata": item.get("metadata", {}),
    }


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
@_router.get("")
def list_memories(
    q: str = Query("", description="检索词；留空则取代表性记忆集合"),
    top_k: int = Query(30, ge=1, le=100),
) -> Dict[str, Any]:
    """列出/检索记忆。无 query 时用宽泛词拉取近期记忆集合。"""
    # 总开关关闭时不报错：返回空集合（不构造 agent、不打后端）。
    if not bool(_memory_settings().get("enabled", True)):
        return {"ok": True, "count": 0, "query": q.strip(), "memories": [], "disabled": True}
    query = q.strip() or "材料 科研 实验 用户 结论 方向 参数"
    res = _call("mem0_search", {"query": query, "top_k": top_k})
    results = res.get("results", []) if isinstance(res, dict) else []
    items = [_normalize(r) for r in results]
    return {"ok": True, "count": len(items), "query": query, "memories": items}


@_router.post("")
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


@_router.get("/status")
def memory_status() -> Dict[str, Any]:
    """记忆子系统状态：设置开关 + 后端就绪情况 + 记忆条数（最佳努力）。

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
                count = _best_effort_count(prov)
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


@_router.patch("/{memory_id}")
def update_memory(memory_id: str, req: UpdateMemoryReq) -> Dict[str, Any]:
    """按 ID 更新记忆文本。"""
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text 不能为空")
    res = _call("mem0_update", {"memory_id": memory_id, "text": text})
    return {"ok": True, **res}


@_router.delete("/{memory_id}")
def delete_memory(memory_id: str) -> Dict[str, Any]:
    """按 ID 删除记忆。"""
    res = _call("mem0_delete", {"memory_id": memory_id})
    return {"ok": True, **res}
