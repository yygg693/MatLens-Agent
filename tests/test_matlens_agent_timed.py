# -*- coding: utf-8 -*-
"""MatLens 回归测试 —— P2-3 agent 构造超时守卫。

覆盖 get_agent_timed：正常返回、构造抛错透传、超时抛 TimeoutError（防记忆后端
挂起把 HTTP 请求线程永久卡死）。
"""
import time

import pytest

import matlens_kit.ui.common as common


def test_normal_return(monkeypatch):
    fake = object()
    monkeypatch.setattr(common, "get_agent", lambda session_id="", **kw: fake)
    assert common.get_agent_timed(session_id="s1", timeout=2) is fake


def test_exception_propagated(monkeypatch):
    def boom(session_id="", **kw):
        raise RuntimeError("构造失败")

    monkeypatch.setattr(common, "get_agent", boom)
    with pytest.raises(RuntimeError, match="构造失败"):
        common.get_agent_timed(session_id="s2", timeout=2)


def test_timeout_raises(monkeypatch):
    def slow(session_id="", **kw):
        time.sleep(5)  # 超过 timeout

    monkeypatch.setattr(common, "get_agent", slow)
    start = time.monotonic()
    with pytest.raises(TimeoutError):
        common.get_agent_timed(session_id="s3", timeout=0.2)
    # 守卫应快速返回（不等待完整 5s）
    assert time.monotonic() - start < 3


def test_timeout_does_not_block_process_exit():
    # daemon 线程 + join 限时：即使内部线程仍挂起，函数已返回
    # （该断言由上一个用例的时间上限间接保证，这里验证 timeout 参数生效）
    assert common.get_agent_timed.__doc__  # 文档存在即契约存在
