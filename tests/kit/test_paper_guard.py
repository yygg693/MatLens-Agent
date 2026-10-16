# -*- coding: utf-8 -*-
"""paper/guard.py 回归测试：上游错误文本不得写入正文。

真事故背景：402 欠费时 agent 把错误提示塞进 final_response，
runner 落库把已有 2 万字正文覆盖成 409 字错误信息。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from matlens_kit.paper.guard import ensure_not_error, error_summary, is_error_text

# 真实事故文本（DeepSeek 402，2026-10-14 实测捕获）
REAL_402 = (
    "Billing or credits exhausted: HTTP 402: Insufficient Balance "
    "(request_id: 5c096038-8c32-456c-be22-b5c59cc1764f)\n\n"
    "DeepSeek reported that billing, credits, or account entitlement is exhausted "
    "for deepseek-v4-flash.\n"
    "Add credits or update billing with that provider, then retry.\n"
    "DeepSeek billing: https://platform.deepseek.com/top_up\n"
    "You can switch providers temporarily with /model <model> --provider <provider>."
)


class TestIsErrorText:
    def test_real_402_text_detected(self):
        assert is_error_text(REAL_402) is True

    @pytest.mark.parametrize(
        "text",
        [
            "HTTP 401: Incorrect API key provided",
            "Error code: 429 - Rate limit reached",
            "error code: 500 internal server error",
            "余额不足，请充值",
            "额度不足",
        ],
    )
    def test_common_errors_detected(self, text):
        assert is_error_text(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "",
            None,
            "   ",
            "本文提出 2 mol% Ca 共掺杂 GDC 电解质的设计窗口。",
            "The peak conductivity reached 0.45 S/cm at 900 °C.",
            "实验表明，HTTP 协议栈在此处并非瓶颈，但 502 端口需进一步排查。" * 5,
        ],
    )
    def test_normal_text_not_flagged(self, text):
        """正常论文正文（哪怕含数字/缩写）不得误判。"""
        assert is_error_text(text) is False

    def test_long_paper_with_http_word_not_flagged(self):
        """超长正文里偶然出现 HTTP/500 不该被判为错误（避免误杀）。"""
        long_paper = "正文段落。" * 300 + " HTTP 500 " + "后续段落。" * 300
        assert is_error_text(long_paper) is False


class TestErrorSummary:
    def test_extracts_http_code(self):
        s = error_summary(REAL_402)
        assert "402" in s

    def test_empty_returns_default(self):
        assert error_summary("") == "上游模型调用失败"
        assert error_summary(None) == "上游模型调用失败"


class TestEnsureNotError:
    def test_raises_on_error_text(self):
        with pytest.raises(RuntimeError) as ei:
            ensure_not_error(REAL_402, "write")
        assert "402" in str(ei.value)
        assert "write" in str(ei.value)

    def test_passes_through_normal_text(self):
        ensure_not_error("这是一段正常的论文正文内容。", "write")  # 不抛即通过

    def test_passes_through_empty(self):
        ensure_not_error("", "write")
        ensure_not_error(None, "write")


class TestEngineGuardsContent:
    """引擎层兜底：runner 返回错误文本时必须走 error 分支且保留原正文。"""

    def test_error_content_does_not_overwrite_existing(self, tmp_path, monkeypatch):
        from matlens_kit.paper import db as PDB
        from matlens_kit.paper.engine import PaperEngine

        # 关键：PaperEngine 内部走 PDB 模块级默认路径，必须重定向到临时库，
        # 否则测试会打到真实 ~/.matlens/papers.db。
        dbp = tmp_path / "p.db"
        monkeypatch.setattr(PDB, "_PAPER_DB", str(dbp))

        paper = PDB.create_paper("测试论文", "research", "主题")
        pid = paper["id"]
        # write 的前置是 outline → done
        PDB.save_stage_content(pid, "outline", "大纲", None)
        PDB.set_stage_status(pid, "outline", "done")
        # 先写一段已有正文
        PDB.save_stage_content(pid, "write", "原有正文内容，2 万字的那种。" * 10, None)

        def _bad_runner(stage, pid_, ctx, emit):
            return REAL_402, []

        eng = PaperEngine(runner=_bad_runner)
        res = eng.run_stage(pid, "write")

        assert res["ok"] is False
        assert res["status"] == "error"
        got = PDB.get_paper(pid)
        assert "原有正文内容" in got["stages"]["write"]["content"]
        assert "Insufficient Balance" not in got["stages"]["write"]["content"]

    def test_normal_content_still_saves(self, tmp_path, monkeypatch):
        """守卫不得误伤正常正文（回归保护）。"""
        from matlens_kit.paper import db as PDB
        from matlens_kit.paper.engine import PaperEngine

        dbp = tmp_path / "p2.db"
        monkeypatch.setattr(PDB, "_PAPER_DB", str(dbp))

        pid = PDB.create_paper("正常论文", "research", "主题")["id"]
        PDB.save_stage_content(pid, "outline", "大纲", None)
        PDB.set_stage_status(pid, "outline", "done")

        body = "本文提出 2 mol% Ca 共掺杂设计窗口，峰值电导率 0.45 S/cm @900 °C。" * 20

        eng = PaperEngine(runner=lambda s, p, c, e: (body, []))
        res = eng.run_stage(pid, "write")

        assert res["ok"] is True
        assert res["status"] == "done"
        assert PDB.get_paper(pid)["stages"]["write"]["content"] == body