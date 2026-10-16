# -*- coding: utf-8 -*-
"""论文实验数据（experimental_data）存储 + API 测试。

学术诚信要求：论文要么用真实实验数据（measured），要么用拟议值并明确标注
（proposed），绝不能让 AI 编造数据冒充真实实验。本测试覆盖：

DB 层（全部走临时 db_path，不碰真实 ~/.matlens/papers.db）：
- create_paper → save_paper_data → get_paper 读回 data；
- 老库迁移：手工建一个无 experimental_data 列的旧结构库，_init 幂等 ALTER 后
  能正常 get_paper / 存 data。

API 层（TestClient + monkeypatch PDB._PAPER_DB）：
- POST /api/papers/{pid}/data 保存并回显 data；
- GET  /api/papers/{pid} 全量返回 data；
- 404 处理。

注意：papers_api import prompts（并行开发中）。若 import 失败，本文件 API 段会
collect error——届时先跑 DB 段并如实说明，最终统一验证。
"""
from __future__ import annotations

import sqlite3

import pytest

from matlens_kit.paper import db as PDB


# ---------------------------------------------------------------------------
# DB 层
# ---------------------------------------------------------------------------
@pytest.fixture()
def db_path(tmp_path):
    return str(tmp_path / "paper_data.db")


def test_create_paper_data_default_is_none(db_path):
    p = PDB.create_paper("数据论文", topic="SOFC 电解质", db_path=db_path)
    # 新库 create 时 data 列为 NULL → 读出 None（前端按未录入处理）
    assert p.get("data") is None
    got = PDB.get_paper(p["id"], db_path=db_path)
    assert got.get("data") is None


def test_save_and_read_back_data(db_path):
    p = PDB.create_paper("存实验数据", db_path=db_path)
    pid = p["id"]
    payload = {
        "status": "measured",
        "notes": "2026-10-11 在 SOFC 实验室实测",
        "tables": [{"name": "Table 1", "caption": "电导率随温度", "rows": [[600, 0.012], [700, 0.035]]}],
    }
    saved = PDB.save_paper_data(pid, payload, db_path=db_path)
    assert saved["status"] == "measured"
    assert saved["notes"] == payload["notes"]
    assert len(saved["tables"]) == 1
    # 服务端盖时间戳
    assert saved.get("updated_at")

    got = PDB.get_paper(pid, db_path=db_path)
    assert got["data"]["status"] == "measured"
    assert got["data"]["tables"][0]["rows"][1] == [700, 0.035]


def test_overwrite_data(db_path):
    p = PDB.create_paper("覆盖数据", db_path=db_path)
    pid = p["id"]
    PDB.save_paper_data(pid, {"status": "proposed", "notes": "初始拟议", "tables": []}, db_path=db_path)
    PDB.save_paper_data(pid, {"status": "measured", "notes": "后补实测", "tables": []}, db_path=db_path)
    got = PDB.get_paper(pid, db_path=db_path)
    assert got["data"]["status"] == "measured"
    assert got["data"]["notes"] == "后补实测"


def test_migrate_old_db_without_column(db_path):
    """手工建一个无 experimental_data 列的旧库 → _init 幂等 ALTER → 正常读写。"""
    pid = "oldpid_legacy"
    with sqlite3.connect(db_path) as c:
        c.execute(
            """
            CREATE TABLE papers (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                paper_type TEXT NOT NULL DEFAULT 'research',
                topic TEXT DEFAULT '',
                stages_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        c.execute(
            "INSERT INTO papers (id,title,paper_type,topic,stages_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            (pid, "老库论文", "research", "旧主题", "{}", "2026-01-01 00:00:00", "2026-01-01 00:00:00"),
        )

    # _init 应幂等迁移（补列）
    PDB._init(db_path)
    with sqlite3.connect(db_path) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(papers)").fetchall()}
    assert "experimental_data" in cols

    # 老行 get_paper 不报错，data 为 None
    got = PDB.get_paper(pid, db_path=db_path)
    assert got is not None
    assert got["title"] == "老库论文"
    assert got.get("data") is None

    # 老库也能存 data
    PDB.save_paper_data(pid, {"status": "proposed", "notes": "补录拟议值", "tables": []}, db_path=db_path)
    got2 = PDB.get_paper(pid, db_path=db_path)
    assert got2["data"]["notes"] == "补录拟议值"

    # 再跑一次 _init 不重复 ALTER（幂等）
    PDB._init(db_path)
    with sqlite3.connect(db_path) as c:
        cols2 = [r[1] for r in c.execute("PRAGMA table_info(papers)").fetchall()]
    assert cols2.count("experimental_data") == 1


def test_corrupt_data_falls_back_to_none(db_path):
    """experimental_data 列存了坏 JSON → _row_to_paper 回退 None，不抛错。"""
    p = PDB.create_paper("坏数据", db_path=db_path)
    pid = p["id"]
    with sqlite3.connect(db_path) as c:
        c.execute("UPDATE papers SET experimental_data=? WHERE id=?", ("{{{not json", pid))
    got = PDB.get_paper(pid, db_path=db_path)
    assert got["data"] is None


# ---------------------------------------------------------------------------
# API 层
# ---------------------------------------------------------------------------
@pytest.fixture()
def tmp_paper_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "api_paper_data.db")
    monkeypatch.setattr(PDB, "_PAPER_DB", db_path)
    return db_path


def test_api_post_data_and_get_returns_data(tmp_paper_db):
    from fastapi.testclient import TestClient

    from matlens_kit.api.server import app

    client = TestClient(app)
    r = client.post("/api/papers", json={"title": "API 数据论文", "topic": "SOFC"})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]

    payload = {"data": {"status": "proposed", "notes": "拟议值待验证", "tables": [{"name": "Table 1", "caption": "", "rows": [[1, 2]]}]}}
    r2 = client.post(f"/api/papers/{pid}/data", json=payload)
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "proposed"
    assert body["data"]["tables"][0]["rows"] == [[1, 2]]

    r3 = client.get(f"/api/papers/{pid}")
    assert r3.status_code == 200
    d = r3.json()
    assert d["data"]["notes"] == "拟议值待验证"
    assert len(d["data"]["tables"]) == 1


def test_api_post_data_404(tmp_paper_db):
    from fastapi.testclient import TestClient

    from matlens_kit.api.server import app

    client = TestClient(app)
    r = client.post("/api/papers/nonexistent/data", json={"data": {"status": "proposed"}})
    assert r.status_code == 404
