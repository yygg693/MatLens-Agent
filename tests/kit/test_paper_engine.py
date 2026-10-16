# -*- coding: utf-8 -*-
"""paper/engine.py：前置状态机 + PaperEngine CRUD。

PaperEngine 的 create/list/get/delete 不接受 db_path（内部直调 PDB），
故用 monkeypatch 把 PDB._PAPER_DB 指到临时库，绝不落真实 ~/.matlens。
"""
from __future__ import annotations

import pytest

from matlens_kit.paper import db as PDB
from matlens_kit.paper.engine import PaperEngine, check_prerequisite


def _pending_stages():
    return {
        "topic": {"status": "pending", "content": "", "refs": [], "error": ""},
        "search": {"status": "pending", "content": "", "refs": [], "error": ""},
    }


def test_topic_has_no_prerequisite():
    ok, reason = check_prerequisite(_pending_stages(), "topic")
    assert ok is True
    assert reason == ""


def test_search_blocked_when_topic_not_done():
    ok, reason = check_prerequisite(_pending_stages(), "search")
    assert ok is False
    assert reason  # 应给出「前置步骤尚未完成」之类的原因


def test_search_passes_after_topic_done():
    stages = _pending_stages()
    stages["topic"]["status"] = "done"
    ok, reason = check_prerequisite(stages, "search")
    assert ok is True
    assert reason == ""


@pytest.fixture()
def engine_on_tmp_db(tmp_path, monkeypatch):
    tmp_db = str(tmp_path / "engine_papers.db")
    monkeypatch.setattr(PDB, "_PAPER_DB", tmp_db)
    return PaperEngine()


def test_engine_create_list_get_delete(engine_on_tmp_db):
    e = engine_on_tmp_db
    a = e.create("引擎项目A")
    b = e.create("引擎项目B")
    assert a["id"] != b["id"]

    lst = e.list()
    assert len(lst) == 2
    assert {x["title"] for x in lst} == {"引擎项目A", "引擎项目B"}

    got = e.get(a["id"])
    assert got is not None
    assert got["title"] == "引擎项目A"

    assert e.delete(a["id"]) is True
    assert e.get(a["id"]) is None
    assert len(e.list()) == 1
