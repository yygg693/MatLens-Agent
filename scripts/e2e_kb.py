# -*- coding: utf-8 -*-
"""KB 端到端冒烟测试（全程本地哈希嵌入，不调网络 LLM）。

流程：临时目录建 KB → add 一段含 [BMIM][BF4] 粘度文本的 .md →
query "粘度 温度" → 断言返回带 source（来源段落）与 score（相似度）。

用法：
    .\\.venv\\Scripts\\python.exe scripts\\e2e_kb.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# 让项目根可导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from matlens_kit.rag.kb import Embedder, KnowledgeBase  # noqa: E402


def main() -> int:
    # 1) 隔离到临时目录，绝不污染真库 ~/.matlens/knowledge
    tmp_home = Path(tempfile.mkdtemp(prefix="matlens_kb_e2e_"))
    os.environ["MATLENS_HOME"] = str(tmp_home)

    # 2) 本地哈希嵌入降级（空 base_url/api_key → _local_fallback=True）
    embedder = Embedder(base_url="", api_key="", model="")
    assert embedder._local_fallback, "嵌入器未进入本地降级模式（不应联网）"

    # 3) 建一个临时 KB
    kb = KnowledgeBase("e2e_tmp", embedder)
    print(f"[setup] MATLENS_HOME={tmp_home}")
    print(f"[setup] 使用 {'FAISS' if kb.store._use_faiss else 'numpy 降级'} 向量库")

    # 4) 写一段含目标知识点的 .md 文献片段
    doc = tmp_home / "ionic_liquid.md"
    doc.write_text(
        "离子液体 [BMIM][BF4] 作为电解质溶剂被广泛研究。"
        "实验发现离子液体 [BMIM][BF4] 粘度随温度升高而降低，"
        "在 298-353K 范围内温度每升高 10 K 粘度约下降 30%。"
        "采用旋转流变仪在剪切速率 100 s^-1 下测定粘度-温度曲线。"
        "另外，[EMIM][Ac] 的电导率随含水量增加而上升。",
        encoding="utf-8",
    )

    res = kb.add_document(str(doc))
    print(f"[add] {res}")
    assert not res.get("skipped"), f"文档应被导入，却被跳过：{res}"
    assert res.get("chunks", 0) >= 1, "至少应分 1 块"

    # 5) 检索
    hits = kb.query("粘度 温度", top_k=3)
    print(f"[query] 命中 {len(hits)} 条：")
    for i, h in enumerate(hits, 1):
        print(f"  #{i}  source={h.get('source')}  score={h.get('score')}")
        print(f"       text={h.get('text','')[:80]}…")

    # 6) 断言：必须有 source 与 score，且首条命中应含目标知识点
    assert hits, "检索应至少命中 1 条"
    top = hits[0]
    assert "source" in top and top["source"], "结果必须带 source（来源段落）"
    assert "score" in top and isinstance(top["score"], float), "结果必须带 score（相似度分数）"
    assert top["score"] > 0.0, f"相似度分数应 > 0，实际 {top['score']}"
    assert "粘度" in top["text"] and "温度" in top["text"], \
        f"首条命中应包含'粘度/温度'，实际：{top['text'][:100]}"

    print("\nKB E2E OK  ✓")
    print(f"  来源文件 source = {top['source']}")
    print(f"  相似度 score    = {top['score']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
