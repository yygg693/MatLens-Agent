# -*- coding: utf-8 -*-
import sqlite3, json, os

out = open(r"D:\MatLens\_inspect_out.txt", "w", encoding="utf-8")
def print(*a):
    out.write(" ".join(str(x) for x in a) + "\n")

db = os.path.expanduser("~/.matlens/papers.db")
c = sqlite3.connect(db)
c.row_factory = sqlite3.Row
r = c.execute("SELECT stages_json FROM papers WHERE title LIKE ?", ("%固态氧化物燃料电池%",)).fetchone()
s = json.loads(r["stages_json"])

search = s.get("search", {})
print("search refs 数量:", len(search.get("refs") or []))
for i, ref in enumerate(search.get("refs") or [], 1):
    print(f"  [{i}] {ref.get('title','')[:60]} | {ref.get('authors','')[:30]} | {ref.get('year','')} | {ref.get('source','')[:40]} | doi={ref.get('doi','')[:40]}")

# 检查 write 正文中的引用标记类型
w = s.get("write", {}).get("content", "")
import re
cites = re.findall(r"\{?\[?[A-Z]-?\d+\]?\}?", w)[:20]
print("\nwrite 引用标记样本:", cites[:20])

# 检查正文里 Table 是否含 ---
tables = [ln for ln in w.split("\n") if "---" in ln]
print("\n含 --- 的行数:", len(tables))
for ln in tables[:5]:
    print(" ", ln[:100])
out.close()
