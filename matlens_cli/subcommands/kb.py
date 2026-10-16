"""``matlens kb`` — MatLens 本地文献知识库管理。

命令行全操作：
    matlens kb list
    matlens kb create <name>
    matlens kb switch <name>
    matlens kb delete <name>
    matlens kb add <file...>
    matlens kb ask <question>
    matlens kb stats

数据存 ~/.matlens/knowledge/，嵌入复用主 provider（OpenAI 兼容端点）。
"""

from __future__ import annotations

import argparse
import json


def cmd_kb(args: argparse.Namespace) -> int:
    """执行 /kb 系列命令。"""
    from matlens_kit.plugins.local_rag import handle_kb_command

    if args.kb_cmd is None:
        print("用法：matlens kb <list|create|switch|delete|add|ask|stats> ...")
        print("示例：")
        print("  matlens kb create mylib")
        print("  matlens kb switch mylib")
        print("  matlens kb add paper1.pdf paper2.txt")
        print('  matlens kb ask "TiO2 的带隙是多少"')
        return 2
    result = handle_kb_command([args.kb_cmd] + args.kb_args)
    _render(result)
    return 0


def _render(result: dict) -> None:
    """友好打印命令结果。"""
    if "error" in result:
        print(f"⚠️  {result['error']}")
        return
    if "knowledge_bases" in result:
        kbs = result["knowledge_bases"]
        active = result.get("active")
        if not kbs:
            print("（暂无知识库，用 matlens kb create <name> 创建）")
        for k in kbs:
            print(f"  {'●' if k == active else '○'} {k}")
        return
    if "created" in result:
        print(f"✅ 知识库已创建：{result['created']}")
        print(f"   用 matlens kb switch {result['created']} 激活，或直接 create 后 add 文献")
        return
    if "deleted" in result:
        print(f"🗑️  已删除知识库：{result['deleted']}")
        return
    if "active" in result:
        print(f"✅ 当前激活知识库：{result['active']}")
        return
    if "ok" in result:
        print(f"📥 导入完成：成功 {result['ok']}，跳过 {result['skipped']}")
        for item in result.get("items", []):
            if item.get("skipped"):
                print(f"   ⏭️  {item.get('source')}（已存在）")
            else:
                print(f"   ✅ {item.get('source')}：{item.get('chunks')} 个分块")
        for err in result.get("errors", []):
            print(f"   ❌ {err['path']}：{err['error']}")
        return
    if "hits" in result:
        print(f"📖 检索「{result.get('question', result.get('query', ''))}」→ 命中 {result.get('count', len(result.get('hits', [])))} 条")
        for i, h in enumerate(result["hits"], 1):
            print(f"  [{i}] （来源：{h['source']}，相关度 {h.get('score', '-')}）")
            print(f"      {h['text'][:120]}{'…' if len(h['text']) > 120 else ''}")
        return
    if "name" in result and "chunks" in result:
        print(f"📚 知识库 {result['name']}：{result['docs']} 篇文献 / {result['chunks']} 个分块")
        print(f"   目录：{result['dir']}")
        return
    print(json.dumps(result, ensure_ascii=False, indent=2))


def build_kb_parser(subparsers) -> None:
    """注册 ``matlens kb`` 子命令（Hermes subcommands 扩展机制）。"""
    parser = subparsers.add_parser(
        "kb",
        help="MatLens 本地文献知识库管理（create/switch/add/ask/list/delete/stats）",
        description="本地文献知识库：FAISS 向量检索，数据存 ~/.matlens/knowledge/",
    )
    parser.add_argument(
        "kb_cmd",
        nargs="?",
        choices=["list", "create", "switch", "delete", "add", "ask", "stats"],
        help="子命令",
    )
    parser.add_argument("kb_args", nargs="*", help="子命令参数（如 知识库名 / 文件路径 / 问题）")
    parser.set_defaults(func=cmd_kb)
