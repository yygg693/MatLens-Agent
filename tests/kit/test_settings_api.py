# -*- coding: utf-8 -*-
"""GET/PUT /api/settings 接通测试（TestClient，tmp_mat_home 隔离）。

断言：
(a) 每个新键 PUT 后再 GET 值保持（持久化往返，含 int/bool 类型）；
(b) 嵌套部分更新不会冲掉其它段；
(c) model / approval / api_key 旧流程仍正常；
(d) settings_store 直接读写与 HTTP 落盘一致。
"""
from __future__ import annotations

import yaml
from fastapi.testclient import TestClient

from matlens_kit.api.server import app
from matlens_kit import settings_store as s


def test_get_shape_and_old_fields(tmp_mat_home):
    client = TestClient(app)
    r = client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    # 旧字段全部保留
    for k in ("model", "providers", "model_catalog", "api_key_set",
              "api_key_masked", "provider_keys", "approval", "agent", "memory"):
        assert k in body, f"missing old field {k}"
    # 新段
    for k in ("general", "papers", "kb", "experiment", "about"):
        assert k in body, f"missing new section {k}"
    # 默认值
    assert body["general"]["max_turns"] == 25
    assert body["general"]["reasoning_effort"] == "medium"
    assert body["memory"]["enabled"] is True
    assert body["memory"]["auto_write"] is True
    assert body["memory"]["graph_auto_build"] is True
    # agent 别名与 general 一致
    assert body["agent"]["reasoning_effort"] == body["general"]["reasoning_effort"]
    assert body["agent"]["max_turns"] == body["general"]["max_turns"]


def test_put_nested_roundtrip_types(tmp_mat_home):
    client = TestClient(app)
    r = client.put("/api/settings", json={
        "papers": {"cite_style": "ieee", "autosave": False},
        "kb": {"chunk_size": 1200, "table_extract": False},
        "experiment": {"dpi": 600},
        "general": {"reasoning_effort": "high", "max_turns": 100},
    })
    assert r.status_code == 200
    assert r.json()["ok"] is True

    body = client.get("/api/settings").json()
    assert body["papers"]["cite_style"] == "ieee"
    assert body["papers"]["autosave"] is False
    assert isinstance(body["papers"]["autosave"], bool)
    assert body["kb"]["chunk_size"] == 1200
    assert isinstance(body["kb"]["chunk_size"], int)
    assert body["kb"]["table_extract"] is False
    assert body["experiment"]["dpi"] == 600
    assert isinstance(body["experiment"]["dpi"], int)
    assert body["general"]["reasoning_effort"] == "high"
    assert body["general"]["max_turns"] == 100
    # agent 别名同步
    assert body["agent"]["reasoning_effort"] == "high"
    assert body["agent"]["max_turns"] == 100


def test_put_nested_does_not_clobber_other_sections(tmp_mat_home):
    client = TestClient(app)
    client.put("/api/settings", json={
        "papers": {"cite_style": "ieee", "tone": "detailed"},
        "kb": {"chunk_size": 1200},
    })
    # 只更新 papers.cite_style
    r = client.put("/api/settings", json={"papers": {"cite_style": "apa"}})
    assert r.json()["ok"] is True
    body = client.get("/api/settings").json()
    assert body["papers"]["cite_style"] == "apa"
    assert body["papers"]["tone"] == "detailed"   # 未提及保留
    assert body["kb"]["chunk_size"] == 1200        # 其它段不被冲掉
    assert body["kb"]["embed_model"] == "local"    # 默认仍在


def test_old_flat_model_approval_apikey_flow(tmp_mat_home):
    client = TestClient(app)
    # 模型扁平字段
    r = client.put("/api/settings", json={
        "model_default": "deepseek-chat",
        "model_provider": "deepseek",
        "api_key": "sk-test1234567890abcdef",
    })
    assert r.status_code == 200
    body = client.get("/api/settings").json()
    assert body["model"]["default"] == "deepseek-chat"
    assert body["model"]["provider"] == "deepseek"
    assert body["api_key_set"] is True
    assert body["api_key_masked"]  # 已脱敏

    # 审批扁平字段
    r2 = client.put("/api/settings", json={
        "approval_enabled": True,
        "approval_strategy": "confirm_list",
        "approval_allowlist": ["web_search", "read_file"],
    })
    assert r2.json()["ok"] is True
    body2 = client.get("/api/settings").json()
    assert body2["approval"]["enabled"] is True
    assert body2["approval"]["strategy"] == "confirm_list"
    assert body2["approval"]["allowlist"] == ["web_search", "read_file"]


def test_agent_reset_triggers(tmp_mat_home):
    client = TestClient(app)
    # 普通 papers 改动不应触发 reset
    r = client.put("/api/settings", json={"papers": {"cite_style": "ieee"}})
    assert r.json()["agent_reset"] is False
    # effort 变化触发
    r = client.put("/api/settings", json={"general": {"reasoning_effort": "high"}})
    assert r.json()["agent_reset"] is True
    # max_turns 变化触发
    r = client.put("/api/settings", json={"general": {"max_turns": 100}})
    assert r.json()["agent_reset"] is True
    # memory.enabled 变化触发
    r = client.put("/api/settings", json={"memory": {"enabled": False}})
    assert r.json()["agent_reset"] is True
    # 已为该值，无变化不触发
    r = client.put("/api/settings", json={"memory": {"enabled": False}})
    assert r.json()["agent_reset"] is False


def test_store_directly_matches_http(tmp_mat_home):
    client = TestClient(app)
    client.put("/api/settings", json={"experiment": {"template": "electrochem"}})
    # settings_store 直读与 HTTP 返回一致
    ss = s.load_settings()
    body = client.get("/api/settings").json()
    assert ss["experiment"]["template"] == body["experiment"]["template"] == "electrochem"
    # 落盘文件确认
    raw = yaml.safe_load(s._config_path().read_text(encoding="utf-8"))
    assert raw["experiment"]["template"] == "electrochem"
