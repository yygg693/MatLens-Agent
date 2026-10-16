"""MatLens 本地文献知识库插件（matlens-local-rag）。

- 注册 `rag_search` 工具：对话中检索当前知识库相关文献片段；
- 通过 /kb 系列命令管理知识库（create/list/switch/add/ask/delete）；
- 所有数据存 ~/.matlens/knowledge/，嵌入复用主 provider（OpenAI 兼容端点）。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from tools.registry import registry, tool_result

from matlens_kit.rag import KnowledgeManager


def _build_manager() -> KnowledgeManager:
    """按 kb 设置（embed_model）+ 主 provider 环境端点构建知识库管理器。

    - embed_model=local：强制本地哈希嵌入（不传 base_url/api_key，
      Embedder 走 _local_embed，384 维确定性向量，离线可用）；
    - text-embedding-3-small/large：用对应模型名 + 现有 provider 的
      base_url/api_key 构造远程 Embedder（保留探活失败降级本地逻辑）。
    """
    from matlens_kit import settings_store

    kb = settings_store.get_section("kb")
    embed_model = kb.get("embed_model", "local")
    base_url = os.environ.get("MATLENS_EMBED_BASE_URL") or os.environ.get("OPENAI_BASE_URL", "")
    api_key = os.environ.get("MATLENS_EMBED_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
    if embed_model == "local":
        return KnowledgeManager(base_url="", api_key="", embed_model="local")
    return KnowledgeManager(base_url=base_url, api_key=api_key, embed_model=embed_model)


# 模块级单例（会话内复用，避免重复探活）；_manager_key 记录其构建快照
_manager: Optional[KnowledgeManager] = None
_manager_key: Optional[tuple] = None


def reset_manager() -> None:
    """清空单例（测试/设置变更后强制下次重建）。"""
    global _manager, _manager_key
    _manager = None
    _manager_key = None


def get_manager() -> KnowledgeManager:
    """返回管理器单例；embed_model / root 变化时按新设置重建。

    FAISS index 维度在新建库时固定，故只对「新建库 / 新导入」生效——
    重建后新构造的 KnowledgeBase 用新 embedder，不回写旧库向量维度。
    chunk_size / chunk_overlap / table_extract 不在此缓存键里：它们在
    导入/解析时刻由 kb.py 实时读 settings，无需重建管理器。
    """
    global _manager, _manager_key
    try:
        from matlens_kit import settings_store

        kb = settings_store.get_section("kb")
    except Exception:
        kb = {}
    key = (kb.get("embed_model", "local"), kb.get("root"))
    if _manager is None or _manager_key != key:
        _manager = _build_manager()
        _manager_key = key
    return _manager


# ─────────────────────────────────────────────────────────────
# rag_search 工具
# ─────────────────────────────────────────────────────────────
def rag_search_tool(
    query: str,
    kb: Optional[str] = None,
    top_k: int = 5,
    **kwargs: Any,
) -> Dict[str, Any]:
    """在本地文献知识库中检索相关内容片段。

    Args:
        query: 检索问题/关键词。
        kb: 知识库名（默认当前激活库）。
        top_k: 返回片段数（1-10）。

    Returns:
        命中的文献片段列表（含来源文件名与相似度）。
    """
    try:
        manager = get_manager()
        kbase = manager.get(kb)
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"知识库初始化失败：{exc}"}
    try:
        hits = kbase.query(query, top_k=max(1, min(top_k, 10)))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"检索失败：{exc}"}
    if not hits:
        return {"kb": kbase.name, "query": query, "hits": [], "message": "未命中相关文献片段"}
    return {"kb": kbase.name, "query": query, "hits": hits, "count": len(hits)}


RAG_SEARCH_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "检索问题或关键词（如：二氧化钛的带隙是多少）"},
        "kb": {"type": "string", "description": "知识库名称（可选，默认当前激活库）"},
        "top_k": {"type": "number", "description": "返回片段数 1-10（默认 5）"},
    },
    "required": ["query"],
    "additionalProperties": False,
}


# ─────────────────────────────────────────────────────────────
# /kb 命令处理
# ─────────────────────────────────────────────────────────────
def handle_kb_command(args: List[str]) -> Dict[str, Any]:
    """处理 /kb 系列命令。

    /kb list | /kb create <name> | /kb switch <name> | /kb delete <name>
    /kb add <file...> | /kb ask <question> | /kb stats
    """
    if not args:
        return {"error": "用法：/kb list|create|switch|delete|add|ask|stats", "help": True}
    cmd = args[0].lower()
    try:
        manager = get_manager()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"知识库初始化失败：{exc}"}
    if cmd == "list":
        kbs = manager.list_kbs()
        return {"knowledge_bases": kbs, "active": manager.active,
                "tip": "当前激活库用 /kb switch <name> 切换"}
    if cmd == "create" and len(args) >= 2:
        return manager.create(args[1])
    if cmd == "switch" and len(args) >= 2:
        return manager.switch(args[1])
    if cmd == "delete" and len(args) >= 2:
        return manager.delete(args[1])
    if cmd == "add" and len(args) >= 2:
        paths = args[1:]
        missing = [p for p in paths if not os.path.exists(p)]
        if missing:
            return {"error": f"文件不存在：{', '.join(missing)}"}
        try:
            kbase = manager.get()
        except ValueError as exc:
            return {"error": str(exc), "hint": "先 /kb create <name> 再 /kb switch <name> 激活"}
        return kbase.add_documents(paths)
    if cmd == "ask" and len(args) >= 2:
        question = " ".join(args[1:])
        try:
            kbase = manager.get()
        except ValueError as exc:
            return {"error": str(exc)}
        hits = kbase.query(question)
        if not hits:
            return {"kb": kbase.name, "question": question, "hits": [],
                    "answer": "知识库中未检索到相关内容，请先 /kb add 导入文献。"}
        context = "\n\n".join(f"[{i + 1}]（来源：{h['source']}）{h['text']}" for i, h in enumerate(hits))
        return {"kb": kbase.name, "question": question, "count": len(hits),
                "context": context, "hits": hits}
    if cmd == "stats":
        try:
            kbase = manager.get()
            return kbase.stats()
        except ValueError as exc:
            return {"error": str(exc), "knowledge_bases": manager.list_kbs()}
    return {"error": f"未知 /kb 子命令：{cmd}（支持 list/create/switch/delete/add/ask/stats）"}


# ─────────────────────────────────────────────────────────────
# 注册
# ─────────────────────────────────────────────────────────────
def _check_rag_available() -> bool:
    return True


registry.register(
    name="rag_search",
    toolset="matlens_material",
    schema=RAG_SEARCH_SCHEMA,
    handler=lambda args, **kw: tool_result(rag_search_tool(
        query=args.get("query", ""), kb=args.get("kb"), top_k=args.get("top_k", 5))),
    check_fn=_check_rag_available,
    description="在本地文献知识库中检索相关内容片段（多知识库，支持 PDF/TXT/MD 导入，返回来源标注）",
    emoji="📖",
)

# 暴露 /kb 命令处理器（供 CLI 命令接入）
KB_COMMAND_HANDLER = handle_kb_command
