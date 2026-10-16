# -*- coding: utf-8 -*-
"""归档箱（设置→会话）+ 提炼记忆 端到端验证。"""
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
    pg.goto("http://127.0.0.1:7896/?t=D101", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4500)

    print("=== 侧栏：归档箱入口 ===")
    print("  入口钮:", pg.locator('[data-act="open-archive-box"]').count()>0,
          " 文案:", pg.locator(".s-toggle").first.inner_text().replace("\n"," "))
    print("  侧栏无归档视图切换(应为0):", pg.locator('[data-act="toggle-archive"]').count())
    print("  活跃会话数:", pg.locator(".session-item").count())

    print("\n=== 归档一条（侧栏按钮）===")
    before_arch = api("/api/sessions/archived")["count"]
    it = pg.locator(".session-item").first
    it.hover(); pg.wait_for_timeout(500)
    pg.locator('[data-act="archive"]').first.click(); pg.wait_for_timeout(1800)
    after_arch = api("/api/sessions/archived")["count"]
    print(f"  归档箱: {before_arch} → {after_arch}  侧栏条目: {pg.locator('.session-item').count()}")

    print("\n=== 设置 → 会话 面板 ===")
    pg.locator("#btn-settings").click(); pg.wait_for_timeout(1600)
    pg.locator('.stng-nav-item[data-tab="sessions"]').click(); pg.wait_for_timeout(2000)
    m = pg.evaluate("""()=>{
      const box=document.getElementById('archived-list');
      return {paneActive: document.querySelector('[data-pane="sessions"]').classList.contains('active'),
              items: box.querySelectorAll('.ar-item').length,
              empty: !!box.querySelector('.ar-empty'),
              head:(box.querySelector('.ar-head')||{}).innerText||'',
              distillBtn: !!document.getElementById('btn-distill-sessions'),
              ops: box.querySelector('.ar-item')?[...box.querySelectorAll('.ar-op')].map(x=>x.dataset.act):[]};}""")
    print("  面板激活:", m["paneActive"], " 归档条目:", m["items"], " 空态:", m["empty"])
    print("  头部:", m["head"].replace("\n"," "), " 提炼钮:", m["distillBtn"], " 行内操作:", m["ops"])
    pg.locator('[data-pane="sessions"]').screenshot(path=r"D:/MatLens/_ui_archivebox.png")

    print("\n=== 从归档提炼记忆 ===")
    pg.locator("#btn-distill-sessions").click()
    for i in range(50):
        pg.wait_for_timeout(2000)
        vis = pg.evaluate("()=>getComputedStyle(document.getElementById('distill-log')).display")
        tx = pg.locator("#distill-btn-tx").inner_text()
        if "提炼中" not in tx: break
    log = pg.evaluate("()=>document.getElementById('distill-log').innerText")
    print("  按钮态:", tx)
    print("  日志:\n   ", log.replace("\n","\n    ")[:600])
    pg.locator('[data-pane="sessions"]').screenshot(path=r"D:/MatLens/_ui_distill.png")

    print("\n=== 恢复一条 ===")
    n_before = api("/api/sessions/archived")["count"]
    pg.locator('[data-act="restore"]').first.click(); pg.wait_for_timeout(1800)
    print(f"  归档箱: {n_before} → {api('/api/sessions/archived')['count']}")
    b.close()
print("\nconsole:", [e for e in errs if "ERR_" not in e][:5] or "无")
