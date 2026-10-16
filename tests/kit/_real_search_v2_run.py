# -*- coding: utf-8 -*-
"""真实网络验证 run_dual_search（含方法学扩充）。"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, r"D:\MatLens")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from matlens_kit.paper import search as S  # noqa: E402

TOPIC = "固态氧化物燃料电池 电解质 GDC 中温固体氧化物燃料电池"
OUT = r"D:\MatLens\tests\kit\_real_search_v2_result.json"
OUT_MD = r"D:\MatLens\tests\kit\_real_search_v2_rendered.md"


def main():
    res = S.run_dual_search(TOPIC, top_k=8, use_llm_rewrite=True)

    # 按 meth 标签分桶
    buckets = {"topic": [], "GDC_SINGLE_CELL": [], "EIS_DRT": [], "HEBB_WAGNER": [], "SPACE_CHARGE": []}
    for r in res["refs"]:
        tag = r.get("meth")
        if tag:
            buckets.setdefault(tag, []).append(r["title"])
        else:
            buckets["topic"].append(r["title"])

    out = {
        "topic": TOPIC,
        "count": res["count"],
        "queries": res["queries"],
        "meth_queries": res["meth_queries"],
        "channels": res["channels"],
        "latency_s": res["latency_s"],
        "local_count": res["local_count"],
        "oa_count": res["oa_count"],
        "buckets_by_method": {k: len(v) for k, v in buckets.items()},
        "refs": [
            {
                "index": r.get("index"),
                "title": r.get("title"),
                "authors": r.get("authors"),
                "year": r.get("year"),
                "source": r.get("source"),
                "doi": r.get("doi"),
                "meth": r.get("meth", ""),
            }
            for r in res["refs"]
        ],
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    rendered = S.render_refs(res["refs"])
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(rendered)

    print("OK", res["count"], "refs", res["channels"], res["latency_s"], "s")
    print("buckets:", {k: len(v) for k, v in buckets.items()})


if __name__ == "__main__":
    main()
