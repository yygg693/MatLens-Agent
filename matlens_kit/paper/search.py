# -*- coding: utf-8 -*-
"""论文工坊 · 检索双通道（P3，含 Crossref 降级）。

通道 A：RAG 本地知识库（激活库语义检索，带 source/score）
通道 B：OpenAlex 网络学术库（LLM 改写中英检索式 + 并发检索）
        降级：OpenAlex 失败/超时/空 → Crossref API
        兜底：两路皆失败 → 返回 []，不阻塞本地结果

产出：核验文献列表 refs = [{title, authors, year, source, doi, abstract}]
→ 作为**引用白名单**供 outline/write 引用、quality 核验。
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import time
import urllib.request
import urllib.parse
from typing import Any, Dict, List, Tuple

_UA = {"User-Agent": "MatLens/0.1 (mailto:matlens@example.com)"}

_OPENALEX_TIMEOUT = 12.0  # 国内网络余量（原 8s）
_CROSSREF_TIMEOUT = 12.0
_LOCAL_SCORE_MIN = 0.05  # 本地 KB 条目最低分


# ---------------------------------------------------------------------------
# 工具：HTTP GET JSON（带 1 次重试）
# ---------------------------------------------------------------------------
def _http_get_json(url: str, timeout: float, retries: int = 1) -> Any:
    """GET JSON，retries 次重试（间隔 1s）。失败抛最后一次异常。"""
    last_ex: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            last_ex = e
            if attempt < retries:
                time.sleep(1.0)
    assert last_ex is not None
    raise last_ex


# ---------------------------------------------------------------------------
# 通道 A：RAG 本地知识库
# ---------------------------------------------------------------------------
def search_local_kb(question: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """激活知识库语义检索。返回 [{title, snippet, score, source}]。

    无激活库 / 异常 → 静默返回 []（不抛）。
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
        results = kb.query(question, top_k=top_k, score_threshold=_LOCAL_SCORE_MIN)
        refs = []
        for r in results:
            text = (r.get("text") or r.get("content") or "")[:200]
            title = (r.get("source") or "知识库文档").split("/")[-1][:80]
            score = round(float(r.get("score", 0)), 3)
            if score < _LOCAL_SCORE_MIN:
                continue
            refs.append({
                "title": title,
                "snippet": text,
                "score": score,
                "source": f"本地知识库·{active}",
                "year": "",
                "authors": "",
                "doi": "",
            })
        return refs
    except Exception:
        return []


# ---------------------------------------------------------------------------
# 通道 B1：OpenAlex 网络学术库
# ---------------------------------------------------------------------------
def search_openalex(query: str, per_page: int = 8, timeout: float = _OPENALEX_TIMEOUT) -> List[Dict[str, Any]]:
    """OpenAlex works 检索。返回 [{title, year, authors, source, doi}]。

    单次请求可重试 1 次（间隔 1s）；最终失败/空 → 返回 []（由上层降级 Crossref）。
    """
    url = (
        "https://api.openalex.org/works?search=" + urllib.parse.quote(query)
        + f"&per-page={per_page}&select=id,title,publication_year,authorships,doi,primary_location"
    )
    try:
        d = _http_get_json(url, timeout=timeout, retries=1)
    except Exception:
        return []
    refs = []
    for w in (d.get("results") or [])[:per_page]:
        title = (w.get("title") or "").strip()
        if not title:
            continue
        auths = [a.get("author", {}).get("display_name", "") for a in (w.get("authorships") or [])[:4]]
        loc = w.get("primary_location") or {}
        src = loc.get("source") or {}
        venue = src.get("display_name", "") or ""
        refs.append({
            "title": title,
            "year": str(w.get("publication_year") or ""),
            "authors": ", ".join(a for a in auths if a),
            "source": f"OpenAlex·{venue}" if venue else "OpenAlex",
            "doi": w.get("doi") or "",
            "score": 0.5,
        })
    return refs


# ---------------------------------------------------------------------------
# 通道 B2：Crossref（OpenAlex 降级）
# ---------------------------------------------------------------------------
def search_crossref(query: str, rows: int = 8, timeout: float = _CROSSREF_TIMEOUT) -> List[Dict[str, Any]]:
    """Crossref works 检索（OpenAlex 失败时的降级通道）。

    返回与 search_openalex 同构的 refs，source 标记 "Crossref·刊名"。
    失败/空 → 返回 []。
    """
    url = (
        "https://api.crossref.org/works?query=" + urllib.parse.quote(query)
        + f"&rows={rows}&select=title,author,issued,container-title,DOI"
    )
    try:
        d = _http_get_json(url, timeout=timeout, retries=1)
    except Exception:
        return []
    items = ((d.get("message") or {}).get("items")) or []
    refs: List[Dict[str, Any]] = []
    for it in items[:rows]:
        titles = it.get("title") or []
        title = (titles[0] if titles else "").strip()
        if not title:
            continue
        authors_list = it.get("author") or []
        names = []
        for a in authors_list[:4]:
            given = (a.get("given") or "").strip()
            family = (a.get("family") or "").strip()
            names.append((given + " " + family).strip())
        # 年份：issued["date-parts"][0][0]
        year = ""
        try:
            year = str(it["issued"]["date-parts"][0][0])
        except Exception:
            year = ""
        containers = it.get("container-title") or []
        venue = (containers[0] if containers else "").strip()
        doi = (it.get("DOI") or "").strip()
        refs.append({
            "title": title,
            "year": year,
            "authors": ", ".join(n for n in names if n),
            "source": f"Crossref·{venue}" if venue else "Crossref",
            "doi": f"https://doi.org/{doi}" if doi else "",
            "score": 0.4,
        })
    return refs


def _search_network(query: str, per_page: int) -> Tuple[List[Dict[str, Any]], bool, bool]:
    """对单条 query 先 OpenAlex，空/失败降级 Crossref。

    返回 (refs, openalex_hit, crossref_hit)。
    """
    oa = search_openalex(query, per_page=per_page, timeout=_OPENALEX_TIMEOUT)
    if oa:
        return oa, True, False
    cr = search_crossref(query, rows=per_page, timeout=_CROSSREF_TIMEOUT)
    if cr:
        return cr, False, True
    return [], False, False


# ---------------------------------------------------------------------------
# 弱条目过滤
# ---------------------------------------------------------------------------
_FILENAME_SUFFIXES = (".txt", ".pdf", ".docx", ".doc", ".md", ".epub")


def _is_weak(entry: Dict[str, Any]) -> bool:
    """弱条目：title 空/过短/文件名特征；或本地条目 score 过低。"""
    title = (entry.get("title") or "").strip()
    if not title or len(title) < 8:
        return True
    low = title.lower()
    if low.endswith(_FILENAME_SUFFIXES):
        return True
    # 文件名风格：大量下划线 + 数字版本号（如 "GDC_electrolyte_v3"）
    if low.count("_") >= 3 and any(ch.isdigit() for ch in low):
        return True
    # 本地 KB 条目低分
    src = entry.get("source") or ""
    if src.startswith("本地知识库"):
        try:
            if float(entry.get("score", 0) or 0) < _LOCAL_SCORE_MIN:
                return True
        except Exception:
            return True
    return False


def _filter_weak(refs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in refs if not _is_weak(r)]


# ---------------------------------------------------------------------------
# 材料科研场景：方法学查询扩充（SOFC/GDC/电解质 类主题自动追加）
# ---------------------------------------------------------------------------
_SOFC_TRIGGER_KEYWORDS = (
    "sofc", "gdc", "ysz", "电解质", "燃料电池",
    "solid oxide fuel", "ceria", "氧化铈",
)

# 每个维度给一个英文检索式（OpenAlex/Crossref 英文命中率高），
# 取 top 2-4 条。source 上打个 meth 标签便于后续按类别分桶。
_SOFC_METHODOLOGY_QUERIES: List[Tuple[str, str]] = [
    ("GDC_SINGLE_CELL",
     "GDC electrolyte single cell OCV power density open circuit"),
    ("EIS_DRT",
     "electrochemical impedance spectroscopy distribution relaxation times DRT solid oxide electrolyte"),
    ("HEBB_WAGNER",
     "Hebb-Wagner method electronic conductivity ceria blocking electrode"),
    ("SPACE_CHARGE",
     "grain boundary space charge layer ceria ionic conductivity"),
    # v3 评审新增维度
    ("CA_DOPED_GDC",
     "Ca doped GDC ceria electrolyte conductivity"),
    ("ALKALINE_DOPED_CERIA",
     "alkaline earth doped ceria SOFC electrolyte"),
    ("CO_SINTERING_AID_GB",
     "Co sintering aid grain boundary conductivity GDC ceria"),
    ("LSCF_GDC_INTERFACE",
     "LSCF GDC cathode interface reaction SOFC co-firing"),
    ("DRT_REGULARIZATION",
     "distribution of relaxation times regularization impedance deconvolution"),
]


def _detect_methodology_queries(topic: str) -> List[Tuple[str, str]]:
    """若主题命中 SOFC/GDC/电解质 类关键词，返回 [(dim_tag, query)] 列表。

    非材料主题 → []。
    """
    low = (topic or "").lower()
    if not any(k in low for k in _SOFC_TRIGGER_KEYWORDS):
        return []
    return list(_SOFC_METHODOLOGY_QUERIES)


# ---------------------------------------------------------------------------
# LLM 查询改写（中英检索式）
# ---------------------------------------------------------------------------
def query_rewrite(topic: str) -> List[str]:
    """用 DeepSeek 把主题改写为 2-3 个中英检索式（短调用，不走 agent 锁）。

    无 key / 失败 → 回退 [topic]。
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.expanduser("~/.matlens/.env"))
        from openai import OpenAI

        key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not key:
            return [topic]
        client = OpenAI(api_key=key, base_url="https://api.deepseek.com", timeout=20)
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{
                "role": "user",
                "content": (
                    "你是文献检索专家。把研究主题改写为 3 个检索式（1 中文 + 2 英文），"
                    "每行一个，只输出检索式本身，不要编号和解释。\n主题：" + topic
                ),
            }],
            max_tokens=150,
            temperature=0.2,
        )
        text = (resp.choices[0].message.content or "").strip()
        qs = [q.strip() for q in text.splitlines() if q.strip()]
        return qs[:3] or [topic]
    except Exception:
        return [topic]


# ---------------------------------------------------------------------------
# 双通道合并
# ---------------------------------------------------------------------------
def _dedup(refs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for r in refs:
        key = (r.get("title") or "").strip().lower()[:60]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def run_dual_search(topic: str, top_k: int = 8, use_llm_rewrite: bool = True,
                    auto_queries: bool = True) -> Dict[str, Any]:
    """双通道检索：本地 RAG + 网络（OpenAlex→Crossref 降级，中英变体并发）。

    材料科研场景（SOFC/GDC/电解质 类主题）下，auto_queries=True 会自动追加
    4 个方法学维度查询（GDC 单电池基准 / EIS-DRT / Hebb-Wagner / 晶界空间电荷层），
    每维度取 3 条，与主题查询合并去重后通常可达 12-16 条。

    返回字段保持向后兼容：
      ok / count / queries / local_count / oa_count / refs / latency_s / channels
    新增：meth_queries（被追加的方法学查询，便于观测）。
    """
    t0 = time.time()
    queries = query_rewrite(topic) if use_llm_rewrite else [topic]

    # 方法学扩充（材料科研场景）
    meth_dims: List[Tuple[str, str]] = []
    if auto_queries:
        meth_dims = _detect_methodology_queries(topic)
    meth_queries = [q for _, q in meth_dims]

    local_refs: List[Dict[str, Any]] = []
    topic_net_refs: List[Dict[str, Any]] = []  # 主题查询结果（无 meth 标签）
    meth_refs_by_tag: Dict[str, List[Dict[str, Any]]] = {}  # tag -> [refs]
    oa_hit = False
    cr_hit = False
    local_hit = False

    METH_PERQ = 3  # 每个方法学维度最多取 3 条

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        local_fut = ex.submit(search_local_kb, topic, top_k)
        # 主题查询
        net_futs = [ex.submit(_search_network, q, top_k) for q in queries]
        # 方法学查询（per_query 收紧到 METH_PERQ）
        meth_futs = [(tag, ex.submit(_search_network, q, METH_PERQ)) for tag, q in meth_dims]

        # 本地 KB 秒级：优先收集
        try:
            local_refs = local_fut.result(timeout=10) or []
        except Exception:
            local_refs = []

        for f in net_futs:
            try:
                refs, oa, cr = f.result(timeout=_OPENALEX_TIMEOUT + _CROSSREF_TIMEOUT + 2)
                topic_net_refs.extend(refs)
                oa_hit = oa_hit or oa
                cr_hit = cr_hit or cr
            except Exception:
                pass

        for tag, f in meth_futs:
            try:
                refs, oa, cr = f.result(timeout=_OPENALEX_TIMEOUT + _CROSSREF_TIMEOUT + 2)
                for r in refs:
                    r["meth"] = tag  # 给方法学条目打类别标签
                meth_refs_by_tag.setdefault(tag, []).extend(refs)
                oa_hit = oa_hit or oa
                cr_hit = cr_hit or cr
            except Exception:
                pass

    local_hit = bool(local_refs)

    # 弱条目过滤
    local_refs = _filter_weak(local_refs)
    topic_net_refs = _filter_weak(topic_net_refs)
    for tag in list(meth_refs_by_tag.keys()):
        meth_refs_by_tag[tag] = _filter_weak(meth_refs_by_tag[tag])

    # 修正 channels
    local_hit = bool(local_refs)
    total_net = len(topic_net_refs) + sum(len(v) for v in meth_refs_by_tag.values())
    if total_net == 0:
        oa_hit = False
        cr_hit = False

    # ------------------------------------------------------------------
    # 组装白名单：按维度预留名额，避免主题查询把方法学条目挤掉
    # ------------------------------------------------------------------
    if meth_dims:
        final_cap = max(top_k, 16)
        final_cap = min(final_cap, 20)
        # 每个方法学维度保留 1-2 条：保底 1 条，余量充足时补到 2 条
        METH_FLOOR = 1 if len(meth_dims) > 6 else 2
        METH_CEIL = 2
        # 1) 先放本地 KB（最多 top_k）
        picked: List[Dict[str, Any]] = list(local_refs[:top_k])
        used_titles: set = {(r.get("title") or "").strip().lower()[:60] for r in picked}

        def _take(pool: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
            out = []
            for r in pool:
                if len(out) >= n:
                    break
                key = (r.get("title") or "").strip().lower()[:60]
                if not key or key in used_titles:
                    continue
                used_titles.add(key)
                out.append(r)
            return out

        # 2) 每个方法学维度先各取 METH_FLOOR 条（保底覆盖 4 个维度）
        for tag, pool in meth_refs_by_tag.items():
            picked.extend(_take(pool, METH_FLOOR))
        # 3) 主题查询取剩余名额（尽量补到 final_cap）
        remaining = final_cap - len(picked)
        if remaining > 0:
            picked.extend(_take(topic_net_refs, remaining))
        # 4) 还有空缺再用方法学维度的第 3 条补
        for tag, pool in meth_refs_by_tag.items():
            if len(picked) >= final_cap:
                break
            # 跳过该维度已选的（_take 内部按 title 去重）
            picked.extend(_take(pool, METH_CEIL - METH_FLOOR))
        refs = picked[:final_cap]
    else:
        combined = _dedup(local_refs + topic_net_refs)
        refs = combined[:top_k]

    for i, r in enumerate(refs, 1):
        r["index"] = i

    return {
        "ok": True,
        "count": len(refs),
        "queries": queries + meth_queries,  # 合并后便于观测
        "local_count": len(local_refs),
        "oa_count": len(topic_net_refs) + sum(len(v) for v in meth_refs_by_tag.values()),
        "refs": refs,
        "latency_s": round(time.time() - t0, 1),
        "channels": {
            "local": bool(local_hit),
            "openalex": bool(oa_hit),
            "crossref": bool(cr_hit),
        },
        "meth_queries": meth_queries,
    }


def render_refs(refs: List[Dict[str, Any]]) -> str:
    """引用白名单渲染为 Markdown（search 步落库 + prompt 引用块）。"""
    if not refs:
        return "（双通道检索未命中核验文献，请检查知识库内容或网络）"
    lines = ["## 核验文献列表（引用白名单）", ""]
    for r in refs:
        t = r.get("title", "")
        a = r.get("authors", "")
        y = r.get("year", "")
        s = r.get("source", "")
        d = r.get("doi", "")
        lines.append(f"[{r.get('index', '?')}] **{t}** · {a} · {y} · {s}")
        if d:
            lines.append(f"    DOI: {d}")
    return "\n".join(lines)
