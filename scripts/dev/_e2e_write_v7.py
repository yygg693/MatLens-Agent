# -*- coding: utf-8 -*-
"""跑 write 步并验证「实测数据真正进入正文」（充值后首次真实链路验证）。

与上一轮 _e2e_write_run.py 的区别：这次要等完整生成结束（不截断 SSE），
然后核对实测数据的特征值/标注是否出现在落库正文里。
"""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:7896"
PID = "12eac584bbae4e728870e482e51a6109"


def get_paper():
    with urllib.request.urlopen(f"{BASE}/api/papers/{PID}", timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


p = get_paper()
data = p.get("data") or {}
st = p["stages"]
print("[前置] 阶段状态:", {k: v.get("status") for k, v in st.items()})
print("[前置] data.status =", data.get("status"))
print("[前置] data.notes =", (data.get("notes") or "")[:70])
print("[前置] data.tables =", json.dumps(data.get("tables") or [], ensure_ascii=False)[:220])
print("[前置] write 现有正文长度 =", len(st["write"].get("content") or ""))
print("[前置] outline 长度 =", len(st["outline"].get("content") or ""))
print("[前置] refs 数 =", len((st["search"].get("refs") or [])))

if st["outline"].get("status") != "done":
    raise SystemExit("前置中止：outline 未完成，write 会被引擎拦住")

print("\n[跑] POST /run/write （可能耗时数分钟）…")
t0 = time.time()
req = urllib.request.Request(f"{BASE}/api/papers/{PID}/run/write", method="POST", data=b"")
n_ev = 0
last_err = ""
with urllib.request.urlopen(req, timeout=1800) as r:
    buf = ""
    for raw in r:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        buf += line[5:].strip()
        try:
            ev = json.loads(buf)
        except Exception:
            continue
        buf = ""
        n_ev += 1
        t = ev.get("type")
        if t == "error":
            last_err = (ev.get("data") or {}).get("message", "")
            print(f"[SSE] error: {last_err[:200]}")
            break
        if t == "done":
            print(f"[SSE] done （{time.time()-t0:.0f}s, {n_ev} 事件）")
            break
        if n_ev % 50 == 0:
            print(f"  … {n_ev} 事件 / {time.time()-t0:.0f}s")

if last_err:
    print("\n[结论] 生成失败（正文应被 guard 保住）")
    q = get_paper()
    w = q["stages"]["write"]
    print("  write status =", w.get("status"), " len =", len(w.get("content") or ""))
    print("  正文完好 =", "Calcium co-doping" in (w.get("content") or ""))
    print("  error =", (w.get("error") or "")[:160])
    raise SystemExit(1)

q = get_paper()
w = q["stages"]["write"]
c = w.get("content") or ""
print(f"\n[结果] write status={w.get('status')}  正文长度={len(c)}  ({time.time()-t0:.0f}s)")

# 实测数据特征值 —— 表格里编的值，随便哪个出现都算真消费
print("\n[核对] 实测数据是否进入正文：")
probes = {
    "0.45（900C 实测σ）": "0.45",
    "0.28（850C 实测σ）": "0.28",
    "0.12（800C 实测σ）": "0.12",
    "EIS（测试方法）": "EIS",
    "950（测试温度）": "950",
    "重复 3 次": "重复3次|重复 3 次|three repeat",
    "实测标注": "实测|measured",
}
hit = []
for label, pat in probes.items():
    import re
    ok = bool(re.search(pat, c))
    print(f"   {label:22} {'✅ 命中' if ok else '❌ 未出现'}")
    if ok:
        hit.append(label)

print(f"\n[结论] 命中 {len(hit)}/{len(probes)} 项")
with open(r"D:\MatLens\_e2e_write_v7.md", "w", encoding="utf-8") as f:
    f.write(c)
print("[存档] 新正文已存 _e2e_write_v7.md")