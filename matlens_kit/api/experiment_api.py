# -*- coding: utf-8 -*-
"""实验工作流 API —— 复用 matlens_kit/tools/experiment.py 现成工具。

- POST   /api/experiment/generate  {goal, template} → 实验方案（模板化生成，同步快）
- POST   /api/experiment/record    {title, protocol, note} → 保存实验记录
- GET    /api/experiments          历史实验记录列表
- GET    /api/experiments/{id}     单条详情
- DELETE /api/experiments/{id}     删除记录
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

_router = APIRouter(prefix="/api/experiment", tags=["experiment"])

_EXP_DB = os.path.expanduser("~/.matlens/experiments.db")


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_EXP_DB, timeout=15)
    c.row_factory = sqlite3.Row
    return c


def _init() -> None:
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS experiments (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                protocol TEXT NOT NULL,
                note TEXT DEFAULT '',
                template TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class GenerateReq(BaseModel):
    goal: str
    # 未显式传（或为空）时，实时取 settings experiment.template；显式传入优先。
    template: Optional[str] = None


class RecordReq(BaseModel):
    title: str
    protocol: str
    note: str = ""
    template: str = ""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@_router.get("/templates")
def list_templates() -> Dict[str, Any]:
    """可用实验模板列表（前端模板卡片渲染）。"""
    from matlens_kit.tools.experiment import EXPERIMENT_TEMPLATES
    return {"ok": True, "templates": [
        {"key": k, "name": v["name"], "applicable": v["applicable"]}
        for k, v in EXPERIMENT_TEMPLATES.items()
    ]}


@_router.post("/generate")
def generate_protocol(req: GenerateReq) -> Dict[str, Any]:
    """按模板生成实验方案（复用 experiment_protocol_tool）。

    template 未显式给（或为空）时，默认用 settings experiment.template；
    显式传入仍优先。
    """
    goal = (req.goal or "").strip()
    if not goal:
        raise HTTPException(status_code=400, detail="goal 必填（研究目标）")
    from matlens_kit.tools.experiment import experiment_protocol_tool, _resolve_template

    tpl = (req.template or "").strip()
    if not tpl:
        # 动作时刻实时读设置默认模板
        try:
            from matlens_kit import settings_store
            tpl = settings_store.get_section("experiment").get("template", "standard")
        except Exception:  # noqa: BLE001
            tpl = "standard"
    tpl = _resolve_template(tpl)

    res = experiment_protocol_tool(goal, tpl)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return {"ok": True, **res}


@_router.post("/record")
def save_record(req: RecordReq) -> Dict[str, Any]:
    """保存实验记录（方案 + 备注）。"""
    title = (req.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title 必填")
    _init()
    rid = uuid.uuid4().hex
    with _conn() as c:
        c.execute(
            "INSERT INTO experiments (id, title, protocol, note, template, created_at) VALUES (?,?,?,?,?,?)",
            (rid, title, req.protocol, req.note, req.template, _now()),
        )
    return {"ok": True, "id": rid, "title": title}


@_router.get("/list")
def list_records() -> Dict[str, Any]:
    """历史实验记录列表（按时间倒序）。"""
    _init()
    with _conn() as c:
        rows = c.execute("SELECT * FROM experiments ORDER BY created_at DESC LIMIT 100").fetchall()
    return {"ok": True, "count": len(rows), "records": [
        {"id": r["id"], "title": r["title"], "note": r["note"], "template": r["template"],
         "created_at": r["created_at"], "protocol_len": len(r["protocol"])}
        for r in rows
    ]}


@_router.get("/records/{rid}")
def get_record(rid: str) -> Dict[str, Any]:
    _init()
    with _conn() as c:
        row = c.execute("SELECT * FROM experiments WHERE id=?", (rid,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="实验记录不存在")
    return {"ok": True, "id": row["id"], "title": row["title"], "protocol": row["protocol"],
            "note": row["note"], "template": row["template"], "created_at": row["created_at"]}


@_router.delete("/records/{rid}")
def delete_record(rid: str) -> Dict[str, Any]:
    _init()
    with _conn() as c:
        cur = c.execute("DELETE FROM experiments WHERE id=?", (rid,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="实验记录不存在")
    return {"ok": True, "deleted": rid}
