"""记忆图谱 API —— 从 matlens 统一后端的记忆抽取实体/关系，供前端 vis-network 渲染。

数据流（见 design/backend-api.md 第四节）：
  Mem0 记忆（带 [用户]/[实验]/[材料]/[结论] 标签）
    → DeepSeek 抽实体/关系（复用 matlens 的 DEEPSEEK_API_KEY）
    → ~/.matlens/graph.json（增量合并）
    → 前端 vis-network 蜘蛛网

后端不可用时（qdrant 异常）优雅降级：返回节点（无边的启发式图）而非崩溃。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

_router = APIRouter(prefix="/api/graph", tags=["graph"])

_GRAPH_PATH = Path(os.path.expanduser("~/.matlens/graph.json"))
_graph_lock = threading.Lock()
_CAT_RE = re.compile(r"^\s*\[([^\]]+)\]\s*")

# 类别 → 颜色（前端 vis-network 用）
# 任务约定：材料=蓝、方法=绿、性质=橙、参数=灰；其余类别保留旧色。
CATEGORY_COLORS = {
    "材料": "#38bdf8",   # sky blue
    "方法": "#22c55e",   # green
    "性质": "#f97316",   # orange
    "参数": "#9ca3af",   # gray
    "用户": "#6366f1",   # indigo
    "实验": "#2dd4bf",   # teal
    "结论": "#f59e0b",   # amber
    "其他": "#94a3b8",   # slate
}

_DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
_DEEPSEEK_MODEL = "deepseek-chat"


def _get_deepseek_key() -> str:
    """解析 DEEPSEEK_API_KEY：优先 secret scope / 进程环境，缺省回落到 ~/.matlens/.env。"""
    try:
        from agent.secret_scope import get_secret

        key = get_secret("DEEPSEEK_API_KEY", "") or ""
    except Exception:
        key = ""
    if key:
        return key
    # 回落到 .env 文件（独立脚本/测试场景）
    try:
        from agent.secret_scope import load_env_file

        env_path = Path(os.path.expanduser("~/.matlens/.env"))
        return load_env_file(env_path).get("DEEPSEEK_API_KEY", "")
    except Exception:
        return os.environ.get("DEEPSEEK_API_KEY", "")


def _graph_auto_build_enabled() -> bool:
    """实时读取 memory.graph_auto_build 开关（settings_store 不缓存）。读取失败默认 True。"""
    try:
        from matlens_kit import settings_store

        return bool(settings_store.get_section("memory").get("graph_auto_build", True))
    except Exception:
        return True


def _graph_cache() -> Dict[str, Any]:
    if _GRAPH_PATH.exists():
        try:
            return json.loads(_GRAPH_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"nodes": [], "edges": []}


def _save_cache(g: Dict[str, Any]) -> None:
    _GRAPH_PATH.parent.mkdir(parents=True, exist_ok=True)
    _GRAPH_PATH.write_text(json.dumps(g, ensure_ascii=False, indent=2), encoding="utf-8")


def _fetch_memories(top_k: int = 200) -> List[Dict[str, Any]]:
    """从统一后端取记忆集合（复用 mem_api 的 provider 访问）。

    优先全量分页枚举。旧实现用一次语义检索取 top_k，那只是"最相关的一批"，
    不是全部记忆——图谱因此永远看不见库里的另一半，实体覆盖和边都会缺一块。
    后端不支持枚举时（抛 NotImplementedError）才回落到检索。
    """
    try:
        from matlens_kit.api.mem_api import _categorize, _get_provider

        provider = _get_provider()
        if provider is None or getattr(provider, "_backend", None) is None:
            return []

        results: List[Dict[str, Any]] = []
        lister = getattr(provider, "list_memories", None)
        if callable(lister):
            offset = 0
            while True:
                data = lister(page=1, page_size=200, offset=offset)
                if not isinstance(data, dict):
                    break
                rows = data.get("results") or []
                for r in rows:
                    mem = r.get("memory") or r.get("text") or ""
                    if mem:
                        results.append({
                            "id": r.get("id"),
                            "memory": mem,
                            "category": _categorize(mem),
                        })
                if not rows or not data.get("has_more"):
                    break
                offset += len(rows)
                if offset > 2000:
                    break
        if results:
            return results

        raw = provider.handle_tool_call(
            "mem0_search",
            {"query": "材料 科研 实验 用户 结论 方向 参数 偏好", "top_k": top_k},
        )
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = {}
        for r in (raw.get("results", []) if isinstance(raw, dict) else []):
            mem = r.get("memory") or r.get("text") or ""
            if mem:
                results.append({"id": r.get("id"), "memory": mem, "category": _categorize(mem)})
        return results
    except Exception:
        return []


def _llm_extract(memos: List[Dict[str, Any]],
                 known: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    """用 DeepSeek（OpenAI 兼容 client）从记忆文本抽取实体/关系（JSON）。失败返回 None。"""
    if not memos:
        return None

    key = _get_deepseek_key()
    if not key:
        return None
    try:
        from openai import OpenAI
    except Exception:
        return None

    lines = []
    for m in memos:
        lines.append(f"[{m['category']}] {m['memory']}")
    corpus = "\n".join(lines)

    sys_prompt = (
        "你是材料科研知识图谱抽取器。从给定记忆中抽取实体与关系，输出严格 JSON：\n"
        '{"nodes":[{"id":"唯一id","label":"实体名","category":"材料|方法|性质|参数|用户|实验|结论|其他"}],'
        '"edges":[{"source":"节点id","target":"节点id","label":"关系"}]}\n'
        "规则：节点去重；实体优先归为四类——材料(物质/组分/体系)、方法(合成/表征/测试手段)、"
        "性质(性能/现象/规律)、参数(数值/条件/配比)；边表示'属于/用于/导致/偏好/得出/测试'等科研关系；"
        "id 用英文短词或数字，保持引用一致；只输出 JSON，不要多余文字。\n"
        "命名规则（重要）：① 每个实体只用一个规范名，取记忆里最短通行写法（不超过 16 字），"
        "不要把别名、分子式、参数堆成一个长名字；② 关于用户的实体一律用「用户」，"
        "不要写姓名、学校、年级、身份；③ 同一实体的不同写法只能出现一个节点；"
        "④ 只要与下面「已有实体」里的某个名称指同一对象，就**原样使用那个名称**，"
        "不要再缩短、改写或换一种说法——名字一旦变了，图上就会出现两个本该是一个的节点。"
    )
    known_hint = ""
    if known:
        known_hint = (
            "\n\n已有实体（若含义相同，请直接复用下列完全相同的名称，不要另起新名）：\n"
            + "、".join(known[:200])
        )
    user_prompt = f"记忆列表：\n{corpus}{known_hint}\n\n请输出图谱 JSON。"

    try:
        client = OpenAI(base_url=_DEEPSEEK_BASE_URL, api_key=key, timeout=60)
        resp = client.chat.completions.create(
            model=_DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            # 抽取必须是确定性的：否则同一批记忆重建两次会得到两套实体名，
            # 实体归一配置、结构诊断的历史对比全部失效
            temperature=0,
        )
        content = resp.choices[0].message.content
        data = json.loads(content)
        if isinstance(data, dict) and "nodes" in data:
            return data
    except Exception:
        return None
    return None


def _heuristic_graph(memos: List[Dict[str, Any]]) -> Dict[str, Any]:
    """LLM 不可用时的启发式降级：记忆即节点，同类别聚簇相连。"""
    nodes = []
    for m in memos:
        nodes.append({
            "id": m["id"] or f"m{len(nodes)}",
            "label": (m["memory"][:40] + "…") if len(m["memory"]) > 40 else m["memory"],
            "category": m["category"],
        })
    # 同类别节点成链（仅保证图非空、可见结构）
    edges = []
    by_cat: Dict[str, List[str]] = {}
    for n in nodes:
        by_cat.setdefault(n["category"], []).append(n["id"])
    for cat, ids in by_cat.items():
        for i in range(len(ids) - 1):
            edges.append({"id": f"e{len(edges)}", "source": ids[i], "target": ids[i + 1], "label": cat})
    return {"nodes": nodes, "edges": edges, "fallback": True}


GRAPH_BATCH_SIZE = 45

# 材料写法里的下标/上标（Ce₀.₇₈、O₂₋δ）。NFKC 能处理大部分，但下标负号和
# 上标数字它不认，得手工兜一层。
_SUB_MAP = str.maketrans({
    "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
    "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9",
    "₊": "+", "₋": "-",
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
    "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
    "⁺": "+", "⁻": "-",
    # NFKC 会把下标负号转成 U+2212 数学减号，跟 ASCII 的 '-' 不相等
    "−": "-", "–": "-", "—": "-", "﹣": "-",
})

# 上位类别词：出现在别的名字里是正常的上下位关系，不代表同一个实体
_GENERIC_WORDS = {
    "电池", "电解质", "氧化物", "界面", "阻抗", "稳定性", "材料", "方法",
    "性质", "参数", "用户", "实验", "结论", "其他", "论文", "文献", "不锈钢",
    "合金", "高温合金", "钛合金", "铝合金", "碳钢", "电极", "负极", "正极",
    "涂层", "薄膜", "催化剂", "纳米", "复合", "掺杂", "共掺杂", "体系",
}

# 这些前缀说明长名是"基础手段 + 另一种方法"的组合，不是同一个东西
_COMPOSITE_PREFIXES = ("ml-", "ai-", "dft-", "operando-", "in-situ", "insitu",
                       "机器学习", "计算", "模拟", "原位")


def _normalize_label(label: str) -> str:
    """实体名的比对形式：下标/上标折成普通字符、全角转半角、去掉空白。

    只用来判断两个写法是不是同一个实体；展示仍用原 label——材料符号里的下标是
    专业写法（Ce₀.₇₈），不该为了比对把它抹平。
    """
    s = unicodedata.normalize("NFKC", str(label or ""))
    s = s.translate(_SUB_MAP)
    s = re.sub(r"\s+", "", s)
    return s.casefold()


def _merge_candidates(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """找出"名字可能指同一个东西"的实体对，只给证据，不自动合并。

    材料名里的重复大多是上位/下位或同族不同牌号——`304不锈钢` 与 `316不锈钢` 差一个
    牌号就是两种材料，`高温合金` 与 `镍基高温合金` 是上下位，`Gd掺杂CeO₂` 与
    `GDC-Ca共掺杂` 差一个掺杂元素。合并它们等于替用户下错误的材料学断言，所以这里
    只把可疑对列出来。三条依据：括号别名、一方完整包含另一方，且要求同类别、
    短的一方不是上位类别词、两边不是只差数字的牌号。
    """
    items = [(str(n.get("id")), str(n.get("label") or ""), str(n.get("category") or ""))
             for n in nodes]
    label_of = {i: lb for i, lb, _ in items}
    cat_of = {i: c for i, _, c in items}
    norm = {i: _normalize_label(lb) for i, lb, _ in items}

    out: List[Dict[str, Any]] = []
    seen = set()

    def add(a: str, b: str, reason: str) -> None:
        if a == b:
            return
        pair = tuple(sorted((a, b)))
        if pair in seen:
            return
        seen.add(pair)
        out.append({"a": pair[0], "b": pair[1],
                    "a_label": label_of[pair[0]], "b_label": label_of[pair[1]],
                    "reason": reason})

    # 依据一：括号别名 —— 钛酸锂(LTO) 里的 LTO 若也单独成节点，就是同一个
    for nid, lb, _ in items:
        m = re.match(r"^(.+?)\(([^()]+)\)$", lb.strip())
        if not m:
            continue
        targets = {_normalize_label(m.group(1))}
        alias = m.group(2).strip()
        if len(alias) >= 2:
            targets.add(_normalize_label(alias))
        for other, other_lb, _ in items:
            if other != nid and norm[other] in targets:
                add(nid, other, "括号别名")

    # 依据二：一方完整包含另一方（缩写如 GDC ⊂ GDC-Ca共掺杂 也走这条）
    for i, (a_id, a_lb, a_cat) in enumerate(items):
        for b_id, b_lb, b_cat in items[i + 1:]:
            if a_cat != b_cat:
                continue  # 跨类别包含几乎都是上位概念，不是同物异名
            na, nb = norm[a_id], norm[b_id]
            short, long_label, short_label = (
                (na, nb, a_lb) if len(na) <= len(nb) else (nb, na, b_lb)
            )
            if len(short) < 3 or short not in long_label:
                continue
            if short_label.strip().casefold() in _GENERIC_WORDS:
                continue  # 上位类别词被包含是正常的
            if re.sub(r"[0-9.]", "", na) == re.sub(r"[0-9.]", "", nb):
                continue  # 只差数字：同族不同牌号（304/316 不锈钢），不是同一个
            longer = nb if short == na else na
            if longer.startswith(_COMPOSITE_PREFIXES):
                continue  # ML-XPS 与 XPS：一个是组合手段，一个是基础表征
            add(a_id, b_id, "名称包含")

    return out


def _merge_graph_parts(parts: List[Any]) -> Dict[str, Any]:
    """把分批抽取的结果合并成一张图。

    每批独立送给模型，模型自己编的 id 在不同批之间并不互相指向，所以不能直接
    把各批的 nodes/edges 拼起来——那样会出现"t1 在这批指 A、在那批指 B"的错连。
    处理办法：节点按 label 归一去重并重新分配稳定 id，每批的原始 id 先映射到
    规范 id，再让边按映射落地；最后按 (source, target, label) 去重。
    """
    nodes: List[Dict[str, Any]] = []
    by_label: Dict[str, str] = {}
    by_id: Dict[str, Dict[str, Any]] = {}
    id_maps: List[Dict[str, str]] = []

    for part in parts:
        local: Dict[str, str] = {}
        if isinstance(part, dict):
            for n in part.get("nodes") or []:
                if not isinstance(n, dict):
                    continue
                label = str(n.get("label") or "").strip()
                if not label:
                    continue
                # 比对用归一形式：Ce₀.₇₈ 与 Ce0.78 是同一种写法，不该各占一个节点
                key = _normalize_label(label)
                nid = by_label.get(key)
                if nid is None:
                    nid = "n%d" % len(nodes)
                    by_label[key] = nid
                    node = {
                        "id": nid,
                        "label": label,
                        "category": n.get("category") or "其他",
                        "aliases": [],
                    }
                    nodes.append(node)
                    by_id[nid] = node
                else:
                    node = by_id[nid]
                    if label != node["label"] and label not in node["aliases"]:
                        node["aliases"].append(label)
                local[str(n.get("id") or "")] = nid
                local.setdefault(label, nid)
        id_maps.append(local)

    edges: List[Dict[str, Any]] = []
    seen = set()
    for idx, part in enumerate(parts):
        if not isinstance(part, dict):
            continue
        local = id_maps[idx]
        for e in part.get("edges") or []:
            if not isinstance(e, dict):
                continue
            src = local.get(str(e.get("source") or ""))
            dst = local.get(str(e.get("target") or ""))
            if not src or not dst or src == dst:
                continue
            rel = str(e.get("label") or "").strip()
            key = (src, dst, rel)
            if key in seen:
                continue
            seen.add(key)
            edges.append({"id": "e%d" % len(edges), "source": src, "target": dst,
                          "label": rel, "kind": "semantic"})

    return {"nodes": nodes, "edges": edges}


_ENTITY_MERGE_PATH = Path(os.path.expanduser("~/.matlens/entity_merge.json"))
_ENTITY_DICT_PATH = Path(os.path.expanduser("~/.matlens/entity_dict.json"))
_dict_lock = threading.Lock()


def _fold_nodes(data: Dict[str, Any], label_map: Dict[str, str]) -> Dict[str, Any]:
    """按 label_map 把节点改成规范名，并把因此重名的节点并成一个。

    只影响 label，不动 id；被并掉的写法收进保留节点的 aliases，边重新指向保留节点。
    自环和重复边（同源同目标同 label）在这一步一并丢掉。
    """
    nodes = data.get("nodes") or []
    if not nodes:
        return data

    renamed: List[Dict[str, Any]] = []
    for n in nodes:
        n = dict(n)
        lb = str(n.get("label") or "")
        canon = label_map.get(lb, lb)
        if canon != lb:
            n["label"] = canon
            al = list(n.get("aliases") or [])
            if lb not in al:
                al.append(lb)
            n["aliases"] = al
        renamed.append(n)

    groups: Dict[str, List[Dict[str, Any]]] = {}
    for n in renamed:
        groups.setdefault(_normalize_label(n.get("label")), []).append(n)

    remap: Dict[str, str] = {}
    kept: List[Dict[str, Any]] = []
    for _key, members in groups.items():
        if len(members) == 1:
            kept.append(members[0])
            continue
        target = members[0]
        for m in members[1:]:
            remap[m["id"]] = target["id"]
            al = target.setdefault("aliases", [])
            for a in list(m.get("aliases") or []) + [str(m.get("label") or "")]:
                if a and a != target["label"] and a not in al:
                    al.append(a)
        kept.append(target)

    data["nodes"] = kept
    if not remap:
        return data

    seen = set()
    edges: List[Dict[str, Any]] = []
    for e in data.get("edges") or []:
        src = remap.get(e.get("source"), e.get("source"))
        dst = remap.get(e.get("target"), e.get("target"))
        if not src or not dst or src == dst:
            continue
        key = (src, dst, str(e.get("label") or ""))
        if key in seen:
            continue
        seen.add(key)
        e2 = dict(e)
        e2["source"], e2["target"] = src, dst
        edges.append(e2)
    data["edges"] = edges
    return data


def _load_entity_dict() -> Dict[str, Any]:
    """读本机实体词典（~/.matlens/entity_dict.json）。

    词典的作用是让实体名跨重建稳定：第一次自由抽取后，把当时的名字记下来，
    以后每次重建都复用同一批名字，而不是每回都让模型重新命名一遍。
    """
    try:
        raw = json.loads(_ENTITY_DICT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"entities": {}}
    if not isinstance(raw, dict):
        return {"entities": {}}
    ents = raw.get("entities")
    out: Dict[str, Any] = {}
    # 落盘格式是 {规范名: {category, aliases, seen}}，规范名本身就是 key；
    # 也兼容数组格式（每条自带 canonical/label）。
    if isinstance(ents, dict):
        for key, item in ents.items():
            canon = str(key or "").strip()
            if not canon or not isinstance(item, dict):
                continue
            out[canon] = {
                "category": item.get("category"),
                "aliases": [str(a).strip() for a in (item.get("aliases") or []) if str(a).strip()],
                "seen": item.get("seen") if isinstance(item.get("seen"), int) else 0,
            }
    elif isinstance(ents, list):
        for item in ents:
            if not isinstance(item, dict):
                continue
            canon = str(item.get("canonical") or item.get("label") or "").strip()
            if not canon:
                continue
            out[canon] = {
                "category": item.get("category"),
                "aliases": [str(a).strip() for a in (item.get("aliases") or []) if str(a).strip()],
                "seen": item.get("seen") if isinstance(item.get("seen"), int) else 0,
            }
    return {"entities": out}


def _save_entity_dict(d: Dict[str, Any]) -> None:
    try:
        _ENTITY_DICT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _ENTITY_DICT_PATH.write_text(
            json.dumps({"updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "entities": d.get("entities", {})},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
    except Exception:
        pass


def _dict_canonical_names() -> List[str]:
    """词典里已经见过的规范名，按出现次数排序——次数多的先传给模型。"""
    ents = _load_entity_dict().get("entities", {})
    if not isinstance(ents, dict):
        return []
    ranked = sorted(ents.items(),
                    key=lambda kv: -(kv[1].get("seen") or 0) if isinstance(kv[1], dict) else 0)
    return [k for k, _ in ranked if k]


def _apply_entity_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """把节点名对齐到词典里的规范名，并把这次见到的新名字登记进词典。

    命中规则：归一后相等，或命中了词典里某条的 aliases。没命中的就是新实体，
    登记为独立条目（seen 计数 +1），下次重建时它也会变成要复用的名字。
    """
    with _dict_lock:
        d = _load_entity_dict()
        ents = d.setdefault("entities", {})
        if not isinstance(ents, dict):
            ents = {}
            d["entities"] = ents

        index: Dict[str, str] = {}
        for canon, info in ents.items():
            index.setdefault(_normalize_label(canon), canon)
            for a in (info.get("aliases") or []):
                index.setdefault(_normalize_label(a), canon)

        label_map: Dict[str, str] = {}
        for n in data.get("nodes") or []:
            lb = str(n.get("label") or "")
            if not lb:
                continue
            key = _normalize_label(lb)
            canon = index.get(key) or lb
            if canon != lb:
                label_map[lb] = canon
                info = ents.setdefault(canon, {"category": None, "aliases": [], "seen": 0})
                al = info.setdefault("aliases", [])
                if lb not in al:
                    al.append(lb)
            else:
                info = ents.setdefault(canon, {"category": None, "aliases": [], "seen": 0})
            info["seen"] = int(info.get("seen") or 0) + 1
            if n.get("category"):
                info["category"] = n.get("category")

        _save_entity_dict(d)

    if label_map:
        return _fold_nodes(data, label_map)
    return data


def _load_entity_merge() -> List[Dict[str, Any]]:
    """读人工复核过的同物异名归并配置（~/.matlens/entity_merge.json）。

    配置只在本机、不进仓库——里面的实体名来自个人记忆内容。删掉这个文件就回到
    "每种写法各占一个节点"的行为，所以归并天然可撤销。
    """
    try:
        raw = json.loads(_ENTITY_MERGE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    groups = raw.get("groups") if isinstance(raw, dict) else raw
    if not isinstance(groups, list):
        return []
    out: List[Dict[str, Any]] = []
    for g in groups:
        if not isinstance(g, dict):
            continue
        canon = str(g.get("canonical") or "").strip()
        aliases = [str(a).strip() for a in (g.get("aliases") or []) if str(a).strip()]
        if canon and aliases:
            out.append({"canonical": canon, "aliases": aliases,
                        "why": str(g.get("why") or "")})
    return out


def _apply_entity_merge(data: Dict[str, Any]) -> Dict[str, Any]:
    """把同一实体的多种写法并成一个节点，边随节点一起重映射。

    被并掉的写法不丢弃，收进规范节点的 aliases——前端详情里仍能看到它原本怎么写，
    这比"悄悄改名"要好，用户随时能核对合并到底对不对。
    """
    groups = _load_entity_merge()
    nodes = data.get("nodes") or []
    if not groups or not nodes:
        return data

    by_label = {str(n.get("label") or ""): n for n in nodes}
    by_norm: Dict[str, Dict[str, Any]] = {}
    for n in nodes:
        by_norm.setdefault(_normalize_label(n.get("label")), n)

    def resolve(name: str) -> Optional[Dict[str, Any]]:
        return by_label.get(name) or by_norm.get(_normalize_label(name))

    remap: Dict[str, str] = {}
    absorbed: List[str] = []
    for g in groups:
        # 名字是抽取出来的，重建时可能换写法；只要这一组里有两个名字在图上，
        # 就用其中一个当规范节点，而不是因为 canonical 暂时缺失就整组放弃。
        present: List[Dict[str, Any]] = []
        for nm in [g["canonical"], *g["aliases"]]:
            node = resolve(nm)
            if node is not None and all(node["id"] != p["id"] for p in present):
                present.append(node)
        if len(present) < 2:
            continue
        target = resolve(g["canonical"]) or min(
            present, key=lambda n: len(str(n.get("label") or "")))
        for src in present:
            if src["id"] == target["id"]:
                continue
            remap[src["id"]] = target["id"]
            src_label = str(src.get("label") or "")
            absorbed.append(src_label)
            al = target.setdefault("aliases", [])
            if src_label != target["label"] and src_label not in al:
                al.append(src_label)
        if g.get("why"):
            target["merged_why"] = g["why"]
            target["preferred_label"] = g["canonical"]

    if not remap:
        return data

    kept = [n for n in nodes if n["id"] not in remap]
    seen = set()
    edges: List[Dict[str, Any]] = []
    for e in data.get("edges") or []:
        src = remap.get(e.get("source"), e.get("source"))
        dst = remap.get(e.get("target"), e.get("target"))
        if not src or not dst or src == dst:
            continue
        key = (src, dst, str(e.get("label") or ""))
        if key in seen:
            continue
        seen.add(key)
        e2 = dict(e)
        e2["source"], e2["target"] = src, dst
        edges.append(e2)

    data["nodes"] = kept
    data["edges"] = edges
    data["merged_labels"] = absorbed
    return data


def _save_entity_merge(groups: List[Dict[str, Any]]) -> None:
    """把归并组写回配置文件，保留 rejected 等人工判断记录。"""
    try:
        raw = json.loads(_ENTITY_MERGE_PATH.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    if isinstance(raw, list):
        raw = {"groups": raw}
    if not isinstance(raw, dict):
        raw = {}
    raw["groups"] = groups
    raw["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _ENTITY_MERGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _ENTITY_MERGE_PATH.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")


COOC_BRIDGE_LABEL = "同条记忆提及"


def _cooc_bridges(nodes: List[Dict[str, Any]],
                  memos: List[Dict[str, Any]],
                  edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """同一条记忆里一起出现的两个实体，补一条桥接边。

    分批抽取有个代价：模型每批只看得到自己那几十条，批与批之间的实体它连不起来，
    于是一张图被切成几块互不相通的岛。这里用最朴素的证据把岛接起来——两个实体
    出现在同一条记忆里。

    只补"能把两块断开的连起来"的那些（按同框次数优先），不是把所有同框对都画出来：
    短名实体（用户、GDC）几乎在每条记忆里都出现，全补会得到几百条噪声边。
    语义边已经连通的两点不再补，并且统一标 kind="cooc"，免得被当成模型给出的关系。
    """
    parent: Dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    existing = set()
    for e in edges:
        a, b = str(e.get("source")), str(e.get("target"))
        existing.add(tuple(sorted((a, b))))
        union(a, b)

    # 长 label 先匹配，命中后占位，防止短 label 在长 label 内部重复命中
    order = sorted(nodes, key=lambda n: -len(str(n.get("label") or "")))
    pairs: Dict[Any, int] = {}
    for m in memos:
        text = str(m.get("memory") or m.get("text") or "").casefold()
        if not text:
            continue
        hits: List[str] = []
        for n in order:
            lb = str(n.get("label") or "").casefold().strip()
            if len(lb) < 2 or lb not in text:
                continue
            text = text.replace(lb, "\u0001")
            hits.append(str(n.get("id")))
        for i in range(len(hits)):
            for j in range(i + 1, len(hits)):
                pair = tuple(sorted((hits[i], hits[j])))
                if pair[0] == pair[1] or pair in existing:
                    continue
                pairs[pair] = pairs.get(pair, 0) + 1

    out: List[Dict[str, Any]] = []
    for (a, b), count in sorted(pairs.items(), key=lambda kv: -kv[1]):
        if find(a) == find(b):
            continue  # 这两块本来就通着，再补一条只是噪声
        union(a, b)
        out.append({"source": a, "target": b, "label": COOC_BRIDGE_LABEL,
                    "kind": "cooc", "weight": count})
    return out


def _build_graph(force: bool = False) -> Dict[str, Any]:
    memos = _fetch_memories()
    if not memos:
        return {"nodes": [], "edges": [], "empty": True, "message": "暂无记忆可供构图"}

    parts: List[Any] = []
    # 优先复用词典里的规范名；词典为空时才回落到上一版图的名字。两条都是为了让
    # 同一批记忆在多次重建中得到同一套实体名——名字一漂，按名字写的归并配置和
    # 前后两次的结构对比就全部失效。
    known: List[str] = _dict_canonical_names()
    if not known:
        cached = _graph_cache() or {}
        known = [str(n.get("label") or "").strip()
                 for n in (cached.get("nodes") or [])
                 if isinstance(n, dict) and str(n.get("label") or "").strip()]
    for start in range(0, len(memos), GRAPH_BATCH_SIZE):
        chunk = memos[start:start + GRAPH_BATCH_SIZE]
        # 把前面批次已抽到的实体名带上，让后一批复用同名而不是另起一套写法
        data = _llm_extract(chunk, known)
        if data is None:
            data = _heuristic_graph(chunk)
        parts.append(data)
        for n in (data.get("nodes") or []) if isinstance(data, dict) else []:
            label = str(n.get("label") or "").strip()
            if label and label not in known:
                known.append(label)

    data = _merge_graph_parts(parts)
    # 先对齐词典（名字层面），再套人工归并配置（语义层面），最后补桥
    data = _apply_entity_dict(data)
    data = _apply_entity_merge(data)
    fell_back = bool(parts) and all(
        isinstance(p, dict) and p.get("fallback") for p in parts
    )

    # 分批把图切成了几块，用同条记忆共现补桥（不覆盖模型给的关系）
    for bridge in _cooc_bridges(data.get("nodes", []), memos, data.get("edges", [])):
        bridge["id"] = "e%d" % len(data["edges"])
        data["edges"].append(bridge)

    # 疑似同物异名：只提示，不替用户合并（见 _merge_candidates 的取舍说明）
    data["merge_candidates"] = _merge_candidates(data.get("nodes", []))

    # 着色 + 尺寸
    for n in data.get("nodes", []):
        n["color"] = CATEGORY_COLORS.get(n.get("category", "其他"), CATEGORY_COLORS["其他"])
        n.setdefault("val", 1)
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    data["built_ts"] = time.time()
    data["memory_count"] = len(memos)
    data["fallback"] = fell_back
    return data


def _current_memory_total() -> Optional[int]:
    """当前记忆总量；后端不可用时返回 None（此时不做过期判断）。"""
    try:
        from matlens_kit.api.mem_api import _exact_count, _get_provider

        return _exact_count(_get_provider())
    except Exception:
        return None


_STALE_PROBE_INTERVAL = 300.0
_stale_probe = {"at": 0.0}


def _cache_is_stale(cached: Dict[str, Any]) -> bool:
    """缓存里的记忆条数和库里的对不上，说明缓存是旧快照，该重建了。

    探针本身要问后端，有代价，所以最多每 5 分钟查一次；拿不到总量时不判过期，
    宁可继续用旧图，也不因为一次探测失败把图清空。
    """
    recorded = cached.get("memory_count")
    if not isinstance(recorded, int):
        return False
    now = time.time()
    if now - _stale_probe["at"] < _STALE_PROBE_INTERVAL:
        return False
    _stale_probe["at"] = now
    total = _current_memory_total()
    if total is None:
        return False
    return total != recorded


_rebuild_state = {"running": False}


def _should_replace(previous: Optional[Dict[str, Any]],
                   candidate: Dict[str, Any]) -> bool:
    """新图能否覆盖旧图。

    抽取降级（LLM 不可用 → 启发式"记忆即节点"）时，产物在结构上是有损的：
    节点变成一句句记忆、边变成同类别的串链。用它覆盖已有的真图，等于把好图
    降级成垃圾，所以只允许在旧图本来就是降级图、或旧图空的时候替换。
    """
    if not candidate.get("nodes"):
        return False
    if candidate.get("fallback") and previous:
        if not previous.get("fallback"):
            return False
    return True


def _kick_rebuild(previous: Optional[Dict[str, Any]] = None) -> None:
    """后台重建图谱，不阻塞当前请求：先返回旧图，下一次请求拿到新图。"""
    if _rebuild_state["running"]:
        return
    _rebuild_state["running"] = True

    def _run() -> None:
        try:
            with _graph_lock:
                g = _build_graph(force=True)
                if not _should_replace(previous, g):
                    return
                _save_cache(g)
        except Exception:
            pass
        finally:
            _rebuild_state["running"] = False

    threading.Thread(target=_run, daemon=True, name="graph-rebuild").start()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
class MergeBody(BaseModel):
    a: str
    b: str
    keep: Optional[str] = None
    why: Optional[str] = None


@_router.post("/merge")
def merge_entities(body: MergeBody) -> Dict[str, Any]:
    """把两个实体合成一个，写进人工归并配置并立即应用到当前缓存图。

    判断权在用户手里：候选只是提示，这里才真正改图。合错了可以删掉配置里对应
    条目再重建一次就恢复，所以它不是不可逆操作。
    """
    a = str(body.a or "").strip()
    b = str(body.b or "").strip()
    if not a or not b or a == b:
        raise HTTPException(status_code=400, detail="需要两个不同的实体名")
    keep = b if str(body.keep or "").strip().lower() == "b" else a
    drop = b if keep == a else a

    groups = _load_entity_merge()
    target = next((g for g in groups if g["canonical"] == keep), None)
    if target is None:
        groups.append({"canonical": keep, "aliases": [drop],
                       "why": body.why or "用户在图上手动合并"})
    else:
        if drop not in target["aliases"]:
            target["aliases"].append(drop)
        if body.why:
            target["why"] = body.why
    _save_entity_merge(groups)

    with _graph_lock:
        cached = _graph_cache()
        if not cached.get("nodes"):
            raise HTTPException(status_code=409, detail="当前没有可合并的图谱")
        data = _apply_entity_merge(cached)
        for n in data.get("nodes") or []:
            n["color"] = CATEGORY_COLORS.get(n.get("category", "其他"),
                                             CATEGORY_COLORS["其他"])
            n.setdefault("val", 1)
        _save_cache(data)

    return {
        "ok": True,
        "merged": data.get("merged_labels"),
        "nodes": len(data.get("nodes") or []),
        "edges": len(data.get("edges") or []),
        "message": "已合并「%s」到「%s」，可删除 ~/.matlens/entity_merge.json 中对应条目撤销" % (drop, keep),
    }


@_router.get("")
def get_graph() -> Dict[str, Any]:
    """返回当前图谱。自动构建开启时：优先缓存，无缓存则即时从记忆构图。
    自动构建关闭时：只返回已有缓存（不重新构图），无缓存则返回空图并带
    auto_build:false 标记——绝不从不记忆触发启发式/LLM 构图。"""
    cached = _graph_cache()
    auto_build_on = _graph_auto_build_enabled()
    if cached.get("nodes"):
        cached.setdefault("fallback", False)
        cached["auto_build"] = auto_build_on
        # 缓存自查：记忆库长了但图还是旧快照时，后台重建，当前请求先返回旧图。
        if auto_build_on and _cache_is_stale(cached):
            _kick_rebuild(cached)
            cached["rebuilding"] = True
        return cached
    if not auto_build_on:
        return {
            "nodes": [],
            "edges": [],
            "empty": True,
            "message": "已关闭记忆图谱自动构建",
            "auto_build": False,
        }
    with _graph_lock:
        g = _build_graph()
        _save_cache(g)
        g["auto_build"] = True
        return g


@_router.post("/extract")
def extract_graph() -> Dict[str, Any]:
    """强制从当前记忆重新抽取图谱。自动构建关闭时拒绝重建，返回明确提示。"""
    if not _graph_auto_build_enabled():
        return {
            "nodes": [],
            "edges": [],
            "empty": True,
            "message": "已关闭记忆图谱自动构建",
            "auto_build": False,
        }
    previous = _graph_cache()
    with _graph_lock:
        g = _build_graph(force=True)
        # 手动触发同样要过这道门：抽取降级时返回结果，但不允许把好图覆盖掉。
        if not _should_replace(previous, g):
            g["skipped"] = True
            g["message"] = "本次抽取降级为启发式结果，已保留原有图谱未覆盖"
            g.setdefault("auto_build", True)
            return g
        _save_cache(g)
        g.setdefault("auto_build", True)
        return g
