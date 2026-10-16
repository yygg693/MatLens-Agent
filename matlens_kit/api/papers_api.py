# -*- coding: utf-8 -*-
"""论文工坊 · HTTP API（同进程调 engine，SSE 流式）。

- POST   /api/papers                 建项目
- GET    /api/papers                 项目列表
- GET    /api/papers/{pid}           项目详情（7 步状态 + 产物）
- PUT    /api/papers/{pid}           改标题/主题
- DELETE /api/papers/{pid}           删除项目
- POST   /api/papers/{pid}/save      {stage, content, refs} 手动编辑保存（断点续写）
- POST   /api/papers/{pid}/run/{stage}  执行某步（SSE 流式：agent 生成）
- GET    /api/papers/{pid}/export/{fmt} 导出（md/tex）
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from matlens_kit.paper.engine import PaperEngine, STAGES, STAGE_LABELS
from matlens_kit.paper.prompts import render_prompt, refs_text
from matlens_kit.paper.engine import PAPER_TYPES
from matlens_kit.paper import db as PDB

_router = APIRouter(prefix="/api/papers", tags=["papers"])

#: 图件文件名：fig_{序号}_{谱系或类型}.{png,pdf,svg}
_FIG_FILE_RE = re.compile(r"^fig_\d+_[A-Za-z_]+\.(png|pdf|svg)$", re.IGNORECASE)

_engine = PaperEngine()

# agent 单例非并发安全：论文步骤生成必须全局串行（同一时间只跑一个生成线程）
import threading as _threading
_PAPER_RUN_LOCK = _threading.Lock()

#: 生成取消标志：key = f"{pid}:{stage}" -> threading.Event（用户停止生成时置位）
_PAPER_CANCEL: Dict[str, _threading.Event] = {}
_PAPER_CANCEL_LOCK = _threading.Lock()


class PaperCancelled(Exception):
    """论文步骤生成被用户取消。"""


def _get_engine() -> PaperEngine:
    # P2 起注入 agent 流式 runner（见 run_stage 的 runner 装配）
    return _engine


def _papers_settings() -> Dict[str, Any]:
    """实时读 settings papers 段（生成/导出动作发生时刻读，不缓存）。"""
    try:
        from matlens_kit import settings_store

        return settings_store.get_section("papers")
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class PaperCreate(BaseModel):
    title: str
    paper_type: str = "research"
    topic: str = ""


class PaperUpdate(BaseModel):
    title: Optional[str] = None
    topic: Optional[str] = None


class StageSave(BaseModel):
    stage: str
    content: str = ""
    refs: Optional[list] = None


class PaperDataIn(BaseModel):
    """实验数据录入（学术诚信：proposed 拟议 / measured 实测）。

    data 任意 dict，约定 schema：
    {"status": "proposed"|"measured", "notes": str, "tables": [...], "updated_at": str}
    """

    data: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@_router.post("")
def create_paper(req: PaperCreate) -> Dict[str, Any]:
    title = (req.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title 必填")
    return _get_engine().create(title, req.paper_type, (req.topic or "").strip())


@_router.get("")
def list_papers() -> Dict[str, Any]:
    return {"ok": True, "papers": _get_engine().list(), "stages": list(STAGES), "stage_labels": STAGE_LABELS}


@_router.get("/{pid}")
def get_paper(pid: str) -> Dict[str, Any]:
    p = _get_engine().get(pid)
    if p is None:
        raise HTTPException(status_code=404, detail="论文项目不存在")
    return p


@_router.put("/{pid}")
def update_paper(pid: str, req: PaperUpdate) -> Dict[str, Any]:
    if PDB.get_paper(pid) is None:
        raise HTTPException(status_code=404, detail="论文项目不存在")
    PDB.update_meta(pid, title=(req.title or "").strip() or None, topic=(req.topic or "").strip() or None)
    return {"ok": True, **PDB.get_paper(pid)}


@_router.delete("/{pid}")
def delete_paper(pid: str) -> Dict[str, Any]:
    ok = PDB.delete_paper(pid)
    if not ok:
        raise HTTPException(status_code=404, detail="论文项目不存在")
    return {"ok": True, "deleted": pid}


@_router.post("/{pid}/save")
def save_stage(pid: str, req: StageSave) -> Dict[str, Any]:
    """手动编辑/保存某步产物（断点续写入口）。"""
    if req.stage not in STAGES:
        raise HTTPException(status_code=400, detail=f"未知阶段：{req.stage}")
    if PDB.get_paper(pid) is None:
        raise HTTPException(status_code=404, detail="论文项目不存在")
    s = PDB.save_stage_content(pid, req.stage, req.content, req.refs)
    # 手动保存内容即视为完成该步（否则前置检查永远卡住，无法推进流程）
    if (req.content or "").strip():
        try:
            PDB.set_stage_status(pid, req.stage, "done", error="")
        except Exception:
            pass
    return {"ok": True, "stage": req.stage, "saved": s}


@_router.post("/{pid}/data")
def save_paper_data(pid: str, req: PaperDataIn) -> Dict[str, Any]:
    """保存实验数据（学术诚信：标注 proposed 拟议 / measured 实测）。

    GET /api/papers/{pid} 已随全量返回 data 字段，本端点仅负责写入。
    """
    if PDB.get_paper(pid) is None:
        raise HTTPException(status_code=404, detail="论文项目不存在")
    try:
        saved = PDB.save_paper_data(pid, req.data)
    except KeyError:
        raise HTTPException(status_code=404, detail="论文项目不存在")
    except TypeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "data": saved}


@_router.post("/{pid}/run/{stage}")
async def run_stage(pid: str, stage: str) -> StreamingResponse:
    """执行某步（SSE 实时流式）。

    生成在独立线程运行（emit → asyncio.Queue），SSE 边生成边推送——
    与 chat 端点同一模式。topic/search/outline/write 走 agent 流式；其余占位。
    """
    import asyncio
    import queue as _queue
    import threading

    if stage not in STAGES:
        raise HTTPException(status_code=400, detail=f"未知阶段：{stage}")
    paper = PDB.get_paper(pid)
    if paper is None:
        raise HTTPException(status_code=404, detail="论文项目不存在")

    # 标准库 queue.Queue 线程安全（asyncio.Queue 非线程安全会丢事件）
    q: "_queue.Queue[Dict[str, Any]]" = _queue.Queue()
    _cancel_key = f"{pid}:{stage}"
    with _PAPER_CANCEL_LOCK:
        _PAPER_CANCEL[_cancel_key] = _threading.Event()

    def emit(etype: str, data: Dict[str, Any]) -> None:
        q.put({"type": etype, "data": data})

    def _work() -> None:
        done_flag = threading.Event()

        def watchdog() -> None:
            if not done_flag.is_set():
                try:
                    PDB.set_stage_status(pid, stage, "pending", "生成超时（15 分钟），已重置待重跑")
                except Exception:
                    pass
                q.put({"type": "error", "data": {"message": "生成超时，已重置待重跑"}})

        timer = threading.Timer(900.0, watchdog)  # 15 分钟兜底
        timer.start()
        try:
            eng = PaperEngine(runner=_make_agent_runner(pid, cancel_key=_cancel_key))
            result = eng.run_stage(pid, stage, emit=emit)
            q.put_nowait({"type": "done", "data": result})
        except Exception as e:  # noqa: BLE001
            q.put_nowait({"type": "error", "data": {"message": str(e)[:300]}})
        finally:
            done_flag.set()
            timer.cancel()
            with _PAPER_CANCEL_LOCK:
                _PAPER_CANCEL.pop(_cancel_key, None)

    threading.Thread(target=_work, daemon=True, name=f"paper-{stage}-{pid[:8]}").start()

    async def _gen():
        try:
            yield f"data: {__import__('json').dumps({'type': 'turn_start', 'data': {'stage': stage}}, ensure_ascii=False)}\n\n"
            while True:
                try:
                    ev = q.get_nowait()
                except _queue.Empty:
                    yield ": keepalive\n\n"
                    await asyncio.sleep(0.5)
                    continue
                yield f"data: {__import__('json').dumps(ev, ensure_ascii=False)}\n\n"
                if ev["type"] in ("done", "error"):
                    break
        finally:
            # 客户端断开/异常 → 通知 worker 中断 agent（用户停止生成）
            try:
                _PAPER_CANCEL.get(_cancel_key, None).set()
            except Exception:
                pass

    return StreamingResponse(_gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


def _make_agent_runner(pid: str, cancel_key: Optional[str] = None):
    """构造 agent 流式 runner（生成在请求线程外执行）。"""

    def _runner(stage_: str, pid_: str, ctx: Dict[str, Any], cb) -> tuple:
        # ── search 步：双通道检索（RAG 本地库 + OpenAlex 网络）+ LLM 文献总览 ──
        if stage_ == "search":
            from matlens_kit.paper.search import run_dual_search, render_refs
            from matlens_kit.api.hooks import install_hooks as _ih
            from matlens_kit.ui.common import get_agent as _ga
            from matlens_state import SessionDB as _SDB

            p = PDB.get_paper(pid_)
            topic = p.get("topic") or p.get("title", "")
            cb("stream_text", {"text": f"🔍 双通道检索中（RAG 本地库 + OpenAlex 网络）…\n"})
            res = run_dual_search(topic, top_k=8)
            refs = res.get("refs", [])
            cb("stream_text", {"text": f"✓ 检索完成：本地 {res.get('local_count', 0)} 条 + 网络 {res.get('count', 0)} 条（去重后 {res.get('count', 0)} 条核验文献）\n\n"})
            cb("stream_text", {"text": render_refs(refs) + "\n\n"})

            # ── 2026-10-16：补抓正文 ──
            # 检索只拿到题录（题名/作者/DOI），写作时需要的是原文 ——
            # 只有题录时 LLM 只能编。这里对前几篇补抓正文（本地库优先，
            # 其次 OA 链接，最后 Unpaywall 按 DOI 解析），拿不到的如实留空。
            fulltext_block = ""
            try:
                from matlens_kit.paper.search_enrich import enrich_refs, render_fulltext_notes

                cb("stream_text", {"text": "📄 抓取文献正文（本地库 → 开放获取 → Unpaywall 解析）…\n"})
                en = enrich_refs(refs, max_refs=6)
                refs = en.get("refs", refs)
                fulltext_block = render_fulltext_notes(refs)
                cb("stream_text", {
                    "text": (f"✓ 正文抓取：{en.get('with_text', 0)}/{en.get('with_text', 0) + en.get('without_text', 0)} "
                             f"篇拿到原文（{en.get('elapsed_s', 0)}s）\n\n")
                })
                if not fulltext_block:
                    cb("stream_text", {
                        "text": "⚠️ 未取到任何正文（多为出版商付费墙 / 无合法开放版本）。"
                                "本次文献总览仅基于题录，引用前请自行核实。\n\n"
                    })
            except Exception as e:  # noqa: BLE001
                cb("stream_text", {"text": f"⚠️ 正文抓取跳过：{type(e).__name__}\n\n"})

            # LLM 生成文献总览（基于白名单）—— 独立会话级 agent，避免与其他对话/论文并发踩踏
            paper_sid = f"paper_{pid_[:12]}"
            agent = _ga(session_id=paper_sid, model="deepseek-chat", provider="deepseek")
            if getattr(agent, "_session_db", None) is None:
                agent._session_db = _SDB()
                agent._session_db_created = False
            _ih(force=True)
            _cancel_ev = _PAPER_CANCEL.get(cancel_key, None) if cancel_key else None
            if _cancel_ev is not None:
                def _watch_cancel() -> None:
                    _cancel_ev.wait()
                    try:
                        agent.interrupt()
                    except Exception:
                        pass
                _threading.Thread(target=_watch_cancel, daemon=True, name=f"paper-cancel-{paper_sid[:8]}").start()
            _papers = _papers_settings()
            # 2026-10-16：把抓到的原文片段一并给 LLM。
            # 只有题录时模型会「凭印象补全」别人的结论 —— 那是最危险的引用污染，
            # 所以有正文才给；没有就明确告诉它只能基于题录。
            refs_payload = refs_text(refs)
            if fulltext_block:
                refs_payload = refs_payload + "\n\n" + fulltext_block
            else:
                refs_payload += ("\n\n⚠️ 本次未取到任何文献正文（多为出版商付费墙或无合法开放版本）。"
                                 "请仅基于题录给出概览，**不要推测文献的具体结论或数据**；"
                                 "需要引用具体结论时，请提示用户补充 PDF。")
            prompt = render_prompt("search", {
                "topic": topic,
                "paper_type": PAPER_TYPES.get(p.get("paper_type", "research"), "研究论文"),
                "refs_text": refs_payload,
                "tone": _papers.get("tone", "formal"),
                "cite_style": _papers.get("cite_style", "gb7714"),
            })
            texts: list = []

            def _scb(t: str) -> None:
                texts.append(t)
                cb("stream_text", {"text": t})

            with _PAPER_RUN_LOCK:
                result = run_conversation_guarded(agent, prompt, paper_sid, _scb)
            if _cancel_ev is not None and _cancel_ev.is_set():
                raise PaperCancelled("生成已取消")
            # 优先用 run_conversation 返回值（stream_callback 在核心链路未接线时兜底）
            final = (result or {}).get("final_response") or "".join(texts) or ""
            _guard(final, stage_)   # ← search 步同样要拦（欠费时总览也拿不到）
            content = render_refs(refs) + "\n\n" + final
            return content, refs
        # ── quality 步：自研三维巡检（本地规则，秒级） ──
        if stage_ == "quality":
            from matlens_kit.paper.quality import check_quality, render_report
            p = PDB.get_paper(pid_)
            draft = (p["stages"].get("write", {}) or {}).get("content", "")
            refs = (p["stages"].get("search", {}) or {}).get("refs") or []
            check = check_quality(draft, refs)
            report = render_report(check)
            cb("stream_text", {"text": report})
            return report, []
        # ── export 步：二期完善（md 已可直接导出） ──
        if stage_ == "export":
            return f"（{STAGE_LABELS.get(stage_, stage_)} 待完善：Markdown 已可用，LaTeX/Word 二期）", []
        from matlens_kit.api.hooks import install_hooks
        from matlens_kit.ui.common import get_agent
        from matlens_state import SessionDB

        # 落库前守卫：上游欠费/鉴权失败时 agent 会把错误文本塞进 final_response，
        # 不拦住会静默覆盖用户已有正文（见 paper/guard.py 模块文档）
        from matlens_kit.paper.guard import ensure_not_error as _guard

        paper_sid = f"paper_{pid_[:12]}"
        agent = get_agent(session_id=paper_sid, model="deepseek-chat", provider="deepseek")
        if getattr(agent, "_session_db", None) is None:
            agent._session_db = SessionDB()
            agent._session_db_created = False
        install_hooks(force=True)

        _cancel_ev = _PAPER_CANCEL.get(cancel_key, None) if cancel_key else None
        if _cancel_ev is not None:
            def _watch_cancel() -> None:
                _cancel_ev.wait()
                try:
                    agent.interrupt()
                except Exception:
                    pass
            _threading.Thread(target=_watch_cancel, daemon=True, name=f"paper-cancel-{paper_sid[:8]}").start()

        p = PDB.get_paper(pid_)
        st = p["stages"]
        refs_list = st.get("search", {}).get("refs") or []
        from matlens_kit.paper.enforce_refs import inject_whitelist
        _papers = _papers_settings()
        ctx = {
            "topic": p.get("topic") or p.get("title", ""),
            "paper_type": PAPER_TYPES.get(p.get("paper_type", "research"), "研究论文"),
            "topic_content": st.get("topic", {}).get("content", ""),
            "outline_text": st.get("outline", {}).get("content", ""),
            "section": "全文",
            "word_count": "3000",
            "section_points": "",
            "existing_text": "",
            "continuation": "",
            "draft_text": st.get("write", {}).get("content", ""),
            "tone": _papers.get("tone", "formal"),
            "cite_style": _papers.get("cite_style", "gb7714"),
            # 实验数据（proposed/measured）；渲染由 prompts.py 负责，未录入为 None
            "experimental_data": p.get("data"),
        }
        # 写前注入引用白名单（write/outline 步只能引用 search 步核验的 [1..N]）
        inject_whitelist(ctx, refs_list)
        prompt = render_prompt(stage_, ctx)
        texts: list = []

        def _cb(t: str) -> None:
            texts.append(t)
            cb("stream_text", {"text": t})

        # 串行执行：同一论文会话由 per-session 锁串行（common.run_conversation）；
        # _PAPER_RUN_LOCK 保留作全局兜底（agent 池上限内的极端并发仍安全）
        with _PAPER_RUN_LOCK:
            result = run_conversation_guarded(agent, prompt, paper_sid, _cb)
        if _cancel_ev is not None and _cancel_ev.is_set():
            raise PaperCancelled("生成已取消")
        # 优先用 run_conversation 返回值（stream_callback 在核心链路未接线时兜底）
        final = (result or {}).get("final_response") or "".join(texts) or ""
        _guard(final, stage_)   # ← 拦错误文本，保住已有正文（真事故修复）
        return final, refs_list if stage_ == "search" else []

    return _runner


def run_conversation_guarded(agent, prompt: str, session_id: str, stream_callback):
    """论文步骤的 agent 调用：统一走 common.run_conversation（per-session 锁）。

    返回 run_conversation 的 dict 结果（含 final_response），供调用方取生成内容。
    """
    from matlens_kit.ui.common import run_conversation

    return run_conversation(agent, prompt, session_id=session_id, stream_callback=stream_callback)


def _build_export_response(res: Dict[str, Any]) -> Any:
    """把 export_paper 的结果 dict 转成 HTTP 响应（bytes→Response，文本→PlainText）。

    质量门警告（res["warning"]）通过 `X-Matlens-Quality-Warning` 响应头透出
    （非 ASCII 需编码），供前端提示「质量偏低，是否仍要导出」。
    """
    from urllib.parse import quote

    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "导出失败"))
    safe_fn = quote(res["filename"])
    headers: Dict[str, str] = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{safe_fn}"
    }
    warn = res.get("warning")
    if warn:
        from urllib.parse import quote as _q

        headers["X-Matlens-Quality-Warning"] = _q(str(warn), safe="")
    if "bytes" in res:
        from fastapi.responses import Response

        return Response(
            content=res["bytes"],
            media_type=res["media_type"],
            headers=headers,
        )
    return PlainTextResponse(
        res["content"],
        media_type=res["media_type"],
        headers=headers,
    )


@_router.get("/{pid}/figures")
def list_figures(pid: str) -> Dict[str, Any]:
    """列出该论文已生成的图件（按图注序号分组，PNG + 矢量）。

    返回 {ok, figures: [{num, kind, scheme, status, path, files[], reason, metrics}]}。
    skipped 的图也返回并带 reason——前端要能告诉用户「为什么这张没画出来」。
    """
    p = PDB.get_paper(pid)
    if p is None:
        raise HTTPException(status_code=404, detail="论文项目不存在")
    from matlens_kit.paper.export import figures_dir_for

    d = figures_dir_for(p)
    if not d or not os.path.isdir(d):
        return {"ok": True, "figures": [], "dir": d}
    out = []
    for name in sorted(os.listdir(d)):
        m = _FIG_FILE_RE.match(name)
        if not m:
            continue
        stem, ext = os.path.splitext(name)
        out.append({"stem": stem, "ext": ext.lstrip("."), "file": name,
                    "url": f"/api/papers/{pid}/figures/file/{name}"})
    return {"ok": True, "figures": out, "dir": d}


@_router.post("/{pid}/figures")
def generate_figures(pid: str) -> Dict[str, Any]:
    """生成论文图件（示意 + 数据图），返回逐图结果。

    - 示意图（cell / mechanism）：无需数据，直接画
    - 数据图：仅从 ``experimental_data.tables`` 取数，**无数据即跳过**（学术诚信红线）

    返回 {ok, generated, skipped, results:[...]}。
    """
    p = PDB.get_paper(pid)
    if p is None:
        raise HTTPException(status_code=404, detail="论文项目不存在")
    from matlens_kit.paper.export import figures_dir_for
    from matlens_kit.paper.fig_gen import gen_figures

    write = (p.get("stages", {}).get("write") or {}).get("content") or ""
    if not write.strip():
        raise HTTPException(status_code=400, detail="论文尚无正文（请先完成写作步）")
    out_dir = figures_dir_for(p)
    if not out_dir:
        raise HTTPException(status_code=500, detail="无法定位图件目录")
    try:
        results = gen_figures(write, out_dir, experimental_data=p.get("data"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"图件生成失败：{e}")
    return {
        "ok": True,
        "generated": sum(1 for r in results if r["status"] == "generated"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
        "results": results,
    }


@_router.get("/{pid}/figures/file/{name}")
def get_figure_file(pid: str, name: str):
    """回传图件文件（PNG/PDF/SVG）。路径做 basename 校验防目录穿越。"""
    p = PDB.get_paper(pid)
    if p is None:
        raise HTTPException(status_code=404, detail="论文项目不存在")
    from matlens_kit.paper.export import figures_dir_for

    base = figures_dir_for(p)
    if not base:
        raise HTTPException(status_code=404, detail="图件目录不存在")
    safe = os.path.basename(name)          # 防 ../../ 穿越
    fp = os.path.join(base, safe)
    if not os.path.isfile(fp):
        raise HTTPException(status_code=404, detail="图件文件不存在")
    media = {"png": "image/png", "pdf": "application/pdf", "svg": "image/svg+xml"}.get(
        safe.rsplit(".", 1)[-1].lower(), "application/octet-stream")
    from fastapi.responses import FileResponse

    return FileResponse(fp, media_type=media)


@_router.get("/{pid}/quality_gate")
def quality_gate(pid: str) -> Dict[str, Any]:
    """导出质量门预检：前端点「导出成稿」前先问一次要不要拦。

    返回 {ok, passed, checked, score, threshold, reasons[], blocking[]}。
    checked=False 表示未跑过质量巡检 → 不做任何判断（无据不判）。
    """
    p = PDB.get_paper(pid)
    if p is None:
        raise HTTPException(status_code=404, detail="论文项目不存在")
    from matlens_kit.paper.quality_gate import evaluate as _gate_evaluate

    return {"ok": True, **_gate_evaluate(p)}


@_router.get("/{pid}/export")
def export_paper_default(pid: str, force: bool = False) -> Any:
    """默认导出：格式取 settings papers.export_format（docx/tex/md），引用风格同设置。"""
    p = PDB.get_paper(pid)
    if p is None:
        raise HTTPException(status_code=404, detail="论文项目不存在")
    from matlens_kit.paper.export import default_export_format, export_paper as _export

    return _build_export_response(_export(p, default_export_format(), force=force))


@_router.get("/{pid}/export/{fmt}")
def export_paper(pid: str, fmt: str = "md", force: bool = False) -> Any:
    """导出论文成稿：md / tex / docx（URL 显式指定格式优先；引用风格取设置）。

    force=true 跳过质量门警告（用户确认后强行导出）。
    """
    p = PDB.get_paper(pid)
    if p is None:
        raise HTTPException(status_code=404, detail="论文项目不存在")
    from matlens_kit.paper.export import export_paper as _export

    return _build_export_response(_export(p, fmt, force=force))


@_router.post("/{pid}/to_kb")
def paper_to_kb(pid: str) -> Dict[str, Any]:
    """论文 → 知识库回流：把正文切片写入当前激活知识库。

    正文来源：优先 write 阶段成稿；为空则回退到完整 Markdown 导出。
    入库复用 rag/kb.KnowledgeBase.add_document（分块 + 嵌入 + FAISS 落盘），
    不新写一套入库逻辑。返回 {ok, chunks, kb, source, skipped?}。
    """
    import os
    import tempfile

    p = PDB.get_paper(pid)
    if p is None:
        raise HTTPException(status_code=404, detail="论文项目不存在")

    # 1) 正文：write 成稿优先，否则完整 markdown
    write_body = (p.get("stages", {}).get("write", {}) or {}).get("content", "").strip()
    if write_body:
        body = f"# {p.get('title') or '未命名论文'}\n\n{write_body}"
    else:
        from matlens_kit.paper.export import export_markdown

        body = export_markdown(p)
    if not body.strip():
        raise HTTPException(status_code=400, detail="论文尚无正文可回流（请先完成写作步）")

    # 2) 定位激活知识库
    from matlens_kit.plugins.local_rag import get_manager

    mgr = get_manager()
    if not mgr.active:
        raise HTTPException(status_code=400, detail="未激活知识库，请先在知识库页新建/切换一个库")
    try:
        kb = mgr.get(mgr.active)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"打开知识库失败：{e}")

    # 3) 写成临时 .md 走标准入库路径（extract_text 支持 md）
    tmp_path = ""
    try:
        fd, tmp_path = tempfile.mkstemp(prefix=f"paper_{pid[:8]}_", suffix=".md")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        res = kb.add_document(tmp_path)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"回流知识库失败：{e}")
    finally:
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

    if res.get("error"):
        raise HTTPException(status_code=400, detail=res["error"])
    return {
        "ok": True,
        "chunks": res.get("chunks", 0),
        "kb": kb.name,
        "source": res.get("source", ""),
        "skipped": res.get("skipped", False),
        "reason": res.get("reason", ""),
    }
