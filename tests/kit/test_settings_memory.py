# -*- coding: utf-8 -*-
"""设置页「通用/记忆」tab → 运行时生效的后端接线测试。

覆盖（见 design/settings-backend-contract.md 第 6 节）：
  (a) run_agent._sync_external_memory_for_turn 的 auto_write 门控：
      auto_write=false 不写、总开关 enabled=false 不写、默认会写；prefetch 始终保留。
  (b) matlens_kit.ui.common.get_agent 构造 AIAgent 时把 settings 实时翻译成
      max_iterations / reasoning_config / skip_memory（用假 AIAgent 捕获 kwargs，
      绝不真实构造 qdrant/LLM）。
  (c) GET /api/memory/status 形状，且随 memory.enabled 联动；关闭时手动 add 返回
      {ok:false,'记忆已关闭'}，list 不报错。
  (d) memory.graph_auto_build=false 时 get_graph 不自动从记忆构图。

全程：tmp_mat_home 隔离 MATLENS_HOME，假 provider/假 agent，严禁真实联网/qdrant/LLM。
"""
from __future__ import annotations

import json
import sys
import types

import pytest


# ---------------------------------------------------------------------------
# (a) 回合末记忆同步 auto_write 门控
# ---------------------------------------------------------------------------
class _FakeMemoryManager:
    """记录 sync_all / queue_prefetch_all 是否被调用。"""

    def __init__(self):
        self.sync_calls = []
        self.prefetch_calls = []

    def sync_all(self, user_text, response_text, **kw):
        self.sync_calls.append((user_text, response_text, kw))

    def queue_prefetch_all(self, user_text, **kw):
        self.prefetch_calls.append(user_text)


def _make_agent_with_mm(mm):
    """不跑 __init__ 造一个最小 AIAgent，只挂 _memory_manager / session_id。"""
    from run_agent import AIAgent

    agent = AIAgent.__new__(AIAgent)
    agent._memory_manager = mm
    agent.session_id = "test-session"
    return agent


def test_auto_write_default_writes(tmp_mat_home):
    agent = _make_agent_with_mm(_FakeMemoryManager())
    agent._sync_external_memory_for_turn(
        original_user_message="用户最近在研究钙钛矿的稳定性问题",
        final_response="结论：湿度加速相分离，需要封装。",
        interrupted=False,
        messages=None,
    )
    assert len(agent._memory_manager.sync_calls) == 1, "默认(auto_write=true)应自动写入"
    assert len(agent._memory_manager.prefetch_calls) >= 1, "非 trivial 回合应预热 prefetch"


def test_auto_write_false_skips_write_keeps_prefetch(tmp_mat_home):
    from matlens_kit import settings_store

    settings_store.update_settings({"memory": {"auto_write": False}})
    agent = _make_agent_with_mm(_FakeMemoryManager())
    agent._sync_external_memory_for_turn(
        original_user_message="用户最近在研究钙钛矿的稳定性问题",
        final_response="结论：湿度加速相分离，需要封装。",
        interrupted=False,
        messages=None,
    )
    assert agent._memory_manager.sync_calls == [], "auto_write=false 必须跳过 sync_all 写入"
    assert len(agent._memory_manager.prefetch_calls) >= 1, "但保留 prefetch 召回预热"


def test_memory_disabled_no_write(tmp_mat_home):
    # 总开关关闭 → skip_memory 使 _memory_manager 为 None（此处直接模拟该终态）
    agent = _make_agent_with_mm(None)
    agent._sync_external_memory_for_turn(
        original_user_message="用户最近在研究钙钛矿的稳定性问题",
        final_response="结论：湿度加速相分离。",
        interrupted=False,
        messages=None,
    )
    # _memory_manager is None → 提前 return，不写不炸
    assert agent._memory_manager is None


# ---------------------------------------------------------------------------
# (b) common.get_agent 把 settings 翻译成 AIAgent 构造 kwargs
# ---------------------------------------------------------------------------
class _CapturingAgent:
    """假 AIAgent：记录构造 kwargs，提供 model/provider 属性供池判断。"""

    def __init__(self, **kw):
        _CapturingAgent.last_kwargs = kw
        self.model = kw.get("model")
        self.provider = kw.get("provider")


def _patch_fake_agent(monkeypatch):
    """把 run_agent.AIAgent 换成捕获假类（避免真实导入副作用之外的构造）。"""
    fake_mod = types.ModuleType("run_agent")
    fake_mod.AIAgent = _CapturingAgent
    monkeypatch.setitem(sys.modules, "run_agent", fake_mod)
    from matlens_kit.ui import common

    common.reset_agent()
    return common


def test_common_passes_max_turns_skip_memory_reasoning(tmp_mat_home, monkeypatch):
    from matlens_kit import settings_store

    common = _patch_fake_agent(monkeypatch)

    # max_turns=42 / reasoning_effort=high / memory.enabled=false
    settings_store.update_settings(
        {
            "general": {"max_turns": 42, "reasoning_effort": "high"},
            "memory": {"enabled": False},
        }
    )
    common.reset_agent()
    common.get_agent(session_id="s-1")  # 会话池路径
    kw = _CapturingAgent.last_kwargs
    assert kw.get("max_iterations") == 42, "max_turns 应映射为 max_iterations"
    assert kw.get("skip_memory") is True, "enabled=false 应映射为 skip_memory=True"
    rc = kw.get("reasoning_config") or {}
    assert rc.get("effort") == "high", f"reasoning_effort 应进 reasoning_config: {rc}"
    assert rc.get("enabled") is True

    # enabled=true → skip_memory=False；全局单例路径
    settings_store.update_settings({"memory": {"enabled": True}})
    common.reset_agent()
    common.get_agent()  # 全局单例路径
    kw2 = _CapturingAgent.last_kwargs
    assert kw2.get("skip_memory") is False, "enabled=true 应映射为 skip_memory=False"
    assert kw2.get("max_iterations") == 42


# ---------------------------------------------------------------------------
# (c) GET /api/memory/status 形状 + enabled 联动；disabled 时 add/list 行为
# ---------------------------------------------------------------------------
class _UnserializableBackend:
    """模拟真实 OSSBackend：一个普通 Python 对象，json.dumps 会失败。"""

    pass


class _FakeMem0Provider:
    # 真实环境 _backend 是不可序列化的后端对象（如 OSSBackend 实例），
    # 不是字符串——早期用字符串 _backend 的假对象没覆盖到生产 500。
    _backend = _UnserializableBackend()
    _mode = "oss"

    def handle_tool_call(self, tool_name, args):
        return json.dumps({"results": [{"id": "1"}, {"id": "2"}, {"id": "3"}]})


def test_memory_status_shape_and_enabled_linkage(tmp_mat_home, monkeypatch):
    from fastapi.testclient import TestClient

    from matlens_kit.api import mem_api
    from matlens_kit.api.server import app

    # 后端就绪时：用假 provider（_backend 是不可序列化对象），count=3
    monkeypatch.setattr(mem_api, "_get_provider", lambda: _FakeMem0Provider())
    client = TestClient(app)

    r = client.get("/api/memory/status")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["enabled"] is True
    assert body["provider"] == "mem0"
    # source 必须是 JSON 安全字符串（_mode=oss → "oss"），绝不能是后端对象
    assert body["source"] == "oss"
    assert isinstance(body["source"], str)
    json.dumps(body)  # 整包可序列化
    assert body["count"] == 3
    assert body["auto_write"] is True
    assert body["graph_auto_build"] is True

    # 关闭总开关：不碰后端，count=null，source=None
    from matlens_kit import settings_store

    settings_store.update_settings({"memory": {"enabled": False}})
    r2 = client.get("/api/memory/status")
    b2 = r2.json()
    assert b2["enabled"] is False
    assert b2["count"] is None
    assert b2["source"] is None

    # 手动 add 关闭时返回 ok:false
    r3 = client.post("/api/memory", json={"content": "一条测试记忆"})
    b3 = r3.json()
    assert b3["ok"] is False
    assert "记忆已关闭" in b3.get("error", "")

    # list 关闭时不报错、返回空
    r4 = client.get("/api/memory")
    b4 = r4.json()
    assert r4.status_code == 200
    assert b4["ok"] is True
    assert b4["count"] == 0
    assert b4["memories"] == []


def test_status_backend_object_is_json_safe_regression(tmp_mat_home, monkeypatch):
    """回归：生产环境 _backend 是 OSSBackend 实例（不可序列化）曾导致 500。

    构造一个 _backend 为普通不可序列化对象的假 provider，经 TestClient 打
    GET /api/memory/status，断言 200、整包可 json.dumps、source 为 str/None。
    """
    from fastapi.testclient import TestClient

    from matlens_kit.api import mem_api
    from matlens_kit.api.server import app

    class _OSSBackendLike:
        """模拟 plugins.memory.mem0._backend.OSSBackend（无 __dict__ 序列化友好性）。"""

        def __repr__(self):
            return "<OSSBackend object at 0xdeadbeef>"

    class _Prov:
        _backend = _OSSBackendLike()
        _mode = "oss"

    # 直接替换两个内部函数：provider 带不可序列化 backend；count 直接给整数
    monkeypatch.setattr(mem_api, "_get_provider", lambda: _Prov())
    monkeypatch.setattr(mem_api, "_backend_ready", lambda p: True)
    monkeypatch.setattr(mem_api, "_best_effort_count", lambda p: 42)

    client = TestClient(app)
    r = client.get("/api/memory/status")
    assert r.status_code == 200, r.text
    body = r.json()
    # source 必须是字符串标识，绝不能是后端对象
    assert isinstance(body["source"], (str, type(None)))
    assert body["source"] == "oss"
    assert body["count"] == 42
    json.dumps(body)  # 关键：整包可序列化，否则就是当年的 500

    # enabled=false：不碰后端，source=None / count=None
    from matlens_kit import settings_store

    settings_store.update_settings({"memory": {"enabled": False}})
    called = {"n": 0}

    def _boom():
        called["n"] += 1
        raise AssertionError("enabled=false 不得构造/访问后端")

    monkeypatch.setattr(mem_api, "_get_provider", _boom)
    r2 = client.get("/api/memory/status")
    assert r2.status_code == 200
    b2 = r2.json()
    assert b2["enabled"] is False
    assert b2["source"] is None
    assert b2["count"] is None
    assert called["n"] == 0


# ---------------------------------------------------------------------------
# (d) graph_auto_build=false 时 get_graph 不自动构图
# ---------------------------------------------------------------------------
def test_graph_auto_build_off_skips_rebuild(tmp_mat_home, monkeypatch):
    from pathlib import Path

    from matlens_kit import settings_store
    from matlens_kit.api import graph_api

    # 指向临时空路径（无缓存），避免读写真实 ~/.matlens/graph.json
    tmp_graph = tmp_mat_home / "graph.json"
    monkeypatch.setattr(graph_api, "_GRAPH_PATH", tmp_graph)

    built = {"called": False}

    def _boom(*a, **k):
        built["called"] = True
        raise AssertionError("graph_auto_build=off 时不得自动从记忆构图")

    monkeypatch.setattr(graph_api, "_build_graph", _boom)

    settings_store.update_settings({"memory": {"graph_auto_build": False}})
    out = graph_api.get_graph()
    assert built["called"] is False, "关闭时 get_graph 不得触发 _build_graph"
    assert out.get("auto_build") is False
    assert out.get("nodes") == []
    assert out.get("edges") == []

    # 手动 extract 也被拒绝
    out2 = graph_api.extract_graph()
    assert built["called"] is False
    assert out2.get("auto_build") is False


def test_graph_auto_build_on_builds_when_no_cache(tmp_mat_home, monkeypatch):
    from matlens_kit import settings_store
    from matlens_kit.api import graph_api

    tmp_graph = tmp_mat_home / "graph.json"
    monkeypatch.setattr(graph_api, "_GRAPH_PATH", tmp_graph)

    built = {"called": False}

    def _fake_build(force=False):
        built["called"] = True
        return {"nodes": [{"id": "n1"}], "edges": []}

    monkeypatch.setattr(graph_api, "_build_graph", _fake_build)
    settings_store.update_settings({"memory": {"graph_auto_build": True}})

    out = graph_api.get_graph()
    assert built["called"] is True, "开启且无缓存时应构图"
    assert out.get("auto_build") is True
    assert out.get("nodes")
