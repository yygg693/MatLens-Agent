# -*- coding: utf-8 -*-
"""「关于」tab 三个按钮的后端集成测试（TestClient + tmp_mat_home，不联网/不绑端口）。

覆盖契约第 3 节「其他约定接口」：
(a) POST /api/settings/reset —— 先改设置 + 写 key，重置后 GET 回默认、密钥清除、
    home 下出现 config.yaml.bak-* / .env.bak-*；
(b) POST /api/sessions/clear —— 只清 web 会话（含 0 消息预建行）及其消息，
    cli 会话不受影响；
(c) GET  /api/settings/backup —— 返回 application/zip，含 config.yaml/.env 与
    knowledge/MANIFEST.txt；state.db 缺失时也能打（best-effort）；
(d) 路由方法正确性 —— clear/reset 是 POST、backup 是 GET，且 /clear 不被
    /{session_id} 吞掉（POST /{id} 不存在）。
"""
from __future__ import annotations

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from matlens_kit.api.server import app


# ---------------------------------------------------------------------------
# (a) reset
# ---------------------------------------------------------------------------
def test_reset_restores_defaults_and_clears_keys(tmp_mat_home):
    client = TestClient(app)

    # 先把设置改离默认，并写入一个 provider key
    r = client.put("/api/settings", json={
        "general": {"max_turns": 77},
        "papers": {"export_format": "tex"},
        "model_provider": "deepseek",
        "api_key": "sk-testreset1234567890abcdef",
    })
    assert r.status_code == 200 and r.json()["ok"] is True

    body = client.get("/api/settings").json()
    assert body["general"]["max_turns"] == 77
    assert body["papers"]["export_format"] == "tex"
    assert body["api_key_set"] is True
    assert body["api_key_masked"]

    # 执行重置
    r2 = client.post("/api/settings/reset")
    assert r2.status_code == 200
    j = r2.json()
    assert j["ok"] is True
    assert j["reset"] is True
    assert any(n.startswith("config.yaml.bak-") for n in j["backed_up"])
    assert any(n.startswith(".env.bak-") for n in j["backed_up"])

    # GET 回到默认
    body2 = client.get("/api/settings").json()
    assert body2["general"]["max_turns"] == 25
    assert body2["papers"]["export_format"] == "docx"
    assert body2["api_key_set"] is False
    assert body2["api_key_masked"] in (None, "")

    # home 下确实生成了时间戳备份
    assert list(tmp_mat_home.glob("config.yaml.bak-*")), "config.yaml.bak-* 未生成"
    assert list(tmp_mat_home.glob(".env.bak-*")), ".env.bak-* 未生成"


# ---------------------------------------------------------------------------
# (b) clear —— 只清 web
# ---------------------------------------------------------------------------
def test_clear_only_web_sessions(tmp_mat_home):
    from matlens_state import SessionDB

    db = SessionDB()
    # web 会话（带消息）+ 一个 0 消息预建行
    db.create_session("web-sess-1", "web")
    db.append_message("web-sess-1", "user", "hello web")
    db.create_session("web-sess-empty", "web")
    # cli 会话（绝不能被删）
    db.create_session("cli-sess-1", "cli")
    db.append_message("cli-sess-1", "user", "hi cli")

    client = TestClient(app)
    r = client.post("/api/sessions/clear")
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["cleared"] >= 1

    # web 历史列表为空
    lst = client.get("/api/sessions").json()
    assert lst["count"] == 0
    assert lst["sessions"] == []

    # web 会话（含空预建行）已被删除，cli 会话仍在
    assert db.get_session("web-sess-1") is None
    assert db.get_session("web-sess-empty") is None
    assert db.get_session("cli-sess-1") is not None


# ---------------------------------------------------------------------------
# (c) backup
# ---------------------------------------------------------------------------
def test_backup_zip(tmp_mat_home):
    client = TestClient(app)
    # 写点东西让 config.yaml / .env 存在
    client.put("/api/settings", json={
        "papers": {"cite_style": "ieee"},
        "model_provider": "openai",
        "api_key": "sk-bkp1234567890abcdef",
    })

    r = client.get("/api/settings/backup")
    assert r.status_code == 200
    assert "application/zip" in r.headers.get("content-type", "")
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd and "matlens-backup" in cd

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(zf.namelist())
    assert "config.yaml" in names
    assert ".env" in names
    assert "knowledge/MANIFEST.txt" in names
    # arcname 不得泄漏本机绝对路径
    for n in names:
        assert not n.startswith("/"), f"绝对路径泄漏进 zip: {n}"
        assert "\\" not in n, f"Windows 绝对路径泄漏进 zip: {n}"


# ---------------------------------------------------------------------------
# (d) 路由方法正确性
# ---------------------------------------------------------------------------
def test_route_methods(tmp_mat_home):
    client = TestClient(app)
    # clear / reset 是 POST
    assert client.post("/api/sessions/clear").status_code == 200
    assert client.post("/api/settings/reset").status_code == 200
    # backup 是 GET
    assert client.get("/api/settings/backup").status_code == 200

    # /api/sessions 没有 POST /{id}：POST 到任意非 clear id 应是 405，
    # 证明 /clear 是独立字面量路由、不被 {session_id} 吞掉。
    assert client.post("/api/sessions/definitely-not-clear-id").status_code == 405
    # POST 到 backup（只注册了 GET）应 405
    assert client.post("/api/settings/backup").status_code == 405
