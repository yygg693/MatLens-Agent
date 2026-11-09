"""语义近重复检测：写入去重与批量合并共用的一套判定。

背景
----
mem0 v3 的 ``add`` 是 ADD-only，只按内容哈希做精确去重。于是同一件事
只要措辞略有不同（"必须避开硝酸盐" / "须避开硝酸盐"），哈希就不同，
会被当成新记忆累积下来。本项目实测 127 条记忆里有 33 条落进 14 个近
重复簇，其中一对完全同义。

判定方式
--------
不引 embedding、不调 LLM：组合三项字符级指标

    0.45 * 二元组 Jaccard + 0.45 * 单字 Jaccard + 0.10 * 长度因子

二元组看措辞、单字看术语集合，两者互补——只看二元组时，语序一变分数
就塌（实测同义重述只有 0.50）；只看单字又容易被"用户/研究"这类高频字
灌成虚高。

阈值是在本项目 127 条真实记忆（8001 个两两组合）上量出来的：

    组别            组合分数 p05   p50    最大
    已知重复对       0.61        0.74    1.00
    无关对           0.07        0.14    0.59

0.70 处切分可捞回 20/23 个真实重复对，7978 个无关对**零**误报。
写入端用 0.72（自动合并，务必不误伤），人工复核端用 0.55（宁多勿少）。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

# 写入端自动合并：宁漏勿错，误合并没有人工兜底
DUP_THRESHOLD = 0.72
# 复核端扫描：宁多勿少，交给人确认
SUSPECT_THRESHOLD = 0.55

# 长度因子参考长度：短句本身信息少，字面重叠天然偏低
_LEN_REF = 30.0

_LEAD_TAG = re.compile(r"^\[[^\]]{1,8}\]")
_STRIP = set(
    " \t\r\n\u3000，。；：、！？·“”\"'（）()【】[]<>《》,.;:!?-—_~"
)

Features = Tuple[set, set, int]


def normalize_text(text: str) -> str:
    """归一化到可比形态：去掉 ``[用户]`` 这类前缀标签、标点与空白。

    先 strip 再匹配前缀——真实数据里标签前常带空格。
    """
    s = str(text or "").strip()
    s = _LEAD_TAG.sub("", s)
    return "".join(ch for ch in s if ch not in _STRIP).lower()


def fingerprint(text: str) -> str:
    """归一化后的指纹；两条指纹相同即视为完全重复。"""
    return normalize_text(text)


def _ngrams(s: str, n: int) -> set:
    if not s:
        return set()
    if len(s) < n:
        return {s}
    return {s[i : i + n] for i in range(len(s) - n + 1)}


def _jac(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def features(text: str) -> Features:
    """预计算一条文本的判定特征，批量比较时避免重复归一化。"""
    s = normalize_text(text)
    return _ngrams(s, 2), _ngrams(s, 1), len(s)


def score_features(fa: Features, fb: Features) -> float:
    b2a, b1a, la = fa
    b2b, b1b, lb = fb
    if not b2a or not b2b:
        # 空文本不参与判定——否则两条空记忆会被判成完全重复
        return 0.0
    if b2a == b2b and b1a == b1b:
        # 归一化后完全一致：直接判满，别让长度因子把分数压到 1.0 以下
        return 1.0
    j2 = _jac(b2a, b2b)
    j1 = _jac(b1a, b1b)
    length_factor = min(1.0, min(la, lb) / _LEN_REF)
    return 0.45 * j2 + 0.45 * j1 + 0.10 * length_factor


def similarity(a: str, b: str) -> float:
    """两段文本的重复判定分数，0.0 - 1.0。"""
    return score_features(features(a), features(b))


def richer_text(a: str, b: str) -> str:
    """两段同义文本里取信息更全的一条（归一化后更长的那个）。"""
    return a if len(normalize_text(a)) >= len(normalize_text(b)) else b


def best_match(
    text: str,
    rows: Sequence[Dict[str, Any]],
    *,
    threshold: float = DUP_THRESHOLD,
    key: str = "memory",
    skip_ids: Optional[set] = None,
) -> Tuple[Optional[Dict[str, Any]], float]:
    """在候选行里找与 ``text`` 最像的一条。

    返回 ``(row, score)``；没有达到阈值时返回 ``(None, 0.0)``。
    """
    skip = skip_ids or set()
    probe = features(text)
    best_row: Optional[Dict[str, Any]] = None
    best_score = 0.0
    for row in rows:
        rid = str(row.get("id") or "")
        if rid and rid in skip:
            continue
        other = features(row.get(key) or row.get("text") or "")
        score = score_features(probe, other)
        if score >= threshold and score > best_score:
            best_row, best_score = row, score
    return best_row, best_score


def group_duplicates(
    items: Sequence[Dict[str, Any]],
    *,
    threshold: float = SUSPECT_THRESHOLD,
    key: str = "memory",
) -> List[Dict[str, Any]]:
    """把近重复的记忆聚成簇（并查集）。

    返回按"簇越大越靠前"排序的列表，每项
    ``{ids, items, score}``，``score`` 是簇内最高相似度。
    """
    n = len(items)
    feats = [features(m.get(key) or m.get("text") or "") for m in items]
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        a, b = find(i), find(j)
        if a != b:
            parent[b] = a

    pair_score: Dict[Tuple[int, int], float] = {}
    for i in range(n):
        for j in range(i + 1, n):
            score = score_features(feats[i], feats[j])
            if score >= threshold:
                union(i, j)
                pair_score[(i, j)] = score

    buckets: Dict[int, List[int]] = {}
    for i in range(n):
        buckets.setdefault(find(i), []).append(i)

    groups: List[Dict[str, Any]] = []
    for root, idxs in buckets.items():
        if len(idxs) < 2:
            continue
        top = 0.0
        for i in idxs:
            for j in idxs:
                if j > i:
                    top = max(top, pair_score.get((i, j), 0.0))
        groups.append(
            {
                "ids": [str(items[i].get("id") or "") for i in idxs],
                "items": [items[i] for i in idxs],
                "score": top,
            }
        )
    groups.sort(key=lambda g: (-len(g["items"]), -g["score"]))
    return groups
