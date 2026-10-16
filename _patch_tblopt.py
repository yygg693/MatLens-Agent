# -*- coding: utf-8 -*-
"""表格宽度优化：由强制拉宽改为内容自适应，格子大小适中。幂等。"""
import io, os

p = r"D:\MatLens\design\prototype\index.html"
s = io.open(p, encoding="utf-8").read()

# 1) 对话流表格：去掉 min-width:72% 强制拉宽 → max-content 内容自适应 + 居中
old1 = ".rf-text table.md-table,.think-body table.md-table{width:auto;min-width:72%;max-width:100%;border-collapse:separate;border-spacing:0;margin:8px 0 12px;font-size:12.5px;line-height:1.6;display:block;overflow-x:auto;border:1px solid var(--ml-card-border);border-radius:10px}"
new1 = ".rf-text table.md-table,.think-body table.md-table{width:max-content;min-width:0;max-width:100%;border-collapse:separate;border-spacing:0;margin:8px auto 12px;font-size:12.5px;line-height:1.6;display:block;overflow-x:auto;border:1px solid var(--ml-card-border);border-radius:10px}"
assert old1 in s, "anchor1 missing"
s = s.replace(old1, new1, 1)

# 2) 带工具栏的表格：width:100% → max-content 内容自适应 + 居中
old2 = ".md-table-wrap table.md-table{margin:0;border:none;width:100%}"
new2 = ".md-table-wrap table.md-table{margin:0 auto;border:none;width:max-content;max-width:100%}"
assert old2 in s, "anchor2 missing"
s = s.replace(old2, new2, 1)

io.open(p, "w", encoding="utf-8", newline="").write(s)
print("index.html table width optimized")

# 清理临时脚本
for f in (r"D:\MatLens\_patch_vyfix.py", r"D:\MatLens\_patch_mem0status.py"):
    if os.path.exists(f):
        os.remove(f)
print("cleaned")
