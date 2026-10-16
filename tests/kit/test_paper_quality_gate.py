# -*- coding: utf-8 -*-
"""导出质量门回归测试（paper/quality_gate.py）。

核心取向：**警告不阻断**。门只在真有问题时提示，且未跑 quality 步不判。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from matlens_kit.paper.quality_gate import DEFAULT_MIN_SCORE, evaluate, warning_message
import matlens_kit.paper.quality_gate as _qg

#: 原函数引用（monkeypatch 前保存，供桩函数委托，避免无限递归）
qg_orig = evaluate


def _paper(draft: str = "", quality_status: str = "pending", refs=None, **kw):
    p = {
        "id": "testpid",
        "title": "测试论文",
        "stages": {
            "write": {"status": "done", "content": draft},
            "quality": {"status": quality_status, "content": "报告"},
            "search": {"status": "done", "refs": refs or []},
        },
    }
    p.update(kw)
    return p


# 一份足够长的正文，避免「篇幅偏短」等噪声影响判定焦点
GOOD_DRAFT = (
    "# 绪论\n研究背景与意义。" * 80
    + "\n# 实验方法\n实验装置与测试条件。" * 80
    + "\n# 结果与讨论\n数据分析。" * 80
    + "\n# 结论\n总结。" * 80
)


def _low_score_draft() -> str:
    """造一份能被质检打出低分的正文。

    质检以「扣分制」为主，短文反而可能靠基础分拿到 及格线以上
    （实测：'很短的一篇。' → 65 分）。所以这里显式压低阈值来验证判定逻辑，
    而不是依赖"看起来差"的文本。
    """
    return "空壳论文，没有章节没有数据没有引用。"


class TestNotChecked:
    def test_quality_not_run_passes(self):
        """未跑质量巡检 → 无据不判，放行。"""
        v = evaluate(_paper(draft=GOOD_DRAFT, quality_status="pending"))
        assert v["passed"] is True
        assert v["checked"] is False
        assert v["reasons"] == []

    def test_quality_error_passes(self):
        v = evaluate(_paper(draft=GOOD_DRAFT, quality_status="error"))
        assert v["passed"] is True
        assert v["checked"] is False

    def test_empty_write_passes(self):
        v = evaluate(_paper(draft="", quality_status="done"))
        assert v["passed"] is True
        assert v["checked"] is False


class TestLowScore:
    def test_threshold_violation_triggers_warning(self):
        """显式阈值高于实际分数 → 警告（按 v5 实测 48 分这个量级验证）。"""
        v = evaluate(
            _paper(draft=_low_score_draft(), quality_status="done"),
            min_score=90,
        )
        assert v["checked"] is True
        assert v["passed"] is False
        assert v["score"] < 90
        assert any("低于阈值" in r for r in v["reasons"])

    def test_warning_does_not_block_export(self, monkeypatch):
        """关键取向：门只警告，导出必须仍能进行。"""
        import matlens_kit.paper.export as export_mod
        import matlens_kit.paper.quality_gate as qg

        p = _paper(draft=_low_score_draft(), quality_status="done")
        p["title"] = "低分论文"
        # export_paper 内部动态 import quality_gate，故 patch 模块属性即可生效
        monkeypatch.setattr(
            qg, "evaluate", lambda paper, **kw: qg_orig(paper, min_score=90, **kw)
        )
        res = export_mod.export_paper(p, "md")

        assert res["ok"] is True                       # 没被拦住
        assert res["content"]                          # 正文照常导出
        assert res.get("warning")                      # 但带警告
        assert res["quality_gate"]["passed"] is False


class TestForce:
    def test_force_suppresses_warning(self):
        from matlens_kit.paper.export import export_paper

        p = _paper(draft="很短的一篇。", quality_status="done")
        res = export_paper(p, "md", force=True)
        assert res["ok"] is True
        assert "warning" not in res


class TestConfigurableThreshold:
    def test_higher_threshold_flags_good_draft(self):
        """阈值可调：把阈值拉到100，正常正文也会被提示。"""
        v = evaluate(
            _paper(draft=GOOD_DRAFT, quality_status="done"),
            min_score=100,
        )
        assert v["passed"] is False
        assert "100" in v["reasons"][0]

    def test_disabled_gate_always_passes(self):
        v = evaluate(_paper(draft="很短的一篇。", quality_status="done"), enabled=False)
        assert v["passed"] is True


class TestWarningMessage:
    def test_empty_when_passed(self):
        assert warning_message({"passed": True, "checked": True}) == ""

    def test_empty_when_not_checked(self):
        assert warning_message({"passed": True, "checked": False}) == ""

    def test_renders_reasons(self):
        msg = warning_message(
            {
                "passed": False,
                "checked": True,
                "reasons": ["质量评分 48/100 低于阈值 60"],
                "blocking": ["[数值自洽] 厚度与 ASR 不自洽 → 建议：重新核算"],
            }
        )
        assert "48/100" in msg
        assert "数值自洽" in msg
        assert "质量巡检" in msg


class TestResilience:
    def test_check_quality_exception_does_not_block(self, monkeypatch):
        """质检异常不得挡住导出（门是辅助，不是关卡）。"""
        from matlens_kit.paper import quality_gate

        def _boom(*a, **k):
            raise RuntimeError("质检炸了")

        monkeypatch.setattr(quality_gate, "check_quality", _boom)
        v = evaluate(_paper(draft=GOOD_DRAFT, quality_status="done"))
        assert v["passed"] is True
        assert v["checked"] is False
        assert v["reasons"]          # 说明跳过原因，而非静默

    def test_export_survives_gate_error(self, monkeypatch):
        """门自身抛错时导出仍须成功。"""
        from matlens_kit.paper import export as export_mod

        orig = export_mod.__dict__.get("resolve_cite_style")

        import matlens_kit.paper.quality_gate as qg

        def _boom2(*a, **k):
            raise RuntimeError("门炸了")

        monkeypatch.setattr(qg, "evaluate", _boom2)
        p = _paper(draft="短。", quality_status="done")
        res = export_mod.export_paper(p, "md")
        assert res["ok"] is True
        assert orig is not None