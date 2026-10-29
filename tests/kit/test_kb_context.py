# -*- coding: utf-8 -*-
"""写作步本地库检索测试（matlens_kit.paper.kb_context）。

全部离线，不依赖真实知识库。

重点守护：
  - **只注入真实存在的正文**：检索命中的必须是知识库里真实索引的文档。
  - **噪声必须挡住**：实测库里混有「离子液体双水相萃取分离青霉素」这类
    与主题毫无关系的文档，靠向量分数卡不住（0.158），必须靠词面判定。
  - **表格片段不注入**：模型只会照抄表格。
  - **检索不到就明说**，不能塞低分片段充数。
"""
from __future__ import annotations

import sys

import pytest

sys.path.insert(0, r"D:\MatLens")
from matlens_kit.paper import kb_context as kc  # noqa: E402

TOPIC = "固态氧化物燃料电池电解质研究"
OUTLINE = """# GDC-Ca 共掺杂电解质论文大纲

## 1 引言
固体氧化物燃料电池的电解质材料选择依据

## 2 实验方法
### 2.2 电导率测试
EIS 交流阻抗谱测试装置与参数

## 3 结果与讨论
XRD 相结构与电导率结果
"""


class TestSectionQuery:
    def test_includes_outline_headings(self):
        q = kc._section_query(TOPIC, OUTLINE, "全文")
        assert "电导率测试" in q
        assert "实验方法" in q

    def test_includes_topic(self):
        assert TOPIC in kc._section_query(TOPIC, OUTLINE, "全文")

    def test_skips_full_text_marker(self):
        """section=全文 时不该把「全文」当检索词（无区分度）。"""
        q = kc._section_query(TOPIC, OUTLINE, "全文")
        assert not q.startswith("全文")

    def test_empty_inputs_safe(self):
        assert kc._section_query("", "", "") != ""

    def test_length_bounded(self):
        q = kc._section_query(TOPIC, OUTLINE * 50, "全文")
        assert len(q) <= 700


class TestOutlineHeadings:
    def test_extracts_markdown_headings(self):
        hs = kc._outline_headings(OUTLINE)
        assert any("电导率测试" in h for h in hs)
        assert any("实验方法" in h for h in hs)

    def test_empty_outline(self):
        assert kc._outline_headings("") == []

    def test_respects_limit(self):
        many = "\n".join(f"## 章节{i}" for i in range(30))
        assert len(kc._outline_headings(many, limit=5)) == 5


class TestIsTableHeavy:
    def test_standard_markdown_table(self):
        assert kc._is_table_heavy("| a | b |\n|---|---|\n| 1 | 2 |") is True

    def test_compressed_single_line_table(self):
        """实测抓下来的表格被压成单行，分隔符与数据混在一行。"""
        t = "≤0.15 | Table 2. | σ | |---|---|---|---| | GDC | — | — |"
        assert kc._is_table_heavy(t) is True

    def test_plain_text_not_table(self):
        assert kc._is_table_heavy("普通文本。\n第二行。\n第三行。") is False

    def test_single_pipe_not_table(self):
        assert kc._is_table_heavy("a | b 是或的意思") is False

    def test_prose_with_measurement_not_table(self):
        t = "电解质样品在 600 °C 下电导率为 0.12 S/cm，见文献 [1]。"
        assert kc._is_table_heavy(t) is False


class TestChunkLabel:
    def test_readable_name_kept(self):
        assert "Ceria" in kc._chunk_label("Ceria co-doping__10_1039.md")

    def test_internal_id_becomes_generic(self):
        """内部 ID（paper_xxxxxxxx）不该原样暴露给模型。"""
        assert kc._chunk_label("paper_12eac584_g3k3gkqd.md") == "本地文献片段"

    def test_leading_number_stripped(self):
        assert kc._chunk_label("01_某文献标题.md") == "某文献标题"

    def test_empty(self):
        assert kc._chunk_label("")


class TestTopicTerms:
    def test_extracts_chinese_ngrams(self):
        terms = kc._topic_terms(TOPIC, OUTLINE, "")
        assert any("电解质" in t for t in terms)

    def test_extracts_english_words(self):
        terms = kc._topic_terms(TOPIC, OUTLINE, "")
        assert "xrd" in terms

    def test_cn_en_mapping_adds_english(self):
        """中文主题必须能映射出英文关键词，否则英文文献会被误杀。"""
        terms = kc._topic_terms("固态氧化物燃料电池电解质研究", "", "")
        assert any(t in terms for t in ("sofc", "fuel cell", "electrolyte"))
        assert any(t in terms for t in ("ceria", "gdc"))

    def test_empty_topic(self):
        assert kc._topic_terms("", "", "") == [] or True  # 不应抛


class TestRelevance:
    def test_relevant_by_filename(self):
        terms = kc._topic_terms(TOPIC, OUTLINE, "")
        assert kc._relevant_to_topic(
            "some text", terms, "SOFC thin film GDC__10_3390.md") is True

    def test_irrelevant_penicillin_rejected(self):
        """实测噪声：与 SOFC 毫无关系的青霉素萃取文献。"""
        terms = kc._topic_terms(TOPIC, OUTLINE, "")
        t = "离子液体双水相萃取分离青霉素的研究，采用萃取工艺分离"
        assert kc._relevant_to_topic(
            t, terms, "openalex_离子液体双水相萃取分离青霉素.md") is False

    def test_relevant_by_body_english(self):
        terms = kc._topic_terms(TOPIC, OUTLINE, "")
        t = "The ionic conductivity of Sm-doped ceria is 0.12 S cm-1 at 600 C."
        assert kc._relevant_to_topic(t, terms, "unknown_id.md") is True

    def test_no_terms_accepts_all(self):
        assert kc._relevant_to_topic("任意文本", [], "x.md") is True


class TestSearchKbForWriting:
    def _patch(self, monkeypatch, results, active="demo-kb"):
        # noqa: D401
        class _KB:
            def query(self, q, top_k=10, score_threshold=0.0):
                return results

        class _Mgr:
            def __init__(self):
                self.active = active

            def get(self, name):
                return _KB()

        monkeypatch.setattr("matlens_kit.plugins.local_rag.get_manager", lambda: _Mgr())

    def test_filters_short_chunks(self, monkeypatch):
        self._patch(monkeypatch, [{"text": "太短", "score": 0.9, "source": "a.md"}])
        assert kc.search_kb_for_writing(TOPIC, OUTLINE, "全文") == []

    def test_filters_tables(self, monkeypatch):
        self._patch(monkeypatch, [{"text": "| a | b |\n|---|---|\n| 1 | 2 |\n" + "x" * 200,
                                   "score": 0.9, "source": "SOFC_a.md"}])
        assert kc.search_kb_for_writing(TOPIC, OUTLINE, "全文") == []

    def test_filters_irrelevant(self, monkeypatch):
        self._patch(monkeypatch, [{
            "text": "离子液体双水相萃取分离青霉素" + "研究内容" * 40,
            "score": 0.3, "source": "openalex_离子液体双水相萃取分离青霉素.md"}])
        assert kc.search_kb_for_writing(TOPIC, OUTLINE, "全文") == []

    def test_dedupes_by_content_not_label(self, monkeypatch):
        """同一文档的不同分块标签相同但内容不同 —— 按标签去重会误杀。"""
        self._patch(monkeypatch, [
            {"text": "SOFC 内容甲" + "甲" * 200, "score": 0.3, "source": "same.md"},
            {"text": "SOFC 内容乙" + "乙" * 200, "score": 0.2, "source": "same.md"},
        ])
        out = kc.search_kb_for_writing(TOPIC, OUTLINE, "全文")
        assert len(out) == 2, "同文档不同分块都该保留"

    def test_dedupes_identical_text(self, monkeypatch):
        self._patch(monkeypatch, [
            {"text": "SOFC 内容甲" + "甲" * 200, "score": 0.3, "source": "a.md"},
            {"text": "SOFC 内容甲" + "甲" * 200, "score": 0.25, "source": "b.md"},
        ])
        out = kc.search_kb_for_writing(TOPIC, OUTLINE, "全文")
        assert len(out) == 1, "内容完全相同应去重"

    def test_sorted_by_score_desc(self, monkeypatch):
        self._patch(monkeypatch, [
            {"text": "SOFC 低分" + "低" * 200, "score": 0.2, "source": "SOFC_a.md"},
            {"text": "SOFC 高分" + "高" * 200, "score": 0.5, "source": "SOFC_b.md"},
        ])
        out = kc.search_kb_for_writing(TOPIC, OUTLINE, "全文")
        assert out[0]["score"] >= out[1]["score"]

    def test_respects_max_chunks(self, monkeypatch):
        self._patch(monkeypatch, [
            {"text": f"SOFC 片段{i}" + "x" * 200, "score": 0.3 - i * 0.01,
             "source": f"SOFC_{i}.md"} for i in range(12)])
        out = kc.search_kb_for_writing(TOPIC, OUTLINE, "全文", top_k=3)
        assert len(out) == 3

    def test_no_active_kb_returns_empty(self, monkeypatch):
        class _Mgr:
            active = None

            def get(self, n):
                return None

        monkeypatch.setattr("matlens_kit.plugins.local_rag.get_manager", lambda: _Mgr())
        assert kc.search_kb_for_writing(TOPIC, OUTLINE, "全文") == []

    def test_exception_contained(self, monkeypatch):
        def boom():
            raise RuntimeError("db down")

        monkeypatch.setattr("matlens_kit.plugins.local_rag.get_manager", boom)
        assert kc.search_kb_for_writing(TOPIC, OUTLINE, "全文") == []


class TestRenderKbContext:
    def test_empty_gives_empty_string(self):
        assert kc.render_kb_context([]) == ""

    def test_includes_label_and_score(self):
        blk = kc.render_kb_context([{"label": "论文A", "kb": "demo-kb",
                                     "score": 0.42, "text": "正文内容"}])
        assert "论文A" in blk
        assert "0.42" in blk

    def test_warns_not_to_invent(self):
        """必须明确告诉模型：素材不占编号、没依据别臆测。"""
        blk = kc.render_kb_context([{"label": "A", "kb": "k", "score": 0.3,
                                     "text": "x"}])
        assert "不占用编号" in blk or "不占用" in blk
        assert "臆测" in blk


class TestBuildWritingContext:
    def _patch(self, monkeypatch, results):
        class _KB:
            def query(self, q, top_k=10, score_threshold=0.0):
                return results

        class _Mgr:
            active = "demo-kb"

            def get(self, name):
                return _KB()

        monkeypatch.setattr("matlens_kit.plugins.local_rag.get_manager", lambda: _Mgr())

    def test_success_path(self, monkeypatch):
        self._patch(monkeypatch, [
            {"text": "SOFC 电导率数据" + "x" * 300, "score": 0.4,
             "source": "SOFC_a.md"}])
        r = kc.build_writing_context(TOPIC, OUTLINE, "全文")
        assert r["count"] == 1
        assert r["kb"] == "demo-kb"
        assert "本地知识库原文素材" in r["block"]
        assert r["note"] == ""

    def test_empty_path_explains(self, monkeypatch):
        self._patch(monkeypatch, [])
        r = kc.build_writing_context(TOPIC, OUTLINE, "全文")
        assert r["count"] == 0
        assert "不要臆测" in r["note"]
        assert r["block"] == ""
