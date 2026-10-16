# -*- coding: utf-8 -*-
"""论文工坊 · 数据层（papers.db SQLite）。

表结构：
- papers: id / title / paper_type / topic / stages_json / created_at / updated_at
  stages_json = {stage: {status, content, refs, error, updated_at}}

设计要点（继承老项目 mra 原则）：
- 每阶段独立可重跑：产物全量落库 stages_json，失败单独重跑、断点续写
- 连接模式：每次新开连接（复用 M1 会话读隔离教训——不缓存长连接）
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

_PAPER_DB = os.path.expanduser("~/.matlens/papers.db")


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    c = sqlite3.connect(db_path or _PAPER_DB, timeout=15)
    c.row_factory = sqlite3.Row
    return c


def _init(db_path: Optional[str] = None) -> None:
    with _conn(db_path) as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS papers (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                paper_type TEXT NOT NULL DEFAULT 'research',
                topic TEXT DEFAULT '',
                stages_json TEXT NOT NULL DEFAULT '{}',
                experimental_data TEXT DEFAULT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_papers_updated ON papers(updated_at)")
        # 幂等迁移：已存在的老库（~/.matlens/papers.db）没有 experimental_data 列。
        # SQLite 不支持 ADD COLUMN IF NOT EXISTS，用 PRAGMA table_info 检查再 ALTER。
        cols = {r[1] for r in c.execute("PRAGMA table_info(papers)").fetchall()}
        if "experimental_data" not in cols:
            c.execute("ALTER TABLE papers ADD COLUMN experimental_data TEXT")


def _stages_default() -> Dict[str, Any]:
    """初始化 7 步状态（全部 pending）。"""
    return {
        stage: {"status": "pending", "content": "", "refs": [], "error": ""}
        for stage in ("topic", "search", "outline", "write", "quality", "review", "export")
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
def create_paper(
    title: str,
    paper_type: str = "research",
    topic: str = "",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    _init(db_path)
    pid = uuid.uuid4().hex
    now = _now()
    with _conn(db_path) as c:
        c.execute(
            "INSERT INTO papers (id, title, paper_type, topic, stages_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (pid, title, paper_type, topic, json.dumps(_stages_default(), ensure_ascii=False), now, now),
        )
    return get_paper(pid, db_path=db_path) or {}


def get_paper(pid: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    _init(db_path)
    with _conn(db_path) as c:
        row = c.execute("SELECT * FROM papers WHERE id=?", (pid,)).fetchone()
    if row is None:
        return None
    return _row_to_paper(row)


def list_papers(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    _init(db_path)
    with _conn(db_path) as c:
        rows = c.execute("SELECT * FROM papers ORDER BY updated_at DESC").fetchall()
    return [_row_to_paper(r) for r in rows]


def _parse_experimental_data(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    """解析 experimental_data JSON；NULL/损坏 → None（前端按未录入处理）。"""
    if not raw:
        return None
    try:
        v = json.loads(raw)
    except Exception:
        return None
    return v if isinstance(v, dict) else None


def _row_to_paper(row: sqlite3.Row) -> Dict[str, Any]:
    stages = json.loads(row["stages_json"] or "{}")
    # 进度：done 数 / 总数
    done = sum(1 for s in stages.values() if s.get("status") == "done")
    raw_data = row["experimental_data"] if "experimental_data" in row.keys() else None
    return {
        "id": row["id"],
        "title": row["title"],
        "paper_type": row["paper_type"],
        "topic": row["topic"],
        "stages": stages,
        "progress": {"done": done, "total": len(stages), "pct": round(done * 100 / max(len(stages), 1))},
        "data": _parse_experimental_data(raw_data),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def delete_paper(pid: str, db_path: Optional[str] = None) -> bool:
    _init(db_path)
    with _conn(db_path) as c:
        cur = c.execute("DELETE FROM papers WHERE id=?", (pid,))
        return cur.rowcount > 0


def update_meta(pid: str, title: Optional[str] = None, topic: Optional[str] = None, db_path: Optional[str] = None) -> bool:
    _init(db_path)
    fields, vals = [], []
    if title is not None:
        fields.append("title=?"); vals.append(title)
    if topic is not None:
        fields.append("topic=?"); vals.append(topic)
    if not fields:
        return False
    fields.append("updated_at=?")
    vals.append(_now())
    vals.append(pid)
    with _conn(db_path) as c:
        cur = c.execute(f"UPDATE papers SET {', '.join(fields)} WHERE id=?", vals)
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# 实验数据（学术诚信：proposed 拟议 / measured 实测，禁止 AI 编造冒充）
# ---------------------------------------------------------------------------
def save_paper_data(pid: str, data: Dict[str, Any], db_path: Optional[str] = None) -> Dict[str, Any]:
    """保存论文实验数据（JSON），同时更新行 updated_at 与 data.updated_at。

    data schema: {"status": "proposed"|"measured", "notes": str,
                  "tables": [...], "updated_at": "YYYY-MM-DD HH:MM:SS"}
    返回落库后解析出的 data dict。论文不存在抛 KeyError（API 层转 404）。
    """
    _init(db_path)
    if not isinstance(data, dict):
        raise TypeError("data 必须是 dict")
    data = dict(data)
    # 服务端权威时间戳（前端传入的不可信）
    data["updated_at"] = _now()
    with _conn(db_path) as c:
        cur = c.execute(
            "UPDATE papers SET experimental_data=?, updated_at=? WHERE id=?",
            (json.dumps(data, ensure_ascii=False), _now(), pid),
        )
        if cur.rowcount == 0:
            raise KeyError(f"论文项目不存在：{pid}")
    got = get_paper(pid, db_path=db_path)
    return (got or {}).get("data") or {}


# ---------------------------------------------------------------------------
# 阶段操作（stages_json 局部更新）
# ---------------------------------------------------------------------------
def _load_stages(pid: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    with _conn(db_path) as c:
        row = c.execute("SELECT stages_json FROM papers WHERE id=?", (pid,)).fetchone()
    if row is None:
        raise KeyError(f"论文项目不存在：{pid}")
    return json.loads(row["stages_json"] or "{}")


def _save_stages(pid: str, stages: Dict[str, Any], db_path: Optional[str] = None) -> None:
    with _conn(db_path) as c:
        c.execute(
            "UPDATE papers SET stages_json=?, updated_at=? WHERE id=?",
            (json.dumps(stages, ensure_ascii=False), _now(), pid),
        )


def set_stage_status(pid: str, stage: str, status: str, error: str = "", db_path: Optional[str] = None) -> Dict[str, Any]:
    """更新单步状态（pending/running/done/error）。"""
    stages = _load_stages(pid, db_path)
    s = stages.setdefault(stage, {"status": "pending", "content": "", "refs": [], "error": ""})
    s["status"] = status
    if error:
        s["error"] = error
    _save_stages(pid, stages, db_path)
    return stages[stage]


def save_stage_content(pid: str, stage: str, content: str, refs: Optional[List[Any]] = None, db_path: Optional[str] = None) -> Dict[str, Any]:
    """保存某步产物（content + refs），用于断点续写。"""
    stages = _load_stages(pid, db_path)
    s = stages.setdefault(stage, {"status": "pending", "content": "", "refs": [], "error": ""})
    if content:
        s["content"] = content
    if refs is not None:
        s["refs"] = refs
    s["updated_at"] = _now()
    _save_stages(pid, stages, db_path)
    return s


def recover_stuck_running(db_path: Optional[str] = None) -> int:
    """崩溃恢复：把所有 running 状态的步骤重置为 pending。

    服务进程崩溃/被杀时，生成线程消失但 DB 里步骤停在 running，
    会导致该步骤永远无法重跑。服务启动时调用本函数。
    """
    _init(db_path)
    recovered = 0
    with _conn(db_path) as c:
        rows = c.execute("SELECT id, stages_json FROM papers").fetchall()
        for row in rows:
            stages = json.loads(row["stages_json"] or "{}")
            changed = False
            for s in stages.values():
                if isinstance(s, dict) and s.get("status") == "running":
                    s["status"] = "pending"
                    s["error"] = "生成中断（服务重启），已重置待重跑"
                    changed = True
                    recovered += 1
            if changed:
                c.execute(
                    "UPDATE papers SET stages_json=? WHERE id=?",
                    (json.dumps(stages, ensure_ascii=False), row["id"]),
                )
    return recovered
