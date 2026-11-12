"""记忆图谱 API —— 从 matlens 统一后端的记忆抽取实体/关系，供前端 vis-network 渲染。

数据流（见 design/backend-api.md 第四节）：
  Mem0 记忆（带 [用户]/[实验]/[材料]/[结论] 标签）
    → DeepSeek 抽实体/关系（复用 matlens 的 DEEPSEEK_API_KEY）
    → ~/.matlens/graph.json（增量合并）
    → 前端 vis-network 蜘蛛网

后端不可用时（qdrant 异常）优雅降级：返回节点（无边的启发式图）而非崩溃。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

_router = APIRouter(prefix="/api/graph", tags=["graph"])

_GRAPH_PATH = Path(os.path.expanduser("~/.matlens/graph.json"))
_graph_lock = threading.Lock()
_CAT_RE = re.compile(r"^\s*\[([^\]]+)\]\s*")

# 类别 → 颜色（前端 vis-network 用）
# 任务约定：材料=蓝、方法=绿、性质=橙、参数=灰；其余类别保留旧色。
CATEGORY_COLORS = {
    "材料": "#38bdf8",   # sky blue
    "方法": "#22c55e",   # green
    "性质": "#f97316",   # orange
    "参数": "#9ca3af",   # gray
    "用户": "#6366f1",   # indigo
    "实验": "#2dd4bf",   # teal
    "结论": "#f59e0b",   # amber
    "其他": "#94a3b8",   # slate
}

_DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
_DEEPSEEK_MODEL = "deepseek-chat"


def _get_deepseek_key() -> str:
    """解析 DEEPSEEK_API_KEY：优先 secret scope / 进程环境，缺省回落到 ~/.matlens/.env。"""
    try:
        from agent.secret_scope import get_secret

        key = get_secret("DEEPSEEK_API_KEY", "") or ""
    except Exception:
        key = ""
    if key:
        return key
    # 回落到 .env 文件（独立脚本/测试场景）
    try:
        from agent.secret_scope import load_env_file

        env_path = Path(os.path.expanduser("~/.matlens/.env"))
        return load_env_file(env_path).get("DEEPSEEK_API_KEY", "")
    except Exception:
        return os.environ.get("DEEPSEEK_API_KEY", "")


def _graph_auto_build_enabled() -> bool:
    """实时读取 memory.graph_auto_build 开关（settings_store 不缓存）。读取失败默认 True。"""
    try:
        from matlens_kit import settings_store

        return bool(settings_store.get_section("memory").get("graph_auto_build", True))
    except Exception:
        return True


def _graph_cache() -> Dict[str, Any]:
    if _GRAPH_PATH.exists():
        try:
            return json.loads(_GRAPH_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"nodes": [], "edges": []}


def _save_cache(g: Dict[str, Any]) -> None:
    _GRAPH_PATH.parent.mkdir(parents=True, exist_ok=True)
    _GRAPH_PATH.write_text(json.dumps(g, ensure_ascii=False, indent=2), encoding="utf-8")


def _fetch_memories(top_k: int = 200) -> List[Dict[str, Any]]:
    """从统一后端取记忆集合（复用 mem_api 的 provider 访问）。

    优先全量分页枚举。旧实现用一次语义检索取 top_k，那只是"最相关的一批"，
    不是全部记忆——图谱因此永远看不见库里的另一半，实体覆盖和边都会缺一块。
    后端不支持枚举时（抛 NotImplementedError）才回落到检索。
    """
    try:
        from matlens_kit.api.mem_api import _categorize, _get_provider

        provider = _get_provider()
        if provider is None or getattr(provider, "_backend", None) is None:
            return []

        results: List[Dict[str, Any]] = []
        lister = getattr(provider, "list_memories", None)
        if callable(lister):
            offset = 0
            while True:
                data = lister(page=1, page_size=200, offset=offset)
                if not isinstance(data, dict):
                    break
                rows = data.get("results") or []
                for r in rows:
                    mem = r.get("memory") or r.get("text") or ""
                    if mem:
                        results.append({
                            "id": r.get("id"),
                            "memory": mem,
                            "category": _categorize(mem),
                        })
                if not rows or not data.get("has_more"):
                    break
                offset += len(rows)
                if offset > 2000:
                    break
        if results:
            return results

        raw = provider.handle_tool_call(
            "mem0_search",
            {"query": "材料 科研 实验 用户 结论 方向 参数 偏好", "top_k": top_k},
        )
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = {}
        for r in (raw.get("results", []) if isinstance(raw, dict) else []):
            mem = r.get("memory") or r.get("text") or ""
            if mem:
                results.append({"id": r.get("id"), "memory": mem, "category": _categorize(mem)})
        return results
    except Exception:
        return []


def _llm_extract(memos: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """用 DeepSeek（OpenAI 兼容 client）从记忆文本抽取实体/关系（JSON）。失败返回 None。"""
    if not memos:
        return None

    key = _get_deepseek_key()
    if not key:
        return None
    try:
        from openai import OpenAI
    except Exception:
        return None

    lines = []
    for m in memos:
        lines.append(f"[{m['category']}] {m['memory']}")
    corpus = "\n".join(lines)

    sys_prompt = (
        "你是材料科研知识图谱抽取器。从给定记忆中抽取实体与关系，输出严格 JSON：\n"
        '{"nodes":[{"id":"唯一id","label":"实体名","category":"材料|方法|性质|参数|用户|实验|结论|其他"}],'
        '"edges":[{"source":"节点id","target":"节点id","label":"关系"}]}\n'
        "规则：节点去重；实体优先归为四类——材料(物质/组分/体系)、方法(合成/表征/测试手段)、"
        "性质(性能/现象/规律)、参数(数值/条件/配比)；边表示'属于/用于/导致/偏好/得出/测试'等科研关系；"
        "id 用英文短词或数字，保持引用一致；只输出 JSON，不要多余文字。"
    )
    user_prompt = f"记忆列表：\n{corpus}\n\n请输出图谱 JSON。"

    try:
        client = OpenAI(base_url=_DEEPSEEK_BASE_URL, api_key=key, timeout=60)
        resp = client.chat.completions.create(
            model=_DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content
        data = json.loads(content)
        if isinstance(data, dict) and "nodes" in data:
            return data
    except Exception:
        return None
    return None


def _heuristic_graph(memos: List[Dict[str, Any]]) -> Dict[str, Any]:
    """LLM 不可用时的启发式降级：记忆即节点，同类别聚簇相连。"""
    nodes = []
    for m in memos:
        nodes.append({
            "id": m["id"] or f"m{len(nodes)}",
            "label": (m["memory"][:40] + "…") if len(m["memory"]) > 40 else m["memory"],
            "category": m["category"],
        })
    # 同类别节点成链（仅保证图非空、可见结构）
    edges = []
    by_cat: Dict[str, List[str]] = {}
    for n in nodes:
        by_cat.setdefault(n["category"], []).append(n["id"])
    for cat, ids in by_cat.items():
        for i in range(len(ids) - 1):
            edges.append({"id": f"e{len(edges)}", "source": ids[i], "target": ids[i + 1], "label": cat})
    return {"nodes": nodes, "edges": edges, "fallback": True}


GRAPH_BATCH_SIZE = 45


def _merge_graph_parts(parts: List[Any]) -> Dict[str, Any]:
    """把分批抽取的结果合并成一张图。

    每批独立送给模型，模型自己编的 id 在不同批之间并不互相指向，所以不能直接
    把各批的 nodes/edges 拼起来——那样会出现"t1 在这批指 A、在那批指 B"的错连。
    处理办法：节点按 label 归一去重并重新分配稳定 id，每批的原始 id 先映射到
    规范 id，再让边按映射落地；最后按 (source, target, label) 去重。
    """
    nodes: List[Dict[str, Any]] = []
    by_label: Dict[str, str] = {}
    id_maps: List[Dict[str, str]] = []

    for part in parts:
        local: Dict[str, str] = {}
        if isinstance(part, dict):
            for n in part.get("nodes") or []:
                if not isinstance(n, dict):
                    continue
                label = str(n.get("label") or "").strip()
                if not label:
                    continue
                key = label.casefold()
                nid = by_label.get(key)
                if nid is None:
                    nid = "n%d" % len(nodes)
                    by_label[key] = nid
                    nodes.append({
                        "id": nid,
                        "label": label,
                        "category": n.get("category") or "其他",
                    })
                local[str(n.get("id") or "")] = nid
                local.setdefault(label, nid)
        id_maps.append(local)

    edges: List[Dict[str, Any]] = []
    seen = set()
    for idx, part in enumerate(parts):
        if not isinstance(part, dict):
            continue
        local = id_maps[idx]
        for e in part.get("edges") or []:
            if not isinstance(e, dict):
                continue
            src = local.get(str(e.get("source") or ""))
            dst = local.get(str(e.get("target") or ""))
            if not src or not dst or src == dst:
                continue
            rel = str(e.get("label") or "").strip()
            key = (src, dst, rel)
            if key in seen:
                continue
            seen.add(key)
            edges.append({"id": "e%d" % len(edges), "source": src, "target": dst, "label": rel})

    return {"nodes": nodes, "edges": edges}


def _build_graph(force: bool = False) -> Dict[str, Any]:
    memos = _fetch_memories()
    if not memos:
        return {"nodes": [], "edges": [], "empty": True, "message": "暂无记忆可供构图"}

    parts: List[Any] = []
    for start in range(0, len(memos), GRAPH_BATCH_SIZE):
        chunk = memos[start:start + GRAPH_BATCH_SIZE]
        data = _llm_extract(chunk)
        if data is None:
            data = _heuristic_graph(chunk)
        parts.append(data)

    data = _merge_graph_parts(parts)
    fell_back = bool(parts) and all(
        isinstance(p, dict) and p.get("fallback") for p in parts
    )

    # 着色 + 尺寸
    for n in data.get("nodes", []):
        n["color"] = CATEGORY_COLORS.get(n.get("category", "其他"), CATEGORY_COLORS["其他"])
        n.setdefault("val", 1)
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    data["built_ts"] = time.time()
    data["memory_count"] = len(memos)
    data["fallback"] = fell_back
    return data


def _current_memory_total() -> Optional[int]:
    """当前记忆总量；后端不可用时返回 None（此时不做过期判断）。"""
    try:
        from matlens_kit.api.mem_api import _exact_count, _get_provider

        return _exact_count(_get_provider())
    except Exception:
        return None


_STALE_PROBE_INTERVAL = 300.0
_stale_probe = {"at": 0.0}


def _cache_is_stale(cached: Dict[str, Any]) -> bool:
    """缓存里的记忆条数和库里的对不上，说明缓存是旧快照，该重建了。

    探针本身要问后端，有代价，所以最多每 5 分钟查一次；拿不到总量时不判过期，
    宁可继续用旧图，也不因为一次探测失败把图清空。
    """
    recorded = cached.get("memory_count")
    if not isinstance(recorded, int):
        return False
    now = time.time()
    if now - _stale_probe["at"] < _STALE_PROBE_INTERVAL:
        return False
    _stale_probe["at"] = now
    total = _current_memory_total()
    if total is None:
        return False
    return total != recorded


_rebuild_state = {"running": False}


def _should_replace(previous: Optional[Dict[str, Any]],
                   candidate: Dict[str, Any]) -> bool:
    """新图能否覆盖旧图。

    抽取降级（LLM 不可用 → 启发式"记忆即节点"）时，产物在结构上是有损的：
    节点变成一句句记忆、边变成同类别的串链。用它覆盖已有的真图，等于把好图
    降级成垃圾，所以只允许在旧图本来就是降级图、或旧图空的时候替换。
    """
    if not candidate.get("nodes"):
        return False
    if candidate.get("fallback") and previous:
        if not previous.get("fallback"):
            return False
    return True


def _kick_rebuild(previous: Optional[Dict[str, Any]] = None) -> None:
    """后台重建图谱，不阻塞当前请求：先返回旧图，下一次请求拿到新图。"""
    if _rebuild_state["running"]:
        return
    _rebuild_state["running"] = True

    def _run() -> None:
        try:
            with _graph_lock:
                g = _build_graph(force=True)
                if not _should_replace(previous, g):
                    return
                _save_cache(g)
        except Exception:
            pass
        finally:
            _rebuild_state["running"] = False

    threading.Thread(target=_run, daemon=True, name="graph-rebuild").start()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@_router.get("")
def get_graph() -> Dict[str, Any]:
    """返回当前图谱。自动构建开启时：优先缓存，无缓存则即时从记忆构图。
    自动构建关闭时：只返回已有缓存（不重新构图），无缓存则返回空图并带
    auto_build:false 标记——绝不从不记忆触发启发式/LLM 构图。"""
    cached = _graph_cache()
    auto_build_on = _graph_auto_build_enabled()
    if cached.get("nodes"):
        cached.setdefault("fallback", False)
        cached["auto_build"] = auto_build_on
        # 缓存自查：记忆库长了但图还是旧快照时，后台重建，当前请求先返回旧图。
        if auto_build_on and _cache_is_stale(cached):
            _kick_rebuild(cached)
            cached["rebuilding"] = True
        return cached
    if not auto_build_on:
        return {
            "nodes": [],
            "edges": [],
            "empty": True,
            "message": "已关闭记忆图谱自动构建",
            "auto_build": False,
        }
    with _graph_lock:
        g = _build_graph()
        _save_cache(g)
        g["auto_build"] = True
        return g


@_router.post("/extract")
def extract_graph() -> Dict[str, Any]:
    """强制从当前记忆重新抽取图谱。自动构建关闭时拒绝重建，返回明确提示。"""
    if not _graph_auto_build_enabled():
        return {
            "nodes": [],
            "edges": [],
            "empty": True,
            "message": "已关闭记忆图谱自动构建",
            "auto_build": False,
        }
    previous = _graph_cache()
    with _graph_lock:
        g = _build_graph(force=True)
        # 手动触发同样要过这道门：抽取降级时返回结果，但不允许把好图覆盖掉。
        if not _should_replace(previous, g):
            g["skipped"] = True
            g["message"] = "本次抽取降级为启发式结果，已保留原有图谱未覆盖"
            g.setdefault("auto_build", True)
            return g
        _save_cache(g)
        g.setdefault("auto_build", True)
        return g
