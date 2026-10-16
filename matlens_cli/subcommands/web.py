"""``matlens web`` — 启动 MatLens Gradio 本地 Web 界面。"""

from __future__ import annotations

import argparse


def cmd_web(args: argparse.Namespace) -> int:
    """启动本地 Web。"""
    from matlens_kit.ui.web.gradio_app import main

    main(host=getattr(args, "host", "127.0.0.1") or "127.0.0.1", port=int(getattr(args, "port", 7860) or 7860))
    return 0


def build_web_parser(subparsers) -> None:
    """注册 ``matlens web`` 子命令。"""
    parser = subparsers.add_parser(
        "web",
        help="启动 MatLens 本地 Web 界面（Gradio）",
        description="Gradio 本地 Web：对话 / 知识库 / 工具 / 实验工作流 / 设置，复用核心 Agent 能力",
    )
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    parser.add_argument("--port", default=7860, help="端口（默认 7860）")
    parser.set_defaults(func=cmd_web)
