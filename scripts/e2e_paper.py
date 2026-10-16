# -*- coding: utf-8 -*-
"""论文工坊 · 端到端闭环验收（mock LLM runner，绝不真调模型）。

跑通 7 步状态机，断言：
  1. 每步 run_stage 后 db 里 status=="done" 且 content 非空
  2. 前置检查：topic 未 done 时直接 run outline -> ok=False
  3. 重跑覆盖：改 topic 内容后再 run，content 被新 mock 输出覆盖
  4. 错误可恢复：某步 runner 抛异常 -> status=="error"；修正后重跑回到 done
  5. 全程用临时 papers.db，绝不碰 ~/.matlens/papers.db

跑法：
    .\\.venv\\Scripts\\python.exe scripts\\e2e_paper.py
"""
from __future__ import annotations

import os
import sys
import tempfile

# 让脚本从仓库根目录可导入 matlens_kit
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from matlens_kit.paper.engine import PaperEngine, STAGES  # noqa: E402
from matlens_kit.paper import db as PDB  # noqa: E402


# ---------------------------------------------------------------------------
# 临时库重定向：PaperEngine 调 PDB 时不传 db_path，靠模块全局 _PAPER_DB 兜底。
# 这里把它指到临时文件，保证真实 ~/.matlens/papers.db 零写入。
# ---------------------------------------------------------------------------
_tmp_dir = tempfile.mkdtemp(prefix="matlens_e2e_paper_")
TMP_DB = os.path.join(_tmp_dir, "papers_e2e.db")
PDB._PAPER_DB = TMP_DB  # noqa: SLF001 —— 测试期重定向默认库


# ---------------------------------------------------------------------------
# Mock LLM runner：(stage, pid, ctx, emit) -> (content, refs)，确定性假内容
# ---------------------------------------------------------------------------
MOCK_REFS = [
    {"title": "Ionic liquid viscosity prediction via machine learning",
     "authors": "Zhang W, Li H", "year": "2023",
     "source": "OpenAlex·Journal of Chemical Engineering", "doi": "10.1001/jce.2023.001"},
    {"title": "分子描述符在流体物性预测中的应用",
     "authors": "Wang Y", "year": "2022",
     "source": "OpenAlex·化工学报", "doi": ""},
    {"title": "Deep learning for transport properties of liquids",
     "authors": "Chen X, Smith J, Brown A", "year": "2024",
     "source": "OpenAlex·Fluid Phase Equilibria", "doi": "10.1002/fpe.2024.009"},
]

# 可变开关（供覆盖测试 / 错误恢复测试）
_state = {"topic_override": None, "write_raise": False}


def mock_runner(stage: str, pid: str, ctx: dict, emit):
    emit("stream_text", {"text": f"[mock] {stage} 生成中…\n"})

    if stage == "write" and _state["write_raise"]:
        raise RuntimeError("模拟：write 步 LLM 调用崩溃（用于错误恢复验证）")

    if stage == "topic":
        content = _state["topic_override"] or (
            "# 选题设定\n\n本研究聚焦离子液体粘度预测建模，"
            "针对现有分子描述符方法精度不足问题，提出基于机器学习的多尺度预测框架。"
        )
        return content, []

    if stage == "search":
        content = (
            "## 检索策略\n双通道检索（RAG 本地库 + OpenAlex 网络），命中 3 篇核验文献。\n\n"
            "## 文献总览\n关键文献见白名单 [1][2][3]，覆盖粘度预测、分子描述符、输运性质三个方向。"
        )
        return content, MOCK_REFS

    if stage == "outline":
        return (
            "## 大纲\n\n### 引言\n（背景与问题）\n\n"
            "### 方法\n（描述符 + 模型）\n\n### 结果与讨论\n\n### 结论\n\n建议引用 [1][2]。"
        ), []

    if stage == "write":
        return (
            "# 引言\n离子液体因其宽电化学窗口与可设计性受到广泛关注[1]。\n\n"
            "# 方法\n本文采用多尺度分子描述符 [2] 构建粘度预测模型。\n\n"
            "# 结果\n模型在测试集上精度优于传统基团贡献法[1][3]。\n\n"
            "# 结论\n本文验证了机器学习框架对离子液体输运性质预测的有效性。"
        ), []

    if stage == "quality":
        return (
            "## 质量巡检报告\n\n巡检完成：引用均在白名单内，结构完整，评分 95/100。"
        ), []

    if stage == "review":
        return (
            "## 模拟审稿\n\n新颖性 8/10；方法严谨性 7/10；数据与论证 8/10；语言规范 9/10。"
        ), []

    if stage == "export":
        return "## 导出\n成稿已就绪，可导出 md / tex / docx。", []

    return f"[{stage}] 占位内容", []


def db_stage(pid: str, stage: str) -> dict:
    return PDB.get_paper(pid)["stages"][stage]


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)
    print(f"  ✓ {msg}")


def main() -> int:
    print(f"[e2e] 临时 papers.db = {TMP_DB}")
    eng = PaperEngine(runner=mock_runner)

    # 建一个空项目（7 步全 pending）
    p = eng.create("离子液体粘度预测研究", paper_type="research",
                   topic="基于机器学习的离子液体粘度预测")
    pid = p["id"]
    print(f"[e2e] 已建项目 pid={pid[:12]}…")

    # ── 2) 前置检查：topic 还没 done，直接跑 outline 必须失败 ──
    print("[e2e] 断言①：前置检查（topic 未完成时跑 outline 应被拒绝）")
    r = eng.run_stage(pid, "outline", emit=lambda *a: None)
    check(r.get("ok") is False, "topic 未 done 时 run outline 返回 ok=False")
    check(db_stage(pid, "outline")["status"] == "pending", "outline 仍停留在 pending")

    # ── 顺序跑完全部 7 步（先 topic，后其余）──
    print("[e2e] 顺序执行 7 步并断言 done + content 非空")
    for stage in STAGES:
        r = eng.run_stage(pid, stage, emit=lambda *a: None)
        check(r.get("ok") is True, f"{stage} 步 run 返回 ok=True")
        s = db_stage(pid, stage)
        check(s["status"] == "done", f"{stage} 步 db status==done")
        check((s.get("content") or "").strip() != "", f"{stage} 步 content 非空")

    # search 步应落库 3 条 refs（白名单）
    check(len(db_stage(pid, "search").get("refs", [])) == 3, "search 步落库 3 条核验文献")

    # ── 3) 重跑覆盖：改 topic 内容再跑，content 必须被新输出覆盖 ──
    print("[e2e] 断言②：重跑覆盖 topic")
    old = db_stage(pid, "topic")["content"]
    _state["topic_override"] = "选题：离子液体粘度预测（修订版 v2，聚焦深度学习骨架）"
    r = eng.run_stage(pid, "topic", emit=lambda *a: None)
    new = db_stage(pid, "topic")["content"]
    check(r.get("ok") is True, "重跑 topic 返回 ok=True")
    check(new != old, "重跑后 topic content 与旧值不同")
    check("修订版 v2" in new, "topic content 被新 mock 输出覆盖")
    _state["topic_override"] = None

    # ── 4) 错误可恢复：让 write 抛异常 -> status=error；修正后重跑 -> done ──
    print("[e2e] 断言③：错误可恢复（write 崩溃 -> error，修复后重跑 -> done）")
    _state["write_raise"] = True
    r = eng.run_stage(pid, "write", emit=lambda *a: None)
    check(r.get("ok") is False, "write 崩溃时 run 返回 ok=False")
    check(db_stage(pid, "write")["status"] == "error", "write 步 db status==error")
    check("崩溃" in (db_stage(pid, "write").get("error") or ""), "write 步 error 字段记录了异常")

    _state["write_raise"] = False
    r = eng.run_stage(pid, "write", emit=lambda *a: None)
    check(r.get("ok") is True, "修复后重跑 write 返回 ok=True")
    check(db_stage(pid, "write")["status"] == "done", "write 步恢复为 done")
    check((db_stage(pid, "write").get("content") or "").strip() != "", "write 步内容恢复非空")

    # ── 收尾：7 步全 done ──
    final = PDB.get_paper(pid)
    done = sum(1 for s in final["stages"].values() if s.get("status") == "done")
    check(done == len(STAGES), f"最终 {done}/{len(STAGES)} 步全部 done")

    # 顺带验证 enforce_refs 越界检测（正文 [9] 不在 3 条白名单内）
    from matlens_kit.paper.enforce_refs import out_of_range_ids, check_refs_whitelist
    bad = out_of_range_ids("见[1][9]和[2]", 3)
    check(bad == [9], "enforce_refs 识别越界编号 [9]")
    issues = check_refs_whitelist("正文引用 [9][10]", MOCK_REFS)
    check(issues and issues[0]["location"] == "引用越界", "越界写入质检报告「引用越界」条目")

    print("\nE2E PAPER OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
