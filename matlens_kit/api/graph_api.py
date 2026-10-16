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


def _fetch_memories(top_k: int = 60) -> List[Dict[str, Any]]:
    """从统一后端取记忆集合（复用 mem_api 的 provider 访问）。"""
    try:
        from matlens_kit.api.mem_api import _get_provider, _categorize

        provider = _get_provider()
        if provider is None or getattr(provider, "_backend", None) is None:
            return []
        raw = provider.handle_tool_call(
            "mem0_search",
            {"query": "材料 科研 实验 用户 结论 方向 参数 偏好", "top_k": top_k},
        )
        results = []
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = {}
        for r in (raw.get("results", []) if isinstance(raw, dict) else []):
            mem = r.get("memory") or r.get("text") or ""
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


def _build_graph(force: bool = False) -> Dict[str, Any]:
    memos = _fetch_memories()
    if not memos:
        return {"nodes": [], "edges": [], "empty": True, "message": "暂无记忆可供构图"}

    data = _llm_extract(memos)
    if data is None:
        data = _heuristic_graph(memos)

    # 着色 + 尺寸
    for n in data.get("nodes", []):
        n["color"] = CATEGORY_COLORS.get(n.get("category", "其他"), CATEGORY_COLORS["其他"])
        n.setdefault("val", 1)
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    data["memory_count"] = len(memos)
    if "fallback" not in data:
        data["fallback"] = False
    return data


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
    with _graph_lock:
        g = _build_graph(force=True)
        _save_cache(g)
        g.setdefault("auto_build", True)
        return g
