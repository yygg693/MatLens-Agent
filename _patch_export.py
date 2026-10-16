# -*- coding: utf-8 -*-
"""export.py 补丁：类型显示 + 文件名用标题。幂等。"""
import io

p = r"D:\MatLens\matlens_kit\paper\export.py"
s = io.open(p, encoding="utf-8").read()
orig = s

# 1) import + _safe_filename
old1 = "from matlens_kit.paper.engine import STAGE_LABELS\n\n# 生成/导出顺序（与 STAGES 一致）\n_EXPORT_ORDER = [\"topic\", \"search\", \"outline\", \"write\", \"quality\", \"review\"]"
new1 = "from matlens_kit.paper.engine import STAGE_LABELS, PAPER_TYPES\n\n# 生成/导出顺序（与 STAGES 一致）\n_EXPORT_ORDER = [\"topic\", \"search\", \"outline\", \"write\", \"quality\", \"review\"]\n\n\ndef _safe_filename(p: Dict[str, Any], ext: str) -> str:\n    \"\"\"导出文件名：优先课题标题（过滤非法字符），回退 id。\"\"\"\n    import re\n    name = (p.get(\"title\") or \"\").strip() or p.get(\"id\", \"paper\")\n    name = re.sub(r'[\\\\/:*?\"<>|\\r\\n]', \"_\", name)\n    return f\"{name[:60]}.{ext}\""
assert old1 in s, "anchor1 missing"
s = s.replace(old1, new1, 1)

# 2) 类型行 bug 修复
old2 = """    meta = []
    meta.append(f"- **类型**：{STAGE_LABELS.get('topic', '') and paper_type or paper_type}")"""
new2 = """    meta = []
    meta.append(f"- **类型**：{PAPER_TYPES.get(paper_type, paper_type)}")"""
assert old2 in s, "anchor2 missing"
s = s.replace(old2, new2, 1)

# 3) md 文件名
old3 = '''        return {
            "ok": True,
            "content": export_markdown(p),
            "filename": f"{p.get('id', 'paper')}.md",
            "media_type": "text/markdown; charset=utf-8",
        }'''
new3 = '''        return {
            "ok": True,
            "content": export_markdown(p),
            "filename": _safe_filename(p, "md"),
            "media_type": "text/markdown; charset=utf-8",
        }'''
assert old3 in s, "anchor3 missing"
s = s.replace(old3, new3, 1)

# 4) tex 文件名
old4 = '''        return {
            "ok": True,
            "content": export_latex(p),
            "filename": f"{p.get('id', 'paper')}.tex",
            "media_type": "application/x-tex; charset=utf-8",
        }'''
new4 = '''        return {
            "ok": True,
            "content": export_latex(p),
            "filename": _safe_filename(p, "tex"),
            "media_type": "application/x-tex; charset=utf-8",
        }'''
assert old4 in s, "anchor4 missing"
s = s.replace(old4, new4, 1)

# 5) docx 文件名
old5 = '''        return {
            "ok": True,
            "bytes": data,
            "filename": f"{p.get('id', 'paper')}.docx",
            "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }'''
new5 = '''        return {
            "ok": True,
            "bytes": data,
            "filename": _safe_filename(p, "docx"),
            "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }'''
assert old5 in s, "anchor5 missing"
s = s.replace(old5, new5, 1)

io.open(p, "w", encoding="utf-8", newline="").write(s)
print("export.py patched, changed:", orig != s)
