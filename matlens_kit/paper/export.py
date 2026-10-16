# -*- coding: utf-8 -*-
"""论文导出统一入口（门面）。

导出的是一篇**真正的学术成稿**，而非工作流过程记录：

- 唯一正文来源是 ``write``（逐章写作）阶段 content，经 :mod:`md_model` 解析为
  标题 / 摘要 / 关键词 / 正文章节；
- 参考文献来自 ``search`` 阶段 refs，按 settings ``papers.cite_style`` 排版；
- ``topic / search / outline / quality / review`` 的过程性文字一律不进入成稿。

三种格式：
- markdown（:mod:`export_text`）
- latex（ctexart 中文模板，:mod:`export_text`）
- docx（python-docx 学术排版，:mod:`export_docx`；未安装时返回明确提示）。

``write`` 为空时不导出残文档，统一返回 :data:`EMPTY_WRITE_MESSAGE`。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from matlens_kit.paper.md_model import parse_paper, EMPTY_WRITE_MESSAGE
from matlens_kit.paper.refs import (
    resolve_cite_style,
    default_export_format,
    fmt_refs,
    ref_lines,
    papers_settings,
)
from matlens_kit.paper.export_text import export_markdown, export_latex
from matlens_kit.paper.export_docx import export_docx

__all__ = [
    "export_paper",
    "export_markdown",
    "export_latex",
    "export_docx",
    "parse_paper",
    "resolve_cite_style",
    "default_export_format",
    "fmt_refs",
    "ref_lines",
    "papers_settings",
    "EMPTY_WRITE_MESSAGE",
]


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _safe_filename(p: Dict[str, Any], ext: str) -> str:
    """导出文件名：优先课题标题（过滤非法字符），回退 id。"""
    import re

    name = (p.get("title") or "").strip() or p.get("id", "paper")
    name = re.sub(r'[\\/:*?"<>|\r\n]', "_", name)
    return f"{name[:60]}.{ext}"


def figures_dir_for(p: Dict[str, Any]) -> Optional[str]:
    """定位本篇论文的图件目录（`paper_id` 同级的 figures/ 子目录）。

    约定：``~/.matlens/papers/<pid>/figures/fig_{n}_*.png``。
    目录不存在 → 返回 None（导出无图，这是允许状态）。
    不存在时按需创建，便于 :func:`matlens_kit.paper.fig_gen.gen_figures` 写入。
    """
    import os

    pid = p.get("id")
    if not pid:
        return None
    base = os.path.join(os.path.expanduser("~/.matlens/papers"), str(pid), "figures")
    try:
        os.makedirs(base, exist_ok=True)
    except Exception:
        return None
    return base


def _stage_content(p: Dict[str, Any], stage: str) -> str:
    st = p.get("stages", {}).get(stage, {}) or {}
    return (st.get("content") or "").strip()


def _stage_refs(p: Dict[str, Any], stage: str) -> List[Dict[str, Any]]:
    st = p.get("stages", {}).get(stage, {}) or {}
    return st.get("refs") or []


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------
def export_paper(p: Dict[str, Any], fmt: str, cite_style: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    """统一导出入口（API 层调用）。

    - fmt: md/tex/docx（显式格式）
    - cite_style: 显式引用风格优先；否则实时读 settings papers.cite_style
    - force: True 跳过质量门警告（用户确认后强行导出）
    Returns:
        {"ok": True, "content"|"bytes", "filename", "media_type",
         "warning"?} 或 {"ok": False, "error"}

    质量门（见 :mod:`quality_gate`）：分数过低或存在 🔴 问题时**不阻断**，
    但会在返回值里带 ``warning`` + ``quality_gate`` 详情，由 API 层提示用户。
    """
    # write 为空 → 明确提示，不导出残文档
    if not _stage_content(p, "write"):
        return {"ok": False, "error": EMPTY_WRITE_MESSAGE}

    style = resolve_cite_style(cite_style)
    fmt = (fmt or "md").lower().strip()

    # 质量门评估（警告不阻断；force=True 时只算不报）
    gate_verdict: Dict[str, Any] = {}
    try:
        from matlens_kit.paper.quality_gate import evaluate as _gate_evaluate

        gate_verdict = _gate_evaluate(p)
    except Exception:
        gate_verdict = {}

    res: Dict[str, Any]
    if fmt in ("md", "markdown"):
        res = {
            "ok": True,
            "content": export_markdown(p, cite_style=style),
            "filename": _safe_filename(p, "md"),
            "media_type": "text/markdown; charset=utf-8",
        }
    elif fmt in ("tex", "latex"):
        res = {
            "ok": True,
            "content": export_latex(p, cite_style=style),
            "filename": _safe_filename(p, "tex"),
            "media_type": "application/x-tex; charset=utf-8",
        }
    elif fmt == "docx":
        figs = figures_dir_for(p)
        # 导出前自动补图：正文有图注但目录缺图时现生成一次。
        # 图件生成失败不阻断导出（宁可少图也不给不出稿）。
        fig_summary = None
        if figs:
            try:
                from matlens_kit.paper.fig_gen import gen_figures

                results = gen_figures(
                    _stage_content(p, "write"), figs, experimental_data=p.get("data")
                )
                gen = [r for r in results if r.get("status") == "generated"]
                if gen:
                    fig_summary = {
                        "generated": len(gen),
                        "skipped": sum(1 for r in results if r.get("status") == "skipped"),
                        "figures": [r.get("path") for r in gen],
                    }
            except Exception as e:  # noqa: BLE001
                fig_summary = {"error": f"图件生成失败（不影响导出）：{e}"}
        data = export_docx(p, cite_style=style, figures_dir=figs)
        if data is None:
            return {
                "ok": False,
                "error": "Word 导出需要 python-docx（pip install python-docx），请先用 md/tex 导出",
            }
        res = {
            "ok": True,
            "bytes": data,
            "filename": _safe_filename(p, "docx"),
            "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
        if fig_summary:
            res["figures"] = fig_summary
    else:
        return {"ok": False, "error": f"暂不支持导出格式：{fmt}（支持 md / tex / docx）"}

    if gate_verdict and not gate_verdict.get("passed", True) and not force:
        from matlens_kit.paper.quality_gate import warning_message

        res["warning"] = warning_message(gate_verdict)
        res["quality_gate"] = gate_verdict
    return res
