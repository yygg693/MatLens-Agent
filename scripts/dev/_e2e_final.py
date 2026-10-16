# -*- coding: utf-8 -*-
"""归档箱（设置内）+ 提炼记忆 最终验证。"""
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
    pg.goto("http://127.0.0.1:7896/?t=E101", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4500)

    print("=== 侧栏（应无归档箱文字/按钮）===")
    print("  会话数:", pg.locator(".session-item").count())
    print("  列表头文案:", repr(pg.evaluate("()=>document.querySelector('.s-group')?.innerText")))
    print("  s-toggle 残留(应为0):", pg.locator(".s-toggle").count())
    print("  归档箱入口钮(图标):", pg.locator("#btn-manage-archive").count()>0)
    print("  每行操作数:", pg.locator('.session-item').first.locator('.s-op').count(),
          [x.get_attribute("data-act") for x in pg.locator('.session-item').first.locator('.s-op').all()])

    print("\n=== 点侧栏图标 → 设置会话面板 ===")
    pg.locator("#btn-manage-archive").click(); pg.wait_for_timeout(2200)
    st = pg.evaluate("""()=>({
      open: document.getElementById('page-settings').classList.contains('open'),
      pane: document.querySelector('[data-pane="sessions"]').classList.contains('active'),
      items: document.querySelectorAll('#archived-list .ar-item').length,
      empty: !!document.querySelector('#archived-list .ar-empty'),
      distill: !!document.getElementById('btn-distill-sessions')})""")
    print("  设置打开:", st["open"], " 会话面板激活:", st["pane"])
    print("  归档条目:", st["items"], " 空态:", st["empty"], " 提炼钮:", st["distill"])
    pg.locator('[data-pane="sessions"]').screenshot(path=r"D:/MatLens/_ui_archbox_final.png")

    print("\n=== 提炼记忆（限最近10条，内容不足时会说明）===")
    pg.locator("#btn-distill-sessions").click()
    tx=""
    for i in range(50):
        pg.wait_for_timeout(2000)
        tx = pg.locator("#distill-btn-tx").inner_text()
        if "提炼中" not in tx: break
    print("  按钮态:", tx)
    print("  日志:", pg.evaluate("()=>document.getElementById('distill-log').innerText.replace(/\\n+/g,' | ')")[:340])
    b.close()
print("\nconsole:", [e for e in errs if "ERR_" not in e][:5] or "无")
