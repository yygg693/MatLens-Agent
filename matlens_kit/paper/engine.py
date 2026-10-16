# -*- coding: utf-8 -*-
"""论文工坊 · 工作流引擎（STAGES 状态机 + 断点续写）。

7 步：topic(选题) → search(检索) → outline(大纲) → write(写作)
      → quality(质量巡检) → review(审稿) → export(导出)

设计原则（继承老项目 mra，深度定制于 matlens）：
- 每步独立可重跑：产物落库 stages_json，失败单独重跑
- 前置检查：下一步需上一步 done（topic 无前置）
- 断点续写：重新运行已 done 步骤会重跑（覆盖内容）；未完成步骤从已有内容继续
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from matlens_kit.paper import db as PDB

#: 工作流阶段顺序（前端步骤条依此渲染）
STAGES: Tuple[str, ...] = ("topic", "search", "outline", "write", "quality", "review", "export")

STAGE_LABELS: Dict[str, str] = {
    "topic": "选题设定",
    "search": "文献检索",
    "outline": "大纲生成",
    "write": "逐章写作",
    "quality": "质量巡检",
    "review": "模拟审稿",
    "export": "导出",
}

PAPER_TYPES = {"review": "综述（Review）", "research": "研究论文（Research Article）"}


def _autosave_enabled() -> bool:
    """实时读 settings papers.autosave（默认 True）。动作发生时刻读，不缓存。"""
    try:
        from matlens_kit import settings_store

        return bool(settings_store.get_section("papers").get("autosave", True))
    except Exception:
        return True


def stage_index(stage: str) -> int:
    return STAGES.index(stage) if stage in STAGES else -1


def prev_stage(stage: str) -> Optional[str]:
    i = stage_index(stage)
    return STAGES[i - 1] if i > 0 else None


def check_prerequisite(stages: Dict[str, Any], stage: str) -> Tuple[bool, str]:
    """前置检查：上一步必须 done（topic 无前置）。返回 (ok, reason)。"""
    if stage not in STAGES:
        return False, f"未知阶段：{stage}"
    prev = prev_stage(stage)
    if prev is None:
        return True, ""
    p = stages.get(prev, {})
    if p.get("status") != "done":
        return False, f"前置步骤「{STAGE_LABELS.get(prev, prev)}」尚未完成"
    return True, ""


def progress_of(stages: Dict[str, Any]) -> Dict[str, Any]:
    done = sum(1 for s in stages.values() if s.get("status") == "done")
    return {"done": done, "total": len(STAGES), "pct": round(done * 100 / max(len(STAGES), 1))}


class PaperEngine:
    """论文工作流引擎：同进程调 matlens 核心（AIAgent 等），不重复实现业务。"""

    def __init__(self, runner: Optional[Callable[[str, str, Dict[str, Any], Callable], Any]] = None):
        """runner(stage, pid, stage_ctx, emit) -> 同步执行某步生成。

        - emit(event_type, data)：SSE 事件回调（stream_text / tool_call / done / error）
        - runner 由 API 层注入（接 AIAgent 流式生成）；None 时 run_stage 走占位模式。
        """
        self._runner = runner

    # ------------------------------------------------------------------
    # 项目级操作
    # ------------------------------------------------------------------
    def create(self, title: str, paper_type: str = "research", topic: str = "") -> Dict[str, Any]:
        return PDB.create_paper(title, paper_type, topic)

    def list(self) -> List[Dict[str, Any]]:
        return PDB.list_papers()

    def get(self, pid: str) -> Optional[Dict[str, Any]]:
        return PDB.get_paper(pid)

    def delete(self, pid: str) -> bool:
        return PDB.delete_paper(pid)

    def save_step(self, pid: str, stage: str, content: str, refs: Optional[List[Any]] = None) -> Dict[str, Any]:
        """手动保存/编辑某步内容（断点续写入口）。"""
        if stage not in STAGES:
            raise KeyError(f"未知阶段：{stage}")
        return PDB.save_stage_content(pid, stage, content, refs)

    # ------------------------------------------------------------------
    # 阶段执行（状态机）
    # ------------------------------------------------------------------
    def run_stage(
        self,
        pid: str,
        stage: str,
        emit: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """执行单个阶段：前置检查 → running → 生成 → done/error 落库。

        返回 {ok, stage, status, content?, error?}。
        """
        paper = PDB.get_paper(pid)
        if paper is None:
            return {"ok": False, "error": f"论文项目不存在：{pid}"}
        stages = paper["stages"]

        ok, reason = check_prerequisite(stages, stage)
        if not ok:
            return {"ok": False, "error": reason}

        # 标记 running
        PDB.set_stage_status(pid, stage, "running")
        if emit:
            emit("stage_status", {"stage": stage, "status": "running"})

        stage_ctx = stages.get(stage, {})
        try:
            if self._runner is not None:
                content, refs = self._runner(stage, pid, stage_ctx, emit or (lambda *a: None))
                # 兜底守卫：任何 runner 若漏接 guard，仍不许把上游错误文本写进正文。
                # （真事故：402 欠费时 agent 把错误提示塞进 final_response，静默覆盖万字正文）
                from matlens_kit.paper.guard import ensure_not_error

                ensure_not_error(content, stage)
                if _autosave_enabled():
                    PDB.save_stage_content(pid, stage, content or "", refs)
                else:
                    # 自动保存草稿关闭：不把生成正文落库，但保留结构性 refs（写作白名单）；
                    # 用户手动「保存编辑」仍可写入。阶段完成状态照常标记。
                    PDB.save_stage_content(pid, stage, "", refs)
                PDB.set_stage_status(pid, stage, "done")
                if emit:
                    emit("stage_status", {"stage": stage, "status": "done"})
                return {"ok": True, "stage": stage, "status": "done", "content": content or "", "refs": refs or []}
            # 占位模式（P1 骨架：无 runner 时仅流转状态）
            PDB.set_stage_status(pid, stage, "done")
            if emit:
                emit("stage_status", {"stage": stage, "status": "done"})
            return {"ok": True, "stage": stage, "status": "done", "content": stage_ctx.get("content", "")}
        except Exception as e:
            PDB.set_stage_status(pid, stage, "error", error=str(e))
            if emit:
                emit("stage_error", {"stage": stage, "message": str(e)[:300]})
            return {"ok": False, "stage": stage, "status": "error", "error": str(e)[:300]}
