"""MatLens 垂直工具桥接（注册机制接入，零核心逻辑改动）。

Hermes 工具发现会扫描 tools/*.py 并 import 含 ``registry.register`` 的模块。
本文件：1) 顶层调用 ``registry.register``（让 AST 识别为工具模块被 import）；
        2) import matlens_kit 包，触发材料 10 工具与 RAG 插件的注册。
所有实现代码均在 matlens_kit/ 目录下。
"""

from __future__ import annotations

from typing import Any, Dict, List

from tools.registry import registry, tool_result

# 导入 matlens_kit 触发 10 个材料工具 + rag_search 注册（见各模块顶层 registry.register）
from matlens_kit.tools import material_kit  # noqa: F401
from matlens_kit.plugins import local_rag  # noqa: F401


# ─────────────────────────────────────────────────────────────
# matlens_kb：对话内知识库命令工具（让桥接具备真实功能）
# ─────────────────────────────────────────────────────────────
def matlens_kb_tool(command_line: str, **kwargs: Any) -> Dict[str, Any]:
    """执行 MatLens 本地知识库管理命令。

    Args:
        command_line: 知识库命令，如 "create mylib" / "switch mylib" /
            "add /path/a.pdf" / "ask TiO2 的带隙是多少" / "list" / "stats"。

    Returns:
        命令执行结果。
    """
    parts: List[str] = [p for p in command_line.split(" ") if p.strip()]
    if not parts:
        return {"error": "用法：matlens_kb <list|create|switch|delete|add|ask|stats> ..."}
    return local_rag.handle_kb_command(parts)


MATLENS_KB_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "command_line": {
            "type": "string",
            "description": "知识库命令：create <名> / switch <名> / delete <名> / "
                           "add <文件路径...> / ask <问题> / list / stats",
        },
    },
    "required": ["command_line"],
    "additionalProperties": False,
}


def _check_kit_available() -> bool:
    return True


registry.register(
    name="matlens_kb",
    toolset="matlens_material",
    schema=MATLENS_KB_SCHEMA,
    handler=lambda args, **kw: tool_result(matlens_kb_tool(command_line=args.get("command_line", ""))),
    check_fn=_check_kit_available,
    description="MatLens 本地文献知识库管理：create/switch/add/ask/list/delete/stats（数据在 ~/.matlens/knowledge/）",
    emoji="📚",
)
