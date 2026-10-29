# -*- coding: utf-8 -*-
"""MatLens 论文工坊 · 写作步的本地库检索增强。

为什么需要
----------
检索步抓到的正文进了本地知识库，但**写作时靠 RAG 检索未必命中**
刚抓的那一篇 —— 检索是按语义相似度排的，而写作需要的是
「当前这一节该引用的那几篇」。

所以写作步额外做一次**定向检索**：拿当前章节的主题去查激活库，
把命中的正文片段直接喂进 prompt。

三条硬约束（都是防引用污染）
----------------------------
1. **只注入真实存在的正文**。检索命中的是知识库里真实索引的文档，
   不是模型编的 —— 这是与「凭题录推测结论」的根本区别。
2. **标注来源**。每段片段标出源文件与相似度，模型能看出依据。
3. **检索不到就明说**。查不到就告诉模型「本地库没有相关材料」，
   而不是塞一堆低分片段充数 —— 低分片段反而会误导。

⚠️ 引用白名单（[1..N]）仍然由 ``enforce_refs`` 单独管：
本地库片段**不占用**白名单编号，只是提供原文素材。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

#: 相似度下限：低于此值视为「不相关」，不注入。
#: ⚠️ 实测观察：库里的向量相似度绝对值偏低（相关文献常在 0.15~0.36），
#: 因为分块后单块向量与多词查询的余弦相似度本就不高。
#: 设 0.28 会把真正相关的片段全滤掉（实测 12 条命中只剩 1 条）。
#: 0.12 是实测下"明显相关"的水平；配合「表格过滤 + 数量上限 + 排序」
#: 控制噪声，比设高阈值丢内容更合理。
MIN_SCORE = 0.12

#: 注入 prompt 的片段数上限。再多会挤占上下文且收益递减。
MAX_CHUNKS = 6

#: 每段注入的字符上限。
CHUNK_CHARS = 1400

#: 同一篇文献最多取几段。
#: 否则一篇长文会把名额占满（实测 Ceria co-doping 占了 3/6），
#: 其他文献就没位置了 —— 引用面太窄。
MAX_PER_DOC = 2

#: 章节主题的关键词提取上限（用于构造检索式）。
QUERY_TERMS = 12

#: 主题关键词的最小长度（中文按字，英文按词）。
MIN_TERM_LEN = 2


#: 中文主题 → 常见英文术语/缩写对照。
#: ⚠️ 必要原因：中文主题（「固态氧化物燃料电池电解质研究」）里**没有任何英文词**，
#: 而英文文献的题名全是英文 —— 只靠原主题词判相关性，会把
#: "Free Volumes Associated with Sintering in Gadolinium Doped Ceria"
#: 这类**完全相关**的英文文献判成无关（实测被滤掉）。
#: 这里把中文主题里的常见概念映射成英文关键词。
CN_EN_TERMS = (
    ("燃料电池", ["fuel cell", "sofc", "mcfc"]),
    ("固体氧化物", ["solid oxide", "ceria", "gdc", "ysz", "lsgm"]),
    ("固态氧化物", ["solid oxide", "ceria", "gdc", "ysz", "lsgm"]),
    ("电解质", ["electrolyte"]),
    ("电导率", ["conductivity", "ionic conduction"]),
    ("共掺杂", ["co-doping", "codoping", "doped"]),
    ("掺杂", ["doped", "doping"]),
    ("电极", ["electrode", "anode", "cathode"]),
    ("阻抗谱", ["impedance", "eis", "drt"]),
    ("钙钛矿", ["perovskite"]),
    ("电池", ["battery", "cell"]),
    ("循环", ["cycling", "cycle"]),
    ("容量", ["capacity"]),
    ("合成", ["synthesis", "synthesized"]),
    ("烧结", ["sintering"]),
    ("表征", ["characterization"]),
    ("缺陷", ["defect", "vacancy", "vacancies"]),
    ("氧空位", ["oxygen vacancy", "oxygen vacancies"]),
    ("热膨胀", ["thermal expansion"]),
    ("相结构", ["phase", "xrd", "diffraction"]),
    ("稳定性", ["stability", "degradation"]),
    ("三元", ["ternary"]),
    ("复合", ["composite"]),
    ("涂层", ["coating", "coated"]),
)


def _topic_terms(topic: str, outline_text: str, section: str = "") -> List[str]:
    """抽取主题关键词，用于判断片段是否**真的**相关。

    ⚠️ 光靠向量相似度不够：实测库里混入「离子液体双水相萃取分离青霉素」
    这类完全无关的文档，相似度 0.158 —— 分块后单块向量与查询的余弦相似度
    本就偏低，靠分数卡不住噪声。必须再做一次**词面相关**判定。

    且中文主题需配英文对照（见 CN_EN_TERMS）—— 否则英文文献会被误杀。
    """
    import re as _re

    text = " ".join(x for x in (topic, section, outline_text) if x)
    terms = set()
    # 中文：切 2-4 字的连续片段（无分词器，用 n-gram 近似）
    for m in _re.finditer(r"[一-鿿]{2,}", text):
        s = m.group(0)
        for n in (2, 3, 4):
            for i in range(len(s) - n + 1):
                g = s[i:i + n]
                if len(g) >= MIN_TERM_LEN:
                    terms.add(g)
    # 英文/数字：整词
    for m in _re.finditer(r"[A-Za-z][A-Za-z0-9\-]{2,}", text):
        terms.add(m.group(0).lower())
    # 中文概念 → 英文对照
    low_all = text.lower()
    for cn, ens in CN_EN_TERMS:
        if cn in text:
            for e in ens:
                terms.add(e)
    return list(terms)


def _relevant_to_topic(text: str, terms: List[str], source: str = "") -> bool:
    """片段是否与主题相关。

    ⚠️ 判定必须基于**文献身份信息**（文件名里通常带题名），
    不能只看正文词面 ——
    实测正文里「萃取」「分离」「材料」这类通用词到处都是，
    会把「离子液体双水相萃取分离青霉素」判成相关（该文与 SOFC 毫无关系）。

    策略：文件名（含题名）命中主题词 → 相关；
    文件名无主题词但正文命中**多个**长词 → 也算相关（文件可能是内部 ID）。
    """
    if not terms:
        return True
    strong = [t for t in terms if len(t) >= 3]
    weak = [t for t in terms if len(t) == 2]

    # 1) 文件名（常含文献题名）优先
    name = (source or "").split("/")[-1].lower()
    if name:
        for t in strong:
            if t in name:
                return True
        hits = sum(1 for t in weak if t in name)
        if hits >= 2:
            return True

    # 2) 正文：要求命中多个**长词**（单个长词可能只是碰巧）
    low = (text or "").lower()
    strong_hits = sum(1 for t in strong if t in low)
    if strong_hits >= 2:
        return True
    # 英文整词：命中 1 个即可（英文词本身就有区分度）
    en = [t for t in strong if t.isascii()]
    if any(t in low for t in en):
        return True
    return False


def _outline_headings(outline_text: str, limit: int = 6) -> List[str]:
    """从大纲里取章节标题行。

    大纲是 Markdown，章节标题形如 ``## 3.1 电导率测试方法``。
    取标题（而非正文）构造检索式 —— 标题正是「这一节写什么」的浓缩。
    """
    out: List[str] = []
    for raw in (outline_text or "").splitlines():
        ls = raw.strip()
        if not ls:
            continue
        if ls.startswith("#"):
            t = ls.lstrip("#").strip()
            if t:
                out.append(t[:80])
            if len(out) >= limit:
                break
    return out


def _section_query(topic: str, outline_text: str, section: str,
                   existing_text: str = "") -> str:
    """构造检索式。

    检索式 = 章节名 + **大纲章节标题** + 论文主题。
    大纲标题最关键 —— 它就是「这一节要写什么」，与要引用的文献最相关。

    ⚠️ 写作步目前是「一次性写全文」（section 固定为「全文」），
    所以这里用大纲的**各级标题**做检索式 —— 标题集合覆盖全文的各个主题面，
    比单纯用论文主题更聚焦。
    """
    parts: List[str] = []
    if section and section not in ("全文", ""):
        parts.append(section)
    heads = _outline_headings(outline_text)
    parts.extend(heads)
    if topic:
        parts.append(topic)
    if not parts and existing_text:
        parts.append(existing_text[:200])
    if not parts:
        parts.append((topic or section or "论文")[:200])
    return " ".join(parts)[:600]


def _chunk_label(src: str) -> str:
    """从源文件名提取一个可读的标签。

    ⚠️ 库里有两类文件名：
      - 人类可读（``Ceria co-doping__10_1039_C4CP00856A.md``）—— 直接用
      - 内部 ID（``paper_12eac584_g3k3gkqd.md``）—— 需要转成可读标签，
        否则模型看到的是无意义串。取元数据里的标题更好，
        但拿不到时至少去掉前缀让它不像乱码。
    """
    name = (src or "").split("/")[-1]
    if "." in name:
        name = name.rsplit(".", 1)[0]
    # 内部 ID 形态：paper_xxxxxxxx_xxxxxxxx
    if re.match(r"^(paper|doc|chunk)_[0-9a-f]{6,}", name, re.I):
        return "本地文献片段"
    name = name.lstrip("0123456789_")
    return name[:70] or "本地文献片段"


def _is_table_heavy(text: str) -> bool:
    """判断片段是否以表格为主 —— 表格对写作（散文叙述）价值低。

    Markdown 表格的特征：含 ``|---|`` 分隔行。
    ⚠️ 实测抓下来的表格会被**压成单行**（分块时表格行被合并）：
        ``≤0.15 | **Table 2.** | Composition | σₑ | |---|---|---|---| | GDC | — |``
    所以不能只看「行数与含|行数之比」—— 整段就 1 行，比例是 1.0 但仍不是表。
    判据改为：**文本里出现分隔符模式**即判为表格。
    """
    if "|" not in text:
        return False
    # 分隔符：|---| / | --- | / :---: 等
    if re.search(r"\|\s*:?-{3,}:?\s*(\|\s*:?-{0,}:?\s*)*\|", text):
        return True
    # 兜底：多行且多数行含多个 |（正常的 Markdown 表格未被压平时）
    lines = [l for l in text.splitlines() if l.strip()]
    if len(lines) < 3:
        return False
    pipe_lines = sum(1 for l in lines if l.count("|") >= 2)
    return pipe_lines / max(1, len(lines)) >= 0.5


def search_kb_for_writing(topic: str, outline_text: str, section: str,
                          existing_text: str = "", top_k: int = MAX_CHUNKS,
                          min_score: float = MIN_SCORE) -> List[Dict[str, Any]]:
    """按章节主题检索激活知识库，返回可注入 prompt 的正文片段。

    返回 ``[{label, source, score, text}]``，按相似度降序。
    无激活库 / 无命中 → 返回 []（调用方据此说明「没有本地材料」）。
    """
    try:
        from matlens_kit.plugins.local_rag import get_manager

        mgr = get_manager()
        active = getattr(mgr, "active", None)
        if not active:
            return []
        kb = mgr.get(active)
        if kb is None:
            return []

        query = _section_query(topic, outline_text, section, existing_text)
        if not query.strip():
            return []
        terms = _topic_terms(topic, outline_text, section)

        # 召回要**放宽**：实测 top_k=12 时「刚抓的 Ceria co-doping」根本
        # 不在候选里（库大了以后低分但高相关的片段会被挤掉）。
        # 先多召回，再由「表格过滤 + 词面相关性 + 分数下限」逐层筛。
        results = kb.query(query, top_k=max(top_k * 6, 30),
                           score_threshold=min_score)
        out: List[Dict[str, Any]] = []
        seen_text = set()
        per_doc = {}          # 同一文献最多取 MAX_PER_DOC 段
        skipped_table = 0
        skipped_irrelevant = 0
        for r in (results or []):
            text = (r.get("text") or r.get("content") or "").strip()
            if len(text) < 120:
                continue                      # 太短的片段没有引用价值
            if _is_table_heavy(text):
                skipped_table += 1
                continue                      # 表格喂进去模型只会照抄
            score = float(r.get("score", 0) or 0)
            if score < min_score:
                continue
            # 词面相关性兜底：向量相似度低不代表不相关，但**完全无关**的
            # 文档靠分数卡不住（实测「青霉素萃取」这类噪声混进来）
            src = r.get("source") or ""
            if not _relevant_to_topic(text, terms, src):
                skipped_irrelevant += 1
                continue
            # ⚠️ 去重要按**内容**，不能按标签 —— 同一文档的不同分块
            # 标签相同但内容不同（实测同一篇 785 字的片段出现两次），
            # 按标签去重会误杀有效片段。按内容前缀去重才准确。
            tkey = text[:120]
            if tkey in seen_text:
                continue
            # 单篇文献最多取 MAX_PER_DOC 段 —— 否则一篇长文会把名额占满
            # （实测 Ceria co-doping 占了 3/6），其他文献就没位置了。
            doc_key = (src or "")[:60]
            if per_doc.get(doc_key, 0) >= MAX_PER_DOC:
                continue
            seen_text.add(tkey)
            per_doc[doc_key] = per_doc.get(doc_key, 0) + 1
            out.append({
                "label": _chunk_label(src),
                "source": src,
                "score": round(score, 3),
                "text": text[:CHUNK_CHARS],
                "kb": active,
            })
            if len(out) >= top_k:
                break
        out.sort(key=lambda x: x["score"], reverse=True)
        return out
    except Exception:
        return []


def render_kb_context(chunks: List[Dict[str, Any]]) -> str:
    """把检索到的正文片段渲染成 prompt 可用的素材块。

    ⚠️ 必须写清「这些是本地库原文」以及「引用编号仍用白名单」，
    否则模型可能把片段里的内容当成新文献编号。
    """
    if not chunks:
        return ""
    lines = ["## 本地知识库原文素材（写作时可直接引用其内容）", ""]
    for i, c in enumerate(chunks, 1):
        lines.append(f"### 素材 {i}：{c['label']}"
                     f"（来源：{c.get('kb') or '本地库'} · 相似度 {c.get('score', 0)}）")
        lines.append("")
        lines.append(c.get("text", ""))
        lines.append("")
    lines.append(
        "> 以上为本地知识库中已索引的**原文片段**，可直接据此陈述事实。"
        "⚠️ 引用编号仍须使用上方「引用白名单」中的 [n]；"
        "素材本身不占用编号。若某条白名单文献在此素材中没有对应内容，"
        "**不要臆测其结论**。")
    return "\n".join(lines)


def build_writing_context(topic: str, outline_text: str, section: str,
                          existing_text: str = "") -> Dict[str, Any]:
    """写作步的本地库检索入口。返回 ``{block, chunks, count, kb, note}``。"""
    chunks = search_kb_for_writing(topic, outline_text, section, existing_text)
    block = render_kb_context(chunks)
    kb = chunks[0].get("kb") if chunks else ""
    note = ""
    if not chunks:
        note = ("本地知识库中没有与本节高度相关的材料。"
                "请仅依据已核验文献的题录写作，**不要臆测具体结论或数据**；"
                "如需引用原文细节，建议先在检索步点「找 OA 全文」补齐正文。")
    return {
        "block": block,
        "chunks": chunks,
        "count": len(chunks),
        "kb": kb,
        "note": note,
    }
