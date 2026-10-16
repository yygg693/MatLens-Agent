# -*- coding: utf-8 -*-
"""四种题录格式真实样例验证（2026-10-16）。"""
import sys

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
%U http://kns.cnki.net/kcms/detail/detail.aspx?dbcode=CJFD
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
%T Preparation of high-entropy oxide ceramics by solid-state reaction
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
AB  - Sm-doped ceria exhibits high ionic conductivity at intermediate temperatures.
ER  -

TY  - JOUR
AU  - Smith, John
TI  - Second entry without abstract
JO  - Nature Materials
PY  - 2020
DO  - 10.1038/s41563-019-0520-5
ER  -
"""

BIBTEX = """@article{zhang2023,
  author = {Zhang, Wei and Li, Ming and Wang, Fang},
  title = {Preparation of High-Entropy Oxide Ceramics by Solid-State Reaction},
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
  booktitle = {Proceedings of the 5th National Solid State Battery Conference},
  year = {2022},
  pages = {45--52}
}
"""


def show(name, text, fname=""):
    r = bib.parse_bibliography(text, fname)
    print(f"=== {name}  格式={r['format']}  条数={r['count']}")
    for i, it in enumerate(r["items"], 1):
        print(f"  [{i}] {it.get('title','?')[:56]}")
        print(f"      作者: {it.get('authors')}")
        print(f"      出处: {it.get('journal') or it.get('booktitle')} | {it.get('year')} "
              f"| v{it.get('volume','')} n{it.get('issue','')} p{it.get('pages','')}")
        print(f"      DOI: {it.get('doi','(无)')}")
        kw = it.get("keywords")
        if kw:
            print(f"      关键词: {kw}")
        if it.get("abstract"):
            print(f"      摘要: {it['abstract'][:50]}...")
    if r["errors"]:
        print("  错误:", r["errors"])
    print()


print("##### 重点验证：RefWorks 的 %A 张伟%0 李明（%0 既是类型也是分隔符）\n")
show("知网 RefWorks", REFWORKS_CNKI, "cnki.txt")
show("EndNote", ENDNOTE, "x.enw")
show("RIS（2 条）", RIS, "x.ris")
show("BibTeX（2 条）", BIBTEX, "x.bib")

md = bib.to_markdown(bib.parse_bibliography(RIS)["items"])
print("### Markdown 输出预览")
print(md[:300])