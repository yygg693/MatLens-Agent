"""``matlens tui`` — 启动 MatLens Rich 终端界面。"""

from __future__ import annotations

import argparse


def cmd_tui(args: argparse.Namespace) -> int:
    """启动终端 TUI。"""
    from matlens_kit.ui.tui.app import main

    return main(model=getattr(args, "model", "") or "", provider=getattr(args, "provider", "") or "")


def build_tui_parser(subparsers) -> None:
    """注册 ``matlens tui`` 子命令。"""
    parser = subparsers.add_parser(
        "tui",
        help="启动 MatLens 终端界面（Rich TUI）",
        description="Rich 终端界面：对话 / 材料工具 / 知识库，复用核心 Agent 能力",
    )
    parser.add_argument("--model", default="", help="模型名（可选，默认取配置）")
    parser.add_argument("--provider", default="", help="provider（可选，默认取配置）")
    parser.set_defaults(func=cmd_tui)
