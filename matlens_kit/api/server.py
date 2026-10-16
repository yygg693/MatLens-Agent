# -*- coding: utf-8 -*-
"""MatLens Web 服务层 —— FastAPI 入口（M0：SSE 事件流对话 + 健康检查 + 静态托管）。

同进程调核心（AIAgent），不重复实现业务逻辑。
运行：python -m matlens_kit.api.server [--port 7865]
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import FastAPI, Query, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from matlens_kit.api.events import get_bus
from matlens_kit.api.hooks import clear_active_session, install_hooks, set_active_session

app = FastAPI(title="MatLens API", version="0.1.0")


@app.middleware("http")
async def _no_store_static(request, call_next):
    """调试期静态资源不缓存（避免浏览器/代理拿到旧版 index.html / app.js）。"""
    import starlette.responses as _sr
    resp = await call_next(request)
    if not request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request, exc: Exception):
    """全局兜底：把所有未捕获异常统一成 JSON 500，而不是裸堆栈 HTML。

    仅兜住未被路由/HTTPException 处理的异常；HTTPException（4xx）走 Starlette
    默认处理器不受影响。错误信息截断到 300 字符，避免泄漏内部长堆栈。
    """
    return JSONResponse(
        status_code=500,
        content={"ok": False, "error": str(exc)[:300]},
    )

# ── S5 生产化：server 段配置读取（缺字段绝不崩，全部走默认值） ──
_SERVER_DEFAULTS = {
    "host": "127.0.0.1",      # 监听地址
    "port": 7896,             # 监听端口
    "auth_enabled": False,    # 鉴权总开关：默认关闭，本地开箱即用
    "auth_token": "",        # Bearer token；开启后留空则启动时随机生成并打印到控制台
    "allowed_origins": [],    # CORS 白名单；为空 = 同源，不加 CORS
}


def _load_server_config() -> Dict[str, Any]:
    """从 ~/.matlens/config.yaml 的 server 段读配置；任何异常都回退默认值。"""
    cfg = dict(_SERVER_DEFAULTS)
    try:
        import yaml
        home = os.path.expanduser("~/.matlens")
        cfg_path = os.path.join(home, "config.yaml")
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            srv = data.get("server")
            if isinstance(srv, dict):
                for k in cfg:
                    if k in srv and srv[k] is not None:
                        cfg[k] = srv[k]
    except Exception as e:  # 配置读坏了也不阻塞启动
        print(f"[server] config.yaml 读取失败，使用默认配置: {e}", flush=True)
    # 类型兜底：config 里写错类型也不能崩
    try:
        cfg["port"] = int(cfg["port"])
    except Exception:
        cfg["port"] = 7896
    cfg["auth_enabled"] = bool(cfg["auth_enabled"])
    cfg["auth_token"] = str(cfg["auth_token"] or "")
    if not isinstance(cfg["allowed_origins"], list):
        cfg["allowed_origins"] = []
    return cfg


_SRV_CFG = _load_server_config()


# CORS：仅当 allowed_origins 非空时才挂中间件（为空 = 同源，保持现状）。
# 注意 add_middleware 顺序：先挂 CORS 再挂鉴权，使 CORS 位于鉴权外层，
# 浏览器 OPTIONS 预检被 CORS 直接放行，不会被鉴权中间件误判 401。
if _SRV_CFG["allowed_origins"]:
    try:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(_SRV_CFG["allowed_origins"]),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    except Exception as e:
        print(f"[server] CORS 中间件挂载失败: {e}", flush=True)


# 鉴权中间件：auth_enabled=false 时完全不拦截（本地默认，不锁死现有体验）。
# 开启后：除 /、/api/health、以及一切静态资源（非 /api/*）外，
# 所有 /api/* 需带 Authorization: Bearer <token>，否则 401 JSON。
async def _auth_dispatch(request, call_next):
    cfg = _SRV_CFG
    if not cfg.get("auth_enabled") or not cfg.get("auth_token"):
        return await call_next(request)
    path = request.url.path or "/"
    # 放行：首页、健康检查、以及一切静态资源（/js/、/assets/、index.html 等）
    if path == "/" or path == "/api/health" or not path.startswith("/api/"):
        return await call_next(request)
    expected = "Bearer " + cfg["auth_token"]
    if request.headers.get("authorization", "") != expected:
        return JSONResponse(status_code=401, content={"ok": False, "error": "unauthorized"})
    return await call_next(request)


try:
    from starlette.middleware.base import BaseHTTPMiddleware

    app.add_middleware(BaseHTTPMiddleware, dispatch=_auth_dispatch)
except Exception as e:
    print(f"[server] 鉴权中间件挂载失败: {e}", flush=True)

# 项目根（用于静态托管与核心导入）——必须在 .env 加载前定义
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 挂载各业务路由（每个路由封装一个后端能力的真实接口）
from matlens_kit.api.sessions_api import _router as _sessions_router  # noqa: E402
from matlens_kit.api.kb_api import _router as _kb_router  # noqa: E402
from matlens_kit.api.mem_api import _router as _mem_router  # noqa: E402
from matlens_kit.api.graph_api import _router as _graph_router  # noqa: E402
from matlens_kit.api.config_api import _router as _config_router  # noqa: E402
from matlens_kit.api.approval import _router as _approval_router  # noqa: E402
from matlens_kit.api.papers_api import _router as _papers_router  # noqa: E402
from matlens_kit.api.experiment_api import _router as _experiment_router  # noqa: E402
from matlens_kit.api.tools_api import _router as _tools_router  # noqa: E402
from matlens_kit.api.workspaces_api import _router as _workspaces_router  # noqa: E402
from matlens_kit.api.web_api import _router as _web_router  # noqa: E402

app.include_router(_sessions_router)
app.include_router(_kb_router)
app.include_router(_mem_router)
app.include_router(_graph_router)
app.include_router(_config_router)
app.include_router(_approval_router)
app.include_router(_papers_router)
app.include_router(_experiment_router)
app.include_router(_tools_router)
app.include_router(_workspaces_router)
app.include_router(_web_router)

# 加载 .env（graph 抽取向 DeepSeek 需要 DEEPSEEK_API_KEY）
try:
    from dotenv import load_dotenv

    _home = os.path.expanduser("~/.matlens")
    for _f in (os.path.join(_home, ".env"), os.path.join(_ROOT, ".env")):
        if os.path.exists(_f):
            load_dotenv(_f)
except Exception:
    pass


def _get_agent(session_id: str = ""):
    from matlens_kit.ui.common import get_agent
    return get_agent(session_id=session_id)


# ── 静态托管：原型页面（design/prototype） ──


@app.get("/api/health")
def health() -> Dict[str, Any]:
    from matlens_kit.api import hooks as _hooks
    try:
        from matlens_cli.plugins import get_plugin_manager
        pm = get_plugin_manager()
        tr = len(pm._middleware.get("tool_request", []))
        te = len(pm._middleware.get("tool_execution", []))
    except Exception:
        tr = te = -1

    # ── S5：DB 体积（KB，文件不存在=0） ──
    home = os.path.expanduser("~/.matlens")

    def _kb(name: str) -> float:
        try:
            p = os.path.join(home, name)
            return round(os.path.getsize(p) / 1024.0, 1) if os.path.exists(p) else 0.0
        except Exception:
            return 0.0

    db_sizes = {
        "papers_db_kb": _kb("papers.db"),
        "state_db_kb": _kb("state.db"),
        "graph_json_kb": _kb("graph.json"),
    }

    # ── S5：agent 是否就绪 ──
    # 非阻塞 peek 全局单例：预热线程建好后 _AGENT 即为非空。用 0.5s 超时抢锁，
    # 抢不到说明预热仍在构造（首构约 25s）→ 报 not ready，绝不挂死、也不触发
    # get_agent() 的模型比对重建（那会再花 25s）。
    try:
        from matlens_kit.ui import common as _c
        got = _c._AGENT_LOCK.acquire(timeout=0.5)
        try:
            agent_ready = getattr(_c, "_AGENT", None) is not None
        finally:
            if got:
                _c._AGENT_LOCK.release()
    except Exception:
        agent_ready = False

    # ── S5：最近错误数（errors.log 中 WARNING/ERROR/CRITICAL 行数） ──
    try:
        elog = os.path.join(home, "logs", "errors.log")
        err_count = 0
        if os.path.exists(elog):
            with open(elog, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if ("WARNING" in line) or ("ERROR" in line) or ("CRITICAL" in line):
                        err_count += 1
    except Exception:
        err_count = 0

    return {
        "ok": True, "service": "matlens-api", "version": "0.1.0",
        "hooks": {"installed": _hooks._installed, "tool_request": tr, "tool_execution": te},
        "db": db_sizes,
        "agent_ready": bool(agent_ready),
        "errors_warn": int(err_count),
    }


# 对话附件上传根目录（会话隔离）
_UPLOAD_ROOT = os.path.join(_ROOT, ".uploads")


@app.post("/api/chat/upload")
async def chat_upload(
    file: UploadFile = File(...),
    session_id: str = Query("", description="会话标识"),
):
    """对话附件上传：保存到 .uploads/<session>，返回可被 Agent 读取的绝对路径。

    前端把返回的 path 以 [附件: <path>] 形式并入消息文本，Agent 的 read_file /
    vision 等工具即可直接读取，实现「对话中带附件提问」。
    """
    import re as _re
    import shutil as _shutil
    import uuid as _uuid
    raw = (file.filename or "").replace("\\", "/").split("/")[-1]
    ext = os.path.splitext(raw)[1] or ".bin"
    safe = f"{_uuid.uuid4().hex}{ext}"
    safe_sid = _re.sub(r"[^A-Za-z0-9_.\-]", "_", session_id or "default")
    d = os.path.join(_UPLOAD_ROOT, safe_sid)
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, safe)
    try:
        with open(dest, "wb") as f:
            _shutil.copyfileobj(file.file, f)
    finally:
        try:
            file.file.close()
        except Exception:
            pass
    return {
        "ok": True,
        "name": raw,
        "path": dest,
        "url": f"/api/chat/files/{safe_sid}/{safe}",
    }


@app.get("/api/chat/files/{session_id}/{name}")
async def chat_file(session_id: str, name: str):
    """返回已上传附件（图片预览/下载）。"""
    import re as _re
    if not _re.fullmatch(r"[A-Za-z0-9_.\-]+", name or ""):
        raise HTTPException(status_code=400, detail="非法文件名")
    d = os.path.join(_UPLOAD_ROOT, _re.sub(r"[^A-Za-z0-9_.\-]", "_", session_id or "default"))
    p = os.path.join(d, name)
    if not os.path.isfile(p):
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(p)


@app.get("/api/chat/context")
def chat_context(session_id: str = Query("", description="会话标识")):
    """当前会话上下文 token 用量估算（与 Hermes 上下文上限对比）。

    读取 state.db 中该会话的活动消息，用 Hermes 同源的
    agent.model_metadata.estimate_messages_tokens_rough 估算 token 规模，
    供前端「上下文用量」标签展示进度条。上限取 Hermes 默认 262144。
    """
    try:
        from matlens_state import SessionDB
        from agent.model_metadata import estimate_messages_tokens_rough

        msgs = []
        if session_id:
            try:
                db = SessionDB()
                msgs = db.get_messages(session_id) or []
            except Exception:
                msgs = []
        tokens = estimate_messages_tokens_rough(msgs) if msgs else 0
        limit = 262144
        return {
            "ok": True,
            "session_id": session_id,
            "tokens": int(tokens),
            "limit": limit,
            "pct": round(min(100.0, tokens / limit * 100), 1),
            "messages": len(msgs),
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}


@app.get("/api/chat/stream")
async def chat_stream(
    message: str = Query(..., description="用户消息"),
    session_id: str = Query("", description="会话标识（默认空=单会话）"),
    kb: str = Query("", description="激活知识库（预留）"),
):
    """SSE 事件流对话：stream_text / tool_call / tool_result / done / error。"""
    bus = get_bus()
    sid = bus.subscribe()
    # 工具钩子在 _run 线程的 setup（per-session 锁内）以 force=True 注册，
    # 不在 async 入口调用 install_hooks()：避免在事件循环线程做插件/中间件
    # 初始化（可能阻塞/竞争），也避免并发请求重复触发注册。
    set_active_session(session_id)

    def _run() -> None:
        try:
            # 会话级 agent：每个 session 独立实例（由 common 池管理，天然隔离并发）。
            # 用超时守卫构造：记忆后端（mem0/chroma）初始化偶发挂起时，请求快速降级为
            # 友好错误，而不是永久卡死 HTTP 线程。
            from matlens_kit.ui.common import get_agent_timed

            agent = get_agent_timed(session_id=session_id, timeout=45)

            def _setup() -> None:
                # 锁内副作用初始化：对共享 agent 实例的所有修改（注入 _session_db、
                # 重挂工具钩子、会话兜底）都放 per-session 锁内执行。否则并发同会话
                # 请求会在锁外竞争同一实例，导致运行中的 run_conversation 卡死、
                # per-session 锁被死线程永久持有（后续该会话全部请求死等）。
                # 关键：get_agent() 默认不传 session_db → agent._session_db=None →
                # _flush_messages_to_session_db 直接 return，消息不落库。注入共享 SessionDB。
                if getattr(agent, "_session_db", None) is None:
                    try:
                        from matlens_state import SessionDB
                        agent._session_db = SessionDB()
                        agent._session_db_created = False
                    except Exception:
                        pass
                # agent 初始化可能清空中间件注册表 → 初始化后强制重挂工具钩子
                install_hooks(force=True)
                # lazy 会话兜底：前端未预建也落库（source="web"）
                if session_id:
                    try:
                        from matlens_kit.api.sessions_api import WEB_SOURCE, get_session_db
                        db = get_session_db()
                        if db.get_session(session_id) is None:
                            db.create_session(session_id, WEB_SOURCE)
                    except Exception:
                        pass

            bus.publish(session_id, "turn_start", {"message": message[:200]})
            # per-session 锁：同一会话串行，不同会话并发（common.run_conversation）
            from matlens_kit.ui.common import run_conversation as _run_conv
            # 模型思考（reasoning）单独走 thinking 事件：Hermes 经 _fire_reasoning_delta
            # 把推理内容回调给 reasoning_callback。前端渲染为可展开/收缩的思考块，
            # 与正文 stream_text 分离，对齐豆包工作任务模式的执行过程展示。
            _old_reasoning = getattr(agent, "reasoning_callback", None)
            agent.reasoning_callback = (
                lambda t: bus.publish(session_id, "thinking", {"text": t})
            )
            # 记忆召回指示：Hermes 在 prefetch 后调用 _emit_status(describe_recall())，
            # 输出形如 "🧠 Mem0 — recalled 3 memories"。接线 status_callback 把这类
            # 生命周期状态发布为 memory_recall SSE 事件，让用户看到「Agent 正在利用
            # 它的持久记忆」，而不依赖模型主动提及。仅转发含记忆召回特征的提示，避免
            # 其它 lifecycle 状态（等待锁/重试等）污染对话流。
            _old_status = getattr(agent, "status_callback", None)

            def _status_relay(kind: str, msg: str) -> None:
                try:
                    if kind == "lifecycle" and msg and (
                        "recalled" in str(msg) or "🧠" in str(msg) or "memory" in str(msg).lower()
                    ):
                        bus.publish(session_id, "memory_recall", {"message": str(msg)})
                except Exception:
                    pass

            agent.status_callback = _status_relay
            try:
                _run_conv(
                    agent,
                    message,
                    session_id=session_id,
                    setup=_setup,
                    stream_callback=lambda t: bus.publish(session_id, "stream_text", {"text": t}),
                )
            finally:
                # 恢复原回调，避免污染共享 agent 实例（池内复用）
                try:
                    agent.reasoning_callback = _old_reasoning
                except Exception:
                    pass
                try:
                    agent.status_callback = _old_status
                except Exception:
                    pass
            bus.publish(session_id, "done", {})
        except Exception as e:  # 友好错误，不抛堆栈
            bus.publish(session_id, "error", {"message": str(e)[:500]})
        finally:
            clear_active_session()
            bus.unsubscribe(sid)

    threading.Thread(target=_run, daemon=True, name="matlens-chat").start()

    async def _gen():
        try:
            async for frame in bus.astream(sid, session_id):
                yield frame
        finally:
            bus.unsubscribe(sid)

    return StreamingResponse(_gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


# ── 静态托管：原型页面（design/prototype） ──
@app.post("/api/chat/redirect")
async def chat_redirect(payload: dict):
    """流式中途插话：在当前活动轮次插入用户修正，Agent 调整策略继续。

    走 Hermes 原生 redirect()：取消当前模型请求（保留已完成消息/工具结果），
    把修正作为真实用户消息追加并重试；工具执行阶段自动降级为 steer()，
    在安全边界应用。前端在 SSE 流式进行中发送新消息时调用本接口，
    无需断开当前流即可实现「执行中插话改方向」。
    """
    session_id = payload.get("session_id", "")
    message = payload.get("message", "")
    if not message or not str(message).strip():
        return {"ok": False, "error": "空消息"}
    try:
        from matlens_kit.ui.common import get_agent_timed

        agent = get_agent_timed(session_id=session_id, timeout=10)
        if agent is None:
            return {"ok": False, "error": "agent 未就绪"}
        ok = agent.redirect(str(message))
        return {"ok": bool(ok), "redirected": bool(ok)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}


_PROTO_DIR = os.path.join(_ROOT, "design", "prototype")


@app.get("/")
def index():
    proto = os.path.join(_PROTO_DIR, "index.html")
    if os.path.exists(proto):
        return FileResponse(proto)
    return {"ok": True, "hint": "MatLens API 运行中"}


def _warmup_agent() -> None:
    """启动预热：后台初始化 agent（含记忆/工具链），避免首个请求冷启动超时。"""
    try:
        from matlens_kit.ui.common import get_agent
        a = get_agent()
        # 与 chat 端点同样的 session_db 注入，保证消息落库
        if getattr(a, "_session_db", None) is None:
            from matlens_state import SessionDB
            a._session_db = SessionDB()
            a._session_db_created = False
        print("[warmup] agent ready", flush=True)
    except Exception as e:
        print(f"[warmup] agent init failed: {e}", flush=True)


def _recover_stuck_papers() -> None:
    """崩溃恢复：服务启动时重置论文库中所有 running 步骤（生成中断残留）。"""
    try:
        from matlens_kit.paper.db import recover_stuck_running
        n = recover_stuck_running()
        if n:
            print(f"[recover] 已重置 {n} 个中断的论文步骤", flush=True)
    except Exception as e:
        print(f"[recover] 论文恢复失败: {e}", flush=True)


def backup_databases() -> None:
    """启动自动备份：把 papers.db / state.db（含 WAL 侧车）拷到
    ~/.matlens/backups/YYYYMMDD_HHMMSS/，只保留最近 7 份。

    只读拷贝，绝不改动原库；失败只打印警告，不阻塞启动。
    """
    import shutil
    from datetime import datetime

    home = os.path.expanduser("~/.matlens")
    backups_root = os.path.join(home, "backups")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bdir = os.path.join(backups_root, ts)
    try:
        os.makedirs(bdir, exist_ok=True)
        # state.db 是 WAL 模式，连 -wal/-shm 一起拷，避免丢未 checkpoint 数据
        targets = ["papers.db", "state.db", "state.db-wal", "state.db-shm"]
        for name in targets:
            src = os.path.join(home, name)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(bdir, name))
        # 只保留最近 7 份目录（按目录名时间戳排序，删最老的）
        dirs = sorted(
            d for d in os.listdir(backups_root)
            if os.path.isdir(os.path.join(backups_root, d))
        )
        while len(dirs) > 7:
            old = dirs.pop(0)
            try:
                shutil.rmtree(os.path.join(backups_root, old))
            except Exception as e:
                print(f"[backup] 清理旧备份失败 {old}: {e}", flush=True)
        print(f"[backup] 已备份到 {bdir}", flush=True)
    except Exception as e:
        print(f"[backup] 备份失败（不阻塞启动）: {e}", flush=True)


def main(host: str = "127.0.0.1", port: int = 7896) -> None:
    import uvicorn
    srv = _SRV_CFG
    # 鉴权开启但未配 token → 进程内随机生成，打印到控制台（不落盘）
    if srv.get("auth_enabled") and not srv.get("auth_token"):
        import secrets
        srv["auth_token"] = secrets.token_urlsafe(24)
        print(
            f"[auth] MatLens token: {srv['auth_token']}  (http://{host}:{port})",
            flush=True,
        )
    else:
        if srv.get("auth_enabled"):
            print(f"[auth] 鉴权已启用（固定 token，http://{host}:{port}）", flush=True)
        else:
            print(f"[auth] 鉴权关闭（本地开放，http://{host}:{port}）", flush=True)
    # 崩溃恢复 + 预热 + 自动备份（均不阻塞监听）
    threading.Thread(target=_recover_stuck_papers, daemon=True, name="matlens-recover").start()
    threading.Thread(target=_warmup_agent, daemon=True, name="matlens-warmup").start()
    threading.Thread(target=backup_databases, daemon=True, name="matlens-backup").start()
    if os.path.isdir(_PROTO_DIR):
        # 挂到根路径（html=True 使 / 直接返回 index.html）：
        # 相对资源（app.js / assets/...）可被 /app.js、/assets/... 直接命中；
        # /api/* 路由优先匹配，未命中的静态请求才落到 mount。
        app.mount("/", StaticFiles(directory=_PROTO_DIR, html=True), name="proto")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=None, help="监听地址（缺省读 config.yaml server.host）")
    ap.add_argument("--port", type=int, default=None, help="监听端口（缺省读 config.yaml server.port）")
    args = ap.parse_args()
    srv = _SRV_CFG
    _host = args.host or srv["host"]
    _port = args.port or srv["port"]
    main(_host, _port)
