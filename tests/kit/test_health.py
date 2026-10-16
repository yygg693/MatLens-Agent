# -*- coding: utf-8 -*-
"""健康检查接口：GET /api/health 返回 200 且 ok==True。

import app 不会触发 main() 的 warmup（warmup 只在 ``__main__`` 里起线程），
因此这里构造 TestClient 是安全的、不会真的初始化 agent / 连 LLM。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from matlens_kit.api.server import app


def test_health_ok():
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["service"] == "matlens-api"
