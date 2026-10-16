# -*- coding: utf-8 -*-
"""真实网络验证 run_dual_search。"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, r"D:\MatLens")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from matlens_kit.paper import search as S  # noqa: E402

TOPIC = "固态氧化物燃料电池 电解质 GDC 中温固体氧化物燃料电池"
OUT = r"D:\MatLens\tests\kit\_real_search_result.json"
OUT_MD = r"D:\MatLens\tests\kit\_real_search_rendered.md"


def main():
    # 1) 逐通道诊断
    diag = {}
    t = time.time()
    oa = S.search_openalex(TOPIC, per_page=8, timeout=12.0)
    diag["openalex_count"] = len(oa)
    diag["openalex_first_title"] = oa[0]["title"] if oa else None
    diag["openalex_latency"] = round(time.time() - t, 1)

    t = time.time()
    cr = S.search_crossref(TOPIC, rows=8, timeout=12.0)
    diag["crossref_count"] = len(cr)
    diag["crossref_first_title"] = cr[0]["title"] if cr else None
    diag["crossref_latency"] = round(time.time() - t, 1)

    t = time.time()
    lb = S.search_local_kb(TOPIC, top_k=5)
    diag["local_count"] = len(lb)
    diag["local_latency"] = round(time.time() - t, 1)

    # 2) run_dual_search（真实 LLM 改写）
    res = S.run_dual_search(TOPIC, top_k=8, use_llm_rewrite=True)

    out = {
        "topic": TOPIC,
        "diagnostics": diag,
        "run_dual_search": {
            "count": res["count"],
            "queries": res["queries"],
            "local_count": res["local_count"],
            "oa_count": res["oa_count"],
            "channels": res["channels"],
            "latency_s": res["latency_s"],
            "refs": [
                {
                    "index": r.get("index"),
                    "title": r.get("title"),
                    "authors": r.get("authors"),
                    "year": r.get("year"),
                    "source": r.get("source"),
                    "doi": r.get("doi"),
                }
                for r in res["refs"]
            ],
        },
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    rendered = S.render_refs(res["refs"])
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(rendered)

    print("OK", res["count"], "refs", res["channels"], res["latency_s"], "s")


if __name__ == "__main__":
    main()
