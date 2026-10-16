# -*- coding: utf-8 -*-
"""题录解析模块测试（matlens_kit.rag.bibtex）。

全部离线，用各数据库官方导出格式的真实样例（尤其知网 RefWorks）。

⚠️ 重点守护两个实测踩过的坑：
  1. ``%A 张伟%0 李明%0 王芳`` —— %0 既是类型标记又是多条分隔符
  2. ``%0`` 后面跟的是**数字 0**，若正则要求字母则永远匹配不到类型行，
     导致多记录文件被并成一条（曾实测只解析出 1 条而不是 2 条）
"""
from __future__ import annotations

import sys

import pytest

sys.path.insert(0, r"D:\MatLens")
from matlens_kit.rag import bibtex as bib  # noqa: E402

REFWORKS_CNKI = """%0 Journal Article
%A 张伟%0 李明%0 王芳
%T 基于固相反应法制备高熵氧化物陶瓷的研究
%J 材料工程学报
%D 2023
%V 55
%N 3
%P 112-120
%R DOI:10.1385/cnki.issn.1004-0937.2023.03.112
%X 高熵氧化物; 固相反应; 陶瓷
%0 Book Section
%A 赵磊
%T 电化学阻抗谱在固体氧化物燃料电池中的应用
%B 第五届全国固体电池学术会议论文集
%C 北京
%D 2022
%P 45-52
"""

ENDNOTE = """%0 Journal Article
%A Zhang, Wei
%A Li, Ming
%T Preparation of high-entropy oxide ceramics
%J Journal of Materials Engineering
%D 2023
%V 55
%N 3
%P 112-120
%R 10.1385/cnki.issn.1004-0937.2023.03.112
"""

RIS = """TY  - JOUR
AU  - Zhang, Wei
AU  - Li, Ming
TI  - Ionic conductivity of Sm-doped ceria
JO  - Journal of Alloys and Compounds
PY  - 2021
VL  - 850
IS  - 2
SP  - 120358
EP  - 120366
DO  - 10.1016/j.jallcom.2020.120358
AB  - Sm-doped ceria exhibits high ionic conductivity.
ER  -

TY  - JOUR
AU  - Smith, John
TI  - Second entry
JO  - Nature Materials
PY  - 2020
DO  - 10.1038/s41563-019-0520-5
ER  -
"""

BIBTEX = """@article{zhang2023,
  author = {Zhang, Wei and Li, Ming and Wang, Fang},
  title = {Preparation of High-Entropy Oxide Ceramics},
  journal = {Journal of Materials Engineering},
  year = {2023},
  volume = {55},
  number = {3},
  pages = {112--120},
  doi = {10.1385/cnki.issn.1004-0937.2023.03.112}
}

@inproceedings{wang2022,
  author = {Wang, Fang},
  title = {Impedance spectroscopy in SOFC},
  booktitle = {Proceedings of the 5th Conference},
  year = {2022},
  pages = {45--52}
}
"""


class TestFormatDetection:
    def test_detect_by_content(self):
        assert bib.detect_format(REFWORKS_CNKI, "x.txt") == "refworks"
        assert bib.detect_format(RIS, "x.ris") == "ris"
        assert bib.detect_format(BIBTEX, "x.bib") == "bibtex"

    def test_detect_by_extension_fallback(self):
        assert bib.detect_format("", "x.bib") == "bibtex"
        assert bib.detect_format("", "x.enw") == "refworks"

    def test_unknown_format(self):
        assert bib.detect_format("随便一段中文", "x.txt") == "unknown"


class TestRis:
    def test_two_records(self):
        items = bib.parse_ris(RIS)
        assert len(items) == 2

    def test_fields(self):
        it = bib.parse_ris(RIS)[0]
        assert it["title"] == "Ionic conductivity of Sm-doped ceria"
        assert it["authors"] == ["Zhang, Wei", "Li, Ming"]
        assert it["journal"] == "Journal of Alloys and Compounds"
        assert it["year"] == "2021"
        assert it["volume"] == "850" and it["issue"] == "2"
        assert it["doi"] == "10.1016/j.jallcom.2020.120358"

    def test_pages_from_sp_ep(self):
        assert bib.parse_ris(RIS)[0]["pages"] == "120358-120366"

    def test_abstract_kept(self):
        assert "Sm-doped ceria" in bib.parse_ris(RIS)[0]["abstract"]

    def test_empty_input(self):
        assert bib.parse_ris("") == []


class TestBibtex:
    def test_two_entries(self):
        assert len(bib.parse_bibtex(BIBTEX)) == 2

    def test_authors_split_by_and(self):
        assert bib.parse_bibtex(BIBTEX)[0]["authors"] == \
            ["Zhang, Wei", "Li, Ming", "Wang, Fang"]

    def test_double_hyphen_pages_normalised(self):
        assert bib.parse_bibtex(BIBTEX)[0]["pages"] == "112-120"

    def test_inproceedings_maps_to_booktitle(self):
        it = bib.parse_bibtex(BIBTEX)[1]
        assert it["booktitle"].startswith("Proceedings")
        assert it["entry_type"] == "conference"

    def test_citation_key_kept(self):
        assert bib.parse_bibtex(BIBTEX)[0]["citation_key"] == "zhang2023"

    def test_nested_braces_in_value(self):
        t = '@a{k, title={A {nested} title}, year={2020}}'
        assert bib.parse_bibtex(t)[0]["title"] == "A {nested} title"


class TestRefworks:
    """知网 RefWorks —— 两个坑都在这里。"""

    def test_multi_record(self):
        """⚠️ 坑 2：%0 类型行必须被识别，否则多条被并成一条。"""
        items = bib.parse_refworks(REFWORKS_CNKI)
        assert len(items) == 2, "应解析出 2 条记录"

    def test_inline_separator_splits_authors(self):
        """⚠️ 坑 1：``%A 张伟%0 李明%0 王芳`` 必须拆成 3 个作者。"""
        it = bib.parse_refworks(REFWORKS_CNKI)[0]
        assert it["authors"] == ["张伟", "李明", "王芳"], \
            f"作者未按 %0 拆分：{it['authors']}"

    def test_no_separator_leak_in_values(self):
        """任何字段值里都不该残留 %0。"""
        for it in bib.parse_refworks(REFWORKS_CNKI):
            for v in list(it.get("authors") or []) + [it.get("title", "")]:
                assert "%0" not in str(v)

    def test_doi_from_note_prefix(self):
        """RefWorks 把 DOI 放在 %R 里且带 'DOI:' 前缀。"""
        it = bib.parse_refworks(REFWORKS_CNKI)[0]
        assert it["doi"] == "10.1385/cnki.issn.1004-0937.2023.03.112"

    def test_keywords_split(self):
        assert bib.parse_refworks(REFWORKS_CNKI)[0]["keywords"] == \
            ["高熵氧化物", "固相反应", "陶瓷"]

    def test_book_section_type_and_booktitle(self):
        it = bib.parse_refworks(REFWORKS_CNKI)[1]
        assert it["entry_type"] == "book_section"
        assert it["booktitle"] == "第五届全国固体电池学术会议论文集"

    def test_endnote_variant(self):
        items = bib.parse_refworks(ENDNOTE)
        assert len(items) == 1
        assert items[0]["authors"] == ["Zhang, Wei", "Li, Ming"]

    def test_numeric_suffix_variant(self):
        """知网会导出 %A3 / %J1 这类变体。"""
        t = "%0 Journal Article\n%A3 张三\n%T 测试标题\n%J1 某期刊\n%D 2024\n"
        it = bib.parse_refworks(t)[0]
        assert it["authors"] == ["张三"]
        assert it["journal"] == "某期刊"

    def test_empty_input(self):
        assert bib.parse_refworks("") == []


class TestFinalize:
    def test_doi_url_normalised(self):
        """RefWorks 的 %R 可能是 doi.org URL 形式，须剥出裸 DOI。"""
        t = "%0 Journal Article\n%T T\n%D 2020\n%R https://doi.org/10.1385/cnki.issn.1004-0937.2023.03.112\n"
        assert bib.parse_refworks(t)[0]["doi"] == "10.1385/cnki.issn.1004-0937.2023.03.112"

    def test_doi_prefix_stripped(self):
        t = "%0 Journal Article\n%T T\n%D 2020\n%R DOI:10.1385/cnki.issn.1004-0937.2023.03.112\n"
        assert bib.parse_refworks(t)[0]["doi"] == "10.1385/cnki.issn.1004-0937.2023.03.112"

    def test_doi_recovered_from_note_text(self):
        """DOI 埋在说明文字里也要能捞出来。"""
        t = "%0 Journal Article\n%T T\n%D 2020\n%R some note 10.9999/xyz.something more\n"
        assert bib.parse_refworks(t)[0]["doi"] == "10.9999/xyz.something"

    def test_short_number_doi_ignored(self):
        """10.x 的注册码须 4-9 位；位数不对不当 DOI 处理（避免误抓）。"""
        t = "%0 Journal Article\n%T T\n%D 2020\n%R note 10.1/x\n"
        it = bib.parse_refworks(t)[0]
        assert not it.get("doi")

    def test_year_extracted_from_verbose(self):
        t = "%0 Journal Article\n%T T\n%D 2023年5月\n"
        assert bib.parse_refworks(t)[0]["year"] == "2023"

    def test_authors_deduped(self):
        t = "%0 Journal Article\n%T T\n%A 张三\n%A 张三\n%A 李四\n"
        assert bib.parse_refworks(t)[0]["authors"] == ["张三", "李四"]


class TestParseBibliography:
    def test_auto_dispatch_all_formats(self):
        for text, cnt in ((REFWORKS_CNKI, 2), (RIS, 2), (BIBTEX, 2), (ENDNOTE, 1)):
            r = bib.parse_bibliography(text, "x.txt")
            assert r["ok"], f"{r['format']} 应解析成功"
            assert r["count"] == cnt, f"{r['format']} 条数应为 {cnt}，实为 {r['count']}"

    def test_plain_text_reports_failure_honestly(self):
        r = bib.parse_bibliography("这是一段普通说明文字，不是题录。", "x.txt")
        assert r["ok"] is False
        assert r["count"] == 0
        assert r["items"] == []

    def test_preview_result_shape(self):
        r = bib.parse_bibliography(RIS, "x.ris")
        assert set(["ok", "format", "count", "items"]) <= set(r)


class TestMarkdown:
    def test_contains_core_fields(self):
        md = bib.to_markdown(bib.parse_ris(RIS))
        assert "Ionic conductivity of Sm-doped ceria" in md
        assert "Zhang, Wei" in md
        assert "10.1016/j.jallcom.2020.120358" in md
        assert "120358-120366" in md

    def test_declares_metadata_only(self):
        """必须注明是题录而非全文，避免误当作全文引用。"""
        md = bib.to_markdown(bib.parse_ris(RIS))
        assert "仅元数据" in md or "非全文" in md

    def test_empty_items(self):
        assert bib.to_markdown([]) == ""

    def test_chinese_content_preserved(self):
        md = bib.to_markdown(bib.parse_refworks(REFWORKS_CNKI))
        assert "高熵氧化物陶瓷" in md
        assert "材料工程学报" in md