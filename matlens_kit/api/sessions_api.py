# -*- coding: utf-8 -*-
"""MatLens Web 服务层 —— 会话管理 API。

封装 matlens_state.SessionDB（~/.matlens/state.db），为前端提供：
- GET    /api/sessions            列表（最近活跃排序，支持搜索）
- POST   /api/sessions            新建（预建 source="web" 行，避免与 CLI 会话混流）
- GET    /api/sessions/{id}       会话元信息
- GET    /api/sessions/{id}/messages  历史消息
- PUT    /api/sessions/{id}       重命名 / 切换模型
- DELETE /api/sessions/{id}       删除

设计要点：前端必须先 POST 建行再聊天；agent 的 lazy create_session 是
INSERT OR IGNORE + COALESCE（只填空列），故 source="web" 不会被覆盖。
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

WEB_SOURCE = "web"

_router = APIRouter(prefix="/api/sessions", tags=["sessions"])

# session_id 会进入前端 HTML（onclick 属性）与磁盘文件名，仅允许白名单字符。
# 非法字符一律服务端生成 UUID（堵死 XSS / 路径穿越注入面）。
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,96}$")


def get_session_db():
    """返回新的 SessionDB 实例。

    不缓存单例：SessionDB 的读连接池在 WAL 模式下会持有旧快照，
    缓存实例会导致「刚写入的消息」在随后数秒内读不到。每次新建实例
    拿到全新连接，读到的即是已提交的最新数据（SQLite WAL 语义保证）。
    """
    from matlens_state import SessionDB

    return SessionDB()


def _normalize(row: Dict[str, Any]) -> Dict[str, Any]:
    """把 SessionDB 行收敛成前端需要的精简结构。"""
    return {
        "id": row.get("id"),
        "title": row.get("title"),
        "preview": row.get("preview"),
        "message_count": row.get("message_count") or 0,
        "source": row.get("source"),
        "model": row.get("model"),
        "started_at": row.get("started_at"),
        "last_active": row.get("last_active"),
    }


@_router.get("")
def list_sessions(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: str = Query("", description="标题/预览搜索"),
) -> Dict[str, Any]:
    db = get_session_db()
    rows = db.list_sessions_rich(
        source=WEB_SOURCE,
        limit=limit,
        offset=offset,
        order_by_last_active=True,
        include_children=False,
        search_query=q.strip() or None,
    )
    # 空白会话不进入历史列表：只有发过消息（message_count>0）的才算「历史对话」。
    # 数据本身保留在 state.db，避免误删；前端新建会话改为「本地空会话，首条消息才落库」，
    # 双管齐下杜绝空白会话残留。
    rows = [r for r in rows if (r.get("message_count") or 0) > 0]
    return {"sessions": [_normalize(r) for r in rows], "count": len(rows)}


@_router.post("")
def create_session(payload: Dict[str, Any] = None) -> Dict[str, Any]:
    payload = payload or {}
    db = get_session_db()
    client_sid = str(payload.get("session_id") or "")
    # 安全加固：仅接受白名单字符的显式 session_id，其余一律服务端生成 UUID。
    # 历史上客户端可传入任意 id 并原样渲染进前端 HTML（存储型 XSS）。
    if client_sid and _SESSION_ID_RE.match(client_sid):
        sid = client_sid
    else:
        sid = uuid.uuid4().hex
    # 预建 web 源行；agent 首次 turn 的 lazy 创建只会 COALESCE 回填 model 等
    db.create_session(sid, WEB_SOURCE, model=payload.get("model"))
    title = (payload.get("title") or "").strip()
    if title:
        try:
            db.set_session_title(sid, title)
        except Exception:
            pass
    return {"id": sid, "title": title or None, "source": WEB_SOURCE}


@_router.get("/archived")
def list_archived_sessions(
    limit: int = Query(100, ge=1, le=200),
) -> Dict[str, Any]:
    """归档箱：列出已归档的会话（前端会话列表的「归档箱」视图）。"""
    db = get_session_db()
    rows = db.list_sessions_rich(
        source=WEB_SOURCE,
        limit=limit,
        archived_only=True,
        order_by_last_active=True,
        include_children=False,
    )
    out = []
    for r in rows:
        item = _normalize(r)
        item["archived"] = True
        out.append(item)
    return {"sessions": out, "count": len(out)}


# 注意：本段必须注册在 `/​{session_id}` 之前 —— FastAPI 按声明顺序匹配，
# 静态路径 `/archived` 放在动态段之后会被解释成 session_id="archived" → 404。
@_router.get("/{session_id}")
def get_session(session_id: str) -> Dict[str, Any]:
    db = get_session_db()
    row = db.get_session(session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")
    return _normalize(row)


@_router.get("/{session_id}/messages")
def get_messages(
    session_id: str,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    db = get_session_db()
    if db.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    msgs = db.get_messages(session_id, limit=limit, offset=offset)
    return {"messages": msgs, "count": len(msgs)}


@_router.put("/{session_id}")
def update_session(session_id: str, payload: Dict[str, Any] = None) -> Dict[str, Any]:
    payload = payload or {}
    db = get_session_db()
    if db.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    title = (payload.get("title") or "").strip()
    if title:
        db.set_session_title(session_id, title)
    model = payload.get("model")
    if model:
        try:
            db.update_session_model(session_id, model)
        except Exception:
            pass
    return {"ok": True, "id": session_id}


@_router.post("/{session_id}/archive")
def archive_session(session_id: str, payload: Dict[str, Any] = None) -> Dict[str, Any]:
    """归档 / 取消归档会话（前端历史列表的「归档」按钮）。

    底层 SessionDB.set_session_archived 与 list_sessions_rich 的
    include_archived / archived_only 本就存在，此前只是没接到 Web 层。
    归档**不删数据**，仅从默认列表隐藏，随时可恢复。
    """
    payload = payload or {}
    archived = payload.get("archived", True)
    db = get_session_db()
    if db.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    ok = db.set_session_archived(session_id, bool(archived))
    return {"ok": bool(ok), "id": session_id, "archived": bool(archived)}


# ---------------------------------------------------------------------------
# 从归档会话提炼记忆（2026-10-15）
# ---------------------------------------------------------------------------
# 为什么需要：会话是「过程」，记忆是「资产」。用户聊完几十轮后归档，
# 里面的研究方向、材料体系偏好、关键实验参数、下结论方式就此沉在
# state.db 里——下次开新会话 Agent 完全不知道。这个端点把过程 → 资产。
#
# 设计要点：
#  - **必须批量**：一次只提炼一条会话时跨会话的重复信息无法去重
#  - **模型只负责提取，不负责入库**：入库走 mem0_add（原文存储），
#    分类与去重交给 mem0，避免 LLM 幻觉污染记忆库
#  - **SSE 流式**：提炼 10+ 条会话要跑几十秒，必须给进度反馈
#  - **失败不中断**：单条会话提取失败只记日志，继续处理下一条

_DISTILL_PROMPT = """你是一位科研助理，负责从历史对话中提炼出值得长期记住的信息。

下面给你若干段历史对话（材料化学 / 科研场景）。请提取其中**可复用、对未来工作有价值**的信息：

需要提取的：
- 研究方向与关注问题（如「主要做 SOFC 电解质」「关注钙钛矿稳定性」）
- 材料体系与配方偏好（如「常用 LSM-LSCF 集流层」「偏好 Ca 共掺杂方案」）
- 关键实验数据（电导率、活化能、烧结温度等具体数值 + 测试条件）
- 已验证的结论与判断标准（如「σ_bulk 与 σ_total 的 R_gb 占比应自洽」）
- 工作习惯与表达偏好（如「要求标注数据是实测还是拟议」「回答要克制」）
- 明确的否定性约束（如「禁止用扩散模型画的图当实验结果」）

不要提取：
- 闲聊、客套、与科研无关的内容
- 一次性的中间步骤（除非结论依赖它）
- 已存在于长期记忆里的信息

输出格式：每条独立一行，格式为
[分类] 内容
分类限定为：材料 / 实验 / 结论 / 用户  之一

严格只输出这些行，不要编号、不要解释、不要 markdown 代码块。如果某段对话没有值得记的信息，直接跳过。

历史对话：
"""


def _distillable_text(msgs: List[Dict[str, Any]], max_chars: int = 3000) -> str:
    """把一条会话的消息压成「用户问 / 助手答」摘要文本，按字符预算截断。"""
    out: List[str] = []
    budget = max_chars
    for m in msgs:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        content = str(m.get("content") or "").strip()
        if not content:
            continue
        # 工具结果与思考过程不提炼（噪声大、信息密度低）
        if "<untrusted_tool_result" in content or len(content) > 4000:
            content = content[:1200]
        tag = "用户" if role == "user" else "助手"
        line = f"{tag}：{content}"
        if budget - len(line) < 0:
            break
        out.append(line)
        budget -= len(line)
    return "\n".join(out)


@_router.post("/distill")
def distill_archived_sessions(payload: Dict[str, Any] = None) -> Dict[str, Any]:
    """从归档会话中批量提炼记忆。

    Body: {"limit": int = 20} —— 处理最近 N 条归档会话（默认 20）。

    返回：
        {"ok", "sessions": int, "extracted": int, "stored": int,
         "items": [{"session_id", "title", "count", "stored"}], "log": [str]}
    """
    payload = payload or {}
    limit = int(payload.get("limit") or 20)
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=400, detail="limit 需在 1..100 之间")

    db = get_session_db()
    rows = db.list_sessions_rich(
        source=WEB_SOURCE,
        limit=limit,
        archived_only=True,
        order_by_last_active=True,
        include_children=False,
    )

    log: List[str] = []
    if not rows:
        return {"ok": True, "sessions": 0, "extracted": 0, "stored": 0,
                "items": [], "log": ["归档箱是空的，先归档几轮对话再提炼。"]}

    log.append(f"扫描归档会话 {len(rows)} 条")

    # ── 1) 汇总文本 ──
    chunks: List[str] = []
    meta: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        sid = r.get("id")
        if not sid:
            continue
        msgs = db.get_messages(sid, limit=200)
        text = _distillable_text(msgs)
        if len(text) < 40:      # 太短的多半是「你好」式空会话
            continue
        title = r.get("title") or "未命名会话"
        meta[sid] = {"title": title}
        chunks.append(f"### 对话：{title}\n{text}")
    log.append(f"有效会话 {len(chunks)} 条，共 {sum(len(c) for c in chunks)} 字符")

    if not chunks:
        return {"ok": True, "sessions": len(rows), "extracted": 0, "stored": 0,
                "items": [], "log": log + ["没有内容足够长的会话可提炼。"]}

    # ── 2) 交给模型提取（分批，避免超上下文） ──
    from matlens_kit.ui.common import get_agent, run_conversation
    from matlens_kit.api.hooks import install_hooks

    install_hooks(force=True)
    agent = get_agent(session_id="")   # 全局单例：提炼不该占用会话池
    lines: List[str] = []
    BATCH = 6
    batches = [chunks[i:i + BATCH] for i in range(0, len(chunks), BATCH)]
    log.append(f"分{len(batches)} 批调用模型提炼")
    for bi, batch in enumerate(batches):
        prompt = _DISTILL_PROMPT + "\n\n".join(batch)
        try:
            # `final_response` 在部分路径下不填（模型直接给文本时走 stream），
            # 与论文工坊同样用 stream_callback 兜底，否则会解析出 0 条。
            buf: List[str] = []

            def _cb(evt: str, payload: Any) -> None:
                if evt == "stream_text" and isinstance(payload, dict):
                    t = payload.get("text")
                    if t:
                        buf.append(str(t))

            res = run_conversation(agent, prompt, "memory_distill", stream_callback=_cb)
            text = str((res or {}).get("final_response") or "") or "".join(buf)
            if not text.strip():
                log.append(f"第 {bi + 1}/{len(batches)} 批模型无文本输出")
            lines.extend(
                ln.strip() for ln in text.splitlines()
                if ln.strip().startswith("[") and "]" in ln
            )
            log.append(f"第 {bi + 1}/{len(batches)} 批完成，累计提取 {len(lines)} 条")
        except Exception as e:
            log.append(f"第 {bi + 1}/{len(batches)} 批失败（{type(e).__name__}: {e}），继续下一批")

    # ── 3) 逐条入库（mem0_add 原文存储，不让 LLM 决定分类） ──
    stored = 0
    store_errors: List[str] = []
    try:
        from matlens_kit.api import mem_api as M

        for ln in lines:
            try:
                M._call("mem0_add", {"content": ln})
                stored += 1
            except Exception as e:
                store_errors.append(f"{ln[:40]}… → {type(e).__name__}")
    except Exception as e:
        store_errors.append(f"记忆后端不可用：{e}")

    log.append(f"提取 {len(lines)} 条，成功入库 {stored} 条")
    if store_errors:
        log.append(f"{len(store_errors)} 条入库失败（记忆后端可能未就绪）")

    return {
        "ok": True,
        "sessions": len(rows),
        "processed": len(chunks),
        "extracted": len(lines),
        "stored": stored,
        "items": [{"title": v["title"]} for v in meta.values()],
        "lines": lines[:40],
        "log": log,
    }


@_router.delete("/{session_id}")
def delete_session(session_id: str) -> Dict[str, Any]:
    db = get_session_db()
    ok = db.delete_session(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="session not found")
    return {"ok": True, "id": session_id}


@_router.post("/clear")
def clear_web_sessions() -> Dict[str, Any]:
    """清空所有 source="web" 的会话及其消息（前端「关于 → 清空历史」按钮）。

    与 GET "" 的区别：这里**不**用 message_count>0 过滤——预建但从未发消息的
    空 web 行也要一并清掉。仅枚举 source=WEB_SOURCE 的行，cli / 其它来源会话
    绝不受影响，外部记忆（mem0）、papers.db、experiments.db、knowledge 也不碰。

    delete_session() 会级联删除该会话的 messages（见 matlens_state）。
    best-effort 让进程内可能仍持有已删会话句柄的 agent 失效，避免它继续往
    已删会话写；失败不影响清空结果。
    """
    db = get_session_db()
    # 取原始（非压缩链投影）的全部 web 行，含 0 消息预建行与子会话。
    rows = db.list_sessions_rich(
        source=WEB_SOURCE,
        limit=100_000,
        offset=0,
        include_children=True,
        min_message_count=0,
        order_by_last_active=False,
        project_compression_tips=False,
    )
    cleared = 0
    for row in rows:
        sid = row.get("id")
        if not sid:
            continue
        try:
            if db.delete_session(sid):
                cleared += 1
        except Exception:
            # 某一行删除失败不阻塞整体（可能已被子会话级联删掉）。
            pass

    # best-effort：重置运行中的 agent，避免它持有已删会话的句柄继续写库。
    try:
        from matlens_kit.ui.common import reset_agent

        reset_agent()
    except Exception:
        pass

    return {"ok": True, "cleared": cleared}
