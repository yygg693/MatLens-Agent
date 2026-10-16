# -*- coding: utf-8 -*-
"""matlens_kit 定制层测试的公共夹具。

根 tests/conftest.py 已做全局隔离（MATLENS_HOME 指向临时目录、清掉凭证环境变量）。
本文件补充一个面向 paper/db 的隔离夹具。

关键事实：paper/db.py 的 ``_PAPER_DB`` 在 import 时就固定为
``~/.matlens/papers.db``（走 ``Path.home()``，不读 MATLENS_HOME），
因此 paper 相关测试必须——
- 直接给 db.py 的函数传 ``db_path=<临时文件>``；或
- 用 monkeypatch 把 ``PDB._PAPER_DB`` 指到临时库（PaperEngine 不接受 db_path 时）。
绝不读写真实 ``~/.matlens/papers.db``。
"""
from __future__ import annotations

import pytest


@pytest.fixture()
def tmp_mat_home(tmp_path, monkeypatch):
    """把 MATLENS_HOME 指向临时目录（测试结束自动还原）。

    仅给那些读 MATLENS_HOME 的代码一个隔离目录；paper/db 的真实隔离靠
    显式 db_path / monkeypatch ``PDB._PAPER_DB``（见上文注释）。
    """
    mat_home = tmp_path / "matlens_home"
    mat_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MATLENS_HOME", str(mat_home))
    return mat_home
