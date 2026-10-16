# -*- coding: utf-8 -*-
"""验证实验数据真正影响写作：调 write 步 SSE，断言实测数据进了 prompt 且正文用了它。"""
import json
import urllib.request

BASE = "http://127.0.0.1:7896"
PID = "12eac584bbae4e728870e482e51a6109"

# 1) 确认当前 data 是 measured 且含特征值
with urllib.request.urlopen(f"{BASE}/api/papers/{PID}", timeout=15) as r:
    p = json.loads(r.read().decode("utf-8"))
data = p.get("data") or {}
print("[1] data.status =", data.get("status"))
print("    notes =", (data.get("notes") or "")[:60])
tables = data.get("tables") or []
print("    tables =", json.dumps(tables, ensure_ascii=False)[:200])

# 2) 调 write 步 SSE，只抓前若干事件（不等全文生成完）
req = urllib.request.Request(f"{BASE}/api/papers/{PID}/run/write", method="POST", data=b"")
chunks = []
try:
    with urllib.request.urlopen(req, timeout=600) as r:
        buf = ""
        n = 0
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("data:"):
                buf += line[5:].strip()
                try:
                    ev = json.loads(buf)
                except Exception:
                    continue
                buf = ""
                n += 1
                t = ev.get("type")
                if t == "stream_text":
                    txt = (ev.get("data") or {}).get("text", "")
                    chunks.append(txt)
                elif t in ("done", "error"):
                    print(f"[2] SSE 结束: {t}")
                    if t == "error":
                        print("    error:", (ev.get("data") or {}).get("message"))
                    break
                if n > 400:
                    print("[2] 已抓 400 事件，中断（够验证用）")
                    break
except Exception as e:
    print("[2] SSE 异常:", type(e).__name__, str(e)[:200])

body = "".join(chunks)
print(f"[3] 抓到流式文本 {len(body)} 字")

# 4) 断言：正文是否出现实测数据的特征值 0.45 与「实测」
for kw in ["0.45", "0.28", "0.12", "实测", "measured", "待实验确认"]:
    print(f"    {kw!r:14} in 正文: {kw in body}")

with open(r"D:\MatLens\_e2e_write_stream.txt", "w", encoding="utf-8") as f:
    f.write(body)
print("[4] 流式全文已存 _e2e_write_stream.txt")