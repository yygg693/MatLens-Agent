# -*- coding: utf-8 -*-
"""论文工坊设置接通测试（纯函数级，不调 LLM）。

覆盖契约第 6 节 papers 段：
(a) 四种 cite_style 导出 markdown 的真实排版差异；
(b) 默认导出（不带 fmt）随 settings papers.export_format 变化，显式 fmt 覆盖设置；
(c) render_prompt 在 formal/concise/detailed 三种 tone 下包含对应风格指令；
(d) autosave 开关改变引擎自动草稿落库行为（手动保存不受影响）。

隔离：
- paper/db._PAPER_DB 在 import 时固定为 ~/.matlens/papers.db（不读 MATLENS_HOME），
  故 monkeypatch PDB._PAPER_DB 指向临时库，绝不落真实库。
- settings_store 读 $MATLENS_HOME/config.yaml（tmp_mat_home 夹具隔离），
  用写 config.yaml 的方式控制 papers.export_format / autosave。
"""
from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient

from matlens_kit.paper import db as PDB
from matlens_kit.paper.engine import PaperEngine
from matlens_kit.paper.export import export_paper, export_markdown
from matlens_kit.paper.prompts import render_prompt


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
@pytest.fixture()
def tmp_paper_db(tmp_path, monkeypatch):
    """把 PDB._PAPER_DB 指到临时库（引擎/API 都经此全局）。"""
    db_path = str(tmp_path / "settings_papers.db")
    monkeypatch.setattr(PDB, "_PAPER_DB", db_path)
    return db_path


def _write_papers_config(mat_home, **kv):
    """写 $MATLENS_HOME/config.yaml 的 papers 段（settings_store 实时读）。"""
    (mat_home / "config.yaml").write_text(
        yaml.safe_dump({"papers": kv}, allow_unicode=True), encoding="utf-8"
    )


def _sample_refs():
    return [
        {
            "title": "Graphene oxide membranes for water purification",
            "authors": "Zhang Wei; Li Ming; Wang Fang",
            "year": "2023",
            "source": "OpenAlex·Journal of Membrane Science",
            "doi": "10.1016/j.memsci.2023.01001",
        },
        {
            "title": "MOF-derived porous carbon for CO2 capture",
            "authors": "Liu Chen; Zhao Jun",
            "year": "2022",
            "source": "OpenAlex·Carbon",
            "doi": "10.1016/j.carbon.2022.05.010",
        },
    ]


def _make_paper(tmp_paper_db):
    """建一个含 search refs + write 正文的论文项目（前置步全部 done）。"""
    p = PDB.create_paper("测试论文", paper_type="research", topic="二维膜分离")
    pid = p["id"]
    PDB.save_stage_content(pid, "search", "检索概述正文", _sample_refs())
    PDB.set_stage_status(pid, "search", "done")
    PDB.save_stage_content(pid, "topic", "选题正文")
    PDB.set_stage_status(pid, "topic", "done")
    PDB.save_stage_content(pid, "outline", "大纲正文")
    PDB.set_stage_status(pid, "outline", "done")
    PDB.save_stage_content(pid, "write", "这是写入章节正文 [1].")
    PDB.set_stage_status(pid, "write", "done")
    return PDB.get_paper(pid)


# ---------------------------------------------------------------------------
# (a) 四种 cite_style 导出 markdown 的标志性差异
# ---------------------------------------------------------------------------
def _refs_block(md: str) -> str:
    """从导出 markdown 里抽出文末参考文献小节文本（正文里的 [n] 不算）。"""
    for h in ("## 参考文献", "## References", "### 参考文献"):
        if h in md:
            return md.split(h, 1)[1]
    return ""


def test_four_cite_styles_render_differently(tmp_paper_db):
    p = _make_paper(tmp_paper_db)

    gb = _refs_block(export_markdown(p, cite_style="gb7714"))
    ieee = _refs_block(export_markdown(p, cite_style="ieee"))
    apa = _refs_block(export_markdown(p, cite_style="apa"))
    acs = _refs_block(export_markdown(p, cite_style="acs"))

    # gb7714 / ieee：编号制，含 [1]；gb7714 带文献类型标识 [J]
    assert "[1]" in gb and "[J]" in gb
    assert "[1]" in ieee
    # ieee 标题加双引号："Title," 形态
    assert '"Graphene oxide membranes for water purification,"' in ieee
    # apa：作者-年制，含 (year)，且参考文献区无编号 [1]
    assert "(2023)" in apa
    assert "[1]" not in apa
    # acs：编号制 + 多作者分号分隔（authors 串里含 ;）+ 句点分段
    assert "[1]" in acs
    assert "Zhang Wei; Li Ming; Wang Fang" in acs


def test_export_paper_cite_style_param_roundtrip(tmp_paper_db):
    p = _make_paper(tmp_paper_db)
    for style in ("gb7714", "ieee", "apa", "acs"):
        res = export_paper(p, "md", cite_style=style)
        assert res["ok"] is True
        assert "参考文献" in res["content"]


# ---------------------------------------------------------------------------
# (b) 默认导出路由随 settings.export_format 变化；显式 fmt 覆盖
# ---------------------------------------------------------------------------
def test_default_export_follows_settings(tmp_mat_home, tmp_paper_db):
    p = _make_paper(tmp_paper_db)
    pid = p["id"]
    client = TestClient(app)

    # 默认 export_format = md
    _write_papers_config(tmp_mat_home, export_format="md")
    r = client.get(f"/api/papers/{pid}/export")
    assert r.status_code == 200
    assert "text/markdown" in r.headers["content-type"]
    assert "参考文献" in r.text

    # 改成 tex → 默认路由返回 LaTeX
    _write_papers_config(tmp_mat_home, export_format="tex")
    r = client.get(f"/api/papers/{pid}/export")
    assert r.status_code == 200
    assert "x-tex" in r.headers["content-type"]

    # 显式 /export/md 覆盖当前默认（tex）→ 仍返回 markdown
    r = client.get(f"/api/papers/{pid}/export/md")
    assert r.status_code == 200
    assert "text/markdown" in r.headers["content-type"]


def test_default_export_404_on_missing_paper(tmp_mat_home, tmp_paper_db):
    client = TestClient(app)
    _write_papers_config(tmp_mat_home, export_format="md")
    r = client.get("/api/papers/nonexistent/export")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# (c) render_prompt 三种 tone 注入对应风格指令
# ---------------------------------------------------------------------------
def _write_ctx():
    return {
        "topic": "二维氧化石墨烯膜",
        "paper_type": "研究论文",
        "outline_text": "## 引言\n## 方法",
        "section": "全文",
        "word_count": "3000",
        "section_points": "",
        "refs_text": "[1] Graphene oxide · Zhang Wei · 2023",
        "existing_text": "",
        "continuation": "",
    }


def test_render_prompt_tone_variants():
    ctx = _write_ctx()
    formal = render_prompt("write", {**ctx, "tone": "formal"})
    concise = render_prompt("write", {**ctx, "tone": "concise"})
    detailed = render_prompt("write", {**ctx, "tone": "detailed"})

    assert "正式学术" in formal
    assert "简洁精炼" in concise
    assert "详细深入" in detailed
    # 三者正文不同（风格指令确实注入）
    assert formal != concise
    assert concise != detailed


def test_render_prompt_cite_style_note_injected():
    ctx = _write_ctx()
    out = render_prompt("write", {**ctx, "cite_style": "ieee"})
    assert "IEEE" in out


# ---------------------------------------------------------------------------
# (d) autosave 开关 gate 引擎自动草稿落库
# ---------------------------------------------------------------------------
def _run_write_with_fake_engine(mat_home, autosave):
    _write_papers_config(mat_home, autosave=autosave)
    pid = PDB.create_paper("自动保存测试")["id"]
    for s in ("topic", "search", "outline"):
        PDB.set_stage_status(pid, s, "done")

    def fake_runner(stage, pid_, ctx, cb):
        return ("GENERATED DRAFT CONTENT", [{"title": "whitelist ref"}])

    eng = PaperEngine(runner=fake_runner)
    result = eng.run_stage(pid, "write")
    return pid, result


def test_autosave_true_persists_draft(tmp_mat_home, tmp_paper_db):
    pid, result = _run_write_with_fake_engine(tmp_mat_home, autosave=True)
    assert result["status"] == "done"
    got = PDB.get_paper(pid)
    assert got["stages"]["write"]["content"] == "GENERATED DRAFT CONTENT"
    # refs 白名单照常落库
    assert got["stages"]["write"]["refs"] == [{"title": "whitelist ref"}]


def test_autosave_false_skips_draft_persist(tmp_mat_home, tmp_paper_db):
    pid, result = _run_write_with_fake_engine(tmp_mat_home, autosave=False)
    # 阶段仍标记完成
    assert result["status"] == "done"
    got = PDB.get_paper(pid)
    # 生成草稿正文不自动落库
    assert got["stages"]["write"]["content"] != "GENERATED DRAFT CONTENT"
    # 但结构性 refs（白名单）仍保留
    assert got["stages"]["write"]["refs"] == [{"title": "whitelist ref"}]
    # 手动保存仍可写入（不受开关影响）
    PDB.save_stage_content(pid, "write", "MANUAL SAVED", None)
    assert PDB.get_paper(pid)["stages"]["write"]["content"] == "MANUAL SAVED"


# TestClient app（延后 import，避免收集期副作用）
from matlens_kit.api.server import app  # noqa: E402
