"""Reciprocal Rank Fusion — merging recallers whose scores aren't comparable.

A vector store reports cosine distances; BM25 reports a negative relevance
score; a recency sort reports a timestamp. Averaging them is meaningless.
RRF merges on **rank** instead: every recaller contributes ``1/(k + rank)``
to each document it returns. The result is scale-free, needs no calibration,
and — the property that matters here — treats a document that *both* recallers
like as more relevant than one that only a single recorder found.

``k`` is the usual RRF constant (60 in the original Cormack et al. paper):
it damps the head of each list so a single confident top-1 cannot dominate
the fusion.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

DEFAULT_RRF_K = 60


def rrf_fuse_ids(
    rankings: Sequence[Sequence[str]],
    *,
    k: int = DEFAULT_RRF_K,
) -> List[Tuple[str, float]]:
    """Fuse ranked id lists into one ranking.

    ``rankings`` is a list of rankings, each ordered best-first. The result
    is a list of ``(id, score)`` sorted by descending score.
    """
    scores: Dict[str, float] = {}
    for ranking in rankings or []:
        for rank, doc_id in enumerate(ranking or [], start=1):
            if not doc_id:
                continue
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def rrf_fuse_rows(
    rankings: Sequence[Sequence[Dict[str, Any]]],
    *,
    key: str = "id",
    k: int = DEFAULT_RRF_K,
) -> List[Dict[str, Any]]:
    """Fuse ranked row lists into one ranking of rows.

    The first ranking that mentions a document supplies its payload; the
    fused score is attached as ``rrf_score``. Rows without a usable id are
    dropped — they cannot be fused.
    """
    pool: Dict[str, Dict[str, Any]] = {}
    scores: Dict[str, float] = {}
    for ranking in rankings or []:
        for rank, row in enumerate(ranking or [], start=1):
            if not isinstance(row, dict):
                continue
            doc_id = str(row.get(key) or "")
            if not doc_id:
                continue
            pool.setdefault(doc_id, row)
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    ordered = sorted(
        pool.values(),
        key=lambda row: (-scores.get(str(row.get(key) or ""), 0.0), str(row.get(key))),
    )
    fused: List[Dict[str, Any]] = []
    for row in ordered:
        doc_id = str(row.get(key) or "")
        merged = dict(row)
        merged["rrf_score"] = scores.get(doc_id, 0.0)
        fused.append(merged)
    return fused
