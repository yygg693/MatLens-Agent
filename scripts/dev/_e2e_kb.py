# -*- coding: utf-8 -*-
"""知识库重做端到端验证。"""
import os, sys, json, urllib.request
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
def api(p): return json.loads(urllib.request.urlopen("http://127.0.0.1:7896"+p, timeout=30).read())
errs=[]
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_context(viewport={"width":1700,"height":1000}).new_page()
    pg.on("console", lambda m: errs.append(f"[{m.type}] {m.text}") if m.type=="error" and "favicon" not in m.text else None)
    pg.on("pageerror", lambda e: errs.append(f"[pageerror] {e}"))
    pg.goto("http://127.0.0.1:7896/?t=K101", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4500)
    pg.locator('.nav-item[data-page="kb"]').click(); pg.wait_for_timeout(2200)

    print("=== 布局 ===")
    m = pg.evaluate("""()=>{const g=s=>{const e=document.querySelector(s);if(!e)return null;
      const r=e.getBoundingClientRect();return {w:Math.round(r.width),h:Math.round(r.height),y:Math.round(r.y)};};
      return {searchbar:g('.kb-searchbar'), upload:g('#upload-zone'), search:g('#kb-query'),
              tabs:g('.kb-tabs'), tabsN:document.querySelectorAll('.kb-tab').length,
              panes:document.querySelectorAll('.kb-tabpane').length,
              toolbar:g('.kb-toolbar'), filter:g('#doc-filter')};}""")
    print("  检索条 y=", m["searchbar"]["y"], " tab组 y=", m["tabs"]["y"], " 工具条 y=", m["toolbar"]["y"])
    print("  tab 数:", m["tabsN"], " pane 数:", m["panes"], " 筛选框:", bool(m["filter"]))
    print("  上传区高:", m["upload"]["h"], "(原 162)  检索框在上传区上方:", m["search"]["y"] < m["upload"]["y"])

    print("\n=== 文献列表 ===")
    d = api("/api/kb")["kbs"][0]
    print("  文献行数:", pg.locator(".doc-item").count(), " 期望:", d["docs"])
    print("  行内操作:", [x.get_attribute("data-act") for x in pg.locator(".doc-item").first.locator(".d-op").all()])
    pg.locator(".doc-item").first.hover(); pg.wait_for_timeout(400)
    pg.locator(".kb-main").screenshot(path=r"D:/MatLens/_ui_kb_docs.png")

    print("\n=== 检索（score 阈值修正验证）===")
    pg.fill("#kb-query", "LSM-LSCF 晶界电导"); pg.keyboard.press("Enter"); pg.wait_for_timeout(2600)
    r = pg.evaluate("""()=>({pane:document.querySelector('[data-kbpane="results"]').classList.contains('active'),
      hits:document.querySelectorAll('.kb-hit').length,
      note:(document.querySelector('.kb-hit-note')||{}).textContent||'',
      scores:[...document.querySelectorAll('.kb-score')].map(x=>x.textContent),
      badges:document.querySelectorAll('.kb-badge').length,
      danger:[...document.querySelectorAll('.kb-hit *')].filter(e=>getComputedStyle(e).color.includes('239, 68, 68')).length,
      badge:(document.getElementById('kb-hit-n')||{}).textContent});""")
    print("  切到结果页:", r["pane"], " 命中:", r["hits"], " 角标:", repr(r["badge"]))
    print("  score 展示:", r["scores"])
    print("  「最相关」徽标数:", r["badges"], " 红色元素数(应为0):", r["danger"])
    print("  说明:", r["note"][:64])
    pg.locator(".kb-main").screenshot(path=r"D:/MatLens/_ui_kb_results.png")

    print("\n=== 精读抽屉 ===")
    pg.locator('.kb-tab[data-kbtab="docs"]').click(); pg.wait_for_timeout(600)
    pg.locator('.doc-item').first.hover(); pg.wait_for_timeout(400)
    pg.locator('[data-act="read"]').first.click(); pg.wait_for_timeout(2000)
    rd = pg.evaluate("""()=>({open:document.getElementById('kb-read-panel').classList.contains('show'),
      title:(document.getElementById('kb-read-title')||{}).textContent,
      sub:(document.getElementById('kb-read-sub')||{}).textContent,
      chunks:document.querySelectorAll('.kb-chunk').length});""")
    print("  打开:", rd["open"], " 标题:", rd["title"][:38], " 分块数:", rd["chunks"])
    print("  副标题:", rd["sub"][:60])
    pg.locator("#kb-read-panel").screenshot(path=r"D:/MatLens/_ui_kb_reader.png")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(500)
    print("  Esc 关闭:", pg.evaluate("()=>!document.getElementById('kb-read-panel').classList.contains('show')"))

    print("\n=== 添加文献 tab ===")
    pg.locator('.kb-tab[data-kbtab="add"]').click(); pg.wait_for_timeout(600)
    add = pg.evaluate("""()=>({pane:document.querySelector('[data-kbpane="add"]').classList.contains('active'),
      importBtn:!!document.getElementById('btn-kb-import'),
      kbName:(document.getElementById('cur-kb-name')||{}).textContent});""")
    print("  激活:", add["pane"], " import 钮:", add["importBtn"], " 目标库:", add["kbName"])
    pg.locator('[data-pane="add"]').screenshot(path=r"D:/MatLens/_ui_kb_add.png")
    b.close()
print("\nconsole:", [e for e in errs if "ERR_" not in e][:5] or "无")
