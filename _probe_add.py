import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
errs=[]
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_context(viewport={"width":1700,"height":1000}).new_page()
    pg.on("console", lambda m: errs.append(f"[{m.type}] {m.text}") if m.type=="error" and "favicon" not in m.text else None)
    pg.on("pageerror", lambda e: errs.append(f"[pageerror] {e}"))
    pg.goto("http://127.0.0.1:7896/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4200)
    btn = pg.locator("#btn-add")
    print("[加号] 存在:", btn.count()>0, "可见:", btn.is_visible() if btn.count() else False)
    print("  尺寸:", btn.evaluate("e=>{const b=e.getBoundingClientRect();return {w:Math.round(b.width),h:Math.round(b.height),x:Math.round(b.x),y:Math.round(b.y)};}") if btn.count() else "-")
    # 是否有 onclick
    has = pg.evaluate("()=>{const e=document.querySelector('#btn-add'); return {onclick: !!e.onclick, id:e.id};}")
    print("  onclick 已绑定:", has)
    btn.click(); pg.wait_for_timeout(1000)
    m = pg.evaluate("""()=>{const e=document.querySelector('#add-menu');
      const c=getComputedStyle(e); const b=e.getBoundingClientRect();
      return {disp:c.display, vis:c.visibility, h:Math.round(b.height), w:Math.round(b.width), y:Math.round(b.y)};}""")
    print("  点击后 add-menu:", m)
    print("  菜单项数:", pg.locator("#add-menu .am-item").count())
    pg.screenshot(path=r"D:/MatLens/_ui_addmenu_test.png")
    b.close()
print("console:", [e for e in errs if "ERR_" not in e][:5] or "无")
