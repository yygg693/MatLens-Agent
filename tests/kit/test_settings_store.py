# -*- coding: utf-8 -*-
"""settings_store 统一存储基座测试。

断言：
- DEFAULTS 形状完整；
- update_settings 嵌套部分更新后 load_settings 往返保持（int/bool 类型）；
- 嵌套部分更新不会冲掉其它段；
- 落盘 config.yaml 与直接读取一致，且新键不被 strip_defaults 误删。
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

from matlens_kit import settings_store as s


def test_defaults_shape():
    d = s.load_settings()
    # 五段规范字段齐全
    assert set(d["general"]) == {"theme", "tool_progress", "reasoning_effort", "max_turns"}
    assert set(d["memory"]) == {"enabled", "auto_write", "graph_auto_build", "provider"}
    # papers段允许新增可选字段（导出质量门等），只断言必需字段是超集
    assert {"export_format", "cite_style", "autosave", "tone"} <= set(d["papers"])
    assert set(d["kb"]) == {"embed_model", "chunk_size", "chunk_overlap", "table_extract", "root"}
    assert set(d["experiment"]) == {"template", "autosave", "plot_format", "dpi", "db_path"}
    assert set(d["about"]) == {"version", "tech_stack", "home"}
    # 注意：这里**不断言默认值**（max_turns 等），因为 load_settings 会读用户
    # 真实配置，用户改了值就会失败 —— 那不是 bug。默认值验证见下一个测试。
    assert d["experiment"]["dpi"] >= 0
    assert isinstance(d["memory"]["auto_write"], bool)


def test_defaults_are_used_when_no_disk_config(tmp_path, monkeypatch):
    """无磁盘配置时，各字段必须回落到 DEFAULTS 的声明值。

    这个断言必须隔离真实磁盘配置 —— load_settings() 会读取用户实际的
    config.yaml，而用户改了值（比如 max_turns=500）就会让「默认值」断言
    失败。那不是产品 bug，而是测试没隔离环境（2026-10-15 路径统一后暴露）。
    """
    import pathlib

    empty = tmp_path / "config.yaml"
    empty.write_text("", encoding="utf-8")          # 空文件 → 读出 {}
    monkeypatch.setattr(s, "_config_candidates", lambda: [empty])

    d = s.load_settings()
    assert d["general"]["max_turns"] == s.DEFAULTS["general"]["max_turns"] == 25
    assert d["kb"]["chunk_size"] == 800
    assert d["general"]["theme"] == "dark"
    assert isinstance(pathlib.Path(s._config_path()).name, str)


def test_config_path_is_single_source():
    """config.yaml 路径必须唯一。

    背景：2026-10-15 曾为兼容 Windows 上 ``%LOCALAPPDATA%`` 与 ``~/.matlens``
    的分叉而同时读两处，导致「保存成功却读不回来」。2026-10-16 上游
    ``_get_platform_default_matlens_home()`` 已统一为 ``~/.matlens``，
    分叉根因消除，故退回单路径 —— 路径多源就会再次分叉出静默数据问题。
    """
    assert len(s._config_candidates()) == 1, "config 路径必须唯一，否则会再次分叉"
    assert s._config_candidates()[0] == s._config_path()


def test_config_path_follows_matlens_home(tmp_path, monkeypatch):
    """设 MATLENS_HOME 后，config 路径应跟随 —— 测试隔离与自定义目录的基础。"""
    iso = tmp_path / "iso"
    iso.mkdir()
    monkeypatch.setenv("MATLENS_HOME", str(iso))
    assert s._config_path() == iso / "config.yaml"


def test_read_raw_reads_only_configured_path(tmp_path, monkeypatch):
    """只读指定路径；不存在的目录返回空 dict，不回退到真实用户目录。"""
    empty = tmp_path / "none"
    empty.mkdir()
    monkeypatch.setattr(s, "_config_candidates", lambda: [empty / "config.yaml"])
    assert s._read_raw_config() == {}

    f = empty / "config.yaml"
    f.write_text("agent:\n  model: m1\n", encoding="utf-8")
    raw = s._read_raw_config()
    assert raw["agent"]["model"] == "m1"


def test_home_uses_authoritative_source():
    """_home() 必须走 matlens_cli.config.get_matlens_home（单一事实来源）。"""
    from matlens_cli.config import get_matlens_home

    assert s._home() == get_matlens_home()


def test_export_quality_gate_defaults():
    """导出质量门默认开启，阈值 60（paper/quality_gate.py 依赖这两个默认值）。"""
    d = s.load_settings()
    assert d["papers"]["export_quality_gate"] is True
    assert d["papers"]["export_min_score"] == 60


def test_roundtrip_types(tmp_mat_home):
    s.update_settings({
        "papers": {"cite_style": "ieee"},
        "kb": {"chunk_size": 1200, "table_extract": False},
        "experiment": {"dpi": 600},
        "general": {"max_turns": 50, "reasoning_effort": "high"},
        "memory": {"auto_write": False},
    })
    d = s.load_settings()
    assert d["papers"]["cite_style"] == "ieee"
    assert d["kb"]["chunk_size"] == 1200
    assert isinstance(d["kb"]["chunk_size"], int)
    assert d["kb"]["table_extract"] is False
    assert isinstance(d["kb"]["table_extract"], bool)
    assert d["experiment"]["dpi"] == 600
    assert isinstance(d["experiment"]["dpi"], int)
    assert d["general"]["max_turns"] == 50
    assert d["general"]["reasoning_effort"] == "high"
    assert d["memory"]["auto_write"] is False


def test_int_coercion_from_string(tmp_mat_home):
    # 前端 select 给的是字符串，update 必须强制 int
    s.update_settings({"kb": {"chunk_size": "1200", "chunk_overlap": "200"}})
    d = s.load_settings()
    assert d["kb"]["chunk_size"] == 1200
    assert isinstance(d["kb"]["chunk_size"], int)
    assert d["kb"]["chunk_overlap"] == 200


def test_nested_partial_does_not_clobber(tmp_mat_home):
    # 先写 papers 全段 + kb
    s.update_settings({
        "papers": {"cite_style": "ieee", "tone": "detailed"},
        "kb": {"chunk_size": 1200, "embed_model": "text-embedding-3-small"},
    })
    # 再只更新 papers.cite_style
    s.update_settings({"papers": {"cite_style": "apa"}})
    d = s.load_settings()
    assert d["papers"]["cite_style"] == "apa"
    # 未提及的叶子保持
    assert d["papers"]["tone"] == "detailed"
    assert d["kb"]["chunk_size"] == 1200
    assert d["kb"]["embed_model"] == "text-embedding-3-small"


def test_disk_roundtrip_and_persistence(tmp_mat_home):
    s.update_settings({"experiment": {"template": "electrochem", "plot_format": "svg"}})
    # 直接读磁盘文件，确认落盘内容
    path = s._config_path()
    assert path.exists()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    # 实验段落盘在 experiment.* 同名同段
    assert raw["experiment"]["template"] == "electrochem"
    assert raw["experiment"]["plot_format"] == "svg"
    # int 字段落盘是 int（不是字符串）
    s.update_settings({"kb": {"chunk_size": 500}})
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["kb"]["chunk_size"] == 500
    assert isinstance(raw["kb"]["chunk_size"], int)


def test_get_section(tmp_mat_home):
    s.update_settings({"papers": {"export_format": "md"}})
    papers = s.get_section("papers")
    assert papers["export_format"] == "md"
    assert papers["cite_style"] == "gb7714"  # 未改的保持默认
    # 未知段返回空 dict
    assert s.get_section("nope") == {}


def test_platform_default_matches_legacy_hardcoded_path(monkeypatch):
    """⚠️ 关键防回归：默认 home 必须与项目内 30+ 处硬编码的 ``~/.matlens`` 一致。

    背景（2026-10-16 收拢）：``_get_platform_default_matlens_home()`` 原先在
    Windows 上返回 ``%LOCALAPPDATA%/matlens``，而项目里 server.py /
    graph_api.py / experiment_api.py / kanban_db.py 等大量模块硬编码
    ``~/.matlens``。服务进程靠 ``matlens_kit/api/__init__.py`` 的
    ``setdefault("MATLENS_HOME", "~/.matlens")`` 兜住，**裸跑脚本则落到
    另一个空目录** → 表现为「设置保存了没生效」「数据不见了」。

    这个断言就是守住那 30+ 处硬编码仍可用；
    若将来有人改默认路径，此测试会立即失败并指出真实影响面。
    """
    from matlens_constants import _get_platform_default_matlens_home

    monkeypatch.delenv("MATLENS_HOME", raising=False)
    default = _get_platform_default_matlens_home()
    legacy = Path.home() / ".matlens"
    assert default == legacy, (
        f"默认 home 变成了 {default}，与项目内硬编码的 {legacy} 不一致 —— "
        "所有硬编码 ~/.matlens 的模块都会读到另一个目录")


def test_bare_import_resolves_same_as_server(tmp_path):
    """裸跑（无 MATLENS_HOME）与服务进程（导入 matlens_kit.api）解析的 home 必须一致。

    2026-10-16 修复前：Windows 默认返回 %LOCALAPPDATA%/matlens，
    而服务进程被 api/__init__.py 的 setdefault 拉回 ~/.matlens → 二者分叉。
    """
    import subprocess
    import sys

    script = tmp_path / "probe.py"
    script.write_text(
        "import sys, os\n"
        "sys.path.insert(0, os.environ['MATLENS_PROBE_ROOT'])\n"
        "os.environ.pop('MATLENS_HOME', None)\n"
        "from matlens_cli.config import get_matlens_home\n"
        "bare = get_matlens_home()\n"
        "import matlens_kit.api\n"
        "print(bare == get_matlens_home())\n",
        encoding="utf-8")
    env = dict(os.environ)
    env["MATLENS_PROBE_ROOT"] = str(Path(__file__).resolve().parents[2])
    env.pop("MATLENS_HOME", None)
    out = subprocess.run([sys.executable, str(script)], capture_output=True,
                         text=True, timeout=180, env=env)
    assert out.returncode == 0, out.stderr[-600:]
    assert out.stdout.strip() == "True", (
        f"裸跑与服务进程解析到不同 home: {out.stdout.strip()} {out.stderr[-300:]}")
    assert len(out.stdout.strip().splitlines()) == 1
