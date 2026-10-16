# -*- coding: utf-8 -*-
"""丢图检测回归测试（quality._figure_missing_issues）。

真事故（2026-10-14 v6）：模型把该画图的数据全改写成表格，
正文「图 N」交叉引用 12 处但零图注行 → 导出 docx 时内嵌图 0 张（v5 有 2 张）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from matlens_kit.paper.quality import _figure_missing_issues

# 一份有篇幅、有多表、但零图注的正文（v6 形态）
_TABLES_ONLY = (
    "\n\n".join(
        f"**表 {i} 某组参数**（n = 3，拟议值，待实验确认）\n| A | B |\n| 1 | 2 |"
        for i in range(1, 8)
    )
    + "\n\n"
    + "结果讨论正文需要足够篇幅以越过丢图检测的 3000 字门槛。" * 200
    + "\n\n本节小结：如上表所示，本体相电导随温度升高而增大，如图 3 所示、表 7 给出对照。"
)

# 同一份正文，但带图注行（v5 形态）
_WITH_CAPTIONS = (
    _TABLES_ONLY
    + "\n\n**图 1** 单电池结构示意图（Schematic）：NiO-GDC 阳极支撑｜电解质｜阴极。\n"
    + "\n\n**图 2** 机制示意图（Schematic）：Ca 晶界偏析 → 致密化链路。\n"
)


class TestNoCaptionMeansLostFigures:
    def test_tables_only_draft_flagged(self):
        """多表 + 有篇幅 + 零图注 → 必须报丢图。"""
        issues = _figure_missing_issues(_TABLES_ONLY)
        assert len(issues) == 1
        assert issues[0]["location"] == "图件"
        assert "图注" in issues[0]["issue"]

    def test_cross_reference_does_not_count_as_caption(self):
        """正文里「如图 3 所示」这类交叉引用不代表规划了图（关键回归点）。"""
        assert "图 3" in _TABLES_ONLY          # 确实有交叉引用
        issues = _figure_missing_issues(_TABLES_ONLY)
        assert issues                          # 但仍应判定为丢图
        assert "零图注" in issues[0]["issue"]  # 且理由是"无图注"而非"无标注"

    def test_with_captions_not_flagged(self):
        """有图注行 → 不报丢图（不得误伤 v5 这类正常成稿）。"""
        assert _figure_missing_issues(_WITH_CAPTIONS) == []


class TestNoFalsePositives:
    def test_short_draft_not_flagged(self):
        """篇幅不足的草稿不该被判丢图（可能还在写）。"""
        short = "**表 1 参数**\n| A | B |\n| 1 | 2 |\n\n**表 2 参数**\n正文。"
        assert _figure_missing_issues(short) == []

    def test_few_tables_not_flagged(self):
        """表格少 + 有图注语境 → 保持原行为，不硬凑告警。"""
        few = "结果讨论。" * 400 + "\n\n如图 1 所示，Schematic 示意图。"
        assert _figure_missing_issues(few) == []


class TestLegacyBehaviourKept:
    def test_fig_ref_without_marker_still_flagged(self):
        """原模式 1 保留：引用图号但无 Schematic/待获取标注 → 告警。

        注意这份草稿篇幅短（<3000 字）且表格引用少，走的是旧路径，
        与模式 2（丢图）是两套判据，互不干扰。
        """
        draft = "结果如表 1 与图 1、图 2 所示，具体数值见附录。" * 20
        issues = _figure_missing_issues(draft)
        assert len(issues) == 1
        assert "无图片文件" in issues[0]["issue"]

    def test_schematic_marker_passes(self):
        draft = "结果如图 1 所示（Schematic）。" * 300
        assert _figure_missing_issues(draft) == []