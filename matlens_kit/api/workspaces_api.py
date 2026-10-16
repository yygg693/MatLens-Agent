# -*- coding: utf-8 -*-
"""MatLens Web 服务层 —— 工作区 API。

「工作区」= 用户选定的一个本地文件夹，Agent 的文件读写与终端默认以它为根。
这是 MatLens 与普通聊天工具的核心差异：科研场景里 Agent 必须落到真实目录
（实验数据、文献 PDF、脚本），而不是只存在于对话里。

为什么单独一个模块而不是塞进 sessions_api：
  工作区有**独立生命周期**——用户可能在没有任何会话时就先选好目录，
  也可能在删掉工作区后仍保留会话记录。两者不是父子关系。

持久化用独立 JSON（~/.matlens/workspaces.json）而不是 SQLite：
  工作区条目极小（路径 + 名称），无跨表查询需求，且需要在 agent 未初始化
  时就能读到。

安全约束：
  - 路径一律服务端用 os.path.abspath + normpath 规范化，拒绝相对路径
  - 删除工作区**只删索引条目，绝不动磁盘目录**——用户目录里的论文数据
    不该被一个 UI 按钮删掉
  - 复用路径做主键，防止重复添加
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

_router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])

_STORE_DIR = os.path.join(os.path.expanduser("~"), ".matlens")
_STORE_PATH = os.path.join(_STORE_DIR, "workspaces.json")


class WorkspaceCreateReq(BaseModel):
    path: str


class WorkspaceRenameReq(BaseModel):
    name: str


# ---------------------------------------------------------------------------
# 存储
# ---------------------------------------------------------------------------
def _load() -> Dict[str, Any]:
    """读工作区索引。任何异常都退化为空结构——工作区丢失不该让服务起不来。"""
    try:
        with open(_STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return data
        return {"items": []}
    except (OSError, ValueError):
        return {"items": []}


def _save(data: Dict[str, Any]) -> None:
    os.makedirs(_STORE_DIR, exist_ok=True)
    tmp = _STORE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _STORE_PATH)  # 原子替换，避免写一半崩溃留下坏 JSON


def _norm_path(p: str) -> str:
    """规范化路径。相对路径 reject——工作区必须是明确的绝对路径。"""
    raw = (p or "").strip().strip('"').strip("'")
    if not raw:
        raise HTTPException(status_code=400, detail="path 不能为空")
    # 展开 ~ 与环境变量，再绝对化
    expanded = os.path.abspath(os.path.expandvars(os.path.expanduser(raw)))
    # Windows 上统一用反斜杠，避免同一目录出现两条记录
    return os.path.normpath(expanded)


def _enrich(item: Dict[str, Any]) -> Dict[str, Any]:
    """补上磁盘实况（是否存在 / 是否 git 仓库），前端据此显示状态。"""
    p = item.get("path") or ""
    exists = os.path.isdir(p)
    is_git = exists and os.path.isdir(os.path.join(p, ".git"))
    return {
        **item,
        "exists": exists,
        "is_git": is_git,
        "name": item.get("name") or os.path.basename(p.rstrip("\\/")) or p,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@_router.get("")
def list_workspaces() -> Dict[str, Any]:
    """列出全部工作区（最近使用在前）。"""
    data = _load()
    items = [_enrich(it) for it in data["items"]]
    items.sort(key=lambda x: x.get("last_used") or 0, reverse=True)
    return {"ok": True, "workspaces": items, "count": len(items), "current": data.get("current")}


@_router.post("")
def add_workspace(req: WorkspaceCreateReq) -> Dict[str, Any]:
    """新增工作区。路径已存在则直接激活（幂等）。"""
    p = _norm_path(req.path)
    if not os.path.isdir(p):
        raise HTTPException(status_code=400, detail=f"目录不存在：{p}")

    data = _load()
    items = data["items"]
    for it in items:
        if os.path.normcase(it.get("path", "")) == os.path.normcase(p):
            it["last_used"] = time.time()
            data["current"] = it["id"]
            _save(data)
            return {"ok": True, "workspace": _enrich(it), "exists": True}

    item = {
        "id": uuid.uuid4().hex[:12],
        "path": p,
        "name": os.path.basename(p.rstrip("\\/")) or p,
        "created_at": time.time(),
        "last_used": time.time(),
    }
    items.append(item)
    data["current"] = item["id"]
    _save(data)
    return {"ok": True, "workspace": _enrich(item), "exists": False}


@_router.post("/{ws_id}/activate")
def activate_workspace(ws_id: str) -> Dict[str, Any]:
    """切换当前工作区。"""
    data = _load()
    for it in data["items"]:
        if it.get("id") == ws_id:
            it["last_used"] = time.time()
            data["current"] = ws_id
            _save(data)
            return {"ok": True, "workspace": _enrich(it)}
    raise HTTPException(status_code=404, detail="工作区不存在")


@_router.put("/{ws_id}")
def rename_workspace(ws_id: str, req: WorkspaceRenameReq) -> Dict[str, Any]:
    """重命名工作区显示名（不影响磁盘路径）。"""
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name 不能为空")
    data = _load()
    for it in data["items"]:
        if it.get("id") == ws_id:
            it["name"] = name[:60]
            _save(data)
            return {"ok": True, "workspace": _enrich(it)}
    raise HTTPException(status_code=404, detail="工作区不存在")


@_router.delete("/{ws_id}")
def remove_workspace(ws_id: str) -> Dict[str, Any]:
    """移除工作区条目。

    **只删索引，不动磁盘目录**——用户目录里的论文数据不该被一个 UI 按钮删掉。
    """
    data = _load()
    items = data["items"]
    hit = next((it for it in items if it.get("id") == ws_id), None)
    if hit is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    items.remove(hit)
    if data.get("current") == ws_id:
        data["current"] = items[0]["id"] if items else None
    _save(data)
    return {"ok": True, "id": ws_id, "path_kept_on_disk": hit.get("path")}
