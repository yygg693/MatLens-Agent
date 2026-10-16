# -*- coding: utf-8 -*-
"""paper/db.py 持久层：全部走临时 db_path，不碰真实 ~/.matlens/papers.db。"""
from __future__ import annotations

import pytest

from matlens_kit.paper import db as PDB

STAGE_NAMES = ("topic", "search", "outline", "write", "quality", "review", "export")


@pytest.fixture()
def db_path(tmp_path):
    """每个测试一个独立的临时 SQLite 文件。"""
    return str(tmp_path / "papers.db")


def test_create_and_get_roundtrip(db_path):
    p = PDB.create_paper("第一个项目", topic="钙钛矿", db_path=db_path)
    assert p["title"] == "第一个项目"
    assert p["topic"] == "钙钛矿"
    pid = p["id"]
    assert pid

    got = PDB.get_paper(pid, db_path=db_path)
    assert got is not None
    assert got["id"] == pid
    assert got["title"] == "第一个项目"


def test_two_papers_do_not_pollute(db_path):
    a = PDB.create_paper("项目A", topic="A主题", db_path=db_path)
    b = PDB.create_paper("项目B", topic="B主题", db_path=db_path)
    assert a["id"] != b["id"]

    lst = PDB.list_papers(db_path=db_path)
    assert len(lst) == 2
    assert {x["title"] for x in lst} == {"项目A", "项目B"}

    # 各自取出互不串数据
    assert PDB.get_paper(a["id"], db_path=db_path)["topic"] == "A主题"
    assert PDB.get_paper(b["id"], db_path=db_path)["topic"] == "B主题"


def test_initial_stages_are_seven_pending(db_path):
    p = PDB.create_paper("七步初始", db_path=db_path)
    stages = p["stages"]
    assert set(stages.keys()) == set(STAGE_NAMES)
    assert len(stages) == 7
    for name, s in stages.items():
        assert s["status"] == "pending", f"{name} 初始应为 pending"
    assert p["progress"]["done"] == 0
    assert p["progress"]["total"] == 7


def test_set_stage_status(db_path):
    p = PDB.create_paper("改状态", db_path=db_path)
    pid = p["id"]

    res = PDB.set_stage_status(pid, "topic", "done", db_path=db_path)
    assert res["status"] == "done"

    got = PDB.get_paper(pid, db_path=db_path)
    assert got["stages"]["topic"]["status"] == "done"
    assert got["progress"]["done"] == 1


def test_save_stage_content(db_path):
    p = PDB.create_paper("存产物", db_path=db_path)
    pid = p["id"]

    saved = PDB.save_stage_content(pid, "topic", "选题内容", refs=["r1", "r2"], db_path=db_path)
    assert saved["content"] == "选题内容"
    assert saved["refs"] == ["r1", "r2"]

    got = PDB.get_paper(pid, db_path=db_path)
    assert got["stages"]["topic"]["content"] == "选题内容"


def test_delete_paper(db_path):
    p = PDB.create_paper("待删除", db_path=db_path)
    pid = p["id"]

    assert PDB.delete_paper(pid, db_path=db_path) is True
    assert PDB.get_paper(pid, db_path=db_path) is None
    assert PDB.list_papers(db_path=db_path) == []
