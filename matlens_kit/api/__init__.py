# -*- coding: utf-8 -*-
"""MatLens Web 服务层（FastAPI + SSE 事件流）。

- 同进程调核心（AIAgent / 知识库 / Mem0），不重复实现业务
- SSE 事件流：stream_text / tool_call / tool_result / done / error
- 审批（approval_request）M2 接入
"""
import os

# 关键：Web 服务必须与 CLI 共用同一数据目录（~/.matlens）。
# 若未显式设置 MATLENS_HOME，matlens 核心在 Windows 上会落到
# AppData\\Local\\matlens，导致 Web 与 CLI 读写两个独立的数据世界。
# 本行必须在任何 matlens 核心模块导入前执行（包 __init__ 最早加载）。
os.environ.setdefault("MATLENS_HOME", os.path.expanduser("~/.matlens"))

__version__ = "0.1.0"
