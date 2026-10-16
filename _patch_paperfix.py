# -*- coding: utf-8 -*-
"""论文工坊 P0+P1 修复（papers_api.py）。幂等。"""
import io

p = r"D:\MatLens\matlens_kit\api\papers_api.py"
s = io.open(p, encoding="utf-8").read()
orig = s

# ── P0 修复 1：search 分支读 run_conversation 返回值 ──
old1 = """            with _PAPER_RUN_LOCK:
                run_conversation_guarded(agent, prompt, paper_sid, _scb)
            content = render_refs(refs) + "\\n\\n" + "".join(texts)
            return content, refs"""
new1 = """            with _PAPER_RUN_LOCK:
                result = run_conversation_guarded(agent, prompt, paper_sid, _scb)
            # 优先用 run_conversation 返回值（stream_callback 在核心链路未接线时兜底）
            final = (result or {}).get("final_response") or "".join(texts) or ""
            content = render_refs(refs) + "\\n\\n" + final
            return content, refs"""
assert old1 in s, "anchor1 missing"
s = s.replace(old1, new1, 1)

# ── P0 修复 2：通用分支读 run_conversation 返回值 ──
old2 = """        with _PAPER_RUN_LOCK:
            run_conversation_guarded(agent, prompt, paper_sid, _cb)
        return "".join(texts), refs_list if stage_ == "search" else []"""
new2 = """        with _PAPER_RUN_LOCK:
            result = run_conversation_guarded(agent, prompt, paper_sid, _cb)
        # 优先用 run_conversation 返回值（stream_callback 在核心链路未接线时兜底）
        final = (result or {}).get("final_response") or "".join(texts) or ""
        return final, refs_list if stage_ == "search" else []"""
assert old2 in s, "anchor2 missing"
s = s.replace(old2, new2, 1)

# ── P0 修复 3：run_conversation_guarded 返回 result ──
old3 = """    with lock:
        if setup is not None:
            setup()
        return agent.run_conversation(message, stream_callback=stream_callback)

    return _runner"""
# 实际在 papers_api.py 里的结构：
old3 = """    with lock:
        if setup is not None:
            setup()
        return agent.run_conversation(message, stream_callback=stream_callback)"""
new3 = """    with lock:
        if setup is not None:
            setup()
        return agent.run_conversation(message, stream_callback=stream_callback)
    return None"""
if old3 in s:
    s = s.replace(old3, new3, 1)
    print("anchor3 applied")
else:
    print("anchor3 already OK (no dangling return)")

# ── P1 修复：save 端点 content 非空 → 标记 done（手动编辑即视为完成该步） ──
old4 = """    s = PDB.save_stage_content(pid, req.stage, req.content, req.refs)
    return {"ok": True, "stage": req.stage, "saved": s}"""
new4 = """    s = PDB.save_stage_content(pid, req.stage, req.content, req.refs)
    # 手动保存内容即视为完成该步（否则前置检查永远卡住，无法推进流程）
    if (req.content or "").strip():
        try:
            PDB.set_stage_status(pid, req.stage, "done", error="")
        except Exception:
            pass
    return {"ok": True, "stage": req.stage, "saved": s}"""
assert old4 in s, "anchor4 missing"
s = s.replace(old4, new4, 1)

io.open(p, "w", encoding="utf-8", newline="").write(s)
print("papers_api.py patched, changed:", orig != s)
