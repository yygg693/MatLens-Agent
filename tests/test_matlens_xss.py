# -*- coding: utf-8 -*-
"""MatLens 回归测试 —— P0 会话 ID 注入面（XSS/路径穿越）加固。

覆盖 create_session 的 session_id 白名单逻辑：非法字符一律服务端生成 UUID，
合法白名单字符保留，从根上堵死存储型 XSS 与路径穿越。
"""
import re
import uuid

import pytest

from matlens_kit.api.sessions_api import _SESSION_ID_RE, create_session


class TestSessionIdAllowlist:
    def test_valid_ids_match(self):
        for sid in ["abc", "a1B_-", "session_001", "x" * 96]:
            assert _SESSION_ID_RE.match(sid), sid

    def test_invalid_ids_rejected(self):
        for sid in [
            '<script>alert(1)</script>',
            "a b c",
            "id;DROP TABLE",
            "../etc/passwd",
            "a/b",
            "a\\b",
            "中文会话",
            "x" * 97,  # 超长
            "a:b",
            "",
        ]:
            assert _SESSION_ID_RE.match(sid) is None, sid


class TestCreateSessionSanitization:
    """create_session 对显式 session_id 的清洗（核心 P0 回归）。"""

    def test_legitimate_id_preserved(self):
        r = create_session({"session_id": "my_research_001", "title": "t"})
        assert r["id"] == "my_research_001"

    def test_xss_payload_replaced_with_uuid(self):
        r = create_session({"session_id": "<script>alert(1)</script>"})
        # 必须被替换为 32 位十六进制 UUID，而不是原样透传
        assert re.fullmatch(r"[0-9a-f]{32}", r["id"])
        assert r["id"] != "<script>alert(1)</script>"

    def test_path_traversal_replaced_with_uuid(self):
        r = create_session({"session_id": "../../../etc/passwd"})
        assert re.fullmatch(r"[0-9a-f]{32}", r["id"])

    def test_empty_session_id_gets_uuid(self):
        r = create_session({"session_id": ""})
        assert re.fullmatch(r"[0-9a-f]{32}", r["id"])
        # UUID 形式本身是合法白名单字符（大写十六进制 A-F 不在白名单），
        # 服务端生成的是小写 hex，不会进入非法分支
        assert uuid.UUID(r["id"]).version == 4
