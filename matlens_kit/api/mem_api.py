"""记忆 API —— 复用 matlens 统一后端的 Mem0MemoryProvider。

设计原则（见 design/backend-api.md）：
- 不另写记忆存储，直接走 agent 的 MemoryManager → Mem0MemoryProvider
  （与对话中 mem0_search/mem0_add 走同一条后端链路）。
- 后端不可用（如 qdrant 本地锁异常）时优雅返回 503，不拖垮前端。
- 记忆文本含 [用户]/[实验]/[材料]/[结论] 类别标签，API 解析为 category 字段。
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
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

# 分类展示顺序：概览的占比条按这个序排，前后端共用同一个顺序。
CATEGORY_ORDER = ["用户", "实验", "材料", "结论", "其他"]

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


def _mark_superseded(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把软失效状态贴到列表行上，前端据此默认隐藏、也可单独筛选。"""
    ledger = _load_supersede()
    if not ledger:
        return items
    for item in items:
        entry = ledger.get(str(item.get("id") or ""))
        if isinstance(entry, dict):
            item["superseded_by"] = entry.get("keep_id")
            item["superseded_at"] = entry.get("at")
    return items


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class AddMemoryReq(BaseModel):
    content: str
    # 溯源三件套：provider 的 mem0_add 支持它们（_source_fields 会校验），
    # 这里必须透传，否则经 API/UI 写入的记忆永远没有来源标记。
    source_type: Optional[str] = None
    source_ref: Optional[str] = None
    confidence: Optional[float] = None


class UpdateMemoryReq(BaseModel):
    text: str


class MergeMemoryReq(BaseModel):
    """合并一组近重复记忆。

    ``mode="supersede"``（默认）不删任何东西，只把其余几条标记为"已被
    ``keep`` 取代"——列表里不再展示、检索不再召回，但随时可以撤销。这是
    Zep/Graphiti 双时间轴的本地简化版：事实演进靠失效旧边，不靠物理删除，
    所以合并天然可逆。

    ``mode="delete"`` 才是真删，只在用户明确要清掉时才用。
    """

    ids: List[str]
    keep: str
    mode: str = "supersede"
    merged_text: Optional[str] = None


class RestoreMemoryReq(BaseModel):
    ids: List[str]


# ---------------------------------------------------------------------------
# Supersede ledger —— 软失效台账
#
# 记忆本体（向量库里的文本与 id）一律不动，只在本地记一张"谁被谁取代"的
# 小表。这样合并是可撤销的，也不需要在 mem0 的 metadata 上做写入（那条路
# 只为云端后端保留，本地版本改了会给未来升级埋坑）。
# ---------------------------------------------------------------------------
_SUPERSEDE_FILE = "mem0_supersede.json"
_SUPERSEDE_LOCK = threading.Lock()


def _supersede_path() -> Path:
    from matlens_constants import get_matlens_home

    return Path(get_matlens_home()) / _SUPERSEDE_FILE


def _load_supersede() -> Dict[str, Any]:
    path = _supersede_path()
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_supersede(data: Dict[str, Any]) -> None:
    path = _supersede_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _all_memories(provider: Any, page_size: int = 200) -> List[Dict[str, Any]]:
    """把全量记忆翻页拉齐（facet/去重扫描需要完整集合，不能只看一页）。"""
    lister = getattr(provider, "list_memories", None)
    if not callable(lister):
        return []
    rows: List[Dict[str, Any]] = []
    offset = 0
    for _ in range(50):  # 保护上限：1 万条
        try:
            data = lister(page_size=page_size, offset=offset)
        except TypeError:
            data = lister(page=1, page_size=page_size)
        if not isinstance(data, dict):
            break
        batch = [r for r in (data.get("results") or []) if isinstance(r, dict)]
        rows.extend(batch)
        if len(batch) < page_size or not data.get("has_more"):
            break
        offset += len(batch)
    return rows


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
def list_memories(
    q: str = Query("", description="检索词；留空则取代表性记忆集合"),
    top_k: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0, description="分页偏移量"),
    limit: int = Query(30, ge=1, le=200, description="单页条数"),
    include_superseded: bool = False,
) -> Dict[str, Any]:
    """列出/检索记忆。无 query 时用宽泛词拉取近期记忆集合。

    检索与浏览是两条不同的路径：
    - 带 ``q`` 时走语义检索（向量近邻），天然只返回最相关的一批。
    - 不带 ``q`` 时走全量列举（``mem0_list``），可以翻页看到第 51 条之后
      的内容——这是旧的 top_k 截断永远做不到的。

    已被合并的条目默认不出现在列表与检索结果里，但记忆本体仍在库里，
    只有显式传 ``include_superseded=true`` 才能看到（前端"已合并"视图用）。
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
        if not include_superseded:
            ledger = _load_supersede()
            results = [r for r in results if str(r.get("id") or "") not in ledger]
        window = results[offset:offset + limit]
        items = _mark_superseded([_normalize(r) for r in window])
        has_more = len(results) > offset + limit
        return {
            "ok": True, "count": len(items), "total": len(results),
            "query": query, "memories": items,
            "offset": offset, "limit": limit, "has_more": has_more,
            "mode": "search",
        }

    # 全量浏览：拉齐全量 → 按软失效台账过滤 → 再切片。
    #
    # 为什么不把 offset 直接下传给后端分页：一旦有条目被合并，后端的
    # total/分页就还在数"已经看不见的"那些，列表条数不变、第 N 页凭空
    # 少几条。先在本地过滤再切片，total 与 has_more 才反映用户实际
    # 能看到的条数。规模有上限保护（见 _all_memories）。
    lister = getattr(provider, "list_memories", None)
    ledger = _load_supersede()
    if not callable(lister):
        # 后端不支持列举 —— 退化为宽搜抽样（总数不可信，仅供前端显示）。
        res = _call("mem0_search", {
            "query": "材料 科研 实验 用户 结论 方向 参数",
            "top_k": min(max(limit, top_k) + 1, 200),
        })
        results = res.get("results", []) if isinstance(res, dict) else []
        if not include_superseded:
            results = [r for r in results if str(r.get("id") or "") not in ledger]
        window = results[offset:offset + limit]
        items = _mark_superseded([_normalize(r) for r in window])
        return {
            "ok": True, "count": len(items), "total": len(results),
            "query": "", "memories": items,
            "offset": offset, "limit": limit,
            "has_more": len(results) > offset + limit, "mode": "browse",
        }

    rows_all = _all_memories(provider)
    if not include_superseded:
        rows_all = [r for r in rows_all if str(r.get("id") or "") not in ledger]
    total = len(rows_all)
    window = rows_all[offset:offset + limit]
    items = _mark_superseded([_normalize(r) for r in window])
    return {
        "ok": True, "count": len(items),
        "total": total,
        "query": "", "memories": items,
        "offset": offset, "limit": limit,
        "has_more": offset + len(items) < total, "mode": "browse",
    }


def add_memory(req: AddMemoryReq) -> Dict[str, Any]:
    """新增一条记忆（无 LLM 抽取，原样存储）。"""
    # 总开关关闭：明确拒绝手动写入，返回 ok:false（不抛 503）。
    if not bool(_memory_settings().get("enabled", True)):
        return {"ok": False, "error": "记忆已关闭"}
    content = (req.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content 不能为空")
    payload: Dict[str, Any] = {"content": content}
    # 只透传调用方真正给了的字段，缺省时由 provider 端决定不写 metadata。
    if req.source_type:
        payload["source_type"] = req.source_type
    if req.source_ref:
        payload["source_ref"] = req.source_ref
    if isinstance(req.confidence, (int, float)):
        payload["confidence"] = float(req.confidence)
    res = _call("mem0_add", payload)
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


def memory_facet(include_superseded: bool = Query(False)) -> Dict[str, Any]:
    """全库分类/来源聚合，外加重复簇统计。

    前端此前只能"拉一页再自己数"，第 61 条之后的分类计数永远是错的。
    这里做后端聚合：一次把全量拉齐，返回真实占比，与分页无关。
    """
    provider = _get_provider()
    if not _backend_ready(provider):
        return {"ok": True, "available": False, "total": 0, "categories": []}
    rows = _all_memories(provider)
    superseded = _load_supersede()
    visible = (
        rows
        if include_superseded
        else [r for r in rows if str(r.get("id") or "") not in superseded]
    )

    counts: Dict[str, int] = {}
    sources: Dict[str, int] = {}
    missing_source = 0
    for row in visible:
        text = str(row.get("memory") or row.get("text") or "")
        cat = _categorize(text)
        counts[cat] = counts.get(cat, 0) + 1
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        src = meta.get("source_type")
        if src:
            sources[str(src)] = sources.get(str(src), 0) + 1
        else:
            missing_source += 1

    total = len(visible)
    categories = [
        {
            "name": name,
            "count": counts.get(name, 0),
            "pct": round(counts.get(name, 0) / total * 100, 1) if total else 0.0,
        }
        for name in CATEGORY_ORDER
    ]
    groups = _dedup_groups(visible)
    return {
        "ok": True,
        "available": True,
        "total": total,
        "superseded_count": len(rows) - len(visible),
        "categories": categories,
        "sources": [
            {"name": k, "count": v}
            for k, v in sorted(sources.items(), key=lambda kv: -kv[1])
        ],
        "missing_source": missing_source,
        "dup_groups": len(groups),
        "dup_items": sum(len(g["ids"]) for g in groups),
    }


def _dedup_groups(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from plugins.memory.mem0 import _dedup

    # 报告里要给人看得懂的簇：带上文本与分类，前端才能直接渲染"保留哪条"。
    items = []
    for row in rows:
        text = str(row.get("memory") or row.get("text") or "")
        items.append({"id": str(row.get("id") or ""), "memory": text})
    groups = _dedup.group_duplicates(items)
    out = []
    for g in groups:
        out.append(
            {
                "ids": g["ids"],
                "score": round(g["score"], 3),
                "items": [
                    {**it, "category": _categorize(it["memory"])} for it in g["items"]
                ],
            }
        )
    return out


def list_duplicates(threshold: float = Query(0.55, ge=0.3, le=0.95)) -> Dict[str, Any]:
    """疑似重复清单——合并操作的数据来源。

    判定在后端做（``plugins/memory/mem0/_dedup.py``），前端不再自己实现一份
    阈值，避免两套逻辑漂移。
    """
    provider = _get_provider()
    if not _backend_ready(provider):
        return {"ok": True, "available": False, "groups": [], "count": 0}
    rows = _all_memories(provider)
    superseded = _load_supersede()
    visible = [r for r in rows if str(r.get("id") or "") not in superseded]

    from plugins.memory.mem0 import _dedup

    items = [
        {"id": str(r.get("id") or ""), "memory": str(r.get("memory") or r.get("text") or "")}
        for r in visible
    ]
    groups = _dedup.group_duplicates(items, threshold=threshold)
    out = [
        {
            "ids": g["ids"],
            "score": round(g["score"], 3),
            "items": [
                {**it, "category": _categorize(it["memory"])} for it in g["items"]
            ],
        }
        for g in groups
    ]
    return {
        "ok": True,
        "available": True,
        "groups": out,
        "count": len(out),
        "items": sum(len(g["ids"]) for g in out),
        "threshold": threshold,
    }


def merge_memories(req: MergeMemoryReq) -> Dict[str, Any]:
    """合并一组近重复记忆。

    默认走软失效（supersede）：保留 ``keep``，其余记进台账，列表与检索都
    不再展示，但随时可以 ``/restore`` 撤销。物理删除必须显式
    ``mode="delete"``——合并点错一次不该是不可挽回的事故。
    """
    keep = (req.keep or "").strip()
    ids = [i.strip() for i in (req.ids or []) if i and i.strip()]
    if not keep or keep not in ids:
        raise HTTPException(status_code=400, detail="keep 必须是 ids 中的一条")
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="至少要两条才能合并")
    if req.mode not in ("supersede", "delete"):
        raise HTTPException(status_code=400, detail="mode 只能是 supersede 或 delete")

    merged_text = (req.merged_text or "").strip()
    if merged_text:
        _call("mem0_update", {"memory_id": keep, "text": merged_text})

    survivors = [i for i in ids if i != keep]
    if req.mode == "delete":
        for mid in survivors:
            try:
                _call("mem0_delete", {"memory_id": mid})
            except Exception:
                continue
        with _SUPERSEDE_LOCK:
            ledger = _load_supersede()
            for mid in survivors:
                ledger.pop(mid, None)
            _save_supersede(ledger)
        return {"ok": True, "mode": "delete", "keep": keep, "removed": survivors}

    with _SUPERSEDE_LOCK:
        ledger = _load_supersede()
        stamp = _now_iso()
        for mid in survivors:
            ledger[mid] = {"keep_id": keep, "at": stamp}
        _save_supersede(ledger)
    return {"ok": True, "mode": "supersede", "keep": keep, "superseded": survivors}


def restore_memories(req: RestoreMemoryReq) -> Dict[str, Any]:
    """撤销软失效：把被合并掉的条目重新放回列表。"""
    ids = [i.strip() for i in (req.ids or []) if i and i.strip()]
    with _SUPERSEDE_LOCK:
        ledger = _load_supersede()
        restored = [mid for mid in ids if mid in ledger]
        for mid in restored:
            ledger.pop(mid, None)
        if restored:
            _save_supersede(ledger)
    return {"ok": True, "restored": restored, "count": len(restored)}


def list_superseded() -> Dict[str, Any]:
    """列出当前处于失效态的条目（供"已合并"视图与撤销按钮）。"""
    ledger = _load_supersede()
    return {
        "ok": True,
        "items": [
            {"id": mid, "keep_id": v.get("keep_id"), "at": v.get("at")}
            for mid, v in ledger.items()
            if isinstance(v, dict)
        ],
        "count": len(ledger),
    }


def _now_iso() -> str:
    import datetime

    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


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
    router.add_api_route("/facet", memory_facet, methods=["GET"], name="memory_facet")
    router.add_api_route(
        "/duplicates", list_duplicates, methods=["GET"], name="memory_duplicates"
    )
    router.add_api_route(
        "/merge", merge_memories, methods=["POST"], name="memory_merge"
    )
    router.add_api_route(
        "/restore", restore_memories, methods=["POST"], name="memory_restore"
    )
    router.add_api_route(
        "/superseded", list_superseded, methods=["GET"], name="memory_superseded"
    )
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
