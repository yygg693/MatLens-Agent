# -*- coding: utf-8 -*-
"""设置页「实验」tab 接通实验工作流的测试（离线、TestClient、matplotlib Agg）。

覆盖（契约第 6 节 experiment 验收）：
(a) standard/synthesis/characterization/electrochem 四模板均非空且彼此有区分度；
    旧别名 hydrothermal 仍可用（归并到 synthesis）；
(b) settings experiment.template=electrochem 时，POST /generate（不带 template）
    自动用 electrochem；显式 template 仍覆盖设置；
(c) GET /api/experiment/templates 返回的 key 集合 == 四个设置值；
(d) 绘图纯函数：plot_format=svg/dpi=300 与 png/dpi=600 分别产出对应格式字节，
    且 savefig 确实用了设置的 format/dpi；
(e) autosave 开关后端默认值/接口层断言（前端为 JS 定时器，gate 方式见报告）。

隔离：tmp_mat_home 指向临时 MATLENS_HOME；experiment_api._EXP_DB 不读 MATLENS_HOME
（import 时 expanduser 固定），故 monkeypatch 到临时文件，绝不写真 experiments.db。
"""
from __future__ import annotations

import base64

import matplotlib
matplotlib.use("Agg")  # 无头环境，必须最先

import pytest
from fastapi.testclient import TestClient

from matlens_kit import settings_store
from matlens_kit.api.server import app
import matlens_kit.api.experiment_api as exp_api
from matlens_kit.tools.experiment import (
    EXPERIMENT_TEMPLATES,
    experiment_protocol_tool,
)


# 规范四键（与设置 experiment.template 取值一致）
CANON = {"standard", "synthesis", "characterization", "electrochem"}


@pytest.fixture()
def client(tmp_mat_home, monkeypatch, tmp_path):
    """TestClient + 把实验库 monkeypatch 到临时文件。"""
    monkeypatch.setattr(exp_api, "_EXP_DB", str(tmp_path / "experiments.db"))
    return TestClient(app)


# ── (a) 四模板非空、有区分度；旧别名 hydrothermal 仍可用 ───────────────
def test_four_templates_distinct():
    outs = {}
    for key in CANON:
        res = experiment_protocol_tool("测试目标", key)
        assert "error" not in res, f"{key} 报错: {res.get('error')}"
        assert res["steps"], f"{key} steps 为空"
        assert res["reagents"], f"{key} reagents 为空"
        outs[key] = (res["applicable"], res["reagents"], "|".join(res["steps"]))
    # 四个方案彼此有区分度（applicable + steps 全文各不相同）
    keys = list(outs)
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            assert outs[keys[i]] != outs[keys[j]], f"{keys[i]} 与 {keys[j]} 内容无区分度"


def test_legacy_alias_hydrothermal_still_works():
    res = experiment_protocol_tool("水热制备 ZnO", "hydrothermal")
    assert "error" not in res, f"旧别名 hydrothermal 报错: {res.get('error')}"
    # hydrothermal 归并为 synthesis
    assert res["template_key"] == "synthesis"
    # solgel / calcination 同样归并
    for old in ("solgel", "calcination"):
        r2 = experiment_protocol_tool("x", old)
        assert "error" not in r2
        assert r2["template_key"] == "synthesis"


def test_unknown_template_errors():
    res = experiment_protocol_tool("x", "not_a_real_template")
    assert "error" in res
    assert set(res["available_templates"]) == CANON


# ── (b) 默认模板接 settings；显式 template 覆盖 ──────────────────────
def test_generate_defaults_to_settings_template(client):
    settings_store.update_settings({"experiment": {"template": "electrochem"}})
    r = client.post("/api/experiment/generate", json={"goal": "评价电极倍率性能"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["template_key"] == "electrochem"
    assert body["template"] == "电化学测试"


def test_generate_explicit_template_overrides_settings(client):
    settings_store.update_settings({"experiment": {"template": "electrochem"}})
    # 显式传 standard，应覆盖设置里的 electrochem
    r = client.post("/api/experiment/generate",
                    json={"goal": "记录一次通用实验", "template": "standard"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["template_key"] == "standard"


def test_generate_empty_template_falls_back_to_settings(client):
    settings_store.update_settings({"experiment": {"template": "characterization"}})
    # 显式传空串 → 视同未传，回退设置默认
    r = client.post("/api/experiment/generate",
                    json={"goal": "做一组 XRD 表征", "template": ""})
    assert r.status_code == 200, r.text
    assert r.json()["template_key"] == "characterization"


# ── (c) 模板列表与设置四值一致 ───────────────────────────────────────
def test_templates_list_matches_settings_values(client):
    r = client.get("/api/experiment/templates")
    assert r.status_code == 200
    keys = {t["key"] for t in r.json()["templates"]}
    assert keys == CANON, f"模板列表 key 集合不符: {keys}"
    for t in r.json()["templates"]:
        assert t["name"] and t["applicable"]  # 卡片渲染字段齐全


def test_canonical_templates_dict_has_no_alias_leak():
    assert set(EXPERIMENT_TEMPLATES.keys()) == CANON


# ── (d) 绘图 format / dpi 实时生效 ───────────────────────────────────
def _decode_b64(res):
    return base64.b64decode(res["plot_b64"].split(",", 1)[1])


def test_plot_svg_dpi300(client, monkeypatch):
    settings_store.update_settings({"experiment": {"plot_format": "svg", "dpi": 300}})
    # 捕获 savefig 实际收到的 format/dpi
    from matplotlib.figure import Figure
    captured = {}
    orig = Figure.savefig

    def spy(self, fname, **kw):
        captured.update(kw)
        return orig(self, fname, **kw)

    monkeypatch.setattr(Figure, "savefig", spy)

    from matlens_kit.tools.plotting import experiment_plot_tool
    res = experiment_plot_tool(x=[1, 2, 3, 4, 5], y=[1, 4, 9, 16, 25], plot_type="xy")
    assert "error" not in res, res.get("error")
    assert res["plot_format"] == "svg"
    assert res["media_type"] == "image/svg+xml"
    assert res["dpi"] == 300

    raw = _decode_b64(res)
    assert raw.lstrip().startswith(b"<?xml") or b"<svg" in raw[:2000], \
        "svg 输出未含 xml/svg 头"
    # savefig 确实用了设置值
    assert captured.get("format") == "svg"
    assert captured.get("dpi") == 300


def test_plot_png_dpi600(client, monkeypatch):
    settings_store.update_settings({"experiment": {"plot_format": "png", "dpi": 600}})
    from matplotlib.figure import Figure
    captured = {}
    orig = Figure.savefig

    def spy(self, fname, **kw):
        captured.update(kw)
        return orig(self, fname, **kw)

    monkeypatch.setattr(Figure, "savefig", spy)

    from matlens_kit.tools.plotting import experiment_plot_tool
    res = experiment_plot_tool(x=[1, 2, 3], y=[2, 2, 2], plot_type="xy")
    assert "error" not in res, res.get("error")
    assert res["plot_format"] == "png"
    assert res["media_type"] == "image/png"

    raw = _decode_b64(res)
    assert raw[:8] == b"\x89PNG\r\n\x1a\n", "png 魔数不符"
    assert captured.get("format") == "png"
    assert captured.get("dpi") == 600


def test_plot_pdf_format(client):
    settings_store.update_settings({"experiment": {"plot_format": "pdf", "dpi": 150}})
    from matlens_kit.tools.plotting import experiment_plot_tool
    res = experiment_plot_tool(x=[1, 2, 3, 4], y=[3, 1, 4, 1], plot_type="cv")
    assert "error" not in res, res.get("error")
    assert res["media_type"] == "application/pdf"
    raw = _decode_b64(res)
    assert raw[:5] == b"%PDF-", "pdf 魔数不符"


# ── (e) autosave 开关后端默认值/接口层断言 ────────────────────────────
def test_autosave_default_and_toggle(client):
    # 默认开启
    assert settings_store.get_section("experiment")["autosave"] is True
    # GET /api/settings 暴露该键
    body = client.get("/api/settings").json()
    assert body["experiment"]["autosave"] is True
    # 关闭
    settings_store.update_settings({"experiment": {"autosave": False}})
    assert settings_store.get_section("experiment")["autosave"] is False
    body2 = client.get("/api/settings").json()
    assert body2["experiment"]["autosave"] is False


def test_manual_record_save_works_regardless_of_autosave(client):
    # autosave 关闭时，手动保存记录路径仍可用（autosave 只 gate 前端 60s 定时器）
    settings_store.update_settings({"experiment": {"autosave": False}})
    r = client.post("/api/experiment/record",
                    json={"title": "手动记录", "protocol": "{}", "template": "standard"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    # 列表能查到
    lst = client.get("/api/experiment/list").json()
    assert lst["count"] >= 1
