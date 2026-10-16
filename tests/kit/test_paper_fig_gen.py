# -*- coding: utf-8 -*-
"""fig_gen.py 示意图生成器测试。

只用 stdlib + pytest + matplotlib（已在 venv）；无网络。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from matlens_kit.paper.fig_gen import gen_figures


WRITE_WITH_CAPTIONS = """# Test Paper

## Abstract

This is a test.

**Keywords:** a; b

## 1. Introduction

Some text here.

Figure 1. Schematic cross-section of the anode-supported cell with electrolyte layer.

Figure 2. Proposed mechanism diagram for grain-boundary space-charge layer.

Figure 3. XRD patterns of all samples.

Figure 4. Nyquist and DRT plots at 600 C.
"""

WRITE_NO_CAPTIONS = """# Test Paper

## Abstract

No figures here.
"""


def test_gen_figures_cell_and_mechanism(tmp_path: Path):
    out = str(tmp_path / "figs")
    results = gen_figures(WRITE_WITH_CAPTIONS, out)
    # 4 条图注：Fig1 cell, Fig2 mechanism, Fig3 data, Fig4 data
    assert len(results) == 4
    by_num = {r["num"]: r for r in results}

    # Fig1 cell → generated
    assert by_num[1]["kind"] == "cell"
    assert by_num[1]["status"] == "generated"
    assert by_num[1]["path"] and os.path.isfile(by_num[1]["path"])
    assert by_num[1]["path"].endswith(".png")

    # Fig2 mechanism → generated
    assert by_num[2]["kind"] == "mechanism"
    assert by_num[2]["status"] == "generated"
    assert by_num[2]["path"] and os.path.isfile(by_num[2]["path"])

    # Fig3 XRD → data → skipped
    assert by_num[3]["kind"] == "data"
    assert by_num[3]["status"] == "skipped"
    assert by_num[3]["path"] is None

    # Fig4 Nyquist → data → skipped
    assert by_num[4]["kind"] == "data"
    assert by_num[4]["status"] == "skipped"


def test_gen_figures_png_size(tmp_path: Path):
    out = str(tmp_path / "figs")
    results = gen_figures(WRITE_WITH_CAPTIONS, out)
    generated = [r for r in results if r["status"] == "generated"]
    assert len(generated) == 2
    for r in generated:
        sz = os.path.getsize(r["path"])
        # PNG 至少 5KB（150 dpi 示意图）
        assert sz > 5000, f"{r['path']} too small: {sz}"


def test_gen_figures_empty(tmp_path: Path):
    out = str(tmp_path / "figs")
    assert gen_figures("", out) == []
    assert gen_figures("   \n\n", out) == []


def test_gen_figures_no_captions(tmp_path: Path):
    out = str(tmp_path / "figs")
    results = gen_figures(WRITE_NO_CAPTIONS, out)
    assert results == []


def test_gen_figures_creates_out_dir(tmp_path: Path):
    out = str(tmp_path / "nonexistent" / "figs")
    results = gen_figures(WRITE_WITH_CAPTIONS, out)
    assert len(results) == 4
    assert os.path.isdir(out)
